from __future__ import annotations

import platform

from app.core.config import get_settings


def main() -> None:
    try:
        from redis import Redis
        from rq import Queue, SimpleWorker, Worker
    except ImportError as exc:
        raise RuntimeError("redis/rq dependencies are required to run the worker") from exc

    settings = get_settings()
    redis = Redis.from_url(settings.redis_url)
    queue = Queue(settings.grading_queue_name, connection=redis)
    worker_cls = SimpleWorker if platform.system() == "Windows" else Worker
    worker = worker_cls([queue], connection=redis)
    worker.work()


if __name__ == "__main__":
    main()
