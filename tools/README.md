# Tools

Offline validators. Each one is a single file with no third-party
dependencies, and each one exits `0` on success and non-zero on failure, so
they can be used as CI gates.

| Command | What it checks |
|---------|----------------|
| `python tools/validate_analytics_sql.py` | Every table and column named in `analytics/sql/` really exists in the SQLAlchemy models. |
| `python tools/validate_nginx.py` | The frontend nginx configuration really applies the security headers, the cache rules and the SPA fallback it claims to. |
| `python tools/verify_no_model_path.py` | The AI layer never invents a model, a metric or a prediction. |
| `node tools/validate-compose-real.js` | `docker-compose.yml` describes a stack that would actually start and would not wait on the wrong things. |

None of them needs a database, a network connection, a dataset or a
container. They read files and exit.

## Why these exist

Each of these checks guards against a failure that is invisible until
something breaks in production:

* **A typo in a SQL column name** is not a syntax error. PostgreSQL creates
  the view happily and the error only appears when somebody runs the query —
  which, for a KPI in the README, means a wrong number.
* **nginx does not merge `add_header` across levels.** A `location` block
  that declares its own `Cache-Control` silently discards the security
  headers inherited from the `server` block. The headers in this repository
  therefore live in an included file, and `validate_nginx.py` checks that
  every location still includes it.
* **A hard-coded accuracy number is indistinguishable from a measured one**
  in an API response. `verify_no_model_path.py` checks the behaviour *and*
  parses the source, so a literal metric value is caught where it is written.
* **A Compose file that "looks right"** can still build the backend from the
  wrong directory, or run a healthcheck with a tool the image does not
  contain. Both failures happen at start-up, in the one moment you least
  want to be reading YAML.

## Running them

From the repository root:

```bash
python tools/validate_analytics_sql.py
python tools/validate_nginx.py
python tools/verify_no_model_path.py
node tools/validate-compose-real.js
```

The first three need Python 3.11 or newer on `PATH`; the last one needs Node
18 or newer. `verify_no_model_path.py` imports `ai.registry`, so it must be
run from the repository root (it adds the repository root to `sys.path`
itself, so the working directory does not matter).

## Adding a validator

Keep the shape consistent with the existing ones:

* a module docstring that says **why** the check exists, not what it does;
* `from __future__ import annotations` and type hints;
* a `Report`-style collector so the output is a list of `PASS`/`FAIL` lines
  followed by a summary and a final `RESULT: PASS` or `RESULT: FAIL`;
* exit `0` on success and `1` on failure;
* no network, no database, no dataset — the whole point is that the check
  runs anywhere, including in a pull request from a fork.
