from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from uuid import UUID
from decimal import Decimal

from app.db.database import get_db
from app.models.customer import Customer
from app.models.vehicle import Vehicle
from app.models.payment import Payment
from app.models.parking_session import ParkingSession
from app.models.parking_spot import ParkingSpot
from app.models.parking_zone import ParkingZone
from app.models.tariff_plan import TariffPlan
from app.models.booking import Booking
from app.schemas.payment import (
    PaymentCreate,
    PaymentResponse,
    PaymentUpdate,
    PaymentDetailResponse,
    SpotDetail,
    ZoneDetail,
    BookingDetail
)
from app.core.dependencies import get_current_customer
from app.services.notification_service import notification_service
from app.services.mock_payment_service import mock_payment_service

router = APIRouter()


def calculate_parking_cost(session: ParkingSession, tariff: TariffPlan) -> Decimal:
    """Calculate parking cost based on session duration and tariff"""
    if not session.exit_time:
        raise ValueError("Session must have exit time to calculate cost")

    duration = session.exit_time - session.entry_time
    hours = Decimal(duration.total_seconds()) / Decimal(3600)

    # Round up to nearest hour
    hours = hours.quantize(Decimal('1'), rounding='ROUND_UP')

    # Calculate cost
    if tariff.price_per_day and hours >= 24:
        # Use daily rate if available and duration is 24+ hours
        days = (hours / Decimal(24)).quantize(Decimal('1'), rounding='ROUND_UP')
        cost = days * tariff.price_per_day
    else:
        # Use hourly rate
        cost = hours * tariff.price_per_hour

    return cost.quantize(Decimal('0.01'))


@router.get("/", response_model=List[PaymentDetailResponse])
async def get_my_payments(
    current_customer: Customer = Depends(get_current_customer),
    status: str = None,
    db: AsyncSession = Depends(get_db)
):
    """Get all payments for current customer with detailed information"""
    stmt = select(Payment).where(Payment.customer_id == current_customer.customer_id)

    if status:
        stmt = stmt.where(Payment.status == status)

    stmt = stmt.order_by(Payment.created_at.desc())

    result = await db.execute(stmt)
    payments = result.scalars().all()

    # Build detailed response
    detailed_payments = []
    for payment in payments:
        booking_detail = None
        spot_detail = None
        zone_detail = None

        # If payment is for a booking, get booking details
        if payment.booking_id:
            # Get booking
            booking_stmt = select(Booking).where(Booking.booking_id == payment.booking_id)
            booking_result = await db.execute(booking_stmt)
            booking = booking_result.scalar_one_or_none()

            if booking:
                booking_detail = BookingDetail(
                    booking_id=booking.booking_id,
                    start_time=booking.start_time,
                    end_time=booking.end_time,
                    status=booking.status
                )

                # Get spot
                spot_stmt = select(ParkingSpot).where(ParkingSpot.spot_id == booking.spot_id)
                spot_result = await db.execute(spot_stmt)
                spot = spot_result.scalar_one_or_none()

                if spot:
                    spot_detail = SpotDetail(
                        spot_id=spot.spot_id,
                        spot_number=spot.spot_number,
                        spot_type=spot.spot_type
                    )

                    # Get zone
                    zone_stmt = select(ParkingZone).where(ParkingZone.zone_id == spot.zone_id)
                    zone_result = await db.execute(zone_stmt)
                    zone = zone_result.scalar_one_or_none()

                    if zone:
                        zone_detail = ZoneDetail(
                            zone_id=zone.zone_id,
                            name=zone.name,
                            address=zone.address
                        )

        detailed_payment = PaymentDetailResponse(
            payment_id=payment.payment_id,
            session_id=payment.session_id,
            booking_id=payment.booking_id,
            customer_id=payment.customer_id,
            amount=payment.amount,
            payment_method=payment.payment_method,
            status=payment.status,
            transaction_id=payment.transaction_id,
            created_at=payment.created_at,
            updated_at=payment.updated_at,
            booking=booking_detail,
            spot=spot_detail,
            zone=zone_detail
        )
        detailed_payments.append(detailed_payment)

    return detailed_payments


@router.post("/", response_model=PaymentResponse, status_code=status.HTTP_201_CREATED)
async def create_payment(
    payment_data: PaymentCreate,
    current_customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db)
):
    """Create a new payment for a parking session"""

    # Get parking session
    stmt = select(ParkingSession).where(ParkingSession.session_id == payment_data.session_id)
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Parking session not found"
        )

    # Verify session belongs to customer's vehicle
    stmt = select(Vehicle).where(
        Vehicle.vehicle_id == session.vehicle_id,
        Vehicle.customer_id == current_customer.customer_id
    )
    result = await db.execute(stmt)
    vehicle = result.scalar_one_or_none()

    if not vehicle:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Session does not belong to your vehicle"
        )

    # Check if session is completed
    if session.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only create payment for completed sessions"
        )

    # Check if payment already exists for this session
    stmt = select(Payment).where(Payment.session_id == payment_data.session_id)
    result = await db.execute(stmt)
    existing_payment = result.scalar_one_or_none()

    if existing_payment:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payment already exists for this session"
        )

    # Get parking spot and zone to determine tariff
    stmt = select(ParkingSpot).where(ParkingSpot.spot_id == session.spot_id)
    result = await db.execute(stmt)
    spot = result.scalar_one_or_none()

    if not spot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Parking spot not found"
        )

    stmt = select(ParkingZone).where(ParkingZone.zone_id == spot.zone_id)
    result = await db.execute(stmt)
    zone = result.scalar_one_or_none()

    if not zone or not zone.tariff_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Parking zone does not have a tariff plan"
        )

    # Get tariff plan
    stmt = select(TariffPlan).where(TariffPlan.tariff_id == zone.tariff_id)
    result = await db.execute(stmt)
    tariff = result.scalar_one_or_none()

    if not tariff:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tariff plan not found"
        )

    # Calculate cost
    try:
        calculated_amount = calculate_parking_cost(session, tariff)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

    # Verify amount matches calculated amount (allow small difference for rounding)
    if abs(payment_data.amount - calculated_amount) > Decimal('0.02'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Payment amount ({payment_data.amount}) does not match calculated cost ({calculated_amount})"
        )

    # Create payment
    new_payment = Payment(
        session_id=payment_data.session_id,
        customer_id=current_customer.customer_id,
        amount=calculated_amount,
        payment_method=payment_data.payment_method,
        status="pending"
    )

    db.add(new_payment)
    await db.commit()
    await db.refresh(new_payment)

    return new_payment


@router.get("/{payment_id}", response_model=PaymentResponse)
async def get_payment(
    payment_id: UUID,
    current_customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db)
):
    """Get a specific payment"""
    stmt = select(Payment).where(
        Payment.payment_id == payment_id,
        Payment.customer_id == current_customer.customer_id
    )
    result = await db.execute(stmt)
    payment = result.scalar_one_or_none()

    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment not found"
        )

    return payment


@router.patch("/{payment_id}", response_model=PaymentResponse)
async def update_payment_status(
    payment_id: UUID,
    payment_update: PaymentUpdate,
    current_customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db)
):
    """Update payment status (simulate payment processing)"""
    stmt = select(Payment).where(
        Payment.payment_id == payment_id,
        Payment.customer_id == current_customer.customer_id
    )
    result = await db.execute(stmt)
    payment = result.scalar_one_or_none()

    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment not found"
        )

    # Validate status transition
    valid_statuses = ["pending", "completed", "failed", "refunded"]
    if payment_update.status not in valid_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
        )

    # If status is being set to completed, process through mock payment service
    if payment_update.status == "completed" and payment.status != "completed":
        # Process payment through mock service
        payment_result = await mock_payment_service.process_payment(
            amount=float(payment.amount),
            payment_method=payment.payment_method,
            customer_email=current_customer.email,
            description=f"Parking payment {str(payment.payment_id)[:8]}"
        )

        if payment_result["status"] == "completed":
            payment.status = "completed"
            payment.transaction_id = payment_result["transaction_id"]
        else:
            payment.status = "failed"
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=payment_result.get("message", "Payment processing failed")
            )
    else:
        payment.status = payment_update.status
        if payment_update.transaction_id:
            payment.transaction_id = payment_update.transaction_id

    await db.commit()
    await db.refresh(payment)

    # If payment is for a booking, update booking status to confirmed
    if payment.status == "completed" and payment.booking_id:
        stmt = select(Booking).where(Booking.booking_id == payment.booking_id)
        result = await db.execute(stmt)
        booking = result.scalar_one_or_none()

        if booking and booking.status == "pending":
            booking.status = "confirmed"
            await db.commit()

    # Send payment confirmation if payment completed
    if payment.status == "completed":
        await notification_service.send_payment_confirmation(
            customer_email=current_customer.email,
            customer_name=f"{current_customer.first_name} {current_customer.last_name}",
            payment_id=str(payment.payment_id),
            amount=float(payment.amount),
            payment_method=payment.payment_method,
            transaction_id=payment.transaction_id,
            telegram_chat_id=current_customer.telegram_chat_id,
        )

    return payment


@router.get("/session/{session_id}/calculate", response_model=dict)
async def calculate_session_cost(
    session_id: UUID,
    current_customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db)
):
    """Calculate cost for a parking session"""

    # Get parking session
    stmt = select(ParkingSession).where(ParkingSession.session_id == session_id)
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Parking session not found"
        )

    # Verify session belongs to customer's vehicle
    stmt = select(Vehicle).where(
        Vehicle.vehicle_id == session.vehicle_id,
        Vehicle.customer_id == current_customer.customer_id
    )
    result = await db.execute(stmt)
    vehicle = result.scalar_one_or_none()

    if not vehicle:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Session does not belong to your vehicle"
        )

    if not session.exit_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Session must be completed to calculate cost"
        )

    # Get parking spot and zone to determine tariff
    stmt = select(ParkingSpot).where(ParkingSpot.spot_id == session.spot_id)
    result = await db.execute(stmt)
    spot = result.scalar_one_or_none()

    if not spot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Parking spot not found"
        )

    stmt = select(ParkingZone).where(ParkingZone.zone_id == spot.zone_id)
    result = await db.execute(stmt)
    zone = result.scalar_one_or_none()

    if not zone or not zone.tariff_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Parking zone does not have a tariff plan"
        )

    # Get tariff plan
    stmt = select(TariffPlan).where(TariffPlan.tariff_id == zone.tariff_id)
    result = await db.execute(stmt)
    tariff = result.scalar_one_or_none()

    if not tariff:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tariff plan not found"
        )

    # Calculate cost
    cost = calculate_parking_cost(session, tariff)
    duration = session.exit_time - session.entry_time

    return {
        "session_id": session_id,
        "amount": cost,
        "currency": "RUB",
        "duration_hours": float(duration.total_seconds() / 3600),
        "tariff_name": tariff.name,
        "tariff_price_per_hour": tariff.price_per_hour
    }
