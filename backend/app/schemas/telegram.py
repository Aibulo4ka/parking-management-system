from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class TelegramLinkTokenResponse(BaseModel):
    """Одноразовый токен для привязки Telegram + deep-link, который юзер открывает в TG."""
    token: str
    deep_link: str
    expires_at: datetime
    ttl_seconds: int


class TelegramStatusResponse(BaseModel):
    """Состояние привязки Telegram у текущего юзера."""
    linked: bool
    telegram_chat_id: Optional[str] = None
    bot_username: Optional[str] = None
