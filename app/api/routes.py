from __future__ import annotations

import json
import shutil
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import ensure_class_access, ensure_job_access, get_instructor_id
from app.core.config import get_settings
from app.core.database import get_session
from app.models import (
    ClassRoom,
    Exam,
    GradeBand,
    GradingJob,
    JobStatus,
    SmsMessage,
    Student,
    StudentMatchStatus,
    Submission,
    SubmissionStatus,
    utcnow,
)
from app.schemas import (
    AssignStudentRequest,
    ExamRead,
    ExamUpdate,
    GradingResult,
    JobCreateResponse,
    JobStatusResponse,
    MessageDraftCreate,
    MessageResponse,
    OcrResult,
    ReviewUpdate,
    StudentCandidate,
    SubmissionDetail,
    SubmissionSummary,
)
from app.services.classes import student_belongs_to_class
from app.services.comments import parse_comments_json
from app.services.job_queue import JobQueue, QueueEnqueueError
from app.services.jobs import JobRunner
from app.services.json_utils import dumps_model, loads_model
from app.services.messaging import MessageSender, MessageSendError

router = APIRouter()


def get_runner() -> JobRunner:
    from app.main import job_runner

    return job_runner


def get_job_queue() -> JobQueue:
    from app.main import grading_queue

    return grading_queue


def get_message_sender() -> MessageSender:
    from app.main import message_sender

    return message_sender


@router.post("/jobs", response_model=JobCreateResponse, status_code=202)
async def create_grading_job(
    pdf: UploadFile = File(...),
    class_id: str = Form(...),
    comments_json: str = Form(...),
    question_count: int = Form(10),
    instructor_id: str = Depends(get_instructor_id),
    session: AsyncSession = Depends(get_session),
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

    settings = get_settings()
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


@router.patch("/exams/{exam_id}", response_model=ExamRead)
async def update_exam(
    exam_id: str,
    payload: ExamUpdate,
    instructor_id: str = Depends(get_instructor_id),
    session: AsyncSession = Depends(get_session),
) -> ExamRead:
    result = await session.execute(
        select(Exam)
        .join(ClassRoom, ClassRoom.id == Exam.class_id)
        .where(Exam.id == exam_id)
        .where(ClassRoom.instructor_id == instructor_id)
    )
    exam = result.scalar_one_or_none()
    if exam is None:
        raise HTTPException(status_code=404, detail="exam not found")
    exam.exam_date = payload.exam_date
    await session.commit()
    await session.refresh(exam)
    return ExamRead.model_validate(exam, from_attributes=True)


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
        _summary_from_row(submission, student, exam)
        for submission, student, exam in result.all()
    ]


@router.get("/submissions/{submission_id}", response_model=SubmissionDetail)
async def get_submission(
    submission_id: str,
    instructor_id: str = Depends(get_instructor_id),
    session: AsyncSession = Depends(get_session),
) -> SubmissionDetail:
    result = await session.execute(
        select(Submission, Student, Exam)
        .join(Exam, Exam.id == Submission.exam_id)
        .join(ClassRoom, ClassRoom.id == Exam.class_id)
        .outerjoin(Student, Student.id == Submission.student_id)
        .where(Submission.id == submission_id)
        .where(ClassRoom.instructor_id == instructor_id)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="submission not found")
    submission, student, exam = row
    summary = _summary_from_row(submission, student, exam).model_dump()
    return SubmissionDetail(
        **summary,
        image_path=submission.image_path,
        image_url=_storage_url(submission.image_path),
        raw_ocr=loads_model(submission.raw_ocr_json, OcrResult),
        graded=loads_model(submission.graded_json, GradingResult),
        human_ocr=loads_model(submission.human_ocr_json, OcrResult),
        human_grade=loads_model(submission.human_grade_json, GradingResult),
    )


@router.patch("/submissions/{submission_id}/review", response_model=SubmissionDetail)
async def update_review(
    submission_id: str,
    payload: ReviewUpdate,
    instructor_id: str = Depends(get_instructor_id),
    session: AsyncSession = Depends(get_session),
) -> SubmissionDetail:
    submission = await _get_submission_for_instructor(session, submission_id, instructor_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="submission not found")

    if payload.human_ocr:
        submission.human_ocr_json = dumps_model(payload.human_ocr)
    if payload.human_grade:
        submission.human_grade_json = dumps_model(payload.human_grade)
        submission.total_score = payload.human_grade.total_score
        submission.max_score = payload.human_grade.max_score
        submission.grade_band = payload.human_grade.grade_band.value
        submission.needs_human_review = payload.human_grade.needs_human_review
    if payload.approve:
        submission.status = SubmissionStatus.APPROVED.value
        submission.needs_human_review = False
        submission.approved_at = utcnow()
    await session.commit()
    return await get_submission(submission_id, instructor_id, session)


@router.post("/submissions/{submission_id}/assign-student", response_model=SubmissionDetail)
async def assign_student(
    submission_id: str,
    payload: AssignStudentRequest,
    instructor_id: str = Depends(get_instructor_id),
    session: AsyncSession = Depends(get_session),
) -> SubmissionDetail:
    submission = await _get_submission_for_instructor(session, submission_id, instructor_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="submission not found")

    result = await session.execute(
        select(Student)
        .where(Student.id == payload.student_id)
        .where(Student.instructor_id == instructor_id)
        .where(Student.is_active.is_(True))
    )
    student = result.scalar_one_or_none()
    if student is None:
        raise HTTPException(status_code=400, detail="student is not owned by this instructor")
    exam = await session.get(Exam, submission.exam_id)
    class_room = await session.get(ClassRoom, exam.class_id) if exam else None
    if class_room is None or not await student_belongs_to_class(
        session,
        student=student,
        class_room=class_room,
    ):
        raise HTTPException(status_code=400, detail="student is not in the selected class")

    submission.student_id = student.id
    submission.student_match_status = StudentMatchStatus.MANUAL_MATCHED.value
    submission.needs_human_review = False
    await session.commit()
    return await get_submission(submission_id, instructor_id, session)


@router.post("/submissions/{submission_id}/messages/draft", response_model=MessageResponse)
async def create_message_draft(
    submission_id: str,
    payload: MessageDraftCreate,
    instructor_id: str = Depends(get_instructor_id),
    session: AsyncSession = Depends(get_session),
) -> MessageResponse:
    submission = await _get_submission_for_instructor(session, submission_id, instructor_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="submission not found")
    if submission.student_id is None:
        raise HTTPException(status_code=400, detail="student must be assigned before messaging")
    student = await session.get(Student, submission.student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="student not found")

    phone = student.parent_phone if payload.recipient == "parent" else student.student_phone
    if not phone:
        raise HTTPException(status_code=400, detail=f"{payload.recipient} phone is empty")
    graded = loads_model(submission.human_grade_json, GradingResult) or loads_model(
        submission.graded_json,
        GradingResult,
    )
    body = payload.body or (graded.parent_sms_draft if graded else None)
    if not body:
        body = f"{student.name} 학생의 서술형 채점 결과가 등록되었습니다."
    settings = get_settings()
    message = SmsMessage(
        submission_id=submission.id,
        phone=phone,
        body=body,
        status="draft",
        channel="kakao",
        provider=settings.message_provider,
    )
    session.add(message)
    await session.commit()
    await session.refresh(message)
    return _message_response(message)


@router.post("/messages/{message_id}/send", response_model=MessageResponse)
async def send_message(
    message_id: str,
    instructor_id: str = Depends(get_instructor_id),
    session: AsyncSession = Depends(get_session),
    sender: MessageSender = Depends(get_message_sender),
) -> MessageResponse:
    result = await session.execute(
        select(SmsMessage)
        .join(Submission, Submission.id == SmsMessage.submission_id)
        .join(Exam, Exam.id == Submission.exam_id)
        .join(ClassRoom, ClassRoom.id == Exam.class_id)
        .where(SmsMessage.id == message_id)
        .where(ClassRoom.instructor_id == instructor_id)
    )
    message = result.scalar_one_or_none()
    if message is None:
        raise HTTPException(status_code=404, detail="message not found")
    if message.status in {"queued", "sent"}:
        return _message_response(message)

    message.status = "queued"
    message.error_message = None
    await session.commit()
    try:
        send_result = await sender.send_kakao(phone=message.phone, body=message.body)
    except MessageSendError as exc:
        message.status = "failed"
        message.error_message = str(exc)
        await session.commit()
        await session.refresh(message)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    message.status = send_result.status
    message.provider_message_id = send_result.provider_message_id
    message.provider_payload_json = send_result.raw_response
    message.sent_at = utcnow()
    await session.commit()
    await session.refresh(message)
    return _message_response(message)


async def _get_submission_for_instructor(
    session: AsyncSession,
    submission_id: str,
    instructor_id: str,
) -> Submission | None:
    result = await session.execute(
        select(Submission)
        .join(Exam, Exam.id == Submission.exam_id)
        .join(ClassRoom, ClassRoom.id == Exam.class_id)
        .where(Submission.id == submission_id)
        .where(ClassRoom.instructor_id == instructor_id)
    )
    return result.scalar_one_or_none()


def _summary_from_row(
    submission: Submission,
    student: Student | None,
    exam: Exam | None,
) -> SubmissionSummary:
    candidates = [
        StudentCandidate.model_validate(candidate)
        for candidate in (json.loads(submission.student_candidates_json or "[]"))
    ]
    return SubmissionSummary(
        submission_id=submission.id,
        exam_id=submission.exam_id,
        exam_title=exam.title if exam else None,
        exam_date=exam.exam_date if exam else None,
        page_number=submission.page_number,
        status=SubmissionStatus(submission.status),
        student_id=submission.student_id,
        student_name=student.name if student else None,
        student_match_status=StudentMatchStatus(submission.student_match_status),
        student_candidates=candidates,
        total_score=submission.total_score,
        max_score=submission.max_score,
        grade_band=GradeBand(submission.grade_band) if submission.grade_band else None,
        needs_human_review=submission.needs_human_review,
        error_message=submission.error_message,
    )


def _message_response(message: SmsMessage) -> MessageResponse:
    return MessageResponse(
        id=message.id,
        submission_id=message.submission_id,
        phone=message.phone,
        body=message.body,
        status=message.status,
        channel=message.channel,
        provider=message.provider,
        provider_message_id=message.provider_message_id,
        error_message=message.error_message,
        created_at=message.created_at,
        sent_at=message.sent_at,
    )


def _storage_url(path: str) -> str:
    normalized = path.replace("\\", "/")
    if normalized.startswith("storage/"):
        return "/" + normalized
    return f"/storage/{normalized}"
