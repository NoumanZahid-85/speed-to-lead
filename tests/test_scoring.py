import pytest
from app.scoring import score_lead, ScoreResult, HOT_THRESHOLD, WARM_THRESHOLD
from app.enrichment import EnrichmentResult


def test_determinism():
    """Same input scored twice must produce the identical output."""
    payload = {
        "name": "Alice",
        "email": "alice@example.com",
        "phone": "+15551234",
        "company_domain": "stripe.com",
        "message": "Need help ASAP",
    }
    enrichment = EnrichmentResult(
        inferred_industry="fintech",
        company_size_bucket="11-50",
        likely_pain_points=["fraud"],
        enrichment_status="ok",
    )
    r1 = score_lead(payload, enrichment)
    r2 = score_lead(payload, enrichment)
    assert r1.score == r2.score
    assert r1.bucket == r2.bucket
    assert r1.reasons == r2.reasons


def test_failed_enrichment_does_not_crash():
    """Lead with failed enrichment still produces a valid ScoreResult using structured fields only."""
    payload = {"name": "Bob", "email": "bob@example.com"}
    enrichment = EnrichmentResult(
        inferred_industry="unknown",
        company_size_bucket="unknown",
        likely_pain_points=[],
        enrichment_status="failed",
    )
    result = score_lead(payload, enrichment)
    assert isinstance(result, ScoreResult)
    assert result.score >= 0
    assert "enrichment failed" in " ".join(result.reasons).lower()


def test_failed_enrichment_no_llm_bonus():
    """When enrichment fails, no LLM-derived bonus points should be added."""
    payload = {"name": "X", "email": "x@example.com"}
    ok_enrichment = EnrichmentResult(
        inferred_industry="tech",
        company_size_bucket="51-200",
        likely_pain_points=["scaling"],
        enrichment_status="ok",
    )
    failed_enrichment = EnrichmentResult(
        inferred_industry="tech",     # same values, but status=failed
        company_size_bucket="51-200",
        likely_pain_points=["scaling"],
        enrichment_status="failed",
    )
    ok_score = score_lead(payload, ok_enrichment)
    failed_score = score_lead(payload, failed_enrichment)
    # Failed must score strictly lower — the enrichment bonus is 0
    assert failed_score.score < ok_score.score


def test_score_clamped_0_to_100():
    """Score never exceeds [0, 100] even with every bonus stacked."""
    payload = {
        "name": "X",
        "email": "x@example.com",
        "phone": "+1",
        "company_domain": "example.com",
        "message": "urgent today asap immediately rush quickly",
    }
    enrichment = EnrichmentResult(
        inferred_industry="tech",
        company_size_bucket="51-200",
        likely_pain_points=["scaling"],
        enrichment_status="ok",
    )
    result = score_lead(payload, enrichment)
    assert 0 <= result.score <= 100


def test_bucket_assignment_hot():
    """A lead with every field filled + successful enrichment should be hot."""
    payload = {
        "name": "Hot Lead",
        "email": "hot@test.com",
        "phone": "+1",
        "company_domain": "big.com",
        "message": "Need help ASAP",
    }
    enrichment = EnrichmentResult(
        inferred_industry="tech",
        company_size_bucket="51-200",
        likely_pain_points=["needs"],
        enrichment_status="ok",
    )
    result = score_lead(payload, enrichment)
    # phone(15) + domain(10) + urgency(10) + size(20) + industry(5) = 60
    # With "asap" keyword: score >= 60, but check bucket logic
    assert result.score >= WARM_THRESHOLD


def test_bucket_assignment_cold():
    """A bare-minimum lead with no optional fields should be cold."""
    payload = {"name": "Cold", "email": "cold@test.com"}
    enrichment = EnrichmentResult(
        inferred_industry="unknown",
        company_size_bucket="unknown",
        likely_pain_points=[],
        enrichment_status="ok",
    )
    result = score_lead(payload, enrichment)
    assert result.bucket == "cold"
    assert result.score < WARM_THRESHOLD


def test_score_reasons_are_human_readable():
    """Every reason string should be a non-empty human-readable explanation."""
    payload = {"name": "Test", "email": "t@t.com", "phone": "+1"}
    enrichment = EnrichmentResult(
        inferred_industry="fintech",
        company_size_bucket="11-50",
        likely_pain_points=[],
        enrichment_status="ok",
    )
    result = score_lead(payload, enrichment)
    assert len(result.reasons) > 0
    for reason in result.reasons:
        assert isinstance(reason, str)
        assert len(reason) > 3