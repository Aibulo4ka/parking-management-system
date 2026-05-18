import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError, HTTPException
from app.core.config import settings
from app.core.exceptions import (
    http_exception_handler,
    validation_exception_handler,
    generic_exception_handler
)
from app.services.telegram_polling import polling_worker, should_start_polling

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if should_start_polling():
        polling_worker.start()
    try:
        yield
    finally:
        await polling_worker.stop()


# Create FastAPI application
app = FastAPI(
    title="Parking Management System API",
    description="API для системы управления парковкой",
    version="1.0.0",
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://0.0.0.0:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Register custom exception handlers (русские сообщения об ошибках)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Parking Management System API",
        "version": "1.0.0",
        "status": "running"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "database": "connected"
    }


# Import routers
from app.api.endpoints import auth, vehicles, zones, bookings, sessions, payments, ocr, admin, balance, telegram

# Include routers
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(vehicles.router, prefix="/api/vehicles", tags=["Vehicles"])
app.include_router(zones.router, prefix="/api/zones", tags=["Parking Zones"])
app.include_router(bookings.router, prefix="/api/bookings", tags=["Bookings"])
app.include_router(sessions.router, prefix="/api/sessions", tags=["Parking Sessions"])
app.include_router(payments.router, prefix="/api/payments", tags=["Payments"])
app.include_router(balance.router, prefix="/api/balance", tags=["Balance"])
app.include_router(ocr.router, prefix="/api/ocr", tags=["OCR - License Plate Recognition"])
app.include_router(admin.router, prefix="/api/admin", tags=["Admin Panel"])
app.include_router(telegram.router, prefix="/api/telegram", tags=["Telegram"])
