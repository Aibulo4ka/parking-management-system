"""Тесты API-эндпоинтов /api/telegram/*."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.customer import Customer
from app.models.telegram_link_token import TelegramLinkToken


@pytest.fixture(autouse=True)
def configure_bot(monkeypatch):
    """Эмулируем настроенного бота в Settings, чтобы эндпоинты не падали в 503."""
    from app.api.endpoints import telegram as tg_endpoints

    monkeypatch.setattr(tg_endpoints.settings, "TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setattr(tg_endpoints.settings, "TELEGRAM_BOT_USERNAME", "@TestBot")
    monkeypatch.setattr(tg_endpoints.settings, "TELEGRAM_LINK_TOKEN_TTL_MINUTES", 10)


# ---------- /status ----------

@pytest.mark.asyncio
async def test_status_unlinked_by_default(client: AsyncClient, auth_headers):
    response = await client.get("/api/telegram/status", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["linked"] is False
    assert body["telegram_chat_id"] is None
    assert body["bot_username"] == "TestBot"


@pytest.mark.asyncio
async def test_status_linked_when_chat_id_set(
    client: AsyncClient, auth_headers, db_session: AsyncSession, test_customer: Customer
):
    test_customer.telegram_chat_id = "999"
    await db_session.commit()

    response = await client.get("/api/telegram/status", headers=auth_headers)

    body = response.json()
    assert body["linked"] is True
    assert body["telegram_chat_id"] == "999"


# ---------- /link-token ----------

@pytest.mark.asyncio
async def test_create_link_token_returns_deep_link_and_persists(
    client: AsyncClient, auth_headers, db_session: AsyncSession, test_customer: Customer
):
    response = await client.post("/api/telegram/link-token", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["token"]
    assert body["deep_link"] == f"https://t.me/TestBot?start={body['token']}"
    assert body["ttl_seconds"] == 600

    # Проверяем что токен сохранился в БД
    result = await db_session.execute(
        select(TelegramLinkToken).where(TelegramLinkToken.token == body["token"])
    )
    saved = result.scalar_one()
    assert saved.customer_id == test_customer.customer_id
    assert saved.used is False


@pytest.mark.asyncio
async def test_create_link_token_rejects_already_linked(
    client: AsyncClient, auth_headers, db_session: AsyncSession, test_customer: Customer
):
    test_customer.telegram_chat_id = "999"
    await db_session.commit()

    response = await client.post("/api/telegram/link-token", headers=auth_headers)

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_create_link_token_invalidates_previous_unused_tokens(
    client: AsyncClient, auth_headers, db_session: AsyncSession, test_customer: Customer
):
    # Первый запрос
    first = (await client.post("/api/telegram/link-token", headers=auth_headers)).json()
    # Второй запрос должен затереть первый
    second = (await client.post("/api/telegram/link-token", headers=auth_headers)).json()

    assert first["token"] != second["token"]
    # В БД остался только новый токен
    result = await db_session.execute(
        select(TelegramLinkToken).where(
            TelegramLinkToken.customer_id == test_customer.customer_id
        )
    )
    tokens = result.scalars().all()
    assert len(tokens) == 1
    assert tokens[0].token == second["token"]


@pytest.mark.asyncio
async def test_create_link_token_returns_503_when_bot_not_configured(
    client: AsyncClient, auth_headers, monkeypatch
):
    from app.api.endpoints import telegram as tg_endpoints

    monkeypatch.setattr(tg_endpoints.settings, "TELEGRAM_BOT_TOKEN", None)

    response = await client.post("/api/telegram/link-token", headers=auth_headers)

    assert response.status_code == 503


# ---------- DELETE /link ----------

@pytest.mark.asyncio
async def test_unlink_resets_chat_id(
    client: AsyncClient, auth_headers, db_session: AsyncSession, test_customer: Customer
):
    test_customer.telegram_chat_id = "999"
    await db_session.commit()

    response = await client.delete("/api/telegram/link", headers=auth_headers)

    assert response.status_code == 200
    await db_session.refresh(test_customer)
    assert test_customer.telegram_chat_id is None


@pytest.mark.asyncio
async def test_unlink_when_not_linked_returns_400(client: AsyncClient, auth_headers):
    response = await client.delete("/api/telegram/link", headers=auth_headers)
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_unlink_clears_pending_tokens(
    client: AsyncClient, auth_headers, db_session: AsyncSession, test_customer: Customer
):
    test_customer.telegram_chat_id = "999"
    db_session.add(
        TelegramLinkToken(
            customer_id=test_customer.customer_id,
            token="abc",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
            used=False,
        )
    )
    await db_session.commit()

    await client.delete("/api/telegram/link", headers=auth_headers)

    result = await db_session.execute(
        select(TelegramLinkToken).where(
            TelegramLinkToken.customer_id == test_customer.customer_id
        )
    )
    assert result.scalars().all() == []


# ---------- авторизация ----------

@pytest.mark.asyncio
async def test_endpoints_require_auth(client: AsyncClient):
    for method, path in [
        ("get", "/api/telegram/status"),
        ("post", "/api/telegram/link-token"),
        ("delete", "/api/telegram/link"),
    ]:
        response = await getattr(client, method)(path)
        assert response.status_code in (401, 403)
