from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics import build_summary
from app.config import get_settings
from app.database import SessionLocal, get_db, init_db
from app.demo import reset_demo, seed_default_providers, seed_payments
from app.models import AuditEvent, Payment, PaymentAttempt, Provider
from app.orchestrator import process_payment
from app.payment_service import (
    IdempotencyConflict,
    create_payment,
    get_payment,
    get_payment_attempts,
    record_audit,
)
from app.schemas import (
    AnalyticsSummary,
    AuditEventOut,
    DemoResetResponse,
    DemoSeedRequest,
    DemoSeedResponse,
    HealthResponse,
    PaymentAttemptOut,
    PaymentCreate,
    PaymentCreatedResponse,
    PaymentOut,
    ProviderHealthUpdate,
    ProviderOut,
)

DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "dashboard"


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


@app.patch(
    "/api/v1/providers/{provider_id}/health",
    response_model=ProviderOut,
    tags=["providers"],
)
def update_provider_health(
    provider_id: str,
    request: ProviderHealthUpdate,
    db: Session = Depends(get_db),
) -> Provider:
    provider = db.get(Provider, provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")

    changes: dict[str, dict[str, object]] = {}

    if request.is_healthy is not None and request.is_healthy != provider.is_healthy:
        changes["is_healthy"] = {"before": provider.is_healthy, "after": request.is_healthy}
        provider.is_healthy = request.is_healthy
    if (
        request.success_rate is not None
        and request.success_rate != provider.simulated_success_rate
    ):
        changes["success_rate"] = {
            "before": provider.simulated_success_rate,
            "after": request.success_rate,
        }
        provider.simulated_success_rate = request.success_rate
    if request.timeout_rate is not None and request.timeout_rate != provider.timeout_rate:
        changes["timeout_rate"] = {"before": provider.timeout_rate, "after": request.timeout_rate}
        provider.timeout_rate = request.timeout_rate

    if changes:
        record_audit(
            db,
            event_type="PROVIDER_HEALTH_CHANGED",
            payload={"provider_id": provider_id, **changes},
        )
        db.commit()

    return provider


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

    process_payment(db, payment, settings.sim_seed)
    return payment


@app.get("/api/v1/payments", response_model=list[PaymentOut], tags=["payments"])
def list_payments(
    status: str | None = Query(default=None, description="Filter by payment status"),
    provider: str | None = Query(default=None, description="Payments with any attempt on this provider"),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[Payment]:
    stmt = select(Payment).order_by(Payment.created_at.desc(), Payment.id.desc())
    if status:
        stmt = stmt.where(Payment.status == status.upper())
    if provider:
        stmt = stmt.where(Payment.attempts.any(PaymentAttempt.provider_id == provider))
    stmt = stmt.limit(limit)
    return list(db.scalars(stmt))


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


@app.get(
    "/api/v1/payments/{payment_id}/events",
    response_model=list[AuditEventOut],
    tags=["payments"],
)
def get_payment_events_endpoint(
    payment_id: str, db: Session = Depends(get_db)
) -> list[AuditEvent]:
    if get_payment(db, payment_id) is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    return list(
        db.scalars(
            select(AuditEvent)
            .where(AuditEvent.payment_id == payment_id)
            .order_by(AuditEvent.id)
        )
    )


@app.get("/api/v1/analytics/summary", response_model=AnalyticsSummary, tags=["analytics"])
def analytics_summary(db: Session = Depends(get_db)) -> AnalyticsSummary:
    return build_summary(db)


@app.post("/api/v1/demo/seed", response_model=DemoSeedResponse, tags=["demo"])
def demo_seed(request: DemoSeedRequest, db: Session = Depends(get_db)) -> DemoSeedResponse:
    seed = request.seed if request.seed is not None else settings.sim_seed
    outcomes = seed_payments(db, request.count, seed)
    return DemoSeedResponse(seeded=request.count, seed=seed, outcomes=outcomes)


@app.post("/api/v1/demo/reset", response_model=DemoResetResponse, tags=["demo"])
def demo_reset(db: Session = Depends(get_db)) -> DemoResetResponse:
    reset_demo(db)
    return DemoResetResponse()


# Static dashboard — declared after all API routes. Serves dashboard/ at /ui.
app.mount("/ui", StaticFiles(directory=DASHBOARD_DIR, html=True), name="ui")