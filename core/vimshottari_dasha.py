#!/usr/bin/python
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Vimshottari Dasha Calculator for Vedic Astrology
Adapted from pydasha.py by Josh Harper
Supports multiple ayanamsas:
  - 98: Dhruva GC mid-Mula equatorial (default)
  - 100: Equatorial Vedanga Jyotisha
  - 999: Tropical (no sidereal correction)
  - 0-46: All Swiss Ephemeris sidereal ayanamsas
"""

from libaditya import swe
from core.planets_calculator import get_calendar_flag, get_calendar_flag_from_jd

# Nakshatra size in degrees
NAKSIZE = 13 + (1/3)

# Dasha lords and their periods in years: (name, years)
DASHAS = [
    ("Ketu", 7),
    ("Venus", 20),
    ("Sun", 6),
    ("Moon", 10),
    ("Mars", 7),
    ("Rahu", 18),
    ("Jupiter", 16),
    ("Saturn", 19),
    ("Mercury", 17)
]

# Indices for accessing dasha tuples
LORD = 0
LENGTH = 1

# Default year length (Saura year)
DEFAULT_YEAR_LENGTH = 365.2422


class JulianDay:
    """Display-only JD wrapper for dasha date formatting (MM/DD/YYYY, HH:MM)."""
    __slots__ = ('jd', 'datetime')

    def __init__(self, jd):
        self.jd = float(jd) if isinstance(jd, (int, float)) else swe.julday(
            jd[0], jd[1], jd[2], jd[3],
            get_calendar_flag(int(jd[0]), int(jd[1]), int(jd[2])))
        self.datetime = swe.revjul(self.jd, get_calendar_flag_from_jd(self.jd))

    def date(self):
        return f"{int(self.datetime[1]):02d}/{int(self.datetime[2]):02d}/{int(self.datetime[0]):04d}"

    def time(self):
        h = self.datetime[3]
        return f"{int(h):02d}:{int((h - int(h)) * 60):02d}"



def get_nakshatra_for_longitude(tropical_long, jd, ayanamsa=99, **_ignored):
    """
    Get the nakshatra position for ANY tropical longitude (ecliptic).

    Args:
        tropical_long: Tropical (ecliptic) longitude in degrees (0-360)
        jd: Julian Day number (UT)
        ayanamsa: Ayanamsa ID (999=Tropical, 0-46=Swiss Eph, 98=Dhruva, 100=Vedanga)

    Returns:
        (longitude_from_ashvini, nakshatra_index)
    """
    if ayanamsa in (99, 100):
        solequ = swe.cotrans((270, 0, 1), swe.calc(jd, swe.ECL_NUT)[0][0])[0]
        aval = 360 - (solequ + 5 * NAKSIZE)
        long = (tropical_long + aval) % 360

    elif ayanamsa == 98:
        gc_ecl = swe.fixstar(",SgrA*", jd)[0][0]
        mula = gc_ecl - (NAKSIZE / 2)
        ashvini = mula - (18 * NAKSIZE)
        adj_long = tropical_long
        if adj_long < ashvini:
            adj_long += 360
        long = adj_long - ashvini

    elif ayanamsa == 999:
        long = tropical_long

    elif 0 <= ayanamsa <= 46:
        swe.set_sid_mode(ayanamsa)
        ayanamsa_val = swe.get_ayanamsa_ut(jd)
        long = (tropical_long - ayanamsa_val) % 360

    else:
        return get_nakshatra_for_longitude(tropical_long, jd, ayanamsa=99)

    nindex = int(long / NAKSIZE) % 27
    return long, nindex




def _resolve_lib_ayanamsa(ayanamsa, nak_mode="neither"):
    """Map app ayanamsa ID to libaditya ayanamsa based on nakshatra coordinate mode.

    Args:
        ayanamsa: app ayanamsa ID (98, 99, 100, 0-46, 999)
        nak_mode: "equatorial" uses libaditya's native equatorial paths,
                  "neither" (default) uses ecliptic paths (matches Kala default)

    Returns:
        libaditya ayanamsa ID
    """
    if ayanamsa == 999:
        return -1
    if nak_mode == "equatorial":
        return ayanamsa
    # "neither" / "ecliptic": use ecliptic Vedanga (99) instead of equatorial (100)
    if ayanamsa == 100:
        return 99
    return ayanamsa


def _build_moon(jd_ut, ayanamsa, utcoffset=0.0, nak_mode="neither"):
    """Build a libaditya Moon object for dasha calculation.

    Args:
        jd_ut: Julian Day in UT (Moon position lookup time)
        ayanamsa: app ayanamsa ID (98, 99, 100, 0-46, 999)
        utcoffset: UTC offset in hours (for JulianDay local-time display)
        nak_mode: nakshatra coordinate mode from settings ("equatorial"/"neither")
    """
    from libaditya.objects.context import EphContext
    from libaditya.objects.julian_day import JulianDay as LibJD
    from libaditya.objects.planets import Moon as LibMoon

    lib_ayanamsa = _resolve_lib_ayanamsa(ayanamsa, nak_mode)
    timeJD = LibJD(jd_ut, utcoffset=utcoffset)
    ctx = EphContext(timeJD=timeJD, ayanamsa=lib_ayanamsa)
    return LibMoon(ctx)


def get_moon_nakshatra_bridge(jd_ut, ayanamsa=98):
    """Get Moon nakshatra via libaditya (replaces get_moon_nakshatra).

    Args:
        jd_ut: Julian Day in UT
        ayanamsa: ayanamsa ID (98, 99, 100, 0-46, 999)

    Returns:
        (ashvini_longitude, nakshatra_index)
    """
    moon = _build_moon(jd_ut, ayanamsa)
    nak = moon.nakshatra()
    return nak.ashvini_longitude(), nak.index()


def calculate_vimshottari_dasha(birth_jd, dlevels=1, yrlen=DEFAULT_YEAR_LENGTH,
                                ayanamsa=98, tz_offset_hours=0,
                                moon_jd_override=None, nak_mode="neither",
                                **_ignored):
    """
    Calculate Vimshottari Dasha via libaditya engine.

    Args:
        birth_jd: Julian Day of birth (float or JulianDay object).
                  This should be the LOCAL time JD (used for date display).
        dlevels: Number of dasha levels to calculate (1=mahadasha, 2=antardasha, etc.)
        yrlen: Year length in days (default 365.2422 Saura year)
        ayanamsa: Ayanamsa number (999=Tropical, 0-46=Swiss Eph, 98/100=Custom)
        tz_offset_hours: UTC offset in hours (e.g., 1.0 for CET, 5.5 for IST).
                         Used to convert local time to UT for accurate Moon position.
        moon_jd_override: If set (float, UT), use this JD for Moon nakshatra lookup
                          instead of deriving from birth_jd. Used for Human Design mode
                          where the dasha sequence is seeded by the Design date Moon.
        nak_mode: Nakshatra coordinate mode from settings.
                  "neither" (default, matches Kala) or "equatorial".

    Returns:
        List of dasha periods: [[dasha_jd, length_in_days, subdasha], ..., first_dasha_lord, beginning_age]
    """
    from libaditya.calc.vimshottari import (
        calculate_vimshottari_dasha as lib_calc,
        calc_vdasha as lib_calc_vdasha,
    )
    from libaditya.objects.julian_day import JulianDay as LibJD

    if isinstance(birth_jd, float):
        birth_jd = JulianDay(birth_jd)

    if moon_jd_override is not None:
        moon_jd_ut = moon_jd_override
    else:
        moon_jd_ut = birth_jd.jd - tz_offset_hours / 24.0

    # Ayanamsa 98 + "neither" mode: ecliptic Dhruva (no libaditya equivalent).
    # Compute Moon nakshatra with ecliptic GC zero-point, then use libaditya's
    # calc_vdasha for the tree. This matches Kala's "Neither" setting.
    if ayanamsa == 98 and nak_mode != "equatorial":
        gc_ecl = swe.fixstar(",SgrA*", moon_jd_ut)[0][0]
        ashvini = gc_ecl - (NAKSIZE / 2) - (18 * NAKSIZE)
        ecl_moon = swe.calc_ut(moon_jd_ut, swe.MOON)[0][0]
        if ecl_moon < ashvini:
            ecl_moon += 360
        ash_long = ecl_moon - ashvini
        nindex = int(ash_long / NAKSIZE) % 27
        elapsed_frac = (ash_long - nindex * NAKSIZE) / NAKSIZE
        lib_first = nindex % 9
        years_elapsed = DASHAS[lib_first][LENGTH] * elapsed_frac
        lib_age = -years_elapsed
        birth_jd_ut = birth_jd.jd - tz_offset_hours / 24.0
        dasha_start_ut = birth_jd_ut + lib_age * yrlen
        lib_start_jd = LibJD(dasha_start_ut, utcoffset=tz_offset_hours)
        lib_periods = lib_calc_vdasha([lib_first], lib_start_jd, 0, dlevels, yrlen)
        anchor_offset = 0.0
    else:
        moon = _build_moon(moon_jd_ut, ayanamsa, utcoffset=tz_offset_hours,
                           nak_mode=nak_mode)
        lib_result = lib_calc(moon, dlevels=dlevels, yrlen=yrlen)
        lib_age = lib_result.pop()
        lib_first = lib_result.pop()
        lib_periods = lib_result
        # libaditya anchors dates to moon_jd_ut; re-anchor to birth for HD mode
        birth_jd_ut = birth_jd.jd - tz_offset_hours / 24.0
        anchor_offset = birth_jd_ut - moon_jd_ut

    def _convert_jd_tree(periods):
        """Convert libaditya JulianDay objects to core JulianDay for display compatibility."""
        converted = []
        for period in periods:
            ut_jd = period[0].jd + anchor_offset
            local_jd = ut_jd + tz_offset_hours / 24.0
            core_jd = JulianDay(local_jd)
            subs = _convert_jd_tree(period[2]) if period[2] else []
            converted.append([core_jd, period[1], subs])
        return converted

    converted_periods = _convert_jd_tree(lib_periods)

    return converted_periods + [lib_first] + [lib_age]


def format_dasha_for_display(dasha_data, birth_jd, max_periods=200, today_jd=None):
    """
    Format dasha data for hierarchical GUI display

    Args:
        dasha_data: Output from calculate_vimshottari_dasha()
        birth_jd: Birth Julian Day
        max_periods: Maximum number of periods to display
        today_jd: Current Julian Day for marking active dasha (defaults to today)

    Returns:
        List of dicts with hierarchical dasha information
    """
    # Extract components
    age = dasha_data.pop()
    first_dasha = dasha_data.pop()
    periods = dasha_data

    result = []

    if isinstance(birth_jd, float):
        birth_jd = JulianDay(birth_jd)

    # Calculate today's Julian Day for current dasha detection
    if today_jd is None:
        from datetime import datetime
        now = datetime.utcnow()
        today_jd = swe.julday(now.year, now.month, now.day,
                              now.hour + now.minute/60 + now.second/3600)
    if isinstance(today_jd, (int, float)):
        today_jd = JulianDay(today_jd)

    # Recursive function to flatten nested dasha structure
    def flatten_dasha(dasha_list, dasha_indices, age, level=0):
        """Recursively flatten nested dasha structure"""
        # Use dlist[level] like pydasha.py does - this is the KEY to correct sequence
        # At each level, use the dasha index AT that level from dasha_indices
        current_dasha_idx = dasha_indices[level] if level < len(dasha_indices) else 0

        for i, period in enumerate(dasha_list):
            start_jd = period[0]
            length_days = period[1]
            sub_dashas = period[2]

            # Calculate which dasha lord this is
            # The sequence continues from current_dasha_idx
            this_dasha_idx = (current_dasha_idx + i) % 9
            lord_name = DASHAS[this_dasha_idx][LORD]

            # Build lord name chain (e.g., "Sa/Me/Ke")
            # Keep ALL parent dashas + this one (like pydasha: dlist+[this_dasha])
            lord_chain = dasha_indices + [this_dasha_idx]
            # For display: at level 0 skip first element (it's the mahadasha itself)
            # At level 1+, show all elements starting from index 1
            display_indices = lord_chain[1:]
            lord_names = [DASHAS[idx][LORD][:2] for idx in display_indices]
            display_lord = "/".join(lord_names)

            # Format age (handle negative ages for birth dasha)
            if age < 0:
                abs_age = abs(age)
                years = -int(abs_age)
                months = -int((abs_age % 1) * 12)
                age_str = f"{years}yrs {months}mts"
            else:
                years = int(age)
                months = int((age % 1) * 12)
                age_str = f"{years}yrs {months}mts"

            # Check if current active dasha (comparing against TODAY, not birth date)
            is_current = start_jd.jd <= today_jd.jd < (start_jd.jd + length_days)

            result.append({
                'lord': display_lord,
                'date': start_jd.date(),
                'time': start_jd.time(),
                'age': age_str,
                'is_current': is_current,
                'jd': start_jd.jd,
                'end_jd': start_jd.jd + length_days,  # Add end date for optimization
                'level': level,
                'indent': "  " * level  # Indentation for display
            })

            # Recursively process sub-dashas if they exist
            if sub_dashas and len(result) < max_periods:
                flatten_dasha(sub_dashas, lord_chain, age, level + 1)

            age += length_days / DEFAULT_YEAR_LENGTH

    # Start flattening from top level
    flatten_dasha(periods, [first_dasha], age, level=0)

    return result[:max_periods]


def calculate_sub_dashas_for_period(parent_start_jd, parent_end_jd, parent_lord,
                                    ayanamsa=98, tz_offset_hours=0):
    """
    Calculate only the sub-dashas within a specific parent period's time range.
    This is MUCH faster than calculating from birth and filtering.

    Args:
        parent_start_jd: Julian Day of parent period start
        parent_end_jd: Julian Day of parent period end
        parent_lord: Full lord chain of parent (e.g., "Ju/Me/Su")
        ayanamsa: Ayanamsa number
        tz_offset_hours: UTC offset (same as birth data) so that is_current
            comparison uses the same local-time JD space as the dasha JDs.

    Returns:
        Formatted list of 9 sub-dashas within parent period
    """
    from datetime import datetime

    # Mapping from abbreviated names to full names
    abbrev_to_full = {
        'Ke': 'Ketu',
        'Ve': 'Venus',
        'Su': 'Sun',
        'Mo': 'Moon',
        'Ma': 'Mars',
        'Ra': 'Rahu',
        'Ju': 'Jupiter',
        'Sa': 'Saturn',
        'Me': 'Mercury'
    }

    # Reverse mapping (full names to abbreviated)
    full_to_abbrev = {v: k for k, v in abbrev_to_full.items()}

    # Calculate parent duration
    parent_duration_days = parent_end_jd - parent_start_jd

    # Get starting lord from parent_lord (last element after split)
    parent_lords = parent_lord.split('/')
    last_lord_abbrev = parent_lords[-1]

    # Convert abbreviated name to full name
    last_lord = abbrev_to_full.get(last_lord_abbrev, last_lord_abbrev)

    # Find index of last lord in DASHAS
    start_idx = None
    for i, dasha in enumerate(DASHAS):
        if dasha[LORD] == last_lord:
            start_idx = i
            break

    if start_idx is None:
        print(f"[DASHA DEBUG] WARNING: Could not find lord '{last_lord}' (from '{last_lord_abbrev}') in DASHAS")
        return []  # Invalid lord

    # Calculate sub-periods using Vimshottari proportions
    result = []
    current_jd = parent_start_jd

    # Get current date for is_current check.
    # Dasha JDs are in the chart's local-time JD space (birth_jd uses local hour),
    # so today_jd must also be in local-time JD space for an accurate comparison,
    # especially at level 4/5 where periods are only hours long.
    now = datetime.utcnow()
    today_jd_utc = swe.julday(now.year, now.month, now.day,
                              now.hour + now.minute/60 + now.second/3600)
    today_jd = today_jd_utc + tz_offset_hours / 24.0

    # Generate 9 sub-periods in sequence
    for i in range(9):
        sub_idx = (start_idx + i) % 9
        sub_lord_full = DASHAS[sub_idx][LORD]
        sub_years = DASHAS[sub_idx][LENGTH]

        # Convert full name back to abbreviated for display
        sub_lord_abbrev = full_to_abbrev.get(sub_lord_full, sub_lord_full)

        # Calculate proportional duration
        proportion = sub_years / 120.0  # Total Vimshottari cycle = 120 years
        sub_duration_days = parent_duration_days * proportion
        sub_end_jd = current_jd + sub_duration_days

        # Build display lord (append to parent chain)
        display_lord = f"{parent_lord}/{sub_lord_abbrev}"

        # Convert JD to date/time
        year, month, day, hour_decimal = swe.revjul(current_jd, get_calendar_flag_from_jd(current_jd))
        hour = int(hour_decimal)
        minute = int((hour_decimal - hour) * 60)
        date_str = f"{int(month):02d}/{int(day):02d}/{int(year):04d}"
        time_str = f"{hour:02d}:{minute:02d}"

        # Calculate age from parent start
        age_days = current_jd - parent_start_jd
        years = int(age_days / 365.25)
        months = int((age_days % 365.25) / 30.44)
        age_str = f"{years}yrs {months}mts"

        # Check if current
        is_current = current_jd <= today_jd < sub_end_jd

        # Calculate indent level (parent level + 1)
        indent_level = len(parent_lords)

        result.append({
            'lord': display_lord,
            'date': date_str,
            'time': time_str,
            'age': age_str,
            'is_current': is_current,
            'jd': current_jd,
            'end_jd': sub_end_jd,
            'level': indent_level,
            'indent': "  " * indent_level
        })

        current_jd = sub_end_jd

    return result


def calculate_dasha_from_birth_data(year, month, day, hour, minute, second=0,
                                    dlevels=1, ayanamsa=98,
                                    tz_offset_hours=0, moon_jd_override=None,
                                    nak_mode="neither", **_ignored):
    """
    Convenience function to calculate dasha from birth data.

    Args:
        year, month, day, hour, minute, second: Birth date/time components (LOCAL time)
        dlevels: Number of dasha levels (1=mahadasha, 2=antardasha, 3=pratyantar, etc.)
        ayanamsa: Ayanamsa number (999=Tropical, 0-46=Swiss Eph, 98/100=Custom)
        tz_offset_hours: UTC offset in hours (e.g., 1.0 for CET, 5.5 for IST).
        moon_jd_override: If set (float, UT), override Moon lookup JD (for Human Design).

    Returns:
        Formatted dasha data ready for display
    """
    hour_decimal = hour + minute / 60.0 + second / 3600.0
    birth_jd = swe.julday(year, month, day, hour_decimal,
                          get_calendar_flag(year, month, day))

    dasha_data = calculate_vimshottari_dasha(
        birth_jd, dlevels=dlevels, yrlen=DEFAULT_YEAR_LENGTH,
        ayanamsa=ayanamsa,
        tz_offset_hours=tz_offset_hours,
        moon_jd_override=moon_jd_override,
        nak_mode=nak_mode,
    )

    # Format for display - increase limits for deeper levels to reach current periods
    if dlevels == 1:
        max_periods = 50  # 9 mahadashas
    elif dlevels == 2:
        max_periods = 200  # 81 antardashas + context
    elif dlevels == 3:
        max_periods = 1000  # Enough to reach current periods
    elif dlevels == 4:
        max_periods = 5000  # Deep nested periods - increased for level 4
    else:  # dlevels >= 5
        max_periods = 50000  # Maximum depth - level 5 needs MANY entries to reach current periods

    # Compute today_jd in the chart's local-time JD space (matching birth_jd)
    # so that is_current highlights the correct period at deep levels.
    from datetime import datetime
    _now = datetime.utcnow()
    _now_jd_utc = swe.julday(_now.year, _now.month, _now.day,
                             _now.hour + _now.minute/60 + _now.second/3600)
    today_jd_local = _now_jd_utc + tz_offset_hours / 24.0

    formatted = format_dasha_for_display(dasha_data, birth_jd,
                                         max_periods=max_periods,
                                         today_jd=today_jd_local)

    return formatted


if __name__ == "__main__":
    # Test with example data (Ernst Wilhelm: Nov 11, 1970, 07:55 UTC)
    test_data = calculate_dasha_from_birth_data(1970, 11, 11, 7, 55, 0)

    print("Vimshottari Dasha (Dhruva GC Equatorial)")
    print("=" * 60)
    for entry in test_data[:10]:
        current_mark = " <-- CURRENT" if entry['is_current'] else ""
        print(f"{entry['lord']:4} {entry['date']:12} {entry['time']:6} {entry['age']:15}{current_mark}")
