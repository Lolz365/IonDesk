from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import APIKey, AuditEvent, Membership, Organization, User
from app.services.api_keys import (
    APIKeyExpired,
    APIKeyRevoked,
    authenticate_api_key,
    create_api_key,
    hash_api_key_secret,
    revoke_api_key,
    verify_api_key_secret,
)
from app.services.authorization import (
    Capability,
    Role,
    TenantContext,
    capabilities_for_role,
)


async def seed_owner(
    session_factory: async_sessionmaker[AsyncSession],
) -> TenantContext:
    async with session_factory() as session, session.begin():
        org = Organization(identifier="keys-org", name="Keys Org")
        user = User(oidc_subject="keys-owner", email="o@example.test", display_name="O")
        session.add_all([org, user])
        await session.flush()
        membership = Membership(
            organization_id=org.id, user_id=user.id, role=Role.OWNER
        )
        session.add(membership)
        await session.flush()
        return TenantContext(
            organization_id=org.id,
            user_id=user.id,
            membership_id=membership.id,
            role=Role.OWNER,
            capabilities=capabilities_for_role(Role.OWNER),
        )


def test_api_key_hash_is_salted_one_way_and_verifiable() -> None:
    first = hash_api_key_secret("high entropy secret")
    second = hash_api_key_secret("high entropy secret")

    assert first != second
    assert "high entropy secret" not in first
    assert verify_api_key_secret("high entropy secret", first)
    assert not verify_api_key_secret("wrong", first)


@pytest.mark.anyio
async def test_api_key_lifecycle_scope_expiry_revocation_and_audit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    owner = await seed_owner(session_factory)
    correlation_id = uuid.uuid4()
    async with session_factory() as session:
        issued = await create_api_key(
            session,
            context=owner,
            name="Building integration",
            scopes=frozenset({Capability.ORGANIZATION_READ}),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            correlation_id=correlation_id,
            source_ip=None,
            user_agent=None,
        )
        await session.commit()

    assert issued.token.startswith(f"vo_sk_{issued.prefix}.")
    async with session_factory() as session:
        stored = await session.scalar(select(APIKey).where(APIKey.id == issued.id))
        assert stored is not None
        assert issued.token not in stored.secret_hash
        context = await authenticate_api_key(session, issued.token)
        await session.commit()
    assert context.organization_id == owner.organization_id
    assert context.capabilities == frozenset({Capability.ORGANIZATION_READ})

    async with session_factory() as session:
        updated = await session.get(APIKey, issued.id)
        assert updated is not None and updated.last_used_at is not None
        await revoke_api_key(
            session,
            context=owner,
            api_key_id=issued.id,
            correlation_id=uuid.uuid4(),
            source_ip=None,
            user_agent=None,
        )
        await revoke_api_key(
            session,
            context=owner,
            api_key_id=issued.id,
            correlation_id=uuid.uuid4(),
            source_ip=None,
            user_agent=None,
        )
        await session.commit()
        with pytest.raises(APIKeyRevoked):
            await authenticate_api_key(session, issued.token)

    async with session_factory() as session:
        events = list(
            await session.scalars(select(AuditEvent).order_by(AuditEvent.created_at))
        )
    assert [event.action for event in events] == ["api_key.created", "api_key.revoked"]
    assert issued.token not in str([event.after for event in events])


@pytest.mark.anyio
async def test_expired_api_key_is_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    owner = await seed_owner(session_factory)
    async with session_factory() as session, session.begin():
        key = APIKey(
            organization_id=owner.organization_id,
            created_by_user_id=owner.user_id,
            name="Expired",
            key_prefix="expired00001",
            secret_hash=hash_api_key_secret("s" * 32),
            scopes=[Capability.ORGANIZATION_READ.value],
            expires_at=datetime.now(UTC) + timedelta(seconds=1),
        )
        session.add(key)
    with pytest.raises(APIKeyExpired):
        async with session_factory() as session:
            await authenticate_api_key(
                session,
                f"vo_sk_expired00001.{('s' * 32)}",
                now=datetime.now(UTC) + timedelta(seconds=2),
            )
