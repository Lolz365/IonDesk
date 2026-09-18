from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import (
    AuditEvent,
    IdempotencyRecord,
    Membership,
    Organization,
    OutboxEvent,
    Ticket,
    User,
)
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
        "status": "new",
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
async def test_owner_lists_tickets_newest_first_with_id_tie_breaker(
    api_client: tuple[AsyncClient, Callable[[TenantContext], None]],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session, session.begin():
        organization = Organization(identifier="ordered-org", name="Ordered Org")
        owner = User(
            oidc_subject="ordering-owner",
            email="ordering-owner@example.test",
            display_name="Ordering Owner",
        )
        session.add_all([organization, owner])
        await session.flush()
        membership = Membership(
            organization_id=organization.id,
            user_id=owner.id,
            role=Role.OWNER,
        )
        newer_created_at = datetime(2026, 1, 2, tzinfo=UTC)
        session.add_all(
            [
                membership,
                Ticket(
                    id=uuid.UUID(int=3),
                    organization_id=organization.id,
                    created_by_user_id=owner.id,
                    title="Older ticket",
                    created_at=datetime(2026, 1, 1, tzinfo=UTC),
                ),
                Ticket(
                    id=uuid.UUID(int=1),
                    organization_id=organization.id,
                    created_by_user_id=owner.id,
                    title="Newer lower-id ticket",
                    created_at=newer_created_at,
                ),
                Ticket(
                    id=uuid.UUID(int=2),
                    organization_id=organization.id,
                    created_by_user_id=owner.id,
                    title="Newer higher-id ticket",
                    created_at=newer_created_at,
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
    assert [ticket["title"] for ticket in response.json()] == [
        "Newer higher-id ticket",
        "Newer lower-id ticket",
        "Older ticket",
    ]


@pytest.mark.anyio
async def test_owner_filters_tenant_ticket_list_by_assigned_status(
    api_client: tuple[AsyncClient, Callable[[TenantContext], None]],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session, session.begin():
        organization = Organization(identifier="filtered-org", name="Filtered Org")
        other_organization = Organization(
            identifier="other-filtered-org", name="Other Filtered Org"
        )
        owner = User(
            oidc_subject="filtering-owner",
            email="filtering-owner@example.test",
            display_name="Filtering Owner",
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
                    title="Older assigned ticket",
                    status="assigned",
                    created_at=datetime(2026, 1, 1, tzinfo=UTC),
                ),
                Ticket(
                    organization_id=organization.id,
                    created_by_user_id=owner.id,
                    title="Newer assigned ticket",
                    status="assigned",
                    created_at=datetime(2026, 1, 2, tzinfo=UTC),
                ),
                Ticket(
                    organization_id=organization.id,
                    created_by_user_id=owner.id,
                    title="New tenant ticket",
                    status="new",
                    created_at=datetime(2026, 1, 3, tzinfo=UTC),
                ),
                Ticket(
                    organization_id=other_organization.id,
                    created_by_user_id=owner.id,
                    title="Other tenant assigned ticket",
                    status="assigned",
                    created_at=datetime(2026, 1, 4, tzinfo=UTC),
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
    response = await client.get("/api/v1/tickets?status=assigned")

    assert response.status_code == 200
    assert [ticket["title"] for ticket in response.json()] == [
        "Newer assigned ticket",
        "Older assigned ticket",
    ]


@pytest.mark.anyio
async def test_owner_limits_ticket_list_to_newest_tenant_ticket(
    api_client: tuple[AsyncClient, Callable[[TenantContext], None]],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session, session.begin():
        organization = Organization(identifier="limited-org", name="Limited Org")
        owner = User(
            oidc_subject="limited-owner",
            email="limited-owner@example.test",
            display_name="Limited Owner",
        )
        session.add_all([organization, owner])
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
                    title="Older limited ticket",
                    created_at=datetime(2026, 1, 1, tzinfo=UTC),
                ),
                Ticket(
                    organization_id=organization.id,
                    created_by_user_id=owner.id,
                    title="Newest limited ticket",
                    created_at=datetime(2026, 1, 2, tzinfo=UTC),
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
    response = await client.get("/api/v1/tickets?limit=1")

    assert response.status_code == 200
    assert [ticket["title"] for ticket in response.json()] == [
        "Newest limited ticket"
    ]


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
    assert response.json()["status"] == "new"

    from app.models import Ticket

    async with session_factory() as session:
        tickets = list(await session.scalars(select(Ticket)))

    assert len(tickets) == 1
    assert tickets[0].organization_id == organization.id
    assert tickets[0].title == "Leaking valve"
    assert tickets[0].status == "new"


@pytest.mark.anyio
async def test_owner_ticket_creation_writes_audit_and_outbox_events(
    api_client: tuple[AsyncClient, Callable[[TenantContext], None]],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session, session.begin():
        organization = Organization(identifier="creation-org", name="Creation Org")
        owner = User(
            oidc_subject="creation-owner",
            email="creation-owner@example.test",
            display_name="Creation Owner",
        )
        session.add_all([organization, owner])
        await session.flush()
        membership = Membership(
            organization_id=organization.id,
            user_id=owner.id,
            role=Role.OWNER,
        )
        session.add(membership)
        await session.flush()
        context = TenantContext(
            organization_id=organization.id,
            user_id=owner.id,
            membership_id=membership.id,
            role=Role.OWNER,
            capabilities=capabilities_for_role(Role.OWNER),
        )

    client, set_context = api_client
    set_context(context)
    request_id = uuid.uuid4()
    response = await client.post(
        "/api/v1/tickets",
        headers={"x-request-id": str(request_id)},
        json={"title": "  Leaking valve  "},
    )

    assert response.status_code == 201
    ticket_id = uuid.UUID(response.json()["id"])
    async with session_factory() as session:
        audit_event = await session.scalar(select(AuditEvent))
        outbox_event = await session.scalar(select(OutboxEvent))

    assert audit_event is not None
    assert audit_event.organization_id == organization.id
    assert audit_event.actor_user_id == owner.id
    assert audit_event.object_type == "ticket"
    assert audit_event.object_id == ticket_id
    assert audit_event.action == "ticket.created"
    assert audit_event.before is None
    assert audit_event.after == {"title": "Leaking valve", "status": "new"}
    assert audit_event.correlation_id == request_id
    assert outbox_event is not None
    assert outbox_event.organization_id == organization.id
    assert outbox_event.aggregate_type == "ticket"
    assert outbox_event.aggregate_id == ticket_id
    assert outbox_event.event_type == "ticket.created"
    assert outbox_event.payload == {
        "ticket_id": str(ticket_id),
        "title": "Leaking valve",
        "status": "new",
    }
    assert outbox_event.idempotency_key == f"ticket.created:{ticket_id}:{request_id}"


@pytest.mark.anyio
async def test_ticket_creation_replays_idempotent_response_without_duplicate_writes(
    api_client: tuple[AsyncClient, Callable[[TenantContext], None]],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session, session.begin():
        organization = Organization(identifier="idempotent-org", name="Idempotent Org")
        owner = User(
            oidc_subject="idempotent-owner",
            email="idempotent-owner@example.test",
            display_name="Idempotent Owner",
        )
        session.add_all([organization, owner])
        await session.flush()
        membership = Membership(
            organization_id=organization.id,
            user_id=owner.id,
            role=Role.OWNER,
        )
        session.add(membership)
        await session.flush()
        context = TenantContext(
            organization_id=organization.id,
            user_id=owner.id,
            membership_id=membership.id,
            role=Role.OWNER,
            capabilities=capabilities_for_role(Role.OWNER),
        )

    client, set_context = api_client
    set_context(context)
    headers = {"Idempotency-Key": "create-ticket-1"}
    payload = {"title": "Leaking valve"}

    first = await client.post("/api/v1/tickets", headers=headers, json=payload)
    second = await client.post("/api/v1/tickets", headers=headers, json=payload)

    assert first.status_code == second.status_code == 201
    assert second.json() == first.json()
    async with session_factory() as session:
        ticket_count = await session.scalar(select(func.count()).select_from(Ticket))
        audit_count = await session.scalar(
            select(func.count()).select_from(AuditEvent)
        )
        outbox_count = await session.scalar(
            select(func.count()).select_from(OutboxEvent)
        )
        idempotency_count = await session.scalar(
            select(func.count()).select_from(IdempotencyRecord)
        )

    assert ticket_count == 1
    assert audit_count == 1
    assert outbox_count == 1
    assert idempotency_count == 1


@pytest.mark.anyio
async def test_dispatcher_assigns_new_ticket(
    api_client: tuple[AsyncClient, Callable[[TenantContext], None]],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session, session.begin():
        organization = Organization(identifier="dispatch-org", name="Dispatch Org")
        dispatcher = User(
            oidc_subject="dispatch-user",
            email="dispatch@example.test",
            display_name="Dispatch User",
        )
        session.add_all([organization, dispatcher])
        await session.flush()
        membership = Membership(
            organization_id=organization.id,
            user_id=dispatcher.id,
            role=Role.DISPATCHER,
        )
        ticket = Ticket(
            organization_id=organization.id,
            created_by_user_id=dispatcher.id,
            title="Assign this ticket",
        )
        session.add_all([membership, ticket])
        await session.flush()
        context = TenantContext(
            organization_id=organization.id,
            user_id=dispatcher.id,
            membership_id=membership.id,
            role=Role.DISPATCHER,
            capabilities=capabilities_for_role(Role.DISPATCHER),
        )
        ticket_id = ticket.id

    client, set_context = api_client
    set_context(context)
    request_id = uuid.uuid4()
    response = await client.patch(
        f"/api/v1/tickets/{ticket_id}/status",
        headers={"x-request-id": str(request_id)},
        json={"status": "assigned"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "assigned"

    async with session_factory() as session:
        saved_ticket = await session.get(Ticket, ticket_id)
        audit_event = await session.scalar(select(AuditEvent))
        outbox_event = await session.scalar(select(OutboxEvent))

    assert saved_ticket is not None
    assert saved_ticket.status == "assigned"
    assert audit_event is not None
    assert audit_event.organization_id == organization.id
    assert audit_event.actor_user_id == dispatcher.id
    assert audit_event.object_type == "ticket"
    assert audit_event.object_id == ticket_id
    assert audit_event.action == "ticket.status_changed"
    assert audit_event.before == {"status": "new"}
    assert audit_event.after == {"status": "assigned"}
    assert audit_event.correlation_id == request_id
    assert outbox_event is not None
    assert outbox_event.organization_id == organization.id
    assert outbox_event.aggregate_type == "ticket"
    assert outbox_event.aggregate_id == ticket_id
    assert outbox_event.event_type == "ticket.status_changed"
    assert outbox_event.payload == {
        "ticket_id": str(ticket_id),
        "before": {"status": "new"},
        "after": {"status": "assigned"},
    }
    assert outbox_event.idempotency_key == (
        f"ticket.status_changed:{ticket_id}:new:assigned:{request_id}"
    )


@pytest.mark.anyio
async def test_technician_starts_assigned_ticket(
    api_client: tuple[AsyncClient, Callable[[TenantContext], None]],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session, session.begin():
        organization = Organization(identifier="execution-org", name="Execution Org")
        technician = User(
            oidc_subject="execution-technician",
            email="technician@example.test",
            display_name="Execution Technician",
        )
        session.add_all([organization, technician])
        await session.flush()
        membership = Membership(
            organization_id=organization.id,
            user_id=technician.id,
            role=Role.TECHNICIAN,
        )
        ticket = Ticket(
            organization_id=organization.id,
            created_by_user_id=technician.id,
            title="Start this ticket",
            status="assigned",
        )
        session.add_all([membership, ticket])
        await session.flush()
        context = TenantContext(
            organization_id=organization.id,
            user_id=technician.id,
            membership_id=membership.id,
            role=Role.TECHNICIAN,
            capabilities=capabilities_for_role(Role.TECHNICIAN),
        )
        ticket_id = ticket.id

    client, set_context = api_client
    set_context(context)
    response = await client.patch(
        f"/api/v1/tickets/{ticket_id}/status", json={"status": "in_progress"}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "in_progress"

    async with session_factory() as session:
        saved_ticket = await session.get(Ticket, ticket_id)

    assert saved_ticket is not None
    assert saved_ticket.status == "in_progress"


@pytest.mark.anyio
async def test_dispatcher_closes_in_progress_ticket(
    api_client: tuple[AsyncClient, Callable[[TenantContext], None]],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session, session.begin():
        organization = Organization(identifier="close-org", name="Close Org")
        dispatcher = User(
            oidc_subject="close-dispatcher",
            email="close-dispatcher@example.test",
            display_name="Close Dispatcher",
        )
        session.add_all([organization, dispatcher])
        await session.flush()
        membership = Membership(
            organization_id=organization.id,
            user_id=dispatcher.id,
            role=Role.DISPATCHER,
        )
        ticket = Ticket(
            organization_id=organization.id,
            created_by_user_id=dispatcher.id,
            title="Close this ticket",
            status="in_progress",
        )
        session.add_all([membership, ticket])
        await session.flush()
        context = TenantContext(
            organization_id=organization.id,
            user_id=dispatcher.id,
            membership_id=membership.id,
            role=Role.DISPATCHER,
            capabilities=capabilities_for_role(Role.DISPATCHER),
        )
        ticket_id = ticket.id

    client, set_context = api_client
    set_context(context)
    response = await client.patch(
        f"/api/v1/tickets/{ticket_id}/status", json={"status": "closed"}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "closed"

    async with session_factory() as session:
        saved_ticket = await session.get(Ticket, ticket_id)

    assert saved_ticket is not None
    assert saved_ticket.status == "closed"


@pytest.mark.anyio
async def test_dispatcher_cannot_close_new_ticket(
    api_client: tuple[AsyncClient, Callable[[TenantContext], None]],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session, session.begin():
        organization = Organization(
            identifier="invalid-close-org", name="Invalid Close"
        )
        dispatcher = User(
            oidc_subject="invalid-close-dispatcher",
            email="invalid-close@example.test",
            display_name="Invalid Close Dispatcher",
        )
        session.add_all([organization, dispatcher])
        await session.flush()
        membership = Membership(
            organization_id=organization.id,
            user_id=dispatcher.id,
            role=Role.DISPATCHER,
        )
        ticket = Ticket(
            organization_id=organization.id,
            created_by_user_id=dispatcher.id,
            title="Cannot close yet",
        )
        session.add_all([membership, ticket])
        await session.flush()
        context = TenantContext(
            organization_id=organization.id,
            user_id=dispatcher.id,
            membership_id=membership.id,
            role=Role.DISPATCHER,
            capabilities=capabilities_for_role(Role.DISPATCHER),
        )
        ticket_id = ticket.id

    client, set_context = api_client
    set_context(context)
    response = await client.patch(
        f"/api/v1/tickets/{ticket_id}/status", json={"status": "closed"}
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_ticket_transition"
