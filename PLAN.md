# Speed-to-Lead AI Router & Enrichment Pipeline

An event-driven system that takes an inbound lead (from any web form/webhook source), enriches it with an LLM, scores it deterministically, and routes it to Slack (hot leads) or email nurture (warm/cold leads) — end-to-end in under 10 seconds. Built as a resellable, single-tenant deliverable for freelance/agency clients, on a genuinely free-tier stack.

## Problem & Success Criteria

**Problem:** Leads that sit unattended for even 30 minutes convert at a fraction of the rate of leads contacted within 5 minutes. Manual triage, scoring, and routing can't hit that window. Businesses want this automated but most freelancers can't build a system that survives real-world failure modes (duplicate webhooks, API outages, malformed data) — they build demos that work once, on the happy path, in front of the client, and then quietly drop leads in production.

**Success criteria:**
- A lead submitted through the demo form is enriched, scored, and routed to the correct channel (Slack for hot, email for warm/cold) in under 10 seconds, measured end-to-end and logged.
- The same webhook payload delivered twice (simulating a provider retry) produces exactly one processed lead, not two.
- Killing the OpenAI API key or the Slack webhook URL mid-run does not crash the service or silently lose the lead — the lead lands in a visible "needs manual review" state with a logged reason.
- The whole stack runs on $0/month (Render free web service + Neon free Postgres + OpenAI pay-as-you-go + free Slack + Resend free tier), deployed at a public URL, deployable from a fresh machine using only this plan.

**Explicit non-goals (v1):**
- No real Meta/Google Lead Ads integration (App Review overhead deliberately avoided — the webhook contract is generic and swappable later).
- No multi-tenant SaaS (auth, per-client billing, tenant isolation) — this is a single-tenant deploy-per-client model.
- No multi-day nurture drip sequence engine — v1 tags lead status and sends one templated email for warm/cold; the sequence engine is a documented future phase.
- No WhatsApp integration in v1 (same App-Review-overhead problem as Meta Ads) — noted as an optional Phase 7+ stretch adapter.
- No Celery/Redis distributed worker — deliberately replaced with in-process async, see Tech Stack Decision.

## Constraints (locked in during grilling)

| Constraint | Value |
|---|---|
| Scale/users | Single-tenant portfolio/resell project; demo traffic (tens of test leads), not high volume |
| Deployment target | Render free web service (accepts cold-start sleep after 15 min idle) |
| Budget | $0/month hosting; OpenAI usage billed pay-as-you-go (demo-scale, negligible) |
| Timeline | 3-4 weeks |
| Team | Solo, advanced/comfortable with Python, FastAPI, Docker, and LangGraph |
| Data/compliance | Lead PII (name, email, phone) — no formal regulatory scope, but treated as sensitive: no PII in logs beyond a hashed/truncated identifier, no third-party analytics on lead content |

## Research Summary

- **Speed-to-lead is real and measurable**: 2026 industry benchmarks consistently show 5-minute response vs. 30-minute response producing multiples-higher qualification rates — this is the metric the whole system is built to serve, and it's the thing to log and prove, not just assume.
- **LangGraph is the 2026 production standard** for stateful multi-agent orchestration (explicit graph state, conditional branching, resumable checkpoints) — chosen over CrewAI/AutoGen for this reason.
- **The single highest-leverage failure mode in this exact class of system is webhook non-idempotency.** Every provider (and every load balancer/proxy in front of your service) retries on timeout or 5xx. If the handler isn't idempotent, retries create duplicate leads, duplicate Slack pings, and duplicate emails — this is designed against from Phase 1, not bolted on later.
- **LLMs are the wrong tool for the actual scoring decision**: research on production classification systems is consistent that non-deterministic, expensive LLM calls should not be the source of truth for a score used in automated routing. The converged pattern is deterministic rules/lightweight-ML for the score, LLM reasoning only for qualitative enrichment (inferring pain points, drafting outreach copy).
- **Free-tier hosting reality in 2026 rules out Celery/Redis**: background workers are a paid feature on every major PaaS (~$7+/mo), and Render's free Postgres is deleted after 30 days. This pushes the architecture toward in-process async work and Neon (persistent free Postgres, scale-to-zero, no expiry) instead of the "textbook" distributed-queue design.
- **Webhook timeout is the most common cause of duplicate processing in production**: senders retry on timeout (typically 5-30s), so the handler must acknowledge fast and do real work in the background — not synchronously inside the request/response cycle.

## Tech Stack Decision

**Backend framework:** FastAPI (async)
- Rejected: Flask — no native async, would need extra work to avoid blocking the event loop during LLM/HTTP calls.
- Rejected: Django — far more framework than this project needs; slower to iterate solo.
- Why this one: native `async`/`await` lets the webhook handler ack immediately and hand off work to a background task without blocking, which is core to hitting the timeout-avoidance requirement from research.

**Orchestration:** LangGraph
- Rejected: CrewAI — role-based crews are less explicit about state and error paths than LangGraph's graph model; harder to build a "route to manual review on failure" edge cleanly.
- Rejected: plain sequential Python function calls (no framework) — would work for v1 logic, but loses the resumable-state/checkpoint pattern that matters for surviving a mid-pipeline crash, and doesn't demonstrate the multi-agent orchestration skill the portfolio piece is meant to showcase.
- Why this one: explicit graph nodes/edges let every node have its own error-handling edge (to a "needs_review" terminal node) instead of one big try/except around everything, and its checkpoint model means a crashed run can be inspected/resumed rather than silently vanishing.

**LLM:** OpenAI API, structured outputs (JSON schema / function calling) via Pydantic
- Rejected: unstructured prompt + regex/string parsing — fragile, and exactly the "inconsistent output format" failure mode research flagged as a top production issue.
- Why this one: your choice, and structured output enforcement means a malformed LLM response is a validation error you can catch and fall back on, not a silent bad value flowing into the scorer.

**Scoring:** Deterministic weighted-rule function (pure Python, no external calls)
- Rejected: LLM-based scoring — non-deterministic (same lead could score differently run to run), ~100-1000x the cost per call of a rule evaluation, and much harder to unit test or explain to a client ("why did my lead get this score?").
- Rejected: trained ML classifier (logistic regression/gradient boosting) — legitimate production upgrade path, but needs labeled historical data you don't have yet; noted as a natural v2 once real client data accumulates.
- Why this one: fully deterministic, free, instant, unit-testable, and explainable — exactly what an automated routing decision should be built on.

**Async/background work:** FastAPI `BackgroundTasks` + `asyncio`, no Celery/Redis
- Rejected: Celery + Redis — the "textbook" pattern from initial research, but requires a dedicated worker process that costs $7+/mo on every real free-tier-eligible host, directly violating the budget constraint.
- Why this one: at this traffic scale (a single freelance client's inbound leads, not thousands/sec), in-process async work is a legitimate, defensible pattern — and the queue logic is isolated behind a small interface so swapping in real Celery/Redis later (once a client's volume justifies the $7/mo) is a documented follow-on phase, not a rewrite.

**Database:** Neon Postgres (serverless, free tier)
- Rejected: Render Postgres — free tier is deleted after 30 days, unacceptable for a portfolio piece meant to stay live.
- Rejected: Supabase — free projects pause after 7 days of inactivity (workable, but Neon's scale-to-zero has no such hard pause and needs no auth/storage bundle this project doesn't use).
- Why this one: genuinely persistent free tier, connection-string-only (no BaaS lock-in), and scale-to-zero matches a low-traffic demo without ever deleting data.

**Notifications:** Slack incoming webhook (hot leads) + Resend (warm/cold email)
- Rejected: WhatsApp Business API / Meta channels — same App-Review/business-verification overhead deliberately avoided for the lead-intake side.
- Rejected: SendGrid — killed its permanent free tier in 2025; Resend's free tier (3,000/mo, 100/day) is the current best free option.
- Why this one: both are a five-minute setup with no approval process, matching the "start from zero accounts" constraint.

**Hosting:** Render free web service
- Rejected: Railway/Fly.io — neither has a genuine ongoing free tier for compute in 2026 (trial credits only).
- Why this one: the only option that stays deployed indefinitely at $0, with the accepted tradeoff of a 15-minute-idle cold-start sleep.

## Architecture Overview

```
[Demo lead form / any webhook source]
        |
        v
POST /webhook/lead  (FastAPI, sync handler)
  - validate payload (Pydantic)
  - compute idempotency key
  - INSERT ... ON CONFLICT DO NOTHING into `leads` (status=received)
  - if already existed: return 200 immediately, do nothing else
  - if new: schedule background task, return 200 immediately  <-- ack fast, avoid sender timeout/retry
        |
        v  (background, async)
LangGraph pipeline (in-process):
  [Enrichment Node] --(success)--> [Scoring Node] --(success)--> [Routing Node] --> done
       |(failure after retries)          |(failure)                    |(failure after retries)
       v                                 v                              v
  [Needs-Review Node] <-------------------------------------------------
        |
        v
  leads.status = 'needs_review', reason logged, nothing silently dropped

Routing Node:
  score >= HOT_THRESHOLD   -> Slack incoming webhook (retry w/ backoff on 429/5xx)
  score >= WARM_THRESHOLD  -> Resend templated email + leads.status='nurture'
  else                     -> leads.status='cold' (logged, no outbound action)
  any outbound failure after retries -> leads.status='alert_failed', never deleted, visible in stats dashboard for manual follow-up
```

Every external call (OpenAI, Slack, Resend) goes through the same pattern: hard timeout → tenacity retry with exponential backoff + jitter → on final failure, write a safe fallback state and continue the pipeline rather than raising an unhandled exception. Every write to `leads` includes a correlation ID (the idempotency key) in structured logs, so a 2 AM failure can be traced end-to-end from one log line.

## Resilience Principles (applied in every phase below)

1. **Idempotency first.** Every webhook delivery is deduplicated at the database layer (unique constraint), not just in application logic — a race between two near-simultaneous retries must still only produce one row.
2. **Ack fast, work in background.** The webhook handler never does LLM calls, Slack calls, or email calls synchronously — it only validates and persists, then returns 200 immediately. This is the single biggest lever against sender-side retry storms.
3. **Every external call has: a timeout, a bounded retry with backoff+jitter, and a defined fallback.** No external call is allowed to hang indefinitely or crash the process on failure.
4. **Nothing is silently dropped.** A lead that fails enrichment, scoring, or routing lands in an explicit terminal state (`needs_review` or `alert_failed`) that's visible in the stats dashboard — never just missing.
5. **Structured logging with a correlation ID** (the idempotency key) on every log line touching a lead, so any failure can be traced across all pipeline stages after the fact.
6. **Pure functions where it matters.** The scorer takes no external dependencies and is unit-tested for determinism — same input, same output, always, at 2 AM or any other time.

## Phases

---

### Phase 1: Idempotent Webhook Ingestion

**Depends on:** None (starting point)
**Goal:** A publicly reachable FastAPI endpoint that accepts a generic lead webhook payload, validates it, and stores it exactly once in Neon Postgres — even under duplicate delivery.

**Tasks:**
1. Provision a Neon project (free tier) and get the connection string.
2. Create `leads` table: `id`, `idempotency_key` (unique, not null), `payload` (JSONB), `status` (enum: received/processing/enriched/scored/routed/needs_review/alert_failed/cold/nurture), `created_at`, `updated_at`.
3. Build the FastAPI app skeleton with an async DB connection pool (e.g. `asyncpg` or SQLAlchemy async engine).
4. Implement `POST /webhook/lead`: parse+validate with Pydantic (require at minimum name/email; reject with 400 on missing required fields — this is a client error, not a retry-worthy failure), compute an idempotency key (use the source's event ID if present, otherwise hash of email+form-source+rounded-timestamp), `INSERT ... ON CONFLICT (idempotency_key) DO NOTHING`, return 200 immediately either way.
5. Add structured logging (JSON lines) with the idempotency key on every request.

**Starter code:**

```python
# app/webhooks.py
# Why this approach: the handler does ONLY validation + a single idempotent insert,
# then returns immediately. This is deliberate — research shows sender-side timeouts
# (5-30s) are the most common cause of duplicate webhook delivery in production.
# Keeping this handler fast and synchronous-feeling avoids ever triggering that retry
# path in the first place; the background pipeline is wired in Phase 4.

import hashlib
import json
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, EmailStr, ValidationError

router = APIRouter()

class LeadPayload(BaseModel):
    name: str
    email: EmailStr
    phone: str | None = None
    company_domain: str | None = None
    message: str | None = None
    source: str = "unknown"
    # TODO: decide which fields are truly required vs optional for your generic
    # contract. Learn: Pydantic model validation — https://docs.pydantic.dev/latest/concepts/models/

def compute_idempotency_key(payload: LeadPayload, provider_event_id: str | None) -> str:
    # TODO: if provider_event_id is present (e.g. a real webhook's event ID), use it directly.
    # Otherwise fall back to a hash of stable fields, rounded to a coarse time bucket
    # (e.g. nearest 5 minutes) so a genuine accidental double-submit within that window
    # is still deduped, but a legitimate second inquiry days later is not.
    # Hint: hashlib.sha256(f"{payload.email}|{payload.source}|{bucket}".encode()).hexdigest()
    raise NotImplementedError

@router.post("/webhook/lead")
async def receive_lead(raw_payload: dict, background_tasks: BackgroundTasks):
    try:
        payload = LeadPayload(**raw_payload)
    except ValidationError as e:
        # Malformed payload is a client error — do NOT retry-trigger, respond 400.
        raise HTTPException(status_code=400, detail=e.errors())

    idempotency_key = compute_idempotency_key(payload, raw_payload.get("event_id"))

    # TODO: run the idempotent insert against Neon:
    #   INSERT INTO leads (idempotency_key, payload, status)
    #   VALUES ($1, $2, 'received')
    #   ON CONFLICT (idempotency_key) DO NOTHING
    #   RETURNING id;
    # If no row is returned, this is a duplicate delivery — log it and return 200 without
    # scheduling any further work.
    # Learn: Postgres upsert / ON CONFLICT — https://www.postgresql.org/docs/current/sql-insert.html#SQL-ON-CONFLICT
    inserted_id = None  # TODO: replace with real insert result

    if inserted_id is None:
        # TODO: structured log: {"event": "duplicate_webhook", "idempotency_key": idempotency_key}
        return {"status": "duplicate_ignored"}

    # TODO (Phase 4 will fill this in): background_tasks.add_task(run_pipeline, inserted_id)
    return {"status": "accepted", "id": inserted_id}
```

**Definition of Done (verify before moving on):**
1. Run: `curl -X POST http://localhost:8000/webhook/lead -H "Content-Type: application/json" -d '{"name":"Test Lead","email":"test@example.com","source":"demo_form"}'` twice in a row with the identical body.
2. Expected result: first call returns `{"status":"accepted","id":...}`; second identical call returns `{"status":"duplicate_ignored"}`. Querying `SELECT count(*) FROM leads WHERE idempotency_key = '<key>'` returns exactly `1`.
3. If a second row appears: check that the unique constraint actually exists on `idempotency_key` in the migration, and that the insert uses `ON CONFLICT` rather than a plain `INSERT`. Fix, rerun both curl calls, recheck the count — repeat until it's genuinely `1`.

**Watch out for:** malformed JSON or missing required fields should return `400`, not `500` — a crash here looks identical to a real outage to the sender and will trigger unnecessary retries. Also watch for using the raw request body as the idempotency key (rejected pattern from research) — re-serialization/whitespace differences break this; use stable extracted fields instead.

---

### Phase 2: Enrichment Agent (OpenAI, structured output)

**Depends on:** Phase 1
**Goal:** A standalone function that takes a stored lead and returns validated, structured enrichment data (inferred industry, company size bucket, likely pain points) from OpenAI — and degrades gracefully instead of crashing when OpenAI is unavailable or returns something unexpected.

**Tasks:**
1. Define the enrichment output schema as a Pydantic model.
2. Write `enrich_lead(lead) -> EnrichmentResult` using OpenAI's structured output / JSON schema mode so the response is validated at the API layer, not just hoped-for.
3. Wrap the OpenAI call with `tenacity` — a hard timeout, max 3 retries, exponential backoff with jitter, retrying only on transient errors (timeouts, 429, 5xx) and never on a 400 (bad request — retrying won't fix that).
4. On final failure after retries, return a clearly-marked fallback `EnrichmentResult` (e.g. `enrichment_status="failed"`, generic defaults) rather than raising — the pipeline must be able to continue to scoring with degraded-but-present data.
5. Update `leads.status` to `enriched` (or `enrichment_failed`, still allowed to proceed) and store the raw enrichment JSON.

**Starter code:**

```python
# app/enrichment.py
# Why this approach: structured outputs mean a malformed LLM response becomes a
# schema validation error we can catch, not silent bad data flowing into scoring.
# The tenacity wrapper is what keeps a transient OpenAI blip from becoming a crashed
# pipeline at 2 AM — and the fallback path means "OpenAI is down" degrades the lead's
# enrichment quality, it does not stop the lead from being scored and routed at all.

from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential_jitter, retry_if_exception_type
import httpx

class EnrichmentResult(BaseModel):
    inferred_industry: str
    company_size_bucket: str  # e.g. "1-10", "11-50", "51-200", "unknown"
    likely_pain_points: list[str]
    enrichment_status: str = "ok"  # "ok" | "failed"

class TransientLLMError(Exception):
    pass

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=1, max=8),
    retry=retry_if_exception_type(TransientLLMError),
    reraise=True,
)
async def _call_openai_structured(lead_payload: dict) -> dict:
    # TODO: call the OpenAI Chat Completions API with response_format set to your
    # JSON schema (matching EnrichmentResult), a short hard timeout (e.g. 6s), and
    # a system prompt instructing it to infer industry/size/pain-points from the
    # lead's company_domain/message fields only — no fabricated certainty.
    # On httpx.TimeoutException or a 429/5xx status, raise TransientLLMError so
    # tenacity retries it. On a 400 (bad request), let that exception propagate
    # WITHOUT retrying — retrying a malformed request just wastes the retry budget.
    # Learn: OpenAI structured outputs — https://platform.openai.com/docs/guides/structured-outputs
    raise NotImplementedError

async def enrich_lead(lead_payload: dict) -> EnrichmentResult:
    try:
        raw = await _call_openai_structured(lead_payload)
        return EnrichmentResult(**raw, enrichment_status="ok")
    except Exception as e:
        # TODO: structured log the failure with the lead's idempotency key and
        # the exception type/message — this is exactly what you'll grep for at 2 AM.
        return EnrichmentResult(
            inferred_industry="unknown",
            company_size_bucket="unknown",
            likely_pain_points=[],
            enrichment_status="failed",
        )
```

**Definition of Done (verify before moving on):**
1. Run enrichment against a real stored lead with a valid OpenAI key: `python -c "import asyncio; from app.enrichment import enrich_lead; print(asyncio.run(enrich_lead({'company_domain':'stripe.com','message':'need help with fraud detection'})))"`.
2. Expected result: a valid `EnrichmentResult` with `enrichment_status="ok"` and plausible values (industry roughly "fintech/payments", non-empty pain points list).
3. Now break it deliberately: set `OPENAI_API_KEY` to an invalid value and rerun the same command. Expected result: the function still returns a value (does not raise), with `enrichment_status="failed"` and generic defaults — not a stack trace. If it raises instead, the fallback `except` block isn't actually catching the real exception type OpenAI's SDK throws; check the SDK's exception hierarchy and fix, then rerun until it degrades cleanly.

**Watch out for:** retrying on a 400 (malformed request) wastes your whole retry budget on something retries can never fix — make sure only transient errors (timeout/429/5xx) trigger the tenacity retry path. Also watch for the LLM returning technically-valid-JSON-but-semantically-empty output (e.g. all fields `"unknown"`) — that's not a bug to catch here, but worth flagging in later phases' scoring logic so it doesn't silently inflate/deflate a score.

---

### Phase 3: Deterministic Scoring Agent

**Depends on:** Phase 1, Phase 2 (consumes its output shape, but is independently testable with fake enrichment data)
**Goal:** A pure, dependency-free function that takes a lead + its enrichment result and returns a numeric score (0-100) and a status bucket (`hot`/`warm`/`cold`) — fully deterministic and unit-testable.

**Tasks:**
1. Define the scoring rubric as explicit weighted rules (e.g. has phone number: +15, company size bucket 11-50 or 51-200: +20, message contains urgency keywords: +10, enrichment_status == "failed": cap score contribution from that field at 0, never let a failure inflate the score).
2. Implement `score_lead(lead_payload, enrichment: EnrichmentResult) -> ScoreResult` as a pure function — no I/O, no randomness, no external calls.
3. Define `HOT_THRESHOLD` and `WARM_THRESHOLD` as named constants (not magic numbers) so a client conversation about "what counts as hot" maps directly to a config value.
4. Write unit tests: same input twice must produce the identical score; a lead with `enrichment_status="failed"` must still score using only structured fields, never crash or return `None`.

**Starter code:**

```python
# app/scoring.py
# Why this approach: this function must NEVER call an external API — that's what
# makes it fast, free, deterministic, and trivially explainable to a client ("your
# lead scored 72 because X, Y, Z"). Keeping it a pure function also means it's the
# easiest thing in the whole system to unit-test exhaustively.

from pydantic import BaseModel
from app.enrichment import EnrichmentResult

HOT_THRESHOLD = 70
WARM_THRESHOLD = 40

class ScoreResult(BaseModel):
    score: int  # 0-100
    bucket: str  # "hot" | "warm" | "cold"
    reasons: list[str]  # human-readable, for the client-facing dashboard

URGENCY_KEYWORDS = {"asap", "urgent", "today", "immediately"}

def score_lead(lead_payload: dict, enrichment: EnrichmentResult) -> ScoreResult:
    score = 0
    reasons = []

    # TODO: add structured-field rules first (these are always trustworthy —
    # they came directly from the lead, not an LLM inference).
    # e.g. if lead_payload.get("phone"): score += 15; reasons.append("provided phone number")
    # Hint: keep every rule + its point value + its reason string together so the
    # rubric stays readable and the dashboard can show "why" per lead.

    # TODO: add enrichment-based rules, but ONLY if enrichment.enrichment_status == "ok".
    # If enrichment failed, these rules must contribute exactly 0 — never guess.
    # Learn/hint: this is the key edge case from research — a failed LLM call must
    # degrade the score's confidence, never silently bias it in either direction.

    score = max(0, min(100, score))  # TODO: apply after all rules are summed

    if score >= HOT_THRESHOLD:
        bucket = "hot"
    elif score >= WARM_THRESHOLD:
        bucket = "warm"
    else:
        bucket = "cold"

    return ScoreResult(score=score, bucket=bucket, reasons=reasons)
```

**Definition of Done (verify before moving on):**
1. Run: `pytest tests/test_scoring.py -v` after writing at least these test cases: (a) identical input scored twice yields identical output, (b) a lead with `enrichment_status="failed"` still returns a valid `ScoreResult` using only structured-field rules, (c) score is always clamped within 0-100 even with an extreme/contrived input.
2. Expected result: all tests pass, `0` failures.
3. If a test fails on non-determinism: check for any use of `datetime.now()`, `random`, or a dict iteration order dependency inside the scoring function — remove it. Fix, rerun `pytest`, repeat until determinism holds for real, not just on the first run.

**Watch out for:** the single most important edge case here is a failed enrichment silently becoming a 0 (unfairly penalizing a lead) or accidentally contributing full points via a bad default (unfairly inflating a lead) — write the test for this specific case before moving on, not just the happy path.

---

### Phase 4: LangGraph Pipeline Wiring

**Depends on:** Phase 1, Phase 2, Phase 3
**Goal:** Wire enrichment → scoring → (routing stub) into a single LangGraph graph with explicit error-handling edges, so a failure at any node lands the lead in a visible `needs_review` state instead of crashing the background task.

**Tasks:**
1. Define the graph state (a `TypedDict` or Pydantic model carrying the lead payload, enrichment result, score result, and status).
2. Build nodes: `enrichment_node`, `scoring_node`, `needs_review_node` (terminal), and a routing stub node (real routing logic comes in Phase 5).
3. Wire conditional edges: `enrichment_node` always proceeds to `scoring_node` (Phase 2's fallback already guarantees a valid result even on failure) — but add a hard try/except around the whole node so a completely unexpected exception (not just the anticipated OpenAI failure) still routes to `needs_review_node` rather than crashing the async task.
4. Add a Postgres-backed LangGraph checkpointer (or, if that's too heavy for v1, persist state to the `leads` row after every node) so a crash mid-pipeline leaves an inspectable trail, not silence.
5. Wire this graph into `BackgroundTasks` from Phase 1's webhook handler.

**Starter code:**

```python
# app/pipeline.py
# Why this approach: LangGraph's explicit node/edge model means every node gets its
# own failure path to a shared needs_review terminal node — this is what prevents
# one bad lead (or one transient bug) from crashing the whole background task and
# silently losing the lead. Persisting state after each node (rather than only at
# the end) means a real crash still leaves a row you can inspect and manually retry.

from langgraph.graph import StateGraph, END
from typing import TypedDict, Optional
from app.enrichment import enrich_lead, EnrichmentResult
from app.scoring import score_lead, ScoreResult

class PipelineState(TypedDict):
    idempotency_key: str
    lead_payload: dict
    enrichment: Optional[dict]
    score: Optional[dict]
    error: Optional[str]

async def enrichment_node(state: PipelineState) -> PipelineState:
    # TODO: call enrich_lead(state["lead_payload"]). Because Phase 2's function
    # already never raises (it has its own internal fallback), this node's try/except
    # is a safety net for anything UNANTICIPATED (bug, out-of-memory, etc.) —
    # not the primary error path. Persist state to the `leads` row here (status='enriched'
    # or 'enrichment_failed') before returning.
    # Learn: LangGraph node functions — https://langchain-ai.github.io/langgraph/concepts/low_level/#nodes
    raise NotImplementedError

async def scoring_node(state: PipelineState) -> PipelineState:
    # TODO: call score_lead(...). This is a pure function so failure here should be
    # rare/impossible — but still wrap it, because "should be impossible" and "at 2 AM,
    # actually impossible" are different claims.
    raise NotImplementedError

async def needs_review_node(state: PipelineState) -> PipelineState:
    # TODO: persist leads.status = 'needs_review', leads.error = state["error"].
    # This node must be trivially reliable — it's the last line of defense, so keep
    # it to a single simple DB write, no external calls that could themselves fail.
    raise NotImplementedError

def build_graph():
    graph = StateGraph(PipelineState)
    graph.add_node("enrichment", enrichment_node)
    graph.add_node("scoring", scoring_node)
    graph.add_node("needs_review", needs_review_node)
    graph.set_entry_point("enrichment")
    # TODO: add conditional edges — on success continue forward, on any exception
    # captured in state["error"] route to "needs_review" instead of raising further.
    # Hint: use add_conditional_edges with a routing function that inspects state["error"].
    # graph.add_edge("scoring", END)  # routing node replaces this in Phase 5
    return graph.compile()
```

**Definition of Done (verify before moving on):**
1. Run the graph end-to-end against a real stored lead from Phase 1 with a valid OpenAI key. Expected result: `leads.status` progresses through `received` → `enriched` → `scored`, and the final state has both a valid `enrichment` and `score`.
2. Now deliberately break it: set an invalid OpenAI key AND inject a bug (e.g. temporarily make `scoring_node` raise unconditionally) and rerun on a fresh lead. Expected result: `leads.status` ends at `needs_review` with a non-null `error` field — the background task does not crash the FastAPI process (verify the server is still responding to other requests immediately after).
3. If the process crashes instead of reaching `needs_review`: the conditional edge routing isn't catching the exception before it propagates out of the node — wrap the node body in try/except and set `state["error"]` instead of letting it raise. Fix, rerun both the happy-path and broken-path tests, repeat until both hold.

**Watch out for:** the temptation to wrap the *entire graph invocation* in one big try/except instead of per-node — that would catch the crash, but you'd lose the information about *which* node failed and *why*, which is exactly what you need at 2 AM. Keep per-node error capture even though it's more code.

---

### Phase 5: Routing, Notifications & Latency Verification

**Depends on:** Phase 1, Phase 2, Phase 3, Phase 4
**Goal:** Replace the routing stub with real Slack/Resend delivery, with retry+fallback on outbound failures, and prove the full pipeline hits the sub-10-second target.

**Tasks:**
1. Implement `routing_node`: `score.bucket == "hot"` → Slack incoming webhook; `"warm"`/`"cold"` → Resend templated email + `leads.status` update; no bucket ever results in zero action taken (cold leads still get a DB status, even if no email fires — decide and document whichever you prefer).
2. Wrap both Slack and Resend calls with the same timeout+retry+backoff pattern from Phase 2. On final failure, set `leads.status = 'alert_failed'` with the error logged — **never** let a hot lead silently vanish because Slack was down for a minute.
3. Add end-to-end latency instrumentation: timestamp at webhook receipt, timestamp at routing completion, log the delta, and alert (log a warning) if it exceeds 10 seconds.
4. Add a lightweight retry-queue behavior for `alert_failed` leads: a simple periodic check (e.g. on each new webhook request, opportunistically re-attempt any `alert_failed` leads older than N minutes) — no separate scheduler process needed given the free-tier constraint.

**Starter code:**

```python
# app/routing.py
# Why this approach: the retry+fallback pattern is identical in shape to Phase 2's
# enrichment call — this consistency matters, because it means there's exactly one
# pattern to get right and reuse, not three slightly different ones to debug separately.
# The core invariant: a hot lead's Slack alert failing must NEVER look the same as
# "no alert was needed" — it must be a distinct, visible, re-attemptable state.

import time
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential_jitter, retry_if_exception_type
from app.scoring import ScoreResult, HOT_THRESHOLD, WARM_THRESHOLD

class TransientDeliveryError(Exception):
    pass

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=1, max=6),
    retry=retry_if_exception_type(TransientDeliveryError),
    reraise=True,
)
async def _send_slack_alert(lead_payload: dict, score: ScoreResult):
    # TODO: POST to the Slack incoming webhook URL (from env var) with a short timeout
    # (e.g. 5s). Treat httpx timeout / 429 / 5xx as TransientDeliveryError (retry);
    # treat a 400 (e.g. malformed webhook payload) as a real bug — let it raise
    # without retrying, since retrying won't fix a malformed message.
    # Learn: Slack incoming webhooks — https://api.slack.com/messaging/webhooks
    raise NotImplementedError

async def route_lead(idempotency_key: str, lead_payload: dict, score: ScoreResult, received_at: float):
    if score.bucket == "hot":
        try:
            await _send_slack_alert(lead_payload, score)
            # TODO: leads.status = 'routed'
        except Exception as e:
            # TODO: leads.status = 'alert_failed', log error + idempotency_key.
            # This is the case that must be visible on the stats dashboard (Phase 6) —
            # a hot lead with a failed alert is the single worst silent-failure outcome
            # this whole project exists to prevent.
            pass
    elif score.bucket == "warm":
        # TODO: send via Resend, same retry+fallback pattern, leads.status = 'nurture'
        pass
    else:
        # TODO: leads.status = 'cold' — deliberate no-op action, but still a real,
        # visible status, not just "row exists with no clear state".
        pass

    elapsed = time.monotonic() - received_at
    # TODO: structured log {"event": "pipeline_complete", "idempotency_key": idempotency_key,
    # "elapsed_seconds": elapsed, "bucket": score.bucket}
    # If elapsed > 10: log a warning-level entry specifically flagging the SLA miss.
```

**Definition of Done (verify before moving on):**
1. Submit a lead through the full pipeline (webhook → enrichment → scoring → routing) with real Slack/Resend credentials configured, scored as `hot`. Expected result: a message appears in the configured Slack channel, and logs show `pipeline_complete` with `elapsed_seconds < 10`.
2. Now set the Slack webhook URL to an invalid one and resubmit a new hot-scoring test lead. Expected result: `leads.status = 'alert_failed'` after the retries exhaust, the process doesn't crash, and the failure is visible via a direct DB query (`SELECT * FROM leads WHERE status='alert_failed'`).
3. If step 2 instead shows the lead stuck at `routed` or missing entirely: the exception from the failed Slack call is being swallowed somewhere without updating status — check that the `except` block in `route_lead` actually persists `alert_failed` rather than just logging and moving on silently. Fix, rerun, repeat until the failure is genuinely visible in the database, not just the logs.

**Watch out for:** measuring latency only on the happy path — also measure it on the `enrichment_failed`/fallback path, since that's a slower call pattern (full retry backoff before falling back) and is exactly the scenario most likely to blow the 10-second budget in practice.

---

### Phase 6: Demo Form, Deployment & Stats Dashboard

**Depends on:** Phase 1, Phase 2, Phase 3, Phase 4, Phase 5
**Goal:** A publicly deployed, end-to-end working system: a demo lead-capture form, deployed on Render, backed by Neon, with a simple dashboard showing lead counts by status (including `needs_review`/`alert_failed`, so failures are visible, not buried).

**Tasks:**
1. Build a minimal static HTML/JS form (name, email, phone, message) that POSTs directly to `/webhook/lead` — this is what you'll screen-record for the portfolio piece.
2. Write the Render deployment config (`render.yaml` or dashboard setup): web service pointing at this repo, environment variables for `DATABASE_URL` (Neon), `OPENAI_API_KEY`, `SLACK_WEBHOOK_URL`, `RESEND_API_KEY`.
3. Add a `/stats` endpoint (or a tiny server-rendered page) showing: total leads, counts per status bucket, count of `needs_review` + `alert_failed` (prominently — this is the "did anything break" view), and average end-to-end latency from the logs/DB.
4. Add a Neon connection-retry wrapper: since Neon scales to zero, the first query after idle time may need to wait for compute to resume — handle this with a connection-level retry rather than letting the first request after idle fail outright.
5. Document the cold-start behavior (both Render's request sleep and Neon's compute resume) plainly in the README, along with the $7/mo Render Starter upgrade path for a real paying client who needs to eliminate it.

**Starter code:**

```python
# app/stats.py
# Why this approach: the dashboard's entire purpose is to make failure visible.
# A demo that only shows "12 leads processed successfully" is misleading — the
# real proof this system is production-grade is that it also shows "here are the
# 2 that failed and why," because that's the thing a client will actually ask about
# once real leads start flowing.

from fastapi import APIRouter

router = APIRouter()

@router.get("/stats")
async def get_stats():
    # TODO: query leads grouped by status, e.g.:
    #   SELECT status, count(*) FROM leads GROUP BY status;
    # and separately compute average elapsed_seconds for completed leads
    # (requires either a dedicated `elapsed_seconds` column populated in Phase 5,
    # or parsing it back out of structured logs — storing it as a column is simpler
    # and recommended).
    # Learn: this is a good place to also surface the OLDEST unresolved
    # needs_review/alert_failed lead's age, since that's the number that answers
    # "is anything currently stuck."
    raise NotImplementedError
```

**Definition of Done (verify before moving on):**
1. Run: deploy to Render, then from a browser (not curl, to simulate a real user) submit a lead through the public demo form URL.
2. Expected result: within 10 seconds, the lead appears in Slack (if scored hot) or triggers an email (warm/cold), and `GET https://<your-app>.onrender.com/stats` shows the updated counts including this lead's bucket.
3. Cold-start check: wait 20+ minutes without traffic, then submit another lead. Expected result: the request may take 30-60s longer due to Render's wake-up (and possibly Neon's compute resume) but must still complete correctly — it should not error out or silently drop the lead. If it does fail on cold start: check that any DB client timeout is generous enough to survive Neon's resume latency, and that Render's health check isn't killing the request before it wakes. Fix, redeploy, retest the cold-start path specifically — don't just retest warm.

**Watch out for:** testing exclusively on a warm instance during development and never actually validating the cold-start path before considering this "done" — the cold path is the one most likely to surprise you (and a client) in real usage, precisely because it's the hardest one to remember to test.

---

## Splitting into issues

Each phase above is written to be copy-pasted as a standalone issue/ticket. When starting implementation:
1. Copy one "### Phase N" section as the issue body.
2. Title it `[Phase N] [Name]`.
3. Note the dependency line so your tracker sequences them correctly.
4. Work phase by phase, verifying the Definition of Done — including the deliberately-broken-path checks, not just the happy path — before opening the next issue.

## Alternatives Considered

**Whole-project alternative: n8n/low-code orchestration instead of custom Python.** Seriously considered, since n8n gives retries, queueing, and observability as platform features "for free" — genuinely less code to write and maintain. Rejected for this specific project because (a) it doesn't showcase the multi-agent LangGraph orchestration skill that makes this portfolio piece valuable for AI-engineering freelance work specifically, and (b) full code ownership is more resellable/customizable per client than a visual workflow tied to an n8n instance. If reselling this to a client who explicitly wants their ops team to edit the workflow visually without touching code, n8n becomes the better call — worth revisiting per-client, not a universal rejection.

**Whole-project alternative: Celery + Redis distributed task queue**, as in the original project brief. Rejected outright for v1 due to the free-tier budget constraint (background workers cost $7+/mo on every viable host), but the routing/enrichment logic is intentionally isolated behind plain async functions so migrating to a real Celery-based worker later — once a paying client's volume justifies it — is a swap-in, not a rewrite.
