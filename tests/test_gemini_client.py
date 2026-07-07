from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from app.services.gemini_client import (
    GeminiEmptyResponseError,
    GeminiSafetyBlockedError,
    GeminiSchemaError,
    _extract_response_text,
    _is_retryable_exception,
    _validate_response_json,
)


class Payload(BaseModel):
    name: str


class ApiError(Exception):
    status_code = 429


def test_retryable_api_status_codes() -> None:
    assert _is_retryable_exception(ApiError())


def test_empty_response_is_retryable() -> None:
    with pytest.raises(GeminiEmptyResponseError):
        _extract_response_text(SimpleNamespace(text=""))

    assert _is_retryable_exception(GeminiEmptyResponseError("empty"))


def test_safety_block_is_not_retryable() -> None:
    response = SimpleNamespace(
        text="",
        prompt_feedback=SimpleNamespace(block_reason="SAFETY"),
    )

    with pytest.raises(GeminiSafetyBlockedError):
        _extract_response_text(response)

    assert not _is_retryable_exception(GeminiSafetyBlockedError("blocked"))


def test_schema_mismatch_is_retryable() -> None:
    with pytest.raises(GeminiSchemaError):
        _validate_response_json(Payload, '{"wrong": "field"}')

    assert _is_retryable_exception(GeminiSchemaError("schema"))
