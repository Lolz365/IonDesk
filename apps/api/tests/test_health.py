from collections.abc import Awaitable, Callable

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.settings import Settings

Probe = Callable[[], Awaitable[None]]


def settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+asyncpg://visualops:secret@postgres/visualops",
        redis_url="redis://:secret@redis:6379/0",
        object_storage_endpoint="http://minio:9000",
        object_storage_access_key="access-key",
        object_storage_secret_key="secret-key",
        object_storage_bucket="visualops-private",
        oidc_issuer="https://identity.example.test/realms/visualops",
        oidc_audience="visualops-api",
        oidc_jwks_url="https://identity.example.test/jwks",
    )


def successful_probe() -> Probe:
    async def probe() -> None:
        return None

    return probe


def failed_probe(message: str) -> Probe:
    async def probe() -> None:
        raise RuntimeError(message)

    return probe


@pytest.mark.anyio
async def test_live_reports_process_health_without_dependency_checks() -> None:
    probes = {
        "postgres": failed_probe("internal database detail"),
        "redis": failed_probe("internal redis detail"),
        "object_storage": failed_probe("internal storage detail"),
    }
    transport = ASGITransport(app=create_app(settings(), probes=probes))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.anyio
async def test_ready_reports_each_healthy_dependency() -> None:
    probes = {
        "postgres": successful_probe(),
        "redis": successful_probe(),
        "object_storage": successful_probe(),
    }
    transport = ASGITransport(app=create_app(settings(), probes=probes))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "dependencies": {
            "postgres": "ready",
            "redis": "ready",
            "object_storage": "ready",
        },
    }


@pytest.mark.parametrize("failed_dependency", ["postgres", "redis", "object_storage"])
@pytest.mark.anyio
async def test_ready_returns_safe_independent_state_when_a_dependency_fails(
    failed_dependency: str,
) -> None:
    probes = {
        "postgres": successful_probe(),
        "redis": successful_probe(),
        "object_storage": successful_probe(),
    }
    probes[failed_dependency] = failed_probe("credential=must-not-leak")
    transport = ASGITransport(app=create_app(settings(), probes=probes))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["dependencies"][failed_dependency] == "not_ready"
    assert "credential" not in response.text


def test_settings_require_all_connection_and_credential_values() -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None)
