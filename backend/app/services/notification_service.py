"""
Notification Service
Handles email and Telegram notifications for parking events.
"""
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Optional
import logging

from app.services.telegram_service import (
    TelegramService,
    TelegramServiceError,
    telegram_service,
)

logger = logging.getLogger(__name__)

# Все уведомления рендерим в московском времени (UTC+3, без DST с 2014).
MSK = timezone(timedelta(hours=3))


def _fmt_dt(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(MSK).strftime("%d.%m.%Y %H:%M")


class NotificationService:
    """Service for sending notifications to users (email log + Telegram)."""

    def __init__(
        self,
        email_enabled: bool = False,
        tg_service: Optional[TelegramService] = None,
    ):
        self.email_enabled = email_enabled
        self.telegram = tg_service or telegram_service
        logger.info(
            "Notification service initialized (email_enabled=%s, telegram_configured=%s)",
            email_enabled,
            self.telegram.is_configured,
        )

    async def send_booking_confirmation(
        self,
        customer_email: str,
        customer_name: str,
        booking_id: str,
        zone_name: str,
        spot_number: str,
        start_time: datetime,
        end_time: datetime,
        telegram_chat_id: Optional[str] = None,
    ) -> bool:
        try:
            subject = "Подтверждение бронирования парковочного места"
            message = (
                f"Здравствуйте, {customer_name}!\n\n"
                f"Ваше бронирование успешно создано.\n\n"
                f"Детали бронирования:\n"
                f"- Номер бронирования: {booking_id[:8]}\n"
                f"- Зона: {zone_name}\n"
                f"- Место: {spot_number}\n"
                f"- Начало: {_fmt_dt(start_time)}\n"
                f"- Окончание: {_fmt_dt(end_time)}\n\n"
                f"Спасибо, что выбрали нашу парковку!"
            )
            await self._send_email(customer_email, subject, message)

            tg_text = (
                f"✅ <b>Бронирование подтверждено</b>\n"
                f"№ <code>{escape(booking_id[:8])}</code>\n"
                f"Зона: <b>{escape(zone_name)}</b>, место <b>{escape(spot_number)}</b>\n"
                f"С {_fmt_dt(start_time)} до {_fmt_dt(end_time)}"
            )
            await self._send_telegram(telegram_chat_id, tg_text)
            return True
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to send booking confirmation: {e}")
            return False

    async def send_session_started(
        self,
        customer_email: str,
        customer_name: str,
        session_id: str,
        zone_name: str,
        spot_number: str,
        vehicle_plate: str,
        entry_time: datetime,
        telegram_chat_id: Optional[str] = None,
    ) -> bool:
        try:
            subject = "Парковочная сессия начата"
            message = (
                f"Здравствуйте, {customer_name}!\n\n"
                f"Ваша парковочная сессия начата.\n\n"
                f"Детали:\n"
                f"- Номер сессии: {session_id[:8]}\n"
                f"- Зона: {zone_name}\n"
                f"- Место: {spot_number}\n"
                f"- Автомобиль: {vehicle_plate}\n"
                f"- Время въезда: {_fmt_dt(entry_time)}\n\n"
                f"Удачной поездки!"
            )
            await self._send_email(customer_email, subject, message)

            tg_text = (
                f"🚗 <b>Въезд зафиксирован</b>\n"
                f"Зона: <b>{escape(zone_name)}</b>, место <b>{escape(spot_number)}</b>\n"
                f"Авто: <code>{escape(vehicle_plate)}</code>\n"
                f"Время: {_fmt_dt(entry_time)}"
            )
            await self._send_telegram(telegram_chat_id, tg_text)
            return True
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to send session started notification: {e}")
            return False

    async def send_session_ended(
        self,
        customer_email: str,
        customer_name: str,
        session_id: str,
        zone_name: str,
        spot_number: str,
        vehicle_plate: str,
        entry_time: datetime,
        exit_time: datetime,
        duration_minutes: int,
        total_cost: float,
        telegram_chat_id: Optional[str] = None,
    ) -> bool:
        try:
            hours = duration_minutes // 60
            minutes = duration_minutes % 60

            subject = "Парковочная сессия завершена"
            message = (
                f"Здравствуйте, {customer_name}!\n\n"
                f"Ваша парковочная сессия завершена.\n\n"
                f"Детали:\n"
                f"- Номер сессии: {session_id[:8]}\n"
                f"- Зона: {zone_name}\n"
                f"- Место: {spot_number}\n"
                f"- Автомобиль: {vehicle_plate}\n"
                f"- Время въезда: {_fmt_dt(entry_time)}\n"
                f"- Время выезда: {_fmt_dt(exit_time)}\n"
                f"- Длительность: {hours}ч {minutes}мин\n"
                f"- Стоимость: {total_cost:.2f} ₽\n\n"
                f"Пожалуйста, оплатите парковку в личном кабинете."
            )
            await self._send_email(customer_email, subject, message)

            tg_text = (
                f"🅿️ <b>Выезд зафиксирован</b>\n"
                f"Зона: <b>{escape(zone_name)}</b>, место <b>{escape(spot_number)}</b>\n"
                f"Авто: <code>{escape(vehicle_plate)}</code>\n"
                f"Длительность: <b>{hours}ч {minutes}мин</b>\n"
                f"К оплате: <b>{total_cost:.2f} ₽</b>"
            )
            await self._send_telegram(telegram_chat_id, tg_text)
            return True
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to send session ended notification: {e}")
            return False

    async def send_payment_confirmation(
        self,
        customer_email: str,
        customer_name: str,
        payment_id: str,
        amount: float,
        payment_method: str,
        transaction_id: Optional[str] = None,
        telegram_chat_id: Optional[str] = None,
    ) -> bool:
        try:
            subject = "Платеж успешно обработан"
            message = (
                f"Здравствуйте, {customer_name}!\n\n"
                f"Ваш платеж успешно обработан.\n\n"
                f"Детали платежа:\n"
                f"- Номер платежа: {payment_id[:8]}\n"
                f"- Сумма: {amount:.2f} ₽\n"
                f"- Способ оплаты: {payment_method}\n"
            )
            if transaction_id:
                message += f"- ID транзакции: {transaction_id}\n"
            message += "\nСпасибо за оплату!"
            await self._send_email(customer_email, subject, message)

            tg_text = (
                f"💳 <b>Платёж прошёл</b>\n"
                f"Сумма: <b>{amount:.2f} ₽</b>\n"
                f"Способ: {escape(payment_method)}\n"
                f"№ платежа: <code>{escape(payment_id[:8])}</code>"
            )
            await self._send_telegram(telegram_chat_id, tg_text)
            return True
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to send payment confirmation: {e}")
            return False

    async def send_booking_reminder(
        self,
        customer_email: str,
        customer_name: str,
        zone_name: str,
        spot_number: str,
        start_time: datetime,
        telegram_chat_id: Optional[str] = None,
    ) -> bool:
        try:
            subject = "Напоминание о бронировании"
            message = (
                f"Здравствуйте, {customer_name}!\n\n"
                f"Напоминаем, что у вас скоро начинается бронирование:\n\n"
                f"- Зона: {zone_name}\n"
                f"- Место: {spot_number}\n"
                f"- Начало: {_fmt_dt(start_time)}\n\n"
                f"Не забудьте прибыть вовремя!"
            )
            await self._send_email(customer_email, subject, message)

            tg_text = (
                f"⏰ <b>Скоро начало брони</b>\n"
                f"Зона: <b>{escape(zone_name)}</b>, место <b>{escape(spot_number)}</b>\n"
                f"Начало: {_fmt_dt(start_time)}"
            )
            await self._send_telegram(telegram_chat_id, tg_text)
            return True
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to send booking reminder: {e}")
            return False

    async def _send_email(self, to_email: str, subject: str, message: str) -> None:
        if self.email_enabled:
            logger.info(f"Would send email to {to_email}: {subject}")
        else:
            logger.info(
                f"\n{'='*60}\n"
                f"EMAIL NOTIFICATION\n"
                f"To: {to_email}\n"
                f"Subject: {subject}\n"
                f"Message:\n{message}\n"
                f"{'='*60}\n"
            )

    async def _send_telegram(self, chat_id: Optional[str], html: str) -> None:
        """Отправить в Telegram, если есть chat_id и бот сконфигурирован. Ошибки не пробрасываем."""
        if not chat_id or not self.telegram.is_configured:
            return
        try:
            await self.telegram.send_message(chat_id, html)
        except TelegramServiceError as exc:
            logger.error("Telegram send failed for chat_id=%s: %s", chat_id, exc)


notification_service = NotificationService(email_enabled=False)
