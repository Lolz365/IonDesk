from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.main import create_app
from app.models import APIKey, AuditEvent, Membership, Organization, User
from app.services.authorization import Capability, Role
from app.services.rate_limits import DeterministicRateLimiter
from app.settings import Settings


class AcceptOneToken:
    async def validate(self, token: str) -> str:
        if token != "signed-and-verified":
            raise ValueError
        return "http-subject"


async def seeded_org(
    session_factory: async_sessionmaker[AsyncSession],
) -> Organization:
    async with session_factory() as session, session.begin():
        organization = Organization(identifier="http-org", name="HTTP Org")
        user = User(
            oidc_subject="http-subject",
            email="http@example.test",
            display_name="HTTP Owner",
        )
        session.add_all([organization, user])
        await session.flush()
        session.add(
            Membership(
                organization_id=organization.id,
                user_id=user.id,
                role=Role.OWNER,
            )
        )
    return organization


def phase3_settings(
    *, authenticated_rate_limit: int = 600, anonymous_rate_limit: int = 60
) -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+asyncpg://unused:unused@localhost/unused",
        redis_url="redis://:unused@localhost:6379/0",
        object_storage_endpoint="http://localhost:9000",
        object_storage_access_key="unused",
        object_storage_secret_key="unused",
        object_storage_bucket="unused",
        oidc_issuer="https://identity.example.test/realms/visualops",
        oidc_audience="visualops-api",
        oidc_jwks_url="https://identity.example.test/jwks",
        authenticated_rate_limit=authenticated_rate_limit,
        anonymous_rate_limit=anonymous_rate_limit,
    )


@pytest.mark.anyio
async def test_health_and_openapi_are_public_but_business_routes_require_auth(
    session_factory: async_sessionmaker[AsyncSession],
    successful_probes: dict[str, Callable[[], Awaitable[None]]],
) -> None:
    app = create_app(
        phase3_settings(),
        probes=successful_probes,
        session_factory=session_factory,
        oidc_validator=AcceptOneToken(),
        rate_limiter=DeterministicRateLimiter(),
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        live = await client.get("/health/live")
        ready = await client.get("/health/ready")
        openapi = await client.get("/api/openapi.json")
        denied = await client.get(
            "/api/v1/organizations/00000000-0000-0000-0000-000000000000"
        )

    assert live.status_code == ready.status_code == openapi.status_code == 200
    assert denied.status_code == 401
    assert denied.json() == {
        "error": {
            "code": "authentication_required",
            "message": "Authentication required.",
            "request_id": denied.headers["x-request-id"],
        }
    }


@pytest.mark.anyio
async def test_authentication_error_disables_caching(
    session_factory: async_sessionmaker[AsyncSession],
    successful_probes: dict[str, Callable[[], Awaitable[None]]],
) -> None:
    app = create_app(
        phase3_settings(),
        probes=successful_probes,
        session_factory=session_factory,
        oidc_validator=AcceptOneToken(),
        rate_limiter=DeterministicRateLimiter(),
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/organizations/00000000-0000-0000-0000-000000000000"
        )

    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.anyio
async def test_oidc_boundary_and_api_key_one_time_lifecycle(
    session_factory: async_sessionmaker[AsyncSession],
    successful_probes: dict[str, Callable[[], Awaitable[None]]],
) -> None:
    organization = await seeded_org(session_factory)
    async with session_factory() as session, session.begin():
        other = Organization(identifier="other-http-org", name="Other HTTP Org")
        session.add(other)
        await session.flush()
        other_id = other.id
    app = create_app(
        phase3_settings(),
        probes=successful_probes,
        session_factory=session_factory,
        oidc_validator=AcceptOneToken(),
        rate_limiter=DeterministicRateLimiter(),
    )
    oidc_headers = {
        "authorization": "Bearer signed-and-verified",
        "x-organization-id": str(organization.id),
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        read = await client.get(
            f"/api/v1/organizations/{organization.id}", headers=oidc_headers
        )
        issued = await client.post(
            "/api/v1/api-keys",
            headers=oidc_headers,
            json={"name": "CMMS", "scopes": [Capability.ORGANIZATION_READ]},
        )
        token = issued.json()["token"]
        api_read = await client.get(
            f"/api/v1/organizations/{organization.id}",
            headers={"authorization": f"ApiKey {token}"},
        )
        tenant_denied = await client.get(
            f"/api/v1/organizations/{other_id}",
            headers={"authorization": f"ApiKey {token}"},
        )
        scope_denied = await client.patch(
            "/api/v1/organizations/current",
            headers={"authorization": f"ApiKey {token}"},
            json={"name": "Must not change"},
        )
        revoked = await client.post(
            f"/api/v1/api-keys/{issued.json()['id']}/revoke", headers=oidc_headers
        )
        denied = await client.get(
            f"/api/v1/organizations/{organization.id}",
            headers={"authorization": f"ApiKey {token}"},
        )

    assert read.status_code == issued.status_code == 200
    assert api_read.status_code == revoked.status_code == 200
    assert tenant_denied.status_code == 404
    assert scope_denied.status_code == 403
    assert "secret_hash" not in issued.text
    assert denied.status_code == 401


@pytest.mark.anyio
async def test_api_key_creation_response_disables_caching(
    session_factory: async_sessionmaker[AsyncSession],
    successful_probes: dict[str, Callable[[], Awaitable[None]]],
) -> None:
    organization = await seeded_org(session_factory)
    app = create_app(
        phase3_settings(),
        probes=successful_probes,
        session_factory=session_factory,
        oidc_validator=AcceptOneToken(),
        rate_limiter=DeterministicRateLimiter(),
    )
    headers = {
        "authorization": "Bearer signed-and-verified",
        "x-organization-id": str(organization.id),
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/api-keys",
            headers=headers,
            json={"name": "CMMS", "scopes": [Capability.ORGANIZATION_READ]},
        )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.anyio
async def test_api_key_creation_normalizes_naive_expiry_to_utc(
    session_factory: async_sessionmaker[AsyncSession],
    successful_probes: dict[str, Callable[[], Awaitable[None]]],
) -> None:
    organization = await seeded_org(session_factory)
    app = create_app(
        phase3_settings(),
        probes=successful_probes,
        session_factory=session_factory,
        oidc_validator=AcceptOneToken(),
        rate_limiter=DeterministicRateLimiter(),
    )
    headers = {
        "authorization": "Bearer signed-and-verified",
        "x-organization-id": str(organization.id),
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/api-keys",
            headers=headers,
            json={
                "name": "CMMS",
                "scopes": [Capability.ORGANIZATION_READ],
                "expires_at": "2099-01-01T00:00:00",
            },
        )

    assert response.status_code == 200
    assert datetime.fromisoformat(response.json()["expires_at"]).tzinfo is UTC


@pytest.mark.anyio
async def test_api_key_creation_trims_name_in_response(
    session_factory: async_sessionmaker[AsyncSession],
    successful_probes: dict[str, Callable[[], Awaitable[None]]],
) -> None:
    organization = await seeded_org(session_factory)
    app = create_app(
        phase3_settings(),
        probes=successful_probes,
        session_factory=session_factory,
        oidc_validator=AcceptOneToken(),
        rate_limiter=DeterministicRateLimiter(),
    )
    headers = {
        "authorization": "Bearer signed-and-verified",
        "x-organization-id": str(organization.id),
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/api-keys",
            headers=headers,
            json={"name": "  CMMS  ", "scopes": [Capability.ORGANIZATION_READ]},
        )

    assert response.status_code == 200
    assert response.json()["name"] == "CMMS"


@pytest.mark.anyio
async def test_api_key_creation_rejects_whitespace_name_without_persistence(
    session_factory: async_sessionmaker[AsyncSession],
    successful_probes: dict[str, Callable[[], Awaitable[None]]],
) -> None:
    organization = await seeded_org(session_factory)
    app = create_app(
        phase3_settings(),
        probes=successful_probes,
        session_factory=session_factory,
        oidc_validator=AcceptOneToken(),
        rate_limiter=DeterministicRateLimiter(),
    )
    headers = {
        "authorization": "Bearer signed-and-verified",
        "x-organization-id": str(organization.id),
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/api-keys",
            headers=headers,
            json={"name": "   ", "scopes": [Capability.ORGANIZATION_READ]},
        )

    async with session_factory() as session:
        api_keys = list(await session.scalars(select(APIKey)))
        audit_events = list(await session.scalars(select(AuditEvent)))

    assert response.status_code == 422
    assert api_keys == []
    assert audit_events == []


@pytest.mark.anyio
async def test_api_key_revocation_response_disables_caching(
    session_factory: async_sessionmaker[AsyncSession],
    successful_probes: dict[str, Callable[[], Awaitable[None]]],
) -> None:
    organization = await seeded_org(session_factory)
    app = create_app(
        phase3_settings(),
        probes=successful_probes,
        session_factory=session_factory,
        oidc_validator=AcceptOneToken(),
        rate_limiter=DeterministicRateLimiter(),
    )
    headers = {
        "authorization": "Bearer signed-and-verified",
        "x-organization-id": str(organization.id),
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        issued = await client.post(
            "/api/v1/api-keys",
            headers=headers,
            json={"name": "CMMS", "scopes": [Capability.ORGANIZATION_READ]},
        )
        response = await client.post(
            f"/api/v1/api-keys/{issued.json()['id']}/revoke", headers=headers
        )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.anyio
async def test_api_key_list_returns_metadata_without_secret_material(
    session_factory: async_sessionmaker[AsyncSession],
    successful_probes: dict[str, Callable[[], Awaitable[None]]],
) -> None:
    organization = await seeded_org(session_factory)
    app = create_app(
        phase3_settings(),
        probes=successful_probes,
        session_factory=session_factory,
        oidc_validator=AcceptOneToken(),
        rate_limiter=DeterministicRateLimiter(),
    )
    headers = {
        "authorization": "Bearer signed-and-verified",
        "x-organization-id": str(organization.id),
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        issued = await client.post(
            "/api/v1/api-keys",
            headers=headers,
            json={"name": "CMMS", "scopes": [Capability.ORGANIZATION_READ]},
        )
        response = await client.get("/api/v1/api-keys", headers=headers)

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": issued.json()["id"],
            "name": "CMMS",
            "prefix": issued.json()["prefix"],
            "scopes": [Capability.ORGANIZATION_READ],
            "expires_at": None,
            "revoked_at": None,
            "last_used_at": None,
            "created_at": response.json()[0]["created_at"],
        }
    ]
    assert issued.json()["token"] not in response.text
    assert "secret_hash" not in response.text


@pytest.mark.anyio
async def test_unexpected_authentication_failure_returns_safe_error_envelope(
    session_factory: async_sessionmaker[AsyncSession],
    successful_probes: dict[str, Callable[[], Awaitable[None]]],
) -> None:
    class BrokenTokenValidator:
        async def validate(self, token: str) -> str:
            raise RuntimeError("credential=must-not-leak")

    app = create_app(
        phase3_settings(),
        probes=successful_probes,
        session_factory=session_factory,
        oidc_validator=BrokenTokenValidator(),
        rate_limiter=DeterministicRateLimiter(),
    )
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/api/v1/organizations/00000000-0000-0000-0000-000000000000",
            headers={
                "authorization": "Bearer signed-and-verified",
                "x-organization-id": "00000000-0000-0000-0000-000000000000",
            },
        )

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "An unexpected error occurred.",
            "request_id": response.headers["x-request-id"],
        }
    }
    assert "credential" not in response.text


@pytest.mark.anyio
async def test_authenticated_rate_limit_backend_failure_fails_closed(
    session_factory: async_sessionmaker[AsyncSession],
    successful_probes: dict[str, Callable[[], Awaitable[None]]],
) -> None:
    class UnavailableRateLimiter:
        async def check(
            self, key: str, *, limit: int, window_seconds: int
        ) -> None:
            raise RuntimeError("redis unavailable")

    organization = await seeded_org(session_factory)
    app = create_app(
        phase3_settings(),
        probes=successful_probes,
        session_factory=session_factory,
        oidc_validator=AcceptOneToken(),
        rate_limiter=UnavailableRateLimiter(),
    )
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.get(
            f"/api/v1/organizations/{organization.id}",
            headers={
                "authorization": "Bearer signed-and-verified",
                "x-organization-id": str(organization.id),
            },
        )

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "service_unavailable",
            "message": "Service temporarily unavailable.",
            "request_id": response.headers["x-request-id"],
        }
    }


@pytest.mark.anyio
async def test_rate_limits_have_request_id_envelopes_and_separate_bounds(
    session_factory: async_sessionmaker[AsyncSession],
    successful_probes: dict[str, Callable[[], Awaitable[None]]],
) -> None:
    organization = await seeded_org(session_factory)
    app = create_app(
        phase3_settings(
            authenticated_rate_limit=1,
            anonymous_rate_limit=1,
        ),
        probes=successful_probes,
        session_factory=session_factory,
        oidc_validator=AcceptOneToken(),
        rate_limiter=DeterministicRateLimiter(),
    )
    headers = {
        "authorization": "Bearer signed-and-verified",
        "x-organization-id": str(organization.id),
    }
    path = f"/api/v1/organizations/{organization.id}"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get(path, headers=headers)).status_code == 200
        credential_limited = await client.get(path, headers=headers)
        assert (await client.get(path)).status_code == 401
        anonymous_limited = await client.get(path)

    for response in (credential_limited, anonymous_limited):
        assert response.status_code == 429
        assert response.json()["error"]["code"] == "rate_limit_exceeded"
        assert (
            response.json()["error"]["request_id"] == response.headers["x-request-id"]
        )
