import os

os.environ["OPENPAY_DATABASE_URL"] = "sqlite+pysqlite:///:memory:"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def test_health_and_providers() -> None:
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

        providers = client.get("/api/v1/providers")
        assert providers.status_code == 200
        assert [provider["id"] for provider in providers.json()] == ["provider_a", "provider_b"]

