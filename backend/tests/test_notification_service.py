"""Юнит-тесты NotificationService — форматтер времени и интеграция с Telegram."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.services import notification_service as ns_module
from app.services.notification_service import NotificationService, _fmt_dt
from app.services.telegram_service import TelegramServiceError


# ---------- _fmt_dt ----------

def test_fmt_dt_converts_utc_to_msk():
    utc = datetime(2026, 5, 18, 18, 39, tzinfo=timezone.utc)
    assert _fmt_dt(utc) == "18.05.2026 21:39"


def test_fmt_dt_handles_naive_as_utc():
    naive = datetime(2026, 5, 18, 18, 39)
    assert _fmt_dt(naive) == "18.05.2026 21:39"


def test_fmt_dt_handles_already_msk_offset():
    msk = datetime(2026, 5, 18, 21, 39, tzinfo=ns_module.MSK)
    assert _fmt_dt(msk) == "18.05.2026 21:39"


# ---------- send_* интеграция с Telegram ----------

def _fake_tg(configured: bool = True) -> AsyncMock:
    tg = AsyncMock()
    tg.is_configured = configured
    tg.send_message = AsyncMock(return_value={})
    return tg


@pytest.mark.asyncio
async def test_booking_confirmation_sends_to_telegram_when_chat_id_present():
    tg = _fake_tg()
    svc = NotificationService(email_enabled=False, tg_service=tg)

    await svc.send_booking_confirmation(
        customer_email="u@e.com",
        customer_name="Иван Иванов",
        booking_id="abcdef1234",
        zone_name="Зона А",
        spot_number="A-12",
        start_time=datetime(2026, 5, 18, 14, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 5, 18, 18, 0, tzinfo=timezone.utc),
        telegram_chat_id="999",
    )

    tg.send_message.assert_awaited_once()
    args, _ = tg.send_message.call_args
    chat_id, text = args
    assert chat_id == "999"
    assert "Бронирование подтверждено" in text
    # время приведено к МСК
    assert "17:00" in text and "21:00" in text
    assert "Зона А" in text


@pytest.mark.asyncio
async def test_send_skipped_without_chat_id():
    tg = _fake_tg()
    svc = NotificationService(email_enabled=False, tg_service=tg)

    await svc.send_booking_confirmation(
        customer_email="u@e.com",
        customer_name="X",
        booking_id="1",
        zone_name="Z",
        spot_number="A1",
        start_time=datetime(2026, 5, 18, 14, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 5, 18, 15, 0, tzinfo=timezone.utc),
        telegram_chat_id=None,
    )

    tg.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_send_skipped_when_bot_not_configured():
    tg = _fake_tg(configured=False)
    svc = NotificationService(email_enabled=False, tg_service=tg)

    await svc.send_session_started(
        customer_email="u@e.com",
        customer_name="X",
        session_id="s1",
        zone_name="Z",
        spot_number="A1",
        vehicle_plate="A777AA",
        entry_time=datetime(2026, 5, 18, 14, 0, tzinfo=timezone.utc),
        telegram_chat_id="123",
    )

    tg.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_send_does_not_propagate_telegram_errors():
    tg = _fake_tg()
    tg.send_message.side_effect = TelegramServiceError("boom")
    svc = NotificationService(email_enabled=False, tg_service=tg)

    # Не должно поднимать — у NotificationService свой try/except + _send_telegram глушит TG-ошибки.
    result = await svc.send_payment_confirmation(
        customer_email="u@e.com",
        customer_name="X",
        payment_id="p1",
        amount=100.0,
        payment_method="card",
        transaction_id="tx1",
        telegram_chat_id="123",
    )

    assert result is True
    tg.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_session_ended_message_contains_duration_and_cost():
    tg = _fake_tg()
    svc = NotificationService(email_enabled=False, tg_service=tg)

    await svc.send_session_ended(
        customer_email="u@e.com",
        customer_name="X",
        session_id="abcd1234",
        zone_name="Z",
        spot_number="A1",
        vehicle_plate="A777AA",
        entry_time=datetime(2026, 5, 18, 14, 0, tzinfo=timezone.utc),
        exit_time=datetime(2026, 5, 18, 15, 30, tzinfo=timezone.utc),
        duration_minutes=90,
        total_cost=275.0,
        telegram_chat_id="123",
    )

    args, _ = tg.send_message.call_args
    text = args[1]
    assert "1ч 30мин" in text
    assert "275.00" in text


@pytest.mark.asyncio
async def test_booking_reminder_calls_telegram():
    tg = _fake_tg()
    svc = NotificationService(email_enabled=False, tg_service=tg)

    await svc.send_booking_reminder(
        customer_email="u@e.com",
        customer_name="X",
        zone_name="Z",
        spot_number="A1",
        start_time=datetime(2026, 5, 18, 14, 0, tzinfo=timezone.utc),
        telegram_chat_id="555",
    )

    args, _ = tg.send_message.call_args
    assert args[0] == "555"
    assert "Скоро начало брони" in args[1]
