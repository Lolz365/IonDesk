from __future__ import annotations

import uuid

import pytest

from app.services.authorization import (
    AuthorizationDenied,
    Capability,
    Role,
    TenantContext,
    capabilities_for_role,
    require_capability,
)


@pytest.mark.parametrize("role", list(Role))
def test_every_initial_role_maps_to_capabilities(role: Role) -> None:
    capabilities = capabilities_for_role(role)

    assert Capability.ORGANIZATION_READ in capabilities
    assert Capability.WORK_ORDER_READ in capabilities
    assert capabilities


def test_capability_checks_do_not_compare_role_names_at_call_site() -> None:
    context = TenantContext(
        organization_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        membership_id=uuid.uuid4(),
        role=Role.REQUESTER,
        capabilities=capabilities_for_role(Role.REQUESTER),
    )

    require_capability(context, Capability.WORK_ORDER_CREATE)
    with pytest.raises(AuthorizationDenied):
        require_capability(context, Capability.ORGANIZATION_UPDATE)


def test_tenant_context_is_immutable() -> None:
    context = TenantContext(
        organization_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        membership_id=uuid.uuid4(),
        role=Role.AUDITOR,
        capabilities=capabilities_for_role(Role.AUDITOR),
    )

    with pytest.raises((AttributeError, TypeError)):
        context.organization_id = uuid.uuid4()  # type: ignore[misc]
