#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Bala Calculator Module - Planetary Strength Calculations

Computes the 3 main Shadbala components:
    1. Digbala (Direction Strength) - Distance from best house cusp (0-60)
    2. Uccha (Exaltation Strength) - Distance from exaltation degree (0-60)
    3. Chesta (Motion Strength) - Retrograde/speed based (0-60)

Combined Score:
    DEC Bala = ∛(Digbala × Uccha × Chesta) - Geometric Mean

All formulas verified against reference charts (Dec 2025).

Uccha supports DUAL ZODIAC SYSTEMS via aditya_mode parameter:
- "aditya" (default): Aditya Circle exaltation degrees (shifted -30° from traditional)
- "tropical_classic": Tropical Classic exaltation degrees (traditional Western astrology)

Aditya signs occupy tropical positions shifted -30° from their energy equivalent.
Example: Bhaga has Capricorn energy but occupies tropical Sagittarius (240-270°).

Usage:
    # from core.bala_calculator import get_all_bala_data
    # bala_data = get_all_bala_data(chart)   # Chart-Everywhere Issue 14

Reference:
    # - internal planetary-strengths research notes
    # - test/test_all_chesta.py
"""

import math

try:
    from libaditya import swe
    HAS_SWISSEPH = True
except ImportError:
    HAS_SWISSEPH = False

# ============================================================
# CONSTANTS
# ============================================================

# Exaltation degrees in ADITYA CIRCLE format (shifted -30° from traditional)
# Aditya signs: Dhata=330-360°, Aryama=0-30°, Mitra=30-60°, Varuna=60-90°,
# Indra=90-120°, Vivasvan=120-150°, Tvasta=150-180°, Vishnu=180-210°,
# Amzu=210-240°, Bhaga=240-270°, Pusha=270-300°, Parjanya=300-330°
EXALTATION_DEGREES_ADITYA = {
    'Sun': 340.0,      # 10° Dhata (Aries energy at tropical Pisces 330-360°)
    'Moon': 3.0,       # 3° Aryama (Taurus energy at tropical Aries 0-30°)
    'Mars': 268.0,     # 28° Bhaga (Capricorn energy at tropical Sag 240-270°)
    'Mercury': 135.0,  # 15° Vivasvan (Virgo energy at tropical Leo 120-150°)
    'Jupiter': 65.0,   # 5° Varuna (Cancer energy at tropical Gemini 60-90°)
    'Venus': 327.0,    # 27° Parjanya (Pisces energy at tropical Aqua 300-330°)
    'Saturn': 170.0,   # 20° Tvasta (Libra energy at tropical Virgo 150-180°)
}

# Exaltation degrees in TROPICAL CLASSIC format (traditional Western astrology)
EXALTATION_DEGREES_TROPICAL = {
    'Sun': 10.0,       # 10° Aries
    'Moon': 33.0,      # 3° Taurus
    'Mars': 298.0,     # 28° Capricorn
    'Mercury': 165.0,  # 15° Virgo
    'Jupiter': 95.0,   # 5° Cancer
    'Venus': 357.0,    # 27° Pisces
    'Saturn': 200.0,   # 20° Libra
}

# Default (backwards compatibility) - points to Aditya system
EXALTATION_DEGREES = EXALTATION_DEGREES_ADITYA

STRENGTH_THRESHOLD = 45

# Best house for each planet (Digbala)
# Value is the house number (1-12) where planet has maximum Digbala
BEST_HOUSE = {
    'Sun': 10,      # 10th house cusp (MC)
    'Moon': 4,      # 4th house cusp (IC)
    'Mars': 10,     # 10th house cusp (MC)
    'Mercury': 1,   # 1st house cusp (Ascendant)
    'Jupiter': 1,   # 1st house cusp (Ascendant)
    'Venus': 4,     # 4th house cusp (IC)
    'Saturn': 7,    # 7th house cusp (Descendant)
}

# Swiss Ephemeris planet IDs
PLANET_IDS = {
    'Sun': 0,       # swe.SUN
    'Moon': 1,      # swe.MOON
    'Mars': 4,      # swe.MARS
    'Mercury': 2,   # swe.MERCURY
    'Jupiter': 5,   # swe.JUPITER
    'Venus': 3,     # swe.VENUS
    'Saturn': 6,    # swe.SATURN
}

# ============================================================
# HELPER FUNCTIONS
# ============================================================

def get_planet_speed(planet_name, julian_day):
    """
    Get planet's daily motion (speed) from Swiss Ephemeris.

    Args:
        planet_name: One of Sun, Moon, Mars, Mercury, Jupiter, Venus, Saturn
        julian_day: Julian Day number

    Returns:
        Speed in degrees/day (negative = retrograde)
    """
    if not HAS_SWISSEPH or planet_name not in PLANET_IDS:
        return 1.0  # Default speed

    planet_id = PLANET_IDS[planet_name]
    try:
        result = swe.calc_ut(julian_day, planet_id)
        return result[0][3]  # Speed is index 3
    except Exception:
        return 1.0

def _get_venus_synodic_angle(julian_day, sun_longitude):
    """
    Compute Venus heliocentric synodic angle (Venus_helio - Earth_helio).

    The synodic angle is the angular separation between Venus and Earth
    as seen from the Sun. This is the true underlying variable for
    Venus Cheshta Bala — it maps 1:1 to the classical 8-state cycle.

    Returns angle in 0-360° where:
      0°   = inferior conjunction (Venus between Earth and Sun, retrograde)
      180° = superior conjunction (Venus behind Sun, max direct speed)

    Args:
        julian_day: Julian Day number
        sun_longitude: Sun's geocentric longitude (used to derive Earth's
                       heliocentric position as sun_long + 180°)

    Returns:
        Synodic angle in degrees (0-360), or None if Swiss Ephemeris unavailable
    """
    if not HAS_SWISSEPH:
        return None

    try:
        flag_helctr = getattr(swe, 'FLG_HELCTR', 8)
        venus_helio = swe.calc_ut(julian_day, PLANET_IDS['Venus'], flag_helctr)
        earth_helio_long = (sun_longitude + 180.0) % 360.0
        synodic = (venus_helio[0][0] - earth_helio_long) % 360.0
        return synodic
    except Exception:
        return None

# ============================================================
# DIGBALA (Direction Strength)
# ============================================================

def calculate_digbala(planet_longitude, house_cusps, planet_name,
                      jd_ut=None, lat=None, lon=None,
                      armc=None, eps=None, hsys="C"):
    """
    Calculate Digbala (Directional Strength) for a planet.

    Digbala measures how close a planet is to its best house position
    using Swiss House positions (swe.house_pos) to plot planets in
    Campanus house space, not zodiacal space.

    Algorithm:
        - Uses swe.house_pos() to calculate planet position in house space
        - Each house is normalized to 30° regardless of actual zodiacal size
        - Maximum strength (60) at exact best house cusp
        - Minimum strength (0) at opposite house (180° away in house space)
        - Linear interpolation between

    Args:
        planet_longitude: Planet's tropical longitude (0-360°)
        house_cusps: Dict with house cusp degrees from planets_calculator
                    Keys: "House 1 (Ascendant)", "House 4 (Imum Coeli)", etc.
        planet_name: One of Sun, Moon, Mars, Mercury, Jupiter, Venus, Saturn
        jd_ut: Julian Day (UT) for Swiss Ephemeris calculation
        lat: Geographic latitude
        lon: Geographic longitude
        armc: Pre-computed ARMC (sidereal time). Chart-level value — identical
              for all planets in the same chart. If None, computed from jd_ut/lat/lon.
              Hoist this out of the caller's loop to avoid 7x redundant swe.houses() calls.
        eps: Pre-computed obliquity of ecliptic. Chart-level value — identical
             for all planets in the same chart. If None, computed from jd_ut.
             Hoist this out of the caller's loop to avoid 7x redundant swe.calc_ut(ECL_NUT) calls.

    Returns:
        Digbala value (0-60)

    Reference:
        - Sun/Mars → best at 10th house
        - Moon/Venus → best at 4th house
        - Mercury/Jupiter → best at 1st house (Ascendant)
        - Saturn → best at 7th house

    Note:
        Requires Swiss Ephemeris parameters (jd_ut, lat, lon) for accurate
        house position calculation. Falls back to zodiacal distance method
        if these are not provided.
    """
    if planet_name not in BEST_HOUSE:
        return 30.0  # Default for Rahu/Ketu

    best_house_num = BEST_HOUSE[planet_name]

    # If Swiss Ephemeris parameters are available, use house position method
    if jd_ut is not None and lat is not None and lon is not None:
        try:
            # Use pre-computed ARMC and eps if provided by caller; otherwise
            # compute them here. Hoisting these out of the 7-planet loop in
            # get_all_bala_data() avoids 14 redundant swe calls per chart.
            if armc is None or eps is None:
                _, ascmc = swe.houses(jd_ut, lat, lon, hsys.encode())
                armc = ascmc[2]  # ARMC (sidereal time)
                eps = swe.calc_ut(jd_ut, swe.ECL_NUT)[0][0]  # obliquity of ecliptic

            # Calculate planet position in the active house system's space.
            # swe.house_pos returns house number as float (1.0-13.0)
            # where 1.0 = start of House 1, 1.5 = middle of House 1, etc.
            # SPEC-HSY-001 §6.1: this MUST use the same code as swe.houses()
            # above — the ARMC and the house_pos lookup share a house system.
            house_pos = swe.house_pos(armc, lat, eps, (planet_longitude, 0.0), hsys.encode())

            # Handle house 0 (wraps to house 12)
            house_num = int(house_pos)
            if house_num == 0:
                house_num = 12

            # Calculate distance from planet's house position to best house
            # In house space, each house is 30° (normalized)
            house_distance = abs(house_pos - best_house_num)
            if house_distance > 6:
                house_distance = 12 - house_distance

            # Convert house distance to degrees (each house = 30° in normalized space)
            distance_degrees = house_distance * 30.0

            # Calculate Digbala
            digbala = 60.0 * (1.0 - distance_degrees / 180.0)

            return max(0.0, min(60.0, digbala))

        except Exception as e:
            # Fall back to zodiacal method if Swiss Ephemeris fails
            import warnings
            warnings.warn(f"Swiss House position calculation failed for {planet_name}: {e}, falling back to zodiacal distance")

    # FALLBACK: Original zodiacal distance method
    # (Used when Swiss Ephemeris parameters not available)
    house_keys = {
        1: "House 1 (Ascendant)",
        4: "House 4 (Imum Coeli)",
        7: "House 7 (Descendant)",
        10: "House 10 (Midheaven)",
    }

    best_key = house_keys.get(best_house_num)
    if not best_key or best_key not in house_cusps:
        return 30.0  # Fallback

    best_cusp = house_cusps[best_key].get('decimal_degrees', 0)

    # Calculate angular distance from best cusp
    distance = abs(planet_longitude - best_cusp)
    if distance > 180:
        distance = 360 - distance

    # Digbala: 60 at cusp, 0 at 180° away (opposite cusp)
    # Linear interpolation: digbala = 60 * (1 - distance/180)
    digbala = 60.0 * (1.0 - distance / 180.0)

    return max(0.0, min(60.0, digbala))

# ============================================================
# UCCHA (Exaltation Strength)
# ============================================================

def calculate_uccha(planet_longitude, planet_name, aditya_mode="aditya"):
    """
    Calculate Uccha (Exaltation Strength) for a planet.

    Uses ADITYA CIRCLE or TROPICAL CLASSIC exaltation degrees based on mode.
    Maximum strength at exact exaltation point, minimum at debilitation (180° away).

    Algorithm:
        - At exaltation degree = 60 (maximum)
        - At debilitation degree = 0 (minimum)
        - Linear interpolation based on distance from exaltation

    Args:
        planet_longitude: Planet's TROPICAL longitude (0-360°)
        planet_name: One of Sun, Moon, Mars, Mercury, Jupiter, Venus, Saturn
        aditya_mode: "aditya" for Aditya system, "tropical_classic" for Tropical

    Returns:
        Uccha value (0-60)

    Exaltation Points:
        ADITYA CIRCLE (shifted -30° from traditional):
            Sun: 340°, Moon: 3°, Mars: 268°, Mercury: 135°,
            Jupiter: 65°, Venus: 327°, Saturn: 170°
        TROPICAL CLASSIC (traditional Western):
            Sun: 10°, Moon: 33°, Mars: 298°, Mercury: 165°,
            Jupiter: 95°, Venus: 357°, Saturn: 200°
    """
    # Select exaltation degrees based on mode
    if aditya_mode == "tropical_classic":
        exaltation_degrees = EXALTATION_DEGREES_TROPICAL
    else:
        exaltation_degrees = EXALTATION_DEGREES_ADITYA

    if planet_name not in exaltation_degrees:
        return 30.0  # Default for Rahu/Ketu

    exaltation = exaltation_degrees[planet_name]

    # Calculate angular distance from exaltation
    distance = abs(planet_longitude - exaltation)
    if distance > 180:
        distance = 360 - distance

    # Uccha: 60 at exaltation, 0 at debilitation (180° away)
    # Linear interpolation: uccha = 60 * (1 - distance/180)
    uccha = 60.0 * (1.0 - distance / 180.0)

    return max(0.0, min(60.0, uccha))

# ============================================================
# CHESTA (Motion Strength) - Copied from test_all_chesta.py
# ============================================================

def calculate_sun_chesta(sun_longitude):
    """
    Sun Chesta Bala using modified declination formula (ADITYA CIRCLE).

    Continuous sine curve: 29.7 + 28.7*sin(longitude - 1.6°), clamped [0, 60].
    The -1.6° phase shift aligns the peak with Cancer/Leo energy maximum.

    Aditya Circle context:
        - Maximum (~58): Sun in Varuna/Indra (73-100°) - Cancer/Leo energy
        - Minimum (~1.0): Sun in Bhaga (~265°) - Capricorn energy

    Args:
        sun_longitude: Sun's tropical longitude (0-360°)

    Returns:
        Chesta Bala value (0-60 Shashtiamsas)
    """
    chesta = 29.7 + 28.7 * math.sin(math.radians(sun_longitude - 1.6))
    return max(0.0, min(60.0, chesta))

def calculate_moon_chesta(moon_longitude, sun_longitude):
    """
    Moon Chesta Bala based on elongation from Sun.

    New Moon = 0, Full Moon = 60 (Paksha Bala).

    Args:
        moon_longitude: Moon's tropical longitude (0-360°)
        sun_longitude: Sun's tropical longitude (0-360°)

    Returns:
        Chesta Bala value (0-60)
    """
    elongation = abs(moon_longitude - sun_longitude)
    if elongation > 180:
        elongation = 360 - elongation
    return max(0.0, min(60.0, 60 * (elongation / 180)))

def calculate_mars_chesta(mars_longitude, sun_longitude):
    """
    Mars Chesta Bala = Piecewise cubic formula - OPTIMIZED (Dec 2025).

    Winner of 3-AI competition (GLM vs Gemini vs Claude).
    Maximum error: 0.82° across all 6 reference charts.

    Key insight: Elongation from Sun is the PRIMARY variable, NOT speed.
    Peak occurs at ~141° (retrograde zone), drops after opposition approach.

    Validation (6 reference charts, max error 0.8):
    - 14.2°: 7.4 vs 7.4,  62.7°: 27.2 vs 26.9,  72.6°: 31.1 vs 30.3
    - 97.5°: 37.9 vs 38.7,  141.2°: 56.5 vs 55.7,  170.3°: 50.7 vs 51.4

    Args:
        mars_longitude: Mars's tropical longitude (0-360°)
        sun_longitude: Sun's tropical longitude (0-360°)

    Returns:
        Chesta Bala value (0-60 Shashtiamsas)
    """
    elongation = abs(mars_longitude - sun_longitude)
    if elongation > 180:
        elongation = 360 - elongation

    elongation = max(0, min(180, elongation))

    # OPTIMIZED cubic coefficients
    a = 0.0000111400
    b = -0.00269500
    c = 0.554000

    if elongation <= 141:
        # Rising cubic
        chesta = a * elongation**3 + b * elongation**2 + c * elongation
    else:
        # Linear decline after peak (141-180°)
        peak = a * 141**3 + b * 141**2 + c * 141
        chesta = peak - 0.1500 * (elongation - 141)

    return max(0.0, min(60.0, chesta))

def calculate_mercury_chesta(mercury_longitude, sun_longitude, speed):
    """
    Mercury Chesta Bala = Speed-Adjusted Phase Model.

    Winner of Mercury competition: Gemini AI (0.28 avg error).
    Mercury as inferior planet requires BOTH elongation AND speed.

    Key insights:
        - Retrograde Mercury = Maximum Chesta
        - Direct Mercury peaks at ~21° with moderate speed (~1.0 deg/day)

    Args:
        mercury_longitude: Mercury's tropical longitude (0-360°)
        sun_longitude: Sun's tropical longitude (0-360°)
        speed: Mercury's daily motion (deg/day, negative = retrograde)

    Returns:
        Chesta Bala value (0-60)
    """
    elongation = abs(mercury_longitude - sun_longitude)
    if elongation > 180:
        elongation = 360 - elongation

    # RETROGRADE: Linear decay from maximum strength
    if speed < 0:
        chesta = 60.0 - (0.425 * elongation)
        return max(0.0, min(60.0, chesta))

    # DIRECT MOTION: Two-component model
    speed_bonus = 15.0 * (2.0 - speed)
    speed_bonus = max(0.0, speed_bonus)

    peak_elongation = 21.0
    if elongation <= peak_elongation:
        base_score = 0.003 * (elongation ** 3)
    else:
        peak_val = 0.003 * (peak_elongation ** 3)
        base_score = peak_val - 8.7 * (elongation - peak_elongation)
        base_score = max(0.0, base_score)

    return max(0.0, min(60.0, base_score + speed_bonus))

def calculate_jupiter_chesta(jupiter_longitude, sun_longitude, speed):
    """
    Jupiter Chesta Bala = Linear elongation with retrograde distinction.

    Jupiter is a superior planet - elongation from Sun is PRIMARY.
    Retrograde Jupiter uses a steeper formula with higher base strength.

    Formulas:
        Direct: chesta = 0.3133 * elongation + 2.7534
        Retrograde: chesta = 0.1107 * elongation + 34.3326

    Max error: 0.86° on 6 reference charts. All < 1° error.

    Args:
        jupiter_longitude: Jupiter's tropical longitude (0-360°)
        sun_longitude: Sun's tropical longitude (0-360°)
        speed: Jupiter's daily motion (negative = retrograde)

    Returns:
        Chesta Bala value (0-60 Shashtiamsas)
    """
    elongation = abs(jupiter_longitude - sun_longitude)
    if elongation > 180:
        elongation = 360 - elongation

    if speed < 0:  # Retrograde
        chesta = 0.1107 * elongation + 34.3326
    else:  # Direct
        chesta = 0.3133 * elongation + 2.7534

    return max(0.0, min(60.0, chesta))

# Venus Cheshta Bala lookup table: (synodic_angle°, cheshta_value)
# Derived from 17 reference charts (Feb 2026).
# Synodic angle = Venus_heliocentric - Earth_heliocentric (0-360°).
#   0° = inferior conjunction (retrograde, max strength ~60)
#   180° = superior conjunction (far side of Sun, min strength ~5)
# The curve is NON-MONOTONIC, reflecting the classical 8-state cycle:
#   Vakra(60) → Anuvakra(30) → Vikala(15) → Manda(15) →
#   Mandatara(30) → Sama(7.5) → Chara(45) → Atichara(30)
VENUS_CHESHTA_KNOTS = [
    (0.0, 60.0),
    (5.0, 56.0),
    (17.0, 47.0),
    (39.5, 21.3),
    (45.5, 36.6),
    (68.0, 30.0),
    (95.0, 22.0),
    (135.0, 12.0),
    (180.0, 5.0),
    (247.0, 18.0),
    (263.0, 22.5),
    (282.0, 27.6),
    (308.0, 35.3),
    (321.0, 39.5),
    (360.0, 60.0),
]

def _interpolate_venus_cheshta(synodic_deg):
    """Piecewise linear interpolation on Venus synodic angle lookup table."""
    synodic_deg = synodic_deg % 360.0
    for i in range(len(VENUS_CHESHTA_KNOTS) - 1):
        x0, y0 = VENUS_CHESHTA_KNOTS[i]
        x1, y1 = VENUS_CHESHTA_KNOTS[i + 1]
        if x0 <= synodic_deg <= x1:
            t = (synodic_deg - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return VENUS_CHESHTA_KNOTS[-1][1]

def calculate_venus_chesta(venus_longitude, sun_longitude, speed, julian_day=None):
    """
    Venus Chesta Bala — synodic lookup table (Feb 2026).

    PRIMARY method (when julian_day available):
      Computes the heliocentric synodic angle (Venus_helio - Earth_helio)
      and interpolates on a 15-knot empirical lookup table calibrated
      against 17 reference charts.
      Accuracy: avg error 0.15, max error 0.51 across all 17 charts.

    FALLBACK (no julian_day):
      Geocentric 3-branch formula (Jan 2026) using elongation and speed.
      Less accurate (~avg 3.5 error) but works without ephemeris access.

    Args:
        venus_longitude: Venus's tropical longitude (0-360°)
        sun_longitude: Sun's tropical longitude (0-360°)
        speed: Venus's daily motion (deg/day, negative = retrograde)
        julian_day: Optional Julian Day for synodic angle computation

    Returns:
        Chesta Bala value (0-60 Shashtiamsas)
    """
    # PRIMARY: Synodic lookup table (requires julian_day + Swiss Ephemeris)
    if julian_day is not None:
        synodic = _get_venus_synodic_angle(julian_day, sun_longitude)
        if synodic is not None:
            chesta = _interpolate_venus_cheshta(synodic)
            return max(0.0, min(60.0, chesta))

    # FALLBACK: Geocentric 3-branch formula
    diff = venus_longitude - sun_longitude
    if diff > 180:
        diff -= 360
    elif diff < -180:
        diff += 360

    elongation = abs(diff)

    if speed < 0:
        chesta = 60.0 - 0.44 * elongation
        return max(0.0, min(60.0, chesta))

    chesta = 0.5431 * elongation + 3.362

    return max(0.0, min(60.0, chesta))

def calculate_saturn_chesta(saturn_longitude, sun_longitude):
    """
    Saturn Chesta Bala - OPTIMIZED FORMULA (Dec 2025).

    Maximum error: 0.58° across all 6 reference charts.
    Formula: chesta = -0.000610 * elongation² + 0.445 * elongation - 3.0

    Validation (6 reference charts, max error 0.7):
    - 52.2°: 19.8 vs 19.5,  76.6°: 27.0 vs 27.5,  88.5°: 30.6 vs 30.9
    - 90.9°: 30.8 vs 31.5,  93.6°: 31.2 vs 31.7,  178.3°: 40.4 vs 40.3

    Args:
        saturn_longitude: Saturn's tropical longitude (0-360°)
        sun_longitude: Sun's tropical longitude (0-360°)

    Returns:
        Chesta Bala value (0-60 Shashtiamsas)
    """
    elongation = abs(saturn_longitude - sun_longitude)
    if elongation > 180:
        elongation = 360 - elongation

    # Optimized downward-opening parabola
    chesta = -0.000610 * elongation**2 + 0.445 * elongation - 3.0

    return max(0.0, min(60.0, chesta))

def calculate_chesta(planet_name, planet_long_or_pdata, sun_long=None, speed=None, julian_day=None):
    """
    Calculate Chesta Bala for any planet.

    Accepts either primitive values (preferred) or a legacy dict.

    Args:
        planet_name: One of Sun, Moon, Mars, Mercury, Jupiter, Venus, Saturn
        planet_long_or_pdata: Planet tropical longitude (float) or legacy dict
        sun_long: Sun tropical longitude (float); extracted from dict if dict passed
        speed: Planet daily speed (float); extracted from dict if dict passed
        julian_day: Optional Julian Day for Venus synodic angle

    Returns:
        Chesta Bala value (0-60)
    """
    if isinstance(planet_long_or_pdata, dict):
        # Legacy dict path — callers may pass julian_day as 3rd positional
        pdata = planet_long_or_pdata
        if julian_day is None and isinstance(sun_long, (int, float)) and sun_long > 1e6:
            julian_day = sun_long
        sun_long = pdata.get('Sun', {}).get('decimal_degrees', 0)
        planet_long = pdata.get(planet_name, {}).get('decimal_degrees', 0)
        speed = pdata.get(planet_name, {}).get('speed', 1.0)
        if julian_day is not None and HAS_SWISSEPH:
            speed = get_planet_speed(planet_name, julian_day)
    else:
        planet_long = planet_long_or_pdata
        if sun_long is None:
            sun_long = planet_long if planet_name == 'Sun' else 0.0
        if speed is None:
            speed = 1.0

    if planet_name == 'Sun':
        return calculate_sun_chesta(sun_long)

    if planet_name == 'Moon':
        return calculate_moon_chesta(planet_long, sun_long)
    elif planet_name == 'Mars':
        return calculate_mars_chesta(planet_long, sun_long)
    elif planet_name == 'Mercury':
        return calculate_mercury_chesta(planet_long, sun_long, speed)
    elif planet_name == 'Jupiter':
        return calculate_jupiter_chesta(planet_long, sun_long, speed)
    elif planet_name == 'Venus':
        return calculate_venus_chesta(planet_long, sun_long, speed, julian_day=julian_day)
    elif planet_name == 'Saturn':
        return calculate_saturn_chesta(planet_long, sun_long)
    else:
        return 30.0

# ============================================================
# DEC BALA (Combined Score)
# ============================================================

def calculate_dec_bala(digbala, uccha, chesta):
    """
    Calculate DEC Bala (Direction-Energy-Confidence combined score).

    Uses Geometric Mean: ∛(Digbala × Uccha × Chesta)

    Rationale:
        - Penalizes if ANY single bala is weak
        - A planet needs all 3 strengths to be truly effective
        - Range: 0-60 (same as individual balas)

    Args:
        digbala: Directional strength (0-60)
        uccha: Exaltation strength (0-60)
        chesta: Motion strength (0-60)

    Returns:
        DEC Bala value (0-60)
    """
    # Handle zero/negative values to avoid math errors
    d = max(0.001, digbala)
    u = max(0.001, uccha)
    c = max(0.001, chesta)

    # Geometric mean: cube root of product
    dec = (d * u * c) ** (1/3)

    return max(0.0, min(60.0, dec))

# ============================================================
# MAIN INTERFACE
# ============================================================

def get_all_bala_data(chart_or_data, aditya_mode=None, hsys="C"):
    """
    Calculate all 3 Balas + DEC Bala for all 7 classical planets.

    Accepts a libaditya Chart object (preferred) or a legacy dict.

    Args:
        chart_or_data: Either a libaditya Chart object (preferred) or a
                       legacy renderer-dict (must contain 'houses',
                       'julian_day', 'latitude', 'longitude').
        aditya_mode: "aditya" for Aditya system, "tropical_classic" for Tropical.
                     If None and a Chart is passed, derived from chart.context.circle.
                     If None and a dict is passed, defaults to "aditya".

    Returns:
        Dict with structure:
        {
            'Sun': {'digbala': 36.0, 'uccha': 11.3, 'chesta': 23.0, 'dec_bala': 21.5},
            'Moon': {...},
            ...
        }
    """
    # ---- Chart path (preferred) ----
    try:
        from libaditya.charts.chart import Chart
    except ImportError:
        Chart = None
    if Chart is not None and isinstance(chart_or_data, Chart):
        from libaditya.objects.context import Circle
        from libaditya import constants as _const
        chart = chart_or_data
        is_sidereal = chart.context.sysflg == _const.SID
        if is_sidereal:
            # SPEC-STR-001 §6.3: sidereal must use classic exaltation
            from core.chart_factory import rebuild_chart
            chart = rebuild_chart(chart, mode="tropical_classic")
            if chart.context.sysflg == _const.SID:
                raise ValueError("rebuild_chart failed to produce tropical chart")
            aditya_mode = "tropical_classic"
        elif aditya_mode is None:
            if chart.context.circle == Circle.ADITYA:
                aditya_mode = "aditya"
            else:
                aditya_mode = "tropical_classic"
        return _bala_from_chart(chart, aditya_mode)

    # ---- Legacy dict path ----
    if isinstance(chart_or_data, dict):
        import warnings
        warnings.warn(
            "Passing a dict to get_all_bala_data() is deprecated. Pass a Chart object.",
            DeprecationWarning, stacklevel=2,
        )
        if 'error' in chart_or_data:
            return {}
        return _bala_from_pdata(chart_or_data, aditya_mode or "aditya", hsys=hsys)

    return {}


def _bala_from_pdata(pdata, aditya_mode, hsys="C"):
    """Internal worker — runs the 7-planet bala loop on a renderer dict.

    Kept private so the public surface advertises the Chart API. This worker
    body must not reference the old dict name (Issue 14 grep gate).
    """
    houses = pdata.get('houses', {})
    julian_day = pdata.get('julian_day')
    latitude = pdata.get('latitude')
    longitude = pdata.get('longitude')

    # Pre-compute chart-level Swiss Ephemeris values ONCE before the planet loop.
    # ARMC (sidereal time) and obliquity of ecliptic depend only on jd/lat/lon,
    # not on the planet — so computing them inside calculate_digbala() for every
    # planet is wasted work. Hoisting them here drops swe.houses() + swe.calc_ut(ECL_NUT)
    # from 14 calls per chart load to 2.
    armc = None
    eps = None
    if julian_day is not None and latitude is not None and longitude is not None and HAS_SWISSEPH:
        try:
            _, ascmc = swe.houses(julian_day, latitude, longitude, hsys.encode())
            armc = ascmc[2]
            eps = swe.calc_ut(julian_day, swe.ECL_NUT)[0][0]
        except Exception:
            # On failure, leave armc/eps as None — calculate_digbala() will
            # recompute them itself (backward-compat fallback) or fall through
            # to the zodiacal distance method.
            armc = None
            eps = None

    result = {}

    for planet_name in ['Sun', 'Moon', 'Mars', 'Mercury', 'Jupiter', 'Venus', 'Saturn']:
        planet_data = pdata.get(planet_name, {})
        planet_long = planet_data.get('decimal_degrees', 0)

        # Calculate each bala
        # Pass Swiss Ephemeris parameters AND pre-computed armc/eps for accurate
        # and efficient Digbala calculation.
        digbala = calculate_digbala(planet_long, houses, planet_name,
                                    jd_ut=julian_day, lat=latitude, lon=longitude,
                                    armc=armc, eps=eps, hsys=hsys)
        uccha = calculate_uccha(planet_long, planet_name, aditya_mode)
        chesta = calculate_chesta(planet_name, pdata, julian_day=julian_day)

        # Calculate combined DEC Bala
        dec_bala = calculate_dec_bala(digbala, uccha, chesta)

        result[planet_name] = {
            'digbala': round(digbala, 1),
            'uccha': round(uccha, 1),
            'chesta': round(chesta, 1),
            'dec_bala': round(dec_bala, 1),
        }

    return result


def _bala_from_chart(chart, aditya_mode):
    """Internal worker — runs the 7-planet bala loop on a Chart object."""
    jd = chart.context.timeJD.jd
    lat = chart.context.location.lat
    lon = chart.context.location.long
    # SPEC-HSY-001 §6.1: Digbala follows the chart's own house system. The
    # Chart was built (Phase 2) with the user's setting, so context.hsys is the
    # authoritative SE code; thread it into swe.houses() and calculate_digbala().
    hsys = getattr(chart.context, 'hsys', None) or 'C'

    rashi = chart.rashi()
    all_planets = rashi.planets()

    armc = None
    eps = None
    if HAS_SWISSEPH:
        try:
            _, ascmc = swe.houses(jd, lat, lon, hsys.encode())
            armc = ascmc[2]
            eps = swe.calc_ut(jd, swe.ECL_NUT)[0][0]
        except Exception:
            armc = None
            eps = None

    try:
        sun_long = all_planets['Sun'].ecliptic_longitude()
    except (KeyError, TypeError):
        sun_long = 0.0

    result = {}

    for planet_name in ['Sun', 'Moon', 'Mars', 'Mercury', 'Jupiter', 'Venus', 'Saturn']:
        try:
            planet_long = all_planets[planet_name].ecliptic_longitude()
        except (KeyError, TypeError):
            continue

        if HAS_SWISSEPH:
            speed = get_planet_speed(planet_name, jd)
        else:
            try:
                speed = all_planets[planet_name].longitude_speed()
            except (KeyError, TypeError, AttributeError):
                speed = 1.0

        digbala = calculate_digbala(planet_long, {}, planet_name,
                                    jd_ut=jd, lat=lat, lon=lon,
                                    armc=armc, eps=eps, hsys=hsys)
        uccha = calculate_uccha(planet_long, planet_name, aditya_mode)
        chesta = calculate_chesta(planet_name, planet_long, sun_long, speed, julian_day=jd)
        dec_bala = calculate_dec_bala(digbala, uccha, chesta)

        result[planet_name] = {
            'digbala': round(digbala, 1),
            'uccha': round(uccha, 1),
            'chesta': round(chesta, 1),
            'dec_bala': round(dec_bala, 1),
        }

    return result
