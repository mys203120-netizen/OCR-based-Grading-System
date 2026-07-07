from __future__ import annotations

from datetime import date

GRADE_LABEL_TO_CODE = {
    "예비고1": 9,
    "예비 고1": 9,
    "중3": 9,
    "고1": 10,
    "고 1": 10,
    "고등학교1학년": 10,
    "고2": 11,
    "고 2": 11,
    "고등학교2학년": 11,
    "고3": 12,
    "고3/N수": 12,
    "고3N수": 12,
    "고 3": 12,
    "고등학교3학년": 12,
    "졸업생": 13,
    "N수": 13,
}


def academic_year(today: date | None = None) -> int:
    today = today or date.today()
    return today.year if today.month >= 3 else today.year - 1


def parse_grade_level(value: str | None) -> int | None:
    if not value:
        return None
    normalized = value.replace(" ", "").strip()
    if normalized in GRADE_LABEL_TO_CODE:
        return GRADE_LABEL_TO_CODE[normalized]
    for label, code in GRADE_LABEL_TO_CODE.items():
        if normalized == label.replace(" ", ""):
            return code
    return None


def current_grade_code(
    anchor_level: int | None,
    anchor_year: int | None,
    today: date | None = None,
) -> int | None:
    if anchor_level is None:
        return None
    base_year = anchor_year or academic_year(today)
    return anchor_level + max(academic_year(today) - base_year, 0)


def grade_label_from_code(code: int | None) -> str | None:
    if code is None:
        return None
    if code <= 8:
        return f"중{max(code - 6, 1)}"
    if code == 9:
        return "예비고1"
    if code == 10:
        return "고1"
    if code == 11:
        return "고2"
    if code == 12:
        return "고3/N수"
    return "고3/N수"


def current_grade_label(
    anchor_level: int | None,
    anchor_year: int | None,
    fallback: str | None = None,
    today: date | None = None,
) -> str | None:
    code = current_grade_code(anchor_level, anchor_year, today)
    return grade_label_from_code(code) or fallback
