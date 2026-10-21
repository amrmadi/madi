"""Database engine, session factory, and the declarative model base.

Textbook SQLAlchemy 2.0 ("modern") style is used throughout:
    * `DeclarativeBase` with `Mapped[...]` type annotations on models.
    * `Session` used as a context manager.

The engine is created lazily so that importing this module never opens a
connection — tests and Alembic can import models without a running database.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.app.core.config import get_settings

# ---------------------------------------------------------------------------
# Naming convention
# ---------------------------------------------------------------------------
# Giving every constraint an explicit, predictable name makes Alembic
# migrations (and future downgrades) far easier to read and safer to run.
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    def to_dict(self) -> dict[str, Any]:
        """Return the row as a plain dictionary (handy for debugging/tests)."""
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


def utcnow() -> datetime:
    """Timezone-aware UTC 'now'.

    `datetime.utcnow()` is deprecated because it returns a naive datetime.
    Always storing aware UTC datetimes avoids a whole class of bugs.
    """
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Engine & session factory (created on first use, then cached)
# ---------------------------------------------------------------------------
_engine = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine():
    """Return the process-wide SQLAlchemy `Engine`, creating it on first call.

    `pool_pre_ping` checks the connection is still alive before handing it out,
    which avoids "server closed the connection unexpectedly" errors after the
    database has been restarted (very common during development).
    """
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.database_url,
            pool_pre_ping=True,
            future=True,
            echo=False,
        )
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Return the process-wide `sessionmaker` bound to the shared engine."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(),
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            class_=Session,
        )
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional session: commit on success, roll back on error.

    Usage:
        with session_scope() as session:
            session.add(obj)
    """
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency (used from Phase 3): yield a session per request."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


# Re-exported for convenient, consistent imports across the codebase.
TIMESTAMP = DateTime(timezone=True)
