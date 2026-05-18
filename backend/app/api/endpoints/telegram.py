"""Telegram link-account endpoints."""
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import get_current_customer
from app.db.database import get_db
from app.models.customer import Customer
from app.models.telegram_link_token import TelegramLinkToken
from app.schemas.telegram import TelegramLinkTokenResponse, TelegramStatusResponse

router = APIRouter()


def _bot_username() -> str:
    """Username из настроек без ведущего @."""
    raw = settings.TELEGRAM_BOT_USERNAME or ""
    return raw.lstrip("@").strip()


def _ensure_bot_configured() -> None:
    if not settings.TELEGRAM_BOT_TOKEN or not _bot_username():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram-бот не сконфигурирован на сервере",
        )


@router.post("/link-token", response_model=TelegramLinkTokenResponse)
async def create_link_token(
    current_customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
):
    """Сгенерировать одноразовый токен для привязки Telegram-аккаунта."""
    _ensure_bot_configured()

    if current_customer.telegram_chat_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Telegram уже привязан. Сначала отвяжите текущий.",
        )

    # Чистим неиспользованные токены этого юзера, чтобы старые ссылки не работали
    await db.execute(
        delete(TelegramLinkToken).where(
            TelegramLinkToken.customer_id == current_customer.customer_id,
            TelegramLinkToken.used.is_(False),
        )
    )

    ttl_minutes = settings.TELEGRAM_LINK_TOKEN_TTL_MINUTES
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
    token_value = secrets.token_urlsafe(24)

    link_token = TelegramLinkToken(
        customer_id=current_customer.customer_id,
        token=token_value,
        expires_at=expires_at,
        used=False,
    )
    db.add(link_token)
    await db.commit()

    return TelegramLinkTokenResponse(
        token=token_value,
        deep_link=f"https://t.me/{_bot_username()}?start={token_value}",
        expires_at=expires_at,
        ttl_seconds=ttl_minutes * 60,
    )


@router.get("/status", response_model=TelegramStatusResponse)
async def get_link_status(
    current_customer: Customer = Depends(get_current_customer),
):
    """Привязан ли Telegram к текущему аккаунту."""
    return TelegramStatusResponse(
        linked=bool(current_customer.telegram_chat_id),
        telegram_chat_id=current_customer.telegram_chat_id,
        bot_username=_bot_username() or None,
    )


@router.delete("/link", status_code=status.HTTP_200_OK)
async def unlink_telegram(
    current_customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
):
    """Отвязать Telegram от текущего аккаунта."""
    if not current_customer.telegram_chat_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Telegram не привязан",
        )

    current_customer.telegram_chat_id = None
    await db.execute(
        delete(TelegramLinkToken).where(
            TelegramLinkToken.customer_id == current_customer.customer_id,
            TelegramLinkToken.used.is_(False),
        )
    )
    await db.commit()
    return {"message": "Telegram отвязан"}
