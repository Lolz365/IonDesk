import asyncio
import uuid
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import boto3
import redis.asyncio as redis
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.exceptions import HTTPException

from app.api.dependencies import RateLimitPassthrough, TokenValidator
from app.api.v1 import router as api_v1_router
from app.db.session import create_db_engine, create_session_factory
from app.services.api_keys import APIKeyNotFound
from app.services.authentication import OIDCJWTValidator
from app.services.authorization import AuthenticationRequired, AuthorizationDenied
from app.services.organizations import OrganizationNotFound, TransactionConflict
from app.services.rate_limits import RateLimiter, RateLimitExceeded, RedisRateLimiter
from app.services.tickets import TicketNotFound
from app.settings import Settings

Probe = Callable[[], Awaitable[None]]


def dependency_probes(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, Probe]:
    async def postgres() -> None:
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))

    async def redis_server() -> None:
        client = redis.from_url(settings.redis_url)
        try:
            await client.ping()
        finally:
            await client.aclose()

    async def object_storage() -> None:
        def head_bucket() -> None:
            client = boto3.client(
                "s3",
                endpoint_url=settings.object_storage_endpoint,
                region_name=settings.object_storage_region,
                aws_access_key_id=settings.object_storage_access_key,
                aws_secret_access_key=settings.object_storage_secret_key,
            )
            client.head_bucket(Bucket=settings.object_storage_bucket)

        await asyncio.to_thread(head_bucket)

    return {
        "postgres": postgres,
        "redis": redis_server,
        "object_storage": object_storage,
    }


async def _run_probe(probe: Probe, max_wait: float) -> str:
    try:
        await asyncio.wait_for(probe(), timeout=max_wait)
    except Exception:
        return "not_ready"
    return "ready"


def create_app(
    settings: Settings | None = None,
    *,
    probes: Mapping[str, Probe] | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    oidc_validator: TokenValidator | None = None,
    rate_limiter: RateLimiter | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings()
    if session_factory is None:
        engine = create_db_engine(resolved_settings)
        resolved_session_factory = create_session_factory(engine)
    else:
        resolved_session_factory = session_factory
    resolved_probes = dict(
        probes or dependency_probes(resolved_settings, resolved_session_factory)
    )
    app = FastAPI(
        title="VisualOps API",
        version="0.1.0",
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        redoc_url=None,
    )
    app.state.session_factory = resolved_session_factory
    app.state.settings = resolved_settings
    app.state.oidc_validator = oidc_validator or OIDCJWTValidator(
        issuer=resolved_settings.oidc_issuer,
        audience=resolved_settings.oidc_audience,
        jwks_url=resolved_settings.oidc_jwks_url,
        cache_seconds=resolved_settings.oidc_jwks_cache_seconds,
    )
    app.state.rate_limiter = rate_limiter or RedisRateLimiter(
        resolved_settings.redis_url
    )

    def error_response(
        request: Request, status_code: int, code: str, message: str
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        return JSONResponse(
            {"error": {"code": code, "message": message, "request_id": request_id}},
            status_code=status_code,
            headers={"x-request-id": request_id, "cache-control": "no-store"},
        )

    @app.middleware("http")
    async def request_context(request: Request, call_next: Callable[..., Any]) -> Any:
        supplied = request.headers.get("x-request-id")
        try:
            request_id = str(uuid.UUID(supplied)) if supplied else str(uuid.uuid4())
        except ValueError:
            request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        return response

    @app.exception_handler(AuthenticationRequired)
    async def authentication_error(request: Request, _: Exception) -> JSONResponse:
        return error_response(
            request, 401, "authentication_required", "Authentication required."
        )

    @app.exception_handler(AuthorizationDenied)
    async def authorization_error(request: Request, _: Exception) -> JSONResponse:
        return error_response(
            request,
            403,
            "forbidden",
            "You do not have permission to perform this action.",
        )

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_error(request: Request, _: Exception) -> JSONResponse:
        return error_response(
            request, 429, "rate_limit_exceeded", "Rate limit exceeded."
        )

    @app.exception_handler(RateLimitPassthrough)
    async def rate_limit_unavailable(request: Request, _: Exception) -> JSONResponse:
        return error_response(
            request, 503, "service_unavailable", "Service temporarily unavailable."
        )

    @app.exception_handler(APIKeyNotFound)
    async def api_key_not_found(request: Request, _: Exception) -> JSONResponse:
        return error_response(request, 404, "api_key_not_found", "API key not found.")

    @app.exception_handler(OrganizationNotFound)
    async def organization_not_found(request: Request, _: Exception) -> JSONResponse:
        return error_response(
            request, 404, "organization_not_found", "Organization not found."
        )

    @app.exception_handler(TicketNotFound)
    async def ticket_not_found(request: Request, _: Exception) -> JSONResponse:
        return error_response(request, 404, "ticket_not_found", "Ticket not found.")

    @app.exception_handler(TransactionConflict)
    async def transaction_conflict(request: Request, _: Exception) -> JSONResponse:
        return error_response(
            request,
            409,
            "transaction_conflict",
            "The operation conflicts with existing data.",
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, _: Exception) -> JSONResponse:
        return error_response(
            request, 422, "validation_error", "The request is invalid."
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        return error_response(
            request, error.status_code, "http_error", "Request failed."
        )

    @app.exception_handler(Exception)
    async def internal_error(request: Request, _: Exception) -> JSONResponse:
        return error_response(
            request, 500, "internal_error", "An unexpected error occurred."
        )

    @app.get("/health/live", tags=["health"])
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    async def ready() -> JSONResponse:
        states = dict(
            zip(
                resolved_probes,
                await asyncio.gather(
                    *(
                        _run_probe(probe, resolved_settings.readiness_timeout_seconds)
                        for probe in resolved_probes.values()
                    )
                ),
                strict=True,
            )
        )
        is_ready = all(state == "ready" for state in states.values())
        body: dict[str, Any] = {
            "status": "ready" if is_ready else "not_ready",
            "dependencies": states,
        }
        return JSONResponse(body, status_code=200 if is_ready else 503)

    app.include_router(api_v1_router)
    return app
