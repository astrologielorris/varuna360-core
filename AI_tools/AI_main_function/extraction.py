# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under the GNU AGPL-3.0. See LICENSE at the repository root.
"""
Chart data extraction functions.
================================
parse_dms_to_decimal, extract_from_chtk, extract_from_datetime
"""

import re
import sys

from core.time_utils import resolve_total_offset
# Issue 12: get_all_planets_data replaced with chart_factory's mode-aware path.

from AI_tools.AI_main_function.constants import DEFAULT_CHTK

# Lazy module-level TimezoneFinder fallback singleton (see
# _detect_iana_timezone; only built if the BirthDataManager path fails).
_TZ_FINDER = None


def _detect_iana_timezone(latitude, longitude):
    """Detect the IANA zone from coordinates for CLI loaders.

    Preferred path: BirthDataManager._detect_timezone, the exact detector
    the GUI canonical path uses (importing managers.birth_data_manager pulls
    no Qt modules, checked in-env for td-5w3c.3). Fallback: a module-level
    cached TimezoneFinder mirroring _detect_timezone's pattern, so a future
    Qt dependency in managers/ cannot break headless CLIs.

    Returns the IANA name string, or None on total failure (the resolver
    then degrades to flag 0 with its own fail-loud warning).
    """
    try:
        from managers.birth_data_manager import BirthDataManager
        return BirthDataManager._detect_timezone(latitude, longitude)
    except Exception as e:
        print(f"Timezone: IANA detection via BirthDataManager failed ({e}); "
              f"falling back to local TimezoneFinder", file=sys.stderr)
    global _TZ_FINDER
    try:
        if _TZ_FINDER is None:
            from timezonefinder import TimezoneFinder
            _TZ_FINDER = TimezoneFinder()
        tz = _TZ_FINDER.timezone_at(lat=latitude, lng=longitude)
        return tz if tz else "UTC"
    except Exception as e:
        print(f"Timezone: IANA detection failed: {e}", file=sys.stderr)
        return None


def resolve_chtk_dst_flag_for_cli(time_change_flag, year, month, day,
                                  hour, minute, latitude, longitude):
    """Resolve the Kala AUTO DST flag (-1) for CLI chart loaders.

    Rule 24 parity with the GUI canonical path (td-5w3c.3): the CHTK reader
    can emit -1 on line 14 meaning AUTO, resolve DST from IANA rules at
    load. BirthDataManager._build_canonical resolves it for the GUI; CLI
    loaders that read the raw CHTKReader dict must apply the identical
    resolution or they land 1h off the GUI (Elsa: UT 14:00 vs 13:00).

    Every warning is printed to STDERR (the CLI-visible equivalent of the
    GUI tz_warnings channel, same text; stderr so --json stdout stays
    machine-parseable). Every degradation falls back to flag 0 LOUDLY,
    never silently. Flags other than -1 pass through unchanged (the 0/1/2
    semantics of the callers are preserved).

    Returns:
        int: the normalized flag (0 or 1 when the input was -1, else the
        input unchanged).
    """
    if time_change_flag != -1:
        return time_change_flag
    # Coords check MUST precede detection: _detect_timezone(0, 0) returns
    # "UTC" (not None), so ocean-origin charts would silently resolve via
    # UTC rules (Wave 1 discovery).
    if latitude == 0.0 and longitude == 0.0:
        print("Timezone: DST flag -1 could not be auto-resolved: no "
              "coordinates to detect an IANA zone (chart may be 1h off)",
              file=sys.stderr)
        return 0
    iana = _detect_iana_timezone(latitude, longitude)
    from core.time_utils import resolve_auto_dst_flag
    flag, warns = resolve_auto_dst_flag(iana, year, month, day, hour, minute,
                                        longitude=longitude)
    for w in warns:
        print(w, file=sys.stderr)
    return flag


def iana_total_offset_for_cli(tz_raw, year, month, day, hour, minute,
                              longitude, time_change_flag):
    """TOTAL local offset (hours) for a pure IANA name on CHTK line 13.

    Single source of truth for the IANA branch of BOTH CLI CHTK loaders
    (extract_from_chtk here and render_chart.load_planets_from_chtk), so
    the two cannot diverge (Rule 24 parity, td-5w3c epic). Composition:
    STANDARD hours from resolve_total_offset at the birth instant (the
    IANA-derived flag is discarded), plus the chart's OWN asserted flag
    for 1 (DST) and 2 (War Time). Callers must resolve a -1 auto flag
    via resolve_chtk_dst_flag_for_cli BEFORE calling this.

    Fail-loud: resolution errors (unknown zone name, etc.) print a
    stderr warning then propagate; a caller must never silently treat
    local time as UTC.

    Returns:
        float: total offset in hours (standard + asserted DST/War Time).
    """
    try:
        std_hours, _ = resolve_total_offset(
            tz_raw, year, month, day, hour, minute, longitude=longitude)
    except Exception as e:
        print(f"Timezone: IANA name '{tz_raw}' on CHTK line 13 could not "
              f"be resolved ({e}); refusing to treat local time as UTC",
              file=sys.stderr)
        raise
    return std_hours + (time_change_flag if time_change_flag in (1, 2) else 0)


def parse_dms_to_decimal(dms_str):
    """Kala coordinate text ('44n29', '73w12', "48N49'00") -> decimal degrees.

    Delegates to core.chtk_reader.parse_kala_coordinate, the one chart-file
    coordinate parser (case-insensitive hemisphere letter, seconds kept).
    S and W are negative; empty or unparseable text gives 0.0.
    """
    from core.chtk_reader import parse_kala_coordinate
    return parse_kala_coordinate(dms_str)


def extract_from_chtk(chtk_path, mode="aditya", ayanamsa=1, hsys="C"):
    """
    Build a libaditya Chart from a CHTK file.

    Args:
        chtk_path: Path to CHTK file
        mode: Zodiac mode ("aditya", "tropical_classic", "sidereal").
              Per SPEC-ZOD-002, the Chart must be built in the desired
              mode so get_planet_sign_index() returns correct values.
        ayanamsa: Ayanamsa id, only consulted when mode == "sidereal".
                  Defaults to 1 (the historical CLI basis; CLIs pass the
                  saved Settings tab value, see core/capabilities/cli_settings).
        hsys: Swiss Ephemeris house system code (SPEC-HSY-001), default "C".

    Returns:
        tuple: (Chart object, person_name str)
    """
    # THE app loading path (ChartManager.load_chart): same birth data, same JD
    # (calendar-aware: Julian before 1582-10-15). The hand-rolled parse that
    # lived here built the JD with bare swe.julday (Gregorian), 7 to 10 days
    # off the app on pre-1582 charts. .toml works too.
    from core.chart_factory import build_chart_from_params
    from core.chart_loading import load_birth_data_and_jd
    birth_data, jd = load_birth_data_and_jd(chtk_path, warnings_to=sys.stderr)
    name = birth_data.get('name', '')
    chart = build_chart_from_params(jd=jd, lat=birth_data['latitude'],
                                    lon=birth_data['longitude'], mode=mode,
                                    ayanamsa=ayanamsa, hsys=hsys,
                                    name=name)

    return chart, name


def extract_from_datetime(date_str, time_str, lat, lon, mode="aditya",
                          ayanamsa=1, hsys="C"):
    """
    Build a libaditya Chart from date/time and coordinates.

    Args:
        date_str: Date in YYYY-MM-DD format
        time_str: Time in HH:MM format (or None for noon)
        lat: Latitude
        lon: Longitude
        mode: Zodiac mode ("aditya", "tropical_classic", "sidereal")
        ayanamsa: Ayanamsa id (default 1, the historical CLI basis)
        hsys: Swiss Ephemeris house system code (default "C")

    Returns:
        tuple: (Chart object, description str)
    """
    date_parts = date_str.split('-')
    year = int(date_parts[0])
    month = int(date_parts[1])
    day = int(date_parts[2])

    if time_str:
        time_parts = time_str.split(':')
        hour = int(time_parts[0])
        minute = int(time_parts[1]) if len(time_parts) > 1 else 0
    else:
        hour = 12
        minute = 0

    from core.chart_factory import build_chart_from_params
    from core.time_utils import julday  # Julian before 1582-10-15, as the app
    hour_decimal = hour + minute / 60.0
    jd = julday(year, month, day, hour_decimal)

    name = datetime_chart_name(date_str, time_str, lat, lon)

    chart = build_chart_from_params(jd=jd, lat=lat, lon=lon, mode=mode,
                                    ayanamsa=ayanamsa, hsys=hsys, name=name)

    return chart, name


def datetime_chart_name(date_str, time_str, lat, lon):
    """The title ``extract_from_datetime`` gives a date/time chart."""
    name = f"Chart for {date_str}"
    if time_str:
        name += f" {time_str}"
    name += f" @ ({lat:.2f}, {lon:.2f})"
    return name
