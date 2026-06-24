# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Shame Avastha detection.
=========================
Detects Shame Avastha configurations - the WORST planetary state.
"""

from collections import defaultdict

from .constants import PLANETS, CRUEL_PLANETS
from .houses import get_planets_by_house
from core.chart_helpers import get_planet_sign_name, has_planet


def get_shame_avastha(chart):
    """
    Detect Shame Avastha configurations - the WORST planetary state.

    Shame Avastha Requirements:
    1. MINIMUM: 2+ planets with Rahu OR Ketu in same sign, OR planets in 5th house
    2. AND: At least one cruel planet (Mars, Saturn, Sun) must be present

    Key Rules:
    - Planet ALONE with Rahu/Ketu = NOT shamed (needs 2+ planets)
    - 2+ planets with Rahu/Ketu + one cruel = shame happens
    - Planets in 5th house + one cruel = shame happens
    - Cruel CAN shame another cruel (Saturn can shame Mars, etc.)
    - Rahu and Ketu BOTH cause shame (nodes, not planets - they cannot be shamed themselves)

    Args:
        chart: libaditya Chart object

    Returns:
        dict: {
            "rahu_conjunctions": [(sign, planets, shamed_planets, shamer), ...],
            "ketu_conjunctions": [(sign, planets, shamed_planets, shamer), ...],
            "fifth_house_shame": [(sign, planets, shamed_planets, shamer), ...] or None,
            "all_shamed": [(planet, sign, shamer, source), ...],
            "shame_pairs": set of (shamer, shamed) tuples,
            "has_shame": bool,
            "note": str
        }
    """
    rahu_conjunctions = []
    ketu_conjunctions = []
    fifth_house_shame = []
    all_shamed = []

    rahu_sign = None
    if has_planet(chart, "Rahu"):
        rahu_sign = get_planet_sign_name(chart, "Rahu")

    ketu_sign = None
    if has_planet(chart, "Ketu"):
        ketu_sign = get_planet_sign_name(chart, "Ketu")

    sign_planets = defaultdict(list)
    for planet in PLANETS:
        if has_planet(chart, planet):
            sign = get_planet_sign_name(chart, planet)
            if sign:
                sign_planets[sign].append(planet)

    # Check Rahu conjunctions (2+ planets with Rahu)
    if rahu_sign and rahu_sign in sign_planets:
        planets_with_rahu = sign_planets[rahu_sign]
        other_planets = [p for p in planets_with_rahu if p not in ["Rahu", "Ketu"]]

        if len(other_planets) >= 2:
            cruels_present = [p for p in other_planets if p in CRUEL_PLANETS]

            if cruels_present:
                all_targets = set()
                for cruel in cruels_present:
                    for target in other_planets:
                        if target != cruel:
                            all_targets.add(target)
                            all_shamed.append((target, rahu_sign, cruel, "Rahu conjunction"))
                rahu_conjunctions.append((rahu_sign, other_planets, list(all_targets), cruels_present[0]))

    # Check Ketu conjunctions (2+ planets with Ketu)
    if ketu_sign and ketu_sign in sign_planets:
        planets_with_ketu = sign_planets[ketu_sign]
        other_planets = [p for p in planets_with_ketu if p not in ["Rahu", "Ketu"]]

        if len(other_planets) >= 2:
            cruels_present = [p for p in other_planets if p in CRUEL_PLANETS]

            if cruels_present:
                all_targets = set()
                for cruel in cruels_present:
                    for target in other_planets:
                        if target != cruel:
                            if not any(s[0] == target and s[2] == cruel for s in all_shamed):
                                all_targets.add(target)
                                all_shamed.append((target, ketu_sign, cruel, "Ketu conjunction"))
                ketu_conjunctions.append((ketu_sign, other_planets, list(all_targets), cruels_present[0]))

    # Check 5th house shame (requires house data)
    house_data = get_planets_by_house(chart)
    note = None

    if house_data["houses"]:
        fifth_house = house_data["houses"].get(5, {})
        fifth_sign = fifth_house.get("sign")
        fifth_planets_raw = fifth_house.get("planets", [])
        fifth_planets = [p for p, _ in fifth_planets_raw]

        if len(fifth_planets) >= 2:
            cruels_in_5th = [p for p in fifth_planets if p in CRUEL_PLANETS]

            if cruels_in_5th:
                all_targets = set()
                for cruel in cruels_in_5th:
                    for target in fifth_planets:
                        if target != cruel and target not in ["Rahu", "Ketu"]:
                            if not any(s[0] == target and s[2] == cruel for s in all_shamed):
                                all_targets.add(target)
                                all_shamed.append((target, fifth_sign, cruel, "5th house"))
                if all_targets:
                    fifth_house_shame.append((fifth_sign, fifth_planets, list(all_targets), cruels_in_5th[0]))
    else:
        note = "5th house shame check unavailable (no birth time/house data)"

    # Build shame_pairs for cell-level display
    shame_pairs = set()
    for planet, sign, shamer, source in all_shamed:
        shame_pairs.add((shamer, planet))

    return {
        "rahu_conjunctions": rahu_conjunctions,
        "ketu_conjunctions": ketu_conjunctions,
        "fifth_house_shame": fifth_house_shame,
        "all_shamed": all_shamed,
        "shame_pairs": shame_pairs,
        "has_shame": len(all_shamed) > 0,
        "note": note
    }
