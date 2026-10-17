"""E2 endpoint tests: PATCH health, demo seed/reset, list filters, summary AC-7."""

import os

os.environ["OPENPAY_DATABASE_URL"] = "sqlite+pysqlite:///:memory:"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AuditEvent, Payment, PaymentAttempt  # noqa: E402


def reset(client: TestClient) -> None:
    assert client.post("/api/v1/demo/reset").status_code == 200


def test_reset_clears_and_restores_providers() -> None:
    with TestClient(app) as client:
        assert client.post("/api/v1/demo/seed", json={"count": 5, "seed": 3}).status_code == 200
        client.patch("/api/v1/providers/provider_a/health", json={"is_healthy": False})

        assert client.post("/api/v1/demo/reset").status_code == 200

        providers = {p["id"]: p for p in client.get("/api/v1/providers").json()}
        assert providers["provider_a"]["is_healthy"] is True
        assert providers["provider_a"]["simulated_success_rate"] == 0.97

        summary = client.get("/api/v1/analytics/summary").json()
        assert summary["totals"]["payments"] == 0
        assert summary["totals"]["attempts"] == 0


def test_patch_health_updates_provider_and_audits() -> None:
    with TestClient(app) as client:
        response = client.patch(
            "/api/v1/providers/provider_a/health",
            json={"is_healthy": False, "success_rate": 0.2, "timeout_rate": 0.05},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["is_healthy"] is False
        assert body["simulated_success_rate"] == 0.2
        assert body["timeout_rate"] == 0.05

        assert (
            client.patch("/api/v1/providers/missing/health", json={"is_healthy": False}).status_code
            == 404
        )

        with SessionLocal() as db:
            events = list(
                db.scalars(
                    select(AuditEvent).where(AuditEvent.event_type == "PROVIDER_HEALTH_CHANGED")
                )
            )
        assert events
        payload = events[-1].event_payload
        assert payload["provider_id"] == "provider_a"
        assert payload["is_healthy"] == {"before": True, "after": False}
        assert payload["success_rate"]["after"] == 0.2

        # Restore defaults so later tests route to A again.
        reset(client)


def test_seed_is_deterministic() -> None:
    with TestClient(app) as client:
        reset(client)
        first = client.post("/api/v1/demo/seed", json={"count": 20, "seed": 7}).json()
        rows_first = client.get("/api/v1/payments", params={"limit": 500}).json()

        reset(client)
        second = client.post("/api/v1/demo/seed", json={"count": 20, "seed": 7}).json()
        rows_second = client.get("/api/v1/payments", params={"limit": 500}).json()

        assert first["outcomes"] == second["outcomes"]
        assert [(r["id"], r["status"], str(r["amount"])) for r in rows_first] == [
            (r["id"], r["status"], str(r["amount"])) for r in rows_second
        ]


def test_seed_and_summary_match_sql_counts() -> None:
    """AC-7: every summary number equals a direct SQL count."""

    with TestClient(app) as client:
        reset(client)
        seed = client.post("/api/v1/demo/seed", json={"count": 40, "seed": 11}).json()
        summary = client.get("/api/v1/analytics/summary").json()

        assert seed["seeded"] == 40
        assert summary["simulated"] is True

        with SessionLocal() as db:
            payment_count = int(db.scalar(select(func.count()).select_from(Payment)))
            attempt_count = int(db.scalar(select(func.count()).select_from(PaymentAttempt)))
            succeeded = int(
                db.scalar(select(func.count()).select_from(Payment).where(Payment.status == "SUCCEEDED"))
            )
            failed = int(
                db.scalar(select(func.count()).select_from(Payment).where(Payment.status == "FAILED"))
            )
            pending = int(
                db.scalar(select(func.count()).select_from(Payment).where(Payment.status == "PENDING"))
            )
            retries = int(
                db.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(AuditEvent.event_type == "RETRY_INITIATED")
                )
            )
            inr_value = float(
                db.scalar(select(func.sum(Payment.amount)).where(Payment.currency == "INR"))
            )

        assert summary["totals"]["payments"] == payment_count == 40
        assert summary["totals"]["attempts"] == attempt_count
        assert summary["totals"]["succeeded"] == succeeded
        assert summary["totals"]["failed"] == failed
        assert summary["totals"]["pending"] == pending
        assert summary["retry_count"] == retries
        assert summary["value_by_currency"]["INR"] == inr_value
        assert summary["totals"]["succeeded"] + summary["totals"]["failed"] + summary[
            "totals"
        ]["pending"] == 40


def test_payments_list_filters() -> None:
    with TestClient(app) as client:
        reset(client)
        client.post("/api/v1/demo/seed", json={"count": 30, "seed": 5})

        succeeded = client.get("/api/v1/payments", params={"status": "succeeded", "limit": 500}).json()
        assert succeeded
        assert all(p["status"] == "SUCCEEDED" for p in succeeded)

        on_b = client.get(
            "/api/v1/payments", params={"provider": "provider_b", "limit": 500}
        ).json()
        assert on_b
        assert all(
            any(a["provider_id"] == "provider_b" for a in p["attempts"]) for p in on_b
        )

        limited = client.get("/api/v1/payments", params={"limit": 5}).json()
        assert len(limited) == 5


def test_outage_shifts_traffic_to_provider_b() -> None:
    """CP2 gate: after A goes unhealthy, new traffic routes to B only."""

    with TestClient(app) as client:
        reset(client)
        client.post("/api/v1/demo/seed", json={"count": 30, "seed": 9})
        before = client.get("/api/v1/analytics/summary").json()["per_provider"]
        assert before["provider_a"]["attempts"] > 0  # A scores higher, takes most traffic
        before_b = before.get("provider_b", {"attempts": 0})["attempts"]

        client.patch("/api/v1/providers/provider_a/health", json={"is_healthy": False})
        client.post("/api/v1/demo/seed", json={"count": 15, "seed": 12})

        after = client.get("/api/v1/analytics/summary").json()["per_provider"]
        delta_b = after["provider_b"]["attempts"] - before_b
        delta_a = after["provider_a"]["attempts"] - before["provider_a"]["attempts"]
        assert delta_b >= 15  # every new attempt landed on B
        assert delta_a == 0

        reset(client)