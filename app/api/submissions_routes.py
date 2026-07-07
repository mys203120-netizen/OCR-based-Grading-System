from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_instructor_id
from app.api.submission_helpers import (
    get_submission_for_instructor,
    storage_url,
    summary_from_row,
)
from app.core.database import get_session
from app.models import (
    ClassRoom,
    Exam,
    Student,
    StudentMatchStatus,
    Submission,
    SubmissionStatus,
    utcnow,
)
from app.schemas import (
    AssignStudentRequest,
    GradingResult,
    OcrResult,
    ReviewUpdate,
    SubmissionDetail,
)
from app.services.classes import student_belongs_to_class
from app.services.json_utils import dumps_model, loads_model

router = APIRouter(tags=["submissions"])


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
    summary = summary_from_row(submission, student, exam).model_dump()
    return SubmissionDetail(
        **summary,
        image_path=submission.image_path,
        image_url=storage_url(submission.image_path),
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
    submission = await get_submission_for_instructor(session, submission_id, instructor_id)
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
    submission = await get_submission_for_instructor(session, submission_id, instructor_id)
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
