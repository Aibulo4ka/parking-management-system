"""
Tests for authentication endpoints
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register_new_customer(client: AsyncClient):
    """Test customer registration"""
    response = await client.post(
        "/api/auth/register",
        json={
            "email": "newuser@test.com",
            "password": "Password123",
            "first_name": "New",
            "last_name": "User",
            "phone": "+79991234567"
        }
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "newuser@test.com"
    assert data["first_name"] == "New"
    assert "customer_id" in data


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient, test_customer):
    """Test registration with existing email"""
    response = await client.post(
        "/api/auth/register",
        json={
            "email": "test@test.com",
            "password": "Password123",
            "first_name": "Duplicate",
            "last_name": "User",
            "phone": "+79991234568"
        }
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient, test_customer):
    """Test successful login"""
    response = await client.post(
        "/api/auth/login",
        json={
            "email": "test@test.com",
            "password": "Test123"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient, test_customer):
    """Test login with wrong password"""
    response = await client.post(
        "/api/auth/login",
        json={
            "email": "test@test.com",
            "password": "WrongPassword"
        }
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_current_customer(client: AsyncClient, auth_headers):
    """Test getting current customer info"""
    response = await client.get("/api/auth/me", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "test@test.com"
    assert data["first_name"] == "Test"


@pytest.mark.asyncio
async def test_get_current_customer_unauthorized(client: AsyncClient):
    """Test getting customer info without auth"""
    response = await client.get("/api/auth/me")
    # HTTPBearer без credentials отвечает 403 Forbidden
    assert response.status_code in (401, 403)
