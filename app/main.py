from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ai
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
    Explanation,
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
    ai.clear_cache()
    reset_demo(db)
    return DemoResetResponse()


# Static dashboard — declared after all API routes. Serves dashboard/ at /ui.
# ---- AI copilot -------------------------------------------------------------
# POST returns the rule-based explanation immediately and schedules model enrichment;
# GET returns the latest cached answer (rule-based until the model result lands).


def _explain(
    db: Session, background: BackgroundTasks, *, kind: str, payment: Payment | None = None
) -> Explanation:
    evidence = (
        ai.build_payment_evidence(db, payment) if kind == "payment" else ai.build_incident_evidence(db)
    )
    key = ai.cache_key(kind, payment.id if payment else None)
    explanation = ai.rule_based_explanation(evidence)
    ai.put_cached(key, explanation)
    record_audit(
        db,
        event_type="AI_EXPLANATION_REQUESTED",
        payment_id=payment.id if payment else None,
        payload={"kind": kind, "llm_provider": ai.active_provider(), "simulated": True},
    )
    db.commit()
    background.add_task(ai.generate_and_cache, key, evidence)
    return explanation


@app.post("/api/v1/ai/explain/{payment_id}", response_model=Explanation, tags=["ai"])
def ai_explain_payment(
    payment_id: str, background: BackgroundTasks, db: Session = Depends(get_db)
) -> Explanation:
    payment = get_payment(db, payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    return _explain(db, background, kind="payment", payment=payment)


@app.get("/api/v1/ai/explain/{payment_id}", response_model=Explanation, tags=["ai"])
def ai_explain_payment_cached(payment_id: str) -> Explanation:
    cached = ai.get_cached(ai.cache_key("payment", payment_id))
    if cached is None:
        raise HTTPException(status_code=404, detail="No explanation requested for this payment yet")
    return cached


@app.post("/api/v1/ai/incident", response_model=Explanation, tags=["ai"])
def ai_incident(background: BackgroundTasks, db: Session = Depends(get_db)) -> Explanation:
    return _explain(db, background, kind="incident")


@app.get("/api/v1/ai/incident", response_model=Explanation, tags=["ai"])
def ai_incident_cached() -> Explanation:
    cached = ai.get_cached(ai.cache_key("incident"))
    if cached is None:
        raise HTTPException(status_code=404, detail="No incident summary requested yet")
    return cached


@app.get("/api/v1/ai/status", tags=["ai"])
def ai_status() -> dict[str, object]:
    s = get_settings()
    provider = ai.active_provider()
    model = s.gemini_model if provider == "gemini" else s.ollama_model if provider == "ollama" else None
    return {"llm_provider": provider, "model": model, "fallback": "rule-based", "simulated": True}



app.mount("/ui", StaticFiles(directory=DASHBOARD_DIR, html=True), name="ui")