from __future__ import annotations

import json
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def dumps_model(model: BaseModel) -> str:
    return model.model_dump_json()


def dumps_dict(value: dict | list) -> str:
    return json.dumps(value, ensure_ascii=False)


def loads_model(raw: str | None, model_type: type[T]) -> T | None:
    if not raw:
        return None
    return model_type.model_validate_json(raw)


def loads_json(raw: str | None) -> dict | list | None:
    if not raw:
        return None
    return json.loads(raw)
