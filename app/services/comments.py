from __future__ import annotations

import json

from pydantic import ValidationError

from app.schemas import InstructorCommentInput


def parse_comments_json(raw: str, question_count: int) -> list[InstructorCommentInput]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("comments_json must be valid JSON") from exc

    if isinstance(payload, dict) and "comments" in payload:
        payload = payload["comments"]

    if not isinstance(payload, list):
        raise ValueError("comments_json must be a JSON array or an object with comments")

    comments: list[InstructorCommentInput] = []
    if all(isinstance(item, str) for item in payload):
        comments = [
            InstructorCommentInput(question_number=index + 1, comment=item)
            for index, item in enumerate(payload)
        ]
    else:
        try:
            comments = [InstructorCommentInput.model_validate(item) for item in payload]
        except ValidationError as exc:
            raise ValueError(str(exc)) from exc

    by_number = {comment.question_number: comment for comment in comments}
    missing = set(range(1, question_count + 1)) - set(by_number)
    if missing:
        raise ValueError(f"comments_json is missing question numbers: {sorted(missing)}")
    return [by_number[number] for number in range(1, question_count + 1)]
