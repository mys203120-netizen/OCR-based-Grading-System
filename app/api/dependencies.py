from __future__ import annotations

from typing import Annotated

from fastapi import Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ClassRoom, Exam, GradingJob, Instructor, Student


async def get_instructor_id(
    x_instructor_id: Annotated[str, Header(alias="X-Instructor-Id")],
) -> str:
    return x_instructor_id


async def ensure_instructor(session: AsyncSession, instructor_id: str) -> Instructor:
    instructor = await session.get(Instructor, instructor_id)
    if instructor is None:
        raise HTTPException(status_code=404, detail="instructor not found")
    return instructor


async def ensure_class_access(
    session: AsyncSession,
    *,
    instructor_id: str,
    class_id: str,
) -> ClassRoom:
    class_room = await session.get(ClassRoom, class_id)
    if class_room is None or class_room.instructor_id != instructor_id:
        raise HTTPException(status_code=404, detail="class not found")
    return class_room


async def ensure_job_access(
    session: AsyncSession,
    *,
    instructor_id: str,
    job_id: str,
) -> GradingJob:
    result = await session.execute(
        select(GradingJob)
        .join(Exam, Exam.id == GradingJob.exam_id)
        .join(ClassRoom, ClassRoom.id == Exam.class_id)
        .where(GradingJob.id == job_id)
        .where(ClassRoom.instructor_id == instructor_id)
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


async def ensure_student_access(
    session: AsyncSession,
    *,
    instructor_id: str,
    student_id: str,
) -> Student:
    result = await session.execute(
        select(Student)
        .where(Student.id == student_id)
        .where(Student.instructor_id == instructor_id)
    )
    student = result.scalar_one_or_none()
    if student is None:
        raise HTTPException(status_code=404, detail="student not found")
    return student
