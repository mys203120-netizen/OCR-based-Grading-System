from __future__ import annotations

import asyncio
from typing import Protocol

from app.core.config import Settings
from app.services.jobs import JobRunner


class QueueEnqueueError(RuntimeError):
    pass


class JobQueue(Protocol):
    async def enqueue_grading_job(self, job_id: str) -> None:
        pass


class InlineJobQueue:
    """Local QA queue. It processes the job before returning the API response."""

    def __init__(self, runner: JobRunner) -> None:
        self.runner = runner

    async def enqueue_grading_job(self, job_id: str) -> None:
        await self.runner.process_job(job_id)


class RedisRqJobQueue:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def enqueue_grading_job(self, job_id: str) -> None:
        await asyncio.to_thread(self._enqueue_sync, job_id)

    def _enqueue_sync(self, job_id: str) -> None:
        try:
            from redis import Redis
            from rq import Queue
        except ImportError as exc:
            raise QueueEnqueueError("redis/rq dependencies are not installed") from exc

        try:
            redis = Redis.from_url(self.settings.redis_url)
            queue = Queue(self.settings.grading_queue_name, connection=redis)
            queue.enqueue(
                "app.workers.grading_worker.run_grading_job",
                job_id,
                job_timeout=self.settings.grading_job_timeout_seconds,
                result_ttl=self.settings.grading_job_result_ttl_seconds,
                failure_ttl=self.settings.grading_job_failure_ttl_seconds,
            )
        except Exception as exc:
            raise QueueEnqueueError(f"failed to enqueue grading job: {exc}") from exc


def build_job_queue(settings: Settings, runner: JobRunner) -> JobQueue:
    if settings.queue_provider == "inline":
        return InlineJobQueue(runner)
    return RedisRqJobQueue(settings)
