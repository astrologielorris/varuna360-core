#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Drishti Yuti Avastha — Aspect Relationship Table
=================================================
Augments the existing Graha Sphuta Drishti aspect table (from AI_aspects.py)
with planetary friendship coloring based on the Lajjitadi Avastha system.

Key concept:
    When planet A aspects planet B, the relationship is determined from B's
    perspective: what does B think of A?
    - B sees A as FRIEND  → A helps B (green / +)
    - B sees A as ENEMY   → A damages B (red / -)
    - B sees A as NEUTRAL → no effect (blue / ~)

This module does NOT duplicate aspect math — it reuses calculate_all_aspects()
from AI_aspects.py and adds relationship metadata on top.

Reference: docs/Lajitadi_lorris.csv for reference output comparison
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from AI_tools.analysis.AI_aspects import calculate_all_aspects, PLANETS, ASPECTING_PLANETS
from core.chart_helpers import (
    get_planet_sign_name, get_planet_in_sign_longitude, has_planet,
)

try:
    from core.aditya_data import check_planet_dignity, ADITYA_DIGNITIES
except ImportError:
    ADITYA_DIGNITIES = {}
    def check_planet_dignity(*args, **kwargs): return None


# ============================================================================
# LAJJITAADI AVASTHAS (6 conditions)
# ============================================================================
# "Lajjitaadi Avastha" means "ashamed, etc. condition."
# Reference: Ernst Wilhelm's Graha Sutras
#
# 1. LAJJITA "ashamed"
#    - A Graha in the 5th house conjunct Rahu/Ketu, Saturn or Mars.
#    - ✅ IMPLEMENTED: bold deep red row/column labels + SHAME on diagonal
#
# 2. GARVITA "proud"
#    - A Graha in exaltation or mulatrikona sign.
#    - ✅ IMPLEMENTED: diagonal cells (EX=60, MK=45, OH=30)
#
# 3. KSHUDHITA "starved"
#    - Saturn yuti always starves the conjunct planet.
#    - ✅ IMPLEMENTED: Saturn yuti → always 60- (override relationship)
#
# 4. TRISHITA "thirsty"
#    - A Graha standing in a water rasi and aspected by an enemy
#      with no auspicious Graha aspecting is said to be Trishita.
#    - Water signs (Aditya): Varuna, Vishnu, Parjanya
#    - (TODO: implement later — requires checking all aspects for benefic presence)
#
# 5. MUDITA "delighted"
#    - Positive contacts: friendly aspects, friendly yuti, Jupiter yuti (always).
#    - ✅ IMPLEMENTED: friendly contacts (+), Jupiter yuti always 60+
#
# 6. KSHOBHITA "agitated"
#    - Sun yuti always agitates the conjunct planet.
#    - If Sun is also a friend → both Kshobhita (-60) and Mudita (+60) apply.
#    - If Sun is enemy/neutral → only Kshobhita (-60).
#    - ✅ IMPLEMENTED: Sun yuti → 60- always, plus 60+ if friend (shown as ±)
#
# ============================================================================

# ============================================================================
# CONSTANTS (from Vedic tradition — Aditya Zodiac sign rulers)
# ============================================================================

# Sign Rulers — Aditya Zodiac names AND Tropical/Sidereal names (same planet assignments)
SIGN_RULERS = {
    # Aditya Zodiac sign rulers
    "Dhata": "Mars", "Aryama": "Venus", "Mitra": "Mercury", "Varuna": "Moon",
    "Indra": "Sun", "Vivasvan": "Mercury", "Tvasta": "Venus", "Vishnu": "Mars",
    "Amzu": "Jupiter", "Bhaga": "Saturn", "Pusha": "Saturn", "Parjanya": "Jupiter",
    # Tropical/Sidereal sign rulers (same planet assignments, used when sidereal mode active)
    "Aries": "Mars", "Taurus": "Venus", "Gemini": "Mercury", "Cancer": "Moon",
    "Leo": "Sun", "Virgo": "Mercury", "Libra": "Venus", "Scorpio": "Mars",
    "Sagittarius": "Jupiter", "Capricorn": "Saturn", "Aquarius": "Saturn", "Pisces": "Jupiter",
}

# Dignity VR values (diagonal cells: planet's strength in its own sign)
DIGNITY_VR = {
    "exaltation": 60,
    "mulatrikona": 45,
    "own_sign": 30
}

# Planetary Friendships & Enmities
# Reference: internal planetary-strengths research notes
PLANETARY_RELATIONSHIPS = {
    "Sun":     {"friends": ["Moon", "Mars", "Jupiter"], "neutral": ["Mercury"], "enemies": ["Venus", "Saturn"]},
    "Moon":    {"friends": ["Sun", "Mercury"], "neutral": ["Mars", "Jupiter", "Venus", "Saturn"], "enemies": []},
    "Mars":    {"friends": ["Sun", "Moon", "Jupiter"], "neutral": ["Venus", "Saturn"], "enemies": ["Mercury"]},
    "Mercury": {"friends": ["Sun", "Venus"], "neutral": ["Mars", "Jupiter", "Saturn"], "enemies": ["Moon"]},
    "Jupiter": {"friends": ["Sun", "Moon", "Mars"], "neutral": ["Saturn"], "enemies": ["Mercury", "Venus"]},
    "Venus":   {"friends": ["Mercury", "Saturn"], "neutral": ["Mars", "Jupiter"], "enemies": ["Sun", "Moon"]},
    "Saturn":  {"friends": ["Mercury", "Venus"], "neutral": ["Jupiter"], "enemies": ["Sun", "Moon", "Mars"]},
}


# ============================================================================
# CORE FUNCTIONS
# ============================================================================

def get_relationship(planet, other):
    """
    Get how `planet` views `other`.

    Args:
        planet: The planet whose perspective we're checking
        other: The other planet

    Returns:
        str: "FRIEND", "NEUTRAL", "ENEMY", or "N/A" (for Rahu/Ketu)
    """
    if planet not in PLANETARY_RELATIONSHIPS:
        return "N/A"  # Rahu/Ketu have no natural friendships

    rel = PLANETARY_RELATIONSHIPS[planet]
    if other in rel["friends"]:
        return "FRIEND"
    elif other in rel["enemies"]:
        return "ENEMY"
    else:
        return "NEUTRAL"


def get_drishti_yuti_data(chart):
    """
    Calculate Drishti Yuti data: aspect table augmented with relationships.

    For each aspect (A → B with X virupas), adds what B thinks of A.

    Also detects Yuti (conjunction): planets in the same Aditya sign.

    Args:
        chart: libaditya Chart object

    Returns:
        dict: {
            "aspects": list of augmented aspect records (with "relationship" field),
            "yuti_pairs": list of conjunction pairs with relationships,
            "lordship_pairs": list of sign lordship entries (ruler → planet),
            "matrix": dict of (aspecting, aspected) -> {virupas, relationship, is_yuti, is_lordship},
            "summary": {
                "friend_aspects": int,
                "enemy_aspects": int,
                "neutral_aspects": int,
                "yuti_count": int,
                "lordship_count": int
            }
        }
    """
    # Get all aspects from the existing calculator (threshold=0 to get everything)
    aspects_data = calculate_all_aspects(chart, threshold=0)

    # Build sign lookup for Yuti detection (Issue 12: via chart_data_adapter)
    sign_lookup = {}
    for planet in PLANETS:
        if has_planet(chart, planet):
            sign_lookup[planet] = get_planet_sign_name(chart, planet, default="")

    # Augment each aspect with relationship data
    augmented_aspects = []
    matrix = {}

    for asp in aspects_data["aspects"]:
        aspecting = asp["aspecting"]
        aspected = asp["aspected"]
        virupas = asp["virupas"]

        # What does the ASPECTED planet think of the ASPECTING planet?
        relationship = get_relationship(aspected, aspecting)

        augmented = dict(asp)
        augmented["relationship"] = relationship

        augmented_aspects.append(augmented)
        matrix[(aspecting, aspected)] = {
            "virupas": virupas,
            "relationship": relationship,
            "is_yuti": False,
            "is_lordship": False
        }

    # Detect Yuti (conjunction = same sign)
    # Special Lajjitaadi rules:
    #   Saturn yuti → always Kshudhita (starved) = 60- (ENEMY override)
    #   Sun yuti    → always Kshobhita (agitated) = 60-
    #                  BUT if friend → also Mudita = 60+ (dual: ±)
    #   Jupiter yuti → always Mudita (delighted) = 60+ (FRIEND override)
    yuti_pairs = []
    for i, p1 in enumerate(ASPECTING_PLANETS):
        for p2 in PLANETS:
            if p1 == p2:
                continue
            s1 = sign_lookup.get(p1, "")
            s2 = sign_lookup.get(p2, "")
            if s1 and s2 and s1 == s2:
                # Default: what does p2 think of p1?
                rel = get_relationship(p2, p1)
                is_dual = False
                avastha_names = []

                # Special yuti overrides
                if p1 == "Saturn":
                    # Kshudhita: Saturn always starves
                    rel = "ENEMY"
                    avastha_names = ["Kshudhita"]
                elif p1 == "Sun":
                    # Kshobhita: Sun always agitates
                    natural_rel = get_relationship(p2, p1)
                    if natural_rel == "FRIEND":
                        # Friend of Sun: both agitated AND delighted
                        is_dual = True
                        rel = "DUAL"
                        avastha_names = ["Kshobhita", "Mudita"]
                    else:
                        # Enemy/neutral of Sun: only agitated
                        rel = "ENEMY"
                        avastha_names = ["Kshobhita"]
                elif p1 == "Jupiter":
                    # Mudita: Jupiter always delights
                    rel = "FRIEND"
                    avastha_names = ["Mudita"]
                else:
                    # Normal yuti: use natural relationship
                    if rel == "FRIEND":
                        avastha_names = ["Mudita"]

                yuti_pairs.append({
                    "planet_a": p1,
                    "planet_b": p2,
                    "sign": s1,
                    "relationship": rel,
                    "avastha_names": avastha_names
                })
                matrix[(p1, p2)] = {
                    "virupas": 60,
                    "relationship": rel,
                    "is_yuti": True,
                    "is_lordship": False,
                    "is_dual": is_dual,
                    "avastha_names": avastha_names
                }

    # Detect Sign Lordship (sign ruler has full authority over planets in its sign)
    lordship_pairs = []
    for planet in ASPECTING_PLANETS:
        sign = sign_lookup.get(planet, "")
        if not sign or sign not in SIGN_RULERS:
            continue
        ruler = SIGN_RULERS[sign]
        if ruler == planet:
            continue  # Own sign — skip (diagonal cell)
        # Ruler has lordship over planet → what does planet think of ruler?
        rel = get_relationship(planet, ruler)
        lordship_pairs.append({
            "planet": planet,
            "sign": sign,
            "ruler": ruler,
            "relationship": rel
        })
        # Override matrix cell: ruler → planet = 60.0 (full authority)
        # Only override if lordship is stronger than existing aspect
        existing = matrix.get((ruler, planet))
        if existing is None or existing["virupas"] < 60:
            matrix[(ruler, planet)] = {
                "virupas": 60,
                "relationship": rel,
                "is_yuti": False,
                "is_lordship": True
            }

    # Detect Dignity (diagonal cells: EX=60, MK=45, OH=30)
    dignity_data = {}  # planet -> {"type": str, "virupas": int}
    for planet in ASPECTING_PLANETS:
        if not has_planet(chart, planet) or planet not in ADITYA_DIGNITIES:
            continue
        sign_name = get_planet_sign_name(chart, planet, default="")
        deg_in_sign = get_planet_in_sign_longitude(chart, planet)
        dignity = check_planet_dignity(planet, sign_name, deg_in_sign)
        if dignity and dignity in DIGNITY_VR:
            dignity_data[planet] = {
                "type": dignity,
                "virupas": DIGNITY_VR[dignity]
            }

    # Detect Lajjita (shame) avastha
    # Lazy import to avoid circular dependency (AI_main imports avastha)
    from AI_tools.AI_main_function.shame import get_shame_avastha
    shame_data = get_shame_avastha(chart)
    shamed_planets = set()
    shame_pairs = set()  # (shamer, shamed) tuples for cell-level display
    if shame_data["has_shame"]:
        for planet, sign, shamer, source in shame_data["all_shamed"]:
            shamed_planets.add(planet)
        shame_pairs = shame_data.get("shame_pairs", set())

    # Summary counts (only count aspects with virupas > 0, yuti, or lordship)
    friend_count = 0
    enemy_count = 0
    neutral_count = 0
    yuti_count = 0
    lordship_count = 0

    for key, val in matrix.items():
        if val["is_yuti"]:
            yuti_count += 1
            if val["relationship"] == "DUAL":
                friend_count += 1  # Mudita
                enemy_count += 1   # Kshobhita
            elif val["relationship"] == "FRIEND":
                friend_count += 1
            elif val["relationship"] == "ENEMY":
                enemy_count += 1
            elif val["relationship"] == "NEUTRAL":
                neutral_count += 1
        elif val.get("is_lordship"):
            lordship_count += 1
            if val["relationship"] == "FRIEND":
                friend_count += 1
            elif val["relationship"] == "ENEMY":
                enemy_count += 1
            elif val["relationship"] == "NEUTRAL":
                neutral_count += 1
        elif val["virupas"] > 0:
            if val["relationship"] == "FRIEND":
                friend_count += 1
            elif val["relationship"] == "ENEMY":
                enemy_count += 1
            elif val["relationship"] == "NEUTRAL":
                neutral_count += 1

    return {
        "aspects": augmented_aspects,
        "yuti_pairs": yuti_pairs,
        "lordship_pairs": lordship_pairs,
        "dignity_data": dignity_data,
        "shamed_planets": shamed_planets,
        "shame_pairs": shame_pairs,
        "shame_data": shame_data,
        "matrix": matrix,
        "summary": {
            "friend_aspects": friend_count,
            "enemy_aspects": enemy_count,
            "neutral_aspects": neutral_count,
            "yuti_count": yuti_count,
            "lordship_count": lordship_count
        }
    }


# ============================================================================
# ANSI COLOR SUPPORT
# ============================================================================

def _supports_color():
    """Check if terminal supports ANSI colors."""
    if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
        return False
    return os.environ.get("TERM", "") != "dumb"


# ANSI codes
_GREEN = "\033[32m"
_RED = "\033[31m"
_BLUE = "\033[34m"
_BOLD = "\033[1m"
_DEEP_RED_BOLD = "\033[1;91m"  # Bold + bright red for Lajjita (shame)
_MAGENTA_BOLD = "\033[1;35m"  # Bold magenta for Garvita (proud/dignified)
_RESET = "\033[0m"


def _colorize(text, relationship, use_colors):
    """Apply ANSI color based on relationship."""
    if not use_colors:
        return text
    if relationship == "FRIEND":
        return f"{_GREEN}{text}{_RESET}"
    elif relationship == "ENEMY":
        return f"{_RED}{text}{_RESET}"
    elif relationship == "NEUTRAL":
        return f"{_BLUE}{text}{_RESET}"
    elif relationship == "DUAL":
        # Yellow for dual (both positive and negative)
        return f"\033[33m{text}{_RESET}"
    elif relationship == "PROUD":
        return f"{_MAGENTA_BOLD}{text}{_RESET}"
    elif relationship == "SHAME":
        return f"{_DEEP_RED_BOLD}{text}{_RESET}"
    return text


# ============================================================================
# TABLE FORMATTING
# ============================================================================

REL_SYMBOL = {"FRIEND": "+", "ENEMY": "-", "NEUTRAL": "~", "DUAL": "\u00b1", "N/A": " "}

SHORT_NAMES = {
    "Sun": "Sun", "Moon": "Moon", "Mars": "Mars*", "Mercury": "Merc",
    "Jupiter": "Jupi*", "Venus": "Venu", "Saturn": "Satu*",
    "Rahu": "Rahu", "Ketu": "Ketu"
}


def format_drishti_yuti_table(chart, person_name="", use_colors=None,
                              show_signs=False):
    """
    Format a Drishti Yuti Avastha matrix table.

    Each cell shows: virupas + relationship symbol (+ / - / ~)
    Yuti (conjunction) shown as Y+ / Y- / Y~.
    Strong aspects (>= 45 VR) marked with !.

    Args:
        chart: libaditya Chart object
        person_name: Chart name for header
        use_colors: None=auto-detect, True=force, False=disable
        show_signs: If True, add a SIGN row showing each planet's Aditya sign

    Returns:
        str: Formatted table string
    """
    if use_colors is None:
        use_colors = _supports_color()

    data = get_drishti_yuti_data(chart)
    matrix = data["matrix"]
    dignity_data = data["dignity_data"]
    shamed_planets = data["shamed_planets"]
    shame_pairs = data.get("shame_pairs", set())
    summary = data["summary"]

    lines = []
    lines.append("")
    lines.append("DRISHTI YUTI AVASTHA (Aspect Relationships)" +
                 (f": {person_name}" if person_name else ""))

    # ── Box-drawing table ──
    # Cell width: 8 chars content (was 7, +1 for shame ! marker), label column: 9 chars
    CW = 8   # cell width
    LW = 9   # label width
    n_cols = len(ASPECTING_PLANETS)

    # Build cell content helper
    def _cell(aspecting, aspected):
        """Return (text, relationship_or_None) for a cell."""
        if aspecting == aspected:
            # Diagonal: dignity only (shame is independent)
            dig = dignity_data.get(aspecting)
            if dig:
                return (f"{dig['virupas']:>5.1f}  ", "PROUD")
            else:
                return ("    -   ", None)
        entry = matrix.get((aspecting, aspected))
        if entry is None:
            return ("    .   ", None)

        # Get base virupas and relationship symbol
        if entry["is_yuti"]:
            vr = 60.0
            sym = REL_SYMBOL.get(entry["relationship"], " ")
            rel = entry["relationship"]
        else:
            vr = entry["virupas"]
            if vr <= 0:
                return ("    .   ", None)
            sym = REL_SYMBOL.get(entry["relationship"], " ")
            rel = entry["relationship"]

        # Check if this is a shame pair (shamer→shamed)
        if (aspecting, aspected) in shame_pairs:
            # Override neutral/N/A to enemy (shame overrides neutral)
            if rel in ("NEUTRAL", "N/A"):
                sym = "-"
            text = f"{vr:>5.1f}{sym}!"
            return (f"{text} ", "SHAME")

        text = f"{vr:>5.1f}{sym} "
        return (f"{text} ", rel)

    # Unicode box-drawing characters
    TL, TR, BL, BR = "\u250c", "\u2510", "\u2514", "\u2518"
    H, V = "\u2500", "\u2502"
    TJ, BJ, LJ, RJ, X = "\u252c", "\u2534", "\u251c", "\u2524", "\u253c"

    h_label = H * LW
    h_cell = H * CW

    # Top border
    top = TL + h_label + (TJ + h_cell) * n_cols + TR
    lines.append(top)

    # Header row
    header = V + " " * LW + V
    for p in ASPECTING_PLANETS:
        name = f"{SHORT_NAMES[p]:^{CW}}"
        if use_colors and p in shamed_planets:
            header += f"{_DEEP_RED_BOLD}{name}{_RESET}"
        else:
            header += name
        header += V
    lines.append(header)

    # Separator after header
    sep = LJ + h_label + (X + h_cell) * n_cols + RJ
    lines.append(sep)

    # Data rows
    for aspecting in ASPECTING_PLANETS:
        label = f" {SHORT_NAMES[aspecting]:<{LW - 1}}"
        if use_colors and aspecting in shamed_planets:
            row = V + f"{_DEEP_RED_BOLD}{label}{_RESET}" + V
        else:
            row = V + label + V
        for aspected in ASPECTING_PLANETS:
            text, rel = _cell(aspecting, aspected)
            if rel and use_colors:
                row += _colorize(text, rel, use_colors)
            else:
                row += text
            row += V
        lines.append(row)

    # Separator before totals
    lines.append(sep)

    # Bottom totals row
    totals_label = f" {'TOTAL':<{LW - 1}}"
    totals_row = V + totals_label + V
    for aspected in ASPECTING_PLANETS:
        col_total = 0.0
        dig = dignity_data.get(aspected)
        if dig:
            col_total += dig["virupas"]
        for aspecting in ASPECTING_PLANETS:
            if aspecting == aspected:
                continue
            entry = matrix.get((aspecting, aspected))
            if entry and entry["virupas"] > 0:
                # Check shame: shame always subtracts -60
                if (aspecting, aspected) in shame_pairs:
                    col_total -= 60
                elif entry["relationship"] == "DUAL":
                    pass
                elif entry["relationship"] == "FRIEND":
                    col_total += entry["virupas"]
                elif entry["relationship"] == "ENEMY":
                    col_total -= entry["virupas"]
        totals_row += f"{col_total:>7.0f} " + V
    lines.append(totals_row)

    # Optional SIGN row (after TOTAL, before bottom border)
    if show_signs:
        lines.append(sep)
        sign_label = f" {'SIGN':<{LW - 1}}"
        sign_row = V + sign_label + V
        for planet in ASPECTING_PLANETS:
            sign = get_planet_sign_name(chart, planet, default="?")
            sign_row += f"{sign:^{CW}}" + V
        lines.append(sign_row)

    # Bottom border
    bottom = BL + h_label + (BJ + h_cell) * n_cols + BR
    lines.append(bottom)

    # Legend
    lines.append("* = Special aspects (Mars: 4/8, Jupiter: 5/9, Saturn: 3/10)")
    lines.append("+ Friend (green)  - Enemy (red)  ~ Neutral (blue)  \u00b1 Dual (yellow)")
    lines.append("60.0 = Yuti/Lordship   Diagonal: EX=60 MK=45 OH=30 (magenta = proud)")
    lines.append("! = Lajjita shame (deep red bold)   Bold red labels = shamed planet")
    lines.append("Direction: A row \u2192 B column = what B thinks of A")
    lines.append("")

    # Summary line
    parts = []
    if summary["friend_aspects"] > 0:
        txt = f"{summary['friend_aspects']} friendly"
        parts.append(_colorize(txt, "FRIEND", use_colors))
    if summary["enemy_aspects"] > 0:
        txt = f"{summary['enemy_aspects']} hostile"
        parts.append(_colorize(txt, "ENEMY", use_colors))
    if summary["neutral_aspects"] > 0:
        txt = f"{summary['neutral_aspects']} neutral"
        parts.append(_colorize(txt, "NEUTRAL", use_colors))
    if summary["yuti_count"] > 0:
        parts.append(f"{summary['yuti_count']} yuti")
    if summary["lordship_count"] > 0:
        parts.append(f"{summary['lordship_count']} lordship")

    if parts:
        lines.append("Summary: " + ", ".join(parts))
    lines.append("")

    return "\n".join(lines)


def format_shame_table(chart, person_name="", use_colors=None):
    """
    Format a standalone Shame Avastha table for console output.

    Shows which planets are shamed, in which sign/house, by whom, and why.
    Uses Unicode box-drawing borders matching the Drishti Yuti table style.

    Args:
        chart: libaditya Chart object
        person_name: Chart name for header
        use_colors: None=auto-detect, True=force, False=disable

    Returns:
        str: Formatted shame table string
    """
    if use_colors is None:
        use_colors = _supports_color()

    from .shame import get_shame_avastha
    from .houses import get_planets_by_house

    shame_data = get_shame_avastha(chart)
    house_data = get_planets_by_house(chart)

    lines = []
    lines.append("")
    header = "SHAME AVASTHA" + (f": {person_name}" if person_name else "")
    if use_colors:
        lines.append(f"{_DEEP_RED_BOLD}{header}{_RESET}")
    else:
        lines.append(header)

    if not shame_data["has_shame"]:
        lines.append("No shame configurations detected.")
        if shame_data.get("note"):
            lines.append(f"Note: {shame_data['note']}")
        lines.append("")
        return "\n".join(lines)

    # Build sign -> house lookup
    sign_to_house = {}
    if house_data["houses"]:
        for h_num, h_info in house_data["houses"].items():
            sign_to_house[h_info["sign"]] = h_num

    # Column widths
    CW_planet = 10
    CW_sign = 10
    CW_house = 8
    CW_shamer = 10
    CW_source = 20

    # Unicode box-drawing
    TL, TR, BL, BR = "\u250c", "\u2510", "\u2514", "\u2518"
    H, V = "\u2500", "\u2502"
    TJ, BJ, LJ, RJ, X = "\u252c", "\u2534", "\u251c", "\u2524", "\u253c"

    cols = [CW_planet, CW_sign, CW_house, CW_shamer, CW_source]
    top = TL + TJ.join(H * w for w in cols) + TR
    sep = LJ + X.join(H * w for w in cols) + RJ
    bot = BL + BJ.join(H * w for w in cols) + BR

    lines.append(top)
    # Header row
    hdr = V + f"{'Planet':^{CW_planet}}" + V + f"{'Sign':^{CW_sign}}" + V
    hdr += f"{'House':^{CW_house}}" + V + f"{'Shamer':^{CW_shamer}}" + V
    hdr += f"{'Source':^{CW_source}}" + V
    lines.append(hdr)
    lines.append(sep)

    # Data rows
    for planet, sign, shamer, source in shame_data["all_shamed"]:
        house_str = str(sign_to_house.get(sign, "?"))
        row = V + f"{planet:^{CW_planet}}" + V + f"{sign:^{CW_sign}}" + V
        row += f"{house_str:^{CW_house}}" + V + f"{shamer:^{CW_shamer}}" + V
        row += f"{source:^{CW_source}}" + V
        if use_colors:
            row = f"{_DEEP_RED_BOLD}{row}{_RESET}"
        lines.append(row)

    lines.append(bot)

    # Summary
    shamed_set = set(p for p, _, _, _ in shame_data["all_shamed"])
    sources = set(s for _, _, _, s in shame_data["all_shamed"])
    lines.append(f"{len(shamed_set)} shamed planets | {len(sources)} sources | {len(shame_data['all_shamed'])} instances")

    if shame_data.get("note"):
        lines.append(f"Note: {shame_data['note']}")

    lines.append("")
    return "\n".join(lines)
