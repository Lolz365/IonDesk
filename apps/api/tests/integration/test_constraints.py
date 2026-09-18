from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import AuditEvent, Membership, Organization, User


async def seed_identity(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[uuid.UUID, uuid.UUID]:
    async with session_factory() as session, session.begin():
        organization = Organization(identifier="immutable-org", name="Organization")
        user = User(
            oidc_subject="constraint-subject",
            email="constraints@example.test",
            display_name="Constraint User",
        )
        session.add_all([organization, user])
        await session.flush()
        return organization.id, user.id


@pytest.mark.anyio
async def test_membership_role_check_constraint_rejects_unknown_role(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_id, user_id = await seed_identity(session_factory)

    with pytest.raises(IntegrityError):
        async with session_factory() as session, session.begin():
            session.add(
                Membership(
                    organization_id=organization_id,
                    user_id=user_id,
                    role="administrator",
                )
            )


@pytest.mark.anyio
async def test_organization_identifier_and_tenant_keys_are_immutable(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_id, user_id = await seed_identity(session_factory)
    async with session_factory() as session, session.begin():
        membership = Membership(
            organization_id=organization_id, user_id=user_id, role="owner"
        )
        session.add(membership)
        await session.flush()
        membership_id = membership.id

    with pytest.raises(ValueError, match="organization identifier is immutable"):
        async with session_factory() as session, session.begin():
            organization = await session.get(Organization, organization_id)
            assert organization is not None
            organization.identifier = "changed-org"

    with pytest.raises(ValueError, match="organization_id is immutable"):
        async with session_factory() as session, session.begin():
            stored_membership = await session.get(Membership, membership_id)
            assert stored_membership is not None
            stored_membership.organization_id = uuid.uuid4()


@pytest.mark.anyio
async def test_audit_events_cannot_be_updated_or_deleted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_id, user_id = await seed_identity(session_factory)
    async with session_factory() as session, session.begin():
        event = AuditEvent(
            organization_id=organization_id,
            actor_user_id=user_id,
            object_type="organization",
            object_id=organization_id,
            action="organization.created",
            before=None,
            after={"name": "Organization"},
            correlation_id=uuid.uuid4(),
        )
        session.add(event)
        await session.flush()
        event_id = event.id

    with pytest.raises(ValueError, match="audit events are append-only"):
        async with session_factory() as session, session.begin():
            stored_event = await session.get(AuditEvent, event_id)
            assert stored_event is not None
            stored_event.action = "changed"

    with pytest.raises(ValueError, match="audit events are append-only"):
        async with session_factory() as session, session.begin():
            deleted_event = await session.get(AuditEvent, event_id)
            assert deleted_event is not None
            await session.delete(deleted_event)
