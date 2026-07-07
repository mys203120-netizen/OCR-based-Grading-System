from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.dashboard import router as dashboard_router
from app.api.roster import router as roster_router
from app.api.routes import router as api_router
from app.core.config import Settings, get_settings
from app.core.database import init_db
from app.services.gemini_client import GeminiJsonClient, close_client
from app.services.job_queue import build_job_queue
from app.services.jobs import JobRunner
from app.services.messaging import build_message_sender


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    app_settings.ensure_directories()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.ai_client = GeminiJsonClient(app_settings)
        app.state.job_runner = JobRunner(app_settings, app.state.ai_client)
        app.state.grading_queue = build_job_queue(app_settings, app.state.job_runner)
        app.state.message_sender = build_message_sender(app_settings)
        await init_db()
        try:
            yield
        finally:
            await close_client(app.state.ai_client)

    app = FastAPI(title=app_settings.app_name, lifespan=lifespan)
    app.state.settings = app_settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health(request: Request) -> dict:
        state_settings: Settings = request.app.state.settings
        return {
            "status": "ok",
            "ai_provider": state_settings.ai_provider,
            "database": state_settings.database_url.split("://", maxsplit=1)[0],
            "queue_provider": state_settings.queue_provider,
            "message_provider": state_settings.message_provider,
        }

    app.include_router(api_router, prefix=app_settings.api_v1_prefix)
    app.include_router(roster_router, prefix=app_settings.api_v1_prefix)
    app.include_router(dashboard_router, prefix=app_settings.api_v1_prefix)
    app.mount("/storage", StaticFiles(directory=app_settings.storage_dir), name="storage")
    return app


app = create_app()
