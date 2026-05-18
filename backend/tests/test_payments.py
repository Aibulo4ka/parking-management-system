"""
Тесты для эндпоинтов платежей
"""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta
from decimal import Decimal

from app.models.vehicle import Vehicle
from app.models.parking_zone import ParkingZone
from app.models.parking_spot import ParkingSpot
from app.models.parking_session import ParkingSession
from app.models.tariff_plan import TariffPlan
from app.models.payment import Payment


@pytest.fixture
async def test_vehicle_for_session(db_session: AsyncSession, test_customer):
    """Отдельный vehicle, не пересекается с test_completed_session."""
    vehicle = Vehicle(
        customer_id=test_customer.customer_id,
        license_plate="X777ZZ777",
        brand="Test",
        model="Active",
        color="Red",
        vehicle_type="sedan",
    )
    db_session.add(vehicle)
    await db_session.commit()
    await db_session.refresh(vehicle)
    return vehicle


@pytest.fixture
async def test_spot_with_zone(db_session: AsyncSession, test_tariff_for_payment):
    """Отдельная зона+спот с тарифом для активной сессии."""
    zone = ParkingZone(
        name="Зона активных сессий",
        address="ул. Активная, 1",
        total_spots=5,
        available_spots=5,
        tariff_id=test_tariff_for_payment.tariff_id,
        is_active=True,
    )
    db_session.add(zone)
    await db_session.flush()
    spot = ParkingSpot(
        zone_id=zone.zone_id,
        spot_number="ACTIVE-1",
        spot_type="standard",
        is_occupied=False,
        is_active=True,
    )
    db_session.add(spot)
    await db_session.commit()
    await db_session.refresh(spot)
    return spot


@pytest.fixture
async def test_tariff_for_payment(db_session: AsyncSession):
    """Создание тестового тарифного плана для платежей"""
    tariff = TariffPlan(
        name="Тестовый тариф",
        description="Тариф для тестирования платежей",
        price_per_hour=Decimal("150.00"),
        price_per_day=Decimal("1500.00"),
        is_active=True
    )
    db_session.add(tariff)
    await db_session.commit()
    await db_session.refresh(tariff)
    return tariff


@pytest.fixture
async def test_completed_session(
    db_session: AsyncSession,
    test_customer,
    test_tariff_for_payment
):
    """Создание завершенной парковочной сессии для тестирования платежей"""
    # Создаем зону с тарифом
    zone = ParkingZone(
        name="Зона для платежей",
        address="ул. Платежная, 1",
        total_spots=10,
        available_spots=10,
        tariff_id=test_tariff_for_payment.tariff_id,
        is_active=True
    )
    db_session.add(zone)
    await db_session.flush()

    # Создаем место
    spot = ParkingSpot(
        zone_id=zone.zone_id,
        spot_number="P-001",
        spot_type="standard",
        is_occupied=False,
        is_active=True
    )
    db_session.add(spot)
    await db_session.flush()

    # Создаем автомобиль
    vehicle = Vehicle(
        customer_id=test_customer.customer_id,
        license_plate="П777АР777",
        brand="Mercedes",
        model="E-Class",
        color="Серебристый",
        vehicle_type="sedan"
    )
    db_session.add(vehicle)
    await db_session.flush()

    # Создаем завершенную сессию (ровно 2 часа)
    now = datetime.utcnow()
    entry_time = now - timedelta(hours=3)
    exit_time = now - timedelta(hours=1)

    session = ParkingSession(
        vehicle_id=vehicle.vehicle_id,
        spot_id=spot.spot_id,
        entry_time=entry_time,
        exit_time=exit_time,
        duration_minutes=120,
        total_cost=Decimal("300.00"),
        status="completed"
    )
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    return session, vehicle, spot, zone


@pytest.mark.asyncio
async def test_create_payment_success(
    client: AsyncClient,
    auth_headers,
    test_completed_session
):
    """Тест успешного создания платежа"""
    session, vehicle, spot, zone = test_completed_session

    response = await client.post(
        "/api/payments/",
        headers=auth_headers,
        json={
            "session_id": str(session.session_id),
            "amount": float(session.total_cost),
            "payment_method": "card"
        }
    )

    assert response.status_code == 201, response.json()
    data = response.json()
    assert data["status"] == "pending"
    assert Decimal(str(data["amount"])) == session.total_cost
    assert data["payment_method"] == "card"


@pytest.mark.asyncio
async def test_create_payment_invalid_session(
    client: AsyncClient,
    auth_headers
):
    """Тест создания платежа для несуществующей сессии"""
    response = await client.post(
        "/api/payments/",
        headers=auth_headers,
        json={
            "session_id": "00000000-0000-0000-0000-000000000000",
            "amount": 100.00,
            "payment_method": "card"
        }
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_payment_active_session(
    client: AsyncClient,
    auth_headers,
    test_vehicle_for_session,
    test_spot_with_zone,
    db_session: AsyncSession
):
    """Тест создания платежа для незавершенной сессии"""
    # Создаем активную сессию
    session = ParkingSession(
        vehicle_id=test_vehicle_for_session.vehicle_id,
        spot_id=test_spot_with_zone.spot_id,
        entry_time=datetime.utcnow() - timedelta(hours=1),
        status="active"
    )
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    response = await client.post(
        "/api/payments/",
        headers=auth_headers,
        json={
            "session_id": str(session.session_id),
            "amount": 100.00,
            "payment_method": "card"
        }
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_create_duplicate_payment(
    client: AsyncClient,
    auth_headers,
    test_completed_session,
    test_customer,
    db_session: AsyncSession
):
    """Тест создания дублирующего платежа"""
    session, vehicle, spot, zone = test_completed_session

    # Создаем первый платеж
    payment = Payment(
        session_id=session.session_id,
        customer_id=test_customer.customer_id,
        amount=session.total_cost,
        payment_method="card",
        status="pending"
    )
    db_session.add(payment)
    await db_session.commit()

    # Пытаемся создать второй платеж для той же сессии
    response = await client.post(
        "/api/payments/",
        headers=auth_headers,
        json={
            "session_id": str(session.session_id),
            "amount": float(session.total_cost),
            "payment_method": "card"
        }
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_create_payment_wrong_amount(
    client: AsyncClient,
    auth_headers,
    test_completed_session
):
    """Тест создания платежа с неправильной суммой"""
    session, vehicle, spot, zone = test_completed_session

    response = await client.post(
        "/api/payments/",
        headers=auth_headers,
        json={
            "session_id": str(session.session_id),
            "amount": 50.00,  # Неправильная сумма
            "payment_method": "card"
        }
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_get_my_payments(
    client: AsyncClient,
    auth_headers,
    test_completed_session,
    test_customer,
    db_session: AsyncSession
):
    """Тест получения всех платежей пользователя"""
    session, vehicle, spot, zone = test_completed_session

    # Создаем несколько платежей
    payment1 = Payment(
        session_id=session.session_id,
        customer_id=test_customer.customer_id,
        amount=Decimal("300.00"),
        payment_method="card",
        status="completed"
    )

    db_session.add(payment1)
    await db_session.commit()

    response = await client.get("/api/payments/", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1


@pytest.mark.asyncio
async def test_get_my_payments_filter_by_status(
    client: AsyncClient,
    auth_headers,
    test_completed_session,
    test_customer,
    db_session: AsyncSession
):
    """Тест фильтрации платежей по статусу"""
    session, vehicle, spot, zone = test_completed_session

    # Создаем платежи с разными статусами
    payment1 = Payment(
        session_id=session.session_id,
        customer_id=test_customer.customer_id,
        amount=Decimal("300.00"),
        payment_method="card",
        status="pending"
    )
    db_session.add(payment1)
    await db_session.commit()

    response = await client.get("/api/payments/?status=pending", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert all(p["status"] == "pending" for p in data)


@pytest.mark.asyncio
async def test_get_payment_by_id(
    client: AsyncClient,
    auth_headers,
    test_completed_session,
    test_customer,
    db_session: AsyncSession
):
    """Тест получения конкретного платежа"""
    session, vehicle, spot, zone = test_completed_session

    payment = Payment(
        session_id=session.session_id,
        customer_id=test_customer.customer_id,
        amount=Decimal("300.00"),
        payment_method="card",
        status="pending"
    )
    db_session.add(payment)
    await db_session.commit()
    await db_session.refresh(payment)

    response = await client.get(
        f"/api/payments/{payment.payment_id}",
        headers=auth_headers
    )

    assert response.status_code == 200
    data = response.json()
    assert data["payment_id"] == str(payment.payment_id)


@pytest.mark.asyncio
async def test_get_payment_not_found(
    client: AsyncClient,
    auth_headers
):
    """Тест получения несуществующего платежа"""
    response = await client.get(
        "/api/payments/00000000-0000-0000-0000-000000000000",
        headers=auth_headers
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_payment_status(
    client: AsyncClient,
    auth_headers,
    test_completed_session,
    test_customer,
    db_session: AsyncSession
):
    """Тест обновления статуса платежа"""
    session, vehicle, spot, zone = test_completed_session

    payment = Payment(
        session_id=session.session_id,
        customer_id=test_customer.customer_id,
        amount=Decimal("300.00"),
        payment_method="card",
        status="pending"
    )
    db_session.add(payment)
    await db_session.commit()
    await db_session.refresh(payment)

    response = await client.patch(
        f"/api/payments/{payment.payment_id}",
        headers=auth_headers,
        json={"status": "completed"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert "transaction_id" in data


@pytest.mark.asyncio
async def test_update_payment_invalid_status(
    client: AsyncClient,
    auth_headers,
    test_completed_session,
    test_customer,
    db_session: AsyncSession
):
    """Тест обновления платежа с некорректным статусом"""
    session, vehicle, spot, zone = test_completed_session

    payment = Payment(
        session_id=session.session_id,
        customer_id=test_customer.customer_id,
        amount=Decimal("300.00"),
        payment_method="card",
        status="pending"
    )
    db_session.add(payment)
    await db_session.commit()
    await db_session.refresh(payment)

    response = await client.patch(
        f"/api/payments/{payment.payment_id}",
        headers=auth_headers,
        json={"status": "invalid_status"}
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_calculate_session_cost(
    client: AsyncClient,
    auth_headers,
    test_completed_session
):
    """Тест расчета стоимости парковочной сессии"""
    session, vehicle, spot, zone = test_completed_session

    response = await client.get(
        f"/api/payments/session/{session.session_id}/calculate",
        headers=auth_headers
    )

    assert response.status_code == 200
    data = response.json()
    assert "amount" in data
    assert "currency" in data
    assert data["currency"] == "RUB"
    assert "duration_hours" in data
    assert "tariff_name" in data


@pytest.mark.asyncio
async def test_calculate_cost_active_session(
    client: AsyncClient,
    auth_headers,
    test_vehicle_for_session,
    test_spot_with_zone,
    db_session: AsyncSession
):
    """Тест расчета стоимости незавершенной сессии"""
    session = ParkingSession(
        vehicle_id=test_vehicle_for_session.vehicle_id,
        spot_id=test_spot_with_zone.spot_id,
        entry_time=datetime.utcnow() - timedelta(hours=2),
        status="active"
    )
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    response = await client.get(
        f"/api/payments/session/{session.session_id}/calculate",
        headers=auth_headers
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_payment_cost_calculation():
    """Тест функции расчета стоимости парковки"""
    from app.api.endpoints.payments import calculate_parking_cost

    # Создаем тестовый тариф
    tariff = TariffPlan(
        name="Тестовый",
        description="Тест",
        price_per_hour=Decimal("100.00"),
        price_per_day=Decimal("1000.00"),
        is_active=True
    )

    # Тест 1: Ровно 2 часа парковки
    entry_time = datetime.utcnow() - timedelta(hours=2, minutes=0, seconds=0)
    exit_time = datetime.utcnow()

    session = ParkingSession(
        vehicle_id="00000000-0000-0000-0000-000000000000",
        spot_id="00000000-0000-0000-0000-000000000000",
        entry_time=entry_time,
        exit_time=exit_time,
        status="completed"
    )

    cost = calculate_parking_cost(session, tariff)
    # Функция округляет вверх, так что любое время > 2 часов = 3 часа
    # Проверяем, что стоимость разумная (200-300 руб)
    assert cost >= Decimal("200.00") and cost <= Decimal("300.00")

    # Тест 2: 25 часов парковки (должен использовать дневной тариф)
    entry_time = datetime.utcnow() - timedelta(hours=25)
    exit_time = datetime.utcnow()

    session.entry_time = entry_time
    session.exit_time = exit_time

    cost = calculate_parking_cost(session, tariff)
    assert cost == Decimal("2000.00")  # 2 дня * 1000 руб/день


@pytest.mark.asyncio
async def test_payment_unauthorized(client: AsyncClient):
    """Тест доступа к платежам без авторизации"""
    response = await client.get("/api/payments/")
    # HTTPBearer без credentials отвечает 403 Forbidden
    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_payment_different_methods(
    client: AsyncClient,
    auth_headers,
    test_completed_session,
    db_session: AsyncSession,
):
    """Тест создания платежей разными методами"""
    session, vehicle, spot, zone = test_completed_session
    methods = ["card", "cash", "online"]

    for i, method in enumerate(methods):
        now = datetime.utcnow()
        new_session = ParkingSession(
            vehicle_id=vehicle.vehicle_id,
            spot_id=spot.spot_id,
            entry_time=now - timedelta(hours=3 + i),
            exit_time=now - timedelta(hours=1 + i),
            duration_minutes=120,
            total_cost=Decimal("300.00"),
            status="completed",
        )
        db_session.add(new_session)
        await db_session.commit()
        await db_session.refresh(new_session)

        response = await client.post(
            "/api/payments/",
            headers=auth_headers,
            json={
                "session_id": str(new_session.session_id),
                "amount": 300.00,
                "payment_method": method,
            },
        )

        assert response.status_code == 201, response.json()
        data = response.json()
        assert data["payment_method"] == method
