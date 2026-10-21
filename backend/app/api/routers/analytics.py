"""Analytics endpoints: KPI results and Power BI-ready CSV exports.

Design notes
------------
* **No invented numbers.** Every KPI comes from `kpi_service`, which reads real
  rows. A KPI that cannot be measured is returned with `is_measurable: false`
  and a reason, never with a plausible-looking placeholder.
* **Date range is mandatory** on the KPI endpoints. A KPI without its window is
  meaningless, so the window is a required parameter rather than an optional
  filter with a hidden default.
* **Access.** Admins and analysts may read aggregates. Caregivers do not get a
  cross-resident aggregate feed here; they see their residents' alerts through
  the alert endpoints. This keeps the analytics surface free of personal detail
  and matches the existing `get_accessible_profile` policy, which deliberately
  excludes analysts from raw care records.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from backend.app.core.deps import require_roles
from backend.app.core.errors import ValidationError
from backend.app.db.base import get_db
from backend.app.models.enums import UserRole
from backend.app.models.identity import User
from backend.app.services import kpi_service
from backend.app.services.kpi_definitions import ALL_KPIS, KpiDefinition
from backend.app.services.kpi_service import KpiWindow

router = APIRouter(tags=["Analytics"])

# Admins and analysts may read aggregates. Analysts exist precisely for this.
ANALYTICS_ROLES = (UserRole.ADMIN, UserRole.ANALYST)


def _build_window(start: datetime, end: datetime) -> KpiWindow:
    """Validate and build the reporting window."""
    try:
        return KpiWindow(start=start, end=end)
    except ValueError as exc:
        raise ValidationError(
            "The reporting window is invalid: 'end' must be after 'start'.",
            code="INVALID_WINDOW",
            details={"start": start.isoformat(), "end": end.isoformat()},
        ) from exc


@router.get(
    "/analytics/kpis",
    summary="Compute the KPI catalogue for a date range",
    description=(
        "Returns every KPI with its value, numerator, denominator, window, and "
        "an explicit note on how missing data was handled.\n\n"
        "**A KPI whose data cannot support a value is returned with "
        "`is_measurable: false` and a reason — never a made-up number.**\n\n"
        "**Access:** admin or analyst."
    ),
    responses={403: {"description": "Your role cannot read analytics."}},
)
def get_kpis(
    start: datetime = Query(..., description="Window start (inclusive, ISO 8601)."),
    end: datetime = Query(..., description="Window end (exclusive, ISO 8601)."),
    current_user: User = Depends(require_roles(*ANALYTICS_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Compute all KPIs for the requested window."""
    window = _build_window(start, end)
    results = kpi_service.compute_all_kpis(db, window)
    return {
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "kpis": [r.as_dict() for r in results],
        "note": (
            "Values are computed from stored rows only. `is_measurable: false` "
            "means the data cannot support a value for this window."
        ),
    }


@router.get(
    "/analytics/kpi-definitions",
    summary="List the formal definition of every KPI",
    description=(
        "Returns each KPI's numerator, denominator, unit, and missing-data "
        "handling, straight from the catalogue the calculations use. This makes "
        "it possible to read a number and its definition together.\n\n"
        "**Access:** admin or analyst."
    ),
)
def list_kpi_definitions(
    current_user: User = Depends(require_roles(*ANALYTICS_ROLES)),
) -> dict[str, object]:
    """Return the KPI catalogue itself (no data queried)."""

    def shape(definition: KpiDefinition) -> dict[str, str]:
        return {
            "key": definition.key,
            "name": definition.name,
            "unit": definition.unit.value,
            "numerator": definition.numerator_description,
            "denominator": definition.denominator_description,
            "missing_data_handling": definition.missing_data_handling,
            "notes": definition.notes,
        }

    return {"definitions": [shape(d) for d in ALL_KPIS]}


@router.get(
    "/analytics/kpis.csv",
    summary="Download the KPI results for a date range as CSV",
    description=(
        "The same values as `/analytics/kpis`, as a CSV file Power BI can "
        "import directly. Included so a report can be refreshed without a "
        "separate export script.\n\n"
        "**Access:** admin or analyst."
    ),
)
def get_kpis_csv(
    start: datetime = Query(..., description="Window start (inclusive, ISO 8601)."),
    end: datetime = Query(..., description="Window end (exclusive, ISO 8601)."),
    current_user: User = Depends(require_roles(*ANALYTICS_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    """Return the KPI results as a downloadable CSV."""
    window = _build_window(start, end)
    results = kpi_service.compute_all_kpis(db, window)

    buffer = io.StringIO()
    rows = [r.as_dict() for r in results]
    if rows:
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    filename = f"elderlife_kpis_{start:%Y%m%d}_{end:%Y%m%d}.csv"
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
