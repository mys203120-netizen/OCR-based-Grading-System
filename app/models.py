from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def new_uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"


class SubmissionStatus(StrEnum):
    PENDING = "pending"
    OCR_RUNNING = "ocr_running"
    GRADING_RUNNING = "grading_running"
    COMPLETED = "completed"
    FAILED = "failed"
    APPROVED = "approved"


class GradeBand(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class StudentMatchStatus(StrEnum):
    UNMATCHED = "unmatched"
    AUTO_MATCHED = "auto_matched"
    AMBIGUOUS = "ambiguous"
    NO_MATCH = "no_match"
    MANUAL_MATCHED = "manual_matched"


class Instructor(Base):
    __tablename__ = "instructors"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(120), index=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    email: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    classes: Mapped[list[ClassRoom]] = relationship(back_populates="instructor")


class ClassRoom(Base):
    __tablename__ = "class_rooms"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    instructor_id: Mapped[str] = mapped_column(ForeignKey("instructors.id"), index=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    class_kind: Mapped[str] = mapped_column(String(30), default="manual", index=True)
    grade_level_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    instructor: Mapped[Instructor] = relationship(back_populates="classes")
    enrollments: Mapped[list[StudentClassEnrollment]] = relationship(
        back_populates="class_room", cascade="all, delete-orphan"
    )
    exams: Mapped[list[Exam]] = relationship(back_populates="class_room")


class Student(Base):
    __tablename__ = "students"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    instructor_id: Mapped[str | None] = mapped_column(ForeignKey("instructors.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    parent_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    student_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    level_band: Mapped[str | None] = mapped_column(String(40), nullable=True)
    grade_level: Mapped[str | None] = mapped_column(String(40), nullable=True)
    grade_anchor_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    grade_anchor_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    school: Mapped[str | None] = mapped_column(String(120), nullable=True)
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    submissions: Mapped[list[Submission]] = relationship(back_populates="student")
    enrollments: Mapped[list[StudentClassEnrollment]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )


class StudentClassEnrollment(Base):
    __tablename__ = "student_class_enrollments"
    __table_args__ = (UniqueConstraint("student_id", "class_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"))
    class_id: Mapped[str] = mapped_column(ForeignKey("class_rooms.id", ondelete="CASCADE"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    student: Mapped[Student] = relationship(back_populates="enrollments")
    class_room: Mapped[ClassRoom] = relationship(back_populates="enrollments")


class Exam(Base):
    __tablename__ = "exams"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    class_id: Mapped[str | None] = mapped_column(ForeignKey("class_rooms.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    question_count: Mapped[int] = mapped_column(Integer, default=10)
    source_pdf_path: Mapped[str] = mapped_column(Text)
    exam_date: Mapped[date | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    class_room: Mapped[ClassRoom | None] = relationship(back_populates="exams")
    comments: Mapped[list[InstructorComment]] = relationship(
        back_populates="exam", cascade="all, delete-orphan"
    )
    submissions: Mapped[list[Submission]] = relationship(back_populates="exam")


class InstructorComment(Base):
    __tablename__ = "instructor_comments"
    __table_args__ = (UniqueConstraint("exam_id", "question_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    exam_id: Mapped[str] = mapped_column(ForeignKey("exams.id", ondelete="CASCADE"))
    question_number: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(Text)
    model_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    rubric: Mapped[str | None] = mapped_column(Text, nullable=True)
    book_reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reinforcement_target: Mapped[str | None] = mapped_column(String(200), nullable=True)
    max_score: Mapped[float] = mapped_column(Float, default=1.0)

    exam: Mapped[Exam] = relationship(back_populates="comments")


class GradingJob(Base):
    __tablename__ = "grading_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    exam_id: Mapped[str] = mapped_column(ForeignKey("exams.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(30), default=JobStatus.PENDING.value, index=True)
    total_pages: Mapped[int] = mapped_column(Integer, default=0)
    processed_pages: Mapped[int] = mapped_column(Integer, default=0)
    failed_pages: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    exam: Mapped[Exam] = relationship()
    submissions: Mapped[list[Submission]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (UniqueConstraint("job_id", "page_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    job_id: Mapped[str] = mapped_column(ForeignKey("grading_jobs.id", ondelete="CASCADE"))
    exam_id: Mapped[str] = mapped_column(ForeignKey("exams.id", ondelete="CASCADE"))
    student_id: Mapped[str | None] = mapped_column(ForeignKey("students.id"), nullable=True)
    page_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        String(30), default=SubmissionStatus.PENDING.value, index=True
    )
    image_path: Mapped[str] = mapped_column(Text)

    raw_ocr_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    human_ocr_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    graded_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    human_grade_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    student_match_status: Mapped[str] = mapped_column(
        String(30), default=StudentMatchStatus.UNMATCHED.value, index=True
    )
    student_candidates_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    total_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    grade_band: Mapped[str | None] = mapped_column(String(1), nullable=True, index=True)
    needs_human_review: Mapped[bool] = mapped_column(Boolean, default=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    job: Mapped[GradingJob] = relationship(back_populates="submissions")
    exam: Mapped[Exam] = relationship(back_populates="submissions")
    student: Mapped[Student | None] = relationship(back_populates="submissions")


class SmsMessage(Base):
    __tablename__ = "sms_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    submission_id: Mapped[str] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"))
    phone: Mapped[str] = mapped_column(String(40))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="draft")
    channel: Mapped[str] = mapped_column(String(30), default="kakao")
    provider: Mapped[str] = mapped_column(String(50), default="solapi_kakao")
    provider_message_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    provider_payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
