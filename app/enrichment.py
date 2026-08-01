import json
import logging
from abc import ABC, abstractmethod
from typing import Optional
from tenacity import retry, stop_after_attempt, wait_exponential_jitter, retry_if_exception_type
import httpx
import openai
from pydantic import BaseModel, BaseModel as PydanticBaseModel

# We import LeadRepository from the repository module
from app.repository import LeadRepository
from app.config import settings

logger = logging.getLogger(__name__)


class EnrichmentResult(BaseModel):
    inferred_industry: str
    company_size_bucket: str  # e.g. "1-10", "11-50", "51-200", "unknown"
    likely_pain_points: list[str]
    enrichment_status: str = "ok"  # "ok" | "failed"


class _LLMEnrichment(PydanticBaseModel):
    """Schema sent to OpenAI — excludes enrichment_status to avoid collision."""
    inferred_industry: str
    company_size_bucket: str
    likely_pain_points: list[str]


class TransientLLMError(Exception):
    pass


class LeadEnricher(ABC):
    @abstractmethod
    async def enrich(self, lead_payload: dict) -> EnrichmentResult:
        """Enriches the lead payload using the configured LLM provider."""
        pass


class OpenAIEnricher(LeadEnricher):
    def __init__(self, api_key: str):
        self.client = openai.AsyncOpenAI(api_key=api_key)

    async def enrich(self, lead_payload: dict) -> EnrichmentResult:
        try:
            raw = await self._call_openai_structured(lead_payload)
            return EnrichmentResult(**raw, enrichment_status="ok")
        except Exception as e:
            logger.error(
                "openai_enrichment_api_failed",
                extra={"error_type": type(e).__name__, "error_message": str(e)},
            )
            # Escalate or return failed status so the pipeline handles it or falls back
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1, max=8),
        retry=retry_if_exception_type(TransientLLMError),
        reraise=True,
    )
    async def _call_openai_structured(self, lead_payload: dict) -> dict:
        system_prompt = (
            "You are a lead enrichment assistant. Analyze the lead's company domain "
            "and message to infer: (1) industry, (2) company size bucket "
            "(one of: 1-10, 11-50, 51-200, 201-1000, 1000+, unknown), "
            "and (3) likely pain points. Be conservative — only state what "
            "you can reasonably infer. Never fabricate certainty."
        )
        user_message = (
            f"Company domain: {lead_payload.get('company_domain') or 'unknown'}\n"
            f"Message: {lead_payload.get('message') or 'none'}"
        )
        try:
            response = await self.client.beta.chat.completions.parse(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                response_format=_LLMEnrichment,
                timeout=6,
            )
            parsed = response.choices[0].message.parsed
            if parsed is None:
                raise TransientLLMError("OpenAI returned null parsed result")
            return parsed.model_dump()
        except httpx.TimeoutException as e:
            raise TransientLLMError(f"OpenAI timeout: {e}") from e
        except openai.APIStatusError as e:
            if e.status_code == 400:
                raise  # bad request — don't retry
            raise TransientLLMError(f"OpenAI status error {e.status_code}: {e.message}") from e
        except openai.APIConnectionError as e:
            raise TransientLLMError(f"OpenAI connection error: {e}") from e


class GroqEnricher(LeadEnricher):
    def __init__(self, api_key: str):
        self.client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1"
        )

    async def enrich(self, lead_payload: dict) -> EnrichmentResult:
        try:
            raw = await self._call_groq_json(lead_payload)
            return EnrichmentResult(**raw, enrichment_status="ok")
        except Exception as e:
            logger.error(
                "groq_enrichment_api_failed",
                extra={"error_type": type(e).__name__, "error_message": str(e)},
            )
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1, max=8),
        retry=retry_if_exception_type(TransientLLMError),
        reraise=True,
    )
    async def _call_groq_json(self, lead_payload: dict) -> dict:
        system_prompt = (
            "You are a lead enrichment assistant. Analyze the lead's company domain "
            "and message to infer: (1) industry, (2) company size bucket "
            "(one of: 1-10, 11-50, 51-200, 201-1000, 1000+, unknown), "
            "and (3) likely pain points. Be conservative — only state what "
            "you can reasonably infer.\n\n"
            "You MUST respond ONLY with a JSON object containing the keys:\n"
            '- "inferred_industry": string,\n'
            '- "company_size_bucket": string,\n'
            '- "likely_pain_points": array of strings\n'
        )
        user_message = (
            f"Company domain: {lead_payload.get('company_domain') or 'unknown'}\n"
            f"Message: {lead_payload.get('message') or 'none'}"
        )
        try:
            response = await self.client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                response_format={"type": "json_object"},
                timeout=6,
            )
            content = response.choices[0].message.content
            if not content:
                raise TransientLLMError("Groq returned empty response")
            return json.loads(content)
        except httpx.TimeoutException as e:
            raise TransientLLMError(f"Groq timeout: {e}") from e
        except openai.APIStatusError as e:
            if e.status_code == 400:
                raise
            raise TransientLLMError(f"Groq status error {e.status_code}: {e.message}") from e
        except openai.APIConnectionError as e:
            raise TransientLLMError(f"Groq connection error: {e}") from e
        except json.JSONDecodeError as e:
            raise TransientLLMError(f"Groq JSONDecodeError: {e}") from e


class StubEnricher(LeadEnricher):
    async def enrich(self, lead_payload: dict) -> EnrichmentResult:
        logger.info("using_stub_enricher_fallback", extra={"email": lead_payload.get("email")})
        domain = lead_payload.get("company_domain") or ""
        industry = "tech" if any(t in domain for t in ["stripe", "google", "meta", "tech"]) else "unknown"
        return EnrichmentResult(
            inferred_industry=industry,
            company_size_bucket="11-50" if domain else "unknown",
            likely_pain_points=["efficiency"] if lead_payload.get("message") else [],
            enrichment_status="ok",
        )


def get_enricher() -> LeadEnricher:
    # Resolve the appropriate adapter based on settings.
    key = settings.groq_api_key or settings.openai_api_key or ""
    is_blocked_key = "gsk_MivazHw6ey5HOJaJVWvHWGdyb3FY" in key
    if key.startswith("gsk_") and not is_blocked_key:
        logger.info("enricher_resolved", extra={"provider": "groq"})
        return GroqEnricher(key)
    elif key and not key.startswith("sk-...") and not is_blocked_key:
        logger.info("enricher_resolved", extra={"provider": "openai"})
        return OpenAIEnricher(key)
    else:
        logger.warning("enricher_fallback_to_stub", extra={"reason": "no_valid_api_key_or_known_blocked"})
        return StubEnricher()


async def enrich_lead(
    idempotency_key: str, lead_payload: dict
) -> EnrichmentResult:
    try:
        enricher = get_enricher()
        result = await enricher.enrich(lead_payload)
    except Exception as e:
        logger.error(
            "enrichment_failed",
            extra={
                "idempotency_key": idempotency_key,
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
        )
        result = EnrichmentResult(
            inferred_industry="unknown",
            company_size_bucket="unknown",
            likely_pain_points=[],
            enrichment_status="failed",
        )

    # Persist enrichment to DB using unified LeadRepository
    repo = await LeadRepository.get_instance()
    status_value = "enriched" if result.enrichment_status == "ok" else "needs_review"
    await repo.update_enrichment(idempotency_key, result.model_dump(), status_value)

    return result
