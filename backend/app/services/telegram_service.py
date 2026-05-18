"""
Telegram Bot API client.

Тонкая async-обёртка над https://api.telegram.org/bot{TOKEN}/{method}.
Используется и для отправки уведомлений, и для long-polling воркера.
"""
from typing import Any, Optional
import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"


class TelegramServiceError(Exception):
    """Любая ошибка взаимодействия с Telegram Bot API."""


class TelegramService:
    """Минимальный клиент Telegram Bot API."""

    def __init__(self, token: Optional[str] = None, request_timeout: float = 10.0):
        self.token = token or settings.TELEGRAM_BOT_TOKEN
        self.request_timeout = request_timeout

    @property
    def is_configured(self) -> bool:
        return bool(self.token)

    def _url(self, method: str) -> str:
        return f"{TELEGRAM_API_BASE}/bot{self.token}/{method}"

    async def _call(
        self,
        method: str,
        payload: Optional[dict] = None,
        timeout: Optional[float] = None,
    ) -> dict[str, Any]:
        if not self.is_configured:
            raise TelegramServiceError("TELEGRAM_BOT_TOKEN is not configured")

        try:
            async with httpx.AsyncClient(timeout=timeout or self.request_timeout) as client:
                response = await client.post(self._url(method), json=payload or {})
        except httpx.HTTPError as exc:
            raise TelegramServiceError(f"HTTP error calling {method}: {exc}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise TelegramServiceError(
                f"Non-JSON response from {method} (status {response.status_code})"
            ) from exc

        if not data.get("ok"):
            description = data.get("description", "unknown error")
            raise TelegramServiceError(f"Telegram API {method} failed: {description}")

        return data

    async def send_message(
        self,
        chat_id: str | int,
        text: str,
        parse_mode: Optional[str] = "HTML",
        disable_web_page_preview: bool = True,
    ) -> dict[str, Any]:
        """Отправить сообщение в чат. Возвращает result из ответа Telegram."""
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": disable_web_page_preview,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        data = await self._call("sendMessage", payload)
        return data.get("result", {})

    async def get_updates(
        self,
        offset: Optional[int] = None,
        timeout: int = 25,
        allowed_updates: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        """Long-polling getUpdates. timeout — сколько секунд держит коннект Telegram."""
        payload: dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            payload["offset"] = offset
        if allowed_updates is not None:
            payload["allowed_updates"] = allowed_updates
        # +5 секунд запаса поверх long-poll timeout
        data = await self._call("getUpdates", payload, timeout=timeout + 5)
        return data.get("result", []) or []

    async def get_me(self) -> dict[str, Any]:
        """Информация о боте — используется для self-check на старте."""
        data = await self._call("getMe")
        return data.get("result", {})


telegram_service = TelegramService()
