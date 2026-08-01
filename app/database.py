import asyncio
import logging

import asyncpg
from app.config import settings

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None

MAX_CONNECT_RETRIES = 3
RETRY_DELAY_SECONDS = 5


async def get_pool() -> asyncpg.Pool:
    """Return the global connection pool, creating it with retries for Neon cold starts."""
    global _pool
    if _pool is not None:
        return _pool
    for attempt in range(1, MAX_CONNECT_RETRIES + 1):
        try:
            _pool = await asyncio.wait_for(
                asyncpg.create_pool(
                    settings.database_url,
                    min_size=0,
                    max_size=5,
                    command_timeout=30,
                ),
                timeout=45,
            )
            logger.info("db_pool_created", extra={"attempt": attempt})
            return _pool
        except (asyncio.TimeoutError, OSError, asyncpg.PostgresError) as e:
            logger.warning(
                "db_pool_connect_retry",
                extra={
                    "attempt": attempt,
                    "max_retries": MAX_CONNECT_RETRIES,
                    "error": f"{type(e).__name__}: {e}",
                },
            )
            if attempt == MAX_CONNECT_RETRIES:
                raise
            await asyncio.sleep(RETRY_DELAY_SECONDS)
    raise RuntimeError("Failed to create database pool")


async def close_pool():
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None