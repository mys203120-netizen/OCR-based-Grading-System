from __future__ import annotations

import shutil
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    ensure_class_access,
    ensure_job_access,
    get_app_settings,
    get_instructor_id,
    get_job_queue,
    get_runner,
)
from app.api.submission_helpers import summary_from_row
from app.core.config import Settings
from app.core.database import get_session
from app.models import Exam, GradingJob, JobStatus, Student, Submission
from app.schemas import JobCreateResponse, JobStatusResponse, SubmissionSummary
from app.services.comments import parse_comments_json
from app.services.job_queue import JobQueue, QueueEnqueueError
from app.services.jobs import JobRunner

router = APIRouter(tags=["grading"])


@router.post("/jobs", response_model=JobCreateResponse, status_code=202)
async def create_grading_job(
    pdf: UploadFile = File(...),
    class_id: str = Form(...),
    comments_json: str = Form(...),
    question_count: int = Form(10),
    instructor_id: str = Depends(get_instructor_id),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
    runner: JobRunner = Depends(get_runner),
    queue: JobQueue = Depends(get_job_queue),
) -> JobCreateResponse:
    if not pdf.filename or not pdf.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="pdf upload is required")
    class_room = await ensure_class_access(session, instructor_id=instructor_id, class_id=class_id)
    try:
        comments = parse_comments_json(comments_json, question_count)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    settings.ensure_directories()
    temp_path = settings.upload_dir / f"tmp_{id(pdf)}.pdf"
    with temp_path.open("wb") as output:
        shutil.copyfileobj(pdf.file, output)

    upload_date = date.today()
    job = await runner.create_job(
        title=f"{upload_date.isoformat()} {class_room.name} 서술형",
        pdf_temp_path=temp_path,
        comments=comments,
        question_count=question_count,
        class_id=class_id,
        exam_date=upload_date,
    )
    try:
        await queue.enqueue_grading_job(job.id)
    except QueueEnqueueError as exc:
        await runner.mark_job_failed(job.id, str(exc))
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    exam = await session.get(Exam, job.exam_id)
    current_job = await session.get(GradingJob, job.id)
    return JobCreateResponse(
        job_id=job.id,
        exam_id=job.exam_id,
        class_id=exam.class_id if exam else class_id,
        status=JobStatus(current_job.status if current_job else job.status),
    )


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job(
    job_id: str,
    instructor_id: str = Depends(get_instructor_id),
    session: AsyncSession = Depends(get_session),
) -> JobStatusResponse:
    job = await ensure_job_access(session, instructor_id=instructor_id, job_id=job_id)
    exam = await session.get(Exam, job.exam_id)
    return JobStatusResponse(
        job_id=job.id,
        exam_id=job.exam_id,
        class_id=exam.class_id if exam else None,
        status=JobStatus(job.status),
        total_pages=job.total_pages,
        processed_pages=job.processed_pages,
        failed_pages=job.failed_pages,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


@router.get("/jobs/{job_id}/submissions", response_model=list[SubmissionSummary])
async def list_job_submissions(
    job_id: str,
    instructor_id: str = Depends(get_instructor_id),
    session: AsyncSession = Depends(get_session),
) -> list[SubmissionSummary]:
    await ensure_job_access(session, instructor_id=instructor_id, job_id=job_id)
    result = await session.execute(
        select(Submission, Student, Exam)
        .join(Exam, Exam.id == Submission.exam_id)
        .outerjoin(Student, Student.id == Submission.student_id)
        .where(Submission.job_id == job_id)
        .order_by(Submission.page_number)
    )
    return [
        summary_from_row(submission, student, exam)
        for submission, student, exam in result.all()
    ]
