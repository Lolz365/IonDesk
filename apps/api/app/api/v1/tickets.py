from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.services.authorization import (
    Capability,
    TenantContext,
    get_tenant_context,
    require_capability,
)
from app.services.tickets import (
    create_ticket,
    get_ticket,
    list_tickets,
    transition_ticket,
)

router = APIRouter(prefix="/tickets", tags=["tickets"])
SessionDependency = Annotated[AsyncSession, Depends(get_session)]
TenantDependency = Annotated[TenantContext, Depends(get_tenant_context)]


class TicketCreate(BaseModel):
    title: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
    ]


class TicketStatusUpdate(BaseModel):
    status: Literal["assigned", "in_progress", "closed"]


class TicketResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    title: str
    status: str


@router.get("", response_model=list[TicketResponse])
async def list_tenant_tickets(
    session: SessionDependency,
    context: TenantDependency,
) -> list[TicketResponse]:
    require_capability(context, Capability.WORK_ORDER_READ)
    tickets = await list_tickets(session, context=context)
    return [TicketResponse.model_validate(ticket) for ticket in tickets]


@router.get("/{ticket_id}", response_model=TicketResponse)
async def get_tenant_ticket(
    ticket_id: uuid.UUID,
    session: SessionDependency,
    context: TenantDependency,
) -> TicketResponse:
    require_capability(context, Capability.WORK_ORDER_READ)
    ticket = await get_ticket(session, context=context, ticket_id=ticket_id)
    return TicketResponse.model_validate(ticket)


@router.post("", response_model=TicketResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant_ticket(
    body: TicketCreate,
    session: SessionDependency,
    context: TenantDependency,
) -> TicketResponse:
    require_capability(context, Capability.WORK_ORDER_CREATE)
    ticket = await create_ticket(session, context=context, title=body.title)
    await session.commit()
    return TicketResponse.model_validate(ticket)


@router.patch("/{ticket_id}/status", response_model=TicketResponse)
async def update_tenant_ticket_status(
    ticket_id: uuid.UUID,
    body: TicketStatusUpdate,
    session: SessionDependency,
    context: TenantDependency,
) -> TicketResponse:
    capability = {
        "assigned": Capability.WORK_ORDER_DISPATCH,
        "in_progress": Capability.WORK_ORDER_EXECUTE,
        "closed": Capability.WORK_ORDER_CLOSE,
    }[body.status]
    require_capability(context, capability)
    ticket = await transition_ticket(
        session,
        context=context,
        ticket_id=ticket_id,
        status=body.status,
    )
    await session.commit()
    return TicketResponse.model_validate(ticket)
