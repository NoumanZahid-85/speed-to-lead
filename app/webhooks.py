import hashlib
import json
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, EmailStr, ValidationError

from app.repository import LeadRepository

logger = logging.getLogger(__name__)
router = APIRouter()


class LeadPayload(BaseModel):
    name: str
    email: EmailStr
    phone: str | None = None
    company_domain: str | None = None
    message: str | None = None
    source: str = "unknown"


def compute_idempotency_key(payload: LeadPayload, provider_event_id: str | None) -> str:
    if provider_event_id:
        return hashlib.sha256(f"provider:{provider_event_id}".encode()).hexdigest()
    now = datetime.now(timezone.utc)
    bucket = int(now.timestamp() / 300)
    raw = f"{payload.email}|{payload.source}|{bucket}"
    return hashlib.sha256(raw.encode()).hexdigest()


@router.post("/webhook/lead")
async def receive_lead(raw_payload: dict, background_tasks: BackgroundTasks):
    try:
        payload = LeadPayload(**raw_payload)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=e.errors())

    idempotency_key = compute_idempotency_key(
        payload, raw_payload.get("event_id")
    )

    repo = await LeadRepository.get_instance()
    lead_id = await repo.insert_lead(idempotency_key, raw_payload)

    if lead_id is None:
        logger.info(
            "duplicate_webhook",
            extra={"idempotency_key": idempotency_key},
        )
        return {"status": "duplicate_ignored"}

    logger.info(
        "lead_accepted",
        extra={
            "idempotency_key": idempotency_key,
            "lead_id": lead_id,
            "source": payload.source,
        },
    )

    from app.pipeline import run_pipeline

    background_tasks.add_task(run_pipeline, lead_id, idempotency_key)
    return {"status": "accepted", "id": lead_id}
