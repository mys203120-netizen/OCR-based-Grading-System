from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_instructor_id
from app.core.database import get_session
from app.models import ClassRoom, Exam
from app.schemas import ExamRead, ExamUpdate

router = APIRouter(tags=["exams"])


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
