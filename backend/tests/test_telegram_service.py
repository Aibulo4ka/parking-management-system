"""Юнит-тесты для TelegramService — мок httpx, проверка retry/ошибок."""
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.services import telegram_service as ts_module
from app.services.telegram_service import TelegramService, TelegramServiceError


def _mock_response(payload: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    return resp


@pytest.fixture
def patch_httpx(monkeypatch):
    """Подмена httpx.AsyncClient внутри telegram_service. Возвращает контроллер."""

    state = {"post_side_effect": None, "post_return": None, "calls": []}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            state["init_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json=None):
            state["calls"].append({"url": url, "json": json})
            if state["post_side_effect"] is not None:
                effect = state["post_side_effect"]
                if isinstance(effect, list):
                    item = effect.pop(0)
                else:
                    item = effect
                if isinstance(item, Exception):
                    raise item
                return item
            return state["post_return"]

    monkeypatch.setattr(ts_module.httpx, "AsyncClient", FakeClient)
    return state


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Ускоряем тесты, отключаем реальные паузы между ретраями."""
    async def _instant_sleep(_seconds):
        return None
    monkeypatch.setattr(ts_module.asyncio, "sleep", _instant_sleep)


@pytest.mark.asyncio
async def test_is_configured_reflects_token(monkeypatch):
    # Чтобы конструктор не подтягивал реальный токен из .env при token=None.
    monkeypatch.setattr(ts_module.settings, "TELEGRAM_BOT_TOKEN", None)
    assert TelegramService(token="abc").is_configured is True
    assert TelegramService(token=None).is_configured is False


@pytest.mark.asyncio
async def test_call_returns_payload_on_ok(patch_httpx):
    patch_httpx["post_return"] = _mock_response({"ok": True, "result": {"id": 42}})
    svc = TelegramService(token="abc")

    data = await svc._call("getMe")

    assert data == {"ok": True, "result": {"id": 42}}
    assert patch_httpx["calls"][0]["url"].endswith("/botabc/getMe")


@pytest.mark.asyncio
async def test_call_raises_when_api_returns_ok_false(patch_httpx):
    patch_httpx["post_return"] = _mock_response(
        {"ok": False, "description": "chat not found"}
    )
    svc = TelegramService(token="abc")

    with pytest.raises(TelegramServiceError, match="chat not found"):
        await svc._call("sendMessage", {"chat_id": 1, "text": "x"})


@pytest.mark.asyncio
async def test_call_raises_when_response_not_json(patch_httpx):
    resp = MagicMock()
    resp.status_code = 502
    resp.json.side_effect = ValueError("boom")
    patch_httpx["post_return"] = resp
    svc = TelegramService(token="abc")

    with pytest.raises(TelegramServiceError, match="Non-JSON"):
        await svc._call("sendMessage")


@pytest.mark.asyncio
async def test_call_wraps_httpx_errors(patch_httpx):
    patch_httpx["post_side_effect"] = httpx.ConnectTimeout("boom")
    svc = TelegramService(token="abc")

    with pytest.raises(TelegramServiceError, match="ConnectTimeout"):
        await svc._call("sendMessage")


@pytest.mark.asyncio
async def test_send_message_retries_and_succeeds(patch_httpx):
    patch_httpx["post_side_effect"] = [
        httpx.ConnectTimeout(""),
        _mock_response({"ok": True, "result": {"message_id": 7}}),
    ]
    svc = TelegramService(token="abc")

    result = await svc.send_message(123, "hi")

    assert result == {"message_id": 7}
    assert len(patch_httpx["calls"]) == 2


@pytest.mark.asyncio
async def test_send_message_exhausts_retries(patch_httpx):
    patch_httpx["post_side_effect"] = [
        httpx.ConnectTimeout(""),
        httpx.ConnectTimeout(""),
        httpx.ConnectTimeout(""),
    ]
    svc = TelegramService(token="abc")

    with pytest.raises(TelegramServiceError):
        await svc.send_message(123, "hi")

    # 3 попытки = (0.0, 0.5, 1.5) согласно SEND_RETRY_DELAYS
    assert len(patch_httpx["calls"]) == 3


@pytest.mark.asyncio
async def test_send_message_uses_html_parse_mode_by_default(patch_httpx):
    patch_httpx["post_return"] = _mock_response({"ok": True, "result": {}})
    svc = TelegramService(token="abc")

    await svc.send_message(123, "<b>hi</b>")

    body = patch_httpx["calls"][0]["json"]
    assert body["parse_mode"] == "HTML"
    assert body["disable_web_page_preview"] is True


@pytest.mark.asyncio
async def test_get_updates_returns_result_list(patch_httpx):
    patch_httpx["post_return"] = _mock_response(
        {"ok": True, "result": [{"update_id": 1}, {"update_id": 2}]}
    )
    svc = TelegramService(token="abc")

    updates = await svc.get_updates(offset=10, timeout=5)

    assert len(updates) == 2
    body = patch_httpx["calls"][0]["json"]
    assert body == {"timeout": 5, "offset": 10}


@pytest.mark.asyncio
async def test_call_raises_without_token(monkeypatch):
    monkeypatch.setattr(ts_module.settings, "TELEGRAM_BOT_TOKEN", None)
    svc = TelegramService(token=None)
    with pytest.raises(TelegramServiceError, match="not configured"):
        await svc._call("getMe")
