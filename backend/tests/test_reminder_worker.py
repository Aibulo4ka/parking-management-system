"""Юнит-тесты ReminderWorker._tick — фильтрация и идемпотентность."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.booking import Booking
from app.models.customer import Customer
from app.models.parking_spot import ParkingSpot
from app.models.parking_zone import ParkingZone
from app.models.vehicle import Vehicle
from app.services import notification_service as ns_module
from app.services import reminder_worker as rw_module
from app.services.reminder_worker import ReminderWorker


@pytest.fixture
def fake_notification(monkeypatch) -> AsyncMock:
    """Подменяем глобальный notification_service на мок."""
    fake = AsyncMock()
    fake.send_booking_reminder = AsyncMock(return_value=True)
    monkeypatch.setattr(ns_module, "notification_service", fake)
    return fake


@pytest.fixture
def worker(db_engine, monkeypatch) -> ReminderWorker:
    test_sm = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(rw_module, "AsyncSessionLocal", test_sm)
    return ReminderWorker()


async def _seed_zone_spot_vehicle(db: AsyncSession, customer: Customer):
    zone = ParkingZone(name="Zone Test", address="addr", total_spots=10, available_spots=10)
    db.add(zone)
    await db.flush()
    spot = ParkingSpot(zone_id=zone.zone_id, spot_number="T1", spot_type="standard")
    db.add(spot)
    vehicle = Vehicle(
        customer_id=customer.customer_id,
        license_plate=f"A{customer.customer_id.hex[:6]}",
        vehicle_type="sedan",
    )
    db.add(vehicle)
    await db.flush()
    return zone, spot, vehicle


def _make_booking(customer, vehicle, spot, *, start_in_minutes: int, status="confirmed", reminder_sent_at=None):
    return Booking(
        customer_id=customer.customer_id,
        vehicle_id=vehicle.vehicle_id,
        spot_id=spot.spot_id,
        start_time=datetime.now(timezone.utc) + timedelta(minutes=start_in_minutes),
        end_time=datetime.now(timezone.utc) + timedelta(minutes=start_in_minutes + 60),
        estimated_cost=100,
        status=status,
        reminder_sent_at=reminder_sent_at,
    )


# ---------- happy path ----------

@pytest.mark.asyncio
async def test_tick_sends_reminder_for_due_booking(
    worker, fake_notification, db_session, test_customer
):
    test_customer.telegram_chat_id = "555"
    await db_session.commit()
    zone, spot, vehicle = await _seed_zone_spot_vehicle(db_session, test_customer)
    booking = _make_booking(test_customer, vehicle, spot, start_in_minutes=15)
    db_session.add(booking)
    await db_session.commit()

    await worker._tick()

    await db_session.refresh(booking)
    assert booking.reminder_sent_at is not None
    fake_notification.send_booking_reminder.assert_awaited_once()
    kwargs = fake_notification.send_booking_reminder.call_args.kwargs
    assert kwargs["telegram_chat_id"] == "555"
    assert kwargs["zone_name"] == "Zone Test"
    assert kwargs["spot_number"] == "T1"


@pytest.mark.asyncio
async def test_tick_does_not_send_twice(
    worker, fake_notification, db_session, test_customer
):
    test_customer.telegram_chat_id = "555"
    await db_session.commit()
    zone, spot, vehicle = await _seed_zone_spot_vehicle(db_session, test_customer)
    booking = _make_booking(test_customer, vehicle, spot, start_in_minutes=15)
    db_session.add(booking)
    await db_session.commit()

    await worker._tick()
    await worker._tick()

    fake_notification.send_booking_reminder.assert_awaited_once()


# ---------- фильтры ----------

@pytest.mark.asyncio
async def test_tick_skips_booking_already_started(
    worker, fake_notification, db_session, test_customer
):
    test_customer.telegram_chat_id = "555"
    await db_session.commit()
    zone, spot, vehicle = await _seed_zone_spot_vehicle(db_session, test_customer)
    db_session.add(_make_booking(test_customer, vehicle, spot, start_in_minutes=-5))
    await db_session.commit()

    await worker._tick()

    fake_notification.send_booking_reminder.assert_not_called()


@pytest.mark.asyncio
async def test_tick_skips_booking_outside_lead_window(
    worker, fake_notification, db_session, test_customer
):
    test_customer.telegram_chat_id = "555"
    await db_session.commit()
    zone, spot, vehicle = await _seed_zone_spot_vehicle(db_session, test_customer)
    db_session.add(_make_booking(test_customer, vehicle, spot, start_in_minutes=120))
    await db_session.commit()

    await worker._tick()

    fake_notification.send_booking_reminder.assert_not_called()


@pytest.mark.asyncio
async def test_tick_skips_customer_without_telegram(
    worker, fake_notification, db_session, test_customer
):
    # У test_customer нет telegram_chat_id
    zone, spot, vehicle = await _seed_zone_spot_vehicle(db_session, test_customer)
    db_session.add(_make_booking(test_customer, vehicle, spot, start_in_minutes=15))
    await db_session.commit()

    await worker._tick()

    fake_notification.send_booking_reminder.assert_not_called()


@pytest.mark.asyncio
async def test_tick_skips_cancelled_and_completed(
    worker, fake_notification, db_session, test_customer
):
    test_customer.telegram_chat_id = "555"
    await db_session.commit()
    zone, spot, vehicle = await _seed_zone_spot_vehicle(db_session, test_customer)
    db_session.add(_make_booking(test_customer, vehicle, spot, start_in_minutes=10, status="cancelled"))
    db_session.add(_make_booking(test_customer, vehicle, spot, start_in_minutes=12, status="completed"))
    await db_session.commit()

    await worker._tick()

    fake_notification.send_booking_reminder.assert_not_called()


@pytest.mark.asyncio
async def test_tick_handles_multiple_bookings(
    worker, fake_notification, db_session, test_customer
):
    test_customer.telegram_chat_id = "555"
    await db_session.commit()
    zone, spot, vehicle = await _seed_zone_spot_vehicle(db_session, test_customer)
    db_session.add(_make_booking(test_customer, vehicle, spot, start_in_minutes=5))
    db_session.add(_make_booking(test_customer, vehicle, spot, start_in_minutes=25))
    await db_session.commit()

    await worker._tick()

    assert fake_notification.send_booking_reminder.await_count == 2
