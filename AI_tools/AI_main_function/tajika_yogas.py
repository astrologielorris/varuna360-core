# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Tajika Yoga Detection — All 16 Tajika Yogas
=============================================

Tajika yogas are event-prediction formulas built on top of the Tajika aspect
system. While aspects tell you which planets are interacting, yogas tell you
the *outcome* of that interaction: success, failure, disruption, void, or
transfer through a mediator.

The 16 yogas are grouped by outcome:
  SUCCESS:    Ikkavala, Ithasala, Kambula, Kutha, Tambeera, Dutthothadi
  FAILURE:    Induvara, Isharapha
  DISRUPTION: Manahoo, Durapha
  VOID:       Suunya Marga, Khallasara
  TRANSFER:   Nakta, Yamaya
  SPECIAL:    Gairi Kabula

Reference: Ernst Wilhelm's Tajika aspect/orb tables.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from AI_tools.AI_main_function.tajika import (
    PLANET_SPEEDS,
    DEEPTAMSAS,
    TRADITIONAL_PLANETS,
    TAJIKA_PLANETS,
    TAJIKA_SHORT_NAMES,
    calculate_tajika_strength,
    MAIN_ASPECT_ANGLES,
)
# NOTE: determine_applying_separating / is_within_orb / effective_orb /
# classify_tajika_aspect were used by the old speed/exact-angle Itthasala rule.
# The deg-in-sign rule (classify_pair, below) replaces them entirely.
from AI_tools.AI_main_function.constants import (
    ADITYA_SIGNS,
    SIGN_RULERS,
    DUSTHANA_HOUSES,
    check_planet_dignity,
)
from AI_tools.AI_main_function.houses import get_planets_by_house
from core.chart_helpers import (
    get_planet_sign_name, get_planet_in_sign_longitude,
    get_planet_decimal_degrees, has_planet,
)

try:
    from core.bala_calculator import (
        get_planet_speed,
        EXALTATION_DEGREES_ADITYA,
        get_all_bala_data,
    )
    HAS_BALA = True
except ImportError:
    HAS_BALA = False
    EXALTATION_DEGREES_ADITYA = {}

    def get_planet_speed(planet_name, julian_day):
        return 1.0

    def get_all_bala_data(chart, **kwargs):
        return {}


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _short(planet: str) -> str:
    """Short name for display."""
    return TAJIKA_SHORT_NAMES.get(planet, planet[:2])


def _is_faster(p1: str, p2: str, speeds: dict = None) -> bool:
    """True if p1 is faster than p2. Uses actual speeds if available."""
    if speeds and p1 in speeds and p2 in speeds:
        return abs(speeds[p1]) > abs(speeds[p2])
    idx1 = PLANET_SPEEDS.index(p1) if p1 in PLANET_SPEEDS else 99
    idx2 = PLANET_SPEEDS.index(p2) if p2 in PLANET_SPEEDS else 99
    return idx1 < idx2


def _get_speed_index(planet: str) -> int:
    """Speed index (lower = faster). Returns 99 for unknown planets."""
    return PLANET_SPEEDS.index(planet) if planet in PLANET_SPEEDS else 99


def _get_jd(chart_or_data):
    """Extract julian day from Chart."""
    return chart_or_data.context.timeJD.jd


def _is_combust(planet: str, chart) -> bool:
    """Planet within combustion range of the Sun (6° for planets, 12° for Moon)."""
    if planet == "Sun":
        return False
    sun_pos = get_planet_decimal_degrees(chart, "Sun", default=None)
    planet_pos = get_planet_decimal_degrees(chart, planet, default=None)
    if sun_pos is None or planet_pos is None:
        return False
    dist = abs(planet_pos - sun_pos)
    if dist > 180:
        dist = 360 - dist
    threshold = 12.0 if planet == "Moon" else 6.0
    return dist < threshold


def _is_retrograde(planet: str, chart) -> bool:
    """Planet retrograde in the chart. Sun/Moon never retrograde.

    Positional / state-based (spec section 3 item 2): read the chart planet
    object's OWN stored speed via `retrograde()`. This is robust and does not
    depend on the optional `bala_calculator` module or a valid `jd` - the yoga
    `failing` flag must fire for retrograde participants regardless (the old
    bala-speed path silently returned False whenever HAS_BALA was unavailable,
    dropping every failing flag; codex P1). The bala path stays only as a legacy
    fallback for dict charts without the object API.
    """
    if planet in ("Sun", "Moon"):
        return False
    try:
        return bool(chart.rashi().planets()[planet].retrograde())
    except Exception:
        pass
    jd = _get_jd(chart)
    if jd is None or not HAS_BALA:
        return False
    try:
        return get_planet_speed(planet, jd) < 0
    except Exception:
        return False


def _is_debilitated(planet: str, chart) -> bool:
    """Planet within 10° of its debilitation degree (180° from exaltation)."""
    if planet not in EXALTATION_DEGREES_ADITYA:
        return False
    planet_pos = get_planet_decimal_degrees(chart, planet, default=None)
    if planet_pos is None:
        return False
    debil_deg = (EXALTATION_DEGREES_ADITYA[planet] + 180) % 360
    dist = abs(planet_pos - debil_deg)
    if dist > 180:
        dist = 360 - dist
    return dist < 10


def _is_dignified(planet: str, chart) -> bool:
    """Planet in exaltation, mulatrikona, or own sign.

    Issue 12: accepts Chart or dict via chart_helpers.
    """
    sign_name = get_planet_sign_name(chart, planet, default="")
    deg_in_sign = get_planet_in_sign_longitude(chart, planet)
    dignity = check_planet_dignity(planet, sign_name, deg_in_sign)
    return dignity in ("exaltation", "mulatrikona", "own_sign")


def _is_weak(planet: str, chart, house_data: dict = None,
             bala_data: dict = None) -> bool:
    """
    Planet is weak: combust OR debilitated OR in dusthana house
    OR very low Uccha Bala (< 10).

    Note: Retrograde is NOT weakness — retrograde planets are considered
    stronger (closer to Earth, brighter, more prominent).
    """
    if _is_combust(planet, chart):
        return True
    if _is_debilitated(planet, chart):
        return True
    # Check dusthana house placement
    if house_data:
        planet_house = _get_house_number(planet, house_data)
        if planet_house in DUSTHANA_HOUSES:
            return True
    # Check Uccha Bala if available (use pre-computed bala_data if provided)
    if bala_data is None and HAS_BALA:
        try:
            bala_data = get_all_bala_data(chart)
        except Exception:
            pass
    if bala_data and planet in bala_data:
        uccha = bala_data[planet].get("uccha", 30)
        if uccha < 10:
            return True
    return False


def _in_last_degree(planet: str, chart) -> bool:
    """Planet in the last degree of its sign (29°-30°)."""
    planet_pos = get_planet_decimal_degrees(chart, planet, default=None)
    if planet_pos is None:
        return False
    deg_in_sign = planet_pos % 30
    return deg_in_sign >= 29.0


def _get_house_number(planet: str, house_data: dict) -> int:
    """Get whole-sign house number (1-12) for a planet. Returns 0 if unknown."""
    if house_data is None:
        return 0
    houses = house_data.get("houses", {})
    for house_num, info in houses.items():
        for p_name, _ in info.get("planets", []):
            if p_name == planet:
                return house_num
    return 0


def _get_lagna_lord(chart) -> str:
    """Get the ruler of the ascendant sign (accepts Chart or dict, Issue 12)."""
    asc_sign = get_planet_sign_name(chart, "Ascendant", default="")
    return SIGN_RULERS.get(asc_sign, "")


def _get_position(planet: str, chart) -> float:
    """Get decimal degrees of a planet. Returns -1 if unknown."""
    val = get_planet_decimal_degrees(chart, planet, default=None)
    return val if val is not None else -1


def _get_sign_index(planet: str, chart) -> int:
    """Get 0-11 sign index via Chart API."""
    obj = chart.rashi().planets()[planet]
    return (obj.sign() - 1) % 12


def _next_sign_index(sign_idx: int) -> int:
    """Next sign (wrapping 11 -> 0)."""
    return (sign_idx + 1) % 12


# ============================================================================
# APPLYING/SEPARATING RULE (SPEC-VRS-001 section 3)
# ============================================================================
#
# The original engine classified Itthasala/Isharapha from real ephemeris speeds
# and the distance to the exact aspect angle. That was a mis-extraction: the
# rule (per Ernst Wilhelm's Tajika/Varshaphala teaching) compares the
# DEGREES-WITHIN-SIGN of the faster vs slower planet. A faster planet with fewer
# degrees-in-sign than a slower one is APPLYING (Itthasala); more (by >= 1 deg)
# is SEPARATING (Isharapha). "Faster" is the fixed speed order below, NOT
# ephemeris velocity (retrograde planets keep their natural order and instead
# get a `failing` flag). classify_pair is the single source of truth.

# Fastest -> slowest. Static order. Never ephemeris speed.
TAJIKA_SPEED_ORDER = ["Moon", "Mercury", "Venus", "Sun", "Mars", "Jupiter", "Saturn"]

# Sign offsets (0-based, slow minus fast) that count as an aspecting position:
# 1st/3rd/4th/5th/7th/9th/10th/11th. The remaining offsets are 2/12 (1, 11) and
# 6/8 (5, 7) - non-aspecting. A pair in a non-aspecting position still FORMS the
# yoga mechanically (its sign-aspect virupa is 0), it is only flagged
# non-critical and is Nakta/Yamaya territory (spec section 3 item 1).
ASPECTING_SIGN_OFFSETS = frozenset({0, 2, 3, 4, 6, 8, 9, 10})


def _tajika_faster(p1: str, p2: str) -> tuple:
    """(faster, slower) by the static speed order."""
    return (p1, p2) if (TAJIKA_SPEED_ORDER.index(p1)
                        < TAJIKA_SPEED_ORDER.index(p2)) else (p2, p1)


def classify_pair(p1: str, sign1: int, deg1: float,
                  p2: str, sign2: int, deg2: float):
    """Classify the Tajika applying/separating relationship of two planets.

    Pure function of sign index (0-11) and degrees-within-sign (0-30). Faster /
    slower is resolved internally from TAJIKA_SPEED_ORDER, so argument order does
    not matter. Frame-agnostic: both the sign OFFSET and the degrees-in-sign are
    invariant across zodiac frames (spec section 2).

    Returns None only when the pair is beyond combined orb (no yoga). Otherwise:
        {"yoga": "Itthasala"|"Isharapha",
         "subtype": "Purna"|"Vartamana"|"Bhavishyata",
         "family": "applying"|"separating",
         "fast": str, "slow": str,
         "dist": float,          # deg-in-sign distance, or catching distance
         "critical": bool,       # aspecting sign position (sign virupa > 0)
         "sign_virupas": float,  # tajika strength at offset*30 (0 = non-critical)
         "cross_sign": bool}     # the last-degree next-sign exception fired
    """
    fast, slow = _tajika_faster(p1, p2)
    if fast == p1:
        sf, df, ss, ds = sign1, deg1, sign2, deg2
    else:
        sf, df, ss, ds = sign2, deg2, sign1, deg1

    offset = (ss - sf) % 12
    sign_virupas = calculate_tajika_strength(offset * 30.0)
    critical = offset in ASPECTING_SIGN_OFFSETS
    avg_orb = (DEEPTAMSAS[fast] + DEEPTAMSAS[slow]) / 2.0
    combined_orb = DEEPTAMSAS[fast] + DEEPTAMSAS[slow]

    def _rec(yoga, subtype, family, dist, cross_sign=False, crit=None):
        return {
            "yoga": yoga, "subtype": subtype, "family": family,
            "fast": fast, "slow": slow, "dist": round(dist, 4),
            "critical": critical if crit is None else crit,
            "sign_virupas": sign_virupas, "cross_sign": cross_sign,
        }

    # Last-degree cross-sign Itthasala (yogas 10 & 14): a fast
    # planet in the last degree of its sign forms Itthasala with a planet in the
    # NEXT sign, distance measured as the actual catching distance across the
    # boundary. This overrides both the plain deg-in-sign arithmetic (which would
    # read it as separating) and the sign gate (offset 1 is otherwise 2/12); the
    # aspect completes as a conjunction once the fast planet ingresses, so it is
    # treated as critical.
    if df >= 29.0 and offset == 1:
        dist = (30.0 - df) + ds
        if dist <= 1.0:
            return _rec("Itthasala", "Purna", "applying", dist, True, crit=True)
        if dist <= avg_orb:
            return _rec("Itthasala", "Vartamana", "applying", dist, True, crit=True)
        if dist <= combined_orb:
            return _rec("Itthasala", "Bhavishyata", "applying", dist, True, crit=True)
        return None

    # Normal deg-in-sign rule (classify_pair pseudocode).
    if df <= ds or (df - ds) < 1.0:                 # applying, or up to <1 deg past
        dist = abs(ds - df)
        if dist <= 1.0:
            return _rec("Itthasala", "Purna", "applying", dist)
        # df > ds with dist > 1 cannot reach here: it fails the outer test and
        # falls through to the separating branch (the guide's inner Isharapha
        # arm is dead code - confirmed by adversarial review).
        if dist <= avg_orb:
            return _rec("Itthasala", "Vartamana", "applying", dist)
        if dist <= combined_orb:
            return _rec("Itthasala", "Bhavishyata", "applying", dist)
        return None

    # Separating by >= 1 deg -> Isharapha (event rooted in the past).
    dist = df - ds
    if dist <= avg_orb:
        return _rec("Isharapha", "Vartamana", "separating", dist)
    if dist <= combined_orb:
        return _rec("Isharapha", "Bhavishyata", "separating", dist)
    return None


def _pair_positions(chart) -> dict:
    """{planet: (sign_index, deg_in_sign)} for the 7 traditional planets present."""
    pos = {}
    for p in TRADITIONAL_PLANETS:
        if has_planet(chart, p):
            pos[p] = (_get_sign_index(p, chart),
                      get_planet_in_sign_longitude(chart, p))
    return pos


def _classify_chart_pair(p1: str, p2: str, positions: dict):
    """classify_pair for two planets given a precomputed positions map."""
    if p1 not in positions or p2 not in positions:
        return None
    s1, d1 = positions[p1]
    s2, d2 = positions[p2]
    return classify_pair(p1, s1, d1, p2, s2, d2)


def _in_itthasala(p1: str, p2: str, positions: dict) -> bool:
    """True if the two planets form an Itthasala (applying) by the deg-in-sign rule.
    Single source of truth for dependent detectors (Kambula, Dutthothadi)."""
    r = _classify_chart_pair(p1, p2, positions)
    return r is not None and r["yoga"] == "Itthasala"


# Effect text keyed by Itthasala subtype.
_ITHASALA_EFFECT = {
    "Purna": "Event happening now. Most powerful Itthasala.",
    "Vartamana": "Event manifesting now. Strong current Itthasala.",
    "Bhavishyata": "Future event. Matures as the two planets close in.",
}
_ISHARAPHA_EFFECT = {
    "Vartamana": "Recent-past event: continuation, closure, or resolution.",
    "Bhavishyata": "Distant-past event: matures in the later of the two dasas.",
}


def _pair_yoga_record(chart, r: dict) -> dict:
    """Build a yoga record from a classify_pair result, adding the retrograde
    `failing` flag (positional detection: retrograde participants still FORM the
    yoga but it "looks like it will happen and does not")."""
    fast, slow = r["fast"], r["slow"]
    failing = _is_retrograde(fast, chart) or _is_retrograde(slow, chart)
    if r["yoga"] == "Itthasala":
        name, category, verb = "Ithasala", "SUCCESS", "applying to"
        effect = _ITHASALA_EFFECT.get(r["subtype"], "")
    else:
        name, category, verb = "Isharapha", "FAILURE", "separating from"
        effect = _ISHARAPHA_EFFECT.get(r["subtype"], "")
    crit = "" if r["critical"] else " [non-critical: 2/12 or 6/8]"
    cross = " (last degree, next sign)" if r["cross_sign"] else ""
    fail = " [FAILING: retrograde participant]" if failing else ""
    if failing:
        effect += " Retrograde participant: the yoga forms but tends to fall apart."
    desc = (f"{fast} {verb} {slow}{cross} - {r['subtype']}, "
            f"dist {r['dist']:.2f} deg-in-sign, "
            f"sign aspect {r['sign_virupas']:.0f} VR{crit}{fail}")
    return _yoga(
        name, category, [fast, slow], desc, effect,
        subtype=r["subtype"],
        dist_in_sign=r["dist"],
        critical=r["critical"],
        cross_sign=r["cross_sign"],
        failing=failing,
        sign_virupas=r["sign_virupas"],
        family=r["family"],
    )


# ============================================================================
# YOGA RECORD BUILDER
# ============================================================================

def _yoga(name: str, category: str, planets: list, description: str,
          effect: str, subtype: str = None, **extra) -> dict:
    """Build a standardized yoga record."""
    record = {
        "yoga_name": name,
        "category": category,
        "planets": planets,
        "planets_short": " ".join(_short(p) for p in planets),
        "description": description,
        "effect": effect,
    }
    if subtype:
        record["subtype"] = subtype
    record.update(extra)
    return record


# ============================================================================
# YOGA DETECTORS
# ============================================================================

# --- HOUSE-BASED YOGAS ---

ANGLE_PANAPHARA_HOUSES = {1, 2, 4, 5, 7, 8, 10, 11}
APOKLIMA_HOUSES = {3, 6, 9, 12}


def _detect_ikkavala(chart, house_data: dict, **kw) -> list:
    """
    Ikkavala: ALL 7 traditional planets in angles or panapharas (houses 1,2,4,5,7,8,10,11).
    None may be in apoklima houses (3,6,9,12).
    """
    yogas = []
    all_in = True
    planets_found = []
    for planet in TRADITIONAL_PLANETS:
        h = _get_house_number(planet, house_data)
        if h == 0:
            all_in = False
            break
        if h not in ANGLE_PANAPHARA_HOUSES:
            all_in = False
            break
        planets_found.append(planet)

    if all_in and len(planets_found) == 7:
        yogas.append(_yoga(
            "Ikkavala", "SUCCESS", planets_found,
            "All 7 planets in angles/panapharas (houses 1,2,4,5,7,8,10,11)",
            "Complete success. All planets positioned for manifestation.",
        ))
    return yogas


def _detect_induvara(chart, house_data: dict, **kw) -> list:
    """
    Induvara: ALL 7 traditional planets in apoklima houses (3,6,9,12) only.
    """
    yogas = []
    all_in = True
    planets_found = []
    for planet in TRADITIONAL_PLANETS:
        h = _get_house_number(planet, house_data)
        if h == 0:
            all_in = False
            break
        if h not in APOKLIMA_HOUSES:
            all_in = False
            break
        planets_found.append(planet)

    if all_in and len(planets_found) == 7:
        yogas.append(_yoga(
            "Induvara", "FAILURE", planets_found,
            "All 7 planets in apoklima houses (3,6,9,12)",
            "Complete failure. No planet in a position of strength.",
        ))
    return yogas


# --- ASPECT-BASED YOGAS ---

def _detect_ithasala(chart, tajika_data: dict = None, positions: dict = None,
                     **kw) -> list:
    """Itthasala (applying): faster planet has fewer degrees-in-sign than the
    slower. Subtypes Purna (<=1 deg) / Vartamana (<= average
    orb) / Bhavishyata (<= combined orb). Non-critical (2/12, 6/8) pairs still
    form; retrograde participants are flagged `failing`, not dropped.

    NOTE: the yoga name is kept as "Ithasala" (one t) for downstream / UI
    compatibility; the rule and spec spell it "Itthasala".
    """
    if positions is None:
        positions = _pair_positions(chart)
    present = [p for p in TRADITIONAL_PLANETS if p in positions]
    yogas = []
    for i, a in enumerate(present):
        for b in present[i + 1:]:
            r = _classify_chart_pair(a, b, positions)
            if r is not None and r["yoga"] == "Itthasala":
                yogas.append(_pair_yoga_record(chart, r))
    return yogas


def _detect_isharapha(chart, tajika_data: dict = None, positions: dict = None,
                      **kw) -> list:
    """Isharapha (separating): faster planet is >= 1 deg past the slower in
    degrees-in-sign. In Varshaphala this is an event rooted
    in the past (continuation/closure), not a plain failure. Vartamana = recent
    past (<= average orb); Bhavishyata = distant past (<= combined orb)."""
    if positions is None:
        positions = _pair_positions(chart)
    present = [p for p in TRADITIONAL_PLANETS if p in positions]
    yogas = []
    for i, a in enumerate(present):
        for b in present[i + 1:]:
            r = _classify_chart_pair(a, b, positions)
            if r is not None and r["yoga"] == "Isharapha":
                yogas.append(_pair_yoga_record(chart, r))
    return yogas


# --- MEDIATION YOGAS ---

def _detect_nakta(chart, tajika_data: dict, **kw) -> list:
    """
    Nakta: Two planets NOT in aspect + a FASTER 3rd planet aspects both
    and is positioned between them in degrees. The 3rd planet mediates.
    """
    yogas = []
    matrix = tajika_data.get("matrix", {})
    positions = {}
    for p in TRADITIONAL_PLANETS:
        if has_planet(chart, p):
            positions[p] = get_planet_decimal_degrees(chart, p)

    trad_with_pos = [p for p in TRADITIONAL_PLANETS if p in positions]

    for i, p1 in enumerate(trad_with_pos):
        for j in range(i + 1, len(trad_with_pos)):
            p2 = trad_with_pos[j]
            # p1 and p2 must NOT be in aspect
            if (p1, p2) in matrix:
                continue

            # Find a 3rd planet that aspects both
            for mediator in trad_with_pos:
                if mediator in (p1, p2):
                    continue
                if (mediator, p1) not in matrix or (mediator, p2) not in matrix:
                    continue

                # Mediator must be FASTER than both
                spds = tajika_data.get("speeds", {})
                if not (_is_faster(mediator, p1, spds) and _is_faster(mediator, p2, spds)):
                    continue

                # Mediator should be between p1 and p2 on the shorter arc
                pos1, pos2, pos_m = positions[p1], positions[p2], positions[mediator]
                d12 = abs(pos2 - pos1)
                if d12 > 180:
                    d12 = 360 - d12
                d1m = abs(pos_m - pos1)
                if d1m > 180:
                    d1m = 360 - d1m
                d2m = abs(pos_m - pos2)
                if d2m > 180:
                    d2m = 360 - d2m
                between = abs(d1m + d2m - d12) < 0.01

                if not between:
                    continue

                yogas.append(_yoga(
                    "Nakta", "TRANSFER", [p1, mediator, p2],
                    f"{_short(mediator)} (faster) mediates between "
                    f"{_short(p1)} and {_short(p2)}",
                    "Transfer of light. Event succeeds through a swift intermediary.",
                ))
    return yogas


def _detect_yamaya(chart, tajika_data: dict, **kw) -> list:
    """
    Yamaya: Two planets NOT in aspect + a SLOWER 3rd planet aspects both.
    Like Nakta but with a slow mediator — event comes through patience.
    """
    yogas = []
    matrix = tajika_data.get("matrix", {})
    positions = {}
    for p in TRADITIONAL_PLANETS:
        if has_planet(chart, p):
            positions[p] = get_planet_decimal_degrees(chart, p)

    trad_with_pos = [p for p in TRADITIONAL_PLANETS if p in positions]

    for i, p1 in enumerate(trad_with_pos):
        for j in range(i + 1, len(trad_with_pos)):
            p2 = trad_with_pos[j]
            if (p1, p2) in matrix:
                continue

            for mediator in trad_with_pos:
                if mediator in (p1, p2):
                    continue
                if (mediator, p1) not in matrix or (mediator, p2) not in matrix:
                    continue

                # Mediator must be SLOWER than both
                if not (_get_speed_index(mediator) > _get_speed_index(p1) and
                        _get_speed_index(mediator) > _get_speed_index(p2)):
                    continue

                yogas.append(_yoga(
                    "Yamaya", "TRANSFER", [p1, mediator, p2],
                    f"{_short(mediator)} (slower) mediates between "
                    f"{_short(p1)} and {_short(p2)}",
                    "Slow transfer. Event succeeds through patience and persistence.",
                ))
    return yogas


# --- DISRUPTION YOGAS ---

def _detect_manahoo(chart, tajika_data: dict, **kw) -> list:
    """
    Manahoo: Two planets in aspect, but Mars or Saturn makes an inimical
    aspect to the faster planet of the pair — disrupting the yoga.
    """
    yogas = []
    aspects = tajika_data.get("aspects_within_orb", [])
    matrix = tajika_data.get("matrix", {})
    malefics = {"Mars", "Saturn"}

    for asp in aspects:
        b1, b2 = asp["body1"], asp["body2"]
        if b1 not in TRADITIONAL_PLANETS or b2 not in TRADITIONAL_PLANETS:
            continue

        # Identify faster planet
        spds = tajika_data.get("speeds", {})
        faster = b1 if _is_faster(b1, b2, spds) else b2

        # Check if Mars or Saturn aspects the faster planet with inimical aspect
        for mal in malefics:
            if mal in (b1, b2):
                continue
            mal_asp = matrix.get((mal, faster))
            if mal_asp is None:
                continue
            # Inimical = square or opposition
            if mal_asp["aspect"] in ("Square", "Opposition"):
                yogas.append(_yoga(
                    "Manahoo", "DISRUPTION", [b1, b2, mal],
                    f"{_short(mal)} disrupts {_short(b1)}-{_short(b2)} "
                    f"{asp['aspect']} via {mal_asp['aspect']} to {_short(faster)}",
                    f"Obstruction. {mal} interferes with the outcome.",
                ))
    return yogas


# --- VOID YOGAS ---

def _detect_suunya_marga(chart, tajika_data: dict, **kw) -> list:
    """
    Suunya Marga: Planet not in any aspect with another traditional planet
    AND not in any special dignity (exaltation, mulatrikona, own sign).
    """
    yogas = []
    matrix = tajika_data.get("matrix", {})
    suunya_planets = []

    for planet in TRADITIONAL_PLANETS:
        if not has_planet(chart, planet):
            continue

        # Check if in any aspect with another traditional planet
        has_aspect = False
        for other in TRADITIONAL_PLANETS:
            if other == planet:
                continue
            if (planet, other) in matrix:
                has_aspect = True
                break

        if has_aspect:
            continue

        # Check dignity
        if _is_dignified(planet, chart):
            continue

        suunya_planets.append(planet)
        yogas.append(_yoga(
            "Suunya Marga", "VOID", [planet],
            f"{planet} not in aspect with any planet. No special dignity.",
            "Void of effects. Planet cannot deliver results.",
        ))

    return yogas


def _detect_khallasara(suunya_yogas: list, **kw) -> list:
    """
    Khallasara: Moon specifically in Suunya Marga.
    A special case — the Moon being void makes the whole chart weaker.
    """
    yogas = []
    for yoga in suunya_yogas:
        if "Moon" in yoga["planets"]:
            yogas.append(_yoga(
                "Khallasara", "FAILURE", ["Moon"],
                "Moon in Suunya Marga (void of aspects and dignity)",
                "Moon void. Emotional disconnection, events lack support.",
            ))
    return yogas


# --- ENHANCEMENT YOGAS (depend on Ithasala) ---

def _detect_kambula(chart, tajika_data: dict,
                     ithasala_yogas: list, positions: dict = None, **kw) -> list:
    """
    Kambula: Two planets in Ithasala + Moon in Ithasala with one or both.
    Moon amplifies the Ithasala, making it powerful.
    """
    yogas = []
    if not ithasala_yogas:
        return yogas

    if positions is None:
        positions = _pair_positions(chart)

    for ith in ithasala_yogas:
        planets = ith["planets"]
        if len(planets) < 2:
            continue
        p1, p2 = planets[0], planets[1]

        # Moon must NOT be part of the Ithasala pair itself
        if "Moon" in (p1, p2):
            continue

        # Check if Moon is in Ithasala with either planet (deg-in-sign rule)
        for target in (p1, p2):
            if _in_itthasala("Moon", target, positions):
                yogas.append(_yoga(
                    "Kambula", "SUCCESS",
                    ["Moon", p1, p2],
                    f"{_short(p1)}-{_short(p2)} Ithasala + Moon in "
                    f"Ithasala with {_short(target)}",
                    "GREAT SUCCESS. Moon amplifies the result.",
                ))
                break  # One Kambula per Ithasala pair

    return yogas


def _detect_dutthothadi(chart, tajika_data: dict,
                         ithasala_yogas: list, house_data: dict = None,
                         bala_data: dict = None, positions: dict = None,
                         **kw) -> list:
    """
    Dutthothadi: Weak Ithasala pair (both planets weak) but one of them
    also in Ithasala with a dignified planet — salvation through strength.
    """
    yogas = []
    if not ithasala_yogas:
        return yogas

    if positions is None:
        positions = _pair_positions(chart)

    for ith in ithasala_yogas:
        planets = ith["planets"]
        if len(planets) < 2:
            continue
        p1, p2 = planets[0], planets[1]

        # Both must be weak
        if not (_is_weak(p1, chart, house_data, bala_data=bala_data) and
                _is_weak(p2, chart, house_data, bala_data=bala_data)):
            continue

        # One of them must be in Ithasala with a dignified planet (the rule)
        for weak_p in (p1, p2):
            for strong_p in TRADITIONAL_PLANETS:
                if strong_p in (p1, p2):
                    continue
                if not _is_dignified(strong_p, chart):
                    continue
                if _in_itthasala(weak_p, strong_p, positions):
                    yogas.append(_yoga(
                        "Dutthothadi", "SUCCESS",
                        [p1, p2, strong_p],
                        f"Weak {_short(p1)}-{_short(p2)} Ithasala, but "
                        f"{_short(weak_p)} supported by dignified {_short(strong_p)}",
                        "Success through support. A strong planet rescues a weak pair.",
                    ))
                    break
            else:
                continue
            break

    return yogas


# --- INDEPENDENT YOGAS ---

def _detect_kutha(chart, tajika_data: dict,
                   house_data: dict = None, **kw) -> list:
    """
    Kutha: A planet in the Lagna (1st house) aspected by a dignified planet
    from an angle (1,4,7,10) or panaphara (2,5,8,11).
    """
    yogas = []
    if not house_data:
        return yogas

    matrix = tajika_data.get("matrix", {})

    # Find planets in house 1
    h1_planets = []
    h1_info = house_data.get("houses", {}).get(1, {})
    for p_name, _ in h1_info.get("planets", []):
        if p_name in TRADITIONAL_PLANETS:
            h1_planets.append(p_name)

    for lagna_planet in h1_planets:
        for dignified_p in TRADITIONAL_PLANETS:
            if dignified_p == lagna_planet:
                continue
            if not _is_dignified(dignified_p, chart):
                continue
            # Must be in angle or panaphara
            d_house = _get_house_number(dignified_p, house_data)
            if d_house not in ANGLE_PANAPHARA_HOUSES:
                continue
            # Must aspect the lagna planet
            if (dignified_p, lagna_planet) not in matrix:
                continue

            yogas.append(_yoga(
                "Kutha", "SUCCESS",
                [lagna_planet, dignified_p],
                f"{_short(lagna_planet)} in Lagna aspected by dignified "
                f"{_short(dignified_p)} from house {d_house}",
                "Success through dignity. Lagna planet receives strong support.",
            ))
    return yogas


def _detect_tambeera(chart, tajika_data: dict, **kw) -> list:
    """
    Tambeera: Faster planet in last degree (29-30°) of its sign,
    target planet in the next sign. Imminent Ithasala about to form.
    """
    yogas = []
    positions = {}
    for p in TRADITIONAL_PLANETS:
        if has_planet(chart, p):
            positions[p] = get_planet_decimal_degrees(chart, p)

    trad_with_pos = [p for p in TRADITIONAL_PLANETS if p in positions]

    for faster in trad_with_pos:
        if not _in_last_degree(faster, chart):
            continue

        faster_sign = _get_sign_index(faster, chart)
        next_sign = _next_sign_index(faster_sign)

        for target in trad_with_pos:
            if target == faster:
                continue
            spds = tajika_data.get("speeds", {})
            if not _is_faster(faster, target, spds):
                continue

            target_sign = _get_sign_index(target, chart)
            if target_sign == next_sign:
                yogas.append(_yoga(
                    "Tambeera", "SUCCESS",
                    [faster, target],
                    f"{_short(faster)} at last degree, {_short(target)} in next sign",
                    "Imminent success. Ithasala about to form as planet changes sign.",
                ))
    return yogas


# --- DISRUPTION OF SUCCESS ---

def _detect_durapha(chart, success_yogas: list,
                     house_data: dict = None, bala_data: dict = None,
                     **kw) -> list:
    """
    Durapha: Planet in a SUCCESS yoga that has challenges (combust, debilitated,
    dusthana). Reports ALL factors — both challenges and strengths — so the
    astrologer can make their own judgment.

    Challenges: combust, debilitated, dusthana house.
    Strengths: dignity (exaltation/own sign/mulatrikona), retrograde (closer to Earth),
               angular house (1,4,7,10), Uccha/Dig/Chesta Bala values.
    """
    yogas = []
    checked = set()

    for yoga in success_yogas:
        for planet in yoga["planets"]:
            if planet in checked:
                continue
            if planet not in TRADITIONAL_PLANETS:
                continue
            checked.add(planet)

            challenges = []
            strengths = []

            # --- Challenges ---
            if _is_combust(planet, chart):
                challenges.append("combust")
            if _is_debilitated(planet, chart):
                challenges.append("debilitated")
            house_num = 0
            if house_data:
                house_num = _get_house_number(planet, house_data)
                if house_num in DUSTHANA_HOUSES:
                    challenges.append(f"house {house_num} (dusthana)")

            # --- Strengths ---
            # Dignity with Lajitadi-style points (own=30, MT=45, exalt=60)
            _DIGNITY_POINTS = {"own_sign": 30, "mulatrikona": 45, "exaltation": 60}
            sign_name = get_planet_sign_name(chart, planet, default="")
            deg_in_sign = get_planet_in_sign_longitude(chart, planet)
            dignity = check_planet_dignity(planet, sign_name, deg_in_sign)
            if dignity in _DIGNITY_POINTS:
                label = dignity.replace("_", " ")
                strengths.append(f"{label} ({_DIGNITY_POINTS[dignity]})")

            # Retrograde (strength, not weakness)
            if _is_retrograde(planet, chart):
                strengths.append("retrograde")

            # Angular house (1,4,7,10 = strong; 5,9 = trinal)
            if house_num in (1, 4, 7, 10):
                strengths.append(f"house {house_num} (angular)")
            elif house_num in (5, 9):
                strengths.append(f"house {house_num} (trinal)")

            # All 3 Bala values (always show all with numbers)
            # Keys from bala_calculator: "uccha", "digbala", "chesta"
            if bala_data and planet in bala_data:
                pb = bala_data[planet]
                uccha = pb.get("uccha", 0)
                digbala = pb.get("digbala", 0)
                chesta = pb.get("chesta", 0)
                strengths.append(
                    f"Uccha={uccha:.0f} Dig={digbala:.0f} Chesta={chesta:.0f}"
                )

            # Only create Durapha if there are actual challenges
            if not challenges:
                continue

            # Build description showing both sides
            desc_parts = [f"{planet} in {yoga['yoga_name']}"]
            desc_parts.append(f"Challenges: {', '.join(challenges)}")
            if strengths:
                desc_parts.append(f"Strengths: {', '.join(strengths)}")

            if strengths:
                effect = ("Mixed factors. Challenges present but planet has compensating "
                          "strengths — astrologer's judgment needed.")
            else:
                effect = "Success undermined. Planet too weak to deliver fully."

            yogas.append(_yoga(
                "Durapha", "DISRUPTION",
                [planet],
                " | ".join(desc_parts),
                effect,
                source_yoga=yoga["yoga_name"],
            ))
    return yogas


# --- SPECIAL YOGA ---

def _detect_gairi_kabula(chart, tajika_data: dict,
                          ithasala_yogas: list, suunya_yogas: list, **kw) -> list:
    """
    Gairi Kabula: Lagna lord in Ithasala + Moon in Suunya Marga
    + Moon in last degree + a dignified planet in the next sign.
    Prashna-specific salvation yoga.
    """
    yogas = []
    lagna_lord = _get_lagna_lord(chart)
    if not lagna_lord:
        return yogas

    # Check if lagna lord is in any Ithasala
    lagna_in_ithasala = False
    for ith in ithasala_yogas:
        if lagna_lord in ith["planets"]:
            lagna_in_ithasala = True
            break

    if not lagna_in_ithasala:
        return yogas

    # Moon must be in Suunya Marga
    moon_suunya = any("Moon" in y["planets"] for y in suunya_yogas)
    if not moon_suunya:
        return yogas

    # Moon in last degree
    if not _in_last_degree("Moon", chart):
        return yogas

    # Dignified planet in next sign from Moon
    moon_sign = _get_sign_index("Moon", chart)
    next_sign = _next_sign_index(moon_sign)

    for planet in TRADITIONAL_PLANETS:
        if planet == "Moon":
            continue
        p_sign = _get_sign_index(planet, chart)
        if p_sign == next_sign and _is_dignified(planet, chart):
            yogas.append(_yoga(
                "Gairi Kabula", "SPECIAL",
                ["Moon", lagna_lord, planet],
                f"Lagna lord {_short(lagna_lord)} in Ithasala + Moon void "
                f"at last degree + dignified {_short(planet)} in next sign",
                "Prashna salvation. Despite Moon's weakness, dignified planet rescues.",
            ))
            break

    return yogas


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def detect_all_tajika_yogas(chart, tajika_data: dict) -> dict:
    """
    Detect all 16 Tajika yogas for a chart.

    Args:
        chart: libaditya Chart or legacy renderer dict.
        tajika_data: From calculate_all_tajika_aspects().

    Returns:
        {
            "yogas_by_category": {category: [yoga_records...]},
            "all_yogas": [flat list],
            "summary": {category_count: int, ...}
        }
    """
    house_data = get_planets_by_house(chart)
    # Degrees-in-sign map, computed once and shared by every deg-in-sign detector.
    positions = _pair_positions(chart)

    # Phase 1: Independent yogas
    ikkavala = _detect_ikkavala(chart, house_data)
    induvara = _detect_induvara(chart, house_data)
    ithasala = _detect_ithasala(chart, tajika_data, positions=positions)
    isharapha = _detect_isharapha(chart, tajika_data, positions=positions)
    nakta = _detect_nakta(chart, tajika_data)
    yamaya = _detect_yamaya(chart, tajika_data)
    suunya = _detect_suunya_marga(chart, tajika_data)
    manahoo = _detect_manahoo(chart, tajika_data)
    kutha = _detect_kutha(chart, tajika_data, house_data=house_data)
    tambeera = _detect_tambeera(chart, tajika_data)

    # Phase 2: Dependent yogas (pre-compute bala_data once for performance)
    bala_data = None
    if HAS_BALA:
        try:
            bala_data = get_all_bala_data(chart)
        except Exception:
            pass

    khallasara = _detect_khallasara(suunya)
    kambula = _detect_kambula(chart, tajika_data, ithasala, positions=positions)
    dutthothadi = _detect_dutthothadi(chart, tajika_data, ithasala,
                                       house_data=house_data,
                                       bala_data=bala_data,
                                       positions=positions)

    # Phase 3: Depends on all success yogas
    success_yogas = ikkavala + ithasala + kambula + kutha + tambeera + dutthothadi
    durapha = _detect_durapha(chart, success_yogas, house_data=house_data,
                              bala_data=bala_data)

    # Phase 4: Depends on multiple results
    gairi_kabula = _detect_gairi_kabula(chart, tajika_data,
                                         ithasala, suunya)

    # Collect all
    all_yogas = (ikkavala + induvara + ithasala + isharapha + nakta + yamaya +
                 manahoo + suunya + khallasara + kambula + dutthothadi +
                 kutha + tambeera + durapha + gairi_kabula)

    # Group by category
    categories = ["SUCCESS", "FAILURE", "DISRUPTION", "VOID", "TRANSFER", "SPECIAL"]
    yogas_by_category = {cat: [] for cat in categories}
    for yoga in all_yogas:
        cat = yoga["category"]
        if cat in yogas_by_category:
            yogas_by_category[cat].append(yoga)

    # Summary
    summary = {
        f"{cat.lower()}_count": len(yogas_by_category[cat])
        for cat in categories
    }
    summary["total_count"] = len(all_yogas)

    return {
        "yogas_by_category": yogas_by_category,
        "all_yogas": all_yogas,
        "summary": summary,
    }
