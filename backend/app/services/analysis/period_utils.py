"""Analysis page date-range and comparison-period resolution.

Extends `app.services.reports.dashboard_service.resolve_period()`'s exact
pattern (same tenant-FY-aware logic, same style) rather than replacing it —
`THIS_MONTH`/`THIS_WEEK`/`THIS_FY`/`CUSTOM` behave identically to the
Dashboard's own resolver so a shared period label means the same date range
everywhere in the app. This module only adds the presets the Analysis page
needs that the Dashboard doesn't: `YESTERDAY`, `LAST_WEEK`, `LAST_MONTH`,
`THIS_QUARTER`, `PREVIOUS_FY` — plus comparison-period resolution, which has
no prior implementation anywhere in this codebase.

**"This Quarter" is a FINANCIAL quarter** (Q1=Apr-Jun ... Q4=Jan-Mar,
anchored to `tenant.financial_year_start_month`), not a calendar quarter —
a judgment call made for consistency with this module's FY-anchored date
framework (§5 of the source spec only says "This Quarter" without
specifying calendar vs. fiscal); flagged here, not silently assumed
elsewhere.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import Decimal

from app.models.tenant import Tenant

TODAY = "TODAY"
YESTERDAY = "YESTERDAY"
THIS_WEEK = "THIS_WEEK"
LAST_WEEK = "LAST_WEEK"
THIS_MONTH = "THIS_MONTH"
LAST_MONTH = "LAST_MONTH"
THIS_QUARTER = "THIS_QUARTER"
THIS_FY = "THIS_FY"
PREVIOUS_FY = "PREVIOUS_FY"
CUSTOM = "CUSTOM"

ANALYSIS_PERIODS = frozenset({
    TODAY, YESTERDAY, THIS_WEEK, LAST_WEEK, THIS_MONTH, LAST_MONTH, THIS_QUARTER, THIS_FY, PREVIOUS_FY, CUSTOM,
})

COMPARE_PREVIOUS_PERIOD = "PREVIOUS_PERIOD"
COMPARE_PREVIOUS_MONTH = "PREVIOUS_MONTH"
COMPARE_PREVIOUS_QUARTER = "PREVIOUS_QUARTER"
COMPARE_PREVIOUS_FY = "PREVIOUS_FY"
COMPARE_CUSTOM = "CUSTOM"
COMPARE_NONE = "NONE"

COMPARISON_MODES = frozenset({
    COMPARE_PREVIOUS_PERIOD, COMPARE_PREVIOUS_MONTH, COMPARE_PREVIOUS_QUARTER, COMPARE_PREVIOUS_FY, COMPARE_CUSTOM, COMPARE_NONE,
})


def _shift_months(d: date, months: int) -> date:
    """Shift a date back/forward by whole calendar months, clamping the day
    to the shifted month's own last day (e.g. Mar 31 - 1 month -> Feb 28/29)
    — pure stdlib, no new dependency added for this."""
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _fy_start(tenant: Tenant, as_of: date) -> date:
    start_month = tenant.financial_year_start_month
    fy_start_year = as_of.year if as_of.month >= start_month else as_of.year - 1
    return date(fy_start_year, start_month, 1)


def resolve_analysis_period(*, tenant: Tenant, period: str, custom_from: date | None, custom_to: date | None) -> tuple[date, date]:
    today = date.today()

    if period == TODAY:
        return today, today
    if period == YESTERDAY:
        y = today - timedelta(days=1)
        return y, y
    if period == THIS_WEEK:
        return today - timedelta(days=today.weekday()), today
    if period == LAST_WEEK:
        this_week_start = today - timedelta(days=today.weekday())
        last_week_end = this_week_start - timedelta(days=1)
        last_week_start = last_week_end - timedelta(days=6)
        return last_week_start, last_week_end
    if period == THIS_MONTH:
        return today.replace(day=1), today
    if period == LAST_MONTH:
        last_month_end = today.replace(day=1) - timedelta(days=1)
        return last_month_end.replace(day=1), last_month_end
    if period == THIS_QUARTER:
        fy_start = _fy_start(tenant, today)
        months_into_fy = (today.year - fy_start.year) * 12 + (today.month - fy_start.month)
        quarter_index = months_into_fy // 3
        quarter_start = _shift_months(fy_start, quarter_index * 3)
        return quarter_start, today
    if period == THIS_FY:
        return _fy_start(tenant, today), today
    if period == PREVIOUS_FY:
        this_fy_start = _fy_start(tenant, today)
        prev_fy_start = _shift_months(this_fy_start, -12)
        prev_fy_end = this_fy_start - timedelta(days=1)
        return prev_fy_start, prev_fy_end
    # CUSTOM
    return custom_from or today, custom_to or today


def resolve_comparison_period(
    *, mode: str, date_from: date, date_to: date, custom_from: date | None = None, custom_to: date | None = None,
) -> tuple[date, date] | None:
    """Returns the comparison (date_from, date_to) for the given primary
    range, or None for COMPARE_NONE/when custom bounds are missing."""
    if mode == COMPARE_NONE:
        return None
    if mode == COMPARE_PREVIOUS_PERIOD:
        duration_days = (date_to - date_from).days + 1
        prev_to = date_from - timedelta(days=1)
        prev_from = prev_to - timedelta(days=duration_days - 1)
        return prev_from, prev_to
    if mode == COMPARE_PREVIOUS_MONTH:
        return _shift_months(date_from, -1), _shift_months(date_to, -1)
    if mode == COMPARE_PREVIOUS_QUARTER:
        return _shift_months(date_from, -3), _shift_months(date_to, -3)
    if mode == COMPARE_PREVIOUS_FY:
        return _shift_months(date_from, -12), _shift_months(date_to, -12)
    # CUSTOM
    if custom_from is None or custom_to is None:
        return None
    return custom_from, custom_to


def safe_percent_change(current: Decimal, previous: Decimal | None) -> Decimal | None:
    """Percentage change from `previous` to `current`. Returns None (never
    a fabricated/misleading number) when `previous` is None or zero — the
    frontend must render this as "N/A", not "0%" or "∞%"."""
    if previous is None or previous == 0:
        return None
    return ((current - previous) / previous) * Decimal("100")
