from datetime import date

from app.services.academic import (
    academic_year,
    current_grade_label,
    grade_label_from_code,
    parse_grade_level,
)


def test_academic_year_starts_in_march() -> None:
    assert academic_year(date(2027, 2, 28)) == 2026
    assert academic_year(date(2027, 3, 1)) == 2027


def test_grade_progression_by_academic_year() -> None:
    assert current_grade_label(10, 2026, today=date(2026, 7, 1)) == "고1"
    assert current_grade_label(10, 2026, today=date(2027, 3, 1)) == "고2"
    assert current_grade_label(9, 2026, today=date(2027, 3, 1)) == "고1"


def test_grade_label_parsing() -> None:
    assert parse_grade_level("예비고1") == 9
    assert parse_grade_level("고2") == 11
    assert parse_grade_level("고3/N수") == 12
    assert grade_label_from_code(12) == "고3/N수"
    assert grade_label_from_code(13) == "고3/N수"
