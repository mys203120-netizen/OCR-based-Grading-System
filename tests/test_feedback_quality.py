from app.models import GradeBand
from app.schemas import GradedAnswer, GradingResult
from app.services.feedback_quality import apply_feedback_quality_gate


def test_ai_tone_feedback_is_flagged() -> None:
    grading = GradingResult(
        student_name="A",
        total_score=1,
        max_score=1,
        grade_band=GradeBand.A,
        personalized_summary="전반적으로 문장 구성 능력 개선이 필요합니다.",
        answers=[
            GradedAnswer(
                question_number=1,
                raw_ocr_text="answer",
                score=1,
                max_score=1,
                feedback_comment="해당 문항은 문법에 주의하세요.",
            )
        ],
    )

    checked = apply_feedback_quality_gate(grading)

    assert checked.needs_human_review
    assert "AI_TONE_SUMMARY_REVIEW" in checked.feedback_quality_flags
    assert "AI_TONE_FEEDBACK_REVIEW" in checked.answers[0].audit_flags
    assert "GENERIC_FEEDBACK_REVIEW" in checked.answers[0].audit_flags


def test_concrete_teacher_feedback_passes_quality_gate() -> None:
    grading = GradingResult(
        student_name="A",
        total_score=1,
        max_score=1,
        grade_band=GradeBand.A,
        personalized_summary="문장 핵심은 잡았어. 긴 문장에서는 동사 위치만 먼저 고정하자.",
        answers=[
            GradedAnswer(
                question_number=1,
                raw_ocr_text="answer",
                score=1,
                max_score=1,
                feedback_comment=(
                    "의미는 맞게 잡았어. 다만 관계대명사 뒤 동사가 앞 명사와 "
                    "맞는지 확인하면 문장이 더 안정적이야."
                ),
            )
        ],
    )

    checked = apply_feedback_quality_gate(grading)

    assert not checked.needs_human_review
    assert checked.feedback_quality_flags == []
    assert checked.answers[0].audit_flags == []
