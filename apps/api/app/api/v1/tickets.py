from __future__ import annotations

import uuid
from typing import Annotated

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
from app.services.tickets import create_ticket

router = APIRouter(prefix="/tickets", tags=["tickets"])
SessionDependency = Annotated[AsyncSession, Depends(get_session)]
TenantDependency = Annotated[TenantContext, Depends(get_tenant_context)]


class TicketCreate(BaseModel):
    title: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
    ]


class TicketResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    title: str


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
