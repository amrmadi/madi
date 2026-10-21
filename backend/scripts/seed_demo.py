"""Create synthetic demo data so you can explore the app immediately.

What this script does
---------------------
It inserts a small, entirely **fictional** dataset:

    * 1 admin, 2 caregivers, 1 elderly login account
    * 2 residents, each assigned to a caregiver
    * a care plan, a medication schedule, reminders, check-in schedules
    * some check-ins and activity events
    * a few alerts

Everything it creates is clearly labelled as simulated. In particular, every
`activity_events` row is written with `source = "simulated"`, so demo data can
never be mistaken for a real sensor reading.

Two safety rules are enforced in code
-------------------------------------
1. **It refuses to run in production.** `ENVIRONMENT=production` aborts the
   script before it touches the database.
2. **It refuses to run twice into real data.** If the `users` table already has
   rows, the script stops and tells you, so it cannot pollute a database that
   already contains your own data. Pass `--force` to override, and `--reset`
   to delete only the demo rows it recognises first.

How to run it (from the repository root, with the virtual environment active)
---------------------------------------------------------------------------
    .venv\\Scripts\\python.exe -m backend.scripts.seed_demo

Useful options:
    --reset     delete previously seeded demo rows, then re-seed
    --force     seed even if the database already has users
    --dry-run   show what would happen without writing anything

The demo accounts all use the password below. **These are fake credentials for
local development only** — never reuse them anywhere real.

    Password (all demo accounts): DemoPassw0rd!23
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.security import hash_password
from backend.app.db.base import Base, get_engine, session_scope
from backend.app.models.alerts import Alert
from backend.app.models.care import (
    CarePlan,
    Checkin,
    CheckinSchedule,
    MedicationSchedule,
    Reminder,
)
from backend.app.models.enums import (
    ActivityType,
    AlertStatus,
    AlertType,
    AssignmentRole,
    CarePlanStatus,
    CheckinType,
    EventSource,
    RecurrencePattern,
    ScheduleStatus,
    SeverityLevel,
    UserRole,
    UserStatus,
)
from backend.app.models.events import ActivityEvent
from backend.app.models.identity import CaregiverAssignment, ElderlyProfile, User

logger = logging.getLogger("elderlife.seed")

# Every demo account shares this password. It is deliberately obvious that this
# is a throwaway credential, and it is long enough to satisfy the API policy.
DEMO_PASSWORD = "DemoPassw0rd!23"

# The domain every demo account uses, defined once so the accounts, the reset
# query, and the printed instructions can never drift apart.
#
# Why `.example` and not `.local`: the API validates emails with pydantic's
# `EmailStr`, which rejects `.local` as a special-use TLD — so accounts created
# at `@demo.elderlife.local` could be seeded but never actually log in. `.example`
# is reserved by IANA for documentation, so it is guaranteed never to resolve to
# a real mail server while still being a valid address.
DEMO_EMAIL_DOMAIN = "demo.elderlife.example"

# A stable marker used to find and delete only the rows this script created.
DEMO_NOTE_PREFIX = "[DEMO]"


class SeedRefused(Exception):
    """Raised when seeding would be unsafe."""


def _check_environment(force: bool) -> None:
    """Stop early if it is unsafe to seed."""
    settings = get_settings()
    if settings.is_production:
        raise SeedRefused(
            "Refusing to seed demo data: ENVIRONMENT=production. "
            "Demo seeding is for local development only."
        )
    logger.info("Environment is '%s' — safe to seed.", settings.environment)


def _count_users(session: Session) -> int:
    """How many user rows already exist?"""
    return session.execute(select(func.count()).select_from(User)).scalar_one()


def reset_demo_data(session: Session) -> None:
    """Delete only the rows this script created, identified by a marker.

    Being surgical matters: `--reset` must never wipe real data a developer
    entered by hand, so we only remove rows whose email ends in the demo domain
    and the residents whose notes start with `[DEMO]`.

    Deleting the residents explicitly, child table by child table, is
    deliberate. Some child tables (`medication_schedules`, `reminders`,
    `checkin_schedules`) have a database-level `ON DELETE CASCADE` but no ORM
    relationship on `ElderlyProfile`, and SQLite does not enforce foreign keys
    by default either — so relying on the cascade left orphaned rows behind and
    re-seeding produced duplicates. Removing them explicitly is portable and
    obvious.
    """
    demo_users = (
        session.execute(
            select(User).where(User.email.like(f"%@{DEMO_EMAIL_DOMAIN}"))
        )
        .scalars()
        .all()
    )
    demo_profiles = (
        session.execute(
            select(ElderlyProfile).where(
                ElderlyProfile.notes.like(f"{DEMO_NOTE_PREFIX}%")
            )
        )
        .scalars()
        .all()
    )

    if not demo_users and not demo_profiles:
        logger.info("No demo rows found to reset.")
        return

    profile_ids = [profile.id for profile in demo_profiles]

    if profile_ids:
        # Alerts and events first: they reference both the resident and, for
        # alerts, the acknowledging user.
        for model in (
            Alert,
            ActivityEvent,
            Checkin,
            CheckinSchedule,
            Reminder,
            MedicationSchedule,
            CarePlan,
            CaregiverAssignment,
        ):
            for row in (
                session.execute(
                    select(model).where(model.elderly_profile_id.in_(profile_ids))
                )
                .scalars()
                .all()
            ):
                session.delete(row)
        session.flush()

        for profile in demo_profiles:
            session.delete(profile)
        session.flush()

    # Then the demo accounts (any remaining assignments cascade via the ORM).
    for user in demo_users:
        session.delete(user)
    session.flush()

    logger.info(
        "Reset removed %d demo resident(s) and %d demo account(s).",
        len(demo_profiles),
        len(demo_users),
    )


def create_users(session: Session) -> dict[str, User]:
    """Create the demo accounts and return them by a short key."""
    password_hash = hash_password(DEMO_PASSWORD)

    def make(email: str, name: str, role: UserRole, status: UserStatus = UserStatus.ACTIVE) -> User:
        user = User(
            email=email,
            display_name=name,
            role=role.value,
            status=status.value,
            password_hash=password_hash,
            is_active=True,
        )
        session.add(user)
        return user

    users = {
        "admin": make(f"admin@{DEMO_EMAIL_DOMAIN}", "Demo Administrator", UserRole.ADMIN),
        "caregiver_a": make(
            f"caregiver.a@{DEMO_EMAIL_DOMAIN}", "Alice Caregiver (demo)", UserRole.CAREGIVER
        ),
        "caregiver_b": make(
            f"caregiver.b@{DEMO_EMAIL_DOMAIN}", "Ben Caregiver (demo)", UserRole.CAREGIVER
        ),
        "elderly": make(
            f"resident@{DEMO_EMAIL_DOMAIN}", "Margaret Example (demo)", UserRole.ELDERLY
        ),
    }
    session.flush()
    return users


def create_profiles(session: Session, users: dict[str, User]) -> dict[str, ElderlyProfile]:
    """Create the demo residents and their caregiver assignments."""
    margaret = ElderlyProfile(
        display_name="Margaret Example",
        date_of_birth=date(1948, 4, 12),
        room_label="A-101",
        notes=f"{DEMO_NOTE_PREFIX} Fictional resident used for local development.",
        mobility_notes="Uses a walking frame indoors",
        linked_user_id=users["elderly"].id,
        is_active=True,
    )
    george = ElderlyProfile(
        display_name="George Sample",
        date_of_birth=date(1951, 9, 3),
        room_label="B-204",
        notes=f"{DEMO_NOTE_PREFIX} Fictional resident used for local development.",
        mobility_notes="Independent, stairs are difficult",
        is_active=True,
    )
    session.add_all([margaret, george])
    session.flush()

    session.add_all(
        [
            CaregiverAssignment(
                caregiver_id=users["caregiver_a"].id,
                elderly_profile_id=margaret.id,
                assignment_role=AssignmentRole.PRIMARY.value,
                is_active=True,
            ),
            CaregiverAssignment(
                caregiver_id=users["caregiver_b"].id,
                elderly_profile_id=margaret.id,
                assignment_role=AssignmentRole.SECONDARY.value,
                is_active=True,
            ),
            CaregiverAssignment(
                caregiver_id=users["caregiver_b"].id,
                elderly_profile_id=george.id,
                assignment_role=AssignmentRole.PRIMARY.value,
                is_active=True,
            ),
        ]
    )
    session.flush()
    return {"margaret": margaret, "george": george}


def seed_care(
    session: Session, users: dict[str, User], profiles: dict[str, ElderlyProfile]
) -> None:
    """Create care plans, medications, reminders, and check-in schedules."""
    now = datetime.now(timezone.utc)

    plan = CarePlan(
        elderly_profile_id=profiles["margaret"].id,
        created_by_user_id=users["caregiver_a"].id,
        title="Daily wellbeing plan",
        summary="Morning welfare check, hydration reminders, and a short walk.",
        status=CarePlanStatus.ACTIVE.value,
        start_date=now.date(),
    )
    session.add(plan)

    session.add_all(
        [
            MedicationSchedule(
                elderly_profile_id=profiles["margaret"].id,
                medication_name="Example tablet",
                dosage_text="1 tablet",
                instructions="Take with breakfast. (Fictional example — not medical advice.)",
                recurrence=RecurrencePattern.DAILY.value,
                time_of_day="08:00",
                is_active=True,
            ),
            Reminder(
                elderly_profile_id=profiles["margaret"].id,
                title="Drink some water",
                message="A glass of water with each meal.",
                recurrence=RecurrencePattern.DAILY.value,
                time_of_day="12:30",
                is_active=True,
            ),
            Reminder(
                elderly_profile_id=profiles["margaret"].id,
                title="Short walk",
                message="A gentle walk around the garden, weather permitting.",
                recurrence=RecurrencePattern.WEEKLY.value,
                day_of_week=3,  # Wednesday
                time_of_day="15:00",
                is_active=True,
            ),
        ]
    )

    welfare_schedule = CheckinSchedule(
        elderly_profile_id=profiles["margaret"].id,
        title="Morning welfare check",
        checkin_type=CheckinType.WELLBEING.value,
        recurrence=RecurrencePattern.DAILY.value,
        time_of_day="09:00",
        is_active=True,
    )
    session.add(welfare_schedule)
    session.flush()

    # A few check-ins over the last few days, so history pages have content.
    session.add_all(
        [
            Checkin(
                elderly_profile_id=profiles["margaret"].id,
                checkin_schedule_id=welfare_schedule.id,
                checkin_type=CheckinType.WELLBEING.value,
                status=ScheduleStatus.TAKEN.value,
                scheduled_for=now - timedelta(days=offset),
                performed_at=now - timedelta(days=offset, minutes=-5),
                wellbeing_note="Cheerful, ate a full breakfast.",
                recorded_by_user_id=users["caregiver_a"].id,
            )
            for offset in range(1, 4)
        ]
    )


def seed_activity_and_alerts(
    session: Session, users: dict[str, User], profiles: dict[str, ElderlyProfile]
) -> None:
    """Create simulated activity events and a couple of alerts.

    Every event is written with `source = "simulated"`. This is the honesty
    guarantee: nothing here can be mistaken for a real sensor measurement.
    """
    now = datetime.now(timezone.utc)

    activities = [
        (ActivityType.SLEEPING, 0),
        (ActivityType.EATING, 7),
        (ActivityType.WALKING, 10),
        (ActivityType.SITTING, 13),
        (ActivityType.WALKING, 15),
    ]
    for activity, hours_ago in activities:
        started = now - timedelta(hours=hours_ago)
        session.add(
            ActivityEvent(
                elderly_profile_id=profiles["margaret"].id,
                activity_type=activity.value,
                confidence=0.90,
                started_at=started,
                ended_at=started + timedelta(minutes=30),
                duration_seconds=1800,
                # Explicitly simulated, not real.
                source=EventSource.SIMULATED.value,
                room_label="Living room",
                note="Generated by the demo seed script.",
            )
        )

    fall_alert = Alert(
        elderly_profile_id=profiles["margaret"].id,
        alert_type=AlertType.FALL.value,
        severity=SeverityLevel.HIGH.value,
        status=AlertStatus.NEW.value,
        title="Possible fall (demo)",
        message="Simulated alert used to demonstrate the alerts page.",
        occurrence_count=1,
    )
    # An acknowledged alert must be created *before* it is acknowledged.
    # Leaving created_at to its column default would stamp it at flush time,
    # which is later than the `now` captured above, producing a negative
    # acknowledgement latency in the data. Set it explicitly instead.
    reminder_created_at = now - timedelta(minutes=15)
    reminder_alert = Alert(
        elderly_profile_id=profiles["george"].id,
        alert_type=AlertType.MISSED_MEDICATION.value,
        severity=SeverityLevel.MEDIUM.value,
        status=AlertStatus.ACKNOWLEDGED.value,
        title="Missed medication (demo)",
        message="Simulated alert used to demonstrate acknowledgement.",
        occurrence_count=1,
        created_at=reminder_created_at,
        acknowledged_at=now,
        acknowledged_by_user_id=users["caregiver_b"].id,
    )
    session.add_all([fall_alert, reminder_alert])


def seed(*, reset: bool, force: bool, dry_run: bool) -> None:
    """Run the whole seeding routine."""
    settings = get_settings()
    _check_environment(force)

    # Make sure the tables exist. Alembic is the normal way to do this, but
    # creating from metadata here keeps the script self-contained for a fresh
    # local database. It is a no-op when the tables already exist.
    engine = get_engine()
    if not dry_run:
        Base.metadata.create_all(engine)

    with session_scope() as session:
        existing = _count_users(session)

        if reset:
            if dry_run:
                logger.info("[dry-run] would delete previously seeded demo rows.")
            else:
                reset_demo_data(session)
                existing = _count_users(session)

        if existing and not force:
            raise SeedRefused(
                f"The database already contains {existing} user(s). "
                "Refusing to add demo data on top of real data.\n"
                "Run with --reset to replace previous demo rows, or --force to "
                "seed anyway."
            )

        logger.info(
            "Seeding demo data into %s (dry-run=%s)",
            settings.database_url.split("://", 1)[0],
            dry_run,
        )
        if dry_run:
            logger.info("[dry-run] no rows were written.")
            return

        users = create_users(session)
        profiles = create_profiles(session, users)
        seed_care(session, users, profiles)
        seed_activity_and_alerts(session, users, profiles)

    logger.info("Demo data created successfully.")
    logger.info("Sign in with any of these (password: %s):", DEMO_PASSWORD)
    logger.info("  admin@%s      (admin — sees everything)", DEMO_EMAIL_DOMAIN)
    logger.info("  caregiver.a@%s (primary caregiver for Margaret)", DEMO_EMAIL_DOMAIN)
    logger.info(
        "  caregiver.b@%s (secondary for Margaret, primary for George)", DEMO_EMAIL_DOMAIN
    )
    logger.info("  resident@%s   (elderly login for Margaret)", DEMO_EMAIL_DOMAIN)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--reset", action="store_true", help="delete previously seeded demo rows first"
    )
    parser.add_argument(
        "--force", action="store_true", help="seed even if the database already has users"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="show what would happen, write nothing"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(levelname)-7s %(message)s", stream=sys.stdout
    )

    try:
        seed(reset=args.reset, force=args.force, dry_run=args.dry_run)
    except SeedRefused as exc:
        logger.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - manual entry point
    raise SystemExit(main())
