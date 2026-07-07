from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import Settings
from app.models import GradeBand
from app.schemas import GradedAnswer, GradingResult, OcrAnswer, OcrResult, StudentInfo

T = TypeVar("T", bound=BaseModel)


class GeminiJsonClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = None

    def _ensure_client(self):
        if self._client is None:
            from google import genai

            if self.settings.gemini_api_key:
                self._client = genai.Client(api_key=self.settings.gemini_api_key)
            else:
                self._client = genai.Client()
        return self._client

    async def generate_json(
        self,
        *,
        model: str,
        system_instruction: str,
        prompt: str,
        response_schema: dict,
        response_model: type[T],
        image_path: Path | None = None,
    ) -> T:
        if self.settings.ai_provider == "mock":
            return self._mock_response(response_model)

        from google.genai import types

        parts = [types.Part.from_text(text=prompt)]
        if image_path:
            parts.append(
                types.Part.from_bytes(data=image_path.read_bytes(), mime_type="image/png")
            )
        contents = [types.Content(role="user", parts=parts)]
        config = {
            "system_instruction": system_instruction,
            "temperature": 0,
            "response_format": {
                "text": {
                    "mime_type": "application/json",
                    "schema": response_schema,
                }
            },
        }

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=8),
            retry=retry_if_exception_type((TimeoutError, ConnectionError)),
            reraise=True,
        ):
            with attempt:
                client = self._ensure_client().aio
                response = await client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config,
                )
                return response_model.model_validate_json(response.text)

        raise RuntimeError("Gemini response generation failed")

    def _mock_response(self, response_model: type[T]) -> T:
        if response_model is OcrResult:
            return response_model(
                student_info=StudentInfo(name="Mock Student"),
                answers=[
                    OcrAnswer(question_number=i, raw_ocr_text=f"mock raw answer {i}")
                    for i in range(1, 11)
                ],
            )
        if response_model is GradingResult:
            answers = [
                GradedAnswer(
                    question_number=i,
                    raw_ocr_text=f"mock raw answer {i}",
                    score=1.0,
                    max_score=1.0,
                    feedback_comment=(
                        "핵심 의미는 잡았어. 다만 실제 답안에서는 동사 뒤 구조가 "
                        "흔들리기 쉬우니, 주어-동사-목적어를 먼저 세우고 수식어를 붙이자."
                    ),
                    diagnosis="문장 뼈대 확인 필요",
                    correction_strategy="주어-동사-목적어를 먼저 표시한 뒤 수식어를 붙인다.",
                    drill_recommendation="강사 코멘트에 연결된 문장 배열 문제를 한 번 더 풀기.",
                    better_sentence="This is a mock improved sentence.",
                    weakness_types=[],
                    concept_tags=[],
                    instructor_comment_used="mock",
                )
                for i in range(1, 11)
            ]
            return response_model(
                student_name="Mock Student",
                total_score=10.0,
                max_score=10.0,
                grade_band=GradeBand.A,
                needs_human_review=False,
                personalized_summary=(
                    "문장 핵심은 잘 잡고 있어. 다음에는 긴 문장을 쓰기 전에 "
                    "주어와 동사를 먼저 고정하면 감점이 더 줄어들 거야."
                ),
                next_study_actions=["오답 문장에서 주어와 동사에 먼저 표시하기"],
                next_exam_expectation="이 흐름이면 다음 시험에서도 안정권을 기대해볼 만해.",
                parent_sms_draft=(
                    "Mock Student 학생 서술형은 10/10점입니다. 문장 핵심은 안정적이고, "
                    "긴 문장에서 구조 표시만 더 잡으면 좋겠습니다."
                ),
                answers=answers,
            )
        payload = json.loads("{}")
        return response_model.model_validate(payload)


async def close_client(client: GeminiJsonClient) -> None:
    if client._client is not None:
        await asyncio.to_thread(client._client.close)
