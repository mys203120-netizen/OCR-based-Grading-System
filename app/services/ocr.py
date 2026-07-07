from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.schemas import OcrResult
from app.services.gemini_client import GeminiJsonClient
from app.services.prompts import OCR_SYSTEM_INSTRUCTION, OCR_USER_PROMPT_TEMPLATE, ocr_schema


async def run_ocr(
    *,
    image_path: Path,
    page_number: int,
    question_count: int,
    ai_client: GeminiJsonClient,
    settings: Settings,
) -> OcrResult:
    prompt = OCR_USER_PROMPT_TEMPLATE.format(
        question_count=question_count,
        page_number=page_number,
    )
    return await ai_client.generate_json(
        model=settings.gemini_ocr_model,
        system_instruction=OCR_SYSTEM_INSTRUCTION,
        prompt=prompt,
        response_schema=ocr_schema(),
        response_model=OcrResult,
        image_path=image_path,
    )
