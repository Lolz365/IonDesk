from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Organization
from app.services.audit import enqueue_outbox_event, record_audit_event
from app.services.authorization import TenantContext


class OrganizationNotFound(Exception):
    """Raised without exposing whether another tenant owns a guessed ID."""


class TransactionConflict(Exception):
    """Raised when a transaction violates a uniqueness/concurrency invariant."""


async def get_tenant_organization(
    session: AsyncSession,
    *,
    context: TenantContext,
    organization_id: uuid.UUID,
) -> Organization:
    organization = await session.scalar(
        select(Organization).where(
            Organization.id == organization_id,
            Organization.id == context.organization_id,
        )
    )
    if organization is None:
        raise OrganizationNotFound
    return organization


async def rename_current_organization(
    session: AsyncSession,
    *,
    context: TenantContext,
    name: str,
    correlation_id: uuid.UUID,
    source_ip: str | None,
    user_agent: str | None,
) -> Organization:
    try:
        async with session.begin():
            organization = await get_tenant_organization(
                session,
                context=context,
                organization_id=context.organization_id,
            )
            before: dict[str, object] = {"name": organization.name}
            organization.name = name
            record_audit_event(
                session,
                context=context,
                object_type="organization",
                object_id=organization.id,
                action="organization.renamed",
                before=before,
                after={"name": name},
                correlation_id=correlation_id,
                source_ip=source_ip,
                user_agent=user_agent,
            )
            enqueue_outbox_event(
                session,
                organization_id=context.organization_id,
                aggregate_type="organization",
                aggregate_id=organization.id,
                event_type="organization.renamed",
                payload={"organization_id": str(organization.id), "name": name},
                idempotency_key=f"organization.renamed:{correlation_id}",
            )
            await session.flush()
        return organization
    except IntegrityError as error:
        raise TransactionConflict from error
