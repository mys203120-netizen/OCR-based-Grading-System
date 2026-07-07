from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.models import GradeBand, JobStatus, StudentMatchStatus, SubmissionStatus


class InstructorCreate(BaseModel):
    name: str
    phone: str | None = None
    email: str | None = None


class InstructorRead(InstructorCreate):
    id: str
    created_at: datetime


class ClassCreate(BaseModel):
    name: str
    description: str | None = None


class ClassRead(ClassCreate):
    id: str
    instructor_id: str
    class_kind: str = "manual"
    grade_level_code: int | None = None
    is_active: bool
    created_at: datetime


class StudentCreate(BaseModel):
    name: str
    parent_phone: str | None = None
    student_phone: str | None = None
    level_band: str | None = Field(default=None, description="학원 내부 등급대")
    grade_level: str | None = Field(default=None, description="등록 시점 학년. 예: 예비고1, 고1")
    grade_anchor_year: int | None = Field(default=None, description="등록 기준 학년도. 비우면 자동")
    school: str | None = None
    memo: str | None = None
    external_id: str | None = None
    class_ids: list[str] = Field(default_factory=list)


class StudentUpdate(BaseModel):
    name: str | None = None
    parent_phone: str | None = None
    student_phone: str | None = None
    level_band: str | None = None
    grade_level: str | None = None
    grade_anchor_year: int | None = None
    school: str | None = None
    memo: str | None = None
    external_id: str | None = None
    class_ids: list[str] | None = None


class StudentRead(BaseModel):
    id: str
    name: str
    parent_phone: str | None = None
    student_phone: str | None = None
    level_band: str | None = None
    grade_level: str | None = None
    grade_anchor_level: int | None = None
    grade_anchor_year: int | None = None
    current_grade_level: str | None = None
    current_grade_level_code: int | None = None
    school: str | None = None
    memo: str | None = None
    external_id: str | None = None
    is_active: bool
    class_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    deleted_at: datetime | None = None


class StudentCandidate(BaseModel):
    student_id: str
    name: str
    school: str | None = None
    grade_level: str | None = None
    current_grade_level: str | None = None
    level_band: str | None = None
    parent_phone: str | None = None
    student_phone: str | None = None


class AssignStudentRequest(BaseModel):
    student_id: str


class StudentInfo(BaseModel):
    name: str = Field(default="", description="Extracted student name.")


class OcrAnswer(BaseModel):
    question_number: int = Field(ge=1, le=50)
    raw_ocr_text: str


class OcrResult(BaseModel):
    student_info: StudentInfo
    answers: list[OcrAnswer]


class InstructorCommentInput(BaseModel):
    question_number: int = Field(ge=1, le=50)
    comment: str
    model_answer: str | None = None
    rubric: str | None = None
    book_reference: str | None = None
    reinforcement_target: str | None = None
    max_score: float = Field(default=1.0, gt=0)

    @field_validator("comment")
    @classmethod
    def comment_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("comment must not be empty")
        return value.strip()


class ExamUpdate(BaseModel):
    exam_date: date


class ExamRead(BaseModel):
    id: str
    class_id: str | None = None
    title: str
    question_count: int
    exam_date: date | None = None
    created_at: datetime


class JobCreateResponse(BaseModel):
    job_id: str
    exam_id: str
    class_id: str | None = None
    status: JobStatus
    total_pages: int = 0


class JobStatusResponse(BaseModel):
    job_id: str
    exam_id: str
    class_id: str | None = None
    status: JobStatus
    total_pages: int
    processed_pages: int
    failed_pages: int
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


WeaknessType = Literal[
    "grammar",
    "vocabulary",
    "word_order",
    "meaning",
    "omission",
    "spelling",
    "punctuation",
    "concept",
]


class GradedAnswer(BaseModel):
    question_number: int = Field(ge=1, le=50)
    raw_ocr_text: str
    score: float = Field(ge=0)
    max_score: float = Field(gt=0)
    feedback_comment: str = Field(
        description=(
            "학생에게 그대로 보여줄 문항별 코멘트. 한국어, 강사 말투, 1~3문장. "
            "뭉뚱그린 AI식 총평 금지."
        )
    )
    diagnosis: str | None = Field(
        default=None,
        description="오답 원인을 한 줄로 특정합니다. 예: 관계대명사 뒤 동사 수일치 누락.",
    )
    correction_strategy: str | None = Field(
        default=None,
        description="학생이 다음번에 적용할 교정 순서나 체크포인트.",
    )
    drill_recommendation: str | None = Field(
        default=None,
        description="강사 코멘트/교재 정보가 있으면 연결한 짧은 보강 지시.",
    )
    better_sentence: str | None = Field(
        default=None,
        description="더 나은 영어 문장. raw_ocr_text를 절대 대체하지 않습니다.",
    )
    likely_reason_for_error: str | None = Field(
        default=None,
        description="학생이 왜 그렇게 썼을지에 대한 조심스러운 추정. 단정 금지.",
    )
    weakness_types: list[WeaknessType] = Field(default_factory=list)
    concept_tags: list[str] = Field(default_factory=list)
    instructor_comment_used: str | None = None
    audit_flags: list[str] = Field(default_factory=list)


class GradingResult(BaseModel):
    student_name: str
    total_score: float = Field(ge=0)
    max_score: float = Field(gt=0)
    grade_band: GradeBand
    needs_human_review: bool = False
    personalized_summary: str
    next_study_actions: list[str] = Field(default_factory=list)
    next_exam_expectation: str | None = None
    parent_sms_draft: str | None = None
    feedback_quality_flags: list[str] = Field(default_factory=list)
    answers: list[GradedAnswer]


class SubmissionSummary(BaseModel):
    submission_id: str
    exam_id: str
    exam_title: str | None = None
    exam_date: date | None = None
    page_number: int
    status: SubmissionStatus
    student_id: str | None = None
    student_name: str | None = None
    student_match_status: StudentMatchStatus = StudentMatchStatus.UNMATCHED
    student_candidates: list[StudentCandidate] = Field(default_factory=list)
    total_score: float | None = None
    max_score: float | None = None
    grade_band: GradeBand | None = None
    needs_human_review: bool
    error_message: str | None = None


class SubmissionDetail(SubmissionSummary):
    image_path: str
    image_url: str
    raw_ocr: OcrResult | None = None
    graded: GradingResult | None = None
    human_ocr: OcrResult | None = None
    human_grade: GradingResult | None = None


class ReviewUpdate(BaseModel):
    human_ocr: OcrResult | None = None
    human_grade: GradingResult | None = None
    approve: bool = False


class RankingRow(BaseModel):
    rank: int
    student_id: str
    student_name: str
    total_score: float
    max_score: float
    percentage: float
    grade_band: GradeBand
    page_number: int
    needs_human_review: bool


class TrendPoint(BaseModel):
    exam_id: str
    exam_title: str
    submitted_at: datetime
    total_score: float
    max_score: float
    percentage: float
    grade_band: GradeBand


class StudentGrowthResponse(BaseModel):
    student_id: str
    student_name: str
    trend: list[TrendPoint]
    growth_label: str
    next_exam_expectation: str


class DashboardOverview(BaseModel):
    exams: int
    jobs: int
    submissions: int
    students: int
    pending_review: int


class StudentExamRecord(BaseModel):
    exam_id: str
    exam_title: str
    exam_date: date | None = None
    submitted_at: datetime
    submission_id: str
    page_number: int
    total_score: float | None = None
    max_score: float | None = None
    grade_band: GradeBand | None = None
    image_path: str
    image_url: str
    needs_human_review: bool


class StudentExamSummary(BaseModel):
    exam_id: str
    exam_title: str
    exam_date: date | None = None
    latest_submitted_at: datetime
    submission_count: int
    total_score: float | None = None
    max_score: float | None = None
    grade_band: GradeBand | None = None
    needs_human_review: bool


class MessageDraftCreate(BaseModel):
    recipient: Literal["parent", "student"] = "parent"
    body: str | None = None


class MessageResponse(BaseModel):
    id: str
    submission_id: str
    phone: str
    body: str
    status: str
    channel: str = "kakao"
    provider: str | None = None
    provider_message_id: str | None = None
    error_message: str | None = None
    created_at: datetime
    sent_at: datetime | None = None
