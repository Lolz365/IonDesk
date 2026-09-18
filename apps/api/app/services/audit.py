from __future__ import annotations

import uuid
from collections.abc import Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditEvent, OutboxEvent
from app.services.authorization import TenantContext


def record_audit_event(
    session: AsyncSession,
    *,
    context: TenantContext,
    object_type: str,
    object_id: uuid.UUID,
    action: str,
    before: Mapping[str, object] | None,
    after: Mapping[str, object] | None,
    correlation_id: uuid.UUID,
    source_ip: str | None,
    user_agent: str | None,
) -> AuditEvent:
    event = AuditEvent(
        organization_id=context.organization_id,
        actor_user_id=context.user_id,
        object_type=object_type,
        object_id=object_id,
        action=action,
        before=before,
        after=after,
        correlation_id=correlation_id,
        source_ip=source_ip,
        user_agent=user_agent,
    )
    session.add(event)
    return event


def enqueue_outbox_event(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    aggregate_type: str,
    aggregate_id: uuid.UUID,
    event_type: str,
    payload: dict[str, object],
    idempotency_key: str,
) -> OutboxEvent:
    event = OutboxEvent(
        organization_id=organization_id,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        payload=payload,
        idempotency_key=idempotency_key,
    )
    session.add(event)
    return event
