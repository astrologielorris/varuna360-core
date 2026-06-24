# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Dasha calculation module for CLI and AI tools.
================================================
Reusable functions that mirror the GUI dasha code path exactly:

  CLI:  show_dasha.py → dasha.py → core/vimshottari_dasha.py
  GUI:  dasha_manager.py ─────────→ core/vimshottari_dasha.py

All calculations delegate to core.vimshottari_dasha — zero re-implementation.
"""

import json
import os
import sys
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.time_utils import (
    julday,
    _parse_offset,
    invert_chtk_timezone,
    resolve_total_offset,
)

from core.chtk_reader import CHTKReader
from core.vimshottari_dasha import (
    calculate_dasha_from_birth_data,
    get_moon_nakshatra_bridge,
)
from .constants import DEFAULT_CHTK

# =============================================================================
# Section 1: Nakshatra Constants (future-proof for planet-nakshatra feature)
# =============================================================================

NAKSHATRA_NAMES_27 = [
    "Ashvini", "Bharani", "Krittika", "Rohini", "Mrigashira",
    "Ardra", "Punarvasu", "Pushya", "Ashlesha", "Magha",
    "Purva Phalguni", "Uttara Phalguni", "Hasta", "Chitra", "Svati",
    "Vishakha", "Anuradha", "Jyeshtha", "Mula", "Purva Ashadha",
    "Uttara Ashadha", "Shravana", "Dhanishta", "Shatabhisha",
    "Purva Bhadrapada", "Uttara Bhadrapada", "Revati",
]

NAKSHATRA_NAMES_28 = [
    "Ashvini", "Bharani", "Krittika", "Rohini", "Mrigashira",
    "Ardra", "Punarvasu", "Pushya", "Ashlesha", "Magha",
    "Purva Phalguni", "Uttara Phalguni", "Hasta", "Chitra", "Svati",
    "Vishakha", "Anuradha", "Jyeshtha", "Mula", "Purva Ashadha",
    "Uttara Ashadha", "Abhijit", "Shravana", "Dhanishta", "Shatabhisha",
    "Purva Bhadrapada", "Uttara Bhadrapada", "Revati",
]

# =============================================================================
# Section 2: Nakshatra Name Lookup
# =============================================================================

def get_moon_nakshatra_name(jd, ayanamsa=98):
    """
    Get Moon's nakshatra with human-readable name.

    Uses libaditya bridge.

    Args:
        jd: Julian Day number (UT)
        ayanamsa: Ayanamsa ID (98=Dhruva, 1=Lahiri, 999=Tropical, etc.)

    Returns:
        (name, index, longitude_from_ashvini)
    """
    longitude, index = get_moon_nakshatra_bridge(jd, ayanamsa=ayanamsa)
    names = NAKSHATRA_NAMES_27
    name = names[index] if 0 <= index < len(names) else f"Nak#{index}"
    return name, index, longitude


# =============================================================================
# Section 3: Ayanamsa Name Resolution
# =============================================================================

# Core aliases — no PySide6 dependency
_AYANAMSA_ALIASES = {
    "dhruva": 98,
    "dhruva_gc": 98,
    "vedanga": 100,
    "vedanga_jyotisha": 100,
    "tropical": 999,
    "lahiri": 1,
    "kp": 5,
    "krishnamurti": 5,
    "raman": 3,
    "fagan": 0,
    "fagan_bradley": 0,
    "yukteshwar": 7,
    "true_citra": 27,
}

# Try to extend with full names from ayanamsa_dialog.py (graceful fallback)
_AYANAMSA_FULL_LIST = None
try:
    from core.ayanamsa_data import AYANAMSA_OPTIONS
    _AYANAMSA_FULL_LIST = AYANAMSA_OPTIONS
    # Build reverse lookup: lowercase name → id
    for aid, aname, _cat, _tip in AYANAMSA_OPTIONS:
        key = aname.lower().replace(" ", "_").replace("(", "").replace(")", "").replace("°", "")
        _AYANAMSA_ALIASES[key] = aid
except ImportError:
    pass


def resolve_ayanamsa(value_str):
    """
    Resolve an ayanamsa from a string — accepts numeric ID or name.

    Examples:
        resolve_ayanamsa("98")      → 98
        resolve_ayanamsa("lahiri")  → 1
        resolve_ayanamsa("dhruva")  → 98
        resolve_ayanamsa("tropical") → 999

    Returns:
        int: Ayanamsa ID

    Raises:
        ValueError: If the value cannot be resolved
    """
    s = value_str.strip()

    # Try numeric first
    try:
        return int(s)
    except ValueError:
        pass

    # Try name lookup (case-insensitive, underscores and spaces interchangeable)
    key = s.lower().replace(" ", "_").replace("-", "_")
    if key in _AYANAMSA_ALIASES:
        return _AYANAMSA_ALIASES[key]

    # Partial match fallback
    for alias, aid in _AYANAMSA_ALIASES.items():
        if key in alias or alias in key:
            return aid

    raise ValueError(
        f"Unknown ayanamsa: '{value_str}'. "
        f"Use a numeric ID or name like: dhruva, lahiri, tropical, kp, raman, vedanga"
    )


def list_ayanamsas():
    """
    Return a formatted listing of all available ayanamsas.

    Returns:
        str: Multi-line formatted text
    """
    lines = ["Available Ayanamsas:", "=" * 60]

    if _AYANAMSA_FULL_LIST:
        current_category = None
        for aid, aname, category, tooltip in _AYANAMSA_FULL_LIST:
            if category != current_category:
                current_category = category
                lines.append(f"\n  {category}:")
                lines.append(f"  {'-' * 40}")
            lines.append(f"    {aid:>3}  {aname}")
    else:
        # Fallback: show core aliases only
        lines.append("\n  Core aliases (full list requires PySide6):")
        seen = set()
        for alias, aid in sorted(_AYANAMSA_ALIASES.items(), key=lambda x: x[1]):
            if aid not in seen:
                seen.add(aid)
                lines.append(f"    {aid:>3}  {alias}")

    lines.append("")
    lines.append("CLI aliases: dhruva, vedanga, tropical, lahiri, kp, raman, fagan, yukteshwar")
    return "\n".join(lines)


# =============================================================================
# Section 4: Load Birth Data from CHTK + Timezone Parsing
# =============================================================================

def parse_chtk_tz_offset(timezone_str, time_change_flag=0, year=None, month=None, day=None):
    """
    Parse CHTK timezone string to a numeric UTC offset in hours.

    CHTK uses the OPPOSITE sign convention from UTC:
        CHTK "-01:00:00" = UTC+1 (France CET)
        CHTK "+05:30:00" = UTC-5:30 (Argentina)

    The time_change flag value is ADDED to the standard offset for BOTH
    flag 1 (DST, +1h) and flag 2 (war time, +2h), matching the GUI
    (canonical behavior; legacy code added only flag 1).

    CHTK fields can also hold a pure IANA name ("Europe/Paris", passed
    through sign-stripped by chtk_reader); those need the birth date to
    resolve the historical standard offset.

    Args:
        timezone_str: CHTK timezone string (e.g., "-01:00:00") or IANA name
        time_change_flag: 0=Standard, 1=DST, 2=War time
        year, month, day: birth date, required for IANA names

    Returns:
        float: UTC offset in hours (e.g., 1.0 for CET, 5.5 for IST)

    Raises:
        ValueError: IANA name given without a birth date
    """
    if not timezone_str or not timezone_str.strip():
        return 0.0

    tz = timezone_str.strip()
    if '/' in tz:
        # IANA name in CHTK field: STANDARD sign, never CHTK-inverted. Do NOT invert.
        if year is None:
            raise ValueError(f"IANA timezone {tz} requires a birth date for resolution")
        std_hours, _ = resolve_total_offset(tz, year, month, day)
        return std_hours + (time_change_flag if time_change_flag in (1, 2) else 0)
    # Input convention: RAW CHTK (inverted sign)
    h, m = _parse_offset(invert_chtk_timezone(tz))
    offset = h + m / 60.0
    if time_change_flag in (1, 2):
        offset += time_change_flag
    return offset


def load_birth_data_for_dasha(chtk_path):
    """
    Load birth data from a CHTK file — same path as the GUI.

    Uses CHTKReader.read_chtk_file() which returns LOCAL time.

    Args:
        chtk_path: Path to .chtk file

    Returns:
        dict with keys: name, year, month, day, hour, minute, second,
                        city, country, birth_place, timezone, time_change_flag, ...
    """
    reader = CHTKReader()
    return reader.read_chtk_file(chtk_path)


# =============================================================================
# Section 5: Calculate Dasha
# =============================================================================

def get_dasha_params(birth_data, is_human_design=False):
    """
    Build dasha calculation parameters from birth data.

    Normal mode: returns birth params + tz_offset, moon_jd_override=None.
    HD mode: computes Design date JD (Sun 88° backward), returns it as
    moon_jd_override so the dasha sequence is seeded by the Design Moon.

    Args:
        birth_data: dict with year/month/day/hour/minute/second/timezone/time_change_flag
        is_human_design: If True, compute Design date for Moon override

    Returns:
        dict with keys:
            year, month, day, hour, minute, second, tz_offset,
            moon_jd_override (None or float), design_date_info (None or dict)
    """
    year = birth_data.get('year')
    month = birth_data.get('month')
    day = birth_data.get('day')
    hour = birth_data.get('hour', 0)
    minute = birth_data.get('minute', 0)
    second = birth_data.get('second', 0)

    raw_utcoffset = birth_data.get('utcoffset')
    if raw_utcoffset is not None:
        tz_offset = float(raw_utcoffset)
    else:
        tz_offset = parse_chtk_tz_offset(
            birth_data.get('timezone', ''),
            birth_data.get('time_change_flag', 0),
            year=year, month=month, day=day,
        )

    moon_jd_override = None
    design_date_info = None

    if is_human_design:
        from core.human_design_calculator import get_design_date_info

        # Compute birth JD in UT (local JD minus timezone offset)
        hour_decimal = hour + minute / 60.0 + second / 3600.0
        birth_jd_local = julday(year, month, day, hour_decimal)
        birth_jd_ut = birth_jd_local - tz_offset / 24.0

        # Design date: when Sun was 88° backward (~88 days before birth)
        design_info = get_design_date_info(birth_jd_ut)
        moon_jd_override = design_info['jd']  # Already in UT
        design_date_info = design_info

    return {
        'year': year, 'month': month, 'day': day,
        'hour': hour, 'minute': minute, 'second': second,
        'tz_offset': tz_offset,
        'moon_jd_override': moon_jd_override,
        'design_date_info': design_date_info,
    }


def calculate_dasha(birth_data, dlevels=1, ayanamsa=98,
                    is_human_design=False):
    """
    Calculate dasha periods from birth data.

    Direct delegation to core.vimshottari_dasha.calculate_dasha_from_birth_data().
    Passes LOCAL time + timezone offset so the core can compute the correct UT
    for Moon position lookup (matching other astrology software).

    In Human Design mode, the Moon nakshatra is looked up at the Design date
    (~88 days before birth), producing a completely different dasha sequence.

    Args:
        birth_data: dict from load_birth_data_for_dasha() with year/month/day/hour/minute/second
        dlevels: Depth 1-5 (Maha through Prana)
        ayanamsa: Ayanamsa ID (98=Dhruva, 1=Lahiri, 999=Tropical, etc.)
        is_human_design: If True, use Design date Moon for dasha sequence

    Returns:
        list of dasha entry dicts with keys:
            lord, date, time, age, is_current, jd, end_jd, level, indent
    """
    params = get_dasha_params(birth_data, is_human_design=is_human_design)

    return calculate_dasha_from_birth_data(
        params['year'], params['month'], params['day'],
        params['hour'], params['minute'], params['second'],
        dlevels=dlevels, ayanamsa=ayanamsa,
        tz_offset_hours=params['tz_offset'],
        moon_jd_override=params['moon_jd_override'],
    )


# =============================================================================
# Section 6: Date Range Filtering
# =============================================================================

def _parse_date_to_jd(date_str):
    """Convert 'YYYY-MM-DD' to Julian Day number."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return julday(dt.year, dt.month, dt.day, 0.0)


def filter_dasha_by_date_range(entries, start_date=None, end_date=None):
    """
    Filter dasha entries to those overlapping a date range.

    Args:
        entries: list of dasha entry dicts (must have 'jd' and 'end_jd')
        start_date: "YYYY-MM-DD" or None (no lower bound)
        end_date: "YYYY-MM-DD" or None (no upper bound)

    Returns:
        list of entries whose [jd, end_jd) overlaps [start_jd, end_jd)
    """
    start_jd = _parse_date_to_jd(start_date) if start_date else None
    end_jd = _parse_date_to_jd(end_date) if end_date else None

    filtered = []
    for entry in entries:
        entry_start = entry.get('jd')
        entry_end = entry.get('end_jd')
        if entry_start is None or entry_end is None:
            continue
        # Overlap test: entry overlaps range if entry_end > range_start AND entry_start < range_end
        if start_jd is not None and entry_end <= start_jd:
            continue
        if end_jd is not None and entry_start >= end_jd:
            continue
        filtered.append(entry)
    return filtered


# =============================================================================
# Section 7: Console Formatter
# =============================================================================

_LEVEL_NAMES = {0: "Maha", 1: "Antar", 2: "Pratyantar", 3: "Sukshma", 4: "Prana"}


def _get_ayanamsa_display_name(ayanamsa_id):
    """Get display name for an ayanamsa ID."""
    if _AYANAMSA_FULL_LIST:
        for aid, aname, _cat, _tip in _AYANAMSA_FULL_LIST:
            if aid == ayanamsa_id:
                return aname
    # Fallback to core aliases
    for alias, aid in _AYANAMSA_ALIASES.items():
        if aid == ayanamsa_id:
            return alias.replace("_", " ").title()
    return str(ayanamsa_id)


def format_dasha_table(entries, birth_data, ayanamsa=98,
                       dlevels=1, design_date_info=None):
    """
    Format dasha entries as a human-readable console table.

    Args:
        entries: list of dasha entry dicts
        birth_data: dict from load_birth_data_for_dasha()
        ayanamsa: Ayanamsa ID used
        dlevels: Dasha depth level
        design_date_info: If set (dict with jd/year/month/day/hour), show HD header

    Returns:
        str: Multi-line formatted text
    """
    lines = []

    # Header block
    name = birth_data.get('name', 'Unknown')
    birth_date = birth_data.get('birth_date', '')
    birth_time = birth_data.get('birth_time', '')
    birth_place = birth_data.get('birth_place', '')
    ayanamsa_name = _get_ayanamsa_display_name(ayanamsa)

    is_hd = design_date_info is not None
    title = f"Human Design Dasha — {name}" if is_hd else f"Vimshottari Dasha — {name}"
    lines.append(title)
    lines.append("=" * 70)
    lines.append(f"  Born: {birth_date}  {birth_time}")
    lines.append(f"  Place: {birth_place}")
    if is_hd:
        d = design_date_info
        dh = int(d['hour'])
        dm = int((d['hour'] - dh) * 60)
        lines.append(f"  Design date: {d['day']:02d}/{d['month']:02d}/{d['year']}  {dh:02d}:{dm:02d} UTC")
    lines.append(f"  Ayanamsa: {ayanamsa_name} (ID {ayanamsa})")
    lines.append(f"  Depth: {dlevels} ({_LEVEL_NAMES.get(dlevels - 1, f'Level {dlevels}')}dasha)")

    # Moon nakshatra info — use Design JD if HD, else birth UT JD
    hour_decimal = (birth_data.get('hour', 0)
                    + birth_data.get('minute', 0) / 60.0
                    + birth_data.get('second', 0) / 3600.0)
    birth_jd_local = julday(birth_data['year'], birth_data['month'],
                            birth_data['day'], hour_decimal)
    tz_offset = parse_chtk_tz_offset(
        birth_data.get('timezone', ''),
        birth_data.get('time_change_flag', 0),
        year=birth_data.get('year'),
        month=birth_data.get('month'),
        day=birth_data.get('day'),
    )
    moon_lookup_jd = design_date_info['jd'] if is_hd else (birth_jd_local - tz_offset / 24.0)
    nak_name, nak_idx, nak_long = get_moon_nakshatra_name(
        moon_lookup_jd, ayanamsa=ayanamsa
    )
    nak_label = "Design Moon nakshatra" if is_hd else "Moon nakshatra"
    lines.append(f"  {nak_label}: {nak_name} (#{nak_idx + 1}, {nak_long:.2f}°)")
    lines.append("=" * 70)
    lines.append("")

    # Column header
    lines.append(f"{'':2}{'Lord':<8} {'Start Date':<12} {'Time':<6} {'Age':<16} {'Level'}")
    lines.append(f"{'':2}{'-' * 8} {'-' * 12} {'-' * 6} {'-' * 16} {'-' * 10}")

    # Dasha rows
    for entry in entries:
        lord = entry.get('lord', '?')
        date = entry.get('date', '')
        time_str = entry.get('time', '')
        age = entry.get('age', '')
        is_current = entry.get('is_current', False)
        level = entry.get('level', 0)
        indent = "  " * level

        marker = ">>>" if is_current else "   "
        level_name = _LEVEL_NAMES.get(level, f"L{level}")

        lines.append(f"{marker}{indent}{lord:<8} {date:<12} {time_str:<6} {age:<16} {level_name}")

    lines.append("")
    lines.append(f"Total periods: {len(entries)}")
    return "\n".join(lines)


def format_dasha_json(entries, birth_data, ayanamsa=98,
                      dlevels=1, design_date_info=None):
    """
    Format dasha entries as a JSON string.

    Args:
        entries: list of dasha entry dicts
        birth_data: dict from load_birth_data_for_dasha()
        ayanamsa: Ayanamsa ID used
        dlevels: Dasha depth level
        design_date_info: If set (dict with jd/year/month/day/hour), include HD data

    Returns:
        str: JSON string
    """
    is_hd = design_date_info is not None

    # Moon nakshatra — use Design JD if HD, else birth UT JD
    hour_decimal = (birth_data.get('hour', 0)
                    + birth_data.get('minute', 0) / 60.0
                    + birth_data.get('second', 0) / 3600.0)
    birth_jd_local = julday(birth_data['year'], birth_data['month'],
                            birth_data['day'], hour_decimal)
    tz_offset = parse_chtk_tz_offset(
        birth_data.get('timezone', ''),
        birth_data.get('time_change_flag', 0),
        year=birth_data.get('year'),
        month=birth_data.get('month'),
        day=birth_data.get('day'),
    )
    moon_lookup_jd = design_date_info['jd'] if is_hd else (birth_jd_local - tz_offset / 24.0)
    nak_name, nak_idx, nak_long = get_moon_nakshatra_name(
        moon_lookup_jd, ayanamsa=ayanamsa
    )

    result = {
        "chart": {
            "name": birth_data.get('name', 'Unknown'),
            "birth_date": birth_data.get('birth_date', ''),
            "birth_time": birth_data.get('birth_time', ''),
            "birth_place": birth_data.get('birth_place', ''),
        },
        "mode": "human_design" if is_hd else "birth",
        "settings": {
            "ayanamsa_id": ayanamsa,
            "ayanamsa_name": _get_ayanamsa_display_name(ayanamsa),
            "dlevels": dlevels,
            "human_design": is_hd,
        },
        "moon_nakshatra": {
            "name": nak_name,
            "index": nak_idx,
            "longitude": round(nak_long, 4),
            "source": "design_date" if is_hd else "birth_date",
        },
        "periods": [
            {
                "lord": e.get('lord', '?'),
                "start_date": e.get('date', ''),
                "start_time": e.get('time', ''),
                "age": e.get('age', ''),
                "is_current": e.get('is_current', False),
                "level": e.get('level', 0),
                "jd": e.get('jd'),
                "end_jd": e.get('end_jd'),
            }
            for e in entries
        ],
        "total_periods": len(entries),
    }
    if is_hd:
        d = design_date_info
        result["design_date"] = {
            "jd": d['jd'],
            "year": d['year'],
            "month": d['month'],
            "day": d['day'],
            "hour_utc": round(d['hour'], 4),
        }
    return json.dumps(result, indent=2, default=str)
