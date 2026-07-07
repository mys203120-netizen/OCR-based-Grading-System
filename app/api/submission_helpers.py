from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ClassRoom,
    Exam,
    GradeBand,
    SmsMessage,
    Student,
    StudentMatchStatus,
    Submission,
    SubmissionStatus,
)
from app.schemas import MessageResponse, StudentCandidate, SubmissionSummary


async def get_submission_for_instructor(
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


def summary_from_row(
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


def message_response(message: SmsMessage) -> MessageResponse:
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


def storage_url(path: str) -> str:
    normalized = path.replace("\\", "/")
    if normalized.startswith("storage/"):
        return "/" + normalized
    return f"/storage/{normalized}"
