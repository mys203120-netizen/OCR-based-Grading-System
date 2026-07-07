from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "CTD OCR Grading API"
    app_env: str = "local"
    api_v1_prefix: str = "/api/v1"

    database_url: str = "postgresql+asyncpg://ctd_ocr:ctd_ocr@localhost:5432/ctd_ocr"
    sql_echo: bool = False

    storage_dir: Path = Path("storage")
    upload_dir: Path = Path("storage/uploads")
    page_image_dir: Path = Path("storage/pages")
    render_dpi: int = Field(default=220, ge=120, le=400)

    ai_provider: Literal["gemini", "mock"] = "gemini"
    gemini_api_key: str | None = None
    gemini_ocr_model: str = "gemini-3.5-flash"
    gemini_grading_model: str = "gemini-3.5-flash"

    ocr_concurrency: int = Field(default=4, ge=1, le=16)
    grading_concurrency: int = Field(default=4, ge=1, le=16)

    queue_provider: Literal["redis", "inline"] = "redis"
    redis_url: str = "redis://localhost:6379/0"
    grading_queue_name: str = "ctd-grading-jobs"
    grading_job_timeout_seconds: int = Field(default=1800, ge=60)
    grading_job_result_ttl_seconds: int = Field(default=86400, ge=0)
    grading_job_failure_ttl_seconds: int = Field(default=604800, ge=0)

    message_provider: Literal["solapi_kakao", "mock"] = "solapi_kakao"
    solapi_base_url: str = "https://api.solapi.com"
    solapi_api_key: str | None = None
    solapi_api_secret: str | None = None
    solapi_sender_number: str | None = None
    solapi_kakao_pf_id: str | None = None
    solapi_kakao_template_id: str | None = None
    solapi_kakao_body_variable: str | None = "#{내용}"
    solapi_disable_sms_fallback: bool = False
    solapi_timeout_seconds: float = Field(default=10.0, gt=0)

    allowed_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://localhost:5173",
            "https://www.ctdenglish.com",
        ]
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    def ensure_directories(self) -> None:
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.page_image_dir.mkdir(parents=True, exist_ok=True)
        Path("data").mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
