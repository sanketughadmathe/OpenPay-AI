"""Demo data helpers: default providers, deterministic seeding, reset."""

from decimal import Decimal
from random import Random

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import AuditEvent, Payment, PaymentAttempt, Provider
from app.orchestrator import process_payment
from app.payment_service import record_audit

DEFAULT_PROVIDERS = [
    {
        "id": "provider_a",
        "name": "Provider A",
        "supported_currencies": ["INR", "USD"],
        "supported_payment_methods": ["UPI", "CARD"],
        "configured_cost": 0.018,
        "simulated_success_rate": 0.97,
        "timeout_rate": 0.02,
        "average_latency_ms": 180,
    },
    {
        "id": "provider_b",
        "name": "Provider B",
        "supported_currencies": ["INR", "USD"],
        "supported_payment_methods": ["UPI", "CARD"],
        "configured_cost": 0.021,
        "simulated_success_rate": 0.94,
        "timeout_rate": 0.02,
        "average_latency_ms": 240,
    },
]


def seed_default_providers(db: Session) -> None:
    """Insert the demo providers without overwriting live simulation state."""

    for provider_data in DEFAULT_PROVIDERS:
        if db.get(Provider, provider_data["id"]) is None:
            db.add(Provider(**provider_data))
    db.commit()


def seed_payments(db: Session, count: int, seed: int) -> dict[str, int]:
    """Run `count` real payments through the orchestrator, deterministically.

    Payment ids are derived from the seed so a reset followed by the same
    seed request reproduces the same demo, attempt for attempt.
    """

    rng = Random(f"demo:{seed}")
    existing = int(db.scalar(select(func.count()).select_from(Payment)) or 0)
    outcomes: dict[str, int] = {}

    for offset in range(1, count + 1):
        index = existing + offset
        suffix = f"{seed}_{index:04d}"
        payment = Payment(
            id=f"pay_demo_{suffix}",
            order_id=f"order_demo_{suffix}",
            amount=Decimal(str(round(rng.uniform(50, 5000), 2))),
            currency=rng.choice(("INR", "USD")),
            payment_method=rng.choice(("UPI", "CARD")),
            status="CREATED",
        )
        db.add(payment)
        db.flush()
        record_audit(
            db,
            event_type="PAYMENT_CREATED",
            payment_id=payment.id,
            payload={
                "order_id": payment.order_id,
                "amount": str(payment.amount),
                "currency": payment.currency,
                "payment_method": payment.payment_method,
                "simulated": True,
            },
        )
        db.commit()

        process_payment(db, payment, seed)
        outcomes[payment.status] = outcomes.get(payment.status, 0) + 1

    return outcomes


def reset_demo(db: Session) -> None:
    """Truncate payments, attempts and audit events; restore default providers."""

    db.execute(delete(PaymentAttempt))
    db.execute(delete(Payment))
    db.execute(delete(AuditEvent))

    for provider_data in DEFAULT_PROVIDERS:
        provider = db.get(Provider, provider_data["id"])
        if provider is None:
            db.add(Provider(**provider_data))
        else:
            provider.name = provider_data["name"]
            provider.is_healthy = True
            provider.supported_currencies = provider_data["supported_currencies"]
            provider.supported_payment_methods = provider_data["supported_payment_methods"]
            provider.configured_cost = provider_data["configured_cost"]
            provider.simulated_success_rate = provider_data["simulated_success_rate"]
            provider.timeout_rate = provider_data["timeout_rate"]
            provider.average_latency_ms = provider_data["average_latency_ms"]
    db.commit()