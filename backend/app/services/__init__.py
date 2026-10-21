"""Service layer: business logic that sits between routers and models.

Routers stay thin (validate → call a service → return). Anything with real
rules — the alert engine, KPI computation — lives here so it can be unit-tested
without HTTP and reused by scripts and exports.
"""
