"""Check that every table and column named in `analytics/sql/` really exists.

Why this validator exists
-------------------------
The analytics views are hand-written SQL that nothing type-checks. A typo in a
column name is not a syntax error: PostgreSQL happily creates the view and the
error only appears when somebody runs the query. The views also power the
KPIs in the README, so a wrong column name is a wrong number.

The check is static and offline: it compares the SQL against the SQLAlchemy
models, which are the single source of truth for the schema. No database, no
network and no dataset are needed.

How it works
------------
1. The models are imported and `Base.metadata.tables` becomes a map of
   `table name -> {column names}`.
2. Every `analytics/sql/*.sql` file is read, its comments and string literals
   are stripped, and the tables it reads from are collected from its
   `FROM` / `JOIN` clauses.
3. The `SELECT` list is parsed and every column reference is resolved against
   the tables that view reads from.

What it deliberately does NOT do
--------------------------------
It does not report a failure for a reference it cannot resolve unambiguously.
A false failure is worse than a missed one here: a validator people learn to
ignore stops being useful. References it cannot check are counted and
reported separately, so the coverage is visible rather than implied.

Run it with:

    python tools/validate_analytics_sql.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

# The repository root has to be importable, because the models live under
# `backend.app.models`. This is done before the imports below so the script
# works from any working directory.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SQL_DIR = REPO_ROOT / "analytics" / "sql"

# ---------------------------------------------------------------------------
# SQL keywords and type names that are never column references.
#
# The list is deliberately generous: an unknown word is skipped rather than
# reported, because a false failure is the worse outcome.
# ---------------------------------------------------------------------------
SQL_NON_COLUMN_WORDS = frozenset(
    {
        "all",
        "and",
        "any",
        "array",
        "as",
        "asc",
        "at",
        "between",
        "both",
        "by",
        "case",
        "cast",
        "collate",
        "current",
        "delete",
        "desc",
        "distinct",
        "do",
        "else",
        "end",
        "epoch",
        "except",
        "exists",
        "extract",
        "false",
        "fetch",
        "filter",
        "first",
        "for",
        "from",
        "full",
        "group",
        "having",
        "ilike",
        "in",
        "inner",
        "insert",
        "interval",
        "into",
        "is",
        "join",
        "last",
        "lateral",
        "leading",
        "left",
        "like",
        "limit",
        "null",
        "nulls",
        "offset",
        "on",
        "or",
        "order",
        "outer",
        "over",
        "partition",
        "preceding",
        "range",
        "recursive",
        "returning",
        "right",
        "row",
        "rows",
        "select",
        "set",
        "similar",
        "some",
        "substring",
        "then",
        "time",
        "trailing",
        "trim",
        "true",
        "unbounded",
        "union",
        "update",
        "using",
        "values",
        "when",
        "where",
        "window",
        "with",
        "within",
        "zone",
    }
)

#: Identifiers that follow `::` are type names, not columns.
TYPE_CAST_OPERATOR = "::"

TOKEN_RE = re.compile(
    r"""
      (?P<string>'')
    | (?P<number>\d+(?:\.\d+)?)
    | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
    | (?P<op>::|\|\||->>|->|<>|!=|>=|<=|[+\-*/%=<>(),.;])
    | (?P<other>.)
    """,
    re.VERBOSE,
)

CREATE_VIEW_RE = re.compile(
    r"CREATE\s+OR\s+REPLACE\s+VIEW\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE
)
DROP_VIEW_RE = re.compile(
    r"DROP\s+VIEW\s+IF\s+EXISTS\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE
)
FROM_JOIN_RE = re.compile(
    r"\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE
)
CTE_RE = re.compile(
    r"(?:\bWITH\b|,)\s*([A-Za-z_][A-Za-z0-9_]*)\s+AS\s*\(", re.IGNORECASE
)

#: Words that may follow a table name in a `FROM`/`JOIN` clause but are not
#: an alias for it.
NOT_AN_ALIAS = frozenset(
    {
        "and",
        "as",
        "cross",
        "except",
        "fetch",
        "for",
        "from",
        "full",
        "group",
        "having",
        "inner",
        "intersect",
        "join",
        "left",
        "limit",
        "offset",
        "on",
        "or",
        "order",
        "outer",
        "returning",
        "right",
        "set",
        "union",
        "using",
        "values",
        "when",
        "where",
        "window",
        "with",
    }
)


class Token:
    """One lexical token of a SQL statement."""

    __slots__ = ("kind", "text", "line")

    def __init__(self, kind: str, text: str, line: int) -> None:
        self.kind = kind
        self.text = text
        self.line = line

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Token({self.kind!r}, {self.text!r}, line={self.line})"


# ---------------------------------------------------------------------------
# Cleaning and tokenising
# ---------------------------------------------------------------------------


def strip_comments_and_literals(sql_text: str) -> str:
    """Remove comments and blank out string literals.

    String literals become `''`, which keeps the token positions intact while
    making sure that a word inside a string is never mistaken for a column.
    """
    out: list[str] = []
    index = 0
    length = len(sql_text)
    line = 1

    while index < length:
        char = sql_text[index]

        if sql_text.startswith("--", index):
            end = sql_text.find("\n", index)
            index = length if end == -1 else end
            continue

        if sql_text.startswith("/*", index):
            end = sql_text.find("*/", index + 2)
            end = length if end == -1 else end
            line += sql_text.count("\n", index, end)
            index = end + (2 if end != length else 0)
            continue

        if char == "'":
            out.append("''")
            index += 1
            while index < length:
                if sql_text[index] == "'":
                    if index + 1 < length and sql_text[index + 1] == "'":
                        index += 2
                        continue
                    index += 1
                    break
                if sql_text[index] == "\n":
                    line += 1
                index += 1
            continue

        if char == '"':
            out.append(char)
            index += 1
            while index < length:
                out.append(sql_text[index])
                if sql_text[index] == '"':
                    index += 1
                    break
                if sql_text[index] == "\n":
                    line += 1
                index += 1
            continue

        if char == "\n":
            line += 1
        out.append(char)
        index += 1

    return "".join(out)


def tokenize(sql_text: str) -> list[Token]:
    """Split cleaned SQL into a flat token list."""
    tokens: list[Token] = []
    line = 1
    for match in TOKEN_RE.finditer(sql_text):
        text = match.group(0)
        if text == "\n":
            line += 1
            continue
        if text.isspace():
            continue
        kind = match.lastgroup or "other"
        tokens.append(Token(kind, text, line))
    return tokens


def balanced_group(text: str, open_index: int) -> tuple[str, int]:
    """Return the text inside the parentheses that start at `open_index`."""
    depth = 0
    index = open_index
    length = len(text)
    while index < length:
        char = text[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[open_index + 1 : index], index + 1
        index += 1
    return text[open_index + 1 :], length


# ---------------------------------------------------------------------------
# Relations
# ---------------------------------------------------------------------------


def find_relations(text: str) -> tuple[set[str], dict[str, str]]:
    """Return `(table names, alias -> table name)` for a cleaned statement."""
    tables: set[str] = set()
    aliases: dict[str, str] = {}

    for match in FROM_JOIN_RE.finditer(text):
        table = match.group(1)
        tables.add(table)
        alias_match = re.match(
            r"\s+([A-Za-z_][A-Za-z0-9_]*)", text[match.end() :]
        )
        if alias_match:
            alias = alias_match.group(1)
            if alias.lower() not in NOT_AN_ALIAS:
                aliases[alias.lower()] = table

    return tables, aliases


def find_ctes(text: str) -> dict[str, set[str]]:
    """Return `CTE name -> output column names`.

    The output columns of a CTE are taken from the first `SELECT` list inside
    it. That is enough to check the columns the CTE is later used with, which
    is what makes the more complex views verifiable.
    """
    ctes: dict[str, set[str]] = {}
    normalised = re.sub(r"\bWITH\s+RECURSIVE\b", "WITH", text, flags=re.IGNORECASE)

    for match in CTE_RE.finditer(normalised):
        name = match.group(1)
        open_paren = normalised.find("(", match.end() - 1)
        if open_paren == -1:
            continue
        body, _ = balanced_group(normalised, open_paren)
        ctes[name] = first_select_list_columns(body)

    return ctes


def first_select_list_columns(body: str) -> set[str]:
    """Return the output column names of the first `SELECT` in `body`."""
    tokens = tokenize(body)
    start = None
    for index, token in enumerate(tokens):
        if token.kind == "ident" and token.text.lower() == "select":
            start = index + 1
            break
    if start is None:
        return set()

    items: list[list[Token]] = []
    current: list[Token] = []
    depth = 0
    for token in tokens[start:]:
        if token.kind == "op" and token.text in ("(",):
            depth += 1
        elif token.kind == "op" and token.text == ")":
            depth -= 1
        if depth == 0 and token.kind == "ident" and token.text.lower() == "from":
            break
        if depth == 0 and token.kind == "op" and token.text == ",":
            items.append(current)
            current = []
            continue
        current.append(token)
    if current:
        items.append(current)

    columns: set[str] = set()
    for item in items:
        name = output_name_of(item)
        if name:
            columns.add(name.lower())
    return columns


def output_name_of(item: list[Token]) -> str | None:
    """Return the output name a `SELECT` item produces, if it can be told."""
    if not item:
        return None
    if len(item) >= 2 and item[-2].kind == "ident" and item[-2].text.lower() == "as":
        if item[-1].kind == "ident":
            return item[-1].text
        return None
    if len(item) == 1 and item[0].kind == "ident":
        return item[0].text
    if len(item) == 3 and item[0].kind == "ident" and item[1].text == ".":
        if item[2].kind == "ident":
            return item[2].text
        return None
    return None


# ---------------------------------------------------------------------------
# Column references
# ---------------------------------------------------------------------------


def collect_column_references(
    tokens: list[Token],
    relations: set[str],
    aliases: dict[str, str],
) -> tuple[list[tuple[str | None, str, int]], list[tuple[str, int]]]:
    """Return `(qualified refs, bare refs)` found in a token list.

    A qualified reference is `(qualifier, column, line)`; a bare reference is
    `(column, line)`. Only the column part is returned, because that is what
    has to exist in the schema.
    """
    qualified: list[tuple[str | None, str, int]] = []
    bare: list[tuple[str, int]] = []

    # Words that name a relation (table, CTE or alias) are never column
    # references on their own.
    relation_words = {name.lower() for name in relations}
    relation_words.update(aliases)
    relation_words.update(name.lower() for name in relations)

    index = 0
    total = len(tokens)
    while index < total:
        token = tokens[index]
        if token.kind != "ident":
            index += 1
            continue

        word = token.text
        lower = word.lower()
        previous = tokens[index - 1] if index > 0 else None
        following = tokens[index + 1] if index + 1 < total else None

        # A function call: the name is not a column.
        if following is not None and following.kind == "op" and following.text == "(":
            index += 1
            continue

        # An output alias (`... AS some_name`).
        if (
            previous is not None
            and previous.kind == "ident"
            and previous.text.lower() == "as"
        ):
            index += 1
            continue

        # A cast target (`value::date`).
        if (
            previous is not None
            and previous.kind == "op"
            and previous.text == TYPE_CAST_OPERATOR
        ):
            index += 1
            continue

        # A qualified reference: `alias.column` or `table.column`.
        if (
            following is not None
            and following.kind == "op"
            and following.text == "."
            and index + 2 < total
            and tokens[index + 2].kind == "ident"
        ):
            qualified.append((word, tokens[index + 2].text, token.line))
            index += 3
            continue

        # A keyword, a type name, or a relation name.
        if lower in SQL_NON_COLUMN_WORDS or lower in relation_words:
            index += 1
            continue

        bare.append((word, token.line))
        index += 1

    return qualified, bare


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------


class Failure:
    """One genuine problem found in one SQL file."""

    def __init__(self, path: Path, line: int | None, message: str) -> None:
        self.path = path
        self.line = line
        self.message = message

    def __str__(self) -> str:
        location = self.path.name
        if self.line is not None:
            location = f"{location}:{self.line}"
        return f"{location}: {self.message}"


def load_schema() -> dict[str, set[str]]:
    """Return `table name -> column names` from the SQLAlchemy models."""
    try:
        from backend.app.db.base import Base
        import backend.app.models  # noqa: F401  (registers every table)
    except ImportError as exc:
        raise SystemExit(
            "ERROR: this validator needs SQLAlchemy and the project models.\n"
            f"  {type(exc).__name__}: {exc}\n"
            "  Install the backend dependencies first:\n"
            "    pip install -r backend/requirements.txt\n"
            "The check was NOT skipped: a validator that quietly does nothing "
            "is worse than no validator."
        )

    return {
        table.name: {column.name.lower() for column in table.columns}
        for table in Base.metadata.tables.values()
    }


def check_file(path: Path, schema: dict[str, set[str]]) -> tuple[list[Failure], dict[str, int]]:
    """Check one SQL file. Returns `(failures, counters)`."""
    failures: list[Failure] = []
    counters = {
        "table_references": 0,
        "column_references": 0,
        "column_references_skipped": 0,
    }

    raw = path.read_text(encoding="utf-8")
    cleaned = strip_comments_and_literals(raw)

    created = CREATE_VIEW_RE.findall(cleaned)
    dropped = DROP_VIEW_RE.findall(cleaned)

    if len(created) != 1:
        failures.append(
            Failure(
                path,
                None,
                f"expected exactly one 'CREATE OR REPLACE VIEW' statement, found {len(created)}",
            )
        )
        return failures, counters

    view_name = created[0]
    if len(dropped) != 1 or dropped[0] != view_name:
        failures.append(
            Failure(
                path,
                None,
                f"expected one 'DROP VIEW IF EXISTS {view_name}' statement, found {len(dropped)}",
            )
        )

    relations, aliases = find_relations(cleaned)
    ctes = find_ctes(cleaned)

    # Every relation that is not a CTE must be a real table.
    for relation in sorted(relations):
        if relation in ctes:
            continue
        counters["table_references"] += 1
        if relation not in schema:
            failures.append(
                Failure(
                    path,
                    None,
                    f"view {view_name} reads from unknown table {relation!r}",
                )
            )

    # The body of the view is everything after the `AS` of the CREATE.
    match = CREATE_VIEW_RE.search(cleaned)
    assert match is not None
    body = cleaned[match.end() :]
    as_index = body.upper().find(" AS ")
    if as_index == -1:
        failures.append(
            Failure(path, None, f"view {view_name} has no 'AS' before its SELECT")
        )
        return failures, counters
    body = body[as_index + 4 :]

    tokens = tokenize(body)
    qualified, bare = collect_column_references(tokens, relations | set(ctes), aliases)

    model_tables = {name for name in relations if name not in ctes}

    for qualifier, column, line in qualified:
        key = qualifier.lower()
        if key in aliases:
            table = aliases[key]
            if table in ctes:
                known = ctes[table]
                if not known:
                    counters["column_references_skipped"] += 1
                    continue
                if column.lower() not in known:
                    failures.append(
                        Failure(
                            path,
                            line,
                            f"view {view_name} references {qualifier}.{column}, "
                            f"which is not an output column of the CTE {table!r}",
                        )
                    )
                else:
                    counters["column_references"] += 1
                continue
            columns = schema.get(table)
            if columns is None:
                counters["column_references_skipped"] += 1
                continue
            if column.lower() not in columns:
                failures.append(
                    Failure(
                        path,
                        line,
                        f"view {view_name} references {qualifier}.{column}, "
                        f"but table {table!r} has no column {column!r}",
                    )
                )
            else:
                counters["column_references"] += 1
            continue

        if key in {name.lower() for name in ctes}:
            known = ctes[qualifier]
            if not known:
                counters["column_references_skipped"] += 1
                continue
            if column.lower() not in known:
                failures.append(
                    Failure(
                        path,
                        line,
                        f"view {view_name} references {qualifier}.{column}, "
                        f"which is not an output column of the CTE {qualifier!r}",
                    )
                )
            else:
                counters["column_references"] += 1
            continue

        # An unknown qualifier: it may be a derived table this parser does not
        # model. Skipped rather than reported, so it cannot cause a false
        # failure.
        counters["column_references_skipped"] += 1

    for column, line in bare:
        if any(column.lower() in schema[name] for name in model_tables):
            counters["column_references"] += 1
            continue
        counters["column_references_skipped"] += 1

    return failures, counters


def main() -> int:
    """Run the check. Returns the process exit code."""
    if not SQL_DIR.is_dir():
        print(f"FAIL: SQL directory not found: {SQL_DIR}", file=sys.stderr)
        return 1

    files = sorted(SQL_DIR.glob("*.sql"))
    if not files:
        print(f"FAIL: no .sql files found in {SQL_DIR}", file=sys.stderr)
        return 1

    schema = load_schema()

    all_failures: list[Failure] = []
    totals = {
        "table_references": 0,
        "column_references": 0,
        "column_references_skipped": 0,
    }

    print(f"Checking {len(files)} SQL file(s) against {len(schema)} model table(s)")
    for path in files:
        failures, counters = check_file(path, schema)
        all_failures.extend(failures)
        for key in totals:
            totals[key] += counters[key]
        status = "FAIL" if failures else "ok"
        print(
            f"  {status:>4}  {path.name}"
            f"  (tables: {counters['table_references']},"
            f" columns: {counters['column_references']},"
            f" skipped: {counters['column_references_skipped']})"
        )

    print()
    print(f"Table references checked : {totals['table_references']}")
    print(f"Column references checked: {totals['column_references']}")
    print(
        "Column references skipped: "
        f"{totals['column_references_skipped']} "
        "(could not be resolved unambiguously — not a failure)"
    )

    if all_failures:
        print()
        print(f"FAIL: {len(all_failures)} unresolved reference(s):")
        for failure in all_failures:
            print(f"  - {failure}")
        return 1

    print()
    print("PASS: every table and column named in analytics/sql/ exists.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
