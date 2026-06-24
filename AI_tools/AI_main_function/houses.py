# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
House position and manifestation power analysis.
==================================================
"""

from .constants import PLANETS, ADITYA_SIGNS, HOUSE_POWER, POWER_ORDER, SIGN_RULERS
from core.chart_helpers import (
    get_planet_sign_name, get_planet_in_sign_longitude, has_planet,
)

# Tropical sign names — used when sidereal mode produces Western sign names
# instead of Aditya names. The chart_data_adapter normalises libaditya's IAST
# Aditya names to legacy ASCII; tropical signs come through unchanged.
TROPICAL_SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"
]

# Tropical sign rulers (same rulership, Western names)
TROPICAL_SIGN_RULERS = {
    "Aries": "Mars", "Taurus": "Venus", "Gemini": "Mercury", "Cancer": "Moon",
    "Leo": "Sun", "Virgo": "Mercury", "Libra": "Venus", "Scorpio": "Mars",
    "Sagittarius": "Jupiter", "Capricorn": "Saturn", "Aquarius": "Saturn", "Pisces": "Jupiter"
}


def _resolve_sign_list(asc_sign):
    """Return (sign_list, rulers_dict) matching the chart's sign naming convention.

    Aditya mode → ADITYA_SIGNS; classic/sidereal mode → TROPICAL_SIGNS. The
    chart_data_adapter ensures the Chart-path returns names from one of these
    two lists (libaditya IAST is normalized).
    """
    if asc_sign in ADITYA_SIGNS:
        return ADITYA_SIGNS, SIGN_RULERS
    if asc_sign in TROPICAL_SIGNS:
        return TROPICAL_SIGNS, TROPICAL_SIGN_RULERS
    import logging
    logging.getLogger(__name__).warning("Unknown sign name '%s' — cannot resolve sign list", asc_sign)
    return None, None


def get_house_lord(house_num, chart_or_data):
    """
    Get the ruling planet of a given house (1-12).

    Uses whole-sign houses: ascendant sign = 1st house, then sequential.
    Returns the ruler of the sign that falls in that house.

    Args:
        house_num: House number (1-12)
        chart_or_data: libaditya Chart object.

    Returns:
        str or None: Planet name that rules the house, or None if invalid
    """
    asc_sign = get_planet_sign_name(chart_or_data, "Ascendant", default="Unknown")

    sign_list, rulers = _resolve_sign_list(asc_sign)
    if sign_list is None:
        return None

    asc_index = sign_list.index(asc_sign)
    sign_index = (asc_index + house_num - 1) % 12
    house_sign = sign_list[sign_index]

    return rulers.get(house_sign)


def get_planets_by_house(chart_or_data):
    """
    Get planets organized by house (whole sign houses).

    In whole sign houses, the ascendant sign is the 1st house,
    and each subsequent sign is the next house.

    Args:
        chart_or_data: libaditya Chart object.

    Returns:
        dict: {
            "ascendant_sign": str,
            "houses": {1: {"sign": str, "planets": [(planet, deg), ...]}, ...}
        }
    """
    asc_sign = get_planet_sign_name(chart_or_data, "Ascendant", default="Unknown")

    sign_list, _rulers = _resolve_sign_list(asc_sign)
    if sign_list is None:
        return {"ascendant_sign": asc_sign, "houses": {}}

    asc_index = sign_list.index(asc_sign)

    house_signs = {}
    sign_to_house = {}
    for house_num in range(1, 13):
        sign_index = (asc_index + house_num - 1) % 12
        sign_name = sign_list[sign_index]
        house_signs[house_num] = sign_name
        sign_to_house[sign_name] = house_num

    houses = {}
    for house_num in range(1, 13):
        houses[house_num] = {
            "sign": house_signs[house_num],
            "planets": []
        }

    for planet in PLANETS:
        if not has_planet(chart_or_data, planet):
            continue

        planet_sign = get_planet_sign_name(chart_or_data, planet)
        deg_in_sign = get_planet_in_sign_longitude(chart_or_data, planet)

        if planet_sign and planet_sign in sign_to_house:
            house_num = sign_to_house[planet_sign]
            houses[house_num]["planets"].append((planet, deg_in_sign))

    return {
        "ascendant_sign": asc_sign,
        "houses": houses
    }


def get_manifestation_power(chart_or_data):
    """
    Get planets organized by their house manifestation power.

    Args:
        chart_or_data: libaditya Chart object.

    Returns:
        dict: {
            "by_power": {power_level: [(planet, house, sign, reason), ...]},
            "planet_power": {planet: (power_level, house, reason)}
        }
    """
    house_data = get_planets_by_house(chart_or_data)

    if not house_data["houses"]:
        return {"by_power": {}, "planet_power": {}}

    planet_houses = {}
    for house_num, house_info in house_data["houses"].items():
        for planet, deg in house_info["planets"]:
            planet_houses[planet] = (house_num, house_info["sign"])

    by_power = {level: [] for level in POWER_ORDER}
    planet_power = {}

    for planet in PLANETS:
        if planet not in planet_houses:
            continue

        house_num, sign = planet_houses[planet]
        power_level, reason = HOUSE_POWER.get(house_num, ("MODERATE", ""))

        by_power[power_level].append((planet, house_num, sign, reason))
        planet_power[planet] = (power_level, house_num, reason)

    return {
        "by_power": by_power,
        "planet_power": planet_power
    }
