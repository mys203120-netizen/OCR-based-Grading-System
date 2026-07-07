from __future__ import annotations

from fastapi import APIRouter

from app.api.exams_routes import router as exams_router
from app.api.jobs_routes import router as jobs_router
from app.api.messages_routes import router as messages_router
from app.api.submissions_routes import router as submissions_router

router = APIRouter()
router.include_router(jobs_router)
router.include_router(exams_router)
router.include_router(submissions_router)
router.include_router(messages_router)
