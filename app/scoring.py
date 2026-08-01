from pydantic import BaseModel
from app.enrichment import EnrichmentResult

HOT_THRESHOLD = 45
WARM_THRESHOLD = 25

URGENCY_KEYWORDS = {"asap", "urgent", "today", "immediately", "rush", "quickly"}

PHONE_BONUS = 15
SIZE_BUCKET_BONUS = 20
URGENCY_KEYWORD_BONUS = 10
ENRICHMENT_FAILED_PENALTY = 0


class ScoreResult(BaseModel):
    score: int
    bucket: str
    reasons: list[str]


def score_lead(lead_payload: dict, enrichment: EnrichmentResult) -> ScoreResult:
    score = 0
    reasons: list[str] = []

    if lead_payload.get("phone"):
        score += PHONE_BONUS
        reasons.append("provided phone number")

    if lead_payload.get("company_domain"):
        score += 10
        reasons.append("provided company domain")

    message = lead_payload.get("message") or ""
    found_urgency = [
        kw for kw in URGENCY_KEYWORDS if kw in message.lower()
    ]
    if found_urgency:
        score += URGENCY_KEYWORD_BONUS
        reasons.append(f"urgency keywords: {', '.join(found_urgency)}")

    if enrichment.enrichment_status == "ok":
        if enrichment.company_size_bucket not in ("unknown", ""):
            score += SIZE_BUCKET_BONUS
            reasons.append(
                f"company size bucket: {enrichment.company_size_bucket}"
            )
        if enrichment.inferred_industry not in ("unknown", ""):
            score += 5
            reasons.append(
                f"inferred industry: {enrichment.inferred_industry}"
            )
    else:
        reasons.append("enrichment failed, scored from structured fields only")

    score = max(0, min(100, score))

    if score >= HOT_THRESHOLD:
        bucket = "hot"
    elif score >= WARM_THRESHOLD:
        bucket = "warm"
    else:
        bucket = "cold"

    return ScoreResult(score=score, bucket=bucket, reasons=reasons)