from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import ensure_student_access, get_instructor_id
from app.core.database import get_session
from app.models import (
    ClassRoom,
    Exam,
    GradeBand,
    GradingJob,
    Student,
    Submission,
)
from app.schemas import DashboardOverview, RankingRow, StudentGrowthResponse, TrendPoint
from app.services.policy import infer_growth_label

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/overview", response_model=DashboardOverview)
async def overview(
    instructor_id: str = Depends(get_instructor_id),
    session: AsyncSession = Depends(get_session),
) -> DashboardOverview:
    exams = await session.scalar(
        select(func.count())
        .select_from(Exam)
        .join(ClassRoom, ClassRoom.id == Exam.class_id)
        .where(ClassRoom.instructor_id == instructor_id)
    )
    jobs = await session.scalar(
        select(func.count())
        .select_from(GradingJob)
        .join(Exam, Exam.id == GradingJob.exam_id)
        .join(ClassRoom, ClassRoom.id == Exam.class_id)
        .where(ClassRoom.instructor_id == instructor_id)
    )
    submissions = await session.scalar(
        select(func.count())
        .select_from(Submission)
        .join(Exam, Exam.id == Submission.exam_id)
        .join(ClassRoom, ClassRoom.id == Exam.class_id)
        .where(ClassRoom.instructor_id == instructor_id)
    )
    students = await session.scalar(
        select(func.count())
        .select_from(Student)
        .where(Student.instructor_id == instructor_id)
        .where(Student.is_active.is_(True))
    )
    pending_review = await session.scalar(
        select(func.count())
        .select_from(Submission)
        .join(Exam, Exam.id == Submission.exam_id)
        .join(ClassRoom, ClassRoom.id == Exam.class_id)
        .where(ClassRoom.instructor_id == instructor_id)
        .where(Submission.needs_human_review.is_(True))
    )
    return DashboardOverview(
        exams=exams or 0,
        jobs=jobs or 0,
        submissions=submissions or 0,
        students=students or 0,
        pending_review=pending_review or 0,
    )


@router.get("/rankings", response_model=list[RankingRow])
async def rankings(
    exam_id: str = Query(...),
    instructor_id: str = Depends(get_instructor_id),
    session: AsyncSession = Depends(get_session),
) -> list[RankingRow]:
    result = await session.execute(
        select(Submission, Student)
        .join(Exam, Exam.id == Submission.exam_id)
        .join(ClassRoom, ClassRoom.id == Exam.class_id)
        .join(Student, Student.id == Submission.student_id)
        .where(Submission.exam_id == exam_id)
        .where(ClassRoom.instructor_id == instructor_id)
        .where(Submission.total_score.is_not(None))
        .order_by(
            (Submission.total_score / Submission.max_score).desc(),
            Submission.total_score.desc(),
        )
    )
    rows = result.all()
    ranking: list[RankingRow] = []
    previous_percentage: float | None = None
    rank = 0
    for index, (submission, student) in enumerate(rows, start=1):
        percentage = (submission.total_score / submission.max_score) * 100
        if previous_percentage is None or percentage != previous_percentage:
            rank = index
            previous_percentage = percentage
        ranking.append(
            RankingRow(
                rank=rank,
                student_id=student.id,
                student_name=student.name,
                total_score=submission.total_score,
                max_score=submission.max_score,
                percentage=round(percentage, 2),
                grade_band=GradeBand(submission.grade_band),
                page_number=submission.page_number,
                needs_human_review=submission.needs_human_review,
            )
        )
    return ranking


@router.get("/students/{student_id}/growth", response_model=StudentGrowthResponse)
async def student_growth(
    student_id: str,
    instructor_id: str = Depends(get_instructor_id),
    session: AsyncSession = Depends(get_session),
) -> StudentGrowthResponse:
    student = await ensure_student_access(
        session,
        instructor_id=instructor_id,
        student_id=student_id,
    )

    result = await session.execute(
        select(Submission, Exam)
        .join(Exam, Exam.id == Submission.exam_id)
        .join(ClassRoom, ClassRoom.id == Exam.class_id)
        .where(Submission.student_id == student_id)
        .where(ClassRoom.instructor_id == instructor_id)
        .where(Submission.total_score.is_not(None))
        .order_by(Submission.created_at)
    )
    trend: list[TrendPoint] = []
    percentages: list[float] = []
    for submission, exam in result.all():
        percentage = (submission.total_score / submission.max_score) * 100
        percentages.append(percentage)
        trend.append(
            TrendPoint(
                exam_id=exam.id,
                exam_title=exam.title,
                submitted_at=submission.created_at,
                total_score=submission.total_score,
                max_score=submission.max_score,
                percentage=round(percentage, 2),
                grade_band=GradeBand(submission.grade_band),
            )
        )
    growth_label, expectation = infer_growth_label(percentages)
    return StudentGrowthResponse(
        student_id=student.id,
        student_name=student.name,
        trend=trend,
        growth_label=growth_label,
        next_exam_expectation=expectation,
    )
