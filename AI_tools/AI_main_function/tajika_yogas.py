# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
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

Reference: Ernst Wilhelm's Tajika PDFs in docs/tajika_prasna/.
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
    effective_orb,
    is_within_orb,
    calculate_tajika_strength,
    determine_applying_separating,
    classify_tajika_aspect,
    MAIN_ASPECT_ANGLES,
)
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
    """Planet has negative speed (retrograde). Sun/Moon never retrograde."""
    if planet in ("Sun", "Moon"):
        return False
    jd = _get_jd(chart)
    if jd is None or not HAS_BALA:
        return False
    try:
        speed = get_planet_speed(planet, jd)
        return speed < 0
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

def _detect_ithasala(chart, tajika_data: dict, **kw) -> list:
    """
    Ithasala: Applying aspects between two planets.
    3 subtypes:
      - Purna: within orb, distance_from_exact <= 1.0° (most powerful)
      - Vartamana: within orb, distance_from_exact > 1.0° (current, manifesting)
      - Bhavishyata: OUT of orb but faster planet applying toward exact aspect
    """
    yogas = []
    aspects = tajika_data.get("aspects_within_orb", [])

    # Purna and Vartamana: within orb + applying
    for asp in aspects:
        b1, b2 = asp["body1"], asp["body2"]
        # Skip if involves Ascendant or outer planets
        if b1 not in TRADITIONAL_PLANETS or b2 not in TRADITIONAL_PLANETS:
            continue
        if asp.get("applying_status") not in ("applying", "exact"):
            continue

        dist_exact = asp["distance_from_exact"]
        if dist_exact <= 1.0 or asp.get("applying_status") == "exact":
            subtype = "Purna"
            effect = "Event happening NOW. Most powerful Ithasala."
        else:
            subtype = "Vartamana"
            effect = "Event manifesting. Strong Ithasala currently active."

        # Determine faster/slower for arrow display
        speeds = tajika_data.get("speeds", {})
        if _is_faster(b1, b2, speeds):
            faster, slower = b1, b2
        else:
            faster, slower = b2, b1

        yogas.append(_yoga(
            "Ithasala", "SUCCESS", [faster, slower],
            f"{faster} applying to {slower} — {asp['aspect']}, "
            f"{asp['virupas']} VR ({dist_exact:.1f}° from exact)",
            effect,
            subtype=subtype,
            aspect_record=asp,
        ))

    # Bhavishyata: out of orb but applying toward an exact aspect
    positions = {}
    for body in TRADITIONAL_PLANETS:
        if has_planet(chart, body):
            positions[body] = get_planet_decimal_degrees(chart, body)

    in_orb_pairs = set()
    for asp in aspects:
        in_orb_pairs.add((asp["body1"], asp["body2"]))
        in_orb_pairs.add((asp["body2"], asp["body1"]))

    trad_with_pos = [p for p in TRADITIONAL_PLANETS if p in positions]
    for i, b1 in enumerate(trad_with_pos):
        for j in range(i + 1, len(trad_with_pos)):
            b2 = trad_with_pos[j]
            if (b1, b2) in in_orb_pairs:
                continue

            distance = (positions[b2] - positions[b1]) % 360

            # Find nearest aspect angle
            classified = classify_tajika_aspect(distance)
            if classified is None:
                continue

            exact_angle = classified[2]
            speeds = tajika_data.get("speeds", {})
            status = determine_applying_separating(
                b1, b2, distance, exact_angle,
                speed1=speeds.get(b1), speed2=speeds.get(b2),
            )
            if status not in ("applying", "exact"):
                continue

            # Confirm they're truly out of orb
            within, _, dist_exact, _ = is_within_orb(b1, b2, distance)
            if within:
                continue

            eff_orb = effective_orb(b1, b2)
            orb_excess = round(dist_exact - eff_orb, 1)

            if _is_faster(b1, b2, speeds):
                faster, slower = b1, b2
            else:
                faster, slower = b2, b1

            virupas = calculate_tajika_strength(distance)
            yogas.append(_yoga(
                "Ithasala", "SUCCESS", [faster, slower],
                f"{faster} applying toward {slower} — {classified[0]}, "
                f"{virupas:.1f} VR (out of orb by {orb_excess:.1f}°, "
                f"{dist_exact:.1f}° from exact)",
                "Distant future event. Will manifest when planets reach orb.",
                subtype="Bhavishyata",
                orb_excess=orb_excess,
            ))

    return yogas


def _detect_isharapha(chart, tajika_data: dict, **kw) -> list:
    """
    Isharapha: Separating aspects — the event is past.
    """
    yogas = []
    aspects = tajika_data.get("aspects_within_orb", [])

    for asp in aspects:
        b1, b2 = asp["body1"], asp["body2"]
        if b1 not in TRADITIONAL_PLANETS or b2 not in TRADITIONAL_PLANETS:
            continue
        if asp.get("applying_status") != "separating":
            continue

        speeds = tajika_data.get("speeds", {})
        if _is_faster(b1, b2, speeds):
            faster, slower = b1, b2
        else:
            faster, slower = b2, b1

        yogas.append(_yoga(
            "Isharapha", "FAILURE", [faster, slower],
            f"{faster} separating from {slower} — {asp['aspect']}, "
            f"{asp['virupas']} VR",
            "Past event. Disappointment or missed opportunity.",
            aspect_record=asp,
        ))
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
                     ithasala_yogas: list, **kw) -> list:
    """
    Kambula: Two planets in Ithasala + Moon in Ithasala with one or both.
    Moon amplifies the Ithasala, making it powerful.
    """
    yogas = []
    if not ithasala_yogas:
        return yogas

    matrix = tajika_data.get("matrix", {})

    for ith in ithasala_yogas:
        planets = ith["planets"]
        if len(planets) < 2:
            continue
        p1, p2 = planets[0], planets[1]

        # Moon must NOT be part of the Ithasala pair itself
        if "Moon" in (p1, p2):
            continue

        # Check if Moon is in Ithasala (applying aspect) with either planet
        for target in (p1, p2):
            moon_asp = matrix.get(("Moon", target))
            if moon_asp is None:
                continue
            if moon_asp.get("applying_status") in ("applying", "exact"):
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
                         bala_data: dict = None, **kw) -> list:
    """
    Dutthothadi: Weak Ithasala pair (both planets weak) but one of them
    also in Ithasala with a dignified planet — salvation through strength.
    """
    yogas = []
    if not ithasala_yogas:
        return yogas

    matrix = tajika_data.get("matrix", {})

    for ith in ithasala_yogas:
        planets = ith["planets"]
        if len(planets) < 2:
            continue
        p1, p2 = planets[0], planets[1]

        # Both must be weak
        if not (_is_weak(p1, chart, house_data, bala_data=bala_data) and
                _is_weak(p2, chart, house_data, bala_data=bala_data)):
            continue

        # One of them must be in applying aspect with a dignified planet
        for weak_p in (p1, p2):
            for strong_p in TRADITIONAL_PLANETS:
                if strong_p in (p1, p2):
                    continue
                if not _is_dignified(strong_p, chart):
                    continue
                asp = matrix.get((weak_p, strong_p))
                if asp and asp.get("applying_status") in ("applying", "exact"):
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

    # Phase 1: Independent yogas
    ikkavala = _detect_ikkavala(chart, house_data)
    induvara = _detect_induvara(chart, house_data)
    ithasala = _detect_ithasala(chart, tajika_data)
    isharapha = _detect_isharapha(chart, tajika_data)
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
    kambula = _detect_kambula(chart, tajika_data, ithasala)
    dutthothadi = _detect_dutthothadi(chart, tajika_data, ithasala,
                                       house_data=house_data,
                                       bala_data=bala_data)

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
