from __future__ import annotations

from app.models import GradeBand
from app.schemas import GradedAnswer, GradingResult, InstructorCommentInput, OcrAnswer, OcrResult
from app.services.feedback_quality import apply_feedback_quality_gate


def grade_band(total_score: float, max_score: float) -> GradeBand:
    if max_score <= 0:
        return GradeBand.D
    percentage = (total_score / max_score) * 100
    if percentage >= 90:
        return GradeBand.A
    if percentage >= 75:
        return GradeBand.B
    if percentage >= 60:
        return GradeBand.C
    return GradeBand.D


def contains_uncertainty(ocr: OcrResult) -> bool:
    return any("[Unrecognizable]" in answer.raw_ocr_text for answer in ocr.answers)


def missing_question_numbers(ocr: OcrResult, question_count: int) -> set[int]:
    present = {answer.question_number for answer in ocr.answers if answer.raw_ocr_text.strip()}
    return set(range(1, question_count + 1)) - present


def normalize_ocr_result(ocr: OcrResult, question_count: int) -> OcrResult:
    by_question = {
        answer.question_number: answer.raw_ocr_text
        for answer in ocr.answers
        if 1 <= answer.question_number <= question_count
    }
    return OcrResult(
        student_info=ocr.student_info,
        answers=[
            OcrAnswer(
                question_number=question_number,
                raw_ocr_text=by_question.get(question_number, ""),
            )
            for question_number in range(1, question_count + 1)
        ],
    )


def should_review_ocr(ocr: OcrResult, question_count: int) -> bool:
    return contains_uncertainty(ocr) or bool(missing_question_numbers(ocr, question_count))


def lock_raw_ocr_text(ocr: OcrResult, grading: GradingResult) -> GradingResult:
    source_by_question = {answer.question_number: answer.raw_ocr_text for answer in ocr.answers}
    for answer in grading.answers:
        source_text = source_by_question.get(answer.question_number)
        if source_text is None:
            answer.audit_flags.append("MISSING_SOURCE_OCR_ANSWER")
            grading.needs_human_review = True
            continue
        if answer.raw_ocr_text != source_text:
            answer.raw_ocr_text = source_text
            answer.audit_flags.append("MODEL_ATTEMPTED_TO_MUTATE_RAW_OCR")
            grading.needs_human_review = True
    grading.grade_band = grade_band(grading.total_score, grading.max_score)
    return grading


def finalize_grading_result(
    *,
    ocr: OcrResult,
    grading: GradingResult,
    comments: list[InstructorCommentInput],
    question_count: int,
) -> GradingResult:
    normalized_ocr = normalize_ocr_result(ocr, question_count)
    raw_by_question = {
        answer.question_number: answer.raw_ocr_text
        for answer in normalized_ocr.answers
    }
    comment_by_question = {comment.question_number: comment for comment in comments}
    grade_by_question = {
        answer.question_number: answer
        for answer in grading.answers
        if 1 <= answer.question_number <= question_count
    }

    finalized: list[GradedAnswer] = []
    for question_number in range(1, question_count + 1):
        raw_text = raw_by_question.get(question_number, "")
        comment = comment_by_question.get(question_number)
        existing = grade_by_question.get(question_number)
        max_score = comment.max_score if comment else existing.max_score if existing else 1.0

        if existing is None:
            answer = GradedAnswer(
                question_number=question_number,
                raw_ocr_text=raw_text,
                score=0,
                max_score=max_score,
                feedback_comment="미작성 문항으로 0점 처리되었습니다."
                if not raw_text.strip()
                else "채점 결과가 누락되어 검수가 필요합니다.",
                audit_flags=["MISSING_GRADING_RESULT"],
            )
            grading.needs_human_review = grading.needs_human_review or bool(raw_text.strip())
        else:
            answer = existing
            if answer.raw_ocr_text != raw_text:
                answer.audit_flags.append("MODEL_ATTEMPTED_TO_MUTATE_RAW_OCR")
                grading.needs_human_review = True
            answer.raw_ocr_text = raw_text
            answer.max_score = max_score

        if not raw_text.strip():
            answer.score = 0
            answer.feedback_comment = "미작성 문항으로 0점 처리되었습니다."
            if "BLANK_ANSWER_AUTO_ZERO" not in answer.audit_flags:
                answer.audit_flags.append("BLANK_ANSWER_AUTO_ZERO")
        else:
            answer.score = min(max(answer.score, 0), max_score)
        finalized.append(answer)

    grading.student_name = grading.student_name or normalized_ocr.student_info.name
    grading.answers = finalized
    grading.total_score = sum(answer.score for answer in finalized)
    grading.max_score = sum(answer.max_score for answer in finalized)
    grading.grade_band = grade_band(grading.total_score, grading.max_score)
    grading.needs_human_review = grading.needs_human_review or contains_uncertainty(normalized_ocr)
    return apply_feedback_quality_gate(grading)


def infer_growth_label(percentages: list[float]) -> tuple[str, str]:
    if len(percentages) < 2:
        return (
            "insufficient_history",
            "아직 누적 시험이 부족해서 다음 시험 전망은 보수적으로만 볼 수 있습니다.",
        )

    delta = percentages[-1] - percentages[0]
    recent_delta = percentages[-1] - percentages[-2]
    if delta >= 10 and recent_delta >= 0:
        return "rising", "최근 성장세가 뚜렷해서 다음 시험에서 추가 상승을 기대할 수 있습니다."
    if recent_delta >= 5:
        return "recovering", "최근 회복 흐름이 보여 다음 시험에서 안정적인 상승 가능성이 있습니다."
    if abs(recent_delta) <= 3:
        return (
            "steady",
            "성적이 안정권에 있어 약점 문항만 줄이면 다음 시험도 유지 또는 소폭 상승이 가능합니다.",
        )
    return (
        "needs_support",
        "최근 점수가 흔들려서 오답 원인별 보강과 검수 피드백이 먼저 필요합니다.",
    )
