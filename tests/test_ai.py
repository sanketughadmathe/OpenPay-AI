import os

os.environ["OPENPAY_DATABASE_URL"] = "sqlite+pysqlite:///:memory:"

from fastapi.testclient import TestClient  # noqa: E402

from app import ai  # noqa: E402
from app.main import app  # noqa: E402
from app.schemas import Explanation  # noqa: E402


def _no_llm(monkeypatch):
    monkeypatch.setattr(ai, "generate_llm_explanation", lambda evidence: None)


def _seed(client: TestClient) -> None:
    assert client.post("/api/v1/demo/reset").status_code == 200
    assert client.post("/api/v1/demo/seed", json={"count": 100, "seed": 42}).status_code == 200


def _retried_payment_id(client: TestClient) -> str:
    rows = client.get("/api/v1/payments", params={"limit": 500}).json()
    retried = [p for p in rows if p["attempt_count"] == 2]
    assert retried, "seed 42 should contain at least one retried payment"
    return retried[0]["id"]


def test_rule_based_explanation_is_grounded_in_attempts(monkeypatch) -> None:
    _no_llm(monkeypatch)
    with TestClient(app) as client:
        _seed(client)
        pid = _retried_payment_id(client)
        r = client.post(f"/api/v1/ai/explain/{pid}")
        assert r.status_code == 200
        body = r.json()
        assert body["source"] == "rule-based"
        assert body["simulated"] is True
        assert "attempt 1" in body["summary"].lower()
        assert any("Attempt 1 on provider_a" in line for line in body["evidence"])
        assert any("Attempt 2 on provider_b" in line for line in body["evidence"])
        assert any("selected provider_b" in line for line in body["evidence"])
        assert all(c.startswith("Hypothesis:") for c in body["possible_causes"])


def test_cached_get_returns_latest_and_404_before_request(monkeypatch) -> None:
    _no_llm(monkeypatch)
    with TestClient(app) as client:
        _seed(client)
        pid = _retried_payment_id(client)
        assert client.get(f"/api/v1/ai/explain/{pid}").status_code == 404
        client.post(f"/api/v1/ai/explain/{pid}")
        cached = client.get(f"/api/v1/ai/explain/{pid}")
        assert cached.status_code == 200
        assert cached.json()["source"] == "rule-based"


def test_model_result_replaces_rule_based_in_cache(monkeypatch) -> None:
    def fake_llm(evidence):
        return Explanation(
            summary="model summary",
            evidence=["e"],
            possible_causes=["Hypothesis: x"],
            recommended_actions=["a"],
            confidence_note="n",
            source="gemini:fake-model",
        )

    monkeypatch.setattr(ai, "generate_llm_explanation", fake_llm)
    with TestClient(app) as client:
        _seed(client)
        pid = _retried_payment_id(client)
        first = client.post(f"/api/v1/ai/explain/{pid}").json()
        assert first["source"] == "rule-based"  # immediate answer is always rule-based
        later = client.get(f"/api/v1/ai/explain/{pid}").json()  # background task ran before return
        assert later["source"] == "gemini:fake-model"
        assert later["summary"] == "model summary"


def test_explain_unknown_payment_404(monkeypatch) -> None:
    _no_llm(monkeypatch)
    with TestClient(app) as client:
        assert client.post("/api/v1/ai/explain/pay_missing").status_code == 404


def test_incident_without_health_change_reports_insufficient_data(monkeypatch) -> None:
    _no_llm(monkeypatch)
    with TestClient(app) as client:
        _seed(client)
        body = client.post("/api/v1/ai/incident").json()
        assert body["source"] == "rule-based"
        assert "insufficient" in body["confidence_note"].lower()


def test_incident_after_outage_shows_traffic_shift(monkeypatch) -> None:
    _no_llm(monkeypatch)
    with TestClient(app) as client:
        _seed(client)
        assert client.patch("/api/v1/providers/provider_a/health", json={"is_healthy": False}).status_code == 200
        assert client.post("/api/v1/demo/seed", json={"count": 50, "seed": 7}).status_code == 200
        body = client.post("/api/v1/ai/incident").json()
        assert "provider_a" in body["summary"]
        assert "provider_b" in body["summary"]
        assert any(line.startswith("Health change on provider_a") for line in body["evidence"])


def test_audit_event_recorded_for_ai_request(monkeypatch) -> None:
    _no_llm(monkeypatch)
    with TestClient(app) as client:
        _seed(client)
        pid = _retried_payment_id(client)
        client.post(f"/api/v1/ai/explain/{pid}")
        events = client.get(f"/api/v1/payments/{pid}/events").json()
        assert any(e["event_type"] == "AI_EXPLANATION_REQUESTED" for e in events)


def test_llm_failure_is_swallowed(monkeypatch) -> None:
    def boom(evidence):
        raise RuntimeError("network down")

    # generate_llm_explanation must never raise even if a client does
    monkeypatch.setattr(ai, "call_gemini", boom)
    monkeypatch.setattr(ai, "call_ollama", boom)
    monkeypatch.setattr(ai, "active_provider", lambda: "gemini")
    assert ai.generate_llm_explanation({"kind": "payment"}) is None
