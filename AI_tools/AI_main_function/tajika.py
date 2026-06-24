# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Tajika Aspects — Western-style orb-based aspects in the Indian tradition.
=========================================================================

Tajika is a preserved branch of Turkish/Arabic astrology in India, using
Western aspects (conjunction, sextile, square, trine, opposition) with
planet-specific orbs (Deeptamsas) and sign-based relationship rules.

Key Differences from Graha Sphuta Drishti:
- Only 5 aspect types (not continuous curves per planet)
- Planet-specific orbs determine "within orb" status
- Sextile 3rd house (40 VR) ≠ Sextile 11th house (10 VR)
- Includes outer planets (Uranus, Neptune, Pluto) + Ascendant
- No Rahu/Ketu

Reference: Ernst Wilhelm's Tajika aspect/orb tables (docs/tajika_prasna/).
"""

# ============================================================================
# CONSTANTS
# ============================================================================

# Planet-specific orbs (Deeptamsas) in degrees
# Traditional 7 planets: from Ernst Wilhelm's PDF tables
# Ascendant: 9° (validated against reference charts; not in PDF, 15° was too large)
# Outer planets: 8° each (validated against reference charts; no traditional values exist)
DEEPTAMSAS = {
    "Sun": 15, "Moon": 12, "Mars": 8, "Mercury": 7, "Jupiter": 9,
    "Venus": 7, "Saturn": 9, "Uranus": 8, "Neptune": 8, "Pluto": 8,
    "Ascendant": 9,
}

# Bodies included in Tajika analysis (11 total, standard set)
TAJIKA_PLANETS = [
    "Ascendant", "Sun", "Moon", "Mars", "Mercury",
    "Jupiter", "Venus", "Saturn", "Uranus", "Neptune", "Pluto",
]

# Short display names for the matrix
TAJIKA_SHORT_NAMES = {
    "Ascendant": "Lg", "Sun": "Su", "Moon": "Mo", "Mars": "Ma",
    "Mercury": "Me", "Jupiter": "Ju", "Venus": "Ve", "Saturn": "Sa",
    "Uranus": "Ur", "Neptune": "Ne", "Pluto": "Pl",
}

# Exact aspect angles and their peak virupas (from PDF interpolation table)
ASPECT_POINTS = {
    0: 60, 60: 40, 90: 15, 120: 45, 180: 60,
    240: 45, 270: 15, 300: 10,
}

# Aspect names by exact angle
ASPECT_NAMES = {
    0: ("Conjunction", "\u260c"),     # ☌
    60: ("Sextile", "\u2736"),        # ✶
    90: ("Square", "\u25a1"),         # □
    120: ("Trine", "\u25b3"),         # △
    180: ("Opposition", "\u260d"),    # ☍
}

# Minor aspect names (not part of standard Tajika 5, shown with --minor flag)
MINOR_ASPECT_NAMES = {
    30: ("Semi-sextile", "\u26ba"),    # ⚺
    150: ("Quincunx", "\u26bb"),       # ⚻
}

# All aspect angles grouped
MAIN_ASPECT_ANGLES = [0, 60, 90, 120, 180, 240, 270, 300]
MINOR_ASPECT_ANGLES = [30, 150, 210, 330]

# Sign-based relationships (houses apart → classification)
# houses_apart is 1-indexed: 1 = same sign, 2 = adjacent, etc.
RELATIONSHIP_MAP = {
    1:  ("Openly Inimical", "Open"),
    2:  ("Neutral", None),
    3:  ("Secretly Friendly", "Secret"),
    4:  ("Secretly Inimical", "Secret"),
    5:  ("Openly Friendly", "Open"),
    6:  ("Neutral", None),
    7:  ("Openly Inimical", "Open"),
    8:  ("Neutral", None),
    9:  ("Openly Friendly", "Open"),
    10: ("Secretly Inimical", "Secret"),
    11: ("Secretly Friendly", "Secret"),
    12: ("Neutral", None),
}

# Aspect associated with each house distance (for relationship display)
HOUSE_ASPECT_MAP = {
    1: ("\u260c", "Conjunction"),      # ☌
    3: ("\u2736", "Sextile"),          # ✶
    4: ("\u25a1", "Square"),           # □
    5: ("\u25b3", "Trine"),            # △
    7: ("\u260d", "Opposition"),       # ☍
    9: ("\u25b3", "Trine"),            # △
    10: ("\u25a1", "Square"),          # □
    11: ("\u2736", "Sextile"),         # ✶
}

# Planet speed order (fastest → slowest, for applying/separating logic)
PLANET_SPEEDS = [
    "Moon", "Mercury", "Venus", "Sun", "Mars",
    "Jupiter", "Saturn", "Uranus", "Neptune", "Pluto",
]


# Traditional 7 planets used in Tajika yoga analysis (no outer planets, no Ascendant)
TRADITIONAL_PLANETS = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]


# ============================================================================
# APPLYING / SEPARATING DETECTION
# ============================================================================

def determine_applying_separating(body1: str, body2: str,
                                   distance: float, exact_angle: float,
                                   speed1: float = None,
                                   speed2: float = None) -> str:
    """
    Determine if an aspect between two bodies is applying, separating, or exact.

    Two methods, in priority order:
    1. **Actual speeds** (handles retrograde correctly): When speed1 and speed2
       are provided, compute the rate of change of the angular distance and check
       if the deviation from exact is shrinking (applying) or growing (separating).
    2. **Static speed ordering** (fallback): Uses PLANET_SPEEDS list to guess
       which planet is faster and compares forward distance to exact angle.

    Args:
        body1: First body name.
        body2: Second body name.
        distance: Angular distance (pos2 - pos1) % 360, as stored in aspect record.
        exact_angle: The matched aspect angle (0, 60, 90, 120, 180, 240, 270, 300).
        speed1: Actual daily speed of body1 in deg/day (negative = retrograde).
        speed2: Actual daily speed of body2 in deg/day (negative = retrograde).

    Returns:
        "applying", "separating", "exact", or "unknown" (for Ascendant).
    """
    # Ascendant doesn't move — can't determine applying/separating
    if body1 == "Ascendant" or body2 == "Ascendant":
        return "unknown"

    # Deviation from exact aspect angle (normalized to ±180°)
    dev = distance - exact_angle
    if dev > 180:
        dev -= 360
    elif dev < -180:
        dev += 360

    if abs(dev) < 0.1:
        return "exact"

    # Method 1: Use actual speeds when available (retrograde-aware)
    if speed1 is not None and speed2 is not None:
        dd = speed2 - speed1
        if abs(dd) < 1e-6:
            return "exact"
        if dev * dd < 0:
            return "applying"
        else:
            return "separating"

    # Method 2: Fallback to static speed ordering (original logic)
    # Canonicalize reverse-arc angles (240→120, 270→90, 300→60)
    if exact_angle > 180:
        exact_angle = 360 - exact_angle

    idx1 = PLANET_SPEEDS.index(body1) if body1 in PLANET_SPEEDS else 99
    idx2 = PLANET_SPEEDS.index(body2) if body2 in PLANET_SPEEDS else 99

    if idx1 <= idx2:
        fwd_dist = distance
        if fwd_dist > 180:
            fwd_dist = 360 - fwd_dist
    else:
        fwd_dist = (360 - distance) % 360
        if fwd_dist > 180:
            fwd_dist = 360 - fwd_dist

    signed_diff = fwd_dist - exact_angle
    if signed_diff > 180:
        signed_diff -= 360
    elif signed_diff < -180:
        signed_diff += 360

    if signed_diff > 0:
        return "separating"
    else:
        return "applying"


# ============================================================================
# CORE CALCULATIONS
# ============================================================================

def calculate_tajika_strength(distance: float) -> float:
    """
    Calculate Tajika aspect strength using 12-segment piecewise linear interpolation.

    Each 30° segment linearly interpolates between endpoint values from the PDF table.
    Returns 0-60 virupas.

    Key asymmetry: Sextile at 60° = 40 VR, but Sextile at 300° = 10 VR.
    This reflects the 3rd house sextile being stronger than the 11th house sextile.

    Args:
        distance: Angular distance 0-360° between two bodies.

    Returns:
        Virupas (0.0 to 60.0).
    """
    d = distance % 360
    segment = int(d / 30)
    local_d = d - (segment * 30)  # 0-30 within segment

    # Endpoint values for each 30° segment: (start_vr, end_vr)
    segments = [
        (60, 0),    # 0-30°:   Conjunction peak → zero
        (0, 40),    # 30-60°:  zero → Sextile (3rd house)
        (40, 15),   # 60-90°:  Sextile → Square
        (15, 45),   # 90-120°: Square → Trine
        (45, 0),    # 120-150°: Trine → zero
        (0, 60),    # 150-180°: zero → Opposition
        (60, 0),    # 180-210°: Opposition → zero
        (0, 45),    # 210-240°: zero → Trine (9th house)
        (45, 15),   # 240-270°: Trine → Square (10th house)
        (15, 10),   # 270-300°: Square → Sextile (11th house)
        (10, 0),    # 300-330°: Sextile → zero
        (0, 60),    # 330-360°: zero → Conjunction
    ]

    start_vr, end_vr = segments[segment]
    return start_vr + (end_vr - start_vr) * (local_d / 30.0)


def classify_tajika_aspect(distance: float, include_minor: bool = False) -> tuple | None:
    """
    Classify a distance as a named Tajika aspect.

    Finds the nearest of the 5 exact aspect angles (0°, 60°, 90°, 120°, 180°).
    With include_minor=True, also checks semi-sextile (30°) and quincunx (150°).
    Returns None if the distance isn't close enough to any aspect angle.

    Args:
        distance: Angular distance 0-360°.
        include_minor: Also classify semi-sextile/quincunx.

    Returns:
        (aspect_name, symbol, exact_angle) or None.
    """
    d = distance % 360

    # Main aspects (forward and backward where applicable)
    checks = [
        (0, 0),     # Conjunction at 0° (also near 360°)
        (60, 60),   # Sextile (3rd house)
        (90, 90),   # Square (4th house)
        (120, 120), # Trine (5th house)
        (180, 180), # Opposition
        (240, 120), # Trine (9th house) — same aspect, other direction
        (270, 90),  # Square (10th house)
        (300, 60),  # Sextile (11th house)
    ]

    if include_minor:
        checks.extend([
            (30, 30),    # Semi-sextile (2nd house)
            (150, 150),  # Quincunx (6th house)
            (210, 150),  # Quincunx (8th house, reverse)
            (330, 30),   # Semi-sextile (12th house, reverse)
        ])

    best = None
    best_diff = 999

    for angle, base_angle in checks:
        diff = abs(d - angle)
        if diff > 180:
            diff = 360 - diff
        if diff < best_diff:
            best_diff = diff
            best = (angle, base_angle)

    if best is None or best_diff > 15:
        return None

    _, base_angle = best
    if base_angle in ASPECT_NAMES:
        name, symbol = ASPECT_NAMES[base_angle]
        return (name, symbol, best[0])
    if include_minor and base_angle in MINOR_ASPECT_NAMES:
        name, symbol = MINOR_ASPECT_NAMES[base_angle]
        return (name, symbol, best[0])

    return None


def effective_orb(planet1: str, planet2: str) -> float:
    """
    Calculate the effective orb (Deeptamsa) between two bodies.

    Tajika uses the average of both planets' orbs.

    Args:
        planet1: Name of first body (e.g. "Sun", "Ascendant").
        planet2: Name of second body.

    Returns:
        Effective orb in degrees.
    """
    orb1 = DEEPTAMSAS.get(planet1, 5)
    orb2 = DEEPTAMSAS.get(planet2, 5)
    return (orb1 + orb2) / 2.0


def is_within_orb(planet1: str, planet2: str, distance: float,
                  include_minor: bool = False) -> tuple:
    """
    Check if two bodies are within orb of any Tajika aspect.

    Args:
        planet1: First body name.
        planet2: Second body name.
        distance: Angular distance between them (0-360°).
        include_minor: Also check semi-sextile/quincunx angles.

    Returns:
        (within_orb: bool, aspect_name: str|None, distance_from_exact: float,
         is_minor: bool)
    """
    d = distance % 360

    aspect_angles = list(MAIN_ASPECT_ANGLES)
    if include_minor:
        aspect_angles.extend(MINOR_ASPECT_ANGLES)

    orb = effective_orb(planet1, planet2)

    best_aspect = None
    best_distance = 999

    for angle in aspect_angles:
        diff = abs(d - angle)
        if diff > 180:
            diff = 360 - diff
        if diff < best_distance:
            best_distance = diff
            best_aspect = angle

    if best_distance <= orb:
        # Map angles to base aspect names
        base_map = {0: 0, 60: 60, 90: 90, 120: 120, 180: 180,
                    240: 120, 270: 90, 300: 60,
                    30: 30, 150: 150, 210: 150, 330: 30}
        base = base_map.get(best_aspect, 0)

        if base in ASPECT_NAMES:
            name, _ = ASPECT_NAMES[base]
            return (True, name, best_distance, False)
        if include_minor and base in MINOR_ASPECT_NAMES:
            name, _ = MINOR_ASPECT_NAMES[base]
            return (True, name, best_distance, True)

    return (False, None, best_distance, False)


def get_sign_index_from_degrees(degrees: float) -> int:
    """
    Get 0-11 sign index from tropical degrees.

    0=Aries, 1=Taurus, ..., 11=Pisces.

    Args:
        degrees: Tropical longitude 0-360°.

    Returns:
        Sign index 0-11.
    """
    return int((degrees % 360) / 30)


def get_tajika_relationship(sign1_idx: int, sign2_idx: int) -> dict:
    """
    Determine the Tajika relationship between two bodies based on their signs.

    Counts signs apart (1-indexed: same sign = 1, adjacent = 2, etc.)
    and looks up the relationship classification.

    Args:
        sign1_idx: Sign index of first body (0-11).
        sign2_idx: Sign index of second body (0-11).

    Returns:
        {"houses_apart": int, "relationship": str, "open_secret": str|None}
    """
    houses_apart = ((sign2_idx - sign1_idx) % 12) + 1

    relationship, open_secret = RELATIONSHIP_MAP.get(
        houses_apart, ("Neutral", None)
    )

    return {
        "houses_apart": houses_apart,
        "relationship": relationship,
        "open_secret": open_secret,
    }


def calculate_all_tajika_aspects(chart,
                                 include_minor: bool = False) -> dict:
    """
    Calculate all Tajika aspects for a chart.

    Iterates all 11×11 pairs (upper triangle, since aspects are symmetric).
    Returns both a list of aspects within orb and a matrix for table display.

    Args:
        chart: libaditya Chart object.
        include_minor: Also detect semi-sextile (30°) and quincunx (150°).

    Returns:
        {
            "aspects_within_orb": [aspect records...],
            "matrix": {(body1, body2): record, ...},
            "speeds": {planet_name: float, ...}  (deg/day, negative=retrograde)
        }
    """
    # Extract positions
    from core.chart_helpers import get_planet_decimal_degrees, has_planet
    positions = {}
    for body in TAJIKA_PLANETS:
        if has_planet(chart, body):
            positions[body] = get_planet_decimal_degrees(chart, body)

    speeds = {}
    jd = chart.context.timeJD.jd
    if jd is not None:
        try:
            from libaditya import swe
            _SE_IDS = {"Sun": 0, "Moon": 1, "Mercury": 2, "Venus": 3, "Mars": 4,
                       "Jupiter": 5, "Saturn": 6, "Uranus": 7, "Neptune": 8, "Pluto": 9}
            for body, se_id in _SE_IDS.items():
                if body in positions:
                    try:
                        result = swe.calc_ut(jd, se_id)
                        speeds[body] = result[0][3]
                    except Exception:
                        pass
        except ImportError:
            pass

    aspects_within_orb = []
    matrix = {}

    # Upper triangle only (i < j)
    bodies = [b for b in TAJIKA_PLANETS if b in positions]

    for i, body1 in enumerate(bodies):
        for j in range(i + 1, len(bodies)):
            body2 = bodies[j]

            pos1 = positions[body1]
            pos2 = positions[body2]

            # Angular distance (body1 → body2, forward)
            distance = (pos2 - pos1) % 360

            # Tajika strength
            virupas = calculate_tajika_strength(distance)

            # Check if within orb of an aspect
            within, aspect_name, dist_from_exact, is_minor = is_within_orb(
                body1, body2, distance, include_minor=include_minor
            )

            # Sign-based relationship
            sign1 = get_sign_index_from_degrees(pos1)
            sign2 = get_sign_index_from_degrees(pos2)
            rel = get_tajika_relationship(sign1, sign2)

            # Get aspect symbol
            classified = classify_tajika_aspect(distance,
                                                include_minor=include_minor)
            symbol = classified[1] if classified else ""

            if within and aspect_name:
                orb_used = effective_orb(body1, body2)

                # Determine applying/separating status
                exact_angle_val = classified[2] if classified else 0
                app_status = determine_applying_separating(
                    body1, body2, distance, exact_angle_val,
                    speed1=speeds.get(body1), speed2=speeds.get(body2),
                )

                record = {
                    "body1": body1,
                    "body2": body2,
                    "distance": round(distance, 2),
                    "aspect": aspect_name,
                    "symbol": symbol,
                    "virupas": round(virupas, 1),
                    "strength_pct": round((virupas / 60) * 100, 1),
                    "orb_used": round(orb_used, 1),
                    "distance_from_exact": round(dist_from_exact, 1),
                    "relationship": rel["relationship"],
                    "open_secret": rel["open_secret"],
                    "houses_apart": rel["houses_apart"],
                    "is_minor": is_minor,
                    "applying_status": app_status,
                    "exact_angle": exact_angle_val,
                }

                aspects_within_orb.append(record)
                matrix[(body1, body2)] = record
                matrix[(body2, body1)] = record  # symmetric

    # Sort by virupas descending
    aspects_within_orb.sort(key=lambda x: -x["virupas"])

    return {
        "aspects_within_orb": aspects_within_orb,
        "matrix": matrix,
        "speeds": speeds,
    }


def calculate_transit_aspects(natal_chart, transit_chart,
                              include_minor: bool = False) -> dict:
    """
    Calculate Tajika aspects between transit planets and natal planets.

    Computes TWO directional views (different virupas due to asymmetric curve):
    - Transit-to-Natal: distance = (natal_pos - transit_pos) % 360
      "Transit Saturn aspects Natal Sun" — the standard/default view.
    - Natal-to-Transit: distance = (transit_pos - natal_pos) % 360
      "Natal Sun aspects Transit Saturn" — the reverse view.

    Same pairs are within orb for both directions, but virupas differ because
    the 3rd-house sextile (60°, 40 VR) ≠ 11th-house sextile (300°, 10 VR).

    Args:
        natal_chart: libaditya Chart object for the natal chart.
        transit_chart: libaditya Chart object for the transit chart.
        include_minor: Also detect semi-sextile/quincunx.

    Returns:
        {
            "transit_to_natal": [records sorted by strength...],
            "natal_to_transit": [records sorted by strength...],
            "matrix": {(t_body, n_body): transit_to_natal record, ...},
            "speeds": {planet: float, ...},
            "is_transit": True,
        }
    """
    # Extract positions from both charts
    from core.chart_helpers import get_planet_decimal_degrees, has_planet
    natal_positions = {}
    for body in TAJIKA_PLANETS:
        if has_planet(natal_chart, body):
            natal_positions[body] = get_planet_decimal_degrees(natal_chart, body)

    transit_positions = {}
    for body in TAJIKA_PLANETS:
        if has_planet(transit_chart, body):
            transit_positions[body] = get_planet_decimal_degrees(transit_chart, body)

    transit_speeds = {}
    jd = transit_chart.context.timeJD.jd
    if jd is not None:
        try:
            from libaditya import swe
            _SE_IDS = {"Sun": 0, "Moon": 1, "Mercury": 2, "Venus": 3, "Mars": 4,
                       "Jupiter": 5, "Saturn": 6, "Uranus": 7, "Neptune": 8, "Pluto": 9}
            for body, se_id in _SE_IDS.items():
                if body in transit_positions:
                    result = swe.calc_ut(jd, se_id)
                    transit_speeds[body] = result[0][3]
        except (ImportError, Exception):
            pass

    transit_to_natal = []
    natal_to_transit = []
    matrix = {}

    # Transit Ascendant is a calculated point, not a planet — it doesn't aspect.
    # Natal Ascendant CAN receive aspects from transit planets.
    transit_bodies = [b for b in TAJIKA_PLANETS
                      if b in transit_positions and b != "Ascendant"]
    natal_bodies = [b for b in TAJIKA_PLANETS if b in natal_positions]

    for t_body in transit_bodies:
        for n_body in natal_bodies:
            t_pos = transit_positions[t_body]
            n_pos = natal_positions[n_body]

            # ── Direction 1: Transit to Natal ──
            dist_fwd = (n_pos - t_pos) % 360
            vr_fwd = calculate_tajika_strength(dist_fwd)

            within, aspect_name, dist_from_exact, is_minor = is_within_orb(
                t_body, n_body, dist_fwd, include_minor=include_minor
            )

            if not (within and aspect_name):
                continue

            orb_used = effective_orb(t_body, n_body)

            # Sign relationships for both directions
            sign_t = get_sign_index_from_degrees(t_pos)
            sign_n = get_sign_index_from_degrees(n_pos)
            rel_fwd = get_tajika_relationship(sign_t, sign_n)
            rel_rev = get_tajika_relationship(sign_n, sign_t)

            # Aspect classification for both directions
            cls_fwd = classify_tajika_aspect(dist_fwd, include_minor=include_minor)
            symbol_fwd = cls_fwd[1] if cls_fwd else ""
            exact_fwd = cls_fwd[2] if cls_fwd else 0

            dist_rev = (t_pos - n_pos) % 360
            vr_rev = calculate_tajika_strength(dist_rev)
            cls_rev = classify_tajika_aspect(dist_rev, include_minor=include_minor)
            symbol_rev = cls_rev[1] if cls_rev else ""
            exact_rev = cls_rev[2] if cls_rev else 0

            # Applying/separating (transit speed vs 0, natal frozen)
            app_status = determine_applying_separating(
                t_body, n_body, dist_fwd, exact_fwd,
                speed1=transit_speeds.get(t_body),
                speed2=0.0,
            )

            # Transit-to-Natal record
            rec_fwd = {
                "transit_body": t_body,
                "natal_body": n_body,
                "distance": round(dist_fwd, 2),
                "aspect": aspect_name,
                "symbol": symbol_fwd,
                "virupas": round(vr_fwd, 1),
                "strength_pct": round((vr_fwd / 60) * 100, 1),
                "orb_used": round(orb_used, 1),
                "distance_from_exact": round(dist_from_exact, 1),
                "relationship": rel_fwd["relationship"],
                "open_secret": rel_fwd["open_secret"],
                "houses_apart": rel_fwd["houses_apart"],
                "is_minor": is_minor,
                "applying_status": app_status,
                "exact_angle": exact_fwd,
            }

            # Natal-to-Transit record (same pair, reverse direction)
            _, rev_aspect_name, rev_dist_exact, rev_is_minor = is_within_orb(
                n_body, t_body, dist_rev, include_minor=include_minor
            )
            app_status_rev = determine_applying_separating(
                n_body, t_body, dist_rev, exact_rev,
                speed1=0.0,
                speed2=transit_speeds.get(t_body),
            )
            rec_rev = {
                "transit_body": t_body,
                "natal_body": n_body,
                "distance": round(dist_rev, 2),
                "aspect": rev_aspect_name or aspect_name,
                "symbol": symbol_rev,
                "virupas": round(vr_rev, 1),
                "strength_pct": round((vr_rev / 60) * 100, 1),
                "orb_used": round(orb_used, 1),
                "distance_from_exact": round(rev_dist_exact, 1),
                "relationship": rel_rev["relationship"],
                "open_secret": rel_rev["open_secret"],
                "houses_apart": rel_rev["houses_apart"],
                "is_minor": rev_is_minor,
                "applying_status": app_status_rev,
                "exact_angle": exact_rev,
            }

            transit_to_natal.append(rec_fwd)
            natal_to_transit.append(rec_rev)
            matrix[(t_body, n_body)] = rec_fwd

    # Sort both lists by virupas descending
    transit_to_natal.sort(key=lambda x: -x["virupas"])
    natal_to_transit.sort(key=lambda x: -x["virupas"])

    return {
        "transit_to_natal": transit_to_natal,
        "natal_to_transit": natal_to_transit,
        # Keep "aspects_within_orb" as alias for transit_to_natal (backward compat)
        "aspects_within_orb": transit_to_natal,
        "matrix": matrix,
        "speeds": transit_speeds,
        "is_transit": True,
    }
