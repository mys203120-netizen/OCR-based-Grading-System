from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.dashboard import router as dashboard_router
from app.api.roster import router as roster_router
from app.api.routes import router as api_router
from app.core.config import get_settings
from app.core.database import init_db
from app.services.gemini_client import GeminiJsonClient
from app.services.job_queue import build_job_queue
from app.services.jobs import JobRunner
from app.services.messaging import build_message_sender

settings = get_settings()
ai_client = GeminiJsonClient(settings)
job_runner = JobRunner(settings, ai_client)
grading_queue = build_job_queue(settings, job_runner)
message_sender = build_message_sender(settings)

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def on_startup() -> None:
    settings.ensure_directories()
    await init_db()


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "ai_provider": settings.ai_provider,
        "database": settings.database_url.split("://", maxsplit=1)[0],
        "queue_provider": settings.queue_provider,
        "message_provider": settings.message_provider,
    }


app.include_router(api_router, prefix=settings.api_v1_prefix, tags=["grading"])
app.include_router(roster_router, prefix=settings.api_v1_prefix)
app.include_router(dashboard_router, prefix=settings.api_v1_prefix)
app.mount("/storage", StaticFiles(directory=settings.storage_dir), name="storage")
