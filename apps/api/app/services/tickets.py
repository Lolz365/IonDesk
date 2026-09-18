from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import IdempotencyRecord, Ticket
from app.services.audit import enqueue_outbox_event, record_audit_event
from app.services.authorization import TenantContext
from app.services.organizations import TransactionConflict


class TicketNotFound(Exception):
    """Raised without exposing whether another tenant owns a guessed ID."""


class InvalidTicketTransition(Exception):
    """Raised when a ticket status change skips the required workflow."""


IDEMPOTENCY_TTL = timedelta(hours=24)


def _create_request_hash(title: str) -> str:
    request = json.dumps(
        {"operation": "ticket.create", "title": title},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(request.encode()).hexdigest()


def _stored_response(
    record: IdempotencyRecord, request_hash: str
) -> dict[str, object]:
    if (
        record.request_hash != request_hash
        or record.response_status != 201
        or record.response_body is None
    ):
        raise TransactionConflict
    return record.response_body


async def _find_idempotency_record(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    key: str,
) -> IdempotencyRecord | None:
    return cast(
        IdempotencyRecord | None,
        await session.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.organization_id == organization_id,
                IdempotencyRecord.key == key,
            )
        ),
    )


async def create_ticket(
    session: AsyncSession,
    *,
    context: TenantContext,
    title: str,
    correlation_id: uuid.UUID,
    source_ip: str | None,
    user_agent: str | None,
    idempotency_key: str | None = None,
) -> Ticket | dict[str, object]:
    request_hash = _create_request_hash(title)
    try:
        async with session.begin():
            idempotency_record = None
            if idempotency_key is not None:
                idempotency_record = await _find_idempotency_record(
                    session,
                    organization_id=context.organization_id,
                    key=idempotency_key,
                )
                if idempotency_record is not None:
                    expires_at = idempotency_record.expires_at
                    if expires_at.tzinfo is None:
                        expires_at = expires_at.replace(tzinfo=UTC)
                    if expires_at > datetime.now(UTC):
                        return _stored_response(idempotency_record, request_hash)
                    await session.delete(idempotency_record)
                    await session.flush()

                idempotency_record = IdempotencyRecord(
                    organization_id=context.organization_id,
                    key=idempotency_key,
                    request_hash=request_hash,
                    response_status=None,
                    response_body=None,
                    expires_at=datetime.now(UTC) + IDEMPOTENCY_TTL,
                )
                session.add(idempotency_record)
                await session.flush()

            ticket = Ticket(
                organization_id=context.organization_id,
                created_by_user_id=context.user_id,
                title=title,
            )
            session.add(ticket)
            await session.flush()
            after: dict[str, object] = {
                "title": ticket.title,
                "status": ticket.status,
            }
            record_audit_event(
                session,
                context=context,
                object_type="ticket",
                object_id=ticket.id,
                action="ticket.created",
                before=None,
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
                event_type="ticket.created",
                payload={"ticket_id": str(ticket.id), **after},
                idempotency_key=f"ticket.created:{ticket.id}:{correlation_id}",
            )
            await session.flush()
            if idempotency_record is not None:
                idempotency_record.response_status = 201
                idempotency_record.response_body = {
                    "id": str(ticket.id),
                    "organization_id": str(ticket.organization_id),
                    **after,
                }
        return ticket
    except IntegrityError as error:
        if idempotency_key is not None:
            async with session.begin():
                existing_record = await _find_idempotency_record(
                    session,
                    organization_id=context.organization_id,
                    key=idempotency_key,
                )
                if existing_record is not None:
                    return _stored_response(existing_record, request_hash)
        raise TransactionConflict from error


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
