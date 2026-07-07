from __future__ import annotations

import json

from app.core.config import Settings
from app.schemas import GradingResult, InstructorCommentInput, OcrResult
from app.services.gemini_client import GeminiJsonClient
from app.services.policy import finalize_grading_result
from app.services.prompts import (
    GRADING_SYSTEM_INSTRUCTION,
    GRADING_USER_PROMPT_TEMPLATE,
    grading_schema,
)


async def run_grading(
    *,
    ocr: OcrResult,
    comments: list[InstructorCommentInput],
    history: dict,
    question_count: int,
    ai_client: GeminiJsonClient,
    settings: Settings,
) -> GradingResult:
    prompt = GRADING_USER_PROMPT_TEMPLATE.format(
        ocr_json=ocr.model_dump_json(),
        comments_json=json.dumps(
            [comment.model_dump() for comment in comments],
            ensure_ascii=False,
        ),
        history_json=json.dumps(history, ensure_ascii=False),
    )
    grading = await ai_client.generate_json(
        model=settings.gemini_grading_model,
        system_instruction=GRADING_SYSTEM_INSTRUCTION,
        prompt=prompt,
        response_schema=grading_schema(),
        response_model=GradingResult,
    )
    grading = finalize_grading_result(
        ocr=ocr,
        grading=grading,
        comments=comments,
        question_count=question_count,
    )
    return grading
