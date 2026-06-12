"""Tests for the FastAPI application (app.py)."""

from fastapi.testclient import TestClient

from agents.llm_client import get_active_provider
from app import app
from config import get_version


def test_health_returns_expected_shape() -> None:
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data == {
        "status": "ok",
        "provider": get_active_provider(),
        "version": get_version(),
    }


def test_audit_contract_unconfigured_returns_503() -> None:
    # No Azure settings in the test environment, so the pipeline is not built and
    # the endpoint reports 503 (the app still serves /health).
    with TestClient(app) as client:
        resp = client.post(
            "/audit_contract",
            json={
                "provider_npi": "1234567890",
                "state": "TX",
                "lob": "Medicare",
                "contract_id": "C-001",
            },
        )
    assert resp.status_code == 503
