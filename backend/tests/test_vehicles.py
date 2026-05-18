"""
Tests for vehicle endpoints
"""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle import Vehicle


@pytest.mark.asyncio
async def test_add_vehicle(client: AsyncClient, auth_headers):
    """Test adding a new vehicle"""
    response = await client.post(
        "/api/vehicles/",
        headers=auth_headers,
        json={
            "license_plate": "А123ВС777",
            "brand": "Toyota",
            "model": "Camry",
            "color": "Белый",
            "vehicle_type": "sedan"
        }
    )
    assert response.status_code == 201
    data = response.json()
    assert data["license_plate"] == "А123ВС777"
    assert data["brand"] == "Toyota"
    assert data["model"] == "Camry"


@pytest.mark.asyncio
async def test_get_vehicles(client: AsyncClient, auth_headers, db_session: AsyncSession, test_customer):
    """Test getting user vehicles"""
    # Add test vehicle
    vehicle = Vehicle(
        customer_id=test_customer.customer_id,
        license_plate="Т456ЕС199",
        brand="BMW",
        model="X5",
        color="Черный",
        vehicle_type="suv"
    )
    db_session.add(vehicle)
    await db_session.commit()

    response = await client.get("/api/vehicles/", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert any(v["license_plate"] == "Т456ЕС199" for v in data)


@pytest.mark.asyncio
async def test_delete_vehicle(client: AsyncClient, auth_headers, db_session: AsyncSession, test_customer):
    """Test deleting a vehicle"""
    # Add test vehicle
    vehicle = Vehicle(
        customer_id=test_customer.customer_id,
        license_plate="К789МН777",
        brand="Lada",
        model="Granta",
        color="Серый",
        vehicle_type="sedan"
    )
    db_session.add(vehicle)
    await db_session.commit()
    await db_session.refresh(vehicle)

    response = await client.delete(f"/api/vehicles/{vehicle.vehicle_id}", headers=auth_headers)
    assert response.status_code == 204
