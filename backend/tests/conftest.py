"""Shared pytest fixtures for the backend test suite.

How the tests run without PostgreSQL or Docker
---------------------------------------------
FastAPI talks to the database through the `get_db` dependency. In these tests
we override that dependency so every request uses a **throwaway in-memory SQLite
database** created fresh for each test.

Trade-offs, stated honestly:
    * Tests are fast and need no server, so they can run anywhere.
    * SQLite is not PostgreSQL, so PostgreSQL-specific behaviour (some types,
      concurrency, `ON DELETE` semantics) is NOT covered by these tests. That
      validation happens separately against a real PostgreSQL instance via
      Docker Compose.

Each test gets its own database, so tests cannot leak state into each other.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.core.security import hash_password
from backend.app.db.base import Base, get_db
from backend.app.main import app
from backend.app.models.enums import AssignmentRole, CarePlanStatus, UserRole, UserStatus
from backend.app.models.identity import CaregiverAssignment, ElderlyProfile, User


@pytest.fixture()
def db_engine():
    """Create a fresh in-memory SQLite engine for a single test.

    `StaticPool` plus `check_same_thread=False` keeps the *same* in-memory
    database alive across connections — otherwise each connection would get its
    own empty database and nothing would persist.
    """
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture()
def db_session(db_engine) -> Iterator[Session]:
    """A session bound to the test database."""
    factory = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db_engine) -> Iterator[TestClient]:
    """A TestClient whose requests use the test database instead of `.env`'s URL."""
    factory = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)

    def override_get_db() -> Iterator[Session]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# User helpers
# ---------------------------------------------------------------------------

DEFAULT_PASSWORD = "test-password-123"


def create_user(
    db: Session,
    *,
    email: str,
    role: UserRole = UserRole.CAREGIVER,
    display_name: str | None = None,
    password: str = DEFAULT_PASSWORD,
    is_active: bool = True,
) -> User:
    """Insert a user directly, bypassing the API."""
    user = User(
        email=email.lower(),
        display_name=display_name or email.split("@")[0],
        role=role.value,
        status=UserStatus.ACTIVE.value,
        password_hash=hash_password(password),
        is_active=is_active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def auth_headers(client: TestClient, email: str, password: str = DEFAULT_PASSWORD) -> dict[str, str]:
    """Sign in through the real login endpoint and return an auth header."""
    response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


# ---------------------------------------------------------------------------
# Fixtures describing a realistic scenario
# ---------------------------------------------------------------------------


@pytest.fixture()
def admin_user(db_session: Session) -> User:
    return create_user(
        db_session, email="admin@example.com", role=UserRole.ADMIN, display_name="Admin"
    )


@pytest.fixture()
def caregiver_user(db_session: Session) -> User:
    """The caregiver who IS assigned to the sample resident."""
    return create_user(
        db_session, email="caregiver@example.com", display_name="Assigned Caregiver"
    )


@pytest.fixture()
def other_caregiver(db_session: Session) -> User:
    """A caregiver who is NOT assigned to the sample resident.

    This user exists to prove that access restrictions actually work.
    """
    return create_user(
        db_session, email="outsider@example.com", display_name="Unassigned Caregiver"
    )


@pytest.fixture()
def elderly_profile(db_session: Session, caregiver_user: User) -> ElderlyProfile:
    """A sample resident, assigned to `caregiver_user` only."""
    profile = ElderlyProfile(display_name="Sample Resident", room_label="A-101", is_active=True)
    db_session.add(profile)
    db_session.commit()
    db_session.refresh(profile)

    db_session.add(
        CaregiverAssignment(
            caregiver_id=caregiver_user.id,
            elderly_profile_id=profile.id,
            assignment_role=AssignmentRole.PRIMARY.value,
            is_active=True,
        )
    )
    db_session.commit()
    db_session.refresh(profile)
    return profile


@pytest.fixture()
def sample_care_plan(db_session: Session, elderly_profile: ElderlyProfile) -> object:
    """A minimal care plan belonging to the sample resident."""
    from backend.app.models.care import CarePlan

    plan = CarePlan(
        elderly_profile_id=elderly_profile.id,
        title="Morning routine",
        status=CarePlanStatus.ACTIVE.value,
    )
    db_session.add(plan)
    db_session.commit()
    db_session.refresh(plan)
    return plan
