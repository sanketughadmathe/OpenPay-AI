from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal, get_db, init_db
from app.models import Payment, Provider
from app.payment_service import (
    IdempotencyConflict,
    create_payment,
    get_payment,
    get_payment_attempts,
)
from app.schemas import (
    HealthResponse,
    PaymentAttemptOut,
    PaymentCreate,
    PaymentCreatedResponse,
    PaymentOut,
    ProviderOut,
)


DEFAULT_PROVIDERS = [
    {
        "id": "provider_a",
        "name": "Provider A",
        "supported_currencies": ["INR", "USD"],
        "supported_payment_methods": ["UPI", "CARD"],
        "configured_cost": 0.018,
        "simulated_success_rate": 0.97,
        "average_latency_ms": 180,
    },
    {
        "id": "provider_b",
        "name": "Provider B",
        "supported_currencies": ["INR", "USD"],
        "supported_payment_methods": ["UPI", "CARD"],
        "configured_cost": 0.021,
        "simulated_success_rate": 0.94,
        "average_latency_ms": 240,
    },
]


def seed_default_providers(db: Session) -> None:
    """Insert the demo providers without overwriting live simulation state."""

    for provider_data in DEFAULT_PROVIDERS:
        existing = db.get(Provider, provider_data["id"])
        if existing is None:
            db.add(Provider(**provider_data))
    db.commit()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    with SessionLocal() as db:
        seed_default_providers(db)
    yield


settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version=settings.api_version,
    description="Simulated payment orchestration MVP. No real money is processed.",
    lifespan=lifespan,
)


@app.get("/", tags=["service"])
def read_root() -> dict[str, str]:
    return {
        "service": settings.app_name,
        "version": settings.api_version,
        "environment": settings.environment,
        "simulated": "true",
    }


@app.get("/health", response_model=HealthResponse, tags=["service"])
def health_check(db: Session = Depends(get_db)) -> HealthResponse:
    try:
        db.execute(select(1))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return HealthResponse(
        status="ok",
        version=settings.api_version,
        environment=settings.environment,
        database="connected",
    )


@app.get("/api/v1/providers", response_model=list[ProviderOut], tags=["providers"])
def list_providers(db: Session = Depends(get_db)) -> list[Provider]:
    return list(db.scalars(select(Provider).order_by(Provider.id)))


@app.post(
    "/api/v1/payments",
    response_model=PaymentCreatedResponse,
    status_code=201,
    tags=["payments"],
)
def create_payment_endpoint(
    request: PaymentCreate,
    response: Response,
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Payment:
    try:
        payment, created = create_payment(db, request, idempotency_key)
    except IdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not created:
        response.status_code = 200
    return payment


@app.get("/api/v1/payments/{payment_id}", response_model=PaymentOut, tags=["payments"])
def get_payment_endpoint(payment_id: str, db: Session = Depends(get_db)) -> Payment:
    payment = get_payment(db, payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    return payment


@app.get(
    "/api/v1/payments/{payment_id}/attempts",
    response_model=list[PaymentAttemptOut],
    tags=["payments"],
)
def get_payment_attempts_endpoint(
    payment_id: str, db: Session = Depends(get_db)
) -> list:
    attempts = get_payment_attempts(db, payment_id)
    if attempts is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    return attempts

