from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Ticket
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
) -> Ticket:
    ticket = await get_ticket(session, context=context, ticket_id=ticket_id)
    next_status = {
        "new": "assigned",
        "assigned": "in_progress",
        "in_progress": "closed",
    }.get(ticket.status)
    if status != next_status:
        raise InvalidTicketTransition
    ticket.status = status
    await session.flush()
    return ticket
