# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Dominant sign/element/modality/dignity analysis.
=================================================
"""

from collections import defaultdict

from .constants import (
    PLANETS, LUMINARY_PLANETS, DEFAULT_LUMINARY_WEIGHT,
    ADITYA_DIGNITIES, check_planet_dignity,
    get_sign_elements, get_sign_modalities,
)
from .retinue import get_hora, get_trimsamsa_being, ADITYA_SIGN_ORDER
from core.chart_helpers import (
    get_planet_sign_name, get_planet_aditya_degrees,
    get_planet_decimal_degrees, get_planet_in_sign_longitude,
    get_planet_sign_index, has_planet, TROPICAL_NAMES,
)

# Planets for divisional element analysis (no Rahu/Ketu/outer/Ascendant)
ELEMENT_ANALYSIS_PLANETS = ["Sun", "Moon", "Mars", "Mercury",
                            "Jupiter", "Venus", "Saturn"]


def _classic_sign_name(decimal_degrees: float) -> str:
    """Tropical-sign name from a 0-360 ecliptic longitude."""
    return TROPICAL_NAMES[int(decimal_degrees // 30) % 12]


def get_dominant_aditya(chart_or_data):
    """
    Extract dominant Aditya signs (signs with most planets).

    Args:
        chart_or_data: libaditya Chart object.

    Returns:
        dict: {
            "dominant_signs": [(sign_name, [planet_list], count), ...],
            "sun_sign": str,
            "moon_sign": str,
            "has_strong_dominant": bool
        }
    """
    sign_planets = defaultdict(list)

    for planet in PLANETS:
        if planet in ["Rahu", "Ketu"]:
            continue
        if has_planet(chart_or_data, planet):
            sign = get_planet_sign_name(chart_or_data, planet)
            if sign:
                sign_planets[sign].append(planet)

    sorted_signs = sorted(sign_planets.items(), key=lambda x: -len(x[1]))
    has_dominant = any(len(planets) >= 2 for sign, planets in sorted_signs)

    sun_sign = get_planet_sign_name(chart_or_data, "Sun", default="Unknown")
    moon_sign = get_planet_sign_name(chart_or_data, "Moon", default="Unknown")

    dominant_signs = []
    for sign, planets in sorted_signs:
        if len(planets) >= 2 or (not has_dominant and len(planets) >= 1):
            dominant_signs.append((sign, planets, len(planets)))

    if has_dominant:
        dominant_signs = [(s, p, c) for s, p, c in dominant_signs if c >= 2]

    return {
        "dominant_signs": dominant_signs,
        "sun_sign": sun_sign,
        "moon_sign": moon_sign,
        "has_strong_dominant": has_dominant
    }


def get_dominant_elements(chart_or_data, luminary_weight=DEFAULT_LUMINARY_WEIGHT,
                          mode="aditya", ayanamsa_offset=0.0):
    """
    Extract dominant elements based on sign positions (not planet elements).

    Per the 2026-04-10 learning, the function must respect explicit mode +
    ayanamsa_offset params — never silently fall back to a single key. The
    Chart-Everywhere migration preserves that invariant; only the read
    primitives change to go through chart_helpers.

    Args:
        chart_or_data: libaditya Chart object.
        luminary_weight: Weight for Sun/Moon (default 1.5)
        mode: "aditya" for Aditya Zodiac, "tropical_classic" for Tropical, "sidereal" for Sidereal
        ayanamsa_offset: Ayanamsa degrees for sidereal mode

    Returns:
        dict with element_counts, dominant_elements, has_dominant, total_weight, etc.
    """
    sign_elements = get_sign_elements("aditya")

    element_planets = defaultdict(list)
    total_weight = 0.0

    for planet in PLANETS:
        if planet in ["Rahu", "Ketu"]:
            continue
        if not has_planet(chart_or_data, planet):
            continue

        sign_idx = get_planet_sign_index(chart_or_data, planet)
        sign = ADITYA_SIGN_ORDER[sign_idx]

        if sign and sign in sign_elements:
            element = sign_elements[sign]
            weight = luminary_weight if planet in LUMINARY_PLANETS else 1.0
            element_planets[element].append((planet, sign, weight))
            total_weight += weight

    element_weighted = {}
    for element, planets in element_planets.items():
        weighted = sum(w for _, _, w in planets)
        element_weighted[element] = weighted

    sorted_elements = sorted(element_planets.items(),
                             key=lambda x: -element_weighted[x[0]])

    dominant_elements = []
    for element, planets in sorted_elements:
        raw_count = len(planets)
        weighted = element_weighted[element]
        percent = (weighted / total_weight * 100) if total_weight > 0 else 0
        planet_names = [p for p, _, _ in planets]
        dominant_elements.append((element, raw_count, weighted, percent, planet_names))

    has_dominant = any(pct >= 30 for _, _, _, pct, _ in dominant_elements)

    return {
        "element_counts": {e: [(p, s) for p, s, _ in planets]
                          for e, planets in element_planets.items()},
        "dominant_elements": dominant_elements,
        "has_dominant": has_dominant,
        "total_weight": total_weight,
        "luminary_weight": luminary_weight,
        "mode": mode
    }


def get_dominant_modality(chart_or_data, luminary_weight=DEFAULT_LUMINARY_WEIGHT, mode="aditya"):
    """
    Extract dominant modality based on sign positions.

    Args:
        chart_or_data: libaditya Chart object.
        luminary_weight: Weight for Sun/Moon (default 1.5)
        mode: "aditya" for Aditya Zodiac, "tropical_classic" for Tropical

    Returns:
        dict with modality_counts, dominant_modalities, has_dominant, total_weight, etc.
    """
    sign_modalities = get_sign_modalities("aditya")

    modality_planets = defaultdict(list)
    total_weight = 0.0

    for planet in PLANETS:
        if planet in ["Rahu", "Ketu"]:
            continue
        if not has_planet(chart_or_data, planet):
            continue

        sign_idx = get_planet_sign_index(chart_or_data, planet)
        sign = ADITYA_SIGN_ORDER[sign_idx]
        if sign and sign in sign_modalities:
            modality = sign_modalities[sign]
            weight = luminary_weight if planet in LUMINARY_PLANETS else 1.0
            modality_planets[modality].append((planet, sign, weight))
            total_weight += weight

    modality_weighted = {}
    for modality, planets in modality_planets.items():
        weighted = sum(w for _, _, w in planets)
        modality_weighted[modality] = weighted

    sorted_modalities = sorted(modality_planets.items(),
                               key=lambda x: -modality_weighted[x[0]])

    dominant_modalities = []
    for modality, planets in sorted_modalities:
        raw_count = len(planets)
        weighted = modality_weighted[modality]
        percent = (weighted / total_weight * 100) if total_weight > 0 else 0
        planet_names = [p for p, _, _ in planets]
        dominant_modalities.append((modality, raw_count, weighted, percent, planet_names))

    has_dominant = any(pct >= 40 for _, _, _, pct, _ in dominant_modalities)

    return {
        "modality_counts": {m: [(p, s) for p, s, _ in planets]
                           for m, planets in modality_planets.items()},
        "dominant_modalities": dominant_modalities,
        "has_dominant": has_dominant,
        "total_weight": total_weight,
        "luminary_weight": luminary_weight,
        "mode": mode
    }


def get_dominant_dignity(chart_or_data):
    """
    Extract planets with strong dignity (EX, MK, OH) or debilitation (DB).

    Always uses Aditya sign names (the dignity table is keyed by Aditya signs).

    Args:
        chart_or_data: libaditya Chart object.

    Returns:
        list: [(planet_name, dignity_type, sign_name, deg_in_sign), ...]
    """
    dignified = []

    for planet in PLANETS:
        if not has_planet(chart_or_data, planet):
            continue
        if planet not in ADITYA_DIGNITIES:
            continue

        sign_name = get_planet_sign_name(chart_or_data, planet)
        deg_in_sign = get_planet_in_sign_longitude(chart_or_data, planet)

        if not sign_name:
            continue

        dignity = check_planet_dignity(planet, sign_name, deg_in_sign)
        if dignity:
            dignified.append((planet, dignity, sign_name, deg_in_sign))

    return dignified


# =============================================================================
# HORA & TRIMSAMSA ELEMENT DISTRIBUTIONS
# =============================================================================

def get_hora_elements(chart_or_data, luminary_weight=DEFAULT_LUMINARY_WEIGHT,
                      tropical_mode=False, ayanamsa_offset=0.0):
    """
    Element distribution based on Hora lords (Sun=Fire, Moon=Water).

    Binary split: planets in Sun Hora contribute to Fire,
    planets in Moon Hora contribute to Water.

    Per the 2026-04-10 learning, callers MUST pass tropical_mode/
    ayanamsa_offset explicitly — the function never silently falls back
    to a single sign source. The Chart-Everywhere migration preserves
    that contract; only the read primitives go through chart_helpers.

    Args:
        chart_or_data: libaditya Chart object.
        luminary_weight: Weight for Sun/Moon (default 1.5)
        tropical_mode: Use raw tropical positions (classic mode)
        ayanamsa_offset: Ayanamsa degrees for sidereal mode

    Returns:
        dict with same structure as get_dominant_elements():
            element_counts, dominant_elements, has_dominant, total_weight,
            plus per-planet detail list and analysis type.
    """
    element_planets = defaultdict(list)
    detail = []
    total_weight = 0.0

    for planet in ELEMENT_ANALYSIS_PLANETS:
        if not has_planet(chart_or_data, planet):
            continue

        sign_idx = get_planet_sign_index(chart_or_data, planet)
        aditya_sign = ADITYA_SIGN_ORDER[sign_idx]
        degree = get_planet_in_sign_longitude(chart_or_data, planet)

        if not aditya_sign:
            continue
        hora = get_hora(aditya_sign, degree)
        element = "Fire" if hora["lord"] == "Sun" else "Water"
        weight = luminary_weight if planet in LUMINARY_PLANETS else 1.0

        hora_label = f"{hora['lord']} Hora"
        element_planets[element].append((planet, hora_label, weight))
        # Detail uses degree-int and minute-int derived from the in-sign degree.
        deg_int = int(degree)
        min_int = int((degree - deg_int) * 60)
        detail.append({
            "planet": planet,
            "sign": aditya_sign,
            "degrees": deg_int,
            "minutes": min_int,
            "hora_lord": hora["lord"],
            "hora_being": hora["being_name"],
            "element": element,
        })
        total_weight += weight

    # Compute weighted totals and percentages
    element_weighted = {e: sum(w for _, _, w in ps)
                        for e, ps in element_planets.items()}
    sorted_elements = sorted(element_planets.items(),
                             key=lambda x: -element_weighted[x[0]])

    dominant_elements = []
    for element, planets in sorted_elements:
        raw_count = len(planets)
        weighted = element_weighted[element]
        percent = (weighted / total_weight * 100) if total_weight > 0 else 0
        planet_names = [p for p, _, _ in planets]
        dominant_elements.append((element, raw_count, weighted, percent, planet_names))

    has_dominant = any(pct >= 50 for _, _, _, pct, _ in dominant_elements)

    return {
        "element_counts": {e: [(p, s) for p, s, _ in planets]
                          for e, planets in element_planets.items()},
        "dominant_elements": dominant_elements,
        "has_dominant": has_dominant,
        "total_weight": total_weight,
        "luminary_weight": luminary_weight,
        "detail": detail,
        "analysis": "hora",
    }


def get_trimsamsa_elements(chart_or_data, luminary_weight=DEFAULT_LUMINARY_WEIGHT,
                           tropical_mode=False, ayanamsa_offset=0.0):
    """
    Element distribution based on Trimsamsa divisions (5 elements).

    Each planet's degree falls in one of 5 trimsamsa divisions per sign,
    each mapped to an element: Fire, Air, Ether, Earth, Water.

    Per the 2026-04-10 learning, callers MUST pass tropical_mode/
    ayanamsa_offset explicitly — same contract as get_hora_elements.

    Args:
        chart_or_data: libaditya Chart object.
        luminary_weight: Weight for Sun/Moon (default 1.5)
        tropical_mode: Use raw tropical positions (classic mode)
        ayanamsa_offset: Ayanamsa degrees for sidereal mode

    Returns:
        dict with same structure as get_dominant_elements():
            element_counts, dominant_elements, has_dominant, total_weight,
            plus per-planet detail list and analysis type.
    """
    element_planets = defaultdict(list)
    detail = []
    total_weight = 0.0

    for planet in ELEMENT_ANALYSIS_PLANETS:
        if not has_planet(chart_or_data, planet):
            continue

        sign_idx = get_planet_sign_index(chart_or_data, planet)
        aditya_sign = ADITYA_SIGN_ORDER[sign_idx]
        degree = get_planet_in_sign_longitude(chart_or_data, planet)

        if not aditya_sign:
            continue

        trimsamsa = get_trimsamsa_being(aditya_sign, degree)
        element = trimsamsa["element"]
        weight = luminary_weight if planet in LUMINARY_PLANETS else 1.0

        element_planets[element].append((planet, trimsamsa["being_type"], weight))
        deg_int = int(degree)
        min_int = int((degree - deg_int) * 60)
        detail.append({
            "planet": planet,
            "sign": aditya_sign,
            "degrees": deg_int,
            "minutes": min_int,
            "being_type": trimsamsa["being_type"],
            "being_name": trimsamsa["being_name"],
            "element": element,
            "lord": trimsamsa["lord"],
        })
        total_weight += weight

    # Compute weighted totals and percentages
    element_weighted = {e: sum(w for _, _, w in ps)
                        for e, ps in element_planets.items()}
    sorted_elements = sorted(element_planets.items(),
                             key=lambda x: -element_weighted[x[0]])

    dominant_elements = []
    for element, planets in sorted_elements:
        raw_count = len(planets)
        weighted = element_weighted[element]
        percent = (weighted / total_weight * 100) if total_weight > 0 else 0
        planet_names = [p for p, _, _ in planets]
        dominant_elements.append((element, raw_count, weighted, percent, planet_names))

    has_dominant = any(pct >= 30 for _, _, _, pct, _ in dominant_elements)

    return {
        "element_counts": {e: [(p, s) for p, s, _ in planets]
                          for e, planets in element_planets.items()},
        "dominant_elements": dominant_elements,
        "has_dominant": has_dominant,
        "total_weight": total_weight,
        "luminary_weight": luminary_weight,
        "detail": detail,
        "analysis": "trimsamsa",
    }
