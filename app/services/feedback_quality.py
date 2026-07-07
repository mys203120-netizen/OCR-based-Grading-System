from __future__ import annotations

from app.schemas import GradingResult

AI_TONE_PATTERNS = [
    "전반적으로",
    "학습자",
    "해당 문항",
    "개선이 필요",
    "역량",
    "도움이 됩니다",
    "정확도를 높일 수",
    "문장 구성 능력",
    "본 답안",
    "피드백을 제공",
    "다음과 같이",
    "것으로 보입니다",
    "강화하시기 바랍니다",
    "추가 학습",
    "유의미",
    "학습 효과",
]

GENERIC_PATTERNS = [
    "좋은 답변입니다",
    "잘했습니다",
    "문법에 주의하세요",
    "어휘를 보완하세요",
    "복습하세요",
]


def apply_feedback_quality_gate(grading: GradingResult) -> GradingResult:
    quality_flags = set(grading.feedback_quality_flags)

    summary_hits = _matches(grading.personalized_summary)
    if summary_hits:
        quality_flags.add("AI_TONE_SUMMARY_REVIEW")

    sms_hits = _matches(grading.parent_sms_draft or "")
    if sms_hits:
        quality_flags.add("AI_TONE_SMS_REVIEW")

    for answer in grading.answers:
        hits = _matches(answer.feedback_comment)
        generic_hits = _generic_matches(answer.feedback_comment)
        if hits:
            _append_once(answer.audit_flags, "AI_TONE_FEEDBACK_REVIEW")
            quality_flags.add("AI_TONE_ANSWER_REVIEW")
        if generic_hits:
            _append_once(answer.audit_flags, "GENERIC_FEEDBACK_REVIEW")
            quality_flags.add("GENERIC_ANSWER_FEEDBACK_REVIEW")
        if answer.raw_ocr_text.strip() and len(answer.feedback_comment.strip()) < 18:
            _append_once(answer.audit_flags, "TOO_SHORT_FEEDBACK_REVIEW")
            quality_flags.add("TOO_SHORT_ANSWER_FEEDBACK_REVIEW")

    if quality_flags:
        grading.feedback_quality_flags = sorted(quality_flags)
        grading.needs_human_review = True
    return grading


def _matches(text: str) -> list[str]:
    return [pattern for pattern in AI_TONE_PATTERNS if pattern in text]


def _generic_matches(text: str) -> list[str]:
    return [pattern for pattern in GENERIC_PATTERNS if pattern in text]


def _append_once(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)
