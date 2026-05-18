"""
Тесты для эндпоинтов парковочных зон и мест
"""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta

from app.models.parking_zone import ParkingZone
from app.models.parking_spot import ParkingSpot
from app.models.booking import Booking


@pytest.fixture
async def test_zones(db_session: AsyncSession):
    """Создание тестовых парковочных зон"""
    zones = [
        ParkingZone(
            name="Центральная зона",
            address="ул. Ленина, 10",
            total_spots=50,
            available_spots=30,
            is_active=True
        ),
        ParkingZone(
            name="Северная зона",
            address="пр. Победы, 25",
            total_spots=100,
            available_spots=80,
            is_active=True
        ),
        ParkingZone(
            name="Закрытая зона",
            address="ул. Закрытая, 1",
            total_spots=20,
            available_spots=0,
            is_active=False
        )
    ]
    for zone in zones:
        db_session.add(zone)
    await db_session.commit()
    for zone in zones:
        await db_session.refresh(zone)
    return zones


@pytest.fixture
async def test_spots(db_session: AsyncSession, test_zones):
    """Создание тестовых парковочных мест"""
    spots = [
        ParkingSpot(
            zone_id=test_zones[0].zone_id,
            spot_number="A-001",
            spot_type="standard",
            is_occupied=False,
            is_active=True
        ),
        ParkingSpot(
            zone_id=test_zones[0].zone_id,
            spot_number="A-002",
            spot_type="disabled",
            is_occupied=False,
            is_active=True
        ),
        ParkingSpot(
            zone_id=test_zones[0].zone_id,
            spot_number="A-003",
            spot_type="electric",
            is_occupied=True,
            is_active=True
        ),
        ParkingSpot(
            zone_id=test_zones[1].zone_id,
            spot_number="B-001",
            spot_type="standard",
            is_occupied=False,
            is_active=True
        )
    ]
    for spot in spots:
        db_session.add(spot)
    await db_session.commit()
    for spot in spots:
        await db_session.refresh(spot)
    return spots


@pytest.mark.asyncio
async def test_get_all_zones(client: AsyncClient, test_zones):
    """Тест получения всех активных парковочных зон"""
    response = await client.get("/api/zones/")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2  # Только активные зоны
    assert all(zone["is_active"] for zone in data)


@pytest.mark.asyncio
async def test_get_all_zones_including_inactive(client: AsyncClient, test_zones):
    """Тест получения всех зон включая неактивные"""
    response = await client.get("/api/zones/?is_active=false")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1  # Только неактивные зоны
    assert all(not zone["is_active"] for zone in data)


@pytest.mark.asyncio
async def test_get_zone_by_id(client: AsyncClient, test_zones):
    """Тест получения конкретной зоны по ID"""
    zone = test_zones[0]
    response = await client.get(f"/api/zones/{zone.zone_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["zone_id"] == str(zone.zone_id)
    assert data["name"] == "Центральная зона"
    assert data["address"] == "ул. Ленина, 10"


@pytest.mark.asyncio
async def test_get_zone_not_found(client: AsyncClient):
    """Тест получения несуществующей зоны"""
    response = await client.get("/api/zones/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    assert "не найден" in response.json()["message"].lower()


@pytest.mark.asyncio
async def test_get_zone_spots(client: AsyncClient, test_zones, test_spots):
    """Тест получения всех мест в зоне"""
    zone = test_zones[0]
    response = await client.get(f"/api/zones/{zone.zone_id}/spots")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3  # 3 места в первой зоне
    assert all(spot["zone_id"] == str(zone.zone_id) for spot in data)


@pytest.mark.asyncio
async def test_get_zone_spots_filter_by_occupied(client: AsyncClient, test_zones, test_spots):
    """Тест фильтрации мест по занятости"""
    zone = test_zones[0]
    response = await client.get(f"/api/zones/{zone.zone_id}/spots?is_occupied=false")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2  # 2 свободных места
    assert all(not spot["is_occupied"] for spot in data)


@pytest.mark.asyncio
async def test_get_zone_spots_filter_by_type(client: AsyncClient, test_zones, test_spots):
    """Тест фильтрации мест по типу"""
    zone = test_zones[0]
    response = await client.get(f"/api/zones/{zone.zone_id}/spots?spot_type=disabled")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["spot_type"] == "disabled"


def _avail_payload(zone_id, *, spot_type=None):
    start = (datetime.utcnow() + timedelta(hours=2)).isoformat()
    end = (datetime.utcnow() + timedelta(hours=4)).isoformat()
    payload = {"zone_id": str(zone_id), "start_time": start, "end_time": end}
    if spot_type:
        payload["spot_type"] = spot_type
    return payload


@pytest.mark.asyncio
async def test_check_availability(client: AsyncClient, test_zones, test_spots):
    """Тест проверки доступности мест в зоне"""
    zone = test_zones[0]
    response = await client.post("/api/zones/availability", json=_avail_payload(zone.zone_id))

    assert response.status_code == 200
    data = response.json()
    assert data["zone_id"] == str(zone.zone_id)
    assert data["available_spots"] == 2  # 2 свободных активных места


@pytest.mark.asyncio
async def test_check_availability_by_type(client: AsyncClient, test_zones, test_spots):
    """Тест проверки доступности мест определенного типа"""
    zone = test_zones[0]
    response = await client.post(
        "/api/zones/availability",
        json=_avail_payload(zone.zone_id, spot_type="standard"),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["available_spots"] == 1  # 1 свободное стандартное место


@pytest.mark.asyncio
async def test_check_availability_invalid_zone(client: AsyncClient):
    """Тест проверки доступности для несуществующей зоны"""
    response = await client.post(
        "/api/zones/availability",
        json=_avail_payload("00000000-0000-0000-0000-000000000000"),
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_available_spots_for_timerange(
    client: AsyncClient,
    test_zones,
    test_spots,
    db_session: AsyncSession,
    test_customer,
    test_vehicle
):
    """Тест получения доступных мест для временного интервала"""
    zone = test_zones[0]
    spot = test_spots[0]

    # Создаем бронирование на определенное время
    start_time = datetime.utcnow() + timedelta(hours=2)
    end_time = start_time + timedelta(hours=2)

    booking = Booking(
        customer_id=test_customer.customer_id,
        vehicle_id=test_vehicle.vehicle_id,
        spot_id=spot.spot_id,
        start_time=start_time,
        end_time=end_time,
        status="confirmed"
    )
    db_session.add(booking)
    await db_session.commit()

    # Проверяем доступность на перекрывающееся время
    check_start = start_time + timedelta(hours=1)
    check_end = check_start + timedelta(hours=2)

    response = await client.get(
        f"/api/zones/{zone.zone_id}/available-spots?start_time={check_start.isoformat()}&end_time={check_end.isoformat()}"
    )

    assert response.status_code == 200
    data = response.json()
    # Место A-001 должно быть недоступно из-за бронирования
    available_spot_numbers = [spot["spot_number"] for spot in data]
    assert "A-001" not in available_spot_numbers


@pytest.mark.asyncio
async def test_get_available_spots_invalid_timerange(client: AsyncClient, test_zones):
    """Тест с некорректным временным интервалом"""
    zone = test_zones[0]
    start_time = datetime.utcnow() + timedelta(hours=2)
    end_time = start_time - timedelta(hours=1)  # Конец раньше начала

    response = await client.get(
        f"/api/zones/{zone.zone_id}/available-spots?start_time={start_time.isoformat()}&end_time={end_time.isoformat()}"
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_create_parking_spot(client: AsyncClient, test_zones):
    """Тест создания нового парковочного места"""
    zone = test_zones[0]
    response = await client.post(
        f"/api/zones/{zone.zone_id}/spots",
        json={
            "zone_id": str(zone.zone_id),
            "spot_number": "A-999",
            "spot_type": "standard",
            "is_occupied": False,
            "is_active": True
        }
    )

    assert response.status_code == 201
    data = response.json()
    assert data["spot_number"] == "A-999"
    assert data["zone_id"] == str(zone.zone_id)


@pytest.mark.asyncio
async def test_create_parking_spot_duplicate_number(
    client: AsyncClient,
    test_zones,
    test_spots
):
    """Тест создания места с существующим номером"""
    zone = test_zones[0]
    response = await client.post(
        f"/api/zones/{zone.zone_id}/spots",
        json={
            "zone_id": str(zone.zone_id),
            "spot_number": "A-001",  # Уже существует
            "spot_type": "standard",
            "is_occupied": False,
            "is_active": True
        }
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_create_parking_spot_invalid_zone(client: AsyncClient):
    """Тест создания места в несуществующей зоне"""
    response = await client.post(
        "/api/zones/00000000-0000-0000-0000-000000000000/spots",
        json={
            "zone_id": "00000000-0000-0000-0000-000000000000",
            "spot_number": "X-001",
            "spot_type": "standard",
            "is_occupied": False,
            "is_active": True
        }
    )

    assert response.status_code == 404
