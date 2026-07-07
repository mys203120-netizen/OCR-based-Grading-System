from __future__ import annotations

import asyncio
import json
import shutil
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.models import (
    ClassRoom,
    Exam,
    GradingJob,
    InstructorComment,
    JobStatus,
    Student,
    StudentMatchStatus,
    Submission,
    SubmissionStatus,
    utcnow,
)
from app.schemas import InstructorCommentInput
from app.services.academic import current_grade_label, parse_grade_level
from app.services.classes import student_belongs_to_class
from app.services.gemini_client import GeminiJsonClient
from app.services.grading import run_grading
from app.services.json_utils import dumps_model
from app.services.ocr import run_ocr
from app.services.pdf_pages import render_pdf_pages
from app.services.policy import infer_growth_label, normalize_ocr_result


class JobRunner:
    def __init__(
        self,
        settings: Settings,
        ai_client: GeminiJsonClient,
        sessionmaker: async_sessionmaker[AsyncSession],
    ) -> None:
        self.settings = settings
        self.ai_client = ai_client
        self.sessionmaker = sessionmaker
        self._ocr_semaphore = asyncio.Semaphore(settings.ocr_concurrency)
        self._grading_semaphore = asyncio.Semaphore(settings.grading_concurrency)

    async def create_job(
        self,
        *,
        title: str,
        pdf_temp_path: Path,
        comments: list[InstructorCommentInput],
        question_count: int,
        class_id: str,
        exam_date: date | None,
    ) -> GradingJob:
        self.settings.ensure_directories()
        async with self.sessionmaker() as session:
            exam = Exam(
                class_id=class_id,
                title=title,
                question_count=question_count,
                source_pdf_path="",
                exam_date=exam_date,
            )
            session.add(exam)
            await session.flush()

            final_pdf_path = self.settings.upload_dir / f"{exam.id}.pdf"
            shutil.move(str(pdf_temp_path), final_pdf_path)
            exam.source_pdf_path = str(final_pdf_path)

            for comment in comments:
                session.add(
                    InstructorComment(
                        exam_id=exam.id,
                        question_number=comment.question_number,
                        comment=comment.comment,
                        model_answer=comment.model_answer,
                        rubric=comment.rubric,
                        book_reference=comment.book_reference,
                        reinforcement_target=comment.reinforcement_target,
                        max_score=comment.max_score,
                    )
                )

            job = GradingJob(exam_id=exam.id, status=JobStatus.PENDING.value)
            session.add(job)
            await session.commit()
            await session.refresh(job)
            return job

    async def process_job(self, job_id: str) -> None:
        try:
            await self._mark_job_started(job_id)
            pages = await self._render_and_create_submissions(job_id)
            submission_ids = [submission_id for submission_id, _ in pages]
            results = await asyncio.gather(
                *(self._process_submission(submission_id) for submission_id in submission_ids),
                return_exceptions=True,
            )
            failed = sum(1 for result in results if isinstance(result, Exception))
            await self._mark_job_finished(job_id, failed=failed)
        except Exception as exc:
            await self._mark_job_failed(job_id, str(exc))

    async def mark_job_failed(self, job_id: str, error_message: str) -> None:
        await self._mark_job_failed(job_id, error_message)

    async def _mark_job_started(self, job_id: str) -> None:
        async with self.sessionmaker() as session:
            job = await session.get(GradingJob, job_id)
            if job is None:
                raise ValueError(f"job not found: {job_id}")
            job.status = JobStatus.RUNNING.value
            job.started_at = utcnow()
            await session.commit()

    async def _render_and_create_submissions(self, job_id: str) -> list[tuple[str, int]]:
        async with self.sessionmaker() as session:
            job = await session.get(GradingJob, job_id)
            if job is None:
                raise ValueError(f"job not found: {job_id}")
            exam = await session.get(Exam, job.exam_id)
            if exam is None:
                raise ValueError(f"exam not found: {job.exam_id}")

            page_dir = self.settings.page_image_dir / job.id
            page_paths = await asyncio.to_thread(
                render_pdf_pages,
                Path(exam.source_pdf_path),
                page_dir,
                self.settings.render_dpi,
            )
            job.total_pages = len(page_paths)
            created: list[tuple[str, int]] = []
            for index, page_path in enumerate(page_paths, start=1):
                submission = Submission(
                    job_id=job.id,
                    exam_id=exam.id,
                    page_number=index,
                    image_path=str(page_path),
                    status=SubmissionStatus.PENDING.value,
                )
                session.add(submission)
                await session.flush()
                created.append((submission.id, index))
            await session.commit()
            return created

    async def _process_submission(self, submission_id: str) -> None:
        async with self.sessionmaker() as session:
            submission = await session.get(Submission, submission_id)
            if submission is None:
                raise ValueError(f"submission not found: {submission_id}")
            exam = await session.get(Exam, submission.exam_id)
            if exam is None:
                raise ValueError(f"exam not found: {submission.exam_id}")
            if exam.class_id is None:
                raise ValueError("exam is not attached to a class")
            class_room = await session.get(ClassRoom, exam.class_id)
            if class_room is None:
                raise ValueError(f"class not found: {exam.class_id}")
            instructor_id = class_room.instructor_id
            comments = await self._load_comments(exam.id)

        try:
            async with self._ocr_semaphore:
                async with self.sessionmaker() as session:
                    submission = await session.get(Submission, submission_id)
                    submission.status = SubmissionStatus.OCR_RUNNING.value
                    await session.commit()

                ocr = await run_ocr(
                    image_path=Path(submission.image_path),
                    page_number=submission.page_number,
                    question_count=exam.question_count,
                    ai_client=self.ai_client,
                    settings=self.settings,
                )
                ocr = normalize_ocr_result(ocr, exam.question_count)

            match = await self._match_student(ocr.student_info.name, instructor_id, exam.class_id)
            history = await self._student_history(match.student_id) if match.student_id else {}

            async with self._grading_semaphore:
                async with self.sessionmaker() as session:
                    submission = await session.get(Submission, submission_id)
                    submission.status = SubmissionStatus.GRADING_RUNNING.value
                    submission.raw_ocr_json = dumps_model(ocr)
                    submission.student_id = match.student_id
                    submission.student_match_status = match.status.value
                    submission.student_candidates_json = json.dumps(
                        match.candidates,
                        ensure_ascii=False,
                    )
                    await session.commit()

                grading = await run_grading(
                    ocr=ocr,
                    comments=comments,
                    history=history,
                    question_count=exam.question_count,
                    ai_client=self.ai_client,
                    settings=self.settings,
                )

            async with self.sessionmaker() as session:
                submission = await session.get(Submission, submission_id)
                submission.raw_ocr_json = dumps_model(ocr)
                submission.graded_json = dumps_model(grading)
                submission.student_id = match.student_id
                submission.student_match_status = match.status.value
                submission.student_candidates_json = json.dumps(
                    match.candidates,
                    ensure_ascii=False,
                )
                submission.total_score = grading.total_score
                submission.max_score = grading.max_score
                submission.grade_band = grading.grade_band.value
                submission.needs_human_review = (
                    grading.needs_human_review
                    or match.status
                    in {StudentMatchStatus.AMBIGUOUS, StudentMatchStatus.NO_MATCH}
                )
                submission.status = SubmissionStatus.COMPLETED.value

                job = await session.get(GradingJob, submission.job_id)
                if job is not None:
                    job.processed_pages += 1
                await session.commit()
        except Exception as exc:
            async with self.sessionmaker() as session:
                submission = await session.get(Submission, submission_id)
                if submission is not None:
                    submission.status = SubmissionStatus.FAILED.value
                    submission.error_message = str(exc)
                    job = await session.get(GradingJob, submission.job_id)
                    if job is not None:
                        job.processed_pages += 1
                        job.failed_pages += 1
                    await session.commit()
            raise

    async def _load_comments(self, exam_id: str) -> list[InstructorCommentInput]:
        async with self.sessionmaker() as session:
            result = await session.execute(
                select(InstructorComment)
                .where(InstructorComment.exam_id == exam_id)
                .order_by(InstructorComment.question_number)
            )
            rows = result.scalars().all()
            return [
                InstructorCommentInput(
                    question_number=row.question_number,
                    comment=row.comment,
                    model_answer=row.model_answer,
                    rubric=row.rubric,
                    book_reference=row.book_reference,
                    reinforcement_target=row.reinforcement_target,
                    max_score=row.max_score,
                )
                for row in rows
            ]

    async def _match_student(
        self,
        name: str,
        instructor_id: str,
        class_id: str,
    ) -> StudentMatch:
        clean_name = name.strip() or "Unknown"
        async with self.sessionmaker() as session:
            class_room = await session.get(ClassRoom, class_id)
            if class_room is None:
                raise ValueError(f"class not found: {class_id}")
            result = await session.execute(
                select(Student)
                .where(Student.instructor_id == instructor_id)
                .where(Student.is_active.is_(True))
                .where(Student.name == clean_name)
                .order_by(Student.school, Student.grade_level, Student.created_at)
            )
            candidates_all = list(dict.fromkeys(result.scalars().all()))
            students = [
                student
                for student in candidates_all
                if await student_belongs_to_class(
                    session,
                    student=student,
                    class_room=class_room,
                )
            ]
            candidates = [
                {
                    "student_id": student.id,
                    "name": student.name,
                    "school": student.school,
                    "grade_level": student.grade_level,
                    "current_grade_level": current_grade_label(
                        student.grade_anchor_level or parse_grade_level(student.grade_level),
                        student.grade_anchor_year,
                        student.grade_level,
                    ),
                    "level_band": student.level_band,
                    "parent_phone": student.parent_phone,
                    "student_phone": student.student_phone,
                }
                for student in students
            ]
            if len(students) == 1:
                return StudentMatch(
                    student_id=students[0].id,
                    status=StudentMatchStatus.AUTO_MATCHED,
                    candidates=candidates,
                )
            if len(students) > 1:
                return StudentMatch(
                    student_id=None,
                    status=StudentMatchStatus.AMBIGUOUS,
                    candidates=candidates,
                )
            return StudentMatch(
                student_id=None,
                status=StudentMatchStatus.NO_MATCH,
                candidates=[],
            )

    async def _student_history(self, student_id: str | None) -> dict:
        if student_id is None:
            return {}
        async with self.sessionmaker() as session:
            result = await session.execute(
                select(Submission, Exam)
                .join(Exam, Exam.id == Submission.exam_id)
                .where(Submission.student_id == student_id)
                .where(Submission.total_score.is_not(None))
                .order_by(Submission.created_at)
            )
            rows = result.all()
            percentages = [
                (submission.total_score / submission.max_score) * 100
                for submission, _exam in rows
                if submission.total_score is not None and submission.max_score
            ]
            growth_label, expectation = infer_growth_label(percentages)
            return {
                "previous_percentages": percentages,
                "growth_label": growth_label,
                "next_exam_expectation": expectation,
            }

    async def _mark_job_finished(self, job_id: str, failed: int) -> None:
        async with self.sessionmaker() as session:
            job = await session.get(GradingJob, job_id)
            if job is None:
                return
            job.failed_pages = failed
            job.status = JobStatus.PARTIAL.value if failed else JobStatus.COMPLETED.value
            job.completed_at = utcnow()
            await session.commit()

    async def _mark_job_failed(self, job_id: str, error_message: str) -> None:
        async with self.sessionmaker() as session:
            job = await session.get(GradingJob, job_id)
            if job is None:
                return
            job.status = JobStatus.FAILED.value
            job.error_message = error_message
            job.completed_at = utcnow()
            await session.commit()


class StudentMatch:
    def __init__(
        self,
        *,
        student_id: str | None,
        status: StudentMatchStatus,
        candidates: list[dict],
    ) -> None:
        self.student_id = student_id
        self.status = status
        self.candidates = candidates
