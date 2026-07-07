import pytest

from app.services.comments import parse_comments_json


def test_parse_string_comments() -> None:
    comments = parse_comments_json('["one","two"]', 2)
    assert comments[0].question_number == 1
    assert comments[1].comment == "two"


def test_parse_missing_comment_numbers() -> None:
    with pytest.raises(ValueError):
        parse_comments_json('[{"question_number": 1, "comment": "one"}]', 2)
