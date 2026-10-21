"""Export the analytics views to CSV files for Power BI.

What this script does
---------------------
Applies (optionally) and then reads the eight PostgreSQL views in
`analytics/sql/`, and writes one CSV per view into `analytics/exports/`, plus a
`_manifest.json` that records where every file came from.

How to run it
-------------
    python analytics/export_analytics.py                    # export every view
    python analytics/export_analytics.py --apply-sql        # create the views first
    python analytics/export_analytics.py --views v_alert_lifecycle_daily
    python analytics/export_analytics.py --database-url postgresql://...

Run it from the repository root. The database URL is taken from the
`DATABASE_URL` environment variable, falling back to the placeholder in
`.env.example`. Only the standard library and `psycopg` are needed, and
`psycopg` is imported lazily so `--help` works even where it is not installed.

The rules this script follows
-----------------------------
* **It never fabricates data.** If a view does not exist in the database, the
  script says which view is missing and exits non-zero. It never writes an
  empty CSV, because an empty CSV is indistinguishable from "there was no
  activity" — which is exactly the kind of wrong conclusion this project is
  trying to avoid.
* **It never hides a failure.** An unreachable database is a clear error with
  an actionable message, not a silently skipped export.
* **It labels the data.** The manifest states that the export may contain
  simulated demo rows, and the database URL is stored with its password
  removed, because a manifest is a file that gets shared.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

# Repository root = analytics/export_analytics.py -> one level up.
REPO_ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = REPO_ROOT / "analytics" / "sql"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "analytics" / "exports"
ENV_EXAMPLE = REPO_ROOT / ".env.example"

#: Used when neither the environment nor `.env.example` provides a URL.
FALLBACK_DATABASE_URL = (
    "postgresql+psycopg://elderlife_dev:change_me_local_only@localhost:5432/elderlife"
)

#: Every note in the manifest says this, because a reader of a CSV never sees
#: this file and must still know where the numbers came from.
SIMULATION_NOTE = (
    "Rows may include simulated demo data (source='simulated') and public "
    "research data (source='imported_dataset'). Simulated rows are demo "
    "records, not measurements of a real resident."
)

VIEW_NAME_RE = re.compile(
    r"CREATE\s+OR\s+REPLACE\s+VIEW\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE
)
SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ExportError(RuntimeError):
    """A problem the user can act on. Reported without a traceback."""


class MissingDependency(ExportError):
    """A required third-party package is not installed."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def read_env_example_database_url(path: Path = ENV_EXAMPLE) -> str | None:
    """Read the placeholder `DATABASE_URL` out of `.env.example`.

    The example file is a committed template, so its value is a placeholder —
    using it as the fallback keeps the script runnable out of the box without
    ever hiding a real credential.
    """
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("DATABASE_URL="):
            value = stripped.split("=", 1)[1].strip()
            return value or None
    return None


def resolve_database_url(explicit: str | None) -> str:
    """Pick the database URL: explicit flag, then environment, then example."""
    if explicit:
        return explicit
    from_env = os.environ.get("DATABASE_URL")
    if from_env and from_env.strip():
        return from_env.strip()
    from_example = read_env_example_database_url()
    if from_example:
        return from_example
    return FALLBACK_DATABASE_URL


def normalise_dsn(dsn: str) -> str:
    """Turn a SQLAlchemy-style URL into one `psycopg` understands.

    SQLAlchemy writes `postgresql+psycopg://...`; `psycopg` only accepts
    `postgresql://...`. The driver suffix is dropped rather than the whole
    scheme, so the URL keeps working for a `psycopg2` setup too.
    """
    match = re.match(r"^([A-Za-z0-9+]+)\+([A-Za-z0-9_]+)(://.*)$", dsn.strip())
    if match:
        return f"{match.group(1)}{match.group(3)}"
    return dsn.strip()


def redact_dsn(dsn: str) -> str:
    """Remove the password from a connection string before it is written out."""
    return re.sub(r"://([^:/@]+):[^@]*@", r"://\1:***@", dsn)


# ---------------------------------------------------------------------------
# Finding the views
# ---------------------------------------------------------------------------


def discover_views(sql_dir: Path = SQL_DIR) -> list[tuple[str, Path]]:
    """Return `(view_name, sql_file)` pairs, ordered by file name.

    The view name is read out of the `CREATE OR REPLACE VIEW` statement rather
    than assumed from the file name, so the two cannot drift apart silently.
    """
    if not sql_dir.is_dir():
        raise ExportError(f"SQL directory not found: {sql_dir}")

    found: list[tuple[str, Path]] = []
    for path in sorted(sql_dir.glob("*.sql")):
        text = path.read_text(encoding="utf-8")
        match = VIEW_NAME_RE.search(text)
        if match is None:
            raise ExportError(
                f"{path} does not contain a 'CREATE OR REPLACE VIEW' statement."
            )
        found.append((match.group(1), path))

    if not found:
        raise ExportError(f"No .sql files found in {sql_dir}.")
    return found


def select_views(
    available: list[tuple[str, Path]], requested: str | None
) -> list[tuple[str, Path]]:
    """Filter the discovered views down to the ones the user asked for."""
    if not requested:
        return available

    wanted = [name.strip() for name in requested.split(",") if name.strip()]
    if not wanted:
        raise ExportError("--views was given but contained no view names.")

    by_name = {name: path for name, path in available}
    unknown = [name for name in wanted if name not in by_name]
    if unknown:
        known = ", ".join(sorted(by_name))
        raise ExportError(
            f"Unknown view(s): {', '.join(unknown)}. Known views are: {known}."
        )
    # Keep the canonical (file name) order rather than the order requested.
    return [(name, by_name[name]) for name, _ in available if name in wanted]


# ---------------------------------------------------------------------------
# Database access
# ---------------------------------------------------------------------------


def import_psycopg():
    """Import `psycopg` lazily and explain clearly when it is missing."""
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - depends on the machine
        raise MissingDependency(
            "the 'psycopg' package is not installed. Install it with "
            "`pip install \"psycopg[binary]\"` (or use the project's "
            "backend/requirements.txt)."
        ) from exc
    return psycopg


def split_sql_statements(sql_text: str) -> list[str]:
    """Split a SQL file into individual statements.

    Written by hand because the standard library has no SQL splitter and the
    project has no `sqlparse` dependency. Quoted text, dollar-quoted blocks and
    comments are respected, so a `;` inside a string is not a statement break.
    """
    statements: list[str] = []
    buffer: list[str] = []
    index = 0
    length = len(sql_text)

    while index < length:
        char = sql_text[index]

        # -- line comment
        if sql_text.startswith("--", index):
            end = sql_text.find("\n", index)
            index = length if end == -1 else end
            continue

        # /* block comment */
        if sql_text.startswith("/*", index):
            end = sql_text.find("*/", index + 2)
            index = length if end == -1 else end + 2
            continue

        # '...' string literal
        if char == "'":
            buffer.append(char)
            index += 1
            while index < length:
                buffer.append(sql_text[index])
                if sql_text[index] == "'":
                    if index + 1 < length and sql_text[index + 1] == "'":
                        buffer.append(sql_text[index + 1])
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            continue

        # "..." quoted identifier
        if char == '"':
            buffer.append(char)
            index += 1
            while index < length:
                buffer.append(sql_text[index])
                if sql_text[index] == '"':
                    index += 1
                    break
                index += 1
            continue

        # $tag$ ... $tag$ dollar-quoted block
        dollar = re.match(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$", sql_text[index:])
        if dollar:
            tag = dollar.group(0)
            end = sql_text.find(tag, index + len(tag))
            end = length if end == -1 else end + len(tag)
            buffer.append(sql_text[index:end])
            index = end
            continue

        if char == ";":
            statement = "".join(buffer).strip()
            if statement:
                statements.append(statement)
            buffer = []
            index += 1
            continue

        buffer.append(char)
        index += 1

    tail = "".join(buffer).strip()
    if tail:
        statements.append(tail)
    return statements


def apply_sql_files(conn, files: list[Path]) -> None:
    """Create (or replace) the views in the connected database."""
    for path in files:
        statements = split_sql_statements(path.read_text(encoding="utf-8"))
        for statement in statements:
            try:
                conn.execute(statement)
            except Exception as exc:
                raise ExportError(
                    f"Failed to apply {path.name}: {exc}"
                ) from exc
        print(f"  applied {path.relative_to(REPO_ROOT)}")


def find_missing_views(conn, view_names: list[str]) -> list[str]:
    """Return the requested views that do not exist in the database.

    The check happens *before* anything is written, so a missing view can
    never end up as an empty CSV that looks like "no data".
    """
    rows = conn.execute(
        "SELECT viewname FROM pg_views WHERE viewname = ANY(%s)",
        (list(view_names),),
    ).fetchall()
    existing = {str(row[0]) for row in rows}
    return [name for name in view_names if name not in existing]


# ---------------------------------------------------------------------------
# Writing the exports
# ---------------------------------------------------------------------------


def csv_value(value: Any) -> str:
    """Render one database value as a CSV cell."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def export_view(conn, view_name: str, output_dir: Path) -> dict[str, Any]:
    """Write one view to `<view_name>.csv` and describe it for the manifest."""
    if not SAFE_IDENTIFIER_RE.match(view_name):
        raise ExportError(f"Refusing to query an unsafe view name: {view_name!r}")

    query = f'SELECT * FROM "{view_name}"'
    try:
        with conn.cursor() as cursor:
            cursor.execute(query)
            columns = [description.name for description in cursor.description or []]
            target = output_dir / f"{view_name}.csv"
            with target.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(columns)
                row_count = 0
                for row in cursor:
                    writer.writerow([csv_value(value) for value in row])
                    row_count += 1
    except Exception as exc:
        raise ExportError(f"Failed to export view {view_name!r}: {exc}") from exc

    return {
        "view_name": view_name,
        "row_count": row_count,
        "columns": columns,
        "csv_file": target.name,
    }


def build_manifest(
    entries: list[dict[str, Any]],
    database_url: str,
    exported_at: str,
) -> dict[str, Any]:
    """Assemble the provenance record that ships next to the CSVs."""
    return {
        "generator": "analytics/export_analytics.py",
        "exported_at": exported_at,
        "database_url_redacted": redact_dsn(database_url),
        "note": SIMULATION_NOTE,
        "views": [
            {
                "view_name": entry["view_name"],
                "source_sql_file": entry["source_sql_file"],
                "csv_file": entry["csv_file"],
                "row_count": entry["row_count"],
                "columns": entry["columns"],
                "exported_at": exported_at,
                "note": SIMULATION_NOTE,
            }
            for entry in entries
        ],
    }


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the command line.

    `--help` must work without `psycopg` installed, so nothing here imports it.
    """
    parser = argparse.ArgumentParser(
        prog="export_analytics.py",
        description=(
            "Export the ElderLife AI analytics views to CSV files for Power BI."
        ),
        epilog=(
            "The database URL defaults to the DATABASE_URL environment variable, "
            "then to the placeholder in .env.example. Views must exist in the "
            "database: pass --apply-sql to create them from analytics/sql/."
        ),
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help=(
            "PostgreSQL connection string. Default: the DATABASE_URL environment "
            "variable, otherwise the placeholder from .env.example."
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help=(
            "Directory for the CSV files. Default: analytics/exports (relative "
            "to the repository root). A relative path given here is resolved "
            "against the current directory."
        ),
    )
    parser.add_argument(
        "--views",
        default=None,
        help=(
            "Comma-separated subset of view names to export, e.g. "
            "'v_alert_lifecycle_daily,v_model_run_metrics'. Default: all of them."
        ),
    )
    parser.add_argument(
        "--apply-sql",
        action="store_true",
        help=(
            "Apply the analytics/sql/*.sql files to the target database before "
            "exporting, so the views exist."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns the process exit code."""
    args = parse_args(argv)

    database_url = resolve_database_url(args.database_url)
    dsn = normalise_dsn(database_url)

    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else DEFAULT_OUTPUT_DIR
    )

    try:
        available = discover_views()
        views = select_views(available, args.views)
    except ExportError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    psycopg = None
    try:
        psycopg = import_psycopg()
    except MissingDependency as exc:
        if args.apply_sql:
            # The apply step is skipped with an explanation rather than a bare
            # traceback. The export below then reports the same missing
            # dependency, because it cannot run without the driver either.
            print(f"SKIP: --apply-sql was requested but {exc}", file=sys.stderr)
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2

    if psycopg is None:
        print(
            "ERROR: the export needs the 'psycopg' package, which is not "
            "installed.",
            file=sys.stderr,
        )
        return 2

    try:
        with psycopg.connect(dsn, connect_timeout=10) as conn:
            conn.autocommit = True

            if args.apply_sql:
                print("Applying analytics SQL files...")
                try:
                    apply_sql_files(conn, [path for _, path in views])
                except ExportError as exc:
                    print(f"ERROR: {exc}", file=sys.stderr)
                    return 1

            missing = find_missing_views(conn, [name for name, _ in views])
            if missing:
                print(
                    "ERROR: the following view(s) do not exist in the database:\n"
                    + "".join(f"  - {name}\n" for name in missing),
                    file=sys.stderr,
                )
                print(
                    "Nothing was written. Create the views first, for example:\n"
                    "  python analytics/export_analytics.py --apply-sql\n"
                    "or apply the files in analytics/sql/ with your own tool.",
                    file=sys.stderr,
                )
                return 1

            output_dir.mkdir(parents=True, exist_ok=True)
            exported_at = datetime.now(timezone.utc).isoformat()

            entries: list[dict[str, Any]] = []
            print(f"Exporting {len(views)} view(s) to {output_dir}")
            for view_name, path in views:
                entry = export_view(conn, view_name, output_dir)
                entry["source_sql_file"] = str(path.relative_to(REPO_ROOT)).replace(
                    "\\", "/"
                )
                entries.append(entry)
                print(f"  {view_name}: {entry['row_count']} row(s)")

            manifest = build_manifest(entries, database_url, exported_at)
            manifest_path = output_dir / "_manifest.json"
            manifest_path.write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            print(f"Wrote {manifest_path}")
    except MissingDependency as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except ExportError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        # The database is unreachable, or something else went wrong at the
        # driver level. Say so plainly instead of swallowing it.
        print(
            f"ERROR: could not reach or query the database.\n"
            f"  URL: {redact_dsn(dsn)}\n"
            f"  Reason: {type(exc).__name__}: {exc}\n"
            f"  Check that PostgreSQL is running and that the URL is correct "
            f"(docker compose up -d db, or set DATABASE_URL).",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
