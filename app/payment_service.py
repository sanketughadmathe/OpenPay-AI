from enum import StrEnum
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEvent, Payment, utcnow
from app.schemas import PaymentCreate


class PaymentStatus(StrEnum):
    CREATED = "CREATED"
    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    PENDING = "PENDING"
    REQUIRES_REVIEW = "REQUIRES_REVIEW"


ALLOWED_PAYMENT_TRANSITIONS: dict[PaymentStatus, set[PaymentStatus]] = {
    PaymentStatus.CREATED: {PaymentStatus.PROCESSING},
    PaymentStatus.PROCESSING: {
        PaymentStatus.SUCCEEDED,
        PaymentStatus.FAILED,
        PaymentStatus.PENDING,
        PaymentStatus.REQUIRES_REVIEW,
    },
    PaymentStatus.PENDING: {
        PaymentStatus.SUCCEEDED,
        PaymentStatus.FAILED,
        PaymentStatus.REQUIRES_REVIEW,
    },
    PaymentStatus.REQUIRES_REVIEW: {
        PaymentStatus.SUCCEEDED,
        PaymentStatus.FAILED,
        PaymentStatus.PENDING,
    },
    PaymentStatus.SUCCEEDED: set(),
    PaymentStatus.FAILED: set(),
}


class IdempotencyConflict(ValueError):
    """Raised when an idempotency key is replayed with different data."""


class InvalidPaymentTransition(ValueError):
    """Raised when a payment state change violates the state machine."""


def _request_payload(payment: PaymentCreate) -> tuple[object, ...]:
    return (
        payment.order_id,
        payment.amount,
        payment.currency,
        payment.payment_method,
    )


def _stored_payload(payment: Payment) -> tuple[object, ...]:
    return (
        payment.order_id,
        payment.amount,
        payment.currency,
        payment.payment_method,
    )


def record_audit(
    db: Session,
    *,
    event_type: str,
    payment_id: str | None = None,
    attempt_id: str | None = None,
    payload: dict[str, object],
) -> AuditEvent:
    event = AuditEvent(
        payment_id=payment_id,
        attempt_id=attempt_id,
        event_type=event_type,
        event_payload=payload,
    )
    db.add(event)
    return event


def create_payment(
    db: Session,
    request: PaymentCreate,
    idempotency_key: str | None = None,
) -> tuple[Payment, bool]:
    """Create a payment or return the existing payment for a replayed request."""

    if idempotency_key:
        existing = db.scalar(select(Payment).where(Payment.idempotency_key == idempotency_key))
        if existing is not None:
            if _request_payload(request) != _stored_payload(existing):
                raise IdempotencyConflict(
                    "Idempotency key was already used with a different payment payload"
                )
            return existing, False

    payment = Payment(
        id=f"pay_{uuid4().hex}",
        order_id=request.order_id,
        amount=request.amount,
        currency=request.currency,
        payment_method=request.payment_method,
        status=PaymentStatus.CREATED,
        idempotency_key=idempotency_key,
    )
    db.add(payment)
    db.flush()

    record_audit(
        db,
        event_type="PAYMENT_CREATED",
        payment_id=payment.id,
        payload={
            "order_id": request.order_id,
            "amount": str(request.amount),
            "currency": request.currency,
            "payment_method": request.payment_method,
            "simulated": True,
        },
    )
    db.commit()
    db.refresh(payment)
    return payment, True


def transition_payment(
    db: Session,
    payment: Payment,
    new_status: PaymentStatus,
    *,
    reason: str,
    attempt_id: str | None = None,
) -> Payment:
    current_status = PaymentStatus(payment.status)
    if new_status not in ALLOWED_PAYMENT_TRANSITIONS[current_status]:
        raise InvalidPaymentTransition(
            f"Cannot transition payment from {current_status.value} to {new_status.value}"
        )

    payment.status = new_status.value
    payment.updated_at = utcnow()
    record_audit(
        db,
        event_type="PAYMENT_STATE_CHANGED",
        payment_id=payment.id,
        attempt_id=attempt_id,
        payload={
            "from": current_status.value,
            "to": new_status.value,
            "reason": reason,
        },
    )
    db.commit()
    db.refresh(payment)
    return payment


def get_payment(db: Session, payment_id: str) -> Payment | None:
    return db.get(Payment, payment_id)


def get_payment_attempts(db: Session, payment_id: str):
    payment = get_payment(db, payment_id)
    if payment is None:
        return None
    return list(payment.attempts)
