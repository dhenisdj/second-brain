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
