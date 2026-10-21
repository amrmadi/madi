"""Tests for activity events and alerts.

A recurring theme: activity data defaults to `source = "simulated"`, so demo
data can never be mistaken for real sensor readings.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.models.enums import AssignmentRole
from backend.app.models.identity import CaregiverAssignment, ElderlyProfile, User
from backend.tests.conftest import auth_headers

NOW = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Activity events
# ---------------------------------------------------------------------------


def test_create_activity_event_defaults_source_to_simulated(
    client: TestClient, caregiver_user: User, elderly_profile: ElderlyProfile
) -> None:
    """Honesty guard: unmarked activity data is treated as simulated, not real."""
    headers = auth_headers(client, caregiver_user.email)

    response = client.post(
        f"/api/v1/elderly-profiles/{elderly_profile.id}/activity-events",
        headers=headers,
        json={
            "activity_type": "walking",
            "started_at": NOW.isoformat(),
            "duration_seconds": 300,
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["source"] == "simulated"


def test_create_activity_event_accepts_explicit_sensor_source(
    client: TestClient, caregiver_user: User, elderly_profile: ElderlyProfile
) -> None:
    headers = auth_headers(client, caregiver_user.email)

    response = client.post(
        f"/api/v1/elderly-profiles/{elderly_profile.id}/activity-events",
        headers=headers,
        json={"activity_type": "sitting", "started_at": NOW.isoformat(), "source": "sensor"},
    )

    assert response.status_code == 201
    assert response.json()["source"] == "sensor"


def test_create_activity_event_rejects_unknown_activity_type(
    client: TestClient, caregiver_user: User, elderly_profile: ElderlyProfile
) -> None:
    headers = auth_headers(client, caregiver_user.email)

    response = client.post(
        f"/api/v1/elderly-profiles/{elderly_profile.id}/activity-events",
        headers=headers,
        json={"activity_type": "flying", "started_at": NOW.isoformat()},
    )

    assert response.status_code == 422


def test_create_activity_event_rejects_end_before_start(
    client: TestClient, caregiver_user: User, elderly_profile: ElderlyProfile
) -> None:
    headers = auth_headers(client, caregiver_user.email)

    response = client.post(
        f"/api/v1/elderly-profiles/{elderly_profile.id}/activity-events",
        headers=headers,
        json={
            "activity_type": "walking",
            "started_at": NOW.isoformat(),
            "ended_at": (NOW - timedelta(hours=1)).isoformat(),
        },
    )

    assert response.status_code == 422


def test_create_activity_event_rejects_confidence_above_one(
    client: TestClient, caregiver_user: User, elderly_profile: ElderlyProfile
) -> None:
    headers = auth_headers(client, caregiver_user.email)

    response = client.post(
        f"/api/v1/elderly-profiles/{elderly_profile.id}/activity-events",
        headers=headers,
        json={"activity_type": "walking", "started_at": NOW.isoformat(), "confidence": 1.5},
    )

    assert response.status_code == 422


def test_list_activity_events_is_newest_first(
    client: TestClient,
    db_session: Session,
    caregiver_user: User,
    elderly_profile: ElderlyProfile,
) -> None:
    from backend.app.models.events import ActivityEvent

    db_session.add_all(
        [
            ActivityEvent(
                elderly_profile_id=elderly_profile.id,
                activity_type="walking",
                started_at=NOW - timedelta(hours=5),
                source="simulated",
            ),
            ActivityEvent(
                elderly_profile_id=elderly_profile.id,
                activity_type="sleeping",
                started_at=NOW,
                source="simulated",
            ),
        ]
    )
    db_session.commit()

    headers = auth_headers(client, caregiver_user.email)
    response = client.get(
        f"/api/v1/elderly-profiles/{elderly_profile.id}/activity-events", headers=headers
    )

    assert response.status_code == 200
    items = response.json()["items"]
    assert items[0]["activity_type"] == "sleeping"
    assert items[1]["activity_type"] == "walking"


def test_activity_history_can_be_filtered_by_time_window(
    client: TestClient,
    db_session: Session,
    caregiver_user: User,
    elderly_profile: ElderlyProfile,
) -> None:
    from backend.app.models.events import ActivityEvent

    db_session.add_all(
        [
            ActivityEvent(
                elderly_profile_id=elderly_profile.id,
                activity_type="walking",
                started_at=NOW - timedelta(days=10),
                source="simulated",
            ),
            ActivityEvent(
                elderly_profile_id=elderly_profile.id,
                activity_type="eating",
                started_at=NOW - timedelta(hours=1),
                source="simulated",
            ),
        ]
    )
    db_session.commit()

    headers = auth_headers(client, caregiver_user.email)
    since = (NOW - timedelta(days=1)).isoformat()
    # Pass the timestamp via `params` so httpx percent-encodes the "+" in the
    # UTC offset. Building the URL by hand leaves "+00:00" unencoded, and a raw
    # "+" in a query string is decoded as a space — which the API then rejects
    # as an invalid datetime (a 422 that has nothing to do with the endpoint).
    response = client.get(
        f"/api/v1/elderly-profiles/{elderly_profile.id}/activity-events",
        headers=headers,
        params={"start": since},
    )

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["activity_type"] == "eating"


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


def test_create_alert_starts_with_new_status(
    client: TestClient, caregiver_user: User, elderly_profile: ElderlyProfile
) -> None:
    headers = auth_headers(client, caregiver_user.email)

    response = client.post(
        f"/api/v1/elderly-profiles/{elderly_profile.id}/alerts",
        headers=headers,
        json={"alert_type": "fall", "severity": "critical", "title": "Possible fall"},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "new"
    assert body["severity"] == "critical"
    # The resident's name is included so the UI needs no extra request.
    assert body["elderly_profile_name"] == elderly_profile.display_name


def test_acknowledge_alert_records_who_and_when(
    client: TestClient, caregiver_user: User, elderly_profile: ElderlyProfile
) -> None:
    headers = auth_headers(client, caregiver_user.email)
    created = client.post(
        f"/api/v1/elderly-profiles/{elderly_profile.id}/alerts",
        headers=headers,
        json={"alert_type": "anomaly", "severity": "medium", "title": "Unusual night activity"},
    )
    alert_id = created.json()["id"]

    response = client.post(f"/api/v1/alerts/{alert_id}/acknowledge", headers=headers, json={})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "acknowledged"
    assert body["acknowledged_at"] is not None
    assert body["acknowledged_by_user_id"] == caregiver_user.id


def test_acknowledging_twice_is_rejected(
    client: TestClient, caregiver_user: User, elderly_profile: ElderlyProfile
) -> None:
    """Prevents an alert from being acknowledged repeatedly."""
    headers = auth_headers(client, caregiver_user.email)
    created = client.post(
        f"/api/v1/elderly-profiles/{elderly_profile.id}/alerts",
        headers=headers,
        json={"alert_type": "risk", "title": "Fall risk"},
    )
    alert_id = created.json()["id"]

    client.post(f"/api/v1/alerts/{alert_id}/acknowledge", headers=headers, json={})
    client.patch(f"/api/v1/alerts/{alert_id}", headers=headers, json={"status": "resolved"})

    # A resolved alert cannot be acknowledged again.
    second = client.post(f"/api/v1/alerts/{alert_id}/acknowledge", headers=headers, json={})

    assert second.status_code == 409
    assert second.json()["error"]["code"] == "ALERT_ALREADY_CLOSED"


def test_alert_acknowledge_note_preserves_original_message(
    client: TestClient, caregiver_user: User, elderly_profile: ElderlyProfile
) -> None:
    """The reason the alert was raised must not be overwritten by a note."""
    headers = auth_headers(client, caregiver_user.email)
    created = client.post(
        f"/api/v1/elderly-profiles/{elderly_profile.id}/alerts",
        headers=headers,
        json={"alert_type": "fall", "title": "Fall", "message": "Original reason"},
    )
    alert_id = created.json()["id"]

    response = client.post(
        f"/api/v1/alerts/{alert_id}/acknowledge",
        headers=headers,
        json={"note": "Checked on resident, she is fine."},
    )

    assert response.status_code == 200
    message = response.json()["message"]
    assert "Original reason" in message
    assert "Checked on resident" in message


def test_resolving_alert_sets_resolved_at(
    client: TestClient, caregiver_user: User, elderly_profile: ElderlyProfile
) -> None:
    headers = auth_headers(client, caregiver_user.email)
    created = client.post(
        f"/api/v1/elderly-profiles/{elderly_profile.id}/alerts",
        headers=headers,
        json={"alert_type": "risk", "title": "Needs review"},
    )
    alert_id = created.json()["id"]

    response = client.patch(f"/api/v1/alerts/{alert_id}", headers=headers, json={"status": "resolved"})

    assert response.status_code == 200
    assert response.json()["resolved_at"] is not None


def test_alerts_list_only_shows_accessible_residents(
    client: TestClient,
    db_session: Session,
    caregiver_user: User,
    elderly_profile: ElderlyProfile,
) -> None:
    """A caregiver's alert feed must not leak other residents' alerts."""
    from backend.app.models.alerts import Alert

    stranger = ElderlyProfile(display_name="Stranger", is_active=True)
    db_session.add(stranger)
    db_session.flush()
    db_session.add_all(
        [
            Alert(
                elderly_profile_id=elderly_profile.id,
                alert_type="fall",
                severity="high",
                status="new",
                title="Mine",
            ),
            Alert(
                elderly_profile_id=stranger.id,
                alert_type="fall",
                severity="high",
                status="new",
                title="Not mine",
            ),
        ]
    )
    db_session.commit()

    headers = auth_headers(client, caregiver_user.email)
    response = client.get("/api/v1/alerts", headers=headers)

    assert response.status_code == 200
    titles = [a["title"] for a in response.json()["items"]]
    assert titles == ["Mine"]


def test_alerts_can_be_filtered_by_status(
    client: TestClient,
    db_session: Session,
    caregiver_user: User,
    elderly_profile: ElderlyProfile,
) -> None:
    from backend.app.models.alerts import Alert

    db_session.add_all(
        [
            Alert(
                elderly_profile_id=elderly_profile.id,
                alert_type="fall",
                severity="high",
                status="new",
                title="New one",
            ),
            Alert(
                elderly_profile_id=elderly_profile.id,
                alert_type="fall",
                severity="low",
                status="acknowledged",
                title="Old one",
            ),
        ]
    )
    db_session.commit()

    headers = auth_headers(client, caregiver_user.email)
    response = client.get("/api/v1/alerts?status=new", headers=headers)

    assert response.status_code == 200
    assert [a["title"] for a in response.json()["items"]] == ["New one"]


def test_unassigned_caregiver_cannot_acknowledge_an_alert(
    client: TestClient,
    db_session: Session,
    other_caregiver: User,
    elderly_profile: ElderlyProfile,
) -> None:
    from backend.app.models.alerts import Alert

    alert = Alert(
        elderly_profile_id=elderly_profile.id,
        alert_type="fall",
        severity="high",
        status="new",
        title="Private alert",
    )
    db_session.add(alert)
    db_session.commit()

    headers = auth_headers(client, other_caregiver.email)
    response = client.post(f"/api/v1/alerts/{alert.id}/acknowledge", headers=headers, json={})

    assert response.status_code == 403


def test_missing_alert_returns_404(client: TestClient, caregiver_user: User) -> None:
    headers = auth_headers(client, caregiver_user.email)

    response = client.get("/api/v1/alerts/999999", headers=headers)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ALERT_NOT_FOUND"
