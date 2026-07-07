from __future__ import annotations

import asyncio

from app.core.config import get_settings
from app.core.database import create_database
from app.services.gemini_client import GeminiJsonClient, close_client
from app.services.jobs import JobRunner


def run_grading_job(job_id: str) -> None:
    asyncio.run(_run_grading_job(job_id))


async def _run_grading_job(job_id: str) -> None:
    settings = get_settings()
    settings.ensure_directories()
    database = create_database(settings)
    await database.init()
    ai_client = GeminiJsonClient(settings)
    runner = JobRunner(settings, ai_client, database.sessionmaker)
    try:
        await runner.process_job(job_id)
    finally:
        await close_client(ai_client)
        await database.dispose()
