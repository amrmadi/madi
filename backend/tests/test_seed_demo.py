"""Tests for the demo seed script.

Why this file exists
--------------------
The seed script produces the credentials the README and the demo walkthrough
tell a person to sign in with. If those credentials cannot actually be used, the
documentation is wrong and every demo fails at the first step.

That is not hypothetical: while verifying the deployment phase we found that the
accounts were created at `@demo.elderlife.local`, and the API validates emails
with pydantic's `EmailStr`, which rejects `.local` as a special-use TLD. Seeding
succeeded, but every login returned 422. These tests exist so that can never
happen silently again.

They also pin the two properties the seed script promises:

* `--reset` removes only rows it created, never a developer's own data;
* re-seeding does not create duplicates.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.core.security import verify_password
from backend.app.models.alerts import Alert
from backend.app.models.identity import User
from backend.app.schemas.auth import UserLogin
from backend.scripts.seed_demo import (
    DEMO_EMAIL_DOMAIN,
    DEMO_PASSWORD,
    reset_demo_data,
)


# ---------------------------------------------------------------------------
# The demo credentials must actually work
# ---------------------------------------------------------------------------


def test_demo_emails_pass_the_apis_own_validation() -> None:
    """The single check that would have caught the login bug immediately.

    The API parses every login body with `UserLogin`, so running the demo
    address through that same model proves the address is acceptable to the API
    rather than merely plausible to a human.
    """
    email = f"caregiver.a@{DEMO_EMAIL_DOMAIN}"

    # Raises pydantic.ValidationError if the domain is not a valid email.
    parsed = UserLogin(email=email, password=DEMO_PASSWORD)

    assert parsed.email == email


def test_demo_domain_is_not_a_reserved_local_tld() -> None:
    """`.local` is special-use and rejected by email validators — keep it out.

    This is a direct guard against reintroducing the original bug.
    """
    assert not DEMO_EMAIL_DOMAIN.endswith(".local")
    assert not DEMO_EMAIL_DOMAIN.endswith(".localhost")
    assert not DEMO_EMAIL_DOMAIN.endswith(".invalid")


def test_demo_password_meets_the_documented_policy() -> None:
    """The shared demo password must satisfy the API's own password rules."""
    assert len(DEMO_PASSWORD) >= 12
    assert any(c.isupper() for c in DEMO_PASSWORD)
    assert any(c.islower() for c in DEMO_PASSWORD)
    assert any(c.isdigit() for c in DEMO_PASSWORD)


def test_every_documented_account_has_a_valid_email() -> None:
    """All four accounts the script prints must be acceptable to the API."""
    for local_part in ("admin", "caregiver.a", "caregiver.b", "resident"):
        parsed = UserLogin(
            email=f"{local_part}@{DEMO_EMAIL_DOMAIN}", password=DEMO_PASSWORD
        )
        assert parsed.email.endswith(f"@{DEMO_EMAIL_DOMAIN}")


# ---------------------------------------------------------------------------
# The seeded account is a working credential
# ---------------------------------------------------------------------------


def test_seeded_user_can_be_found_and_its_password_verified(db_session: Session) -> None:
    """End-to-end on the data itself: the stored hash matches the printed password.

    This runs the real seeding functions against the test database, so a change
    to hashing, the email, or the password is caught here rather than during a
    demo.
    """
    from backend.scripts.seed_demo import create_profiles, create_users, seed_care

    users = create_users(db_session)
    profiles = create_profiles(db_session, users)
    seed_care(db_session, users, profiles)
    db_session.flush()

    admin = db_session.execute(
        select(User).where(User.email == f"admin@{DEMO_EMAIL_DOMAIN}")
    ).scalar_one()

    assert admin.is_active is True
    assert verify_password(DEMO_PASSWORD, admin.password_hash) is True
    # A wrong password must not verify — otherwise the check above proves nothing.
    assert verify_password("NotThePassword!23", admin.password_hash) is False


# ---------------------------------------------------------------------------
# Reset safety and idempotency
# ---------------------------------------------------------------------------


def test_reset_removes_only_demo_rows(db_session: Session) -> None:
    """A developer's own account must survive `--reset`."""
    from backend.scripts.seed_demo import create_profiles, create_users, seed_care

    users = create_users(db_session)
    profiles = create_profiles(db_session, users)
    seed_care(db_session, users, profiles)

    real = User(
        email="real.person@hospital.example",
        display_name="A Real User",
        role="caregiver",
        password_hash="x",
        is_active=True,
    )
    db_session.add(real)
    db_session.flush()

    reset_demo_data(db_session)
    db_session.flush()

    remaining = {u.email for u in db_session.execute(select(User)).scalars().all()}

    assert "real.person@hospital.example" in remaining, "reset deleted a non-demo user"
    assert not any(e.endswith(DEMO_EMAIL_DOMAIN) for e in remaining), "demo users were not removed"


def test_seeding_twice_after_reset_creates_no_duplicate_users(db_session: Session) -> None:
    """Re-running the documented demo command must be safe."""
    from backend.scripts.seed_demo import create_profiles, create_users, seed_care

    def seed() -> None:
        users = create_users(db_session)
        profiles = create_profiles(db_session, users)
        seed_care(db_session, users, profiles)
        db_session.flush()

    seed()
    reset_demo_data(db_session)
    db_session.flush()
    seed()

    duplicates = db_session.execute(
        select(User.email, func.count())
        .group_by(User.email)
        .having(func.count() > 1)
    ).all()

    assert duplicates == [], f"duplicate users after re-seed: {duplicates}"


# ---------------------------------------------------------------------------
# Seeded timestamps must be physically sensible
# ---------------------------------------------------------------------------


def test_acknowledged_alert_is_acknowledged_after_it_was_created(
    db_session: Session,
) -> None:
    """An alert cannot be acknowledged before it exists.

    While verifying the deployment against a real PostgreSQL container this
    seed data produced a *negative* median acknowledgement time (~ -0.002 s).
    `created_at` was left to its column default, which is stamped at flush time,
    while `acknowledged_at` was set from a `now` captured earlier in the script.
    The acknowledgement landed two milliseconds before creation.

    The analytics KPI dutifully reported the negative median, which is how a
    nonsense value reached the dashboard. Guard the ordering here.
    """
    from backend.scripts.seed_demo import (
        create_profiles,
        create_users,
        seed_activity_and_alerts,
        seed_care,
    )

    users = create_users(db_session)
    profiles = create_profiles(db_session, users)
    seed_care(db_session, users, profiles)
    seed_activity_and_alerts(db_session, users, profiles)
    db_session.flush()

    alerts = db_session.execute(select(Alert)).scalars().all()
    assert alerts, "seed produced no alerts to check"

    acknowledged = [a for a in alerts if a.acknowledged_at is not None]
    assert acknowledged, "seed produced no acknowledged alert to check"

    for alert in acknowledged:
        assert alert.created_at is not None
        assert alert.acknowledged_at >= alert.created_at, (
            f"alert {alert.id} was acknowledged "
            f"{alert.created_at - alert.acknowledged_at} before it was created"
        )
