from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum

from fastapi import Request


class Role(StrEnum):
    OWNER = "owner"
    OPERATIONS_MANAGER = "operations_manager"
    DISPATCHER = "dispatcher"
    TECHNICIAN = "technician"
    REQUESTER = "requester"
    AUDITOR = "auditor"


class Capability(StrEnum):
    ORGANIZATION_READ = "organization:read"
    ORGANIZATION_UPDATE = "organization:update"
    MEMBERSHIP_MANAGE = "membership:manage"
    API_KEY_MANAGE = "api_key:manage"
    AUDIT_READ = "audit:read"
    WORK_ORDER_READ = "work_order:read"
    WORK_ORDER_CREATE = "work_order:create"
    WORK_ORDER_DISPATCH = "work_order:dispatch"
    WORK_ORDER_EXECUTE = "work_order:execute"
    WORK_ORDER_CLOSE = "work_order:close"


_READ = frozenset({Capability.ORGANIZATION_READ, Capability.WORK_ORDER_READ})
_ROLE_CAPABILITIES: dict[Role, frozenset[Capability]] = {
    Role.OWNER: frozenset(Capability),
    Role.OPERATIONS_MANAGER: _READ
    | {
        Capability.ORGANIZATION_UPDATE,
        Capability.MEMBERSHIP_MANAGE,
        Capability.API_KEY_MANAGE,
        Capability.AUDIT_READ,
        Capability.WORK_ORDER_CREATE,
        Capability.WORK_ORDER_DISPATCH,
        Capability.WORK_ORDER_EXECUTE,
        Capability.WORK_ORDER_CLOSE,
    },
    Role.DISPATCHER: _READ
    | {
        Capability.WORK_ORDER_CREATE,
        Capability.WORK_ORDER_DISPATCH,
        Capability.WORK_ORDER_CLOSE,
    },
    Role.TECHNICIAN: _READ | {Capability.WORK_ORDER_EXECUTE},
    Role.REQUESTER: _READ | {Capability.WORK_ORDER_CREATE},
    Role.AUDITOR: _READ | {Capability.AUDIT_READ},
}


@dataclass(frozen=True, slots=True)
class TenantContext:
    organization_id: uuid.UUID
    user_id: uuid.UUID
    membership_id: uuid.UUID | None
    role: Role | None
    capabilities: frozenset[Capability]
    credential_id: str = ""


class AuthenticationRequired(Exception):
    """Raised when no verified identity context was attached to the request."""


class AuthorizationDenied(Exception):
    """Raised when a verified identity lacks a required capability."""


def capabilities_for_role(role: Role) -> frozenset[Capability]:
    return _ROLE_CAPABILITIES[role]


def require_capability(context: TenantContext, capability: Capability) -> None:
    if capability not in context.capabilities:
        raise AuthorizationDenied


def get_tenant_context(request: Request) -> TenantContext:
    context = getattr(request.state, "tenant_context", None)
    if not isinstance(context, TenantContext):
        raise AuthenticationRequired
    return context
