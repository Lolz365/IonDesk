from __future__ import annotations

import uuid
from collections.abc import Callable

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import AuditEvent, Membership, Organization, OutboxEvent, User
from app.services.authorization import Role, TenantContext, capabilities_for_role


async def seed_owner(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[Organization, TenantContext]:
    async with session_factory() as session, session.begin():
        organization = Organization(identifier="org-a", name="Before")
        user = User(
            oidc_subject="subject-a",
            email="a@example.test",
            display_name="Owner",
        )
        session.add_all([organization, user])
        await session.flush()
        membership = Membership(
            organization_id=organization.id, user_id=user.id, role=Role.OWNER
        )
        session.add(membership)
        await session.flush()
        context = TenantContext(
            organization_id=organization.id,
            user_id=user.id,
            membership_id=membership.id,
            role=Role.OWNER,
            capabilities=capabilities_for_role(Role.OWNER),
        )
    return organization, context


@pytest.mark.anyio
async def test_reference_mutation_writes_one_audit_and_one_outbox_event(
    api_client: tuple[AsyncClient, Callable[[TenantContext], None]],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization, context = await seed_owner(session_factory)
    client, set_context = api_client
    set_context(context)
    request_id = str(uuid.uuid4())

    response = await client.patch(
        "/api/v1/organizations/current",
        headers={"x-request-id": request_id},
        json={"name": "After"},
    )

    assert response.status_code == 200
    async with session_factory() as session:
        audit_events = (
            await session.scalars(
                select(AuditEvent).where(AuditEvent.organization_id == organization.id)
            )
        ).all()
        outbox_events = (
            await session.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.organization_id == organization.id
                )
            )
        ).all()
    assert len(audit_events) == 1
    assert len(outbox_events) == 1
    assert audit_events[0].before == {"name": "Before"}
    assert audit_events[0].after == {"name": "After"}
    assert audit_events[0].correlation_id == uuid.UUID(request_id)
    assert outbox_events[0].idempotency_key == f"organization.renamed:{request_id}"


@pytest.mark.anyio
async def test_mutation_rolls_back_change_and_audit_when_outbox_insert_fails(
    api_client: tuple[AsyncClient, Callable[[TenantContext], None]],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization, context = await seed_owner(session_factory)
    client, set_context = api_client
    set_context(context)
    request_id = str(uuid.uuid4())
    headers = {"x-request-id": request_id}
    first = await client.patch(
        "/api/v1/organizations/current", headers=headers, json={"name": "First"}
    )

    second = await client.patch(
        "/api/v1/organizations/current", headers=headers, json={"name": "Second"}
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "transaction_conflict"
    async with session_factory() as session:
        persisted = await session.get(Organization, organization.id)
        audit_count = await session.scalar(select(func.count()).select_from(AuditEvent))
        outbox_count = await session.scalar(
            select(func.count()).select_from(OutboxEvent)
        )
    assert persisted is not None and persisted.name == "First"
    assert audit_count == 1
    assert outbox_count == 1
