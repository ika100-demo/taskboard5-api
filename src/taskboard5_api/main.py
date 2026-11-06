"""FastAPI entry point for taskboard5-api."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import structlog
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from . import __version__
from .logging_config import configure_logging
from .metrics import MetricsMiddleware
from .tasks import router as tasks_router
from .tasks.store import StorageUnavailableError, TaskStore, get_task_store, task_store_for
from .tracing import configure_tracing, tracing_enabled

configure_logging(level=os.environ.get("LOG_LEVEL", "INFO"))
if tracing_enabled():
    configure_tracing()

logger = structlog.get_logger(__name__)


class HealthResponse(BaseModel):
    status: str


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        task_store_for(app).ensure_schema()
    except StorageUnavailableError:
        logger.warning("schema_setup_deferred", reason="task storage unavailable at startup")
    yield


async def _storage_unavailable(_request: Request, _exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": "Task storage unavailable"})


def create_app(database_url: str | None = None) -> FastAPI:
    """Build the application; the database comes from the argument or DATABASE_URL."""
    app = FastAPI(title="taskboard5-api", version=__version__, lifespan=_lifespan)
    app.state.database_url = database_url
    app.add_middleware(MetricsMiddleware)
    app.include_router(tasks_router)
    app.add_exception_handler(StorageUnavailableError, _storage_unavailable)

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        """Liveness probe — returns 200 as long as the process is responding."""
        return HealthResponse(status="ok")

    @app.get("/ready", response_model=HealthResponse)
    def ready(store: Annotated[TaskStore, Depends(get_task_store)]) -> Response:
        """Readiness probe — 200 when the database answers, else 503."""
        if store.ping():
            return JSONResponse(content={"status": "ready"})
        return JSONResponse(status_code=503, content={"status": "not ready"})

    @app.get("/ping")
    def ping() -> dict[str, str]:
        """Simple ping endpoint."""
        return {"pong": "taskboard5-api"}

    @app.get("/metrics")
    def metrics() -> Response:
        """Prometheus scrape endpoint."""
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
