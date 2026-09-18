from __future__ import annotations

from collections.abc import Callable

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Membership, Organization, User
from app.services.authorization import Role, TenantContext, capabilities_for_role


@pytest.mark.anyio
async def test_organization_a_cannot_read_organization_b_by_guessed_uuid(
    api_client: tuple[AsyncClient, Callable[[TenantContext], None]],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session, session.begin():
        org_a = Organization(identifier="org-a", name="Organization A")
        org_b = Organization(identifier="org-b", name="Organization B")
        user_a = User(
            oidc_subject="subject-a",
            email="a@example.test",
            display_name="User A",
        )
        session.add_all([org_a, org_b, user_a])
        await session.flush()
        membership = Membership(
            organization_id=org_a.id, user_id=user_a.id, role=Role.OWNER
        )
        session.add(membership)
        await session.flush()
        context = TenantContext(
            organization_id=org_a.id,
            user_id=user_a.id,
            membership_id=membership.id,
            role=Role.OWNER,
            capabilities=capabilities_for_role(Role.OWNER),
        )

    client, set_context = api_client
    set_context(context)
    response = await client.get(f"/api/v1/organizations/{org_b.id}")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "organization_not_found",
            "message": "Organization not found.",
            "request_id": response.headers["x-request-id"],
        }
    }
    assert str(org_b.id) not in response.text
