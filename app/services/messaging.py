from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from app.core.config import Settings

_PLACEHOLDER_VALUES = {
    "API 키를 입력하세요.",
    "API 시크릿을 입력하세요.",
    "발신번호를 입력하세요.",
    "카카오 채널 PF ID를 입력하세요.",
    "알림톡 템플릿 ID를 입력하세요.",
}


class MessageSendError(RuntimeError):
    pass


@dataclass(frozen=True)
class MessageSendResult:
    status: str
    provider_message_id: str | None = None
    raw_response: str | None = None


class MessageSender(Protocol):
    async def send_kakao(self, *, phone: str, body: str) -> MessageSendResult:
        pass


class MockMessageSender:
    async def send_kakao(self, *, phone: str, body: str) -> MessageSendResult:
        del phone, body
        return MessageSendResult(
            status="sent",
            provider_message_id=f"mock-{secrets.token_hex(8)}",
            raw_response='{"provider":"mock"}',
        )


class SolapiKakaoSender:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def send_kakao(self, *, phone: str, body: str) -> MessageSendResult:
        self._validate_settings()
        phone_digits = _digits_only(phone)
        if not phone_digits:
            raise MessageSendError("recipient phone number is empty")
        if len(body) > 1000:
            raise MessageSendError("kakao alimtalk body must be 1000 characters or fewer")

        payload = self._build_payload(phone_digits, body)
        headers = {
            "Authorization": self._authorization_header(),
            "Content-Type": "application/json",
        }
        url = self.settings.solapi_base_url.rstrip("/") + "/messages/v4/send-many/detail"

        try:
            import httpx

            async with httpx.AsyncClient(timeout=self.settings.solapi_timeout_seconds) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                response_data = response.json()
        except Exception as exc:
            raise MessageSendError(f"solapi kakao send failed: {exc}") from exc

        failed_messages = response_data.get("failedMessageList") or []
        if failed_messages:
            raise MessageSendError(json.dumps(failed_messages, ensure_ascii=False))

        group_info = response_data.get("groupInfo") or {}
        provider_message_id = (
            group_info.get("groupId")
            or group_info.get("_id")
            or response_data.get("groupId")
            or response_data.get("_id")
        )
        return MessageSendResult(
            status="queued",
            provider_message_id=provider_message_id,
            raw_response=json.dumps(response_data, ensure_ascii=False),
        )

    def _validate_settings(self) -> None:
        required = {
            "SOLAPI_API_KEY": self.settings.solapi_api_key,
            "SOLAPI_API_SECRET": self.settings.solapi_api_secret,
            "SOLAPI_KAKAO_PF_ID": self.settings.solapi_kakao_pf_id,
            "SOLAPI_KAKAO_TEMPLATE_ID": self.settings.solapi_kakao_template_id,
        }
        if not self.settings.solapi_disable_sms_fallback:
            required["SOLAPI_SENDER_NUMBER"] = self.settings.solapi_sender_number

        missing = [
            name
            for name, value in required.items()
            if not value or value.strip() in _PLACEHOLDER_VALUES
        ]
        if missing:
            raise MessageSendError(f"missing solapi settings: {', '.join(missing)}")

    def _build_payload(self, phone_digits: str, body: str) -> dict:
        kakao_options: dict[str, object] = {
            "pfId": self.settings.solapi_kakao_pf_id,
            "templateId": self.settings.solapi_kakao_template_id,
            "disableSms": self.settings.solapi_disable_sms_fallback,
        }
        message: dict[str, object] = {
            "to": phone_digits,
            "type": "ATA",
            "kakaoOptions": kakao_options,
        }
        if self.settings.solapi_sender_number:
            message["from"] = _digits_only(self.settings.solapi_sender_number)

        variable_name = self.settings.solapi_kakao_body_variable
        if variable_name:
            kakao_options["variables"] = {variable_name: body}
        else:
            message["text"] = body

        return {
            "messages": [message],
            "allowDuplicates": True,
            "showMessageList": True,
            "strict": True,
        }

    def _authorization_header(self) -> str:
        date = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
        salt = secrets.token_hex(16)
        signature = hmac.new(
            (self.settings.solapi_api_secret or "").encode("utf-8"),
            f"{date}{salt}".encode(),
            hashlib.sha256,
        ).hexdigest()
        return (
            "HMAC-SHA256 "
            f"apiKey={self.settings.solapi_api_key}, "
            f"date={date}, "
            f"salt={salt}, "
            f"signature={signature}"
        )


def build_message_sender(settings: Settings) -> MessageSender:
    if settings.message_provider == "mock":
        return MockMessageSender()
    return SolapiKakaoSender(settings)


def _digits_only(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\D", "", value)
