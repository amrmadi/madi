"""Tests for caregiver access restrictions and role-based authorization.

These are the most important tests in the suite. The whole point of the
Phase 3 authorization work is that **a caregiver cannot access the records of a
resident they are not assigned to** — and that the rule is enforced by the
server, not merely hidden in the UI.

Each test states the rule it protects in its name.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.models.enums import UserRole
from backend.app.models.identity import CaregiverAssignment, ElderlyProfile, User
from backend.tests.conftest import DEFAULT_PASSWORD, auth_headers, create_user


# ---------------------------------------------------------------------------
# Reading a single profile
# ---------------------------------------------------------------------------


def test_assigned_caregiver_can_read_their_resident(
    client: TestClient,
    caregiver_user: User,
    elderly_profile: ElderlyProfile,
) -> None:
    headers = auth_headers(client, caregiver_user.email)

    response = client.get(f"/api/v1/elderly-profiles/{elderly_profile.id}", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["id"] == elderly_profile.id


def test_unassigned_caregiver_is_forbidden_from_reading_a_resident(
    client: TestClient,
    other_caregiver: User,
    elderly_profile: ElderlyProfile,
) -> None:
    """The core access rule: no assignment means no access."""
    headers = auth_headers(client, other_caregiver.email)

    response = client.get(f"/api/v1/elderly-profiles/{elderly_profile.id}", headers=headers)

    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"


def test_reading_a_nonexistent_resident_returns_404_not_403(
    client: TestClient, caregiver_user: User
) -> None:
    """A missing row and a forbidden row are different, and both are reported correctly."""
    headers = auth_headers(client, caregiver_user.email)

    response = client.get("/api/v1/elderly-profiles/999999", headers=headers)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ELDERLY_PROFILE_NOT_FOUND"


def test_anonymous_cannot_read_a_resident(
    client: TestClient, elderly_profile: ElderlyProfile
) -> None:
    response = client.get(f"/api/v1/elderly-profiles/{elderly_profile.id}")

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Listing scoping
# ---------------------------------------------------------------------------


def test_list_only_returns_assigned_residents(
    client: TestClient,
    db_session: Session,
    caregiver_user: User,
    elderly_profile: ElderlyProfile,
) -> None:
    """A caregiver's list must not leak residents they are not assigned to."""
    # A second resident that belongs to somebody else entirely.
    stranger_profile = ElderlyProfile(display_name="Someone Else", is_active=True)
    db_session.add(stranger_profile)
    db_session.commit()

    headers = auth_headers(client, caregiver_user.email)
    response = client.get("/api/v1/elderly-profiles", headers=headers)

    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["items"]]
    assert elderly_profile.id in ids
    assert stranger_profile.id not in ids


def test_list_is_empty_for_caregiver_with_no_assignments(
    client: TestClient, other_caregiver: User, elderly_profile: ElderlyProfile
) -> None:
    """No assignments returns an empty page, never everybody's residents."""
    headers = auth_headers(client, other_caregiver.email)

    response = client.get("/api/v1/elderly-profiles", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0


def test_admin_sees_all_residents(
    client: TestClient,
    db_session: Session,
    admin_user: User,
    elderly_profile: ElderlyProfile,
) -> None:
    """Administrators intentionally bypass caregiver scoping."""
    extra = ElderlyProfile(display_name="Another Resident", is_active=True)
    db_session.add(extra)
    db_session.commit()

    headers = auth_headers(client, admin_user.email)
    response = client.get("/api/v1/elderly-profiles", headers=headers)

    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["items"]]
    assert {elderly_profile.id, extra.id}.issubset(set(ids))


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------


def test_unassigned_caregiver_cannot_update_a_resident(
    client: TestClient,
    other_caregiver: User,
    elderly_profile: ElderlyProfile,
) -> None:
    headers = auth_headers(client, other_caregiver.email)

    response = client.patch(
        f"/api/v1/elderly-profiles/{elderly_profile.id}",
        headers=headers,
        json={"display_name": "Hacked Name"},
    )

    assert response.status_code == 403


def test_assigned_caregiver_can_update_their_resident(
    client: TestClient,
    caregiver_user: User,
    elderly_profile: ElderlyProfile,
) -> None:
    headers = auth_headers(client, caregiver_user.email)

    response = client.patch(
        f"/api/v1/elderly-profiles/{elderly_profile.id}",
        headers=headers,
        json={"display_name": "Updated Name", "room_label": "B-202"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["display_name"] == "Updated Name"
    assert response.json()["room_label"] == "B-202"


def test_unassigned_caregiver_cannot_read_care_plans(
    client: TestClient,
    other_caregiver: User,
    elderly_profile: ElderlyProfile,
) -> None:
    """Scoping must apply to nested resources too, not just the profile itself."""
    headers = auth_headers(client, other_caregiver.email)

    response = client.get(
        f"/api/v1/elderly-profiles/{elderly_profile.id}/care-plans", headers=headers
    )

    assert response.status_code == 403


def test_unassigned_caregiver_cannot_read_medications(
    client: TestClient,
    other_caregiver: User,
    elderly_profile: ElderlyProfile,
) -> None:
    headers = auth_headers(client, other_caregiver.email)

    response = client.get(
        f"/api/v1/elderly-profiles/{elderly_profile.id}/medications", headers=headers
    )

    assert response.status_code == 403


def test_unassigned_caregiver_cannot_read_reminders(
    client: TestClient,
    other_caregiver: User,
    elderly_profile: ElderlyProfile,
) -> None:
    headers = auth_headers(client, other_caregiver.email)

    response = client.get(
        f"/api/v1/elderly-profiles/{elderly_profile.id}/reminders", headers=headers
    )

    assert response.status_code == 403


def test_unassigned_caregiver_cannot_read_checkins(
    client: TestClient,
    other_caregiver: User,
    elderly_profile: ElderlyProfile,
) -> None:
    headers = auth_headers(client, other_caregiver.email)

    response = client.get(
        f"/api/v1/elderly-profiles/{elderly_profile.id}/checkins", headers=headers
    )

    assert response.status_code == 403


def test_unassigned_caregiver_cannot_read_activity_history(
    client: TestClient,
    other_caregiver: User,
    elderly_profile: ElderlyProfile,
) -> None:
    headers = auth_headers(client, other_caregiver.email)

    response = client.get(
        f"/api/v1/elderly-profiles/{elderly_profile.id}/activity-events", headers=headers
    )

    assert response.status_code == 403


def test_unassigned_caregiver_cannot_read_resident_alerts(
    client: TestClient,
    other_caregiver: User,
    elderly_profile: ElderlyProfile,
) -> None:
    headers = auth_headers(client, other_caregiver.email)

    response = client.get(
        f"/api/v1/elderly-profiles/{elderly_profile.id}/alerts", headers=headers
    )

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Deactivating an assignment revokes access
# ---------------------------------------------------------------------------


def test_deactivating_assignment_revokes_access(
    client: TestClient,
    db_session: Session,
    caregiver_user: User,
    elderly_profile: ElderlyProfile,
) -> None:
    """Access follows the assignment's `is_active` flag, not just its existence."""
    headers = auth_headers(client, caregiver_user.email)
    url = f"/api/v1/elderly-profiles/{elderly_profile.id}"

    assert client.get(url, headers=headers).status_code == 200

    assignment = (
        db_session.query(CaregiverAssignment)
        .filter_by(caregiver_id=caregiver_user.id, elderly_profile_id=elderly_profile.id)
        .one()
    )
    assignment.is_active = False
    db_session.commit()

    assert client.get(url, headers=headers).status_code == 403


# ---------------------------------------------------------------------------
# Role-based authorization for assignments
# ---------------------------------------------------------------------------


def test_secondary_caregiver_cannot_assign_other_caregivers(
    client: TestClient,
    db_session: Session,
    other_caregiver: User,
    elderly_profile: ElderlyProfile,
) -> None:
    """Only an admin or the *primary* caregiver may manage assignments."""
    from backend.app.models.enums import AssignmentRole

    # Give the outsider a SECONDARY assignment so they can see the resident.
    db_session.add(
        CaregiverAssignment(
            caregiver_id=other_caregiver.id,
            elderly_profile_id=elderly_profile.id,
            assignment_role=AssignmentRole.SECONDARY.value,
            is_active=True,
        )
    )
    db_session.commit()

    newcomer = create_user(db_session, email="newcomer@example.com")
    headers = auth_headers(client, other_caregiver.email)

    response = client.post(
        f"/api/v1/elderly-profiles/{elderly_profile.id}/caregivers",
        headers=headers,
        json={"caregiver_id": newcomer.id, "assignment_role": "secondary"},
    )

    assert response.status_code == 403


def test_primary_caregiver_can_assign_another_caregiver(
    client: TestClient,
    db_session: Session,
    caregiver_user: User,
    elderly_profile: ElderlyProfile,
) -> None:
    newcomer = create_user(db_session, email="helper@example.com")
    headers = auth_headers(client, caregiver_user.email)

    response = client.post(
        f"/api/v1/elderly-profiles/{elderly_profile.id}/caregivers",
        headers=headers,
        json={"caregiver_id": newcomer.id, "assignment_role": "secondary"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["caregiver_id"] == newcomer.id


def test_assigning_duplicate_caregiver_conflicts(
    client: TestClient,
    caregiver_user: User,
    elderly_profile: ElderlyProfile,
) -> None:
    """`caregiver_user` already has an assignment on this profile."""
    headers = auth_headers(client, caregiver_user.email)

    response = client.post(
        f"/api/v1/elderly-profiles/{elderly_profile.id}/caregivers",
        headers=headers,
        json={"caregiver_id": caregiver_user.id, "assignment_role": "secondary"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ASSIGNMENT_EXISTS"


def test_assigning_unknown_caregiver_returns_404(
    client: TestClient,
    caregiver_user: User,
    elderly_profile: ElderlyProfile,
) -> None:
    headers = auth_headers(client, caregiver_user.email)

    response = client.post(
        f"/api/v1/elderly-profiles/{elderly_profile.id}/caregivers",
        headers=headers,
        json={"caregiver_id": 999999, "assignment_role": "secondary"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "USER_NOT_FOUND"


def test_analyst_role_cannot_access_individual_care_records(
    client: TestClient, db_session: Session, elderly_profile: ElderlyProfile
) -> None:
    """Analysts are for aggregate reporting only, never raw personal care data."""
    analyst = create_user(db_session, email="analyst@example.com", role=UserRole.ANALYST)
    headers = auth_headers(client, analyst.email)

    response = client.get(f"/api/v1/elderly-profiles/{elderly_profile.id}", headers=headers)

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Creating a profile auto-assigns the creator
# ---------------------------------------------------------------------------


def test_creating_a_profile_assigns_the_creating_caregiver(
    client: TestClient, caregiver_user: User
) -> None:
    """A caregiver must be able to access the resident they just created."""
    headers = auth_headers(client, caregiver_user.email)

    created = client.post(
        "/api/v1/elderly-profiles",
        headers=headers,
        json={"display_name": "Fresh Resident"},
    )
    assert created.status_code == 201, created.text
    profile_id = created.json()["id"]

    # Immediately readable, because the creator was auto-assigned.
    assert client.get(f"/api/v1/elderly-profiles/{profile_id}", headers=headers).status_code == 200

    # And it appears in their list.
    listing = client.get("/api/v1/elderly-profiles", headers=headers).json()
    assert profile_id in [item["id"] for item in listing["items"]]
