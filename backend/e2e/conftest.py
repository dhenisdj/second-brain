"""E2E test fixtures — shared across all scenario files."""

import os
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("LLM_PROVIDER", "openai")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-fake-key")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from app.main import app
from app.database import Base, get_db


SAMPLE_MANUAL_ENTRIES = [
    {
        "timestamp": "2026-04-03T09:00:00",
        "title": "团队站会",
        "content": "讨论了 Q2 OKR 进展，分配了数据分析任务",
        "duration_minutes": 30,
    },
    {
        "timestamp": "2026-04-03T10:00:00",
        "title": "阅读 Transformer 论文",
        "content": "阅读 Attention Is All You Need，重点理解 self-attention 机制",
        "duration_minutes": 60,
    },
    {
        "timestamp": "2026-04-03T12:00:00",
        "title": "午餐散步",
        "content": "和同事在公司附近散步",
        "duration_minutes": 45,
    },
]

SAMPLE_CHROME_HISTORY = [
    {
        "url": "https://arxiv.org/abs/1706.03762",
        "title": "Attention Is All You Need",
        "visit_time": "2026-04-03T10:15:00",
        "visit_duration_seconds": 1800,
    },
    {
        "url": "https://github.com/facebook/react",
        "title": "GitHub - facebook/react",
        "visit_time": "2026-04-03T14:00:00",
        "visit_duration_seconds": 900,
    },
]


@pytest_asyncio.fixture
async def client():
    """Provide an AsyncClient with a fresh in-memory DB for each test."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
