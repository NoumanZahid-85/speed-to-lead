import pytest_asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()


@pytest_asyncio.fixture(scope="session")
async def db_pool():
    pool = await asyncpg.create_pool(
        os.environ["DATABASE_URL"],
        min_size=1,
        max_size=5,
    )
    yield pool
    await pool.close()


@pytest_asyncio.fixture
async def fresh_lead(db_pool):
    await db_pool.execute("DELETE FROM leads")
    return db_pool