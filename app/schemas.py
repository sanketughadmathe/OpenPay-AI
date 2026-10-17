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
    average_latency_ms: int


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
    attempts: list[PaymentAttemptOut] = []


class PaymentCreatedResponse(PaymentOut):
    simulated: bool = True
