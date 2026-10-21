"""Tests for elderly profile CRUD, validation, and soft deletion."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.models.identity import ElderlyProfile, User
from backend.tests.conftest import auth_headers


def test_create_profile_returns_201_and_the_created_row(
    client: TestClient, caregiver_user: User
) -> None:
    headers = auth_headers(client, caregiver_user.email)

    response = client.post(
        "/api/v1/elderly-profiles",
        headers=headers,
        json={"display_name": "Margaret Example", "room_label": "C-3", "notes": "Prefers tea"},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["display_name"] == "Margaret Example"
    assert body["is_active"] is True
    assert "id" in body


def test_create_profile_rejects_blank_name(
    client: TestClient, caregiver_user: User
) -> None:
    headers = auth_headers(client, caregiver_user.email)

    response = client.post(
        "/api/v1/elderly-profiles", headers=headers, json={"display_name": "   "}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_create_profile_rejects_future_date_of_birth(
    client: TestClient, caregiver_user: User
) -> None:
    headers = auth_headers(client, caregiver_user.email)
    tomorrow = (date.today() + timedelta(days=1)).isoformat()

    response = client.post(
        "/api/v1/elderly-profiles",
        headers=headers,
        json={"display_name": "Future Person", "date_of_birth": tomorrow},
    )

    assert response.status_code == 422


def test_validation_error_details_name_the_offending_field(
    client: TestClient, caregiver_user: User
) -> None:
    """The frontend needs to know *which* field failed so it can highlight it."""
    headers = auth_headers(client, caregiver_user.email)

    response = client.post(
        "/api/v1/elderly-profiles", headers=headers, json={"display_name": ""}
    )

    assert response.status_code == 422
    details = response.json()["error"]["details"]
    assert "fields" in details
    assert any(f["field"] == "display_name" for f in details["fields"])


def test_patch_only_changes_provided_fields(
    client: TestClient, caregiver_user: User, elderly_profile: ElderlyProfile
) -> None:
    headers = auth_headers(client, caregiver_user.email)

    response = client.patch(
        f"/api/v1/elderly-profiles/{elderly_profile.id}",
        headers=headers,
        json={"room_label": "D-9"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["room_label"] == "D-9"
    # Untouched fields keep their original values.
    assert body["display_name"] == elderly_profile.display_name


def test_delete_is_a_soft_delete(
    client: TestClient,
    db_session: Session,
    caregiver_user: User,
    elderly_profile: ElderlyProfile,
) -> None:
    """The row must survive so historical events and alerts remain valid."""
    headers = auth_headers(client, caregiver_user.email)

    response = client.delete(f"/api/v1/elderly-profiles/{elderly_profile.id}", headers=headers)
    assert response.status_code == 200

    # The request ran in its own database session, so this session still holds
    # a cached copy of the profile from before the delete. Expire it so the
    # next attribute access re-reads the row from the database rather than
    # returning a stale in-memory value.
    db_session.expire_all()

    # Still present in the database...
    still_there = db_session.get(ElderlyProfile, elderly_profile.id)
    assert still_there is not None
    # ...but marked inactive.
    assert still_there.is_active is False


def test_deactivated_profile_is_hidden_from_default_list(
    client: TestClient,
    db_session: Session,
    caregiver_user: User,
    elderly_profile: ElderlyProfile,
) -> None:
    headers = auth_headers(client, caregiver_user.email)
    client.delete(f"/api/v1/elderly-profiles/{elderly_profile.id}", headers=headers)

    response = client.get("/api/v1/elderly-profiles", headers=headers)

    assert response.status_code == 200
    assert elderly_profile.id not in [i["id"] for i in response.json()["items"]]


def test_inactive_profiles_can_be_included_on_request(
    client: TestClient,
    db_session: Session,
    caregiver_user: User,
    elderly_profile: ElderlyProfile,
) -> None:
    headers = auth_headers(client, caregiver_user.email)
    client.delete(f"/api/v1/elderly-profiles/{elderly_profile.id}", headers=headers)

    response = client.get(
        "/api/v1/elderly-profiles?include_inactive=true", headers=headers
    )

    assert response.status_code == 200
    assert elderly_profile.id in [i["id"] for i in response.json()["items"]]


def test_secondary_caregiver_cannot_deactivate_a_resident(
    client: TestClient,
    db_session: Session,
    other_caregiver: User,
    elderly_profile: ElderlyProfile,
) -> None:
    """Only the primary caregiver or an admin may deactivate."""
    from backend.app.models.enums import AssignmentRole
    from backend.app.models.identity import CaregiverAssignment

    db_session.add(
        CaregiverAssignment(
            caregiver_id=other_caregiver.id,
            elderly_profile_id=elderly_profile.id,
            assignment_role=AssignmentRole.SECONDARY.value,
            is_active=True,
        )
    )
    db_session.commit()

    headers = auth_headers(client, other_caregiver.email)
    response = client.delete(f"/api/v1/elderly-profiles/{elderly_profile.id}", headers=headers)

    assert response.status_code == 403


def test_pagination_reports_total_and_page_size(
    client: TestClient, db_session: Session, caregiver_user: User
) -> None:
    """Creating several residents should paginate, not dump everything."""
    from backend.app.models.enums import AssignmentRole
    from backend.app.models.identity import CaregiverAssignment

    for index in range(5):
        profile = ElderlyProfile(display_name=f"Resident {index}", is_active=True)
        db_session.add(profile)
        db_session.flush()
        db_session.add(
            CaregiverAssignment(
                caregiver_id=caregiver_user.id,
                elderly_profile_id=profile.id,
                assignment_role=AssignmentRole.PRIMARY.value,
                is_active=True,
            )
        )
    db_session.commit()

    headers = auth_headers(client, caregiver_user.email)
    response = client.get("/api/v1/elderly-profiles?page=1&page_size=2", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 2
    assert body["total"] == 5
    assert body["page"] == 1
    assert body["page_size"] == 2


def test_page_size_above_the_maximum_is_rejected(
    client: TestClient, caregiver_user: User
) -> None:
    headers = auth_headers(client, caregiver_user.email)

    response = client.get("/api/v1/elderly-profiles?page_size=5000", headers=headers)

    assert response.status_code == 422
