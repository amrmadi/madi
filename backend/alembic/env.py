"""Alembic environment configuration.

What happens here
-----------------
Alembic calls these functions when you run commands like `alembic upgrade head`
or `alembic revision --autogenerate`, so this file is the bridge between
Alembic and our SQLAlchemy models.

Two important design choices:

1. **The database URL is not stored in `alembic.ini`.** It is read from the
   app settings (your `.env` file). This keeps credentials out of Git and means
   Alembic and the application always target the same database.

2. **`target_metadata` points at our model metadata.** That is what enables
   autogeneration: Alembic compares the models to the live database and writes
   the difference as a migration.

Offline vs online mode:
    * `run_migrations_offline()` — generates SQL without connecting to a
      database (used by `alembic upgrade head --sql`).
    * `run_migrations_online()`  — connects and actually applies changes.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# ---------------------------------------------------------------------------
# Make the project importable.
# ---------------------------------------------------------------------------
# `backend/alembic/env.py` is executed with Alembic's working directory set to
# `backend/`, but our packages are imported as `backend.app...`. The parent
# directory therefore has to be on `sys.path`.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Importing the models package registers every table on `Base.metadata`.
# This import has a side effect and is required for autogenerate to work.
from backend.app.core.config import get_settings  # noqa: E402
from backend.app.models import Base  # noqa: E402

# Alembic's own logging config from alembic.ini.
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The metadata Alembic compares against the database.
target_metadata = Base.metadata


def get_url() -> str:
    """Return the database URL from application settings.

    Reading it here (rather than from alembic.ini) means `.env` is the single
    source of truth for the connection string.
    """
    return get_settings().database_url


def run_migrations_offline() -> None:
    """Generate SQL without a live database connection."""
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Detect column type changes when autogenerating.
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect to the database and apply migrations."""
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
