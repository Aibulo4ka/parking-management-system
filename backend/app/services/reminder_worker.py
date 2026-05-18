"""
Фоновый воркер напоминаний о бронированиях.

Раз в REMINDER_POLL_INTERVAL_SECONDS ищет брони, у которых:
- status IN ('pending', 'confirmed')
- reminder_sent_at IS NULL
- start_time <= now + REMINDER_LEAD_MINUTES
- start_time > now
- у юзера привязан Telegram

Для каждой такой брони шлёт уведомление и проставляет reminder_sent_at.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.models.booking import Booking
from app.models.customer import Customer
from app.models.parking_spot import ParkingSpot
from app.models.parking_zone import ParkingZone

logger = logging.getLogger(__name__)


class ReminderWorker:
    """Цикл, который шлёт пред-стартовые напоминания о бронированиях."""

    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._stopping = asyncio.Event()

    def start(self) -> None:
        if self._task and not self._task.done():
            logger.warning("Reminder worker is already running")
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._run(), name="booking-reminder")
        logger.info(
            "Reminder worker started (lead=%dmin, interval=%ds)",
            settings.REMINDER_LEAD_MINUTES,
            settings.REMINDER_POLL_INTERVAL_SECONDS,
        )

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
        logger.info("Reminder worker stopped")

    async def _run(self) -> None:
        interval = max(5, settings.REMINDER_POLL_INTERVAL_SECONDS)
        while not self._stopping.is_set():
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.exception("Reminder tick failed: %s", exc)

            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    async def _tick(self) -> None:
        """Один проход — найти брони и отправить напоминания."""
        from app.services.notification_service import notification_service

        async with AsyncSessionLocal() as session:
            due = await self._find_due_bookings(session)
            if not due:
                return

            for booking, customer, spot, zone in due:
                logger.info("Sending reminder for booking %s", booking.booking_id)
                await notification_service.send_booking_reminder(
                    customer_email=customer.email,
                    customer_name=f"{customer.first_name} {customer.last_name}",
                    zone_name=zone.name,
                    spot_number=spot.spot_number,
                    start_time=booking.start_time,
                    telegram_chat_id=customer.telegram_chat_id,
                )
                booking.reminder_sent_at = datetime.now(timezone.utc)

            await session.commit()

    async def _find_due_bookings(self, session: AsyncSession):
        """Брони, которым пора отправлять напоминание."""
        now = datetime.now(timezone.utc)
        lead = timedelta(minutes=settings.REMINDER_LEAD_MINUTES)

        stmt = (
            select(Booking, Customer, ParkingSpot, ParkingZone)
            .join(Customer, Customer.customer_id == Booking.customer_id)
            .join(ParkingSpot, ParkingSpot.spot_id == Booking.spot_id)
            .join(ParkingZone, ParkingZone.zone_id == ParkingSpot.zone_id)
            .where(
                and_(
                    Booking.reminder_sent_at.is_(None),
                    Booking.status.in_(("pending", "confirmed")),
                    Booking.start_time > now,
                    Booking.start_time <= now + lead,
                    Customer.telegram_chat_id.is_not(None),
                )
            )
        )
        result = await session.execute(stmt)
        return result.all()


reminder_worker = ReminderWorker()


def should_start_reminder_worker() -> bool:
    return bool(settings.REMINDER_ENABLED)
