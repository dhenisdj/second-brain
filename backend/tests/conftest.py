"""Shared fixtures for all test modules."""

import os
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("LLM_PROVIDER", "openai")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-fake-key")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from app.main import app
from app.database import Base, get_db, get_session_factory, set_session_factory
from app.services.job_executor import shutdown_job_executor
import app.models as _models  # noqa: F401


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_engine):
    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    original_session_factory = get_session_factory()

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    set_session_factory(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await shutdown_job_executor()
    app.dependency_overrides.clear()
    set_session_factory(original_session_factory)


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
