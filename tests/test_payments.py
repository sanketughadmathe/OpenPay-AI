import os

os.environ["OPENPAY_DATABASE_URL"] = "sqlite+pysqlite:///:memory:"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.main import app  # noqa: E402
from app.models import AuditEvent, Payment  # noqa: E402
from app.payment_service import (  # noqa: E402
    InvalidPaymentTransition,
    PaymentStatus,
    transition_payment,
)


def create_payload(order_id: str = "order_1001", amount: str = "1499.00") -> dict[str, str]:
    return {
        "order_id": order_id,
        "amount": amount,
        "currency": "INR",
        "payment_method": "UPI",
    }


def test_create_payment_and_idempotent_replay() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/payments",
            json=create_payload(),
            headers={"Idempotency-Key": "demo-key-1"},
        )
        assert response.status_code == 201
        created = response.json()
        assert created["status"] == "CREATED"
        assert created["simulated"] is True
        assert created["attempts"] == []

        replay = client.post(
            "/api/v1/payments",
            json=create_payload(),
            headers={"Idempotency-Key": "demo-key-1"},
        )
        assert replay.status_code == 200
        assert replay.json()["id"] == created["id"]


def test_idempotency_key_rejects_changed_payload() -> None:
    with TestClient(app) as client:
        first = client.post(
            "/api/v1/payments",
            json=create_payload(),
            headers={"Idempotency-Key": "demo-key-2"},
        )
        assert first.status_code == 201

        conflict = client.post(
            "/api/v1/payments",
            json=create_payload(amount="1999.00"),
            headers={"Idempotency-Key": "demo-key-2"},
        )
        assert conflict.status_code == 409


def test_get_payment_and_attempts() -> None:
    with TestClient(app) as client:
        created = client.post("/api/v1/payments", json=create_payload())
        assert created.status_code == 201
        payment_id = created.json()["id"]

        details = client.get(f"/api/v1/payments/{payment_id}")
        assert details.status_code == 200
        assert details.json()["id"] == payment_id

        attempts = client.get(f"/api/v1/payments/{payment_id}/attempts")
        assert attempts.status_code == 200
        assert attempts.json() == []

        assert client.get("/api/v1/payments/missing").status_code == 404


def test_payment_creation_is_audited() -> None:
    with TestClient(app) as client:
        created = client.post("/api/v1/payments", json=create_payload())
        payment_id = created.json()["id"]

        # Verify through a direct read of the same in-memory database used by the app.
        from app.database import SessionLocal

        with SessionLocal() as db:
            events = list(
                db.scalars(
                    select(AuditEvent).where(
                        AuditEvent.payment_id == payment_id,
                        AuditEvent.event_type == "PAYMENT_CREATED",
                    )
                )
            )
            assert len(events) == 1
            assert events[0].event_payload["simulated"] is True


def test_payment_state_transitions_are_validated() -> None:
    from app.database import SessionLocal, init_db

    init_db()
    with SessionLocal() as db:
        payment = Payment(
            id="pay_state_test",
            order_id="order_state_test",
            amount="100.00",
            currency="INR",
            payment_method="UPI",
            status=PaymentStatus.CREATED,
        )
        db.add(payment)
        db.commit()

        transition_payment(db, payment, PaymentStatus.PROCESSING, reason="attempt started")
        assert payment.status == PaymentStatus.PROCESSING

        transition_payment(db, payment, PaymentStatus.SUCCEEDED, reason="provider confirmed")
        assert payment.status == PaymentStatus.SUCCEEDED

        try:
            transition_payment(db, payment, PaymentStatus.FAILED, reason="invalid terminal change")
        except InvalidPaymentTransition:
            pass
        else:
            raise AssertionError("Expected an invalid terminal state transition")
