from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.dependencies import authenticate_request
from app.db.base import Base
from app.main import create_app
from app.services.authorization import TenantContext, get_tenant_context
from app.services.rate_limits import DeterministicRateLimiter
from app.settings import Settings


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def session_factory(
    tmp_path: Path,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+asyncpg://unused:unused@localhost/unused",
        redis_url="redis://:unused@localhost:6379/0",
        object_storage_endpoint="http://localhost:9000",
        object_storage_access_key="unused",
        object_storage_secret_key="unused",
        object_storage_bucket="unused",
        oidc_issuer="https://identity.example.test/realms/visualops",
        oidc_audience="visualops-api",
        oidc_jwks_url="https://identity.example.test/jwks",
    )


@pytest.fixture
def successful_probes() -> dict[str, Callable[[], Awaitable[None]]]:
    async def successful_probe() -> None:
        return None

    return {
        "postgres": successful_probe,
        "redis": successful_probe,
        "object_storage": successful_probe,
    }


@pytest.fixture
async def api_client(
    session_factory: async_sessionmaker[AsyncSession],
    test_settings: Settings,
    successful_probes: dict[str, Callable[[], Awaitable[None]]],
) -> AsyncIterator[tuple[AsyncClient, Callable[[TenantContext], None]]]:
    app = create_app(
        test_settings,
        probes=successful_probes,
        session_factory=session_factory,
        rate_limiter=DeterministicRateLimiter(),
    )
    active_context: list[TenantContext] = []

    def set_context(context: TenantContext) -> None:
        active_context[:] = [context]

    async def injected_context() -> TenantContext:
        return active_context[0]

    app.dependency_overrides[get_tenant_context] = injected_context
    app.dependency_overrides[authenticate_request] = injected_context
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, set_context
