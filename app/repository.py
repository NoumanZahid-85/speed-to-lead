import json
import logging
from abc import ABC, abstractmethod
from typing import Optional
from datetime import datetime, timezone
import asyncpg
from app.database import get_pool
from app.config import settings

logger = logging.getLogger(__name__)


class LeadRepositoryInterface(ABC):
    @abstractmethod
    async def insert_lead(self, idempotency_key: str, payload: dict) -> Optional[int]:
        pass

    @abstractmethod
    async def get_lead_payload(self, lead_id: int) -> Optional[dict]:
        pass

    @abstractmethod
    async def update_enrichment(self, idempotency_key: str, enrichment_data: dict, status: str):
        pass

    @abstractmethod
    async def update_score(self, idempotency_key: str, score: int, bucket: str, status: str):
        pass

    @abstractmethod
    async def update_status(self, idempotency_key: str, status: str, error: Optional[str] = None):
        pass

    @abstractmethod
    async def update_elapsed(self, idempotency_key: str, elapsed_seconds: float):
        pass

    @abstractmethod
    async def get_stats(self) -> dict:
        pass


class PostgresLeadRepository(LeadRepositoryInterface):
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def insert_lead(self, idempotency_key: str, payload: dict) -> Optional[int]:
        row = await self.pool.fetchrow(
            """
            INSERT INTO leads (idempotency_key, payload, status)
            VALUES ($1, $2::jsonb, 'received'::lead_status)
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING id
            """,
            idempotency_key,
            json.dumps(payload),
        )
        return row["id"] if row else None

    async def get_lead_payload(self, lead_id: int) -> Optional[dict]:
        row = await self.pool.fetchrow(
            "SELECT payload FROM leads WHERE id = $1", lead_id
        )
        if row is None:
            return None
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        return payload

    async def update_enrichment(self, idempotency_key: str, enrichment_data: dict, status: str):
        await self.pool.execute(
            """
            UPDATE leads
            SET enrichment_data = $1::jsonb,
                status = $2::lead_status,
                updated_at = now()
            WHERE idempotency_key = $3
            """,
            json.dumps(enrichment_data),
            status,
            idempotency_key,
        )

    async def update_score(self, idempotency_key: str, score: int, bucket: str, status: str):
        await self.pool.execute(
            """
            UPDATE leads
            SET score = $1, score_bucket = $2, status = $3::lead_status, updated_at = now()
            WHERE idempotency_key = $4
            """,
            score,
            bucket,
            status,
            idempotency_key,
        )

    async def update_status(self, idempotency_key: str, status: str, error: Optional[str] = None):
        if error:
            await self.pool.execute(
                """
                UPDATE leads
                SET status = $1::lead_status, error = $2, updated_at = now()
                WHERE idempotency_key = $3
                """,
                status,
                error,
                idempotency_key,
            )
        else:
            await self.pool.execute(
                """
                UPDATE leads
                SET status = $1::lead_status, updated_at = now()
                WHERE idempotency_key = $2
                """,
                status,
                idempotency_key,
            )

    async def update_elapsed(self, idempotency_key: str, elapsed_seconds: float):
        await self.pool.execute(
            "UPDATE leads SET elapsed_seconds = $1, updated_at = now() WHERE idempotency_key = $2",
            elapsed_seconds,
            idempotency_key,
        )

    async def get_stats(self) -> dict:
        rows = await self.pool.fetch(
            "SELECT status::text, count(*) FROM leads GROUP BY status"
        )
        counts = {r["status"]: r["count"] for r in rows}

        completed = await self.pool.fetchval(
            """
            SELECT avg(elapsed_seconds)
            FROM leads
            WHERE elapsed_seconds IS NOT NULL
              AND status IN ('routed'::lead_status, 'nurture'::lead_status, 'cold'::lead_status)
            """
        )

        oldest_review = await self.pool.fetchrow(
            """
            SELECT idempotency_key, created_at
            FROM leads
            WHERE status IN ('needs_review'::lead_status, 'alert_failed'::lead_status)
            ORDER BY created_at ASC
            LIMIT 1
            """
        )

        return {
            "by_status": counts,
            "avg_elapsed_seconds": round(float(completed), 3) if completed else None,
            "oldest_unresolved": (
                {
                    "idempotency_key": oldest_review["idempotency_key"],
                    "created_at": str(oldest_review["created_at"]),
                }
                if oldest_review
                else None
            ),
        }


class InMemoryLeadRepository(LeadRepositoryInterface):
    _leads = {}
    _idempotency_map = {}
    _id_counter = 1

    async def insert_lead(self, idempotency_key: str, payload: dict) -> Optional[int]:
        if idempotency_key in self._idempotency_map:
            return None
        lead_id = self._id_counter
        self._id_counter += 1
        self._idempotency_map[idempotency_key] = lead_id
        self._leads[lead_id] = {
            "id": lead_id,
            "idempotency_key": idempotency_key,
            "payload": payload,
            "status": "received",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "score": None,
            "score_bucket": None,
            "enrichment_data": None,
            "error": None,
            "elapsed_seconds": None,
        }
        return lead_id

    async def get_lead_payload(self, lead_id: int) -> Optional[dict]:
        lead = self._leads.get(lead_id)
        return lead["payload"] if lead else None

    async def update_enrichment(self, idempotency_key: str, enrichment_data: dict, status: str):
        lead_id = self._idempotency_map.get(idempotency_key)
        if lead_id:
            lead = self._leads[lead_id]
            lead["enrichment_data"] = enrichment_data
            lead["status"] = status
            lead["updated_at"] = datetime.now(timezone.utc)

    async def update_score(self, idempotency_key: str, score: int, bucket: str, status: str):
        lead_id = self._idempotency_map.get(idempotency_key)
        if lead_id:
            lead = self._leads[lead_id]
            lead["score"] = score
            lead["score_bucket"] = bucket
            lead["status"] = status
            lead["updated_at"] = datetime.now(timezone.utc)

    async def update_status(self, idempotency_key: str, status: str, error: Optional[str] = None):
        lead_id = self._idempotency_map.get(idempotency_key)
        if lead_id:
            lead = self._leads[lead_id]
            lead["status"] = status
            if error:
                lead["error"] = error
            lead["updated_at"] = datetime.now(timezone.utc)

    async def update_elapsed(self, idempotency_key: str, elapsed_seconds: float):
        lead_id = self._idempotency_map.get(idempotency_key)
        if lead_id:
            lead = self._leads[lead_id]
            lead["elapsed_seconds"] = elapsed_seconds
            lead["updated_at"] = datetime.now(timezone.utc)

    async def get_stats(self) -> dict:
        counts = {}
        total_elapsed = 0.0
        elapsed_count = 0
        oldest_unresolved = None

        for lead in self._leads.values():
            status = lead["status"]
            counts[status] = counts.get(status, 0) + 1
            if lead["elapsed_seconds"] is not None and status in ("routed", "nurture", "cold"):
                total_elapsed += lead["elapsed_seconds"]
                elapsed_count += 1
            if status in ("needs_review", "alert_failed"):
                if oldest_unresolved is None or lead["created_at"] < oldest_unresolved["created_at"]:
                    oldest_unresolved = lead

        avg_elapsed = total_elapsed / elapsed_count if elapsed_count > 0 else None

        return {
            "by_status": counts,
            "avg_elapsed_seconds": round(avg_elapsed, 3) if avg_elapsed else None,
            "oldest_unresolved": (
                {
                    "idempotency_key": oldest_unresolved["idempotency_key"],
                    "created_at": str(oldest_unresolved["created_at"]),
                }
                if oldest_unresolved
                else None
            ),
        }


_instance: Optional[LeadRepositoryInterface] = None


class LeadRepository:
    @classmethod
    async def get_instance(cls) -> LeadRepositoryInterface:
        global _instance
        if _instance is not None:
            return _instance

        is_placeholder = "host" in settings.database_url or "user:pass" in settings.database_url
        if is_placeholder:
            logger.warning("db_url_is_placeholder_using_in_memory_repository")
            _instance = InMemoryLeadRepository()
            return _instance

        try:
            pool = await get_pool()
            _instance = PostgresLeadRepository(pool)
            return _instance
        except Exception as e:
            logger.error("db_connection_failed_falling_back_to_in_memory", extra={"error": str(e)})
            _instance = InMemoryLeadRepository()
            return _instance
