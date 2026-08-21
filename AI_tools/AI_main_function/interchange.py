# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Interchange yoga (Parivartana) detection.
==========================================
Migrated to Chart-based API (mode-agnostic, works in all zodiac systems).

Three categories per Vedic tradition:
  Maha Yoga   = exchange between good houses (1,2,4,5,7,9,10,11)
  Khala Yoga  = exchange involving 3rd house with non-dusthana house
  Dainya Yoga = exchange involving 6th, 8th, or 12th house
"""

from core.chart_helpers import get_planet_sign_name, get_planet_sign_index, has_planet
from AI_tools.AI_main_function.constants import DUSTHANA_HOUSES

PLANETS_LIST = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]

_SIGN_INDEX_RULERS = {
    0: "Mars",      # Dhata / Aries
    1: "Venus",     # Aryama / Taurus
    2: "Mercury",   # Mitra / Gemini
    3: "Moon",      # Varuna / Cancer
    4: "Sun",       # Indra / Leo
    5: "Mercury",   # Vivasvan / Virgo
    6: "Venus",     # Tvasta / Libra
    7: "Mars",      # Vishnu / Scorpio
    8: "Jupiter",   # Amzu / Sagittarius
    9: "Saturn",    # Bhaga / Capricorn
    10: "Saturn",   # Pusha / Aquarius
    11: "Jupiter",  # Parjanya / Pisces
}


def _classify_interchange(house_a, house_b):
    """Classify an interchange yoga using Vedic Parivartana categories."""
    a_dusthana = house_a in DUSTHANA_HOUSES
    b_dusthana = house_b in DUSTHANA_HOUSES

    if a_dusthana and b_dusthana:
        return "DAINYA_DOUBLE"

    if a_dusthana or b_dusthana:
        dusthana = house_a if a_dusthana else house_b
        if dusthana == 6:
            return "DAINYA_6"
        elif dusthana == 8:
            return "DAINYA_8"
        else:
            return "DAINYA_12"

    if house_a == 3 or house_b == 3:
        return "KHALA"

    return "MAHA"


def _dainya_afflicted_houses(house_a, house_b, classification):
    """Afflicted house(s) for a Dainya interchange.

    A single-dusthana Dainya afflicts the NON-dusthana partner house (the good
    house dragged onto the 6/8/12 misery axis). A DAINYA_DOUBLE (both houses in a
    dusthana) afflicts BOTH. Returns a list of house numbers, or None for a
    non-Dainya classification.
    """
    if classification == "DAINYA_DOUBLE":
        return [house_a, house_b]
    if classification in ("DAINYA_6", "DAINYA_8", "DAINYA_12"):
        # Report the house that is NOT the dusthana (the afflicted good house).
        return [house_b if house_a in DUSTHANA_HOUSES else house_a]
    return None


def dispositor(chart, planet):
    """Return the planet that RULES the sign `planet` occupies (its dispositor).

    Index-keyed via `_SIGN_INDEX_RULERS`, using the chart's own sign-index API
    (no manual ayanamsa math). PURE: takes an ALREADY-FRAMED chart and reads NO
    GUI state. Sidereal (or any other) framing is the caller's responsibility.
    # EXCHDISP-REVIEW: R4 sidereal-rebuild deferred to caller seam
    Returns the ruler planet name, or None if the planet is absent/unresolved.
    """
    idx = get_planet_sign_index(chart, planet, default=-1)
    if idx < 0:
        return None
    return _SIGN_INDEX_RULERS.get(idx)


def house_of(chart, planet):
    """Return the whole-sign house (1-12) the planet OCCUPIES, or None.

    # EXCHDISP-REVIEW: R5 occupied-not-owned house
    Uses the sign the planet OCCUPIES (via `_build_sign_house_map`), never the
    sign it rules. PURE: no GUI state, no manual ayanamsa math; the chart must be
    framed by the caller.
    """
    sign_to_house = _build_sign_house_map(chart)
    if sign_to_house is None:
        return None
    idx = get_planet_sign_index(chart, planet, default=-1)
    if idx < 0:
        return None
    return sign_to_house.get(idx)


def _build_sign_house_map(chart):
    """Build sign_index -> house_number map from the ascendant's sign index."""
    asc_idx = get_planet_sign_index(chart, "Ascendant", default=-1)
    if asc_idx < 0:
        return None
    sign_to_house = {}
    for house_num in range(1, 13):
        sign_idx = (asc_idx + house_num - 1) % 12
        sign_to_house[sign_idx] = house_num
    return sign_to_house


def _collect_planet_positions(chart):
    """Collect sign_index and sign_name for each planet."""
    positions = {}
    for planet in PLANETS_LIST:
        if has_planet(chart, planet):
            idx = get_planet_sign_index(chart, planet, default=-1)
            if idx >= 0:
                name = get_planet_sign_name(chart, planet)
                positions[planet] = (idx, name)
    return positions


def get_all_interchanges(chart):
    """Detect ALL interchange yogas (Parivartana) and classify them.

    Returns dict with interchanges list, by_type grouping, and boolean flags.
    Classification uses Vedic terms: MAHA, KHALA, DAINYA_6/8/12, DAINYA_DOUBLE.
    """
    all_types = ["MAHA", "KHALA", "DAINYA_6", "DAINYA_8", "DAINYA_12", "DAINYA_DOUBLE"]
    interchanges = []
    by_type = {t: [] for t in all_types}

    # dainya_afflicted: a NEW parallel field keyed by the (planet_a, planet_b)
    # pair -> list of afflicted house numbers. Kept SEPARATE from the frozen
    # 7-tuple in "interchanges" (consumers hard-unpack exactly 7 elements).
    dainya_afflicted = {}

    sign_to_house = _build_sign_house_map(chart)
    if sign_to_house is None:
        return {
            "interchanges": [],
            "by_type": by_type,
            "has_maha": False,
            "has_khala": False,
            "has_dainya": False,
            "dainya_afflicted": dainya_afflicted,
        }

    positions = _collect_planet_positions(chart)

    for i, planet_a in enumerate(PLANETS_LIST):
        for planet_b in PLANETS_LIST[i+1:]:
            if planet_a not in positions or planet_b not in positions:
                continue

            idx_a, sign_a = positions[planet_a]
            idx_b, sign_b = positions[planet_b]

            ruler_of_a = _SIGN_INDEX_RULERS.get(idx_a)
            ruler_of_b = _SIGN_INDEX_RULERS.get(idx_b)

            if ruler_of_a == planet_b and ruler_of_b == planet_a:
                house_a = sign_to_house.get(idx_a, 0)
                house_b = sign_to_house.get(idx_b, 0)
                if house_a == 0 or house_b == 0:
                    continue

                classification = _classify_interchange(house_a, house_b)

                # 7-tuple shape is FROZEN (H1) — consumers hard-unpack 7 elements.
                record = (
                    planet_a, sign_a, house_a,
                    planet_b, sign_b, house_b,
                    classification
                )
                interchanges.append(record)
                by_type[classification].append(record)

                afflicted = _dainya_afflicted_houses(house_a, house_b, classification)
                if afflicted is not None:
                    dainya_afflicted[(planet_a, planet_b)] = afflicted

    dainya_types = {"DAINYA_6", "DAINYA_8", "DAINYA_12", "DAINYA_DOUBLE"}

    return {
        "interchanges": interchanges,
        "by_type": by_type,
        "has_maha": bool(by_type["MAHA"]),
        "has_khala": bool(by_type["KHALA"]),
        "has_dainya": any(by_type[t] for t in dainya_types),
        "dainya_afflicted": dainya_afflicted,
    }


def get_bad_interchanges(chart):
    """Detect Dainya (misery) interchange yogas.

    Delegates to get_all_interchanges() and filters for dusthana exchanges.
    """
    all_result = get_all_interchanges(chart)
    if not all_result["interchanges"]:
        return {
            "interchanges": [],
            "by_type": {},
            "has_bad_interchange": False,
            "note": None
        }

    dainya_types = {"DAINYA_6", "DAINYA_8", "DAINYA_12", "DAINYA_DOUBLE"}
    interchanges = []
    by_type = {t: [] for t in dainya_types}

    for rec in all_result["interchanges"]:
        classification = rec[6]
        if classification in dainya_types:
            interchanges.append(rec)
            by_type[classification].append(rec)

    return {
        "interchanges": interchanges,
        "by_type": by_type,
        "has_bad_interchange": len(interchanges) > 0,
        "note": None
    }
