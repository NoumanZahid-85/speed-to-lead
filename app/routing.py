import asyncio
import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone

import httpx
import resend
from tenacity import retry, stop_after_attempt, wait_exponential_jitter, retry_if_exception_type

from app.scoring import ScoreResult
from app.repository import LeadRepository
from app.config import settings

logger = logging.getLogger(__name__)


class TransientDeliveryError(Exception):
    pass


class NotificationDelivery(ABC):
    @abstractmethod
    async def send_slack_alert(self, lead_payload: dict, score: ScoreResult, elapsed: float):
        pass

    @abstractmethod
    async def send_email(self, lead_payload: dict, score: ScoreResult):
        pass


def _build_slack_blocks(lead_payload: dict, score: ScoreResult, elapsed: float) -> dict:
    """Build a rich Slack Block Kit message for a hot lead alert."""
    name = lead_payload.get("name", "Unknown")
    email = lead_payload.get("email", "—")
    phone = lead_payload.get("phone", "—")
    domain = lead_payload.get("company_domain", "—")
    message = lead_payload.get("message", "")
    source = lead_payload.get("source", "unknown")
    now = datetime.now(timezone.utc).strftime("%b %d, %Y %H:%M UTC")

    reasons_text = "\n".join(f"• {r}" for r in score.reasons) if score.reasons else "No specific signals"
    message_preview = (message[:200] + "…") if len(message) > 200 else message

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"🔥 Hot Lead — {name}",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Name*\n{name}"},
                {"type": "mrkdwn", "text": f"*Email*\n<mailto:{email}|{email}>"},
                {"type": "mrkdwn", "text": f"*Phone*\n{phone}"},
                {"type": "mrkdwn", "text": f"*Company*\n{domain}"},
                {"type": "mrkdwn", "text": f"*Score*\n{score.score}/100 ({score.bucket})"},
                {"type": "mrkdwn", "text": f"*Source*\n{source}"},
            ],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Scoring breakdown*\n{reasons_text}",
            },
        },
    ]

    if message_preview:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Message*\n> {message_preview}",
                },
            }
        )

    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"Processed in {elapsed:.1f}s · {now}",
                }
            ],
        }
    )

    return {"blocks": blocks}


class HttpNotificationDelivery(NotificationDelivery):
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1, max=6),
        retry=retry_if_exception_type(TransientDeliveryError),
        reraise=True,
    )
    async def send_slack_alert(self, lead_payload: dict, score: ScoreResult, elapsed: float):
        webhook_url = settings.slack_webhook_url
        if not webhook_url:
            raise TransientDeliveryError("SLACK_WEBHOOK_URL not configured")
        message_body = _build_slack_blocks(lead_payload, score, elapsed)
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.post(webhook_url, json=message_body)
            if resp.status_code in (429, 500, 502, 503, 504):
                raise TransientDeliveryError(f"Slack returned {resp.status_code}")
            if resp.status_code == 400:
                raise ValueError(f"Slack bad request: {resp.text}")
            resp.raise_for_status()
        except httpx.TimeoutException as e:
            raise TransientDeliveryError(f"Slack timeout: {e}") from e
        except httpx.ConnectError as e:
            raise TransientDeliveryError(f"Slack connection error: {e}") from e

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1, max=6),
        retry=retry_if_exception_type(TransientDeliveryError),
        reraise=True,
    )
    async def send_email(self, lead_payload: dict, score: ScoreResult):
        resend_key = settings.resend_api_key
        if not resend_key:
            raise TransientDeliveryError("RESEND_API_KEY not configured")
        resend.api_key = resend_key
        try:
            await asyncio.to_thread(
                resend.Emails.send,
                {
                    "from": "onboarding@resend.dev",
                    "to": lead_payload.get("email"),
                    "subject": f"Thank you, {lead_payload.get('name')}",
                    "html": (
                        f"<p>Hi {lead_payload.get('name')},</p>"
                        "<p>We received your inquiry and will be in touch soon.</p>"
                    ),
                },
            )
        except resend.exceptions.RateLimitError as e:
            raise TransientDeliveryError(f"Resend rate limited: {e}") from e
        except resend.exceptions.ResendError as e:
            raise ValueError(f"Resend API error: {e}") from e


class ConsoleNotificationDelivery(NotificationDelivery):
    async def send_slack_alert(self, lead_payload: dict, score: ScoreResult, elapsed: float):
        logger.info(
            "slack_alert_console_stub",
            extra={"name": lead_payload.get("name"), "score": score.score},
        )

    async def send_email(self, lead_payload: dict, score: ScoreResult):
        logger.info(
            "email_console_stub",
            extra={"name": lead_payload.get("name"), "email": lead_payload.get("email")},
        )


def get_delivery_service() -> NotificationDelivery:
    if settings.slack_webhook_url or settings.resend_api_key:
        return HttpNotificationDelivery()
    return ConsoleNotificationDelivery()


async def route_lead(
    idempotency_key: str,
    lead_payload: dict,
    score: ScoreResult,
    received_at: float,
):
    repo = await LeadRepository.get_instance()
    delivery = get_delivery_service()
    elapsed = time.monotonic() - received_at

    if score.bucket == "hot":
        try:
            await delivery.send_slack_alert(lead_payload, score, elapsed)
            await repo.update_status(idempotency_key, "routed")
            logger.info(
                "hot_lead_routed_to_slack",
                extra={"idempotency_key": idempotency_key, "score": score.score},
            )
        except Exception as e:
            await repo.update_status(
                idempotency_key,
                "alert_failed",
                f"slack_alert_failed: {type(e).__name__}: {e}",
            )
            logger.error(
                "slack_alert_failed",
                extra={"idempotency_key": idempotency_key, "error": str(e)},
            )
    elif score.bucket == "warm":
        try:
            await delivery.send_email(lead_payload, score)
            await repo.update_status(idempotency_key, "nurture")
        except Exception as e:
            await repo.update_status(
                idempotency_key,
                "alert_failed",
                f"resend_email_failed: {type(e).__name__}: {e}",
            )
            logger.error(
                "resend_email_failed",
                extra={"idempotency_key": idempotency_key, "error": str(e)},
            )
    else:
        await repo.update_status(idempotency_key, "cold")

    logger.info(
        "pipeline_complete",
        extra={
            "idempotency_key": idempotency_key,
            "elapsed_seconds": round(elapsed, 3),
            "bucket": score.bucket,
        },
    )
    if elapsed > 10:
        logger.warning(
            "pipeline_sla_miss",
            extra={
                "idempotency_key": idempotency_key,
                "elapsed_seconds": round(elapsed, 3),
            },
        )