"""Юнит-тесты обработчика входящих апдейтов polling-воркера.

Используем настоящую тестовую БД (parking_test) — модели + relationships
проверяются заодно. Telegram-клиент мокаем целиком.
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.customer import Customer
from app.models.telegram_link_token import TelegramLinkToken
from app.services import telegram_polling as polling_module
from app.services.telegram_polling import TelegramPollingWorker


# ---------- фикстуры ----------

@pytest.fixture
def fake_tg() -> AsyncMock:
    tg = AsyncMock()
    tg.is_configured = True
    tg.send_message = AsyncMock(return_value={})
    return tg


@pytest.fixture
def worker(fake_tg, db_engine, monkeypatch) -> TelegramPollingWorker:
    """Воркер с замоканным TG-клиентом и тестовым sessionmaker."""
    test_sm = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(polling_module, "AsyncSessionLocal", test_sm)
    return TelegramPollingWorker(fake_tg)


@pytest.fixture
async def customer_with_token(db_session: AsyncSession):
    """Юзер + неиспользованный валидный link-token."""
    customer = Customer(
        first_name="Иван",
        last_name="Иванов",
        email="link@test.com",
        phone="+79991112233",
        password_hash="x",
    )
    db_session.add(customer)
    await db_session.commit()
    await db_session.refresh(customer)

    token = TelegramLinkToken(
        customer_id=customer.customer_id,
        token="valid-token-1",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        used=False,
    )
    db_session.add(token)
    await db_session.commit()
    return customer, token


def _start_update(text: str, chat_id: int = 555) -> dict:
    return {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "chat": {"id": chat_id, "type": "private"},
            "text": text,
        },
    }


# ---------- /start TOKEN happy path ----------

@pytest.mark.asyncio
async def test_start_with_valid_token_links_customer(
    worker, fake_tg, db_session, customer_with_token
):
    customer, token = customer_with_token

    await worker._handle_update(_start_update("/start valid-token-1", chat_id=777))

    await db_session.refresh(customer)
    await db_session.refresh(token)
    assert customer.telegram_chat_id == "777"
    assert token.used is True

    fake_tg.send_message.assert_awaited_once()
    args, _ = fake_tg.send_message.call_args
    assert args[0] == 777
    assert "Готово" in args[1]


# ---------- ошибки токена ----------

@pytest.mark.asyncio
async def test_start_with_unknown_token_replies_not_found(
    worker, fake_tg, db_session, customer_with_token
):
    customer, _ = customer_with_token

    await worker._handle_update(_start_update("/start unknown-token"))

    await db_session.refresh(customer)
    assert customer.telegram_chat_id is None
    fake_tg.send_message.assert_awaited_once()
    assert "не найден" in fake_tg.send_message.call_args[0][1].lower()


@pytest.mark.asyncio
async def test_start_with_used_token_replies_used(
    worker, fake_tg, db_session, customer_with_token
):
    customer, token = customer_with_token
    token.used = True
    await db_session.commit()

    await worker._handle_update(_start_update("/start valid-token-1"))

    await db_session.refresh(customer)
    assert customer.telegram_chat_id is None
    assert "использован" in fake_tg.send_message.call_args[0][1].lower()


@pytest.mark.asyncio
async def test_start_with_expired_token_replies_expired(
    worker, fake_tg, db_session, customer_with_token
):
    customer, token = customer_with_token
    token.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db_session.commit()

    await worker._handle_update(_start_update("/start valid-token-1"))

    await db_session.refresh(customer)
    assert customer.telegram_chat_id is None
    text = fake_tg.send_message.call_args[0][1].lower()
    assert "истёк" in text or "истек" in text


@pytest.mark.asyncio
async def test_chat_already_linked_to_other_customer_is_rejected(
    worker, fake_tg, db_session, customer_with_token
):
    customer, token = customer_with_token

    # Другой юзер с уже занятым chat_id 777
    other = Customer(
        first_name="Other",
        last_name="One",
        email="other@test.com",
        phone="+70000000001",
        password_hash="x",
        telegram_chat_id="777",
    )
    db_session.add(other)
    await db_session.commit()

    await worker._handle_update(_start_update("/start valid-token-1", chat_id=777))

    await db_session.refresh(customer)
    await db_session.refresh(token)
    assert customer.telegram_chat_id is None
    assert token.used is False
    assert "другому" in fake_tg.send_message.call_args[0][1].lower()


# ---------- /start без аргумента и прочие сообщения ----------

@pytest.mark.asyncio
async def test_start_without_token_sends_hint(worker, fake_tg):
    await worker._handle_update(_start_update("/start"))

    fake_tg.send_message.assert_awaited_once()
    assert "личный кабинет" in fake_tg.send_message.call_args[0][1].lower()


@pytest.mark.asyncio
async def test_unknown_command_sends_help(worker, fake_tg):
    await worker._handle_update(_start_update("/help"))

    fake_tg.send_message.assert_awaited_once()
    assert "/start" in fake_tg.send_message.call_args[0][1]


@pytest.mark.asyncio
async def test_update_without_message_is_ignored(worker, fake_tg):
    await worker._handle_update({"update_id": 1, "callback_query": {}})
    fake_tg.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_message_without_text_is_ignored(worker, fake_tg):
    update = {
        "update_id": 1,
        "message": {"chat": {"id": 1}, "photo": [{"file_id": "x"}]},
    }
    await worker._handle_update(update)
    fake_tg.send_message.assert_not_called()
