from __future__ import annotations

import uuid
from collections.abc import Callable

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Membership, Organization, Ticket, User
from app.services.authorization import Role, TenantContext, capabilities_for_role


@pytest.mark.anyio
async def test_owner_lists_only_tickets_from_their_organization(
    api_client: tuple[AsyncClient, Callable[[TenantContext], None]],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session, session.begin():
        organization = Organization(identifier="owner-org", name="Owner Org")
        other_organization = Organization(identifier="outside-org", name="Outside Org")
        owner = User(
            oidc_subject="listing-owner",
            email="listing-owner@example.test",
            display_name="Listing Owner",
        )
        session.add_all([organization, other_organization, owner])
        await session.flush()
        membership = Membership(
            organization_id=organization.id,
            user_id=owner.id,
            role=Role.OWNER,
        )
        session.add_all(
            [
                membership,
                Ticket(
                    organization_id=organization.id,
                    created_by_user_id=owner.id,
                    title="Visible ticket",
                ),
                Ticket(
                    organization_id=other_organization.id,
                    created_by_user_id=owner.id,
                    title="Other tenant ticket",
                ),
            ]
        )
        await session.flush()
        owner_context = TenantContext(
            organization_id=organization.id,
            user_id=owner.id,
            membership_id=membership.id,
            role=Role.OWNER,
            capabilities=capabilities_for_role(Role.OWNER),
        )

    client, set_context = api_client
    set_context(owner_context)
    response = await client.get("/api/v1/tickets")

    assert response.status_code == 200
    assert [ticket["title"] for ticket in response.json()] == ["Visible ticket"]


@pytest.mark.anyio
async def test_owner_creates_tenant_scoped_ticket_with_non_empty_title(
    api_client: tuple[AsyncClient, Callable[[TenantContext], None]],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session, session.begin():
        organization = Organization(identifier="ticket-org", name="Ticket Org")
        other_organization = Organization(identifier="other-org", name="Other Org")
        owner = User(
            oidc_subject="ticket-owner",
            email="owner@example.test",
            display_name="Ticket Owner",
        )
        session.add_all([organization, other_organization, owner])
        await session.flush()
        membership = Membership(
            organization_id=organization.id,
            user_id=owner.id,
            role=Role.OWNER,
        )
        session.add(membership)
        await session.flush()
        owner_context = TenantContext(
            organization_id=organization.id,
            user_id=owner.id,
            membership_id=membership.id,
            role=Role.OWNER,
            capabilities=capabilities_for_role(Role.OWNER),
        )
        auditor_context = TenantContext(
            organization_id=other_organization.id,
            user_id=uuid.uuid4(),
            membership_id=uuid.uuid4(),
            role=Role.AUDITOR,
            capabilities=capabilities_for_role(Role.AUDITOR),
        )

    client, set_context = api_client
    set_context(auditor_context)
    denied = await client.post("/api/v1/tickets", json={"title": "Not allowed"})
    set_context(owner_context)
    response = await client.post(
        "/api/v1/tickets", json={"title": "  Leaking valve  "}
    )

    assert denied.status_code == 403
    assert response.status_code == 201
    assert response.json()["title"] == "Leaking valve"

    from app.models import Ticket

    async with session_factory() as session:
        tickets = list(await session.scalars(select(Ticket)))

    assert len(tickets) == 1
    assert tickets[0].organization_id == organization.id
    assert tickets[0].title == "Leaking valve"
