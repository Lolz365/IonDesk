from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db.base import Base
from app.main import create_app
from app.models import AuditEvent, Membership, Organization, OutboxEvent, User
from app.services.authorization import (
    Role,
    TenantContext,
    capabilities_for_role,
    get_tenant_context,
)
from app.settings import Settings

pytestmark = [pytest.mark.postgresql, pytest.mark.anyio]


@pytest.fixture
async def postgres_session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    database_url = os.getenv("VISUALOPS_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("VISUALOPS_TEST_DATABASE_URL is not set")
    url = make_url(database_url)
    if url.drivername != "postgresql+asyncpg":
        pytest.skip("VISUALOPS_TEST_DATABASE_URL must use postgresql+asyncpg")

    schema = f"test_{uuid.uuid4().hex}"
    admin_engine = create_async_engine(database_url)
    async with admin_engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(
        database_url,
        connect_args={"server_settings": {"search_path": schema}},
    )
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin_engine.dispose()


@pytest.mark.anyio
async def test_postgresql_tenant_isolation_and_transactional_side_effects(
    postgres_session_factory: async_sessionmaker[AsyncSession],
    test_settings: Settings,
    successful_probes: dict[str, Callable[[], Awaitable[None]]],
) -> None:
    async with postgres_session_factory() as session, session.begin():
        org_a = Organization(identifier="postgres-a", name="Before")
        org_b = Organization(identifier="postgres-b", name="Organization B")
        user = User(
            oidc_subject="postgres-subject",
            email="postgres@example.test",
            display_name="Postgres Owner",
        )
        session.add_all([org_a, org_b, user])
        await session.flush()
        membership = Membership(
            organization_id=org_a.id, user_id=user.id, role=Role.OWNER
        )
        session.add(membership)
        await session.flush()
        context = TenantContext(
            organization_id=org_a.id,
            user_id=user.id,
            membership_id=membership.id,
            role=Role.OWNER,
            capabilities=capabilities_for_role(Role.OWNER),
        )

    app = create_app(
        test_settings,
        probes=successful_probes,
        session_factory=postgres_session_factory,
    )
    app.dependency_overrides[get_tenant_context] = lambda: context
    request_id = str(uuid.uuid4())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        guessed = await client.get(f"/api/v1/organizations/{org_b.id}")
        renamed = await client.patch(
            "/api/v1/organizations/current",
            headers={"x-request-id": request_id},
            json={"name": "After"},
        )

    assert guessed.status_code == 404
    assert renamed.status_code == 200
    async with postgres_session_factory() as session:
        audit_count = await session.scalar(select(func.count()).select_from(AuditEvent))
        outbox_count = await session.scalar(
            select(func.count()).select_from(OutboxEvent)
        )
    assert audit_count == 1
    assert outbox_count == 1
