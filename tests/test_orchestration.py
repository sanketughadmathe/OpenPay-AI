"""Orchestrator + retry tests (S1.c ACs) driven through the real API.

The per-attempt RNG is deterministic, but to test the retry *logic* exactly we
swap the simulator for a scripted one; routing, persistence and audit run real.
Each test resets demo state first so routing order (A before B) is deterministic
regardless of what earlier tests seeded.
"""

import os

os.environ["OPENPAY_DATABASE_URL"] = "sqlite+pysqlite:///:memory:"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AuditEvent  # noqa: E402
from app.providers import AttemptResult  # noqa: E402


def create_payload(order_id: str = "order_orch_1") -> dict[str, str]:
    return {
        "order_id": order_id,
        "amount": "1499.00",
        "currency": "INR",
        "payment_method": "UPI",
    }


def scripted_result(status: str) -> AttemptResult:
    return AttemptResult(
        status=status,
        failure_code=None if status == "SUCCEEDED" else status,
        latency_ms=200,
        simulated_cost=26.982,
    )


def script_by_provider(mapping: dict[str, str], default: str | None = None):
    """Fake simulator; `default` covers providers missing from the mapping."""

    def fake(provider, payment, rng) -> AttemptResult:
        status = mapping.get(provider.id, default)
        if status is None:
            raise AssertionError(f"unexpected provider routed: {provider.id}")
        return scripted_result(status)

    return fake


def audit_types(db, payment_id: str) -> list[str]:
    return list(
        db.scalars(
            select(AuditEvent.event_type).where(AuditEvent.payment_id == payment_id)
        )
    )


def fresh_client() -> TestClient:
    client = TestClient(app)
    client.__enter__()
    assert client.post("/api/v1/demo/reset").status_code == 200
    return client


def test_provider_error_retries_on_next_provider_and_succeeds(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.orchestrator.simulate_attempt",
        script_by_provider({"provider_a": "PROVIDER_ERROR", "provider_b": "SUCCEEDED"}),
    )
    client = fresh_client()
    try:
        response = client.post("/api/v1/payments", json=create_payload("order_orch_retry"))
        assert response.status_code == 201
        payment = response.json()
    finally:
        client.__exit__(None, None, None)

    assert payment["status"] == "SUCCEEDED"
    assert payment["selected_provider"] == "provider_b"
    assert payment["attempt_count"] == 2
    assert [a["provider_id"] for a in payment["attempts"]] == ["provider_a", "provider_b"]
    assert payment["attempts"][0]["status"] == "PROVIDER_ERROR"
    assert payment["attempts"][0]["failure_code"] == "PROVIDER_ERROR"
    assert payment["attempts"][1]["status"] == "SUCCEEDED"
    # Second attempt's routing decision must show A as excluded (already tried).
    assert (
        payment["attempts"][1]["routing_decision"]["excluded"]["provider_a"]
        == "already attempted for this payment"
    )

    with SessionLocal() as db:
        events = audit_types(db, payment["id"])
    for expected in [
        "ROUTING_DECISION_MADE",
        "PROVIDER_ATTEMPT_INITIATED",
        "PROVIDER_RESPONSE_RECEIVED",
        "RETRY_INITIATED",
    ]:
        assert expected in events


def test_timeout_parks_payment_pending_without_retry(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.orchestrator.simulate_attempt", script_by_provider({}, default="TIMEOUT")
    )
    client = fresh_client()
    try:
        response = client.post("/api/v1/payments", json=create_payload("order_orch_timeout"))
        assert response.status_code == 201
        payment = response.json()
    finally:
        client.__exit__(None, None, None)

    assert payment["status"] == "PENDING"
    assert payment["attempt_count"] == 1
    assert payment["attempts"][0]["status"] == "TIMEOUT"
    assert payment["attempts"][0]["failure_code"] == "TIMEOUT"

    with SessionLocal() as db:
        assert "RETRY_INITIATED" not in audit_types(db, payment["id"])


def test_attempts_are_bounded_by_max_attempts(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.orchestrator.simulate_attempt", script_by_provider({}, default="PROVIDER_ERROR")
    )
    client = fresh_client()
    try:
        response = client.post("/api/v1/payments", json=create_payload("order_orch_bound"))
        payment = response.json()
    finally:
        client.__exit__(None, None, None)

    assert payment["status"] == "FAILED"
    assert payment["attempt_count"] == 2  # MAX_ATTEMPTS=2
    assert all(a["status"] == "PROVIDER_ERROR" for a in payment["attempts"])
    assert {a["provider_id"] for a in payment["attempts"]} == {"provider_a", "provider_b"}

    with SessionLocal() as db:
        assert audit_types(db, payment["id"]).count("RETRY_INITIATED") == 1


def test_declined_is_final_no_retry(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.orchestrator.simulate_attempt", script_by_provider({}, default="DECLINED")
    )
    client = fresh_client()
    try:
        response = client.post("/api/v1/payments", json=create_payload("order_orch_declined"))
        payment = response.json()
    finally:
        client.__exit__(None, None, None)

    assert payment["status"] == "FAILED"
    assert payment["attempt_count"] == 1

    with SessionLocal() as db:
        assert "RETRY_INITIATED" not in audit_types(db, payment["id"])


def test_no_eligible_provider_fails_without_attempts() -> None:
    with TestClient(app) as client:
        assert (
            client.patch(
                "/api/v1/providers/provider_a/health", json={"is_healthy": False}
            ).status_code
            == 200
        )
        assert (
            client.patch(
                "/api/v1/providers/provider_b/health", json={"is_healthy": False}
            ).status_code
            == 200
        )
        response = client.post("/api/v1/payments", json=create_payload("order_orch_none"))
        payment = response.json()

        # Restore health for later tests.
        client.patch("/api/v1/providers/provider_a/health", json={"is_healthy": True})
        client.patch("/api/v1/providers/provider_b/health", json={"is_healthy": True})

    assert payment["status"] == "FAILED"
    assert payment["attempt_count"] == 0
    assert payment["selected_provider"] is None
    assert payment["attempts"] == []


def test_same_seed_replays_same_outcome() -> None:
    """Determinism AC: identical (seed, payment, attempt) draws identical results."""

    from app.providers import attempt_rng, simulate_attempt

    provider = type(
        "P",
        (),
        {
            "is_healthy": True,
            "simulated_success_rate": 0.5,
            "timeout_rate": 0.1,
            "average_latency_ms": 180,
            "configured_cost": 0.02,
        },
    )()
    payment = type("Pay", (), {"amount": 1000})()

    first = simulate_attempt(provider, payment, attempt_rng("42", "pay_fixed", 1))
    second = simulate_attempt(provider, payment, attempt_rng("42", "pay_fixed", 1))

    assert first == second