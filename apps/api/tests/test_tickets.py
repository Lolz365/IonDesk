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
async def test_owner_gets_own_ticket_but_not_another_organizations_ticket(
    api_client: tuple[AsyncClient, Callable[[TenantContext], None]],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session, session.begin():
        organization = Organization(identifier="retrieval-org", name="Retrieval Org")
        other_organization = Organization(identifier="hidden-org", name="Hidden Org")
        owner = User(
            oidc_subject="retrieval-owner",
            email="retrieval-owner@example.test",
            display_name="Retrieval Owner",
        )
        session.add_all([organization, other_organization, owner])
        await session.flush()
        membership = Membership(
            organization_id=organization.id,
            user_id=owner.id,
            role=Role.OWNER,
        )
        visible_ticket = Ticket(
            organization_id=organization.id,
            created_by_user_id=owner.id,
            title="Visible ticket detail",
        )
        hidden_ticket = Ticket(
            organization_id=other_organization.id,
            created_by_user_id=owner.id,
            title="Secret ticket detail",
        )
        session.add_all([membership, visible_ticket, hidden_ticket])
        await session.flush()
        owner_context = TenantContext(
            organization_id=organization.id,
            user_id=owner.id,
            membership_id=membership.id,
            role=Role.OWNER,
            capabilities=capabilities_for_role(Role.OWNER),
        )
        visible_ticket_id = visible_ticket.id
        hidden_ticket_id = hidden_ticket.id

    client, set_context = api_client
    set_context(owner_context)
    visible = await client.get(f"/api/v1/tickets/{visible_ticket_id}")
    hidden = await client.get(f"/api/v1/tickets/{hidden_ticket_id}")

    assert visible.status_code == 200
    assert visible.json() == {
        "id": str(visible_ticket_id),
        "organization_id": str(organization.id),
        "title": "Visible ticket detail",
    }
    assert hidden.status_code == 404
    assert hidden.json()["error"]["code"] == "ticket_not_found"
    assert "Secret ticket detail" not in hidden.text


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
