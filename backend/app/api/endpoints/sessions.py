from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from uuid import UUID
from datetime import datetime, timezone, timedelta


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: datetime) -> datetime:
    if dt is None:
        return dt
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)

from app.db.database import get_db
from app.models.customer import Customer
from app.models.vehicle import Vehicle
from app.models.parking_session import ParkingSession
from app.models.parking_spot import ParkingSpot
from app.models.booking import Booking
from app.models.parking_zone import ParkingZone
from app.models.tariff_plan import TariffPlan
from app.models.payment import Payment
from app.models.transaction import Transaction
from app.schemas.session import (
    ParkingSessionCreate,
    ParkingSessionResponse,
    ParkingSessionEnd,
    ParkingSessionHistoryResponse,
    ActiveSessionDetailResponse,
    SessionSpotDetail,
    SessionZoneDetail,
    SessionVehicleDetail,
    SessionPaymentDetail
)
from app.core.dependencies import get_current_customer
from app.services.notification_service import notification_service
from decimal import Decimal
import math

router = APIRouter()


async def calculate_session_cost(session: ParkingSession, db: AsyncSession) -> Decimal:
    """Calculate parking session cost based on duration and tariff"""

    if not session.exit_time:
        return Decimal("0.00")

    # Calculate duration in minutes
    duration = _as_utc(session.exit_time) - _as_utc(session.entry_time)
    duration_minutes = int(duration.total_seconds() / 60)

    # Get spot and zone to find tariff
    spot_stmt = select(ParkingSpot).where(ParkingSpot.spot_id == session.spot_id)
    spot_result = await db.execute(spot_stmt)
    spot = spot_result.scalar_one_or_none()

    if not spot:
        return Decimal("0.00")

    zone_stmt = select(ParkingZone).where(ParkingZone.zone_id == spot.zone_id)
    zone_result = await db.execute(zone_stmt)
    zone = zone_result.scalar_one_or_none()

    if not zone or not zone.tariff_id:
        return Decimal("0.00")

    tariff_stmt = select(TariffPlan).where(TariffPlan.tariff_id == zone.tariff_id)
    tariff_result = await db.execute(tariff_stmt)
    tariff = tariff_result.scalar_one_or_none()

    if not tariff:
        return Decimal("0.00")

    # Calculate cost
    # If parking is less than 1 day, use hourly rate
    if duration_minutes < 1440:  # 24 hours = 1440 minutes
        hours = math.ceil(duration_minutes / 60)  # Round up to next hour
        cost = tariff.price_per_hour * hours

        # Apply daily max if exists
        if tariff.price_per_day and cost > tariff.price_per_day:
            cost = tariff.price_per_day
    else:
        # For multi-day parking
        days = math.ceil(duration_minutes / 1440)
        cost = tariff.price_per_day * days if tariff.price_per_day else tariff.price_per_hour * 24 * days

    return Decimal(str(cost))


@router.get("/", response_model=List[ParkingSessionResponse])
async def get_my_sessions(
    current_customer: Customer = Depends(get_current_customer),
    status: str = None,
    db: AsyncSession = Depends(get_db)
):
    """Get all parking sessions for current customer's vehicles"""

    # Get customer's vehicle IDs
    vehicles_stmt = select(Vehicle.vehicle_id).where(Vehicle.customer_id == current_customer.customer_id)
    vehicles_result = await db.execute(vehicles_stmt)
    vehicle_ids = [row[0] for row in vehicles_result.all()]

    if not vehicle_ids:
        return []

    # Get sessions for customer's vehicles
    stmt = select(ParkingSession).where(ParkingSession.vehicle_id.in_(vehicle_ids))

    if status:
        stmt = stmt.where(ParkingSession.status == status)

    stmt = stmt.order_by(ParkingSession.entry_time.desc())

    result = await db.execute(stmt)
    sessions = result.scalars().all()
    return sessions


@router.post("/", response_model=ParkingSessionResponse, status_code=status.HTTP_201_CREATED)
async def start_parking_session(
    session_data: ParkingSessionCreate,
    current_customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db)
):
    """Start a new parking session"""

    # Verify vehicle belongs to customer
    stmt = select(Vehicle).where(
        Vehicle.vehicle_id == session_data.vehicle_id,
        Vehicle.customer_id == current_customer.customer_id
    )
    result = await db.execute(stmt)
    vehicle = result.scalar_one_or_none()

    if not vehicle:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vehicle not found"
        )

    # Verify parking spot exists
    stmt = select(ParkingSpot).where(ParkingSpot.spot_id == session_data.spot_id)
    result = await db.execute(stmt)
    spot = result.scalar_one_or_none()

    if not spot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Parking spot not found"
        )

    # Check if spot is already occupied
    if spot.is_occupied:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Parking spot is already occupied"
        )

    # If booking_id provided, verify it exists and belongs to this customer
    booking = None
    if session_data.booking_id:
        stmt = select(Booking).where(
            Booking.booking_id == session_data.booking_id,
            Booking.customer_id == current_customer.customer_id,
            Booking.vehicle_id == session_data.vehicle_id,
            Booking.spot_id == session_data.spot_id
        )
        result = await db.execute(stmt)
        booking = result.scalar_one_or_none()

        if not booking:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Бронирование не найдено или не соответствует параметрам сессии"
            )

        # Check if booking time is valid (current time should be within booking period)
        # Allow starting 5 minutes before scheduled time
        current_time = _utc_now()
        booking_start = _as_utc(booking.start_time)
        booking_end = _as_utc(booking.end_time)
        booking_start_with_buffer = booking_start - timedelta(minutes=5)

        if current_time < booking_start_with_buffer:
            minutes_until_start = int((booking_start - current_time).total_seconds() / 60)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Слишком рано! Можно начать парковку за 5 минут до времени бронирования. Осталось ждать: {minutes_until_start} мин"
            )

        if current_time > booking_end:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Время бронирования уже истекло"
            )

        # Check booking status - should be 'pending' (payment was made, waiting for session start)
        if booking.status == "cancelled":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Нельзя начать сессию для отмененного бронирования"
            )

        if booking.status == "completed":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Это бронирование уже было использовано"
            )

        # Change booking status to 'confirmed' when session starts
        if booking.status == "pending":
            booking.status = "confirmed"

    # Create parking session
    session_dict = session_data.model_dump()
    # Auto-set entry_time to current time if not provided
    if not session_dict.get('entry_time'):
        session_dict['entry_time'] = _utc_now()

    new_session = ParkingSession(
        **session_dict,
        status="active"
    )

    # Mark spot as occupied
    spot.is_occupied = True

    # Update zone's available spots
    stmt = select(ParkingZone).where(ParkingZone.zone_id == spot.zone_id)
    result = await db.execute(stmt)
    zone = result.scalar_one_or_none()
    if zone:
        zone.available_spots = max(0, zone.available_spots - 1)

    db.add(new_session)
    await db.commit()
    await db.refresh(new_session)

    # Send session started notification
    await notification_service.send_session_started(
        customer_email=current_customer.email,
        customer_name=f"{current_customer.first_name} {current_customer.last_name}",
        session_id=str(new_session.session_id),
        zone_name=zone.name if zone else "Unknown",
        spot_number=spot.spot_number,
        vehicle_plate=vehicle.license_plate,
        entry_time=new_session.entry_time,
        telegram_chat_id=current_customer.telegram_chat_id,
    )

    return new_session


@router.get("/active", response_model=List[ActiveSessionDetailResponse])
async def get_active_sessions(
    current_customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db)
):
    """Get all active parking sessions for current customer with details"""

    # Get customer's vehicle IDs
    vehicles_stmt = select(Vehicle.vehicle_id).where(Vehicle.customer_id == current_customer.customer_id)
    vehicles_result = await db.execute(vehicles_stmt)
    vehicle_ids = [row[0] for row in vehicles_result.all()]

    if not vehicle_ids:
        return []

    # Get active sessions
    stmt = select(ParkingSession).where(
        ParkingSession.vehicle_id.in_(vehicle_ids),
        ParkingSession.status == "active"
    )

    result = await db.execute(stmt)
    sessions = result.scalars().all()

    # Build detailed response
    detailed_sessions = []
    for session in sessions:
        # Get spot
        spot_stmt = select(ParkingSpot).where(ParkingSpot.spot_id == session.spot_id)
        spot_result = await db.execute(spot_stmt)
        spot = spot_result.scalar_one_or_none()

        if not spot:
            continue

        # Get zone
        zone_stmt = select(ParkingZone).where(ParkingZone.zone_id == spot.zone_id)
        zone_result = await db.execute(zone_stmt)
        zone = zone_result.scalar_one_or_none()

        if not zone:
            continue

        # Get vehicle
        vehicle_stmt = select(Vehicle).where(Vehicle.vehicle_id == session.vehicle_id)
        vehicle_result = await db.execute(vehicle_stmt)
        vehicle = vehicle_result.scalar_one_or_none()

        if not vehicle:
            continue

        # Build detailed session
        detailed_session = ActiveSessionDetailResponse(
            session_id=session.session_id,
            entry_time=session.entry_time,
            status=session.status,
            spot=SessionSpotDetail(
                spot_id=spot.spot_id,
                spot_number=spot.spot_number,
                spot_type=spot.spot_type
            ),
            zone=SessionZoneDetail(
                zone_id=zone.zone_id,
                name=zone.name,
                address=zone.address
            ),
            vehicle=SessionVehicleDetail(
                vehicle_id=vehicle.vehicle_id,
                license_plate=vehicle.license_plate,
                model=vehicle.model,
                color=vehicle.color
            )
        )

        detailed_sessions.append(detailed_session)

    return detailed_sessions


@router.get("/{session_id}", response_model=ParkingSessionResponse)
async def get_session(
    session_id: UUID,
    current_customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db)
):
    """Get a specific parking session"""

    # Get customer's vehicle IDs
    vehicles_stmt = select(Vehicle.vehicle_id).where(Vehicle.customer_id == current_customer.customer_id)
    vehicles_result = await db.execute(vehicles_stmt)
    vehicle_ids = [row[0] for row in vehicles_result.all()]

    if not vehicle_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    stmt = select(ParkingSession).where(
        ParkingSession.session_id == session_id,
        ParkingSession.vehicle_id.in_(vehicle_ids)
    )
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    return session


@router.patch("/{session_id}/end", response_model=ParkingSessionResponse)
async def end_parking_session(
    session_id: UUID,
    session_end: ParkingSessionEnd,
    current_customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db)
):
    """End a parking session"""

    # Get customer's vehicle IDs
    vehicles_stmt = select(Vehicle.vehicle_id).where(Vehicle.customer_id == current_customer.customer_id)
    vehicles_result = await db.execute(vehicles_stmt)
    vehicle_ids = [row[0] for row in vehicles_result.all()]

    if not vehicle_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    stmt = select(ParkingSession).where(
        ParkingSession.session_id == session_id,
        ParkingSession.vehicle_id.in_(vehicle_ids)
    )
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    if session.status != "active":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Session is not active"
        )

    # Ensure exit_time is timezone-aware
    exit_time = session_end.exit_time
    if exit_time.tzinfo is None:
        exit_time = exit_time.replace(tzinfo=timezone.utc)

    # Validate exit time
    if exit_time < _as_utc(session.entry_time):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Exit time must be after entry time"
        )

    # Update session
    session.exit_time = exit_time
    session.status = "completed"

    # Calculate duration in minutes
    duration = _as_utc(session.exit_time) - _as_utc(session.entry_time)
    session.duration_minutes = int(duration.total_seconds() / 60)

    # Calculate cost
    session.total_cost = await calculate_session_cost(session, db)

    # Mark spot as available
    stmt = select(ParkingSpot).where(ParkingSpot.spot_id == session.spot_id)
    result = await db.execute(stmt)
    spot = result.scalar_one_or_none()

    if spot:
        spot.is_occupied = False

        # Update zone's available spots
        stmt = select(ParkingZone).where(ParkingZone.zone_id == spot.zone_id)
        result = await db.execute(stmt)
        zone = result.scalar_one_or_none()
        if zone:
            zone.available_spots = min(zone.total_spots, zone.available_spots + 1)

    # Handle refund or penalty if session was from a booking
    if session.booking_id:
        # Get the booking
        booking_stmt = select(Booking).where(Booking.booking_id == session.booking_id)
        booking_result = await db.execute(booking_stmt)
        booking = booking_result.scalar_one_or_none()

        if booking:
            estimated_cost = booking.estimated_cost
            actual_cost = session.total_cost

            # Calculate difference
            difference = estimated_cost - actual_cost

            if difference > 0:
                # Refund: actual cost was less than estimated
                balance_before = current_customer.balance
                balance_after = balance_before + difference
                current_customer.balance = balance_after

                # Create refund transaction
                refund_transaction = Transaction(
                    customer_id=current_customer.customer_id,
                    booking_id=booking.booking_id,
                    session_id=session.session_id,
                    amount=difference,
                    type="refund",
                    description=f"Возврат средств: парковка завершена раньше",
                    balance_before=balance_before,
                    balance_after=balance_after
                )
                db.add(refund_transaction)

            elif difference < 0:
                # Penalty: actual cost was more than estimated (stayed longer)
                penalty = abs(difference)

                # Check if customer has sufficient balance
                if current_customer.balance < penalty:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Недостаточно средств для оплаты штрафа. Требуется: {penalty} ₽, Доступно: {current_customer.balance} ₽"
                    )

                balance_before = current_customer.balance
                balance_after = balance_before - penalty
                current_customer.balance = balance_after

                # Create penalty transaction
                penalty_transaction = Transaction(
                    customer_id=current_customer.customer_id,
                    booking_id=booking.booking_id,
                    session_id=session.session_id,
                    amount=penalty,
                    type="penalty",
                    description=f"Штраф: превышено время бронирования",
                    balance_before=balance_before,
                    balance_after=balance_after
                )
                db.add(penalty_transaction)

            # Mark booking as completed
            booking.status = "completed"

            # Update existing payment to link it with session
            payment_stmt = select(Payment).where(Payment.booking_id == booking.booking_id)
            payment_result = await db.execute(payment_stmt)
            payment = payment_result.scalar_one_or_none()
            if payment:
                payment.session_id = session.session_id
                payment.amount = actual_cost  # Update to actual cost
    else:
        # Session without booking - create payment and deduct from balance
        # Check if customer has sufficient balance
        if current_customer.balance < session.total_cost:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Недостаточно средств на балансе. Требуется: {session.total_cost} ₽, Доступно: {current_customer.balance} ₽"
            )

        # Deduct from balance
        balance_before = current_customer.balance
        balance_after = balance_before - session.total_cost
        current_customer.balance = balance_after

        # Create transaction record
        new_transaction = Transaction(
            customer_id=current_customer.customer_id,
            session_id=session.session_id,
            amount=session.total_cost,
            type="parking_charge",
            description=f"Оплата парковки без бронирования",
            balance_before=balance_before,
            balance_after=balance_after
        )
        db.add(new_transaction)
        await db.flush()  # Flush to get transaction_id

        # Create payment record
        new_payment = Payment(
            customer_id=current_customer.customer_id,
            session_id=session.session_id,
            amount=session.total_cost,
            payment_method="balance",
            status="completed",
            transaction_id=str(new_transaction.transaction_id) if new_transaction.transaction_id else None
        )
        db.add(new_payment)

    await db.commit()
    await db.refresh(session)

    # Get vehicle for notification
    vehicle_stmt = select(Vehicle).where(Vehicle.vehicle_id == session.vehicle_id)
    vehicle_result = await db.execute(vehicle_stmt)
    vehicle = vehicle_result.scalar_one_or_none()

    # Send session ended notification
    if vehicle and spot and zone:
        await notification_service.send_session_ended(
            customer_email=current_customer.email,
            customer_name=f"{current_customer.first_name} {current_customer.last_name}",
            session_id=str(session.session_id),
            zone_name=zone.name,
            spot_number=spot.spot_number,
            vehicle_plate=vehicle.license_plate,
            entry_time=session.entry_time,
            exit_time=session.exit_time,
            duration_minutes=session.duration_minutes,
            total_cost=float(session.total_cost),
            telegram_chat_id=current_customer.telegram_chat_id,
        )

    return session


@router.get("/{session_id}/calculate-cost")
async def calculate_current_cost(
    session_id: UUID,
    current_customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db)
):
    """Calculate current cost for an active session"""

    # Get customer's vehicle IDs
    vehicles_stmt = select(Vehicle.vehicle_id).where(Vehicle.customer_id == current_customer.customer_id)
    vehicles_result = await db.execute(vehicles_stmt)
    vehicle_ids = [row[0] for row in vehicles_result.all()]

    if not vehicle_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    stmt = select(ParkingSession).where(
        ParkingSession.session_id == session_id,
        ParkingSession.vehicle_id.in_(vehicle_ids)
    )
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    # Create temporary session with current time as exit to calculate cost
    temp_session = ParkingSession(
        session_id=session.session_id,
        vehicle_id=session.vehicle_id,
        spot_id=session.spot_id,
        entry_time=session.entry_time,
        exit_time=_utc_now(),
        booking_id=session.booking_id,
        status=session.status
    )

    cost = await calculate_session_cost(temp_session, db)
    duration = _utc_now() - _as_utc(session.entry_time)
    duration_minutes = int(duration.total_seconds() / 60)

    return {
        "session_id": session_id,
        "entry_time": session.entry_time,
        "current_time": _utc_now(),
        "duration_minutes": duration_minutes,
        "estimated_cost": float(cost),
        "status": session.status
    }


@router.get("/history/all", response_model=List[ParkingSessionHistoryResponse])
async def get_session_history(
    current_customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db)
):
    """Get detailed history of all parking sessions for current customer"""

    # Get customer's vehicle IDs
    vehicles_stmt = select(Vehicle.vehicle_id).where(Vehicle.customer_id == current_customer.customer_id)
    vehicles_result = await db.execute(vehicles_stmt)
    vehicle_ids = [row[0] for row in vehicles_result.all()]

    if not vehicle_ids:
        return []

    # Get all completed sessions
    stmt = select(ParkingSession).where(
        ParkingSession.vehicle_id.in_(vehicle_ids),
        ParkingSession.status == "completed"
    ).order_by(ParkingSession.entry_time.desc())

    result = await db.execute(stmt)
    sessions = result.scalars().all()

    # Build detailed response
    detailed_sessions = []
    for session in sessions:
        # Get spot
        spot_stmt = select(ParkingSpot).where(ParkingSpot.spot_id == session.spot_id)
        spot_result = await db.execute(spot_stmt)
        spot = spot_result.scalar_one_or_none()

        if not spot:
            continue

        # Get zone
        zone_stmt = select(ParkingZone).where(ParkingZone.zone_id == spot.zone_id)
        zone_result = await db.execute(zone_stmt)
        zone = zone_result.scalar_one_or_none()

        if not zone:
            continue

        # Get vehicle
        vehicle_stmt = select(Vehicle).where(Vehicle.vehicle_id == session.vehicle_id)
        vehicle_result = await db.execute(vehicle_stmt)
        vehicle = vehicle_result.scalar_one_or_none()

        if not vehicle:
            continue

        # Get payment (optional)
        payment_stmt = select(Payment).where(Payment.session_id == session.session_id)
        payment_result = await db.execute(payment_stmt)
        payment = payment_result.scalar_one_or_none()

        # Build detailed session
        detailed_session = ParkingSessionHistoryResponse(
            session_id=session.session_id,
            entry_time=session.entry_time,
            exit_time=session.exit_time,
            duration_minutes=session.duration_minutes,
            total_cost=session.total_cost,
            status=session.status,
            created_at=session.created_at,
            spot=SessionSpotDetail(
                spot_id=spot.spot_id,
                spot_number=spot.spot_number,
                spot_type=spot.spot_type
            ),
            zone=SessionZoneDetail(
                zone_id=zone.zone_id,
                name=zone.name,
                address=zone.address
            ),
            vehicle=SessionVehicleDetail(
                vehicle_id=vehicle.vehicle_id,
                license_plate=vehicle.license_plate,
                model=vehicle.model,
                color=vehicle.color
            ),
            payment=SessionPaymentDetail(
                payment_id=payment.payment_id,
                amount=payment.amount,
                status=payment.status,
                payment_method=payment.payment_method,
                created_at=payment.created_at
            ) if payment else None
        )

        detailed_sessions.append(detailed_session)

    return detailed_sessions


@router.get("/statistics/monthly")
async def get_monthly_statistics(
    current_customer: Customer = Depends(get_current_customer),
    months: int = 6,
    db: AsyncSession = Depends(get_db)
):
    """Get monthly parking statistics for charts"""
    from datetime import timedelta
    from collections import defaultdict

    # Get customer's vehicle IDs
    vehicles_stmt = select(Vehicle.vehicle_id).where(Vehicle.customer_id == current_customer.customer_id)
    vehicles_result = await db.execute(vehicles_stmt)
    vehicle_ids = [row[0] for row in vehicles_result.all()]

    if not vehicle_ids:
        return {"months": [], "sessions_count": [], "total_cost": [], "total_hours": []}

    # Calculate date range
    end_date = _utc_now().replace(tzinfo=None)
    start_date = end_date - timedelta(days=months * 30)

    # Get all completed sessions in range
    stmt = select(ParkingSession).where(
        ParkingSession.vehicle_id.in_(vehicle_ids),
        ParkingSession.status == "completed",
        ParkingSession.entry_time >= start_date
    ).order_by(ParkingSession.entry_time)

    result = await db.execute(stmt)
    sessions = result.scalars().all()

    # Group by month
    monthly_data = defaultdict(lambda: {"count": 0, "cost": 0, "hours": 0})

    for session in sessions:
        month_key = session.entry_time.strftime("%Y-%m")
        monthly_data[month_key]["count"] += 1
        monthly_data[month_key]["cost"] += float(session.total_cost or 0)
        monthly_data[month_key]["hours"] += (session.duration_minutes or 0) / 60

    # Format response
    sorted_months = sorted(monthly_data.keys())

    return {
        "months": sorted_months,
        "sessions_count": [monthly_data[m]["count"] for m in sorted_months],
        "total_cost": [round(monthly_data[m]["cost"], 2) for m in sorted_months],
        "total_hours": [round(monthly_data[m]["hours"], 1) for m in sorted_months]
    }
