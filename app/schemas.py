from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models import Provider


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    database: str


class ProviderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    is_healthy: bool
    supported_currencies: list[str]
    supported_payment_methods: list[str]
    configured_cost: float
    simulated_success_rate: float
    timeout_rate: float
    average_latency_ms: int


class ProviderHealthUpdate(BaseModel):
    is_healthy: bool | None = None
    success_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    timeout_rate: float | None = Field(default=None, ge=0.0, le=1.0)


class PaymentCreate(BaseModel):
    order_id: str = Field(min_length=1, max_length=120)
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    currency: str = Field(min_length=3, max_length=3, pattern="^[A-Z]{3}$")
    payment_method: str = Field(min_length=1, max_length=40, pattern="^(UPI|CARD)$")


class PaymentAttemptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    payment_id: str
    provider_id: str
    attempt_number: int
    status: str
    failure_code: str | None
    latency_ms: int | None
    simulated_cost: float | None
    routing_decision: dict[str, object] | None = None
    created_at: datetime
    completed_at: datetime | None


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    order_id: str
    amount: Decimal
    currency: str
    payment_method: str
    status: str
    idempotency_key: str | None
    created_at: datetime
    updated_at: datetime
    selected_provider: str | None = None
    attempt_count: int = 0
    simulated: bool = True
    attempts: list[PaymentAttemptOut] = []


class PaymentCreatedResponse(PaymentOut):
    """POST /payments returns the finished (routed and processed) payment."""


class DemoSeedRequest(BaseModel):
    count: int = Field(default=100, ge=1, le=1000)
    seed: int | None = None


class DemoSeedResponse(BaseModel):
    seeded: int
    seed: int
    outcomes: dict[str, int]
    simulated: bool = True


class DemoResetResponse(BaseModel):
    reset: bool = True
    simulated: bool = True


class ProviderSummary(BaseModel):
    success_rate: float
    avg_latency_ms: float | None
    total_cost: float
    attempts: int


class AnalyticsSummary(BaseModel):
    simulated: bool = True
    totals: dict[str, int]
    success_rate: float
    simulated_value: float
    value_by_currency: dict[str, float]
    per_provider: dict[str, ProviderSummary]
    failure_codes: dict[str, int]
    retry_count: int
