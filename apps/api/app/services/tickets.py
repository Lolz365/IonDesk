from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Ticket
from app.services.audit import enqueue_outbox_event, record_audit_event
from app.services.authorization import TenantContext


class TicketNotFound(Exception):
    """Raised without exposing whether another tenant owns a guessed ID."""


class InvalidTicketTransition(Exception):
    """Raised when a ticket status change skips the required workflow."""


async def create_ticket(
    session: AsyncSession,
    *,
    context: TenantContext,
    title: str,
) -> Ticket:
    ticket = Ticket(
        organization_id=context.organization_id,
        created_by_user_id=context.user_id,
        title=title,
    )
    session.add(ticket)
    await session.flush()
    return ticket


async def get_ticket(
    session: AsyncSession,
    *,
    context: TenantContext,
    ticket_id: uuid.UUID,
) -> Ticket:
    ticket = await session.scalar(
        select(Ticket).where(
            Ticket.id == ticket_id,
            Ticket.organization_id == context.organization_id,
        )
    )
    if ticket is None:
        raise TicketNotFound
    return ticket


async def list_tickets(
    session: AsyncSession,
    *,
    context: TenantContext,
) -> list[Ticket]:
    tickets = await session.scalars(
        select(Ticket)
        .where(Ticket.organization_id == context.organization_id)
        .order_by(Ticket.created_at.desc(), Ticket.id.desc())
    )
    return list(tickets)


async def transition_ticket(
    session: AsyncSession,
    *,
    context: TenantContext,
    ticket_id: uuid.UUID,
    status: str,
    correlation_id: uuid.UUID,
    source_ip: str | None,
    user_agent: str | None,
) -> Ticket:
    ticket = await get_ticket(session, context=context, ticket_id=ticket_id)
    previous_status = ticket.status
    next_status = {
        "new": "assigned",
        "assigned": "in_progress",
        "in_progress": "closed",
    }.get(previous_status)
    if status != next_status:
        raise InvalidTicketTransition
    ticket.status = status
    before: dict[str, object] = {"status": previous_status}
    after: dict[str, object] = {"status": status}
    record_audit_event(
        session,
        context=context,
        object_type="ticket",
        object_id=ticket.id,
        action="ticket.status_changed",
        before=before,
        after=after,
        correlation_id=correlation_id,
        source_ip=source_ip,
        user_agent=user_agent,
    )
    enqueue_outbox_event(
        session,
        organization_id=context.organization_id,
        aggregate_type="ticket",
        aggregate_id=ticket.id,
        event_type="ticket.status_changed",
        payload={
            "ticket_id": str(ticket.id),
            "before": before,
            "after": after,
        },
        idempotency_key=(
            f"ticket.status_changed:{ticket.id}:{previous_status}:{status}:"
            f"{correlation_id}"
        ),
    )
    await session.flush()
    return ticket
