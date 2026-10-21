"""End-to-end workflow test: one caregiver's whole journey through the API.

Why this file exists
--------------------
The other test modules check one endpoint at a time. That is the right way to
find most bugs, but it cannot catch problems that only appear when features are
used *together* — for example, whether a resident created through the API is
immediately reachable for a care plan, a check-in, and an alert.

So this module walks the full path a real user takes, in order:

    1. register a caregiver account
    2. create a resident profile
    3. create a care plan for that resident
    4. record a daily check-in
    5. record a simulated fall event
    6. create the alert that fall produces
    7. acknowledge, resolve, and read the alert's timeline
    8. confirm an unassigned caregiver is locked out of all of it

Everything here uses the public HTTP API. Nothing reaches into the database to
set up state, because a test that bypasses the API cannot prove the API works.

The test also checks the two honesty rules this project depends on:

* a fall detected from **simulated** data is labelled as simulated, so it can
  never be mistaken for a real sensor reading;
* the AI endpoints report that **no model is loaded** rather than inventing a
  prediction.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.models.identity import User
from backend.tests.conftest import auth_headers

API = "/api/v1"


def _register_and_sign_in(client: TestClient, email: str, name: str) -> dict[str, str]:
    """Register a caregiver and return ready-to-use auth headers.

    Registration may return a token directly; if the account already exists in
    another test we fall back to logging in, so the helper is idempotent.
    """
    registered = client.post(
        f"{API}/auth/register",
        json={
            "email": email,
            "display_name": name,
            "password": "WorkflowPassw0rd!23",
            "role": "caregiver",
        },
    )

    if registered.status_code in (200, 201):
        token = registered.json().get("access_token")
        if token:
            return {"Authorization": f"Bearer {token}"}

    logged_in = client.post(
        f"{API}/auth/login",
        json={"email": email, "password": "WorkflowPassw0rd!23"},
    )
    assert logged_in.status_code == 200, logged_in.text
    return {"Authorization": f"Bearer {logged_in.json()['access_token']}"}


# ---------------------------------------------------------------------------
# The full journey
# ---------------------------------------------------------------------------


def test_full_caregiver_workflow_from_registration_to_resolved_alert(
    client: TestClient,
) -> None:
    """One continuous run through every feature Phase 7 asks us to verify."""
    headers = _register_and_sign_in(client, "workflow.caregiver@example.com", "Workflow Carer")

    # --- 1. The account works and identifies itself -------------------------
    me = client.get(f"{API}/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    assert me.json()["role"] == "caregiver"

    # --- 2. Create a resident ----------------------------------------------
    profile_response = client.post(
        f"{API}/elderly-profiles",
        headers=headers,
        json={
            "display_name": "Workflow Resident",
            "room_label": "B-202",
            "date_of_birth": "1948-04-12",
        },
    )
    assert profile_response.status_code == 201, profile_response.text
    profile = profile_response.json()
    profile_id = profile["id"]
    assert profile["display_name"] == "Workflow Resident"

    # The creator is auto-assigned, so they can act on it immediately. Without
    # this the very next request would 403, which is worth asserting explicitly.
    detail = client.get(f"{API}/elderly-profiles/{profile_id}", headers=headers)
    assert detail.status_code == 200, detail.text

    # --- 3. Care plan -------------------------------------------------------
    plan_response = client.post(
        f"{API}/elderly-profiles/{profile_id}/care-plans",
        headers=headers,
        json={
            "title": "Morning routine",
            "summary": "Breakfast, medication, and a short walk.",
            "status": "active",
        },
    )
    assert plan_response.status_code == 201, plan_response.text
    plan = plan_response.json()
    assert plan["status"] == "active"

    # The plan must show up in the resident's plan list.
    plans = client.get(f"{API}/elderly-profiles/{profile_id}/care-plans", headers=headers)
    assert plans.status_code == 200
    assert any(p["id"] == plan["id"] for p in plans.json()["items"])

    # Updating the plan persists the change.
    updated = client.patch(
        f"{API}/care-plans/{plan['id']}",
        headers=headers,
        json={"status": "completed"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["status"] == "completed"

    # --- 4. Daily check-in --------------------------------------------------
    checkin_response = client.post(
        f"{API}/elderly-profiles/{profile_id}/checkins",
        headers=headers,
        json={
            "checkin_type": "wellbeing",
            "status": "taken",
            "wellbeing_note": "Ate a full breakfast and walked to the garden.",
        },
    )
    assert checkin_response.status_code == 201, checkin_response.text
    checkin = checkin_response.json()
    # A completed check-in with no timestamp defaults to "now" on the server.
    assert checkin["performed_at"] is not None
    assert checkin["recorded_by_user_id"] is not None

    # --- 5. A simulated fall event -----------------------------------------
    event_response = client.post(
        f"{API}/elderly-profiles/{profile_id}/activity-events",
        headers=headers,
        json={
            "activity_type": "lying",
            "source": "simulated",
            "confidence": 0.91,
            "started_at": "2026-03-05T09:30:00Z",
            "ended_at": "2026-03-05T09:32:00Z",
            "note": "Simulated fall for demo purposes.",
        },
    )
    assert event_response.status_code == 201, event_response.text
    event = event_response.json()

    # The honesty rule: demo data is labelled as demo data.
    assert event["source"] == "simulated"

    # --- 6. The alert that fall produces ------------------------------------
    alert_response = client.post(
        f"{API}/elderly-profiles/{profile_id}/alerts",
        headers=headers,
        json={
            "alert_type": "fall",
            "severity": "critical",
            "title": "Possible fall detected",
            "message": "Simulated fall event reported for the demo walkthrough.",
        },
    )
    assert alert_response.status_code == 201, alert_response.text
    alert = alert_response.json()
    alert_id = alert["id"]

    # A brand-new alert is unacknowledged, so it appears in the open queue.
    assert alert["status"] == "new"
    assert alert["acknowledged_at"] is None

    open_alerts = client.get(
        f"{API}/elderly-profiles/{profile_id}/alerts",
        headers=headers,
        params={"status": "new"},
    )
    assert open_alerts.status_code == 200
    assert any(a["id"] == alert_id for a in open_alerts.json()["items"])

    # --- 7. Acknowledge, then resolve ---------------------------------------
    acknowledged = client.post(
        f"{API}/alerts/{alert_id}/acknowledge",
        headers=headers,
        json={"note": "Rang the resident; they are fine."},
    )
    assert acknowledged.status_code == 200, acknowledged.text
    ack_body = acknowledged.json()
    assert ack_body["status"] == "acknowledged"
    assert ack_body["acknowledged_at"] is not None
    assert ack_body["acknowledged_by_user_id"] is not None

    resolved = client.post(
        f"{API}/alerts/{alert_id}/resolve",
        headers=headers,
        json={"note": "False alarm — checked in person."},
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "resolved"

    # The timeline returns the alert with its lifecycle timestamps
    # (created_at -> acknowledged_at -> resolved_at). These are the exact
    # values the caregiver-acknowledgement KPI is computed from, so they
    # must all be present on a fully handled alert.
    timeline = client.get(f"{API}/alerts/{alert_id}/timeline", headers=headers)
    assert timeline.status_code == 200, timeline.text
    history = timeline.json()
    assert history["created_at"] is not None
    assert history["acknowledged_at"] is not None
    assert history["resolved_at"] is not None
    assert history["status"] == "resolved"

    # --- 8. An unassigned caregiver is locked out ---------------------------
    outsider = _register_and_sign_in(client, "workflow.outsider@example.com", "Outside Carer")

    for path in (
        f"{API}/elderly-profiles/{profile_id}",
        f"{API}/elderly-profiles/{profile_id}/care-plans",
        f"{API}/elderly-profiles/{profile_id}/checkins",
        f"{API}/elderly-profiles/{profile_id}/alerts",
    ):
        denied = client.get(path, headers=outsider)
        assert denied.status_code == 403, f"{path} returned {denied.status_code}"

    # They must not be able to acknowledge another resident's alert either.
    denied_ack = client.post(
        f"{API}/alerts/{alert_id}/acknowledge", headers=outsider, json={}
    )
    assert denied_ack.status_code == 403


def test_workflow_reports_ai_capabilities_honestly(
    client: TestClient, caregiver_user: User
) -> None:
    """The AI half of the journey: capabilities are declared, results are honest.

    Pairing this with the workflow above makes a central honesty claim testable:
    the care features work on real stored data, and the AI features report their
    own state truthfully.

    Fall detection now has a trained model, but the model file is git-ignored and
    may legitimately be absent (a fresh clone), so both outcomes are possible.
    What must hold either way is that a prediction is never returned without a
    model, and that a returned prediction is flagged as research data rather than
    a live reading of a resident.
    """
    headers = auth_headers(client, caregiver_user.email)

    capabilities = client.get(f"{API}/ai/predictors", headers=headers)
    assert capabilities.status_code == 200, capabilities.text
    body = capabilities.json()
    assert body["any_ready"] is any(p["is_ready"] for p in body["predictors"])

    # The two problems with no model must always be unavailable.
    by_name = {p["name"]: p for p in body["predictors"]}
    assert by_name["activity_recognition"]["is_ready"] is False
    assert by_name["anomaly_detection"]["is_ready"] is False

    fall_ready = by_name["fall_detection"]["is_ready"]
    attempt = client.post(
        f"{API}/ai/predictors/fall_detection/check", headers=headers
    )

    if fall_ready:
        assert attempt.status_code == 200, attempt.text
        result = attempt.json()
        # A capability check must never look like a real reading of a person.
        assert result["is_simulated"] is True
        assert result["source"] == "imported_dataset"
    else:
        assert attempt.status_code == 503
        assert attempt.json()["error"]["code"] == "MODEL_NOT_LOADED"


def test_workflow_health_check_reports_a_connected_database(
    client: TestClient,
) -> None:
    """The health endpoint Docker and the frontend rely on must actually work."""
    response = client.get("/health")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "connected"
