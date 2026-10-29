# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0, see LICENSE file for details.
"""
Eclipse "effective window", faithful port of the Varuna_Arjuna phone module.

Astrologically, an eclipse's influence is felt from about one calendar month
BEFORE to one calendar month AFTER the exact eclipse date. This module
computes that window with calendar-month arithmetic (day-of-month preserved,
clamped to the last valid day when the target month is shorter) and
classifies "today" against it. Pure Python, no GUI and no swisseph, so it is
trivially unit-testable and shared verbatim by the GUI panels and the CLI
tools (SPEC-ECL-002 section 7: one implementation, the tags and the JSON can
never disagree).

Port source: Varuna_Arjuna/lib/src/services/eclipse_window.dart (unchanged
since commit 361de12). Mixed frame rule, deliberate and matching the phone:
window boundaries derive from the UTC eclipse instant reduced to a calendar
date; "today" is the machine's LOCAL calendar date (only Y/M/D of any passed
value is read). Parity guard: test/test_eclipse_window.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional, Union

# How many calendar months the influence extends on EACH side of the peak.
ECLIPSE_INFLUENCE_MONTHS = 1

# English month abbreviations, 1-based lookup via [month - 1].
MONTH_ABBREV = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

# Upcoming eclipses further out than this show NO tag in list surfaces
# (deliberate, avoids flooding past-year lists). Applies ONLY to the list
# tag; the detail banner counts down with no cutoff.
_LIST_TAG_MAX_DAYS = 31

_MONTH_LENGTHS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)

DateLike = Union[date, datetime]


def _is_leap_year(year: int) -> bool:
    """Full Gregorian rule: 2024 yes, 2100 no, 2000 yes."""
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def _days_in_month(year: int, month: int) -> int:
    if month == 2 and _is_leap_year(year):
        return 29
    return _MONTH_LENGTHS[month - 1]


def add_months_clamped(d: DateLike, months: int) -> date:
    """Add ``months`` (may be negative) to a date, preserving the day-of-month
    and clamping to the last valid day when the target month is shorter
    (Jan 31 + 1 month = Feb 28, or Feb 29 in a leap year). Time-of-day is
    dropped: the result is always a plain ``date``.
    """
    total_months = d.year * 12 + (d.month - 1) + months
    year = total_months // 12
    month = total_months % 12 + 1
    day = min(d.day, _days_in_month(year, month))
    return date(year, month, day)


@dataclass(frozen=True)
class EclipseWindowStatus:
    """Result of :meth:`EclipseWindow.status_on`: the phase plus the day
    counts the badges display. Counters not applicable to the phase are None.
    """

    phase: str                                # 'upcoming' | 'active' | 'passed'
    starts_in_days: Optional[int] = None      # upcoming only
    ends_in_days: Optional[int] = None        # active only; 0 on the last day
    is_peak_day: bool = False                 # active only


@dataclass(frozen=True)
class EclipseWindow:
    """The effective window of one eclipse: [peak - 1 month, peak + 1 month],
    inclusive on both ends, at day precision.
    """

    start: date   # first day of influence
    peak: date    # the eclipse date itself
    end: date     # last day of influence, inclusive

    @classmethod
    def from_peak(cls, peak_utc: DateLike) -> "EclipseWindow":
        """Build from the eclipse's maximum instant (the UTC datetime the UI
        shows). Only the calendar date matters; the time-of-day is dropped
        FIRST, then the month arithmetic runs on the date.
        """
        peak = date(peak_utc.year, peak_utc.month, peak_utc.day)
        return cls(
            start=add_months_clamped(peak, -ECLIPSE_INFLUENCE_MONTHS),
            peak=peak,
            end=add_months_clamped(peak, ECLIPSE_INFLUENCE_MONTHS),
        )

    def status_on(self, today: Optional[DateLike] = None) -> EclipseWindowStatus:
        """Classify ``today`` against the window.

        ``None`` means the machine's LOCAL calendar date (the same frame the
        phone uses via ``DateTime.now()``). Any passed value contributes only
        its Y/M/D fields; time-of-day and timezone are ignored.
        """
        if today is None:
            today = date.today()
        day = date(today.year, today.month, today.day)
        if day < self.start:
            return EclipseWindowStatus(
                phase="upcoming",
                starts_in_days=(self.start - day).days,
            )
        if day > self.end:
            return EclipseWindowStatus(phase="passed")
        return EclipseWindowStatus(
            phase="active",
            ends_in_days=(self.end - day).days,
            is_peak_day=(day == self.peak),
        )


# ---------------------------------------------------------------------------
# Shared TEXT helpers (pure functions, used by both the GUI and the CLI so
# the two surfaces can never disagree). English only, like the desktop app.
# ---------------------------------------------------------------------------

def _in_days(days: int) -> str:
    return "in 1 day" if days == 1 else f"in {days} days"


def format_short_date(d: date) -> str:
    """'12 Aug 2026' (D Mon YYYY, no zero padding), the phone's peak format."""
    return f"{d.day} {MONTH_ABBREV[d.month - 1]} {d.year}"


def list_tag_text(status: EclipseWindowStatus) -> Optional[str]:
    """Per-row status tag for list surfaces (results table, year dropdown,
    saros member list). Phone rule (eclipse_screen.dart _statusTag):

    - active: '● ACTIVE' (render red, semantic alert color)
    - upcoming and starts_in_days <= 31: 'in N days' ('in 1 day' singular)
    - otherwise (passed, or upcoming beyond the cutoff): None, no tag
    """
    if status.phase == "active":
        return "● ACTIVE"
    if status.phase == "upcoming" and status.starts_in_days <= _LIST_TAG_MAX_DAYS:
        return _in_days(status.starts_in_days)
    return None


def banner_text(status: EclipseWindowStatus, peak_date: date) -> str:
    """Live status banner for the detail surface, phone composition
    (eclipse_detail_screen.dart _windowBanner), segments joined with ' · ':

    - active: 'ACTIVE NOW · Peak today · Ends in N days' (or
      'Peak: D Mon YYYY' when today is not the peak; 'Ends in 1 day'
      singular; 'Ends today' on the last day)
    - upcoming: 'Starts in N days' ('Starts in 1 day' singular), NO cutoff
    - passed: 'Passed'
    """
    if status.phase == "active":
        peak_part = ("Peak today" if status.is_peak_day
                     else f"Peak: {format_short_date(peak_date)}")
        days = status.ends_in_days
        if days == 0:
            ends_part = "Ends today"
        elif days == 1:
            ends_part = "Ends in 1 day"
        else:
            ends_part = f"Ends in {days} days"
        return f"ACTIVE NOW · {peak_part} · {ends_part}"
    if status.phase == "upcoming":
        days = status.starts_in_days
        return "Starts in 1 day" if days == 1 else f"Starts in {days} days"
    return "Passed"


def window_line_text(window: EclipseWindow) -> str:
    """Persistent window line, e.g. 'Active window: 12 Jul to 12 Sep 2026'.

    The year appears once when both ends share it, on both sides when they
    differ (phone's eclipseWindowRange, with 'to' as the separator per
    SPEC-ECL-002 section 7.2).
    """
    end_part = format_short_date(window.end)
    if window.start.year == window.end.year:
        start_part = f"{window.start.day} {MONTH_ABBREV[window.start.month - 1]}"
    else:
        start_part = format_short_date(window.start)
    return f"Active window: {start_part} to {end_part}"


def window_json(window: EclipseWindow, status: EclipseWindowStatus) -> dict:
    """CLI 'window' object (SPEC-ECL-002 section 7.3): ISO dates, counters
    null when not applicable to the current phase.
    """
    return {
        "start": window.start.isoformat(),
        "end": window.end.isoformat(),
        "phase": status.phase,
        "starts_in_days": status.starts_in_days,
        "ends_in_days": status.ends_in_days,
        "is_peak_day": status.is_peak_day,
    }
