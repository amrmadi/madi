"""Tests for care plans, medications, reminders, and check-ins."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.models.identity import ElderlyProfile, User
from backend.tests.conftest import auth_headers


# ---------------------------------------------------------------------------
# Care plans
# ---------------------------------------------------------------------------


def test_create_care_plan(client: TestClient, caregiver_user: User, elderly_profile: ElderlyProfile) -> None:
    headers = auth_headers(client, caregiver_user.email)

    response = client.post(
        f"/api/v1/elderly-profiles/{elderly_profile.id}/care-plans",
        headers=headers,
        json={"title": "Morning routine", "summary": "Help with breakfast", "status": "active"},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["title"] == "Morning routine"
    assert body["status"] == "active"
    assert body["elderly_profile_id"] == elderly_profile.id


def test_create_care_plan_rejects_end_before_start(
    client: TestClient, caregiver_user: User, elderly_profile: ElderlyProfile
) -> None:
    headers = auth_headers(client, caregiver_user.email)

    response = client.post(
        f"/api/v1/elderly-profiles/{elderly_profile.id}/care-plans",
        headers=headers,
        json={
            "title": "Backwards plan",
            "start_date": "2026-06-01",
            "end_date": "2026-05-01",
        },
    )

    assert response.status_code == 422


def test_create_care_plan_rejects_unknown_status(
    client: TestClient, caregiver_user: User, elderly_profile: ElderlyProfile
) -> None:
    headers = auth_headers(client, caregiver_user.email)

    response = client.post(
        f"/api/v1/elderly-profiles/{elderly_profile.id}/care-plans",
        headers=headers,
        json={"title": "Bad status", "status": "invented_status"},
    )

    assert response.status_code == 422


def test_list_care_plans_returns_only_that_residents_plans(
    client: TestClient,
    db_session: Session,
    caregiver_user: User,
    elderly_profile: ElderlyProfile,
) -> None:
    headers = auth_headers(client, caregiver_user.email)
    client.post(
        f"/api/v1/elderly-profiles/{elderly_profile.id}/care-plans",
        headers=headers,
        json={"title": "Plan A"},
    )

    response = client.get(
        f"/api/v1/elderly-profiles/{elderly_profile.id}/care-plans", headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "Plan A"


def test_update_care_plan(
    client: TestClient, caregiver_user: User, sample_care_plan
) -> None:
    headers = auth_headers(client, caregiver_user.email)

    response = client.patch(
        f"/api/v1/care-plans/{sample_care_plan.id}",
        headers=headers,
        json={"title": "Updated plan", "status": "paused"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["title"] == "Updated plan"
    assert response.json()["status"] == "paused"


def test_update_care_plan_validates_dates_against_stored_start(
    client: TestClient, caregiver_user: User, elderly_profile: ElderlyProfile
) -> None:
    """Setting an end date earlier than the *stored* start date must fail."""
    headers = auth_headers(client, caregiver_user.email)
    created = client.post(
        f"/api/v1/elderly-profiles/{elderly_profile.id}/care-plans",
        headers=headers,
        json={"title": "Dated plan", "start_date": "2026-06-01"},
    )
    plan_id = created.json()["id"]

    response = client.patch(
        f"/api/v1/care-plans/{plan_id}", headers=headers, json={"end_date": "2026-05-01"}
    )

    assert response.status_code == 422


def test_read_care_plan_denied_for_unassigned_caregiver(
    client: TestClient, other_caregiver: User, sample_care_plan
) -> None:
    headers = auth_headers(client, other_caregiver.email)

    response = client.get(f"/api/v1/care-plans/{sample_care_plan.id}", headers=headers)

    assert response.status_code == 403


def test_read_missing_care_plan_returns_404(
    client: TestClient, caregiver_user: User
) -> None:
    headers = auth_headers(client, caregiver_user.email)

    response = client.get("/api/v1/care-plans/999999", headers=headers)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CARE_PLAN_NOT_FOUND"


def test_delete_care_plan(client: TestClient, caregiver_user: User, sample_care_plan) -> None:
    headers = auth_headers(client, caregiver_user.email)

    response = client.delete(f"/api/v1/care-plans/{sample_care_plan.id}", headers=headers)
    assert response.status_code == 200

    assert client.get(f"/api/v1/care-plans/{sample_care_plan.id}", headers=headers).status_code == 404


# ---------------------------------------------------------------------------
# Medications
# ---------------------------------------------------------------------------


def test_create_medication_schedule(
    client: TestClient, caregiver_user: User, elderly_profile: ElderlyProfile
) -> None:
    headers = auth_headers(client, caregiver_user.email)

    response = client.post(
        f"/api/v1/elderly-profiles/{elderly_profile.id}/medications",
        headers=headers,
        json={
            "medication_name": "Example tablet",
            "dosage_text": "1 tablet",
            "time_of_day": "08:00",
            "recurrence": "daily",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["medication_name"] == "Example tablet"
    assert body["time_of_day"] == "08:00"


def test_create_medication_rejects_bad_time_format(
    client: TestClient, caregiver_user: User, elderly_profile: ElderlyProfile
) -> None:
    headers = auth_headers(client, caregiver_user.email)

    response = client.post(
        f"/api/v1/elderly-profiles/{elderly_profile.id}/medications",
        headers=headers,
        json={"medication_name": "Example", "time_of_day": "8am"},
    )

    assert response.status_code == 422


def test_create_medication_rejects_impossible_hour(
    client: TestClient, caregiver_user: User, elderly_profile: ElderlyProfile
) -> None:
    headers = auth_headers(client, caregiver_user.email)

    response = client.post(
        f"/api/v1/elderly-profiles/{elderly_profile.id}/medications",
        headers=headers,
        json={"medication_name": "Example", "time_of_day": "25:00"},
    )

    assert response.status_code == 422


def test_list_medications_excludes_inactive_by_default(
    client: TestClient,
    db_session: Session,
    caregiver_user: User,
    elderly_profile: ElderlyProfile,
) -> None:
    from backend.app.models.care import MedicationSchedule

    db_session.add(
        MedicationSchedule(
            elderly_profile_id=elderly_profile.id,
            medication_name="Stopped medication",
            is_active=False,
        )
    )
    db_session.commit()

    headers = auth_headers(client, caregiver_user.email)
    response = client.get(
        f"/api/v1/elderly-profiles/{elderly_profile.id}/medications", headers=headers
    )

    assert response.status_code == 200
    assert response.json() == []


# ---------------------------------------------------------------------------
# Reminders
# ---------------------------------------------------------------------------


def test_create_daily_reminder(
    client: TestClient, caregiver_user: User, elderly_profile: ElderlyProfile
) -> None:
    headers = auth_headers(client, caregiver_user.email)

    response = client.post(
        f"/api/v1/elderly-profiles/{elderly_profile.id}/reminders",
        headers=headers,
        json={"title": "Drink water", "time_of_day": "14:00", "recurrence": "daily"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["title"] == "Drink water"


def test_weekly_reminder_requires_day_of_week(
    client: TestClient, caregiver_user: User, elderly_profile: ElderlyProfile
) -> None:
    """A weekly reminder with no weekday is ambiguous, so it is rejected."""
    headers = auth_headers(client, caregiver_user.email)

    response = client.post(
        f"/api/v1/elderly-profiles/{elderly_profile.id}/reminders",
        headers=headers,
        json={"title": "Weekly walk", "recurrence": "weekly"},
    )

    assert response.status_code == 422


def test_weekly_reminder_accepts_valid_day(
    client: TestClient, caregiver_user: User, elderly_profile: ElderlyProfile
) -> None:
    headers = auth_headers(client, caregiver_user.email)

    response = client.post(
        f"/api/v1/elderly-profiles/{elderly_profile.id}/reminders",
        headers=headers,
        json={"title": "Weekly walk", "recurrence": "weekly", "day_of_week": 3},
    )

    assert response.status_code == 201
    assert response.json()["day_of_week"] == 3


def test_reminder_day_of_week_out_of_range_is_rejected(
    client: TestClient, caregiver_user: User, elderly_profile: ElderlyProfile
) -> None:
    headers = auth_headers(client, caregiver_user.email)

    response = client.post(
        f"/api/v1/elderly-profiles/{elderly_profile.id}/reminders",
        headers=headers,
        json={"title": "Bad day", "recurrence": "weekly", "day_of_week": 9},
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Check-ins
# ---------------------------------------------------------------------------


def test_record_checkin_defaults_performed_at(
    client: TestClient, caregiver_user: User, elderly_profile: ElderlyProfile
) -> None:
    """A completed check-in with no timestamp defaults to 'now'."""
    headers = auth_headers(client, caregiver_user.email)

    response = client.post(
        f"/api/v1/elderly-profiles/{elderly_profile.id}/checkins",
        headers=headers,
        json={"checkin_type": "wellbeing", "status": "taken", "wellbeing_note": "Ate breakfast"},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["performed_at"] is not None
    assert body["wellbeing_note"] == "Ate breakfast"
    # The API records who submitted it.
    assert body["recorded_by_user_id"] == caregiver_user.id


def test_list_checkins_is_newest_first(
    client: TestClient,
    db_session: Session,
    caregiver_user: User,
    elderly_profile: ElderlyProfile,
) -> None:
    from backend.app.models.care import Checkin

    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            Checkin(
                elderly_profile_id=elderly_profile.id,
                checkin_type="manual",
                status="taken",
                performed_at=now - timedelta(days=2),
            ),
            Checkin(
                elderly_profile_id=elderly_profile.id,
                checkin_type="manual",
                status="taken",
                performed_at=now,
            ),
        ]
    )
    db_session.commit()

    headers = auth_headers(client, caregiver_user.email)
    response = client.get(
        f"/api/v1/elderly-profiles/{elderly_profile.id}/checkins", headers=headers
    )

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 2
    assert items[0]["performed_at"] > items[1]["performed_at"]


def test_checkin_referencing_another_residents_schedule_is_rejected(
    client: TestClient,
    db_session: Session,
    caregiver_user: User,
    elderly_profile: ElderlyProfile,
) -> None:
    """Prevents linking a check-in to a schedule that belongs to someone else."""
    from backend.app.models.care import CheckinSchedule
    from backend.app.models.enums import AssignmentRole
    from backend.app.models.identity import CaregiverAssignment

    other_profile = ElderlyProfile(display_name="Other Resident", is_active=True)
    db_session.add(other_profile)
    db_session.flush()
    foreign_schedule = CheckinSchedule(
        elderly_profile_id=other_profile.id, title="Their schedule", checkin_type="manual"
    )
    db_session.add(foreign_schedule)
    db_session.commit()

    headers = auth_headers(client, caregiver_user.email)
    response = client.post(
        f"/api/v1/elderly-profiles/{elderly_profile.id}/checkins",
        headers=headers,
        json={"checkin_type": "manual", "checkin_schedule_id": foreign_schedule.id},
    )

    assert response.status_code == 422


def test_create_checkin_schedule(
    client: TestClient, caregiver_user: User, elderly_profile: ElderlyProfile
) -> None:
    headers = auth_headers(client, caregiver_user.email)

    response = client.post(
        f"/api/v1/elderly-profiles/{elderly_profile.id}/checkin-schedules",
        headers=headers,
        json={"title": "Daily welfare call", "checkin_type": "wellbeing", "time_of_day": "09:00"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["title"] == "Daily welfare call"
