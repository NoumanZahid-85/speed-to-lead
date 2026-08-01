import pytest
from app.enrichment import get_enricher, EnrichmentResult
from app.routing import get_delivery_service, ConsoleNotificationDelivery, _build_slack_blocks
from app.scoring import ScoreResult


@pytest.mark.asyncio
async def test_enricher_resolution():
    enricher = get_enricher()
    assert hasattr(enricher, "enrich")


@pytest.mark.asyncio
async def test_stub_enricher_returns_val():
    enricher = get_enricher()  # Will resolve to StubEnricher on blocked key
    result = await enricher.enrich({"company_domain": "google.com", "message": "Need support ASAP"})
    assert isinstance(result, EnrichmentResult)
    assert result.inferred_industry == "tech"
    assert result.company_size_bucket == "11-50"
    assert "efficiency" in result.likely_pain_points


@pytest.mark.asyncio
async def test_console_delivery():
    delivery = ConsoleNotificationDelivery()
    payload = {"name": "Charlie", "email": "charlie@example.com"}
    score = ScoreResult(score=80, bucket="hot", reasons=["provided phone number"])
    # Simply ensure they run without throwing exceptions
    await delivery.send_slack_alert(payload, score, 0.45)
    await delivery.send_email(payload, score)


def test_slack_block_builder():
    payload = {
        "name": "Jane Doe",
        "email": "jane@example.com",
        "phone": "+1 555-1234",
        "company_domain": "example.com",
        "message": "We need help migrating ASAP",
        "source": "manual_trigger"
    }
    score = ScoreResult(
        score=65,
        bucket="hot",
        reasons=["provided phone number", "provided company domain", "urgency keywords: asap"]
    )
    blocks_payload = _build_slack_blocks(payload, score, elapsed=1.25)
    
    assert "blocks" in blocks_payload
    blocks = blocks_payload["blocks"]
    assert len(blocks) >= 4
    
    # Check header
    assert blocks[0]["type"] == "header"
    assert "Jane Doe" in blocks[0]["text"]["text"]
    
    # Check fields
    fields = blocks[1]["fields"]
    assert any("Jane Doe" in f["text"] for f in fields)
    assert any("jane@example.com" in f["text"] for f in fields)
    assert any("65/100" in f["text"] for f in fields)
    
    # Check reasons
    reasons_section = blocks[3]
    assert reasons_section["type"] == "section"
    assert "provided phone number" in reasons_section["text"]["text"]
    
    # Check context/footer
    context_section = blocks[-1]
    assert context_section["type"] == "context"
    assert "1.2s" in context_section["elements"][0]["text"]
