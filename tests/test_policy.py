from app.models import GradeBand
from app.schemas import (
    GradedAnswer,
    GradingResult,
    InstructorCommentInput,
    OcrAnswer,
    OcrResult,
    StudentInfo,
)
from app.services.policy import (
    contains_uncertainty,
    finalize_grading_result,
    grade_band,
    missing_question_numbers,
    normalize_ocr_result,
)


def test_grade_band_thresholds() -> None:
    assert grade_band(9, 10) == GradeBand.A
    assert grade_band(7.5, 10) == GradeBand.B
    assert grade_band(6, 10) == GradeBand.C
    assert grade_band(5.9, 10) == GradeBand.D


def test_ocr_review_helpers() -> None:
    ocr = OcrResult(
        student_info=StudentInfo(name="A"),
        answers=[
            OcrAnswer(question_number=1, raw_ocr_text="visible"),
            OcrAnswer(question_number=2, raw_ocr_text="[Unrecognizable] word"),
        ],
    )
    assert contains_uncertainty(ocr)
    assert missing_question_numbers(ocr, 3) == {3}


def test_question_count_normalization_trims_and_fills() -> None:
    ocr = OcrResult(
        student_info=StudentInfo(name="A"),
        answers=[
            OcrAnswer(question_number=1, raw_ocr_text="one"),
            OcrAnswer(question_number=3, raw_ocr_text="three"),
            OcrAnswer(question_number=10, raw_ocr_text="ten"),
        ],
    )

    normalized = normalize_ocr_result(ocr, 5)

    assert [answer.question_number for answer in normalized.answers] == [1, 2, 3, 4, 5]
    assert [answer.raw_ocr_text for answer in normalized.answers] == ["one", "", "three", "", ""]


def test_blank_answer_is_auto_zero() -> None:
    ocr = OcrResult(
        student_info=StudentInfo(name="A"),
        answers=[
            OcrAnswer(question_number=1, raw_ocr_text="visible answer"),
            OcrAnswer(question_number=2, raw_ocr_text=""),
        ],
    )
    grading = GradingResult(
        student_name="A",
        total_score=2,
        max_score=2,
        grade_band=GradeBand.A,
        needs_human_review=False,
        personalized_summary="summary",
        answers=[
            GradedAnswer(
                question_number=1,
                raw_ocr_text="visible answer",
                score=1,
                max_score=1,
                feedback_comment="ok",
            ),
            GradedAnswer(
                question_number=2,
                raw_ocr_text="",
                score=1,
                max_score=1,
                feedback_comment="model tried to give credit",
            ),
        ],
    )
    comments = [
        InstructorCommentInput(question_number=1, comment="c1", max_score=1),
        InstructorCommentInput(question_number=2, comment="c2", max_score=1),
    ]

    finalized = finalize_grading_result(
        ocr=ocr,
        grading=grading,
        comments=comments,
        question_count=2,
    )

    assert finalized.answers[1].score == 0
    assert finalized.total_score == 1
    assert finalized.grade_band == GradeBand.D
    assert "BLANK_ANSWER_AUTO_ZERO" in finalized.answers[1].audit_flags
