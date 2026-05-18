from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings"""

    # Database settings
    DATABASE_URL: str = "postgresql+asyncpg://parking_user:parking_pass@db:5432/parking_db"

    # Security settings
    SECRET_KEY: str = "your-super-secret-key-change-this-in-production-123456789"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Application settings
    PROJECT_NAME: str = "Parking Management System"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api"

    # Telegram bot settings
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_BOT_USERNAME: Optional[str] = None
    TELEGRAM_POLL_ENABLED: bool = False
    TELEGRAM_LINK_TOKEN_TTL_MINUTES: int = 10

    # Booking reminder worker
    REMINDER_ENABLED: bool = False
    REMINDER_LEAD_MINUTES: int = 30
    REMINDER_POLL_INTERVAL_SECONDS: int = 60

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
