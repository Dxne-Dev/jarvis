"""Fabrique de l'application FastAPI du moteur."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from ojarvis import __version__
from ojarvis.api import routes_core, routes_secrets, routes_stream
from ojarvis.config import EngineConfig
from ojarvis.core.errors import install_error_handlers
from ojarvis.security.auth import CorrelationIdMiddleware, TokenAuthMiddleware
from ojarvis.security.redaction import REDACTOR
from ojarvis.security.secrets import SecretBackend
from ojarvis.services import Services

PUBLIC_PATHS = frozenset({"/health"})


def create_app(
    config: EngineConfig,
    *,
    token: str,
    secret_backend: SecretBackend | None = None,
    http_transport: httpx.AsyncBaseTransport | None = None,
    on_ready: Callable[[], None] | None = None,
) -> FastAPI:
    if len(token) < 32:
        raise ValueError("jeton trop court")
    REDACTOR.add_value(token)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        services = await Services.start(
            config, secret_backend=secret_backend, http_transport=http_transport
        )
        app.state.services = services
        if on_ready is not None:
            on_ready()
        try:
            yield
        finally:
            await services.stop()

    app = FastAPI(
        title="O-jarvis — moteur",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if config.dev_mode else None,
        redoc_url=None,
        openapi_url="/openapi.json" if config.dev_mode else None,
    )
    app.state.token = token
    install_error_handlers(app)
    app.include_router(routes_core.public)
    app.include_router(routes_core.router)
    app.include_router(routes_secrets.router)
    app.include_router(routes_stream.router)

    # Ordre : le dernier ajouté est le plus externe.
    app.add_middleware(TokenAuthMiddleware, token=token, public_paths=PUBLIC_PATHS)
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.allowed_origins),
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Correlation-ID"],
        expose_headers=["X-Correlation-ID"],
        max_age=600,
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(config.allowed_hosts))
    return app
