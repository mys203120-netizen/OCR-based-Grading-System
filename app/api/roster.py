from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    ensure_class_access,
    ensure_instructor,
    ensure_student_access,
    get_instructor_id,
)
from app.core.database import get_session
from app.models import (
    ClassRoom,
    Exam,
    Instructor,
    Student,
    StudentClassEnrollment,
    Submission,
    utcnow,
)
from app.schemas import (
    ClassCreate,
    ClassRead,
    InstructorCreate,
    InstructorRead,
    StudentCreate,
    StudentExamRecord,
    StudentExamSummary,
    StudentRead,
    StudentUpdate,
)
from app.services.academic import (
    academic_year,
    current_grade_code,
    current_grade_label,
    parse_grade_level,
)
from app.services.classes import ensure_default_classes, student_belongs_to_class

router = APIRouter(tags=["roster"])


@router.post("/instructors", response_model=InstructorRead)
async def create_instructor(
    payload: InstructorCreate,
    session: AsyncSession = Depends(get_session),
) -> InstructorRead:
    instructor = Instructor(name=payload.name, phone=payload.phone, email=payload.email)
    session.add(instructor)
    await session.flush()
    await ensure_default_classes(session, instructor.id)
    await session.commit()
    await session.refresh(instructor)
    return InstructorRead.model_validate(instructor, from_attributes=True)


@router.get("/instructors", response_model=list[InstructorRead])
async def list_instructors(session: AsyncSession = Depends(get_session)) -> list[InstructorRead]:
    result = await session.execute(select(Instructor).order_by(Instructor.name))
    return [
        InstructorRead.model_validate(instructor, from_attributes=True)
        for instructor in result.scalars().all()
    ]


@router.post("/classes", response_model=ClassRead)
async def create_class(
    payload: ClassCreate,
    instructor_id: str = Depends(get_instructor_id),
    session: AsyncSession = Depends(get_session),
) -> ClassRead:
    await ensure_instructor(session, instructor_id)
    class_room = ClassRoom(
        instructor_id=instructor_id,
        name=payload.name,
        description=payload.description,
    )
    session.add(class_room)
    await session.commit()
    await session.refresh(class_room)
    return ClassRead.model_validate(class_room, from_attributes=True)


@router.get("/classes", response_model=list[ClassRead])
async def list_classes(
    instructor_id: str = Depends(get_instructor_id),
    session: AsyncSession = Depends(get_session),
) -> list[ClassRead]:
    await ensure_default_classes(session, instructor_id)
    await session.commit()
    result = await session.execute(
        select(ClassRoom)
        .where(ClassRoom.instructor_id == instructor_id)
        .where(ClassRoom.is_active.is_(True))
        .order_by(ClassRoom.name)
    )
    return [
        ClassRead.model_validate(class_room, from_attributes=True)
        for class_room in result.scalars().all()
    ]


@router.post("/students", response_model=StudentRead)
async def create_student(
    payload: StudentCreate,
    instructor_id: str = Depends(get_instructor_id),
    session: AsyncSession = Depends(get_session),
) -> StudentRead:
    for class_id in payload.class_ids:
        await ensure_class_access(session, instructor_id=instructor_id, class_id=class_id)

    anchor_level = parse_grade_level(payload.grade_level)
    anchor_year = payload.grade_anchor_year or academic_year()
    student = Student(
        instructor_id=instructor_id,
        name=payload.name,
        parent_phone=payload.parent_phone,
        student_phone=payload.student_phone,
        phone=payload.student_phone,
        level_band=payload.level_band,
        grade_level=payload.grade_level,
        grade_anchor_level=anchor_level,
        grade_anchor_year=anchor_year if anchor_level is not None else None,
        school=payload.school,
        memo=payload.memo,
        external_id=payload.external_id,
    )
    session.add(student)
    await session.flush()
    for class_id in payload.class_ids:
        session.add(StudentClassEnrollment(student_id=student.id, class_id=class_id))
    await session.commit()
    await session.refresh(student)
    return await _student_read(session, student)


@router.get("/students", response_model=list[StudentRead])
async def list_students(
    class_id: str | None = Query(None),
    name: str | None = Query(None),
    instructor_id: str = Depends(get_instructor_id),
    session: AsyncSession = Depends(get_session),
) -> list[StudentRead]:
    query = (
        select(Student)
        .where(Student.instructor_id == instructor_id)
        .where(Student.is_active.is_(True))
        .order_by(Student.name, Student.school, Student.grade_level)
    )
    if class_id:
        class_room = await ensure_class_access(
            session,
            instructor_id=instructor_id,
            class_id=class_id,
        )
    if name:
        query = query.where(Student.name.contains(name))

    result = await session.execute(query)
    students = list(dict.fromkeys(result.scalars().all()))
    if class_id:
        students = [
            student
            for student in students
            if await student_belongs_to_class(session, student=student, class_room=class_room)
        ]
    return [await _student_read(session, student) for student in students]


@router.get("/students/{student_id}", response_model=StudentRead)
async def get_student(
    student_id: str,
    instructor_id: str = Depends(get_instructor_id),
    session: AsyncSession = Depends(get_session),
) -> StudentRead:
    student = await ensure_student_access(
        session,
        instructor_id=instructor_id,
        student_id=student_id,
    )
    return await _student_read(session, student)


@router.patch("/students/{student_id}", response_model=StudentRead)
async def update_student(
    student_id: str,
    payload: StudentUpdate,
    instructor_id: str = Depends(get_instructor_id),
    session: AsyncSession = Depends(get_session),
) -> StudentRead:
    student = await ensure_student_access(
        session,
        instructor_id=instructor_id,
        student_id=student_id,
    )
    updates = payload.model_dump(exclude_unset=True, exclude={"class_ids"})
    for key, value in updates.items():
        if key not in {"grade_level", "grade_anchor_year"}:
            setattr(student, key, value)
    if "student_phone" in updates:
        student.phone = updates["student_phone"]
    if "grade_level" in updates:
        student.grade_level = payload.grade_level
        student.grade_anchor_level = parse_grade_level(payload.grade_level)
        student.grade_anchor_year = (
            payload.grade_anchor_year or academic_year()
            if student.grade_anchor_level is not None
            else None
        )
    elif "grade_anchor_year" in updates:
        student.grade_anchor_year = payload.grade_anchor_year

    if payload.class_ids is not None:
        for class_id in payload.class_ids:
            await ensure_class_access(session, instructor_id=instructor_id, class_id=class_id)
        existing = await _student_class_ids(session, student.id)
        requested = set(payload.class_ids)
        for class_id in requested - set(existing):
            session.add(StudentClassEnrollment(student_id=student.id, class_id=class_id))
        result = await session.execute(
            select(StudentClassEnrollment).where(StudentClassEnrollment.student_id == student.id)
        )
        for enrollment in result.scalars().all():
            enrollment.is_active = enrollment.class_id in requested

    await session.commit()
    await session.refresh(student)
    return await _student_read(session, student)


@router.delete("/students/{student_id}", response_model=StudentRead)
async def delete_student(
    student_id: str,
    instructor_id: str = Depends(get_instructor_id),
    session: AsyncSession = Depends(get_session),
) -> StudentRead:
    student = await ensure_student_access(
        session,
        instructor_id=instructor_id,
        student_id=student_id,
    )
    student.is_active = False
    student.deleted_at = utcnow()
    result = await session.execute(
        select(StudentClassEnrollment).where(StudentClassEnrollment.student_id == student.id)
    )
    for enrollment in result.scalars().all():
        enrollment.is_active = False
    await session.commit()
    await session.refresh(student)
    return await _student_read(session, student)


@router.get("/students/{student_id}/exams", response_model=list[StudentExamSummary])
async def list_student_exams(
    student_id: str,
    instructor_id: str = Depends(get_instructor_id),
    session: AsyncSession = Depends(get_session),
) -> list[StudentExamSummary]:
    await ensure_student_access(session, instructor_id=instructor_id, student_id=student_id)
    result = await session.execute(
        select(Submission, Exam)
        .join(Exam, Exam.id == Submission.exam_id)
        .join(ClassRoom, ClassRoom.id == Exam.class_id)
        .where(Submission.student_id == student_id)
        .where(ClassRoom.instructor_id == instructor_id)
        .order_by(Exam.exam_date.desc(), Submission.created_at.desc())
    )
    grouped: dict[str, list[tuple[Submission, Exam]]] = {}
    for submission, exam in result.all():
        grouped.setdefault(exam.id, []).append((submission, exam))
    summaries = [_student_exam_summary(rows) for rows in grouped.values()]
    return sorted(
        summaries,
        key=lambda item: (item.exam_date is not None, item.exam_date, item.latest_submitted_at),
        reverse=True,
    )


@router.get(
    "/students/{student_id}/exams/{exam_id}/submissions",
    response_model=list[StudentExamRecord],
)
async def list_student_exam_submissions(
    student_id: str,
    exam_id: str,
    instructor_id: str = Depends(get_instructor_id),
    session: AsyncSession = Depends(get_session),
) -> list[StudentExamRecord]:
    await ensure_student_access(session, instructor_id=instructor_id, student_id=student_id)
    result = await session.execute(
        select(Submission, Exam)
        .join(Exam, Exam.id == Submission.exam_id)
        .join(ClassRoom, ClassRoom.id == Exam.class_id)
        .where(Submission.student_id == student_id)
        .where(Submission.exam_id == exam_id)
        .where(ClassRoom.instructor_id == instructor_id)
        .order_by(Submission.page_number)
    )
    return [
        _student_exam_record(submission, exam)
        for submission, exam in result.all()
    ]


async def _student_read(session: AsyncSession, student: Student) -> StudentRead:
    anchor_level = student.grade_anchor_level or parse_grade_level(student.grade_level)
    return StudentRead(
        id=student.id,
        name=student.name,
        parent_phone=student.parent_phone,
        student_phone=student.student_phone,
        level_band=student.level_band,
        grade_level=student.grade_level,
        grade_anchor_level=anchor_level,
        grade_anchor_year=student.grade_anchor_year,
        current_grade_level=current_grade_label(
            anchor_level,
            student.grade_anchor_year,
            student.grade_level,
        ),
        current_grade_level_code=current_grade_code(
            anchor_level,
            student.grade_anchor_year,
        ),
        school=student.school,
        memo=student.memo,
        external_id=student.external_id,
        is_active=student.is_active,
        class_ids=await _student_class_ids(session, student.id),
        created_at=student.created_at,
        deleted_at=student.deleted_at,
    )


def _student_exam_record(submission: Submission, exam: Exam) -> StudentExamRecord:
    return StudentExamRecord(
        exam_id=exam.id,
        exam_title=exam.title,
        exam_date=exam.exam_date,
        submitted_at=submission.created_at,
        submission_id=submission.id,
        page_number=submission.page_number,
        total_score=submission.total_score,
        max_score=submission.max_score,
        grade_band=submission.grade_band,
        image_path=submission.image_path,
        image_url=_storage_url(submission.image_path),
        needs_human_review=submission.needs_human_review,
    )


def _student_exam_summary(rows: list[tuple[Submission, Exam]]) -> StudentExamSummary:
    submissions = [submission for submission, _exam in rows]
    exam = rows[0][1]
    total_score = sum(
        submission.total_score or 0
        for submission in submissions
        if submission.total_score is not None
    )
    max_score = sum(
        submission.max_score or 0
        for submission in submissions
        if submission.max_score is not None
    )
    scored = max_score > 0
    percentage = (total_score / max_score) * 100 if scored else None
    if percentage is None:
        grade_band = None
    elif percentage >= 90:
        grade_band = "A"
    elif percentage >= 75:
        grade_band = "B"
    elif percentage >= 60:
        grade_band = "C"
    else:
        grade_band = "D"
    return StudentExamSummary(
        exam_id=exam.id,
        exam_title=exam.title,
        exam_date=exam.exam_date,
        latest_submitted_at=max(submission.created_at for submission in submissions),
        submission_count=len(submissions),
        total_score=total_score if scored else None,
        max_score=max_score if scored else None,
        grade_band=grade_band,
        needs_human_review=any(submission.needs_human_review for submission in submissions),
    )


async def _student_class_ids(session: AsyncSession, student_id: str) -> list[str]:
    result = await session.execute(
        select(StudentClassEnrollment.class_id)
        .where(StudentClassEnrollment.student_id == student_id)
        .where(StudentClassEnrollment.is_active.is_(True))
    )
    return list(result.scalars().all())


def _storage_url(path: str) -> str:
    normalized = path.replace("\\", "/")
    if normalized.startswith("storage/"):
        return "/" + normalized
    return f"/storage/{normalized}"
