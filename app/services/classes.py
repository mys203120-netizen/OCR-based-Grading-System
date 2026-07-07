from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ClassRoom, Student, StudentClassEnrollment
from app.services.academic import current_grade_code, parse_grade_level

ALL_STUDENTS_CLASS_NAME = "전체 학생"

DEFAULT_CLASS_SPECS = [
    (ALL_STUDENTS_CLASS_NAME, "all_students", None),
    ("예비고1", "grade", 9),
    ("고1", "grade", 10),
    ("고2", "grade", 11),
    ("고3/N수", "grade", 12),
]


async def ensure_default_classes(session: AsyncSession, instructor_id: str) -> None:
    legacy_grade3 = await session.execute(
        select(ClassRoom)
        .where(ClassRoom.instructor_id == instructor_id)
        .where(ClassRoom.name == "고3")
    )
    legacy_class = legacy_grade3.scalar_one_or_none()
    if legacy_class is not None:
        legacy_class.name = "고3/N수"
        legacy_class.class_kind = "grade"
        legacy_class.grade_level_code = 12
        legacy_class.is_active = True

    for name, class_kind, grade_level_code in DEFAULT_CLASS_SPECS:
        result = await session.execute(
            select(ClassRoom)
            .where(ClassRoom.instructor_id == instructor_id)
            .where(ClassRoom.name == name)
        )
        class_room = result.scalar_one_or_none()
        if class_room is None:
            session.add(
                ClassRoom(
                    instructor_id=instructor_id,
                    name=name,
                    class_kind=class_kind,
                    grade_level_code=grade_level_code,
                )
            )
        else:
            class_room.class_kind = class_kind
            class_room.grade_level_code = grade_level_code
            class_room.is_active = True
    await session.flush()


async def student_belongs_to_class(
    session: AsyncSession,
    *,
    student: Student,
    class_room: ClassRoom,
) -> bool:
    if class_room.class_kind == "all_students":
        return True
    if class_room.class_kind == "grade":
        anchor_level = student.grade_anchor_level or parse_grade_level(student.grade_level)
        return (
            current_grade_code(anchor_level, student.grade_anchor_year)
            == class_room.grade_level_code
        )
    result = await session.execute(
        select(StudentClassEnrollment.id)
        .where(StudentClassEnrollment.student_id == student.id)
        .where(StudentClassEnrollment.class_id == class_room.id)
        .where(StudentClassEnrollment.is_active.is_(True))
    )
    return result.scalar_one_or_none() is not None
