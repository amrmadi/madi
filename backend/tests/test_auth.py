"""Tests for registration, login, and token handling."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.models.identity import User
from backend.tests.conftest import DEFAULT_PASSWORD, auth_headers, create_user

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
ME = "/api/v1/auth/me"


def test_register_creates_caregiver_and_returns_token(client: TestClient) -> None:
    response = client.post(
        REGISTER,
        json={
            "email": "new.caregiver@example.com",
            "display_name": "New Caregiver",
            "password": "a-good-password-1",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["email"] == "new.caregiver@example.com"
    # Self-registration must never grant elevated privileges.
    assert body["user"]["role"] == "caregiver"


def test_register_never_returns_password_hash(client: TestClient) -> None:
    response = client.post(
        REGISTER,
        json={
            "email": "nohash@example.com",
            "display_name": "No Hash",
            "password": "a-good-password-1",
        },
    )

    assert response.status_code == 201
    assert "password" not in response.text.lower()
    assert "password_hash" not in response.text


def test_password_is_stored_hashed_not_plaintext(
    client: TestClient, db_session: Session
) -> None:
    """The database must never contain the plain password."""
    password = "a-good-password-1"
    client.post(
        REGISTER,
        json={"email": "hashcheck@example.com", "display_name": "Hash", "password": password},
    )

    user = db_session.query(User).filter_by(email="hashcheck@example.com").one()
    assert user.password_hash is not None
    assert user.password_hash != password
    assert user.password_hash.startswith("$argon2")


def test_register_rejects_duplicate_email(client: TestClient) -> None:
    payload = {
        "email": "dupe@example.com",
        "display_name": "Dupe",
        "password": "a-good-password-1",
    }
    assert client.post(REGISTER, json=payload).status_code == 201

    second = client.post(REGISTER, json=payload)

    assert second.status_code == 409
    assert second.json()["error"]["code"] == "EMAIL_ALREADY_REGISTERED"


def test_register_rejects_short_password(client: TestClient) -> None:
    response = client.post(
        REGISTER,
        json={"email": "short@example.com", "display_name": "Short", "password": "abc"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_register_rejects_common_password(client: TestClient) -> None:
    response = client.post(
        REGISTER,
        json={"email": "weak@example.com", "display_name": "Weak", "password": "password"},
    )

    assert response.status_code == 422


def test_register_rejects_invalid_email(client: TestClient) -> None:
    response = client.post(
        REGISTER,
        json={"email": "not-an-email", "display_name": "Bad", "password": "a-good-password-1"},
    )

    assert response.status_code == 422


def test_login_succeeds_with_correct_credentials(
    client: TestClient, db_session: Session
) -> None:
    create_user(db_session, email="login@example.com")

    response = client.post(
        LOGIN, json={"email": "login@example.com", "password": DEFAULT_PASSWORD}
    )

    assert response.status_code == 200, response.text
    assert response.json()["access_token"]


def test_login_is_case_insensitive_for_email(
    client: TestClient, db_session: Session
) -> None:
    create_user(db_session, email="mixedcase@example.com")

    response = client.post(
        LOGIN, json={"email": "MixedCase@Example.com", "password": DEFAULT_PASSWORD}
    )

    assert response.status_code == 200


def test_login_fails_with_wrong_password(client: TestClient, db_session: Session) -> None:
    create_user(db_session, email="wrongpw@example.com")

    response = client.post(
        LOGIN, json={"email": "wrongpw@example.com", "password": "definitely-wrong"}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_login_unknown_email_gives_same_error_as_wrong_password(
    client: TestClient,
) -> None:
    """Prevents user enumeration: an attacker cannot tell if an email exists."""
    response = client.post(
        LOGIN, json={"email": "ghost@example.com", "password": "whatever-123"}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_login_fails_for_disabled_account(client: TestClient, db_session: Session) -> None:
    user = create_user(db_session, email="disabled@example.com")
    user.is_active = False
    db_session.commit()

    response = client.post(
        LOGIN, json={"email": "disabled@example.com", "password": DEFAULT_PASSWORD}
    )

    assert response.status_code == 401


def test_me_returns_current_user(client: TestClient, db_session: Session) -> None:
    create_user(db_session, email="me@example.com", display_name="Me")
    headers = auth_headers(client, "me@example.com")

    response = client.get(ME, headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "me@example.com"
    assert body["display_name"] == "Me"


def test_me_requires_authentication(client: TestClient) -> None:
    response = client.get(ME)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"


def test_me_rejects_garbage_token(client: TestClient) -> None:
    response = client.get(ME, headers={"Authorization": "Bearer not.a.real.token"})

    assert response.status_code == 401


def test_login_updates_last_login_timestamp(
    client: TestClient, db_session: Session
) -> None:
    user = create_user(db_session, email="timestamp@example.com")
    assert user.last_login_at is None

    client.post(LOGIN, json={"email": "timestamp@example.com", "password": DEFAULT_PASSWORD})

    db_session.refresh(user)
    assert user.last_login_at is not None
