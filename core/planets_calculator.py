# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Birth Chart Calculator — formatting utilities and libaditya bridge dispatch.

All ephemeris computation is delegated to libaditya via the bridge module.
This file retains zodiac formatting functions used across the codebase.
"""

from libaditya import swe
from datetime import datetime
from zoneinfo import ZoneInfo

# Ephemeris path is owned by libaditya. On import, libaditya calls
# swe.set_ephe_path(<libaditya>/ephe/) (see libaditya/__init__.py). Since
# libaditya is now vendored into this repo, its bundled ephe/ is the single
# source of truth — we no longer override the path to a separate ./ephe.
# (libaditya's ephe is a superset of the old ./ephe, incl. seleapsec.txt.)

# Julian Day threshold for the Gregorian calendar reform: Oct 15, 1582, 00:00 UT
GREGORIAN_REFORM_JD = 2299160.5

_JUL_CAL = 0
_GREG_CAL = 1

def get_calendar_flag(year, month, day):
    """Return swe.JUL_CAL for dates before the Gregorian reform (Oct 15, 1582).

    Historical birth dates before the reform are recorded in the Julian calendar.
    Post-1582 dates from late-adopting countries (Russia 1918, England 1752, etc.)
    are assumed to be already converted to Gregorian by the data source.
    """
    if (year < 1582) or (year == 1582 and month < 10) or \
       (year == 1582 and month == 10 and day < 15):
        return swe.JUL_CAL
    return swe.GREG_CAL

def get_calendar_flag_from_jd(jd):
    """Return swe.JUL_CAL for Julian Day numbers before the Gregorian reform.

    Use this for swe.revjul() calls where you have a JD but not a calendar date.
    """
    return swe.JUL_CAL if jd < GREGORIAN_REFORM_JD else swe.GREG_CAL

def format_to_zodiac(decimal_degrees, include_seconds=True):
    """
    Converts 0-360 decimal degrees into a Zodiac string (Sign DD° MM' SS").

    Args:
        decimal_degrees (float): Decimal degrees (0-360)
        include_seconds (bool): Whether to include seconds (default True)

    Returns:
        str: Formatted zodiac string (e.g., "Taurus 15° 30' 45"" or "Taurus 15° 30'")
    """
    zodiac_signs = [
        "Aries", "Taurus", "Gemini", "Cancer",
        "Leo", "Virgo", "Libra", "Scorpio",
        "Sagittarius", "Capricorn", "Aquarius", "Pisces"
    ]

    # Ensure degrees are 0-360
    decimal_degrees = decimal_degrees % 360

    # 1 sign = 30 degrees
    sign_index = int(decimal_degrees // 30)
    sign_name = zodiac_signs[sign_index]

    # Get degrees within the sign (0-29.99)
    deg_in_sign = decimal_degrees % 30

    # Extract Degrees, Minutes, Seconds (with proper rounding)
    d = int(deg_in_sign)
    m_frac = (deg_in_sign - d) * 60
    m = int(m_frac)
    s = round((m_frac - m) * 60)  # Use round instead of int for proper rounding

    # Handle rounding edge cases
    if s == 60:
        s = 0
        m += 1
    if m == 60:
        m = 0
        d += 1

    if include_seconds:
        return f"{sign_name} {d}° {m}' {s}\""
    else:
        return f"{sign_name} {d}° {m}'"

def get_sign_name(decimal_degrees):
    """Get just the zodiac sign name."""
    zodiac_signs = [
        "Aries", "Taurus", "Gemini", "Cancer",
        "Leo", "Virgo", "Libra", "Scorpio",
        "Sagittarius", "Capricorn", "Aquarius", "Pisces"
    ]
    decimal_degrees = decimal_degrees % 360
    sign_index = int(decimal_degrees // 30)
    return zodiac_signs[sign_index]

def get_sign_index(decimal_degrees):
    """Get zodiac sign index (0-11)."""
    decimal_degrees = decimal_degrees % 360
    return int(decimal_degrees // 30)

def get_house_sign(ascendant_sign_index, house_number):
    """
    Get the zodiac sign for a house using Whole Sign House System.

    In Whole Sign system, houses are defined by zodiac signs.
    House 1 is the sign of the Ascendant, House 2 is the next sign, etc.

    Args:
        ascendant_sign_index: Sign index of Ascendant (0-11, where 0=Aries)
        house_number: House number (1-12)

    Returns:
        Tuple: (sign_name, sign_index, start_degree, end_degree)
    """
    zodiac_signs = [
        "Aries", "Taurus", "Gemini", "Cancer",
        "Leo", "Virgo", "Libra", "Scorpio",
        "Sagittarius", "Capricorn", "Aquarius", "Pisces"
    ]

    # Calculate which sign this house is in
    # House 1 = Ascendant sign, House 2 = next sign, etc.
    house_sign_index = (ascendant_sign_index + (house_number - 1)) % 12
    house_sign_name = zodiac_signs[house_sign_index]

    # Calculate degree range for this sign
    start_degree = house_sign_index * 30
    end_degree = start_degree + 30

    return (house_sign_name, house_sign_index, start_degree, end_degree)

def get_aditya_circle_degrees(tropical_degrees):
    """
    Convert tropical zodiac degrees to Aditya Circle degrees.

    In Aditya Circle, each sign is shifted by 1 position.
    Tropical Aries 0° becomes Aditya Circle Taurus 0° (which is 30° in absolute terms).
    This shifts all planets forward by 30°.

    Args:
        tropical_degrees: Degrees in tropical zodiac (0-360)

    Returns:
        float: Degrees in Aditya Circle system (0-360)
    """
    aditya_circle_deg = (tropical_degrees + 30) % 360
    return aditya_circle_deg

def get_aditya_circle_name(sign_index):
    """
    Get the Aditya Circle name for a sign (direct mapping, no shift).

    Aries gets Dhata, Taurus gets Aryama, Gemini gets Mitra, etc.

    Args:
        sign_index: Sign index (0-11, where 0=Aries)

    Returns:
        str: Aditya Circle name
    """
    aditya_circle = [
        "Dhata",        # 0: Aries
        "Aryama",       # 1: Taurus
        "Mitra",        # 2: Gemini
        "Varuna",       # 3: Cancer
        "Indra",        # 4: Leo
        "Vivasvan",     # 5: Virgo
        "Tvasta",       # 6: Libra
        "Vishnu",       # 7: Scorpio
        "Amzu",         # 8: Sagittarius
        "Bhaga",        # 9: Capricorn
        "Pusha",        # 10: Aquarius
        "Parjanya"      # 11: Pisces
    ]
    return aditya_circle[sign_index % 12]

def get_aditya_classic_name(sign_index):
    """
    Get the Aditya Classic name for a sign (same positions as tropical, no shift).

    Aditya Classic uses Aditya names at tropical positions:
    Aries(0)=Dhata, Taurus(1)=Aryama, Gemini(2)=Mitra, etc.

    Args:
        sign_index: Sign index (0-11, where 0=Aries)

    Returns:
        str: Aditya Classic name
    """
    aditya_classic = [
        "Dhata",        # 0: Aries
        "Aryama",       # 1: Taurus
        "Mitra",        # 2: Gemini
        "Varuna",       # 3: Cancer
        "Indra",        # 4: Leo
        "Vivasvan",     # 5: Virgo
        "Tvasta",       # 6: Libra
        "Vishnu",       # 7: Scorpio
        "Amzu",         # 8: Sagittarius
        "Bhaga",        # 9: Capricorn
        "Pusha",        # 10: Aquarius
        "Parjanya"      # 11: Pisces
    ]
    return aditya_classic[sign_index % 12]

def get_all_planets_data(year, month, day, hour, minute, lat, lon, timezone_str, second=0):
    """
    Calculate positions of all planets and lunar nodes.

    .. deprecated::
        Use ``Chart(EphContext(...))`` directly. Will be deleted in Issue 11.
    """
    import warnings
    warnings.warn(
        "get_all_planets_data() is deprecated — use Chart(EphContext(...)) directly. "
        "Will be deleted in Chart-Everywhere Issue 11.",
        DeprecationWarning, stacklevel=2,
    )
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from libaditya.objects.context import EphContext, Circle
    from libaditya.objects.julian_day import JulianDay
    from libaditya.objects.location import Location
    from libaditya.charts.chart import Chart
    from libaditya import constants as const
    from core.planets_data_compat import chart_to_planets_data

    if year < 1:
        utc_year, utc_month, utc_day = year, month, day
        utc_hour, utc_minute, utc_second = hour, minute, second
    else:
        local_dt = datetime(year, month, day, hour, minute, second,
                            tzinfo=ZoneInfo(timezone_str))
        utc_dt = local_dt.astimezone(ZoneInfo("UTC"))
        utc_year, utc_month, utc_day = utc_dt.year, utc_dt.month, utc_dt.day
        utc_hour, utc_minute, utc_second = utc_dt.hour, utc_dt.minute, utc_dt.second

    utc_decimal = utc_hour + (utc_minute / 60.0) + (utc_second / 3600.0)
    jd = JulianDay((utc_year, utc_month, utc_day, utc_decimal), utcoffset=0.0)
    loc = Location(lat=lat, long=lon, alt=0, placename="", utcoffset=0.0)
    ctx = EphContext(
        timeJD=jd,
        location=loc,
        sysflg=const.TROP,
        circle=Circle.ZODIAC,
        sign_names="adityas",
        signize=False,
        toround=(False, 10),
    )
    chart = Chart(ctx)
    return chart_to_planets_data(chart, year, month, day, hour, minute,
                                 lat, lon, timezone_str, second)

def print_birth_chart(data, name="", location=""):
    """
    Pretty print the complete birth chart.

    Args:
        data (dict): Result dictionary from get_all_planets_data
        name (str): Person's name
        location (str): Birth location
    """
    if "error" in data:
        print(f"ERROR: {data['error']}")
        return

    print("\n" + "="*70)
    print("COMPLETE BIRTH CHART CALCULATION".center(70))
    print("="*70)

    if name:
        print(f"Name: {name}".center(70))
    if location:
        print(f"Location: {location}".center(70))

    print(f"Local Time:      {data['local_time']}")
    print(f"UTC Time:        {data['utc_time']}")
    print(f"Timezone:        {data['timezone']}")
    print(f"Coordinates:     {data['latitude']}°N, {abs(data['longitude'])}°W")
    print(f"Julian Day:      {data['julian_day']:.6f}")

    print("\n" + "-"*70)
    print("ANGLES (Campanus House System)".center(70))
    print("-"*70)

    if "angles" in data:
        for angle_name, info in data["angles"].items():
            print(f"{angle_name:20} | {info['formatted']:20} | {info['decimal_degrees']:8.4f}°")

    print("\n" + "-"*70)
    print("PLANETARY POSITIONS (in order)".center(70))
    print("-"*70)

    # Define the order of display
    display_order = [
        "Sun", "Moon", "Mars", "Mercury",
        "Jupiter", "Venus", "Saturn", "Rahu", "Ketu",
        "Uranus", "Neptune", "Pluto"
    ]

    for body in display_order:
        if body in data and isinstance(data[body], dict):
            info = data[body]
            print(f"{body:12} | {info['formatted']:20} | {info['decimal_degrees']:8.4f}°")

    print("\n" + "-"*70)
    print("HOUSES (Campanus System)".center(70))
    print("-"*70)

    if "houses" in data:
        for house_name, info in data["houses"].items():
            print(f"{house_name:12} | {info['formatted']:20} | {info['decimal_degrees']:8.4f}°")

    print("="*70 + "\n")

def print_birth_chart_detailed(data, name="", location=""):
    """
    Print the birth chart with more detailed information.

    Args:
        data (dict): Result dictionary from get_all_planets_data
        name (str): Person's name
        location (str): Birth location
    """
    if "error" in data:
        print(f"ERROR: {data['error']}")
        return

    print("\n" + "="*80)
    print("COMPLETE BIRTH CHART - DETAILED VIEW".center(80))
    print("="*80)

    if name:
        print(f"Name: {name}".center(80))
    if location:
        print(f"Location: {location}".center(80))

    print(f"\nLocal Time:      {data['local_time']}")
    print(f"UTC Time:        {data['utc_time']}")
    print(f"Timezone:        {data['timezone']}")
    print(f"Coordinates:     {data['latitude']}°N, {abs(data['longitude'])}°W")

    print("\n" + "-"*80)
    print("ANGLES (Campanus House System)".center(80))
    print("-"*80)
    print(f"{'Angle':<20} | {'Zodiac Position':<20} | {'Sign':<12} | {'Raw Degrees':>12}")
    print("-"*80)

    if "angles" in data:
        for angle_name, info in data["angles"].items():
            print(f"{angle_name:<20} | {info['formatted']:<20} | {info['sign']:<12} | {info['decimal_degrees']:>12.4f}°")

    print("\n" + "-"*80)
    print("PLANETARY POSITIONS".center(80))
    print("-"*80)
    print(f"{'Body':<12} | {'Zodiac Position':<20} | {'Sign':<12} | {'Raw Degrees':>12}")
    print("-"*80)

    # Define the order of display
    display_order = [
        "Sun", "Moon", "Mars", "Mercury",
        "Jupiter", "Venus", "Saturn", "Rahu", "Ketu",
        "Uranus", "Neptune", "Pluto"
    ]

    for body in display_order:
        if body in data and isinstance(data[body], dict):
            info = data[body]
            print(f"{body:<12} | {info['formatted']:<20} | {info['sign']:<12} | {info['decimal_degrees']:>12.4f}°")

    print("\n" + "-"*80)
    print("HOUSES (Campanus System)".center(80))
    print("-"*80)
    print(f"{'House':<12} | {'Zodiac Position':<20} | {'Sign':<12} | {'Raw Degrees':>12}")
    print("-"*80)

    if "houses" in data:
        for house_name, info in data["houses"].items():
            print(f"{house_name:<12} | {info['formatted']:<20} | {info['sign']:<12} | {info['decimal_degrees']:>12.4f}°")

    print("="*80 + "\n")

def get_planetary_summary(data):
    """
    Get a summary of all planetary positions as a dictionary.

    Args:
        data (dict): Result dictionary from get_all_planets_data

    Returns:
        dict: Summary with just the formatted zodiac positions
    """
    summary = {}
    display_order = [
        "Ascendant", "Sun", "Moon", "Mars", "Mercury",
        "Jupiter", "Venus", "Saturn", "Rahu", "Ketu",
        "Uranus", "Neptune", "Pluto"
    ]

    for body in display_order:
        if body in data and isinstance(data[body], dict):
            summary[body] = data[body]["formatted"]

    return summary

def get_first_new_moon_after_ingress(year, ingress_degree=300, latitude=None, longitude=None, timezone='UTC'):
    """
    Calculate the first new moon (Sun-Moon conjunction) after Sun enters a specific degree.

    This is a generalized version that works for any sign ingress, not just Aquarius.

    Args:
        year (int): Gregorian year (e.g., 2025)
        ingress_degree (float): The ecliptic longitude to search from (default 300° = Aquarius/Parjanya)
            - 300° = Parjanya (Aquarius) - Chinese New Year
            - 330° = Dhata (Pisces)
            - 0° = Aryama (Aries)
            - 30° = Mitra (Taurus)
            - etc.
        latitude (float): Observer's latitude (optional, for reference)
        longitude (float): Observer's longitude (optional, for reference)
        timezone (str): IANA timezone for output (default 'UTC')

    Returns:
        dict: {
            'utc': datetime in UTC,
            'local': datetime in the requested timezone,
            'julian_day': JD of the event,
            'sun_position': Sun's longitude at new moon,
            'moon_position': Moon's longitude at new moon,
            'sun_sign': Formatted zodiac position of Sun,
            'moon_sign': Formatted zodiac position of Moon,
            'year': Gregorian year of the event,
            'ingress_jd': JD when Sun entered the specified degree,
            'ingress_date': Gregorian date when Sun entered the specified degree,
            'ingress_degree': The degree used for calculation
        }
    """
    # 1. Find the Sun's ingress into the specified degree
    # Start search from Jan 1 of the target year
    start_jd = swe.julday(year, 1, 1, 0.0, get_calendar_flag(year, 1, 1))
    ingress_jd = swe.solcross(ingress_degree, start_jd)  # JD when Sun reaches specified degree

    # 2. Search forward for the next new moon after the ingress
    # Start exactly at the ingress point to ensure we only find new moons in Aquarius
    search_jd = ingress_jd
    sun_data = swe.calc_ut(search_jd, swe.SUN)
    moon_data = swe.calc_ut(search_jd, swe.MOON)
    sun_lon = sun_data[0][0]
    moon_lon = moon_data[0][0]
    diff = (moon_lon - sun_lon) % 360.0
    if diff > 180:
        diff -= 360
    prev_diff = diff
    step = 1.0  # 1 day

    # Advance until the Moon catches up to the Sun (conjunction)
    for _ in range(60):  # safety limit (should be within 30 days)
        search_jd += step
        sun_data = swe.calc_ut(search_jd, swe.SUN)
        moon_data = swe.calc_ut(search_jd, swe.MOON)
        sun_lon = sun_data[0][0]
        moon_lon = moon_data[0][0]
        diff = (moon_lon - sun_lon) % 360.0

        # Normalize diff to -180 to +180 range for crossing detection
        if diff > 180:
            diff -= 360

        # Detect crossing: diff changes from negative (Moon behind) to positive (Moon ahead)
        # This catches the zero-crossing regardless of starting angle
        if prev_diff < 0 and diff > 0:
            break

        prev_diff = diff
    else:
        raise RuntimeError("Could not locate new moon within 60 days of Aquarius ingress")

    # 3. Refine the exact conjunction via binary search with convergence criterion
    left = search_jd - step
    right = search_jd
    PRECISION_THRESHOLD = 0.0001  # 0.0001° ≈ 0.36 arcseconds (exact conjunction)

    for _ in range(100):  # Safety limit (convergence usually in ~30 iterations)
        mid = (left + right) / 2
        sun_data = swe.calc_ut(mid, swe.SUN)
        moon_data = swe.calc_ut(mid, swe.MOON)
        sun_lon = sun_data[0][0]
        moon_lon = moon_data[0][0]
        diff = (moon_lon - sun_lon) % 360.0
        if diff > 180:          # treat crossing 360° → 0°
            diff -= 360

        # Early termination when precision achieved
        if abs(diff) <= PRECISION_THRESHOLD:
            break

        # If diff < 0: Moon is behind Sun, conjunction is LATER (move left up)
        # If diff > 0: Moon is ahead of Sun, conjunction is EARLIER (move right down)
        if diff < 0:
            left = mid
        else:
            right = mid
    newmoon_jd = (left + right) / 2

    # 4. Get final positions at the EXACT new moon (with full second precision)
    sun_data = swe.calc_ut(newmoon_jd, swe.SUN)
    moon_data = swe.calc_ut(newmoon_jd, swe.MOON)
    sun_position = sun_data[0][0]
    moon_position = moon_data[0][0]

    # 5. Convert JD to UTC datetime WITH SECONDS (exact conjunction time)
    y, m, d, hour_dec = swe.revjul(newmoon_jd, get_calendar_flag_from_jd(newmoon_jd))
    hour = int(hour_dec)
    minute_frac = (hour_dec - hour) * 60
    minute = int(minute_frac)
    second_frac = (minute_frac - minute) * 60
    second = int(second_frac)

    from core.chart_factory import build_chart_from_params
    _nm_chart = build_chart_from_params(jd=newmoon_jd, lat=0.0, lon=0.0, mode='zodiac', ayanamsa=98)
    _nm_planets = _nm_chart.rashi().planets()
    sun_position_display = _nm_planets['Sun'].ecliptic_longitude()
    moon_position_display = _nm_planets['Moon'].ecliptic_longitude()

    utc = datetime(y, m, d, hour, minute, second, 0, tzinfo=ZoneInfo('UTC'))
    local = utc.astimezone(ZoneInfo(timezone))

    # Get ingress date
    ing_y, ing_m, ing_d, ing_hour_dec = swe.revjul(ingress_jd, get_calendar_flag_from_jd(ingress_jd))

    return {
        'utc': utc,
        'local': local,
        'julian_day': newmoon_jd,  # Exact conjunction JD (not floored)
        'sun_position': sun_position_display,
        'moon_position': moon_position_display,
        'sun_sign': format_to_zodiac(sun_position_display),
        'moon_sign': format_to_zodiac(moon_position_display),
        'year': y,
        'ingress_jd': ingress_jd,
        'ingress_date': f"{ing_y}-{ing_m:02d}-{ing_d:02d}",
        'ingress_degree': ingress_degree
    }

def get_chinese_new_year(year, latitude=None, longitude=None, timezone='UTC'):
    """
    Calculate the exact moment of the Chinese New Year for a given Gregorian year.

    This is a convenience wrapper around get_first_new_moon_after_ingress() with
    ingress_degree=300 (Aquarius/Parjanya).

    Args:
        year (int): Gregorian year (e.g., 2025)
        latitude (float): Observer's latitude (optional, for reference)
        longitude (float): Observer's longitude (optional, for reference)
        timezone (str): IANA timezone for output (default 'UTC')

    Returns:
        Same as get_first_new_moon_after_ingress()
    """
    return get_first_new_moon_after_ingress(year, 300, latitude, longitude, timezone)

def get_chinese_new_year_equatorial(year, latitude=None, longitude=None, timezone='UTC'):
    """
    Calculate the exact moment of Chinese New Year using RIGHT ASCENSION conjunction.

    This is the "proper" prime meridian calculation method used by professional
    professional astrology software. Instead of comparing ecliptic longitudes,
    it compares Right Ascension (RA) coordinates in the equatorial system.

    Due to the 23.4° obliquity between ecliptic and equator, RA conjunction
    happens at a DIFFERENT time than ecliptic longitude conjunction.

    Args:
        year (int): Gregorian year (e.g., 2025)
        latitude (float): Observer's latitude (optional, for reference)
        longitude (float): Observer's longitude (optional, for reference)
        timezone (str): IANA timezone for output (default 'UTC')

    Returns:
        dict: {
            'utc': datetime in UTC,
            'local': datetime in requested timezone,
            'julian_day': JD of the RA conjunction,
            'sun_ra': Sun's Right Ascension at conjunction (degrees),
            'moon_ra': Moon's Right Ascension at conjunction (degrees),
            'sun_dec': Sun's Declination (degrees),
            'moon_dec': Moon's Declination (degrees),
            'sun_ecliptic': Sun's ecliptic longitude (for comparison),
            'moon_ecliptic': Moon's ecliptic longitude (for comparison),
            'sun_sign': Formatted ecliptic position,
            'moon_sign': Formatted ecliptic position,
            'year': Gregorian year of event,
            'ingress_jd': JD when Sun entered Aquarius (ecliptic),
            'ingress_date': Gregorian date of ingress,
            'ra_difference': Final RA difference in degrees (should be ~0)
        }
    """
    # 1. Find Sun's ingress into Aquarius (still use ecliptic for this)
    start_jd = swe.julday(year, 1, 1, 0.0, get_calendar_flag(year, 1, 1))
    ingress_jd = swe.solcross(300, start_jd)  # 300° = 0° Aquarius

    # 2. Set up flags for EQUATORIAL coordinates with SPEED vectors
    iflag = swe.FLG_SWIEPH | swe.FLG_EQUATORIAL | swe.FLG_SPEED

    # 3. Coarse search: Find approximate RA conjunction
    search_jd = ingress_jd
    sun_data, _ = swe.calc_ut(search_jd, swe.SUN, iflag)
    moon_data, _ = swe.calc_ut(search_jd, swe.MOON, iflag)

    # Use difdeg2n for circular normalization (handles 0°/360° wraparound)
    prev_diff = swe.difdeg2n(sun_data[0], moon_data[0])
    step = 1.0  # 1 day

    # Advance until Moon's RA catches up to Sun's RA
    for _ in range(60):  # safety limit
        search_jd += step
        sun_data, _ = swe.calc_ut(search_jd, swe.SUN, iflag)
        moon_data, _ = swe.calc_ut(search_jd, swe.MOON, iflag)

        # difdeg2n returns signed difference (-180 to +180)
        # Negative = Moon ahead (has caught up and passed Sun)
        # Positive = Moon still behind Sun
        diff = swe.difdeg2n(sun_data[0], moon_data[0])

        # Detect crossing: diff changes from positive (Moon behind) to negative (Moon ahead)
        # Look for the zero-crossing where conjunction happens
        if prev_diff > 0 and diff < 0:
            break
        prev_diff = diff
    else:
        raise RuntimeError("Could not locate RA conjunction within 60 days")

    # 4. Binary search refinement for exact RA conjunction
    # (More stable than Newton-Raphson due to Moon's varying RA speed)
    left = search_jd - step
    right = search_jd

    for iteration in range(20):  # 20 iterations gives microsecond precision
        mid = (left + right) / 2
        sun_data, _ = swe.calc_ut(mid, swe.SUN, iflag)
        moon_data, _ = swe.calc_ut(mid, swe.MOON, iflag)

        sun_ra = sun_data[0]
        moon_ra = moon_data[0]

        # Calculate RA difference
        diff = swe.difdeg2n(sun_ra, moon_ra)

        # difdeg2n returns (sun - moon):
        # Positive = Moon behind Sun, conjunction is LATER
        # Negative = Moon ahead of Sun, conjunction is EARLIER
        if diff > 0:
            left = mid  # Move search forward
        else:
            right = mid  # Move search backward

    newmoon_jd = (left + right) / 2

    # 5. Get final coordinates at exact RA conjunction
    # Equatorial coordinates
    sun_eq, _ = swe.calc_ut(newmoon_jd, swe.SUN, iflag)
    moon_eq, _ = swe.calc_ut(newmoon_jd, swe.MOON, iflag)

    # Also get ecliptic coordinates for comparison
    sun_ecl, _ = swe.calc_ut(newmoon_jd, swe.SUN, swe.FLG_SWIEPH)
    moon_ecl, _ = swe.calc_ut(newmoon_jd, swe.MOON, swe.FLG_SWIEPH)

    # 6. Convert JD to UTC datetime
    y, m, d, hour_dec = swe.revjul(newmoon_jd, get_calendar_flag_from_jd(newmoon_jd))
    hour = int(hour_dec)
    minute = int((hour_dec - hour) * 60)
    second = int(((hour_dec - hour) * 60 - minute) * 60)
    microsecond = int((((hour_dec - hour) * 60 - minute) * 60 - second) * 1_000_000)

    utc = datetime(y, m, d, hour, minute, second, microsecond, tzinfo=ZoneInfo('UTC'))
    local = utc.astimezone(ZoneInfo(timezone))

    # Get ingress date
    ing_y, ing_m, ing_d, ing_hour_dec = swe.revjul(ingress_jd, get_calendar_flag_from_jd(ingress_jd))

    return {
        'utc': utc,
        'local': local,
        'julian_day': newmoon_jd,
        'sun_ra': sun_eq[0],
        'moon_ra': moon_eq[0],
        'sun_dec': sun_eq[1],
        'moon_dec': moon_eq[1],
        'sun_ecliptic': sun_ecl[0],
        'moon_ecliptic': moon_ecl[0],
        'sun_sign': format_to_zodiac(sun_ecl[0]),
        'moon_sign': format_to_zodiac(moon_ecl[0]),
        'year': y,
        'ingress_jd': ingress_jd,
        'ingress_date': f"{ing_y}-{ing_m:02d}-{ing_d:02d}",
        'ra_difference': swe.difdeg2n(sun_eq[0], moon_eq[0])
    }

