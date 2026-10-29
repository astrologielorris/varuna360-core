"""
Eclipse Calculator Module

Provides functions to calculate solar and lunar eclipses using Swiss Ephemeris.
Includes Saros cycle information.

Reference: docs/SWISS_EPHEMERIS_ECLIPSE_SAROS_GUIDE.md
"""

import sys
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple

# libaditya re-exports the swisseph module object and owns the single
# ephemeris path; ./ephe and libaditya/ephe were proven byte-identical
# before the local _ensure_ephemeris override was removed (td-tagx.6).
from libaditya import swe
from core.planets_calculator import get_calendar_flag, get_calendar_flag_from_jd

# Eclipse type bit flags
ECL_CENTRAL = 1
ECL_NONCENTRAL = 2
ECL_TOTAL = 4
ECL_ANNULAR = 8
ECL_PARTIAL = 16
ECL_ANNULAR_TOTAL = 32  # Hybrid
ECL_PENUMBRAL = 64


def decode_solar_eclipse_type(ret_value: int) -> str:
    """
    Decode solar eclipse return value to human-readable type.

    Args:
        ret_value: Bit flags from sol_eclipse_when_glob()

    Returns:
        Human-readable eclipse type string
    """
    types = []
    if ret_value & ECL_TOTAL:
        types.append("Total")
    if ret_value & ECL_ANNULAR:
        types.append("Annular")
    if ret_value & ECL_ANNULAR_TOTAL:
        types.append("Hybrid")
    if ret_value & ECL_PARTIAL:
        types.append("Partial")
    if ret_value & ECL_CENTRAL:
        types.append("Central")
    if ret_value & ECL_NONCENTRAL and not types:
        types.append("Non-central")

    return " ".join(types) if types else "Unknown"


def decode_lunar_eclipse_type(ret_value: int) -> str:
    """
    Decode lunar eclipse return value to human-readable type.

    Args:
        ret_value: Bit flags from lun_eclipse_when()

    Returns:
        Human-readable eclipse type string
    """
    if ret_value & ECL_TOTAL:
        return "Total"
    elif ret_value & ECL_PARTIAL:
        return "Partial"
    elif ret_value & ECL_PENUMBRAL:
        return "Penumbral"
    return "Unknown"


def jd_to_datetime(jd: float) -> datetime:
    """
    Convert Julian Day to Python datetime (UTC).

    Args:
        jd: Julian Day number

    Returns:
        datetime object in UTC
    """
    year, month, day, hour = swe.revjul(jd, get_calendar_flag_from_jd(jd))

    # Convert decimal hour to hours, minutes, seconds
    hour_int = int(hour)
    remainder = (hour - hour_int) * 60
    minute = int(remainder)
    second = int((remainder - minute) * 60)

    return datetime(int(year), int(month), int(day),
                   hour_int, minute, second, tzinfo=timezone.utc)


def find_solar_eclipses(start_year: int, end_year: Optional[int] = None) -> List[Dict]:
    """
    Find all solar eclipses in a year range.

    Args:
        start_year: Starting year
        end_year: Ending year (defaults to start_year for single year)

    Returns:
        List of eclipse dictionaries with keys:
        - datetime_utc: datetime object (UTC)
        - type: Eclipse type string
        - type_code: Raw type code
        - magnitude: Eclipse magnitude
        - saros_series: Saros series number
        - saros_member: Member number in series
        - center_lat: Latitude of central line (if applicable)
        - center_lon: Longitude of central line (if applicable)
    """
    if end_year is None:
        end_year = start_year

    eclipses = []

    # Start from January 1 of start year
    jd_start = swe.julday(start_year, 1, 1, 0.0, get_calendar_flag(start_year, 1, 1))
    jd_end = swe.julday(end_year + 1, 1, 1, 0.0, get_calendar_flag(end_year + 1, 1, 1))

    jd_current = jd_start

    while jd_current < jd_end:
        try:
            # Find next solar eclipse
            ret_type, tret = swe.sol_eclipse_when_glob(jd_current, 0, 0)

            jd_max = tret[0]  # Time of maximum eclipse

            # Check if within our range
            if jd_max >= jd_end:
                break

            # Get eclipse attributes using sol_eclipse_where
            # This gives us the central line location and Saros info
            _, geopos, attr = swe.sol_eclipse_where(jd_max, 0)

            # Extract data
            eclipse = {
                'datetime_utc': jd_to_datetime(jd_max),
                'jd': jd_max,
                'type': decode_solar_eclipse_type(ret_type),
                'type_code': ret_type,
                'magnitude': attr[8],  # NASA magnitude
                'saros_series': int(attr[9]) if attr[9] > -99999 else None,
                'saros_member': int(attr[10]) if attr[10] > -99999 else None,
                'center_lat': geopos[1],
                'center_lon': geopos[0],
                'eclipse_kind': 'solar',
            }

            eclipses.append(eclipse)

            # Move past this eclipse for next search (add ~25 days)
            jd_current = jd_max + 25

        except Exception as e:
            print(f"[ECLIPSE] Error finding solar eclipse: {e}")
            break

    return eclipses


def find_lunar_eclipses(start_year: int, end_year: Optional[int] = None) -> List[Dict]:
    """
    Find all lunar eclipses in a year range.

    Args:
        start_year: Starting year
        end_year: Ending year (defaults to start_year for single year)

    Returns:
        List of eclipse dictionaries with keys:
        - datetime_utc: datetime object (UTC)
        - type: Eclipse type string
        - type_code: Raw type code
        - magnitude: Eclipse magnitude (umbral)
        - saros_series: Saros series number
        - saros_member: Member number in series
    """
    if end_year is None:
        end_year = start_year

    eclipses = []

    # Start from January 1 of start year
    jd_start = swe.julday(start_year, 1, 1, 0.0, get_calendar_flag(start_year, 1, 1))
    jd_end = swe.julday(end_year + 1, 1, 1, 0.0, get_calendar_flag(end_year + 1, 1, 1))

    jd_current = jd_start

    while jd_current < jd_end:
        try:
            # Find next lunar eclipse
            ret_type, tret = swe.lun_eclipse_when(jd_current, 0, 0)

            jd_max = tret[0]  # Time of maximum eclipse

            # Check if within our range
            if jd_max >= jd_end:
                break

            # Get eclipse attributes using lun_eclipse_how
            # Use geopos at (0, 0) as reference point (global visibility)
            geopos = (0.0, 0.0, 0.0)
            ret_how, attr = swe.lun_eclipse_how(jd_max, geopos, 0)

            # Extract data
            eclipse = {
                'datetime_utc': jd_to_datetime(jd_max),
                'jd': jd_max,
                'type': decode_lunar_eclipse_type(ret_type),
                'type_code': ret_type,
                'magnitude': attr[0],  # Umbral magnitude
                'penumbral_magnitude': attr[1],
                'saros_series': int(attr[9]) if attr[9] > -99999 else None,
                'saros_member': int(attr[10]) if attr[10] > -99999 else None,
                'eclipse_kind': 'lunar',
            }

            eclipses.append(eclipse)

            # Move past this eclipse for next search (add ~25 days)
            jd_current = jd_max + 25

        except Exception as e:
            print(f"[ECLIPSE] Error finding lunar eclipse: {e}")
            break

    return eclipses


def find_all_eclipses(start_year: int, end_year: Optional[int] = None,
                      include_solar: bool = True, include_lunar: bool = True) -> List[Dict]:
    """
    Find all eclipses (solar and/or lunar) in a year range.

    Args:
        start_year: Starting year
        end_year: Ending year (defaults to start_year)
        include_solar: Include solar eclipses
        include_lunar: Include lunar eclipses

    Returns:
        Combined list of eclipses, sorted by date
    """
    eclipses = []

    if include_solar:
        eclipses.extend(find_solar_eclipses(start_year, end_year))

    if include_lunar:
        eclipses.extend(find_lunar_eclipses(start_year, end_year))

    # Sort by date
    eclipses.sort(key=lambda x: x['jd'])

    return eclipses


def get_saros_series_history(series_num: int, eclipse_type: str = 'solar',
                             max_eclipses: int = 100) -> List[Dict]:
    """
    Get full history of a Saros series.

    A Saros series typically contains 70-85 eclipses over 1200-1500 years.
    Each eclipse is separated by ~18 years, 11 days.

    Args:
        series_num: Saros series number (1-190 for solar)
        eclipse_type: 'solar' or 'lunar'
        max_eclipses: Maximum number to return (default 100)

    Returns:
        List of eclipse dictionaries in the series
    """
    # Strategy: Start from a known recent eclipse and search backward/forward
    # Saros period is approximately 6585.3 days (18y 11d 8h)
    SAROS_PERIOD_DAYS = 6585.3

    series_eclipses = []
    found_jds = set()  # Track found eclipses to avoid duplicates

    # Helper to get eclipse data
    def _get_eclipse_data(jd_search_from: float) -> Optional[Dict]:
        """Find next eclipse from jd and return its data."""
        try:
            if eclipse_type == 'solar':
                ret_type, tret = swe.sol_eclipse_when_glob(jd_search_from, 0, 0)
                jd_max = tret[0]
                _, _, attr = swe.sol_eclipse_where(jd_max, 0)
                type_str = decode_solar_eclipse_type(ret_type)
            else:
                ret_type, tret = swe.lun_eclipse_when(jd_search_from, 0, 0)
                jd_max = tret[0]
                geopos = (0.0, 0.0, 0.0)
                _, attr = swe.lun_eclipse_how(jd_max, geopos, 0)
                type_str = decode_lunar_eclipse_type(ret_type)

            return {
                'jd': jd_max,
                'ret_type': ret_type,
                'type_str': type_str,
                'magnitude': attr[8],
                'saros_series': int(attr[9]) if attr[9] > -99999 else None,
                'saros_member': int(attr[10]) if attr[10] > -99999 else None,
            }
        except Exception:
            return None

    # First, find a recent eclipse in this series by searching from year 2000
    jd_search = swe.julday(2000, 1, 1, 0.0)
    jd_end = swe.julday(2050, 1, 1, 0.0)

    reference_eclipse = None

    while jd_search < jd_end and reference_eclipse is None:
        data = _get_eclipse_data(jd_search)
        if data is None:
            break

        if data['saros_series'] == series_num:
            reference_eclipse = data
            break

        jd_search = data['jd'] + 25

    if reference_eclipse is None:
        print(f"[SAROS] Could not find series {series_num} between 2000-2050")
        return []

    # Add reference eclipse first
    ref_eclipse = {
        'datetime_utc': jd_to_datetime(reference_eclipse['jd']),
        'jd': reference_eclipse['jd'],
        'type': reference_eclipse['type_str'],
        'type_code': reference_eclipse['ret_type'],
        'magnitude': reference_eclipse['magnitude'],
        'saros_series': series_num,
        'saros_member': reference_eclipse['saros_member'],
        'eclipse_kind': eclipse_type,
    }
    series_eclipses.append(ref_eclipse)
    found_jds.add(round(reference_eclipse['jd'], 1))

    # Backward search - keep searching even when we hit different series
    jd_target = reference_eclipse['jd']
    consecutive_misses = 0  # Count how many times we miss our series

    for _ in range(max_eclipses):
        jd_target = jd_target - SAROS_PERIOD_DAYS
        if jd_target < swe.julday(500, 1, 1, 0.0, swe.JUL_CAL):  # Go back to year 500
            break

        # Search in a window around expected time (±30 days)
        # Multiple eclipses can occur near each other from different series
        search_start = jd_target - 30
        search_end = jd_target + 30
        found_in_window = False

        jd_check = search_start
        while jd_check < search_end:
            data = _get_eclipse_data(jd_check)
            if data is None:
                break

            if data['jd'] > search_end:
                break

            jd_rounded = round(data['jd'], 1)

            if data['saros_series'] == series_num and jd_rounded not in found_jds:
                eclipse = {
                    'datetime_utc': jd_to_datetime(data['jd']),
                    'jd': data['jd'],
                    'type': data['type_str'],
                    'type_code': data['ret_type'],
                    'magnitude': data['magnitude'],
                    'saros_series': series_num,
                    'saros_member': data['saros_member'],
                    'eclipse_kind': eclipse_type,
                }
                series_eclipses.append(eclipse)
                found_jds.add(jd_rounded)
                jd_target = data['jd']  # Update target for next iteration
                found_in_window = True
                consecutive_misses = 0
                break

            jd_check = data['jd'] + 1  # Check next eclipse in window

        if not found_in_window:
            consecutive_misses += 1
            # Stop after 3 consecutive misses (series has ended)
            if consecutive_misses >= 3:
                break

    # Forward search
    jd_target = reference_eclipse['jd']
    consecutive_misses = 0

    for _ in range(max_eclipses):
        jd_target = jd_target + SAROS_PERIOD_DAYS
        if jd_target > swe.julday(2800, 1, 1, 0.0):  # Swiss Ephemeris limit
            break

        search_start = jd_target - 30
        search_end = jd_target + 30
        found_in_window = False

        jd_check = search_start
        while jd_check < search_end:
            data = _get_eclipse_data(jd_check)
            if data is None:
                break

            if data['jd'] > search_end:
                break

            jd_rounded = round(data['jd'], 1)

            if data['saros_series'] == series_num and jd_rounded not in found_jds:
                eclipse = {
                    'datetime_utc': jd_to_datetime(data['jd']),
                    'jd': data['jd'],
                    'type': data['type_str'],
                    'type_code': data['ret_type'],
                    'magnitude': data['magnitude'],
                    'saros_series': series_num,
                    'saros_member': data['saros_member'],
                    'eclipse_kind': eclipse_type,
                }
                series_eclipses.append(eclipse)
                found_jds.add(jd_rounded)
                jd_target = data['jd']
                found_in_window = True
                consecutive_misses = 0
                break

            jd_check = data['jd'] + 1

        if not found_in_window:
            consecutive_misses += 1
            if consecutive_misses >= 3:
                break

    # Sort by member number
    series_eclipses.sort(key=lambda x: x['saros_member'] if x['saros_member'] else 0)

    return series_eclipses


# ============= Founding Eclipse Cache =============
_FOUNDING_CACHE = {}  # (series_num, eclipse_type) → eclipse dict or None


def get_founding_eclipse(series_num: int, eclipse_type: str = 'solar') -> Optional[Dict]:
    """Get founding eclipse (member #1) of a Saros series.

    Uses get_saros_series_history(), exact same code path as GUI.
    Results cached because founding eclipses are immutable.

    Args:
        series_num: Saros series number (e.g., 133)
        eclipse_type: 'solar' or 'lunar'

    Returns:
        Eclipse dict for member #1, or None if not found
    """
    cache_key = (series_num, eclipse_type)
    if cache_key in _FOUNDING_CACHE:
        return _FOUNDING_CACHE[cache_key]

    eclipses = get_saros_series_history(series_num, eclipse_type, max_eclipses=100)

    founding = None
    for e in eclipses:
        if e.get('saros_member') == 1:
            founding = e
            break

    _FOUNDING_CACHE[cache_key] = founding
    return founding


def get_active_saros_series(eclipse_type: str = 'solar', year: int = 2024) -> List[int]:
    """
    Get list of currently active Saros series numbers.

    A Saros series is "active" if it has eclipses occurring around the given year.

    Args:
        eclipse_type: 'solar' or 'lunar'
        year: Reference year

    Returns:
        List of active Saros series numbers, sorted
    """
    active_series = set()

    # Search eclipses in a 40-year window centered on year
    start_year = year - 20
    end_year = year + 20

    if eclipse_type == 'solar':
        eclipses = find_solar_eclipses(start_year, end_year)
    else:
        eclipses = find_lunar_eclipses(start_year, end_year)

    for eclipse in eclipses:
        if eclipse['saros_series']:
            active_series.add(eclipse['saros_series'])

    return sorted(active_series)


def find_eclipses_near_date(target_date, days_radius=60,
                            include_solar=True, include_lunar=True):
    """Find all eclipses within days_radius of target_date.

    Args:
        target_date: datetime object or 'YYYY-MM-DD' string (treated as midnight UTC)
        days_radius: Search window in days (default: 60)
        include_solar: Include solar eclipses
        include_lunar: Include lunar eclipses

    Returns:
        List of eclipse dicts, sorted by proximity to target_date.
        Each dict has extra keys: 'days_from_target' (float) and 'direction' ('before'/'after')
    """
    # Parse string to datetime if needed
    if isinstance(target_date, str):
        target_date = datetime.strptime(target_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)

    # Compute year range covering the full search window
    from datetime import timedelta
    earliest = target_date - timedelta(days=days_radius)
    latest = target_date + timedelta(days=days_radius)
    start_year = earliest.year
    end_year = latest.year

    # Get all eclipses in the year range
    eclipses = find_all_eclipses(start_year, end_year, include_solar, include_lunar)

    # Convert target_date to Julian Day for comparison
    target_jd = swe.julday(
        target_date.year, target_date.month, target_date.day,
        target_date.hour + target_date.minute / 60.0 + target_date.second / 3600.0,
        get_calendar_flag(target_date.year, target_date.month, target_date.day)
    )

    # Filter by proximity and add extra fields
    result = []
    for ecl in eclipses:
        delta_days = ecl['jd'] - target_jd
        if abs(delta_days) <= days_radius:
            ecl['days_from_target'] = round(abs(delta_days), 1)
            ecl['direction'] = 'before' if delta_days < 0 else 'after'
            result.append(ecl)

    # Sort by proximity (closest first)
    result.sort(key=lambda x: x['days_from_target'])

    return result


def find_next_eclipse(from_dt: Optional[datetime] = None,
                      include_solar: bool = True,
                      include_lunar: bool = True) -> Optional[Dict]:
    """
    Find the chronologically next eclipse strictly after from_dt.

    Implemented over find_eclipses_near_date with a widening search radius
    (60, then 200, then 400 days). Note that find_eclipses_near_date sorts
    by PROXIMITY, not chronology, so the minimum by datetime_utc is taken
    here explicitly (SPEC-ECL-002 section 5.4).

    Args:
        from_dt: Reference datetime. None means now (UTC). A naive datetime
                 is interpreted as UTC; an aware datetime is converted to UTC.
        include_solar: Include solar eclipses
        include_lunar: Include lunar eclipses

    Returns:
        The engine eclipse dict of the first eclipse with
        datetime_utc strictly greater than from_dt (annotation keys
        'days_from_target' and 'direction' from the underlying search may
        remain on the record), or None if no eclipse is found within
        400 days. None is a real return: a from_dt near or past the end of
        ephemeris coverage yields None instead of raising (swisseph/OSError
        ephemeris-access failures are caught internally with a stderr
        warning; other exceptions propagate, pm-20260711-018).

    Raises:
        ValueError: If both include_solar and include_lunar are False.
    """
    if not include_solar and not include_lunar:
        raise ValueError("At least one of include_solar/include_lunar must be True")

    if from_dt is None:
        from_dt = datetime.now(timezone.utc)
    elif from_dt.tzinfo is None:
        # Naive datetimes are interpreted as UTC so comparisons against the
        # tz-aware datetime_utc values from jd_to_datetime stay consistent.
        from_dt = from_dt.replace(tzinfo=timezone.utc)
    else:
        # Aware non-UTC datetimes must be normalized BEFORE the JD search:
        # find_eclipses_near_date reads the wall-clock fields as UTC when
        # building the target JD, so a +02:00 input would skew the
        # before/after classification by the offset (codex review F3).
        from_dt = from_dt.astimezone(timezone.utc)

    for days_radius in (60, 200, 400):
        try:
            candidates = find_eclipses_near_date(
                from_dt, days_radius=days_radius,
                include_solar=include_solar, include_lunar=include_lunar
            )
        except (swe.Error, OSError) as e:
            # Out-of-range ephemeris access (missing sepl_*.se1 file or a
            # file-level failure) means no reachable eclipse: warn once and
            # return None instead of raising. Programming errors (TypeError,
            # KeyError, ...) propagate (codex review F4).
            print(f"[ECLIPSE] find_next_eclipse: ephemeris access failed near "
                  f"{from_dt.isoformat()} (radius {days_radius}d): {e}",
                  file=sys.stderr)
            return None

        upcoming = [
            ecl for ecl in candidates
            if ecl['direction'] == 'after' and ecl['datetime_utc'] > from_dt
        ]
        if upcoming:
            return min(upcoming, key=lambda x: x['datetime_utc'])

    return None


# ============= Test Code =============
if __name__ == '__main__':
    print("=== Eclipse Calculator Test ===\n")

    # Test 1: Find solar eclipses in 2024
    print("Solar eclipses in 2024:")
    solar_2024 = find_solar_eclipses(2024)
    for e in solar_2024:
        print(f"  {e['datetime_utc'].strftime('%Y-%m-%d %H:%M')} UTC | "
              f"{e['type']:12} | Mag: {e['magnitude']:.3f} | "
              f"Saros: {e['saros_series']}-{e['saros_member']}")

    print("\nLunar eclipses in 2024:")
    lunar_2024 = find_lunar_eclipses(2024)
    for e in lunar_2024:
        print(f"  {e['datetime_utc'].strftime('%Y-%m-%d %H:%M')} UTC | "
              f"{e['type']:12} | Mag: {e['magnitude']:.3f} | "
              f"Saros: {e['saros_series']}-{e['saros_member']}")

    print("\n=== Saros Series 139 (partial) ===")
    saros_139 = get_saros_series_history(139, 'solar', max_eclipses=20)
    for e in saros_139[:10]:  # Show first 10
        print(f"  #{e['saros_member']:2d} | {e['datetime_utc'].strftime('%Y-%m-%d')} | "
              f"{e['type']:12} | Mag: {e['magnitude']:.3f}")

    print("\n=== Active Solar Saros Series (2024) ===")
    active = get_active_saros_series('solar', 2024)
    print(f"Active series: {active[:10]}...")
