"""Payment orchestration: routing, simulated attempts, bounded retries.

`process_payment` drives one payment from CREATED to a terminal (or PENDING)
state, persisting every attempt with its routing decision and an audit trail.
"""

from random import Random
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Payment, PaymentAttempt, Provider, utcnow
from app.payment_service import (
    PaymentStatus,
    record_audit,
    transition_payment,
)
from app.providers import (
    FINAL_FAILURES,
    RETRYABLE_FAILURES,
    attempt_rng,
    simulate_attempt,
)
from app.router import RoutingDecision, route

RECENT_WINDOW = 50


def load_providers(db: Session) -> list[Provider]:
    return list(db.scalars(select(Provider).order_by(Provider.id)))


def recent_success_by_provider(db: Session) -> dict[str, float]:
    """Success rate over each provider's last 50 attempts, else configured rate."""

    rates: dict[str, float] = {}
    for provider in load_providers(db):
        statuses = db.execute(
            select(PaymentAttempt.status)
            .where(PaymentAttempt.provider_id == provider.id)
            .order_by(PaymentAttempt.created_at.desc(), PaymentAttempt.id.desc())
            .limit(RECENT_WINDOW)
        ).scalars().all()
        if statuses:
            rates[provider.id] = sum(1 for s in statuses if s == "SUCCEEDED") / len(statuses)
        else:
            rates[provider.id] = provider.simulated_success_rate
    return rates


def _record_routing_audit(
    db: Session, payment_id: str, attempt_number: int, decision: RoutingDecision
) -> None:
    record_audit(
        db,
        event_type="ROUTING_DECISION_MADE",
        payment_id=payment_id,
        payload={"attempt_number": attempt_number, **decision.to_payload()},
    )


def process_payment(db: Session, payment: Payment, seed: Any) -> Payment:
    """Run a CREATED payment through routing, attempts and retries to completion."""

    settings = get_settings()
    max_attempts = settings.max_attempts

    transition_payment(
        db, payment, PaymentStatus.PROCESSING, reason="routing started"
    )

    tried: list[str] = []
    last_failure: str | None = None

    for attempt_number in range(1, max_attempts + 1):
        decision = route(
            payment,
            load_providers(db),
            recent_success_by_provider(db),
            exclude=set(tried),
        )
        _record_routing_audit(db, payment.id, attempt_number, decision)

        if decision.selected is None:
            transition_payment(
                db,
                payment,
                PaymentStatus.FAILED,
                reason="no eligible provider",
            )
            return payment

        provider = db.get(Provider, decision.selected)
        assert provider is not None  # selected came from the provider list above

        attempt = PaymentAttempt(
            id=f"att_{uuid4().hex}",
            payment_id=payment.id,
            provider_id=provider.id,
            attempt_number=attempt_number,
            status="PROCESSING",
            routing_decision=decision.to_payload(),
        )
        db.add(attempt)
        db.flush()
        record_audit(
            db,
            event_type="PROVIDER_ATTEMPT_INITIATED",
            payment_id=payment.id,
            attempt_id=attempt.id,
            payload={
                "attempt_number": attempt_number,
                "provider_id": provider.id,
                "payment_method": payment.payment_method,
                "currency": payment.currency,
            },
        )

        rng: Random = attempt_rng(str(seed), payment.id, attempt_number)
        result = simulate_attempt(provider, payment, rng)

        attempt.status = result.status
        attempt.failure_code = result.failure_code
        attempt.latency_ms = result.latency_ms
        attempt.simulated_cost = result.simulated_cost
        attempt.completed_at = utcnow()
        record_audit(
            db,
            event_type="PROVIDER_RESPONSE_RECEIVED",
            payment_id=payment.id,
            attempt_id=attempt.id,
            payload={
                "attempt_number": attempt_number,
                "provider_id": provider.id,
                "outcome": result.status,
                "failure_code": result.failure_code,
                "latency_ms": result.latency_ms,
                "simulated_cost": result.simulated_cost,
            },
        )
        db.commit()
        tried.append(provider.id)

        if result.status == "SUCCEEDED":
            transition_payment(
                db, payment, PaymentStatus.SUCCEEDED, reason="provider confirmed"
            )
            return payment

        if result.status == "TIMEOUT":
            # Outcome unknown: no auto-retry, park for manual review (FR-05).
            transition_payment(
                db,
                payment,
                PaymentStatus.PENDING,
                reason="provider timeout - outcome unknown, pending review",
            )
            return payment

        last_failure = result.failure_code or result.status

        if result.status in FINAL_FAILURES:
            transition_payment(
                db,
                payment,
                PaymentStatus.FAILED,
                reason=f"provider declined: {last_failure}",
            )
            return payment

        if result.status in RETRYABLE_FAILURES and attempt_number < max_attempts:
            record_audit(
                db,
                event_type="RETRY_INITIATED",
                payment_id=payment.id,
                attempt_id=attempt.id,
                payload={
                    "from_provider": provider.id,
                    "trigger": last_failure,
                    "next_attempt_number": attempt_number + 1,
                },
            )
            db.commit()
            continue

    transition_payment(
        db,
        payment,
        PaymentStatus.FAILED,
        reason=f"retry limit reached ({max_attempts} attempts): {last_failure}",
    )
    return payment