import json
import logging
import time
from typing import Optional
from langgraph.graph import StateGraph, END

from app.repository import LeadRepository
from app.enrichment import enrich_lead, EnrichmentResult
from app.scoring import score_lead, ScoreResult

logger = logging.getLogger(__name__)


class PipelineState(dict):
    idempotency_key: str
    lead_payload: dict
    enrichment: Optional[dict]
    score: Optional[dict]
    error: Optional[str]
    received_at: float


async def enrichment_node(state: PipelineState) -> PipelineState:
    try:
        result = await enrich_lead(
            state["idempotency_key"], state["lead_payload"]
        )
        state["enrichment"] = result.model_dump()
    except Exception as e:
        state["error"] = f"enrichment_node: {type(e).__name__}: {e}"
    return state


async def scoring_node(state: PipelineState) -> PipelineState:
    try:
        enrichment_data = state.get("enrichment") or {}
        enrichment = EnrichmentResult(**enrichment_data)
        result = score_lead(state["lead_payload"], enrichment)
        state["score"] = result.model_dump()

        # Persist score to DB using LeadRepository
        repo = await LeadRepository.get_instance()
        await repo.update_score(
            state["idempotency_key"],
            result.score,
            result.bucket,
            "scored",
        )
    except Exception as e:
        state["error"] = f"scoring_node: {type(e).__name__}: {e}"
    return state


async def routing_node(state: PipelineState) -> PipelineState:
    try:
        from app.routing import route_lead
        score_data = state.get("score") or {}
        score = ScoreResult(**score_data)
        await route_lead(
            state["idempotency_key"],
            state["lead_payload"],
            score,
            state["received_at"],
        )
    except Exception as e:
        state["error"] = f"routing_node: {type(e).__name__}: {e}"
    return state


async def needs_review_node(state: PipelineState) -> PipelineState:
    try:
        repo = await LeadRepository.get_instance()
        await repo.update_status(
            state["idempotency_key"],
            "needs_review",
            state.get("error", "unknown failure"),
        )
    except Exception as e:
        # Last line of defense — just log, never raise from here
        logger.critical(
            "needs_review_node_failed",
            extra={
                "idempotency_key": state.get("idempotency_key"),
                "error": str(e),
            },
        )
    return state


def route_after_enrichment(state: PipelineState) -> str:
    if state.get("error"):
        return "needs_review"
    return "scoring"


def route_after_scoring(state: PipelineState) -> str:
    if state.get("error"):
        return "needs_review"
    return "routing"


def route_after_routing(state: PipelineState) -> str:
    if state.get("error"):
        return "needs_review"
    return "__end__"


_checkpointer = None
graph = None


def set_checkpointer(checkpointer):
    global _checkpointer, graph
    _checkpointer = checkpointer
    graph = None


def get_graph():
    global graph
    if graph is None:
        g = StateGraph(PipelineState)
        g.add_node("enrichment", enrichment_node)
        g.add_node("scoring", scoring_node)
        g.add_node("routing", routing_node)
        g.add_node("needs_review", needs_review_node)
        g.set_entry_point("enrichment")
        g.add_conditional_edges(
            "enrichment",
            route_after_enrichment,
            {"scoring": "scoring", "needs_review": "needs_review"},
        )
        g.add_conditional_edges(
            "scoring",
            route_after_scoring,
            {"routing": "routing", "needs_review": "needs_review"},
        )
        g.add_conditional_edges(
            "routing",
            route_after_routing,
            {"__end__": END, "needs_review": "needs_review"},
        )
        g.add_edge("needs_review", END)
        graph = g.compile(checkpointer=_checkpointer)
    return graph


async def run_pipeline(lead_id: int, idempotency_key: str):
    received_at = time.monotonic()
    repo = await LeadRepository.get_instance()
    lead_payload = await repo.get_lead_payload(lead_id)

    if lead_payload is None:
        logger.error(
            "pipeline_lead_not_found",
            extra={"lead_id": lead_id, "idempotency_key": idempotency_key},
        )
        return

    state = PipelineState(
        idempotency_key=idempotency_key,
        lead_payload=lead_payload,
        enrichment=None,
        score=None,
        error=None,
        received_at=received_at,
    )

    g = get_graph()
    try:
        config = {"configurable": {"thread_id": idempotency_key}}
        result = await g.ainvoke(state, config=config)
        elapsed = time.monotonic() - received_at
        logger.info(
            "pipeline_complete",
            extra={
                "idempotency_key": idempotency_key,
                "elapsed_seconds": round(elapsed, 3),
                "bucket": (result.get("score") or {}).get("bucket", "unknown"),
            },
        )
        await repo.update_elapsed(idempotency_key, elapsed)
    except Exception as e:
        logger.error(
            "pipeline_unhandled_error",
            extra={
                "idempotency_key": idempotency_key,
                "error": f"{type(e).__name__}: {e}",
            },
        )
        try:
            await repo.update_status(
                idempotency_key,
                "needs_review",
                f"unhandled_pipeline_error: {type(e).__name__}: {e}",
            )
        except Exception:
            logger.critical(
                "pipeline_fallback_db_write_failed",
                extra={"idempotency_key": idempotency_key},
            )