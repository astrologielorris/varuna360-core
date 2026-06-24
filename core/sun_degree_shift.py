#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Sun Degree Shift Calculator
Shifts a birth chart by moving the Sun by N degrees (1° = 1 "astrological day").

This is the foundation for Human Design calculations.

Usage:
    python core/sun_degree_shift.py <chart.chtk> <degrees>
    python core/sun_degree_shift.py Lorris.chtk -1      # 1 day earlier
    python core/sun_degree_shift.py Lorris.chtk -88     # Human Design "Design" chart

The module can be imported and used programmatically:
    from core.sun_degree_shift import shift_sun_degrees, load_chart_with_jd
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from libaditya import swe
from core.planets_calculator import get_calendar_flag, get_calendar_flag_from_jd

# Sign names for display
ADITYA_NAMES = ['Dhata', 'Aryama', 'Mitra', 'Varuna', 'Indra', 'Vivasvan',
                'Tvasta', 'Vishnu', 'Amzu', 'Bhaga', 'Pusha', 'Parjanya']

TROPICAL_NAMES = ['Aries', 'Taurus', 'Gemini', 'Cancer', 'Leo', 'Virgo',
                  'Libra', 'Scorpio', 'Sagittarius', 'Capricorn', 'Aquarius', 'Pisces']


def get_sign_name(decimal_degrees, mode="aditya"):
    """Get sign name for given degrees."""
    tropical_index = int((decimal_degrees % 360) // 30)
    if mode == "aditya":
        aditya_index = (tropical_index + 1) % 12
        return ADITYA_NAMES[aditya_index]
    return TROPICAL_NAMES[tropical_index]


def find_sun_at_longitude(target_lon, jd_start, direction="backward", expected_days=None):
    """
    Find the Julian Day when Sun reaches target longitude.

    Args:
        target_lon: Target longitude (0-360)
        jd_start: Start searching from this JD
        direction: "backward" (earlier) or "forward" (later)
        expected_days: Expected number of days for the shift (helps optimize search)

    Returns:
        Julian Day when Sun reaches target
    """
    target_lon = target_lon % 360

    if direction == "forward":
        # solcross_ut finds NEXT crossing forward in time
        jd_cross = swe.solcross_ut(target_lon, jd_start, swe.FLG_SWIEPH)
    else:
        # For backward search, we need to find the PREVIOUS crossing
        # Strategy: Start from a point BEFORE the expected crossing and search forward

        # Estimate: Sun moves ~1°/day, so N degrees = ~N days
        if expected_days is not None:
            # Use expected days + buffer
            search_start = jd_start + expected_days - 5  # expected_days is negative
        else:
            # Default: go back 30 days (safe for small shifts)
            search_start = jd_start - 30

        jd_cross = swe.solcross_ut(target_lon, search_start, swe.FLG_SWIEPH)

        # Verify we found a crossing BEFORE jd_start
        # If not, we need to go further back
        if jd_cross > jd_start:
            # The crossing we found is after our start - need to go back ~365 days
            search_start = jd_start - 370
            jd_cross = swe.solcross_ut(target_lon, search_start, swe.FLG_SWIEPH)

            # Double check
            if jd_cross > jd_start:
                search_start = jd_start - 740
                jd_cross = swe.solcross_ut(target_lon, search_start, swe.FLG_SWIEPH)

    return jd_cross


def shift_sun_degrees(birth_jd, lat, lon, degrees_shift, mode="aditya", utcoffset=0.0):
    """
    Shift the Sun by N degrees and recalculate the entire chart.

    Args:
        birth_jd: Julian Day of birth (UTC)
        lat, lon: Birth coordinates
        degrees_shift: Degrees to shift (negative=backward, positive=forward)
        mode: aditya_mode for Chart construction ("aditya"/"tropical_classic"/"sidereal")

    Returns:
        tuple: (new_jd, new_pdata) — pdata is a renderer dict projected from
        the new Chart. Chart-Everywhere Issue 14: the renderer dict shape is
        retained for legacy callers; in Issue 11 callers will receive a Chart
        directly.
    """
    from core.chart_factory import build_chart_from_params

    # Get current Sun position
    sun_pos, _ = swe.calc_ut(birth_jd, swe.SUN, swe.FLG_SWIEPH)
    current_sun_lon = sun_pos[0]

    # Calculate target longitude
    target_lon = (current_sun_lon + degrees_shift) % 360

    # Find time when Sun was at target longitude
    # Sun moves ~1°/day, so expected time shift is ~degrees_shift days
    direction = "backward" if degrees_shift < 0 else "forward"
    expected_days = degrees_shift  # Negative for backward
    new_jd = find_sun_at_longitude(target_lon, birth_jd, direction, expected_days)

    # Build a mode-aware Chart at the shifted instant and project to a
    # renderer dict so existing dict-consumer callers keep working.
    chart = build_chart_from_params(jd=new_jd, lat=lat, lon=lon, mode=mode,
                                     utcoffset=utcoffset, ayanamsa=1)

    return new_jd, chart


def load_chart_with_jd(chtk_path, mode="aditya"):
    """
    Load a CHTK file and return a Chart along with Julian Day and coordinates.

    Args:
        chtk_path: Path to CHTK file
        mode: aditya_mode ("aditya"/"tropical_classic"/"sidereal")

    Returns:
        tuple: (chart, birth_jd, lat, lon, birth_data)
        birth_data is a canonical dict from BirthDataManager.
    """
    from managers.birth_data_manager import BirthDataManager
    from core.chart_factory import build_chart_from_params

    bd = BirthDataManager.create_birth_data_from_chtk(str(chtk_path))

    lat = bd['latitude']
    lon = bd['longitude']

    hour_decimal = bd['utc_hour'] + bd['utc_minute'] / 60.0 + bd['utc_second'] / 3600.0
    birth_jd = swe.julday(bd['utc_year'], bd['utc_month'], bd['utc_day'], hour_decimal,
                          get_calendar_flag(bd['utc_year'], bd['utc_month'], bd['utc_day']))

    utcoffset = bd.get('utc_offset_hours', 0.0)
    chart = build_chart_from_params(jd=birth_jd, lat=lat, lon=lon, mode=mode,
                                     utcoffset=utcoffset, ayanamsa=1)

    return chart, birth_jd, lat, lon, bd


def format_planet_line(name, degrees, mode="aditya"):
    """Format a planet line for display."""
    sign = get_sign_name(degrees, mode)
    deg_in_sign = degrees % 30
    return f"  {name:<12} {degrees:>7.2f}° ({sign}, {deg_in_sign:.1f}° in sign)"


def print_comparison(orig_chart, shifted_chart, degrees_shift, time_diff_days):
    """Print before/after comparison of two Chart objects."""
    print(f"\n{'='*70}")
    print(f"COMPARISON: Original vs Shifted ({degrees_shift:+.0f}° Sun = {time_diff_days:.2f} days)")
    print(f"{'='*70}")

    planet_names = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"]
    orig_r = orig_chart.rashi()
    shift_r = shifted_chart.rashi()

    print(f"\n{'Planet':<12} {'Original':>12} {'Shifted':>12} {'Difference':>12}")
    print("-" * 50)

    orig_planets = orig_r.planets()
    shift_planets = shift_r.planets()
    for name in planet_names:
        try:
            orig_deg = orig_planets[name].ecliptic_longitude()
            shift_deg = shift_planets[name].ecliptic_longitude()
        except (KeyError, TypeError):
            continue
        diff = (shift_deg - orig_deg + 180) % 360 - 180
        print(f"{name:<12} {orig_deg:>10.2f}° {shift_deg:>10.2f}° {diff:>+10.2f}°")

    try:
        orig_asc = orig_r.cusps()[1].ecliptic_longitude()
        shift_asc = shift_r.cusps()[1].ecliptic_longitude()
        diff = (shift_asc - orig_asc + 180) % 360 - 180
        print(f"{'Ascendant':<12} {orig_asc:>10.2f}° {shift_asc:>10.2f}° {diff:>+10.2f}°")
    except (KeyError, IndexError):
        pass


def main():
    """Main entry point for standalone invocation."""
    if len(sys.argv) < 3:
        print("Usage: python core/sun_degree_shift.py <chart.chtk> <degrees>")
        print("       python core/sun_degree_shift.py Lorris.chtk -1")
        print("       python core/sun_degree_shift.py Lorris.chtk -88")
        print()
        print("Arguments:")
        print("  <degrees>  Degrees to shift Sun (negative=backward, positive=forward)")
        print("             1° of Sun = ~1 day (Sun moves approximately 1°/day)")
        sys.exit(1)

    chart_name = sys.argv[1]
    degrees_shift = float(sys.argv[2])

    # Find chart file
    chart_path = Path(chart_name)
    if not chart_path.exists():
        chart_path = PROJECT_ROOT / chart_name
    if not chart_path.exists():
        chart_path = PROJECT_ROOT / "chtk_files" / chart_name

    if not chart_path.exists():
        print(f"Error: Chart file not found: {chart_name}")
        sys.exit(1)

    print(f"Loading: {chart_path}")

    _orig_chart, birth_jd, lat, lon, chart_data = load_chart_with_jd(chart_path)

    if not _orig_chart:
        print("Error: Failed to load chart data")
        sys.exit(1)

    name = chart_data.get('name', 'Unknown')
    city = chart_data.get('city', '')
    country = chart_data.get('country', '')

    print(f"\nChart: {name}")
    print(f"Location: {city}, {country}")
    print(f"Birth JD: {birth_jd:.6f}")

    year, month, day, hour = swe.revjul(birth_jd, get_calendar_flag_from_jd(birth_jd))
    hour_int = int(hour)
    minute_int = int((hour - hour_int) * 60)
    print(f"Birth (UTC): {year}-{month:02d}-{day:02d} {hour_int:02d}:{minute_int:02d}")

    _orig_rashi = _orig_chart.rashi()
    orig_sun = _orig_rashi.planets()['Sun'].ecliptic_longitude()
    print(f"\n--- ORIGINAL CHART ---")
    print(format_planet_line("Sun", orig_sun))
    print(format_planet_line("Moon", _orig_rashi.planets()['Moon'].ecliptic_longitude()))
    print(format_planet_line("Ascendant", _orig_rashi.cusps()[1].ecliptic_longitude()))

    print(f"\n--- SHIFTING SUN BY {degrees_shift:+.0f}° ---")
    target_sun = (orig_sun + degrees_shift) % 360
    print(f"Target Sun longitude: {target_sun:.2f}°")

    new_jd, _shifted_chart = shift_sun_degrees(birth_jd, lat, lon, degrees_shift)

    new_year, new_month, new_day, new_hour = swe.revjul(new_jd, get_calendar_flag_from_jd(new_jd))
    new_hour_int = int(new_hour)
    new_minute_int = int((new_hour - new_hour_int) * 60)
    print(f"Found time: JD {new_jd:.6f}")
    print(f"New date (UTC): {new_year}-{new_month:02d}-{new_day:02d} {new_hour_int:02d}:{new_minute_int:02d}")

    _shifted_rashi = _shifted_chart.rashi()
    shifted_sun = _shifted_rashi.planets()['Sun'].ecliptic_longitude()
    print(f"\n--- SHIFTED CHART ({degrees_shift:+.0f}° Sun) ---")
    print(format_planet_line("Sun", shifted_sun))
    print(format_planet_line("Moon", _shifted_rashi.planets()['Moon'].ecliptic_longitude()))
    print(format_planet_line("Ascendant", _shifted_rashi.cusps()[1].ecliptic_longitude()))

    # Verify accuracy
    sun_error = abs(shifted_sun - target_sun)
    if sun_error > 0.01:
        print(f"\nWARNING: Sun position error: {sun_error:.4f}° (target: {target_sun:.2f}°, actual: {shifted_sun:.2f}°)")
    else:
        print(f"\n[OK] Sun position accurate: error = {sun_error:.6f}°")

    # Time difference
    time_diff = new_jd - birth_jd
    print(f"\nTime difference: {time_diff:.4f} days ({time_diff * 24:.2f} hours)")

    # Print full comparison
    print_comparison(_orig_chart, _shifted_chart, degrees_shift, time_diff)

    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    print(f"Sun shift: {degrees_shift:+.0f}° = {time_diff:.2f} days")
    orig_moon = _orig_chart.rashi().planets()['Moon'].ecliptic_longitude()
    shifted_moon = _shifted_chart.rashi().planets()['Moon'].ecliptic_longitude()
    moon_diff = (shifted_moon - orig_moon + 180) % 360 - 180
    print(f"Moon movement: {moon_diff:+.2f}° (expected ~{time_diff * 13:.1f}° at 13°/day)")


if __name__ == "__main__":
    main()
