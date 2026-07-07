from __future__ import annotations

import asyncio

from app.core.config import get_settings
from app.core.database import init_db
from app.services.gemini_client import GeminiJsonClient
from app.services.jobs import JobRunner


def run_grading_job(job_id: str) -> None:
    asyncio.run(_run_grading_job(job_id))


async def _run_grading_job(job_id: str) -> None:
    settings = get_settings()
    settings.ensure_directories()
    await init_db()
    ai_client = GeminiJsonClient(settings)
    runner = JobRunner(settings, ai_client)
    await runner.process_job(job_id)
