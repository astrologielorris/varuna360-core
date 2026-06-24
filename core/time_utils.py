# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Time conversion utilities for CHTK timezone handling.

Extracted from legacy ui/chart_edit_components.py — these are pure functions
with no GUI dependencies.
"""

import logging
from datetime import datetime, timedelta
from typing import Tuple

from libaditya import swe

GREGORIAN_REFORM_JD = 2299160.5


def _calendar_flag(year, month, day):
    """Return swe.JUL_CAL for dates before the Gregorian reform (Oct 15, 1582)."""
    if (year < 1582) or (year == 1582 and month < 10) or \
       (year == 1582 and month == 10 and day < 15):
        return swe.JUL_CAL
    return swe.GREG_CAL


def _calendar_flag_from_jd(jd_val):
    """Return swe.JUL_CAL for Julian Day numbers before the Gregorian reform."""
    return swe.JUL_CAL if jd_val < GREGORIAN_REFORM_JD else swe.GREG_CAL


def julday(year, month, day, hour_decimal, cal_flag=None):
    """Convert calendar date to Julian Day number.

    Auto-detects Julian/Gregorian calendar if cal_flag is not provided.
    """
    if cal_flag is None:
        cal_flag = _calendar_flag(year, month, day)
    return swe.julday(year, month, day, hour_decimal, cal_flag)


def revjul(jd_val, cal_flag=None):
    """Convert Julian Day number to calendar date (year, month, day, hour_decimal).

    Auto-detects Julian/Gregorian calendar if cal_flag is not provided.
    """
    if cal_flag is None:
        cal_flag = _calendar_flag_from_jd(jd_val)
    return swe.revjul(jd_val, cal_flag)


def invert_chtk_timezone(tz_str: str) -> str:
    """
    Invert CHTK timezone offset to standard format.

    CHTK uses OPPOSITE sign convention from standard UTC offsets:
      CHTK '-01:00:00' = UTC+1 (standard '+01:00')
      CHTK '+08:00:00' = UTC-8 (standard '-08:00')

    Args:
        tz_str: Timezone offset in CHTK format (e.g., '-01:00:00')

    Returns:
        Timezone offset in standard format (e.g., '+01:00:00')
    """
    tz_str = tz_str.strip()
    if tz_str.startswith('+'):
        return '-' + tz_str[1:]
    elif tz_str.startswith('-'):
        return '+' + tz_str[1:]
    return '-' + tz_str  # Unsigned treated as positive CHTK -> negative standard


def _parse_offset(timezone_offset: str, ref_year: int = 2000) -> Tuple[int, int]:
    """Parse a timezone string into (hours, minutes) with sign applied.

    Accepts both +HH:MM offset strings and IANA names (e.g. "Europe/Paris").
    For IANA names, returns the STANDARD offset (no DST) via decompose-from-total
    (resolve_total_offset) probed at Jan 15 of ref_year. This handles
    negative-DST zones correctly: Europe/Dublin at Jan 15 already returns the
    correct winter standard 0.0. The remaining limitation is inherent to a
    date-less probe: it cannot know the birth season, so callers needing
    season-specific data (e.g. Dublin summer +1.0) should call
    resolve_total_offset with the actual birth date instead.
    """
    if not timezone_offset:
        return 0, 0
    tz = timezone_offset.strip()
    if '/' in tz:
        try:
            # recursion guard: resolve_total_offset's year < 1 branch calls back
            # into _parse_offset with ref_year=1; max() keeps this terminating.
            # Do not remove.
            std_hours, _flag = resolve_total_offset(tz, max(ref_year, 1), 1, 15)
            total_minutes = int(round(std_hours * 60))
            sign = 1 if total_minutes >= 0 else -1
            am = abs(total_minutes)
            return sign * (am // 60), sign * (am % 60)
        except Exception:
            # Callers depend on the UTC+0 fallback (do not raise), but a typo
            # like "Europe/Pris" must not pass silently.
            logging.warning(
                "_parse_offset: failed to resolve %r, falling back to UTC+0",
                timezone_offset)
            return 0, 0
    if tz and tz[0] not in ('+', '-'):
        tz = '+' + tz
    if tz.startswith('+') or tz.startswith('-'):
        sign = 1 if tz.startswith('+') else -1
        parts = tz[1:].split(':')
        return sign * int(parts[0]), sign * int(parts[1]) if len(parts) > 1 else 0
    return 0, 0


def format_offset(hours: int, minutes: int) -> str:
    """Format (hours, minutes) tuple as '+HH:MM' offset string.

    Inverse of _parse_offset. Handles negative fractional offsets correctly
    by working in total minutes: (-3, -30) -> '-03:30'.
    """
    total_minutes = hours * 60 + minutes
    sign = '+' if total_minutes >= 0 else '-'
    abs_m = abs(total_minutes)
    return f"{sign}{abs_m // 60:02d}:{abs_m % 60:02d}"


def resolve_total_offset(iana_name: str, year: int, month: int, day: int,
                         hour: int = 12, minute: int = 0,
                         longitude: float = None) -> Tuple[float, int]:
    """Resolve an IANA zone at the birth instant; decompose-from-total.

    Contract (SPEC-TZ-001 Sections 1, 5g): the returned std_hours + dst_flag
    equals the pytz TOTAL offset at that instant, always. The TOTAL is the
    only value that reaches the Julian Day; the decomposition exists for
    storage/display. Never returns flag 2 (war time is user-asserted only).
    Never instantiates TimezoneFinder. Propagates pytz.UnknownTimeZoneError
    and other lookup errors to the caller (callers keep their own
    resilience).

    For year < 1 (pytz cannot localize BCE dates), returns the
    _parse_offset ref_year=1 STANDARD offset as float hours with flag 0.

    Labeling notes (correct TOTALs, do not "fix"):
    - Dublin-class negative-DST zones: winter -> (0.0, 0), summer -> (1.0, 0)
      (IANA labels IST as standard; dst > 0 never fires).
    - dst not equal to 1h (London 1943 double summer dst=2h, Lord Howe
      dst=0.5h): the FLAG is subtracted, not the dst, so std is
      unconventionally labeled for those zones; the invariant holds.

    Args:
        iana_name: IANA zone name (e.g. "Europe/Paris")
        year, month, day, hour, minute: local birth instant (noon default)

    Returns:
        Tuple of (std_hours: float, dst_flag: int in {0, 1})
    """
    if year < 1:
        h, m = _parse_offset(iana_name, ref_year=1)
        return h + m / 60.0, 0
    import pytz
    tz = pytz.timezone(iana_name)
    dt = datetime(year, month, day, hour, minute)
    try:
        aware = tz.localize(dt, is_dst=None)
    except (pytz.exceptions.AmbiguousTimeError, pytz.exceptions.NonExistentTimeError):
        # Fold/gap instants: deterministic standard-time interpretation
        aware = tz.localize(dt, is_dst=False)
    # LMT correction: IANA returns the capital's LMT, not the chart city's.
    if longitude is not None and aware.tzname() == 'LMT':
        return longitude / 15.0, 0

    total = aware.utcoffset().total_seconds() / 3600.0
    dst = aware.dst().total_seconds() / 3600.0
    # Subtract the FLAG, not the dst: keeps std + flag == total even when
    # dst is 2h or 0.5h (pm-20260610-101). Negative DST (Dublin winter)
    # lands in the else branch: std = total, flag 0.
    flag = 1 if dst > 0 else 0
    return total - flag, flag


def lmt_corrected_offset(tz_name: str, year: int, month: int, day: int,
                         hour: int, minute: int, second: int,
                         longitude: float) -> float:
    """Get UTC offset in hours, correcting for LMT-era dates.

    ZoneInfo returns the capital's LMT for pre-standardization dates
    (e.g. Berlin's LMT +0:53 for all of Europe/Berlin before 1893).
    For astrology, LMT must be computed from the chart city's longitude.
    """
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(tz_name)
    dt = datetime(year, month, day, hour, minute, second, tzinfo=tz)

    if dt.tzname() == 'LMT':
        return longitude / 15.0

    dt_fold1 = dt.replace(fold=1)
    if dt.utcoffset() != dt_fold1.utcoffset():
        dt = dt_fold1

    return dt.utcoffset().total_seconds() / 3600.0


def local_to_utc(
    year: int, month: int, day: int,
    hour: int, minute: int, second: int,
    timezone_offset: str,
    dst_flag: int = 0
) -> Tuple[int, int, int, int, int, int]:
    """
    Convert local time to UTC using timezone offset string.

    Args:
        year, month, day, hour, minute, second: Local time components
        timezone_offset: Offset string like "+05:30" or "-08:00" (standard time offset)
        dst_flag: 0 = no DST, 1 = DST (+1h), 2 = War Time (+2h).
                  Also accepts True/False for backward compatibility (True -> 1).

    Returns:
        Tuple of (year, month, day, hour, minute, second) in UTC

    Raises:
        ValueError: If timezone_offset cannot be parsed
    """
    if isinstance(dst_flag, bool):
        dst_flag = int(dst_flag)

    # ref_year=year: IANA standard offsets change through history
    # (Paris +00:00 in 1920, +01:00 today), td-cj4j
    offset_hours, offset_minutes = _parse_offset(timezone_offset, ref_year=year)

    if dst_flag in (1, 2):
        offset_hours += dst_flag

    if year >= 1:
        local_dt = datetime(year, month, day, hour, minute, second)
        utc_dt = local_dt - timedelta(hours=offset_hours, minutes=offset_minutes)
        return (utc_dt.year, utc_dt.month, utc_dt.day,
                utc_dt.hour, utc_dt.minute, utc_dt.second)

    return _manual_offset(year, month, day, hour, minute, second,
                          -offset_hours, -offset_minutes)


def local_to_utc_total(year, month, day, hour, minute, second,
                       total_offset_hours):
    """local -> UTC with a TOTAL numeric offset (DST already included).

    Companion to local_to_utc (which takes a STANDARD offset string plus
    dst_flag). Never bakes DST into a string (SPEC-TZ-001 Section 1).
    BCE-safe via _manual_offset.
    """
    if year >= 1:
        local_dt = datetime(year, month, day, hour, minute, second)
        utc_dt = local_dt - timedelta(hours=total_offset_hours)
        return (utc_dt.year, utc_dt.month, utc_dt.day,
                utc_dt.hour, utc_dt.minute, utc_dt.second)
    return _manual_offset(year, month, day, hour, minute, second,
                          -total_offset_hours, 0)


def _manual_offset(year, month, day, hour, minute, second,
                   delta_hours, delta_minutes):
    """Apply hour/minute delta without datetime (handles BCE years)."""
    def _days_in_month(y, m):
        base = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
        if m == 2 and y % 4 == 0:
            return 29
        return base[m - 1]

    total_seconds = hour * 3600 + minute * 60 + second
    total_seconds += round(delta_hours * 3600) + round(delta_minutes * 60)

    if total_seconds < 0:
        total_seconds += 86400
        day -= 1
        if day < 1:
            month -= 1
            if month < 1:
                month = 12
                year -= 1
            day = _days_in_month(year, month)
    elif total_seconds >= 86400:
        total_seconds -= 86400
        day += 1
        if day > _days_in_month(year, month):
            day = 1
            month += 1
            if month > 12:
                month = 1
                year += 1

    return (year, month, day,
            total_seconds // 3600, (total_seconds % 3600) // 60,
            total_seconds % 60)


def utc_to_local(
    year: int, month: int, day: int,
    hour: int, minute: int, second: int,
    timezone_offset: str,
    dst_flag: int = 0
) -> Tuple[int, int, int, int, int, int]:
    """
    Convert UTC time to local time using timezone offset string.

    Args:
        year, month, day, hour, minute, second: UTC time components
        timezone_offset: Offset string like "+05:30" or "-08:00" (standard time offset)
        dst_flag: 0 = no DST, 1 = DST (+1h), 2 = War Time (+2h).
                  Also accepts True/False for backward compatibility (True -> 1).

    Returns:
        Tuple of (year, month, day, hour, minute, second) in local time

    Raises:
        ValueError: If timezone_offset cannot be parsed
    """
    if isinstance(dst_flag, bool):
        dst_flag = int(dst_flag)

    # ref_year=year: same historical-offset rule as local_to_utc (td-cj4j)
    offset_hours, offset_minutes = _parse_offset(timezone_offset, ref_year=year)

    if dst_flag in (1, 2):
        offset_hours += dst_flag

    if year >= 1:
        utc_dt = datetime(year, month, day, hour, minute, second)
        local_dt = utc_dt + timedelta(hours=offset_hours, minutes=offset_minutes)
        return (local_dt.year, local_dt.month, local_dt.day,
                local_dt.hour, local_dt.minute, local_dt.second)

    return _manual_offset(year, month, day, hour, minute, second,
                          offset_hours, offset_minutes)
