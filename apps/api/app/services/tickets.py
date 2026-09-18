from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Ticket
from app.services.authorization import TenantContext


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
