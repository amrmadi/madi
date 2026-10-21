"""Check that the frontend nginx configuration really does what it claims.

Why this validator exists
-------------------------
`frontend/nginx.conf` and `frontend/security-headers.conf` are configuration
files, so nothing type-checks them and a mistake only shows up as a missing
header on a live response. The failure mode this repository already hit once
is worth spelling out:

    nginx does NOT merge `add_header` directives across levels. As soon as a
    `location` block declares one `add_header` of its own, every `add_header`
    inherited from the enclosing `server` block is discarded for that location.

So the obvious-looking layout — security headers at server level, a
`Cache-Control` in each location — silently ships a site with **no** security
headers on exactly the responses that need them. The configuration in this
repository works around that by keeping the headers in an included file and
`include`-ing it from every location. That workaround is easy to undo by
accident, so it is checked mechanically here.

The checks are static and offline: the configuration files are parsed, no
container is started, no HTTP request is made and no dataset is touched.

What it checks
--------------
* every `location` block includes the shared security-header file;
* the shared file defines the four headers the project depends on
  (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`,
  `Content-Security-Policy`), each with the `always` parameter;
* the security headers are *not* declared at `server` level, where they would
  be dropped by the inheritance rule above;
* `= /index.html` is served with `no-cache`, so a deploy cannot keep serving
  a stale bundle reference;
* `/assets/` is served with a single long-lived `Cache-Control` and no
  `expires` directive, because the two together emit two `Cache-Control`
  headers and a duplicate header is ambiguous to caches;
* `location /` falls back to `/index.html`, which is what makes a deep link
  such as `/residents/3` survive a page refresh.

Run it with:

    python tools/validate_nginx.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
NGINX_CONF = REPO_ROOT / "frontend" / "nginx.conf"
SECURITY_HEADERS_CONF = REPO_ROOT / "frontend" / "security-headers.conf"

#: The path the `include` directive inside `nginx.conf` uses. The Dockerfile
#: copies the file to exactly this location next to `default.conf`.
SECURITY_HEADERS_INCLUDE = "/etc/nginx/conf.d/security-headers.conf"

#: The headers the project depends on. Each must be present in
#: `security-headers.conf` exactly once.
REQUIRED_SECURITY_HEADERS = (
    "X-Content-Type-Options",
    "X-Frame-Options",
    "Referrer-Policy",
    "Content-Security-Policy",
)


# ---------------------------------------------------------------------------
# A very small nginx configuration parser
# ---------------------------------------------------------------------------
#
# nginx syntax is small enough to parse directly: directives are words
# followed by arguments and terminated by `;`, and a directive followed by `{`
# opens a block terminated by `}`. Quoted strings are supported because
# `Cache-Control "public, max-age=31536000, immutable"` needs them.


@dataclass(frozen=True)
class Token:
    """One lexical unit of an nginx configuration file."""

    kind: str  # "word" | "punct"
    value: str
    line: int


@dataclass
class Directive:
    """A single nginx directive, possibly with a nested block."""

    name: str
    args: list[str] = field(default_factory=list)
    children: list["Directive"] = field(default_factory=list)
    line: int = 0

    @property
    def is_block(self) -> bool:
        """True when the directive owns a nested `{ ... }` block."""
        return bool(self.children)

    def find_all(self, name: str) -> list["Directive"]:
        """Return every direct child with the given directive name."""
        return [child for child in self.children if child.name == name]

    def find(self, name: str) -> "Directive | None":
        """Return the first direct child with the given directive name."""
        matches = self.find_all(name)
        return matches[0] if matches else None

    def walk(self) -> list["Directive"]:
        """Return this directive and every directive nested inside it."""
        found = [self]
        for child in self.children:
            found.extend(child.walk())
        return found


class ConfigError(RuntimeError):
    """Raised when a configuration file cannot be parsed."""


def tokenize(text: str) -> list[Token]:
    """Split nginx configuration text into tokens.

    Handles `#` comments (to the end of the line), single- and double-quoted
    strings, and the three structural characters `{`, `}` and `;`.
    """
    tokens: list[Token] = []
    index = 0
    line = 1
    length = len(text)

    while index < length:
        char = text[index]

        if char == "\n":
            line += 1
            index += 1
            continue

        if char.isspace():
            index += 1
            continue

        # A `#` starts a comment unless it is inside a quoted string, and
        # quoted strings are handled below before we ever reach this branch.
        if char == "#":
            while index < length and text[index] != "\n":
                index += 1
            continue

        if char in "{};":
            tokens.append(Token("punct", char, line))
            index += 1
            continue

        if char in ('"', "'"):
            quote = char
            index += 1
            buffer: list[str] = []
            while index < length and text[index] != quote:
                if text[index] == "\n":
                    line += 1
                elif text[index] == "\\" and index + 1 < length:
                    index += 1
                    buffer.append(text[index])
                else:
                    buffer.append(text[index])
                index += 1
            if index >= length:
                raise ConfigError(
                    f"unterminated quoted string starting on line {line}."
                )
            index += 1  # consume the closing quote
            tokens.append(Token("word", "".join(buffer), line))
            continue

        # A bare word: everything up to the next whitespace or structural
        # character.
        start = index
        while index < length and not text[index].isspace() and text[index] not in "{};\"'":
            index += 1
        tokens.append(Token("word", text[start:index], line))

    return tokens


def parse(text: str) -> list[Directive]:
    """Parse nginx configuration text into a tree of directives."""
    tokens = tokenize(text)
    position = 0

    def parse_block(depth: int) -> list[Directive]:
        nonlocal position
        directives: list[Directive] = []

        while position < len(tokens):
            token = tokens[position]

            if token.kind == "punct" and token.value == "}":
                if depth == 0:
                    raise ConfigError(f"unexpected '}}' on line {token.line}.")
                position += 1
                return directives

            if token.kind == "punct":
                raise ConfigError(
                    f"unexpected {token.value!r} on line {token.line}."
                )

            name = token.value
            line = token.line
            position += 1
            args: list[str] = []

            while position < len(tokens):
                current = tokens[position]
                if current.kind == "punct" and current.value == ";":
                    position += 1
                    directives.append(Directive(name, args, [], line))
                    break
                if current.kind == "punct" and current.value == "{":
                    position += 1
                    children = parse_block(depth + 1)
                    directives.append(Directive(name, args, children, line))
                    break
                if current.kind == "punct" and current.value == "}":
                    raise ConfigError(
                        f"directive {name!r} on line {line} is missing its ';'."
                    )
                args.append(current.value)
                position += 1
            else:
                raise ConfigError(
                    f"directive {name!r} on line {line} is not terminated."
                )

        if depth != 0:
            raise ConfigError("unbalanced braces: a block was never closed.")

        return directives

    parsed = parse_block(0)
    return parsed


# ---------------------------------------------------------------------------
# Finding the blocks we care about
# ---------------------------------------------------------------------------


def location_matcher(directive: Directive) -> str:
    """Return the matcher text of a `location` directive.

    For `location = /index.html` the matcher is `= /index.html`; for
    `location /assets/` it is `/assets/`.
    """
    return " ".join(directive.args).strip()


def find_locations(server: Directive) -> list[Directive]:
    """Return every `location` block directly inside `server`."""
    return server.find_all("location")


def server_blocks(configs: list[Directive]) -> list[Directive]:
    """Return every `server` block in the parsed configuration."""
    return [directive for directive in configs if directive.name == "server"]


def add_header_values(
    directive: Directive | list[Directive], header: str
) -> list[str]:
    """Return the values of every `add_header <header> ...` in a block.

    The comparison is case-insensitive because HTTP header names are.

    `directive` may be a single block (a `location`, say) or the top-level
    list of directives parsed from a file such as `security-headers.conf`.
    The latter has no enclosing block of its own — it is a flat list of
    `add_header` directives — so it is accepted directly rather than being
    wrapped in a synthetic parent.
    """
    roots = directive if isinstance(directive, list) else [directive]
    values: list[str] = []
    for root in roots:
        for child in root.walk():
            if child.name != "add_header":
                continue
            if not child.args:
                continue
            if child.args[0].lower() == header.lower():
                values.append(" ".join(child.args[1:]))
    return values


def cache_control_values(directive: Directive | list[Directive]) -> list[str]:
    """Return every `Cache-Control` value declared inside a block."""
    return add_header_values(directive, "Cache-Control")


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


@dataclass
class Report:
    """Collects check outcomes so the script can print one tidy summary."""

    passed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    def ok(self, message: str) -> None:
        """Record a passing check."""
        self.passed.append(message)

    def fail(self, message: str) -> None:
        """Record a failing check."""
        self.failed.append(message)

    def check(self, condition: bool, success: str, failure: str) -> bool:
        """Record a check and return its outcome."""
        if condition:
            self.ok(success)
        else:
            self.fail(failure)
        return condition


def run_checks(report: Report) -> None:
    """Run every check, recording the outcome in `report`."""
    # -- files exist -------------------------------------------------------
    if not report.check(
        NGINX_CONF.is_file(),
        f"found {NGINX_CONF.relative_to(REPO_ROOT)}",
        f"missing {NGINX_CONF.relative_to(REPO_ROOT)}",
    ):
        return

    if not report.check(
        SECURITY_HEADERS_CONF.is_file(),
        f"found {SECURITY_HEADERS_CONF.relative_to(REPO_ROOT)}",
        f"missing {SECURITY_HEADERS_CONF.relative_to(REPO_ROOT)}",
    ):
        return

    try:
        nginx_text = NGINX_CONF.read_text(encoding="utf-8")
        headers_text = SECURITY_HEADERS_CONF.read_text(encoding="utf-8")
    except OSError as exc:
        report.fail(f"could not read the configuration files: {exc}")
        return

    # -- the files parse ----------------------------------------------------
    try:
        nginx_config = parse(nginx_text)
    except ConfigError as exc:
        report.fail(f"{NGINX_CONF.relative_to(REPO_ROOT)} does not parse: {exc}")
        return

    try:
        headers_config = parse(headers_text)
    except ConfigError as exc:
        report.fail(
            f"{SECURITY_HEADERS_CONF.relative_to(REPO_ROOT)} does not parse: {exc}"
        )
        return

    report.ok(
        f"{NGINX_CONF.relative_to(REPO_ROOT)} and "
        f"{SECURITY_HEADERS_CONF.relative_to(REPO_ROOT)} parse cleanly"
    )

    servers = server_blocks(nginx_config)
    if not report.check(
        bool(servers),
        "nginx.conf declares a server block",
        "nginx.conf declares no server block",
    ):
        return

    server = servers[0]

    if not report.check(
        len(servers) == 1,
        "nginx.conf declares exactly one server block",
        f"nginx.conf declares {len(servers)} server blocks; expected exactly 1",
    ):
        # Not fatal: the remaining checks still describe the first server.
        pass

    locations = find_locations(server)
    if not report.check(
        bool(locations),
        "the server block declares location blocks",
        "the server block declares no location blocks",
    ):
        return

    # -- every location includes the shared security headers ----------------
    for location in locations:
        matcher = location_matcher(location)
        includes = [
            " ".join(child.args)
            for child in location.children
            if child.name == "include"
        ]
        has_include = any(
            SECURITY_HEADERS_INCLUDE in value or "security-headers.conf" in value
            for value in includes
        )
        report.check(
            has_include,
            f"location {matcher} includes security-headers.conf",
            f"location {matcher} does not include security-headers.conf; "
            "nginx drops inherited add_header directives from any location "
            "that declares its own",
        )

    # -- the shared file defines the headers we rely on ---------------------
    for header in REQUIRED_SECURITY_HEADERS:
        values = add_header_values(headers_config, header)
        report.check(
            len(values) == 1,
            f"security-headers.conf sets {header} exactly once",
            f"security-headers.conf sets {header} {len(values)} times; "
            "expected exactly once",
        )

    # -- every header is sent on error responses too ------------------------
    for directive in headers_config:
        if directive.name != "add_header":
            continue
        header = directive.args[0] if directive.args else "?"
        has_always = len(directive.args) > 1 and directive.args[-1] == "always"
        report.check(
            has_always,
            f"security header {header} is sent with 'always'",
            f"security header {header} is missing the 'always' parameter, so it "
            "is dropped on error responses",
        )

    # -- the headers must NOT be declared at server level --------------------
    server_level_headers = [
        child
        for child in server.children
        if child.name == "add_header"
    ]
    report.check(
        not server_level_headers,
        "no add_header is declared at server level",
        "an add_header is declared at server level; nginx discards inherited "
        "add_header directives in any location that declares its own, so "
        "security headers must stay in the included file",
    )

    # -- index.html must never be cached ------------------------------------
    index_locations = [
        location
        for location in locations
        if location_matcher(location) == "= /index.html"
    ]
    if report.check(
        bool(index_locations),
        "a 'location = /index.html' block exists",
        "no 'location = /index.html' block exists; a deploy could keep "
        "serving a stale bundle reference",
    ):
        index_block = index_locations[0]
        values = cache_control_values(index_block)
        report.check(
            len(values) == 1,
            "'= /index.html' declares exactly one Cache-Control header",
            f"'= /index.html' declares {len(values)} Cache-Control headers; "
            "expected exactly one",
        )
        if values:
            report.check(
                "no-cache" in values[0],
                "'= /index.html' is served with no-cache",
                f"'= /index.html' is served with {values[0]!r}; it must contain "
                "'no-cache'",
            )

    # -- hashed assets are cached, but with exactly one Cache-Control -------
    asset_locations = [
        location for location in locations if location_matcher(location) == "/assets/"
    ]
    if report.check(
        bool(asset_locations),
        "a 'location /assets/' block exists",
        "no 'location /assets/' block exists; hashed build assets would not be "
        "cached",
    ):
        assets = asset_locations[0]
        values = cache_control_values(assets)
        report.check(
            len(values) == 1,
            "'/assets/' declares exactly one Cache-Control header",
            f"'/assets/' declares {len(values)} Cache-Control headers; expected "
            "exactly one",
        )
        if values:
            report.check(
                "max-age" in values[0],
                "'/assets/' declares a long-lived Cache-Control",
                f"'/assets/' declares {values[0]!r}; it must contain 'max-age'",
            )
            report.check(
                "immutable" in values[0],
                "'/assets/' marks its Cache-Control immutable",
                f"'/assets/' declares {values[0]!r}; content-hashed assets "
                "should be immutable",
            )
        report.check(
            assets.find("expires") is None,
            "'/assets/' does not use the 'expires' directive",
            "'/assets/' uses the 'expires' directive; together with an "
            "add_header Cache-Control that emits two Cache-Control headers",
        )

    # -- the SPA fallback ---------------------------------------------------
    root_locations = [
        location for location in locations if location_matcher(location) == "/"
    ]
    if report.check(
        bool(root_locations),
        "a 'location /' block exists",
        "no 'location /' block exists; the single-page app would not be served",
    ):
        root = root_locations[0]
        try_files = root.find("try_files")
        if report.check(
            try_files is not None,
            "'/' uses try_files",
            "'/' does not use try_files; unknown paths would 404 instead of "
            "falling back to the single-page app",
        ):
            assert try_files is not None
            targets = " ".join(try_files.args)
            report.check(
                targets.rstrip().endswith("/index.html"),
                "'/' falls back to /index.html for unknown paths",
                f"'/' falls back to {targets!r}; it must end with '/index.html' "
                "so a deep link survives a page refresh",
            )

    # -- no block may emit two Cache-Control headers ------------------------
    for directive in nginx_config:
        for location in [
            child for child in directive.walk() if child.name == "location"
        ]:
            cache_controls = cache_control_values(location)
            has_expires = location.find("expires") is not None
            if has_expires and cache_controls:
                report.fail(
                    f"location {location_matcher(location)} uses both 'expires' "
                    "and an add_header Cache-Control, which emits two "
                    "Cache-Control headers"
                )
            elif len(cache_controls) > 1:
                report.fail(
                    f"location {location_matcher(location)} declares "
                    f"{len(cache_controls)} Cache-Control headers; expected one"
                )
            else:
                report.ok(
                    f"location {location_matcher(location)} emits at most one "
                    "Cache-Control header"
                )


def main() -> int:
    """Run the checks and print a PASS/FAIL report."""
    report = Report()
    run_checks(report)

    print("nginx configuration validation")
    print("=" * 60)
    for message in report.passed:
        print(f"PASS  {message}")
    for message in report.failed:
        print(f"FAIL  {message}")
    print("-" * 60)
    print(f"{len(report.passed)} passed, {len(report.failed)} failed")

    if report.failed:
        print("RESULT: FAIL")
        return 1

    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
