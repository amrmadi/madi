"""Alembic migration script template.

New revisions created with `alembic revision --autogenerate -m "..."` start
from this file.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql  # noqa: F401  (used in generated code)

# revision identifiers, used by Alembic.
#
# Note on types: these are left un-annotated on purpose. Alembic substitutes
# literal values here, and older Alembic versions write the *string* "None"
# for an absent value. A `str | None` annotation with `from __future__ import
# annotations` hides that mistake; without annotations the real Python None is
# produced, which is what Alembic's revision map requires.
revision = "${up_revision}"
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    """Apply the migration (move the schema forward)."""
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """Revert the migration (move the schema backward)."""
    ${downgrades if downgrades else "pass"}
