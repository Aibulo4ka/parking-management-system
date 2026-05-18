"""
Long-polling воркер для входящих апдейтов Telegram.

Запускается фоновым asyncio.Task в FastAPI lifespan, если включен
TELEGRAM_POLL_ENABLED. Сейчас обрабатывает только /start <TOKEN> —
привязку Telegram-аккаунта к Customer.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.models.customer import Customer
from app.models.telegram_link_token import TelegramLinkToken
from app.services.telegram_service import (
    TelegramService,
    TelegramServiceError,
    telegram_service,
)

logger = logging.getLogger(__name__)

# Сколько ждать после ошибки перед следующей попыткой getUpdates
ERROR_BACKOFF_SECONDS = 5


class TelegramPollingWorker:
    """Бесконечный цикл getUpdates → handle_update."""

    def __init__(self, service: TelegramService):
        self.service = service
        self._task: Optional[asyncio.Task] = None
        self._stopping = asyncio.Event()
        self._offset: Optional[int] = None

    def start(self) -> None:
        if self._task and not self._task.done():
            logger.warning("Telegram polling worker is already running")
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._run(), name="telegram-polling")
        logger.info("Telegram polling worker started")

    async def stop(self) -> None:
        if not self._task:
            return
        self._stopping.set()
        self._task.cancel()
        try:
            await self._task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        self._task = None
        logger.info("Telegram polling worker stopped")

    async def _run(self) -> None:
        try:
            me = await self.service.get_me()
            logger.info(
                "Telegram bot connected: @%s (id=%s)",
                me.get("username"),
                me.get("id"),
            )
        except TelegramServiceError as exc:
            logger.error("Cannot reach Telegram (bot token invalid?): %s", exc)
            return

        while not self._stopping.is_set():
            try:
                updates = await self.service.get_updates(offset=self._offset, timeout=25)
            except TelegramServiceError as exc:
                logger.error("getUpdates failed: %s", exc)
                await asyncio.sleep(ERROR_BACKOFF_SECONDS)
                continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.exception("Unexpected error in polling loop: %s", exc)
                await asyncio.sleep(ERROR_BACKOFF_SECONDS)
                continue

            for update in updates:
                self._offset = update["update_id"] + 1
                try:
                    await self._handle_update(update)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Failed to handle update %s: %s", update.get("update_id"), exc)

    async def _handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message") or update.get("edited_message")
        if not message:
            return

        text = (message.get("text") or "").strip()
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if not chat_id or not text:
            return

        if text.startswith("/start"):
            parts = text.split(maxsplit=1)
            token_value = parts[1].strip() if len(parts) > 1 else ""
            await self._handle_start(chat_id, token_value)
            return

        # Неизвестная команда — короткая подсказка
        await self._safe_reply(
            chat_id,
            "Я понимаю только команду <b>/start &lt;TOKEN&gt;</b> "
            "для привязки аккаунта. Сгенерируйте токен в личном кабинете на сайте.",
        )

    async def _handle_start(self, chat_id: int, token_value: str) -> None:
        if not token_value:
            await self._safe_reply(
                chat_id,
                "Чтобы привязать аккаунт, откройте личный кабинет на сайте парковки "
                "и нажмите «Подключить Telegram». Я открою ссылку вида "
                "<code>/start &lt;TOKEN&gt;</code>.",
            )
            return

        async with AsyncSessionLocal() as session:
            customer, reason = await self._consume_link_token(session, token_value, chat_id)
            if customer is None:
                await self._safe_reply(chat_id, reason)
                return

            await self._safe_reply(
                chat_id,
                f"✅ Готово, <b>{customer.first_name}</b>! "
                f"Ваш Telegram привязан к аккаунту <code>{customer.email}</code>. "
                f"Теперь сюда будут приходить уведомления о бронированиях и сессиях.",
            )

    async def _consume_link_token(
        self,
        session: AsyncSession,
        token_value: str,
        chat_id: int,
    ) -> tuple[Optional[Customer], str]:
        """Атомарно проверяет и расходует link-token; возвращает (customer, error_message)."""
        result = await session.execute(
            select(TelegramLinkToken).where(TelegramLinkToken.token == token_value)
        )
        link_token = result.scalar_one_or_none()
        if link_token is None:
            return None, "❌ Токен не найден. Сгенерируйте новый в личном кабинете."

        now = datetime.now(timezone.utc)
        if link_token.used:
            return None, "❌ Этот токен уже использован."
        if link_token.expires_at < now:
            return None, "❌ Срок действия токена истёк. Сгенерируйте новый."

        customer = await session.get(Customer, link_token.customer_id)
        if customer is None:
            return None, "❌ Аккаунт не найден."

        chat_id_str = str(chat_id)
        # Проверяем, не привязан ли этот chat_id уже к другому аккаунту
        existing = await session.execute(
            select(Customer).where(Customer.telegram_chat_id == chat_id_str)
        )
        other = existing.scalar_one_or_none()
        if other is not None and other.customer_id != customer.customer_id:
            return None, "❌ Этот Telegram уже привязан к другому аккаунту."

        customer.telegram_chat_id = chat_id_str
        link_token.used = True
        await session.commit()
        return customer, ""

    async def _safe_reply(self, chat_id: int, text: str) -> None:
        try:
            await self.service.send_message(chat_id, text)
        except TelegramServiceError as exc:
            logger.error("Failed to reply to chat %s: %s", chat_id, exc)


polling_worker = TelegramPollingWorker(telegram_service)


def should_start_polling() -> bool:
    return bool(settings.TELEGRAM_POLL_ENABLED and settings.TELEGRAM_BOT_TOKEN)
