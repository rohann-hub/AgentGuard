"""FastAPI entry point: `uvicorn app.main:app` from the backend/ directory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.dashboard import mount_dashboard
from app.api.limits import BodySizeLimit
from app.api.routes import agents, approvals, audit, health, overview, proxy
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.database.connection import get_engine


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    if get_engine.cache_info().currsize:
        await get_engine().dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        lifespan=lifespan,
    )
    app.add_middleware(BodySizeLimit, max_bytes=settings.max_request_bytes)
    if settings.cors_origins:
        # Exact origins only, no cookies: the dashboard sends the admin key as a header.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["X-Admin-Key", "Content-Type", "Accept"],
            allow_credentials=False,
            max_age=600,
        )
    app.include_router(health.router)
    for module in (agents, approvals, audit, overview):
        app.include_router(module.router, prefix=settings.api_prefix)
    app.include_router(proxy.router, prefix=settings.api_prefix)
    if settings.dashboard_dir:
        mount_dashboard(app, settings.dashboard_dir)
    return app


app = create_app()
