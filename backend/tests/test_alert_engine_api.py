"""End-to-end API tests for the alert engine and analytics endpoints.

These exercise the rules through HTTP, so they also verify the two guarantees
that must survive the trip through the API layer:

* missing data does not become an emergency;
* operational priority is never presented as validated medical risk.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.models.alerts import Alert
from backend.app.models.identity import ElderlyProfile, User
from backend.tests.conftest import auth_headers, create_user

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Rule evaluation over HTTP
# ---------------------------------------------------------------------------


def _evaluate(
    client: TestClient,
    headers: dict[str, str],
    profile_id: int,
    *,
    kind: str,
    values: dict | None = None,
    verified: bool = False,
    persist: bool = False,
) -> dict:
    response = client.post(
        f"/api/v1/elderly-profiles/{profile_id}/alerts/evaluate",
        headers=headers,
        params={"persist": str(persist).lower()},
        json={
            "kind": kind,
            "elderly_profile_id": profile_id,
            "observed_at": NOW.isoformat(),
            "values": values or {},
            "verified": verified,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_evaluate_verified_fall_is_critical(
    client: TestClient, caregiver_user: User, elderly_profile: ElderlyProfile
) -> None:
    headers = auth_headers(client, caregiver_user.email)

    body = _evaluate(
        client, headers, elderly_profile.id, kind="fall", verified=True
    )

    assert body["match"]["should_alert"] is True
    assert body["match"]["priority"] == "critical"
    assert body["match"]["rule_name"] == "fall.verified"


def test_evaluate_does_not_persist_by_default(
    client: TestClient,
    db_session: Session,
    caregiver_user: User,
    elderly_profile: ElderlyProfile,
) -> None:
    """Explanation is free of side effects unless the caller opts in."""
    headers = auth_headers(client, caregiver_user.email)

    body = _evaluate(
        client, headers, elderly_profile.id, kind="fall", verified=True, persist=False
    )

    assert body["persisted_alert_id"] is None
    assert body["persisted"] is False
    assert db_session.query(Alert).count() == 0


def test_evaluate_with_persist_creates_an_alert(
    client: TestClient,
    db_session: Session,
    caregiver_user: User,
    elderly_profile: ElderlyProfile,
) -> None:
    headers = auth_headers(client, caregiver_user.email)

    body = _evaluate(
        client, headers, elderly_profile.id, kind="fall", verified=True, persist=True
    )

    assert body["persisted_alert_id"] is not None
    assert body["persisted"] is True
    alert = db_session.get(Alert, body["persisted_alert_id"])
    assert alert is not None
    assert alert.severity == "critical"
    assert alert.status == "new"


def test_missing_confidence_does_not_create_an_emergency(
    client: TestClient,
    db_session: Session,
    caregiver_user: User,
    elderly_profile: ElderlyProfile,
) -> None:
    """Missing data must not become an emergency, even when persisting."""
    headers = auth_headers(client, caregiver_user.email)

    body = _evaluate(
        client, headers, elderly_profile.id, kind="fall", persist=True
    )

    assert body["match"]["outcome"] == "suppressed_no_data"
    assert body["match"]["should_alert"] is False
    assert body["match"]["triggered_by_missing_data"] is True
    # Nothing was written, because the engine declined to alert.
    assert body["persisted_alert_id"] is None
    assert db_session.query(Alert).count() == 0


def test_data_gap_is_never_critical(
    client: TestClient, caregiver_user: User, elderly_profile: ElderlyProfile
) -> None:
    headers = auth_headers(client, caregiver_user.email)

    body = _evaluate(
        client,
        headers,
        elderly_profile.id,
        kind="data_gap",
        values={"gap_minutes": 60 * 24 * 7},
    )

    assert body["match"]["should_alert"] is True
    assert body["match"]["priority"] in ("info", "low")
    assert body["match"]["triggered_by_missing_data"] is True


def test_unverified_risk_does_not_reach_high_priority(
    client: TestClient, caregiver_user: User, elderly_profile: ElderlyProfile
) -> None:
    headers = auth_headers(client, caregiver_user.email)

    body = _evaluate(
        client, headers, elderly_profile.id, kind="risk", values={"score": 9.9}
    )

    assert body["match"]["priority"] == "medium"


def test_evaluation_reports_the_thresholds_it_used(
    client: TestClient, caregiver_user: User, elderly_profile: ElderlyProfile
) -> None:
    headers = auth_headers(client, caregiver_user.email)

    body = _evaluate(
        client, headers, elderly_profile.id, kind="fall", values={"confidence": 0.8}
    )

    thresholds = body["match"]["applied_thresholds"]
    assert thresholds["fall_min_confidence"] == 0.60
    assert thresholds["verified"] is False


def test_evaluation_ignores_a_mismatched_body_profile_id(
    client: TestClient,
    db_session: Session,
    caregiver_user: User,
    elderly_profile: ElderlyProfile,
) -> None:
    """The URL is authoritative, so a caller cannot probe another resident."""
    other = ElderlyProfile(display_name="Other", is_active=True)
    db_session.add(other)
    db_session.commit()
    db_session.refresh(other)

    headers = auth_headers(client, caregiver_user.email)
    response = client.post(
        f"/api/v1/elderly-profiles/{elderly_profile.id}/alerts/evaluate",
        headers=headers,
        json={
            "kind": "fall",
            "elderly_profile_id": other.id,
            "observed_at": NOW.isoformat(),
            "values": {"confidence": 0.9},
            "verified": True,
        },
    )

    assert response.status_code == 200, response.text
    # The observation was rewritten to the authorised profile.
    assert response.json()["observation"]["elderly_profile_id"] == elderly_profile.id


def test_unassigned_caregiver_cannot_evaluate(
    client: TestClient, other_caregiver: User, elderly_profile: ElderlyProfile
) -> None:
    headers = auth_headers(client, other_caregiver.email)

    response = client.post(
        f"/api/v1/elderly-profiles/{elderly_profile.id}/alerts/evaluate",
        headers=headers,
        json={
            "kind": "fall",
            "elderly_profile_id": elderly_profile.id,
            "observed_at": NOW.isoformat(),
            "values": {"confidence": 0.9},
        },
    )

    assert response.status_code == 403


def test_evaluate_rejects_unknown_observation_kind(
    client: TestClient, caregiver_user: User, elderly_profile: ElderlyProfile
) -> None:
    headers = auth_headers(client, caregiver_user.email)

    response = client.post(
        f"/api/v1/elderly-profiles/{elderly_profile.id}/alerts/evaluate",
        headers=headers,
        json={
            "kind": "alien_invasion",
            "elderly_profile_id": elderly_profile.id,
            "observed_at": NOW.isoformat(),
        },
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def test_repeated_observations_deduplicate_within_cooldown(
    client: TestClient,
    db_session: Session,
    caregiver_user: User,
    elderly_profile: ElderlyProfile,
) -> None:
    """Three tells about one fall must produce one alert, counted three times."""
    headers = auth_headers(client, caregiver_user.email)

    ids = []
    for _ in range(3):
        body = _evaluate(
            client, headers, elderly_profile.id, kind="fall", verified=True, persist=True
        )
        ids.append(body["persisted_alert_id"])

    assert len(set(ids)) == 1, "deduplication should reuse the same alert"
    alert = db_session.get(Alert, ids[0])
    assert alert.occurrence_count == 3
    assert db_session.query(Alert).count() == 1


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def _create_alert(
    client: TestClient, headers: dict[str, str], profile_id: int
) -> int:
    response = client.post(
        f"/api/v1/elderly-profiles/{profile_id}/alerts",
        headers=headers,
        json={"alert_type": "fall", "severity": "high", "title": "Test alert"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_resolve_acknowledges_if_not_already_acknowledged(
    client: TestClient, caregiver_user: User, elderly_profile: ElderlyProfile
) -> None:
    headers = auth_headers(client, caregiver_user.email)
    alert_id = _create_alert(client, headers, elderly_profile.id)

    response = client.post(
        f"/api/v1/alerts/{alert_id}/resolve", headers=headers, json={"note": "Checked."}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "resolved"
    assert body["acknowledged_at"] is not None
    assert body["resolved_at"] is not None


def test_dismiss_keeps_the_row_and_marks_it_dismissed(
    client: TestClient,
    db_session: Session,
    caregiver_user: User,
    elderly_profile: ElderlyProfile,
) -> None:
    headers = auth_headers(client, caregiver_user.email)
    alert_id = _create_alert(client, headers, elderly_profile.id)

    response = client.post(
        f"/api/v1/alerts/{alert_id}/dismiss",
        headers=headers,
        json={"note": "False alarm."},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "dismissed"
    # Kept, not deleted, so false-alarm rate is measurable.
    assert db_session.get(Alert, alert_id) is not None


def test_resolved_alert_cannot_be_dismissed(
    client: TestClient, caregiver_user: User, elderly_profile: ElderlyProfile
) -> None:
    headers = auth_headers(client, caregiver_user.email)
    alert_id = _create_alert(client, headers, elderly_profile.id)
    client.post(f"/api/v1/alerts/{alert_id}/resolve", headers=headers, json={})

    response = client.post(f"/api/v1/alerts/{alert_id}/dismiss", headers=headers, json={})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ALERT_ALREADY_RESOLVED"


def test_unassigned_caregiver_cannot_resolve(
    client: TestClient, other_caregiver: User, elderly_profile: ElderlyProfile, caregiver_user: User
) -> None:
    owner_headers = auth_headers(client, caregiver_user.email)
    alert_id = _create_alert(client, owner_headers, elderly_profile.id)

    headers = auth_headers(client, other_caregiver.email)
    response = client.post(f"/api/v1/alerts/{alert_id}/resolve", headers=headers, json={})

    assert response.status_code == 403


def test_alert_timeline_exposes_lifecycle_timestamps(
    client: TestClient, caregiver_user: User, elderly_profile: ElderlyProfile
) -> None:
    headers = auth_headers(client, caregiver_user.email)
    alert_id = _create_alert(client, headers, elderly_profile.id)
    client.post(f"/api/v1/alerts/{alert_id}/acknowledge", headers=headers, json={})

    response = client.get(f"/api/v1/alerts/{alert_id}/timeline", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["created_at"] is not None
    assert body["acknowledged_at"] is not None
    assert body["resolved_at"] is None


def test_missing_alert_timeline_returns_404(
    client: TestClient, caregiver_user: User
) -> None:
    headers = auth_headers(client, caregiver_user.email)

    response = client.get("/api/v1/alerts/999999/timeline", headers=headers)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ALERT_NOT_FOUND"


# ---------------------------------------------------------------------------
# Rules inspection
# ---------------------------------------------------------------------------


def test_alert_rules_endpoint_requires_authentication(client: TestClient) -> None:
    response = client.get("/api/v1/alert-rules")

    assert response.status_code == 401


def test_alert_rules_endpoint_documents_the_safety_caps(
    client: TestClient, caregiver_user: User
) -> None:
    headers = auth_headers(client, caregiver_user.email)

    response = client.get("/api/v1/alert-rules", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["data_gap"]["max_priority"] in ("info", "low")
    assert "not validated medical risk" in body["explanation"]


# ---------------------------------------------------------------------------
# Analytics access control and KPI endpoints
# ---------------------------------------------------------------------------


def test_analyst_can_read_kpi_definitions(client: TestClient, db_session: Session) -> None:
    create_user(db_session, email="analyst@example.com", role=_analyst_role())
    headers = auth_headers(client, "analyst@example.com")

    response = client.get("/api/v1/analytics/kpi-definitions", headers=headers)

    assert response.status_code == 200, response.text
    definitions = response.json()["definitions"]
    assert len(definitions) == 8
    assert all(d["numerator"] and d["denominator"] for d in definitions)


def _analyst_role():
    from backend.app.models.enums import UserRole

    return UserRole.ANALYST


def test_caregiver_cannot_read_analytics(
    client: TestClient, caregiver_user: User
) -> None:
    headers = auth_headers(client, caregiver_user.email)

    response = client.get("/api/v1/analytics/kpi-definitions", headers=headers)

    assert response.status_code == 403


def test_admin_can_read_analytics(client: TestClient, db_session: Session) -> None:
    """Admins manage the system, so they can read every aggregate."""
    from backend.app.models.enums import UserRole

    create_user(db_session, email="admin-analytics@example.com", role=UserRole.ADMIN)
    headers = auth_headers(client, "admin-analytics@example.com")

    response = client.get("/api/v1/analytics/kpi-definitions", headers=headers)

    assert response.status_code == 200, response.text


def test_elderly_role_cannot_read_analytics(
    client: TestClient, db_session: Session
) -> None:
    """A resident's own login must not expose cross-resident aggregates."""
    from backend.app.models.enums import UserRole

    create_user(db_session, email="resident-analytics@example.com", role=UserRole.ELDERLY)
    headers = auth_headers(client, "resident-analytics@example.com")

    response = client.get("/api/v1/analytics/kpi-definitions", headers=headers)

    assert response.status_code == 403


def test_analytics_requires_authentication(client: TestClient) -> None:
    response = client.get("/api/v1/analytics/kpi-definitions")

    assert response.status_code == 401


def test_kpis_endpoint_requires_a_date_range(
    client: TestClient, db_session: Session
) -> None:
    create_user(db_session, email="analyst2@example.com", role=_analyst_role())
    headers = auth_headers(client, "analyst2@example.com")

    # No start/end -> 422, because a KPI without a window is meaningless.
    response = client.get("/api/v1/analytics/kpis", headers=headers)

    assert response.status_code == 422


def test_kpis_endpoint_rejects_an_inverted_window(
    client: TestClient, db_session: Session
) -> None:
    create_user(db_session, email="analyst3@example.com", role=_analyst_role())
    headers = auth_headers(client, "analyst3@example.com")

    response = client.get(
        "/api/v1/analytics/kpis",
        headers=headers,
        params={
            "start": (NOW + timedelta(days=1)).isoformat(),
            "end": NOW.isoformat(),
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_WINDOW"


def test_kpis_endpoint_returns_unmeasurable_rather_than_zero(
    client: TestClient, db_session: Session
) -> None:
    """With no data, KPIs must report 'not measurable', not 0%."""
    create_user(db_session, email="analyst4@example.com", role=_analyst_role())
    headers = auth_headers(client, "analyst4@example.com")

    response = client.get(
        "/api/v1/analytics/kpis",
        headers=headers,
        params={
            "start": NOW.isoformat(),
            "end": (NOW + timedelta(days=1)).isoformat(),
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    by_key = {k["kpi_key"]: k for k in body["kpis"]}
    assert by_key["alert_acknowledgement_rate"]["is_measurable"] is False
    assert by_key["alert_acknowledgement_rate"]["value"] is None
    # Every KPI carries its window back to the caller.
    assert body["window"]["start"].startswith("2026-10-20")


def test_kpis_endpoint_measures_real_data(
    client: TestClient, db_session: Session, caregiver_user: User, elderly_profile: ElderlyProfile
) -> None:
    """With genuine rows present, the KPI is measurable and correct."""
    headers = auth_headers(client, caregiver_user.email)
    first = _create_alert(client, headers, elderly_profile.id)
    _create_alert(client, headers, elderly_profile.id)
    client.post(f"/api/v1/alerts/{first}/acknowledge", headers=headers, json={})

    create_user(db_session, email="analyst5@example.com", role=_analyst_role())
    analyst_headers = auth_headers(client, "analyst5@example.com")

    window_start = datetime.now(timezone.utc) - timedelta(hours=1)
    window_end = datetime.now(timezone.utc) + timedelta(hours=1)
    response = client.get(
        "/api/v1/analytics/kpis",
        headers=analyst_headers,
        params={"start": window_start.isoformat(), "end": window_end.isoformat()},
    )

    assert response.status_code == 200, response.text
    by_key = {k["kpi_key"]: k for k in response.json()["kpis"]}
    ack = by_key["alert_acknowledgement_rate"]
    assert ack["is_measurable"] is True
    assert ack["numerator"] == 1
    assert ack["denominator"] == 2
    assert ack["value"] == 0.5


def test_kpis_csv_download_has_a_header_and_the_rows(
    client: TestClient, db_session: Session, caregiver_user: User, elderly_profile: ElderlyProfile
) -> None:
    headers = auth_headers(client, caregiver_user.email)
    _create_alert(client, headers, elderly_profile.id)

    create_user(db_session, email="analyst6@example.com", role=_analyst_role())
    analyst_headers = auth_headers(client, "analyst6@example.com")

    window_start = datetime.now(timezone.utc) - timedelta(hours=1)
    window_end = datetime.now(timezone.utc) + timedelta(hours=1)
    response = client.get(
        "/api/v1/analytics/kpis.csv",
        headers=analyst_headers,
        params={"start": window_start.isoformat(), "end": window_end.isoformat()},
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    lines = response.text.strip().splitlines()
    assert lines[0].startswith("kpi_key,")
    assert len(lines) == 9  # header + 8 KPIs
