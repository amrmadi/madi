"""Dataset registry: keeps public research data separate from APP user records.

This module exists to enforce a hard rule of the project:

    Public research datasets (UP-Fall, CASAS, UCI HAR) describe volunteers in
    research studies. Application records describe real users of ElderLife AI.
    These two must never be mixed in the same table, or a research row could be
    mistaken for a real person's data (and vice versa).

How the separation is guaranteed
--------------------------------
1. Research data lives in its own tables, all prefixed `dataset_`, with NO
   foreign keys to `elderly_profiles` or `users` — and no foreign keys pointing
   back. The schema itself makes mixing impossible.
2. Every event table carries a `source` column (`simulated`, `sensor`,
   `manual_entry`, `imported_dataset`, `model`). Imported research rows must be
   marked `imported_dataset`, so analytics can filter them out.
3. `DatasetRecord` stores only *metadata and a path* to the files under
   `data/raw/` — never the data rows themselves. The datasets are git-ignored.

No dataset has been downloaded yet; this table simply gives Phase 6 a place to
register one once its licence and format have been documented in
`docs/datasets/`.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base, utcnow

# The three datasets this project plans to use. Kept as constants so the seed
# script and Phase 6 code refer to the same identifiers.
KNOWN_DATASETS = ("up_fall", "casas", "uci_har")


class DatasetRegistry(Base):
    """One registered (not necessarily downloaded) research dataset."""

    __tablename__ = "dataset_registry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    source_url: Mapped[str] = mapped_column(String(500), nullable=False)
    license: Mapped[str | None] = mapped_column(String(160), nullable=True)
    documentation_path: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Honest status flags — all false until the work actually happens.
    is_downloaded: Mapped[bool] = mapped_column(nullable=False, default=False)
    is_processed: Mapped[bool] = mapped_column(nullable=False, default=False)
    is_used_for_training: Mapped[bool] = mapped_column(nullable=False, default=False)

    local_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    # ---- Relationships ----
    files: Mapped[list["DatasetFile"]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "slug IN ('up_fall', 'casas', 'uci_har')",
            name="dataset_slug_valid",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<DatasetRegistry slug={self.slug!r} downloaded={self.is_downloaded}>"


class DatasetFile(Base):
    """A single downloaded file belonging to a registered dataset.

    Only the *description* of the file is stored (path, size, checksum). The file
    content stays on disk under `data/raw/`, which is git-ignored.
    """

    __tablename__ = "dataset_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_registry.id", ondelete="CASCADE"), nullable=False, index=True
    )

    relative_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_format: Mapped[str | None] = mapped_column(String(32), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    # ---- Relationships ----
    dataset: Mapped["DatasetRegistry"] = relationship(back_populates="files")

    __table_args__ = (
        Index("ix_dataset_files_dataset_path", "dataset_id", "relative_path"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<DatasetFile id={self.id} path={self.relative_path!r}>"
