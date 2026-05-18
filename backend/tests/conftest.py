"""
Test configuration and fixtures
"""
import pytest
from typing import AsyncGenerator
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.main import app
from app.db.database import Base, get_db
from app.models.customer import Customer
from app.models.vehicle import Vehicle
from app.core.security import get_password_hash

# Test database URL - использовать PostgreSQL как в проде
import os
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://parking_user:parking_pass_2024@db:5432/parking_test"
)


@pytest.fixture
async def db_engine():
    """Create a test database engine"""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        poolclass=NullPool,
        echo=False
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.fixture
async def db_session(db_engine):
    """Create a test database session"""
    async_session = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session() as session:
        yield session


@pytest.fixture
async def client(db_session: AsyncSession):
    """Create a test client"""
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
async def test_customer(db_session: AsyncSession):
    """Create a test customer"""
    customer = Customer(
        email="test@test.com",
        password_hash=get_password_hash("Test123"),
        first_name="Test",
        last_name="User",
        phone="+79999999999"
    )
    db_session.add(customer)
    await db_session.commit()
    await db_session.refresh(customer)
    return customer


@pytest.fixture
async def test_vehicle(db_session: AsyncSession, test_customer: Customer):
    """Create a test vehicle for the test customer"""
    vehicle = Vehicle(
        customer_id=test_customer.customer_id,
        license_plate="Т123ЕС777",
        brand="Toyota",
        model="Camry",
        color="Белый",
        vehicle_type="sedan",
    )
    db_session.add(vehicle)
    await db_session.commit()
    await db_session.refresh(vehicle)
    return vehicle


@pytest.fixture
async def auth_headers(client: AsyncClient, test_customer: Customer):
    """Get authentication headers for test customer"""
    response = await client.post(
        "/api/auth/login",
        json={"email": "test@test.com", "password": "Test123"}
    )
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
