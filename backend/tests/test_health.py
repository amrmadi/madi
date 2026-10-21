"""Tests for the health and version endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_reports_ok_when_database_reachable(client: TestClient) -> None:
    """`/api/v1/health` should report a working database connection."""
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "connected"
    assert "version" in body


def test_health_available_at_root_for_healthchecks(client: TestClient) -> None:
    """Docker/load balancers conventionally probe `/health`."""
    assert client.get("/health").status_code == 200


def test_health_reports_content_type_json(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.headers["content-type"].startswith("application/json")


def test_version_endpoint_returns_environment(client: TestClient) -> None:
    response = client.get("/api/v1/version")

    assert response.status_code == 200
    body = response.json()
    assert "version" in body
    assert "environment" in body


def test_unknown_route_returns_error_envelope(client: TestClient) -> None:
    """A 404 must use the same {"error": {...}} shape as every other failure."""
    response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert "error" in body
    assert body["error"]["code"] == "NOT_FOUND"
