# Pull request

## What this changes

<!-- One or two sentences. What is different after this PR merges? -->

## Why

<!--
Link the issue it closes, e.g. "Closes #12".
If it is a task from CONTRIBUTING.md, say which one: "Task T3".
-->

## How it was verified

<!--
Tick the ones you actually ran, and paste the command and the result.
Do not claim something was verified unless you ran it.
-->

- [ ] `python -m pytest -q` — all tests pass
- [ ] `npm test` (in `frontend/`) — all tests pass
- [ ] `npx tsc -b` (in `frontend/`) — no type errors
- [ ] `npm run build` (in `frontend/`) — build succeeds
- [ ] `python tools/validate_analytics_sql.py`
- [ ] `python tools/validate_nginx.py`
- [ ] `python tools/verify_no_model_path.py`
- [ ] `node tools/validate-compose-real.js`
- [ ] The Docker stack was built and started, and the feature was exercised against it

## Honesty check

<!--
This project has hard rules about what may be claimed. Confirm them:
-->

- [ ] Nothing is described as "working" that I did not actually run.
- [ ] No simulated or demo data is presented as real.
- [ ] No capability that is unavailable is described as available.
- [ ] No metric is reported that I did not measure.
- [ ] No secret, credential, personal datum, dataset, or trained model file is included.

## Notes for the reviewer

<!-- Anything surprising, risky, or worth a second opinion. -->
