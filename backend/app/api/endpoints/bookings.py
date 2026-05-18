from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload
from typing import List
from uuid import UUID
from datetime import datetime, timezone

from app.db.database import get_db
from app.models.customer import Customer
from app.models.vehicle import Vehicle
from app.models.booking import Booking
from app.models.parking_spot import ParkingSpot
from app.models.parking_zone import ParkingZone
from app.models.payment import Payment
from app.models.tariff_plan import TariffPlan
from app.models.transaction import Transaction
from app.schemas.booking import (
    BookingCreate,
    BookingResponse,
    BookingStatusUpdate,
    BookingDetailResponse,
    SpotDetail,
    ZoneDetail,
    VehicleDetail
)
from app.core.dependencies import get_current_customer
from app.services.notification_service import notification_service
from decimal import Decimal

router = APIRouter()


@router.get("/", response_model=List[BookingDetailResponse])
async def get_my_bookings(
    current_customer: Customer = Depends(get_current_customer),
    status: str = None,
    db: AsyncSession = Depends(get_db)
):
    """Get all bookings for current customer with detailed information"""
    stmt = select(Booking).where(Booking.customer_id == current_customer.customer_id)

    if status:
        stmt = stmt.where(Booking.status == status)

    stmt = stmt.order_by(Booking.created_at.desc())

    result = await db.execute(stmt)
    bookings = result.scalars().all()

    # Manually build detailed response with related data
    detailed_bookings = []
    for booking in bookings:
        # Get spot
        spot_stmt = select(ParkingSpot).where(ParkingSpot.spot_id == booking.spot_id)
        spot_result = await db.execute(spot_stmt)
        spot = spot_result.scalar_one()

        # Get zone
        zone_stmt = select(ParkingZone).where(ParkingZone.zone_id == spot.zone_id)
        zone_result = await db.execute(zone_stmt)
        zone = zone_result.scalar_one()

        # Get vehicle
        vehicle_stmt = select(Vehicle).where(Vehicle.vehicle_id == booking.vehicle_id)
        vehicle_result = await db.execute(vehicle_stmt)
        vehicle = vehicle_result.scalar_one()

        # Build response
        detailed_booking = BookingDetailResponse(
            booking_id=booking.booking_id,
            customer_id=booking.customer_id,
            start_time=booking.start_time,
            end_time=booking.end_time,
            estimated_cost=booking.estimated_cost,
            status=booking.status,
            created_at=booking.created_at,
            updated_at=booking.updated_at,
            spot=SpotDetail(
                spot_id=spot.spot_id,
                spot_number=spot.spot_number,
                spot_type=spot.spot_type
            ),
            zone=ZoneDetail(
                zone_id=zone.zone_id,
                name=zone.name,
                address=zone.address
            ),
            vehicle=VehicleDetail(
                vehicle_id=vehicle.vehicle_id,
                license_plate=vehicle.license_plate,
                model=vehicle.model,
                color=vehicle.color
            )
        )
        detailed_bookings.append(detailed_booking)

    return detailed_bookings


@router.post("/", response_model=BookingResponse, status_code=status.HTTP_201_CREATED)
async def create_booking(
    booking_data: BookingCreate,
    current_customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db)
):
    """Create a new booking"""

    # Verify vehicle belongs to customer
    stmt = select(Vehicle).where(
        Vehicle.vehicle_id == booking_data.vehicle_id,
        Vehicle.customer_id == current_customer.customer_id
    )
    result = await db.execute(stmt)
    vehicle = result.scalar_one_or_none()

    if not vehicle:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vehicle not found"
        )

    # Verify parking spot exists and is available
    stmt = select(ParkingSpot).where(ParkingSpot.spot_id == booking_data.spot_id)
    result = await db.execute(stmt)
    spot = result.scalar_one_or_none()

    if not spot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Parking spot not found"
        )

    if not spot.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Parking spot is not active"
        )

    # Check if spot is already booked for the requested time period
    stmt = select(Booking).where(
        Booking.spot_id == booking_data.spot_id,
        Booking.status.in_(["pending", "confirmed"]),
        and_(
            Booking.start_time < booking_data.end_time,
            Booking.end_time > booking_data.start_time
        )
    )
    result = await db.execute(stmt)
    conflicting_booking = result.scalar_one_or_none()

    if conflicting_booking:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Parking spot is already booked for this time period"
        )

    # Validate booking times
    if booking_data.start_time >= booking_data.end_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="End time must be after start time"
        )

    now = datetime.now(timezone.utc)
    start = booking_data.start_time
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if start < now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Start time must be in the future"
        )

    # Get zone for cost calculation
    zone_stmt = select(ParkingZone).where(ParkingZone.zone_id == spot.zone_id)
    zone_result = await db.execute(zone_stmt)
    zone = zone_result.scalar_one()

    # Calculate estimated cost
    duration_hours = (booking_data.end_time - booking_data.start_time).total_seconds() / 3600
    estimated_cost = 0.0

    if zone.tariff_id:
        # Get tariff
        tariff_stmt = select(TariffPlan).where(TariffPlan.tariff_id == zone.tariff_id)
        tariff_result = await db.execute(tariff_stmt)
        tariff = tariff_result.scalar_one_or_none()

        if tariff:
            # Calculate cost
            if duration_hours >= 24 and tariff.price_per_day:
                # Use daily rate if available
                days = duration_hours / 24
                estimated_cost = float(tariff.price_per_day) * days
            else:
                # Use hourly rate
                estimated_cost = float(tariff.price_per_hour) * duration_hours
    else:
        # Default rate if no tariff
        estimated_cost = 50.0 * duration_hours

    estimated_cost = Decimal(str(round(estimated_cost, 2)))

    # Check if customer has sufficient balance
    if current_customer.balance < estimated_cost:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Недостаточно средств на балансе. Требуется: {estimated_cost} ₽, Доступно: {current_customer.balance} ₽. Пожалуйста, пополните баланс."
        )

    # Deduct from balance
    balance_before = current_customer.balance
    balance_after = balance_before - estimated_cost
    current_customer.balance = balance_after

    # Create booking with estimated cost and status 'pending' (money is deducted, but session not started yet)
    new_booking = Booking(
        customer_id=current_customer.customer_id,
        **booking_data.model_dump(),
        estimated_cost=estimated_cost,
        status="pending"  # Оплачено, но парковка еще не началась
    )

    db.add(new_booking)
    await db.flush()  # Get booking_id before creating payment

    # Create transaction record
    new_transaction = Transaction(
        customer_id=current_customer.customer_id,
        booking_id=new_booking.booking_id,
        amount=estimated_cost,
        type="booking_charge",
        description=f"Оплата бронирования: {zone.name}, место {spot.spot_number}",
        balance_before=balance_before,
        balance_after=balance_after
    )
    db.add(new_transaction)
    await db.flush()  # Flush to get transaction_id

    # Create payment record
    new_payment = Payment(
        customer_id=current_customer.customer_id,
        booking_id=new_booking.booking_id,
        amount=estimated_cost,
        payment_method="balance",
        status="completed",
        transaction_id=str(new_transaction.transaction_id) if new_transaction.transaction_id else None
    )
    db.add(new_payment)

    await db.commit()
    await db.refresh(new_booking)

    # Send booking confirmation notification
    await notification_service.send_booking_confirmation(
        customer_email=current_customer.email,
        customer_name=f"{current_customer.first_name} {current_customer.last_name}",
        booking_id=str(new_booking.booking_id),
        zone_name=zone.name,
        spot_number=spot.spot_number,
        start_time=new_booking.start_time,
        end_time=new_booking.end_time,
        telegram_chat_id=current_customer.telegram_chat_id,
    )

    return new_booking


@router.get("/{booking_id}", response_model=BookingResponse)
async def get_booking(
    booking_id: UUID,
    current_customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db)
):
    """Get a specific booking"""
    stmt = select(Booking).where(
        Booking.booking_id == booking_id,
        Booking.customer_id == current_customer.customer_id
    )
    result = await db.execute(stmt)
    booking = result.scalar_one_or_none()

    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found"
        )

    return booking


@router.patch("/{booking_id}/status", response_model=BookingResponse)
async def update_booking_status(
    booking_id: UUID,
    status_update: BookingStatusUpdate,
    current_customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db)
):
    """Update booking status"""
    stmt = select(Booking).where(
        Booking.booking_id == booking_id,
        Booking.customer_id == current_customer.customer_id
    )
    result = await db.execute(stmt)
    booking = result.scalar_one_or_none()

    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found"
        )

    # Validate status transition
    valid_statuses = ["pending", "confirmed", "cancelled", "completed"]
    if status_update.status not in valid_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
        )

    booking.status = status_update.status

    await db.commit()
    await db.refresh(booking)

    return booking


@router.delete("/{booking_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_booking(
    booking_id: UUID,
    current_customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db)
):
    """Cancel a booking and refund the payment"""
    stmt = select(Booking).where(
        Booking.booking_id == booking_id,
        Booking.customer_id == current_customer.customer_id
    )
    result = await db.execute(stmt)
    booking = result.scalar_one_or_none()

    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found"
        )

    if booking.status == "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot cancel completed booking"
        )

    if booking.status == "cancelled":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Booking is already cancelled"
        )

    # Return money to balance
    refund_amount = booking.estimated_cost
    balance_before = current_customer.balance
    balance_after = balance_before + refund_amount
    current_customer.balance = balance_after

    # Create refund transaction
    refund_transaction = Transaction(
        customer_id=current_customer.customer_id,
        booking_id=booking.booking_id,
        amount=refund_amount,
        type="refund",
        description=f"Возврат средств за отмененное бронирование",
        balance_before=balance_before,
        balance_after=balance_after
    )
    db.add(refund_transaction)

    # Update booking status
    booking.status = "cancelled"

    await db.commit()

    return None
