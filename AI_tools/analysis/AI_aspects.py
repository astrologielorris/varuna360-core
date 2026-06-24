#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
AI Aspects - Vedic Planetary Aspect Calculator (Graha Sphuta Drishti)
======================================================================
Calculate planetary aspects using the Graha Sphuta Drishti system from
Graha Sutras. Output aspect strength in Virupas (0-60 scale, where 60 = full aspect).

Key Concept: Graha Sutras Aspect System
---------------------------------------
Unlike Western astrology orb-based aspects, Vedic aspects use CONTINUOUS
STRENGTH CURVES based on exact degree distance:

- ALL planets cast aspects, but strength varies by angular distance
- Mars, Jupiter, Saturn have SPECIAL aspect curves (enhanced at certain angles)
- Aspect strength measured in Virupas (60 VR = 1 Rupa = Full Aspect)
- Formulas derived from pages 54-67 of Graha Sutras

Usage:
    # From CHTK file:
    python AI_tools/analysis/AI_aspects.py path/to/chart.chtk
    python AI_tools/analysis/AI_aspects.py                    # Uses Lorris.chtk

    # Output formats:
    python AI_tools/analysis/AI_aspects.py --list             # List format (sorted by strength)
    python AI_tools/analysis/AI_aspects.py --strong           # Only aspects > 30 VR
    python AI_tools/analysis/AI_aspects.py --full             # Include interpretations
    python AI_tools/analysis/AI_aspects.py --json             # JSON output

    # From birthdate + coordinates:
    python AI_tools/analysis/AI_aspects.py --date 1991-02-22 --time 10:30 --lat 48.98 --lon 2.27

Special Aspects:
    - Mars:    Full (60 VR) at 90° (4th house) and 210° (8th house)
    - Jupiter: Full (60 VR) at 120° (5th house) and 240° (9th house)
    - Saturn:  Full (60 VR) at 60° (3rd house) and 270° (10th house)
    - All:     Full (60 VR) at 180° (opposition/7th house)
"""

import sys
import os
import argparse
import json
from collections import defaultdict

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.chtk_reader import CHTKReader
from core.time_utils import (
    invert_chtk_timezone,
    local_to_utc,
    local_to_utc_total,
    resolve_total_offset,
)
from core.chart_helpers import (
    get_planet_sign_name, get_planet_decimal_degrees, has_planet,
)

# Default CHTK file
DEFAULT_CHTK = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "Lorris.chtk")

# All planets (including nodes for receiving aspects)
PLANETS = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"]

# Planets that CAST aspects (Rahu/Ketu are shadow planets - they only RECEIVE aspects)
ASPECTING_PLANETS = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]

# Planets with special aspects
SPECIAL_ASPECT_PLANETS = {"Mars", "Jupiter", "Saturn"}


# ============================================================================
# ASPECT STRENGTH FORMULAS (from Graha Sutras Tables 1-4)
# ============================================================================

def calculate_general_aspect(diff_degrees: float) -> float:
    """
    Calculate aspect strength for general planets (Sun, Moon, Mercury, Venus, Rahu, Ketu).

    Based on Graha Sutras Table 1 - continuous strength curve.

    Args:
        diff_degrees: Angular distance (0-360) from aspecting to aspected planet

    Returns:
        Virupas (0-60 strength value)
    """
    # Normalize to 0-360
    diff = diff_degrees % 360

    # Apply formulas based on degree range (from Graha Sutras Table 1)
    if diff < 30:
        # 0-30°: No aspect
        return 0
    elif diff < 60:
        # 30-60°: Linear rise from 0 to 15 VR
        # Formula: (diff - 30) / 2
        return (diff - 30) / 2
    elif diff < 90:
        # 60-90°: Rise from 15 to 45 VR
        # Formula: (diff - 60) + 15
        return (diff - 60) + 15
    elif diff < 120:
        # 90-120°: Descent from 45 to 30 VR
        # Formula: ((120 - diff) / 2) + 30
        return ((120 - diff) / 2) + 30
    elif diff < 150:
        # 120-150°: Descent from 30 to 0 VR
        # Formula: 150 - diff
        return 150 - diff
    elif diff < 180:
        # 150-180°: Rise from 0 to 60 VR (approaching opposition)
        # Formula: (diff - 150) * 2
        return (diff - 150) * 2
    elif diff < 300:
        # 180-300°: Descent from 60 to 0 VR
        # Formula: (300 - diff) / 2
        return (300 - diff) / 2
    else:
        # 300-360°: No aspect
        return 0


def calculate_mars_aspect(diff_degrees: float) -> float:
    """
    Calculate aspect strength for Mars (special full aspects at 4th and 8th houses).

    Mars has SPECIAL aspects at:
    - 90° (4th house): Full 60 VR
    - 180° (7th house): Full 60 VR (standard opposition)
    - 210° (8th house): Full 60 VR (plateau from 180-210°)

    Based on Graha Sutras Table 2.

    Args:
        diff_degrees: Angular distance (0-360) from Mars to aspected planet

    Returns:
        Virupas (0-60 strength value)
    """
    diff = diff_degrees % 360

    if diff < 30:
        return 0
    elif diff < 60:
        # 30-60°: Same as general - linear rise to 15 VR
        return (diff - 30) / 2
    elif diff < 90:
        # 60-90°: SPECIAL - steep rise to 60 VR at 90°
        # Modified formula to reach 60 at 90°
        return ((diff - 60) * 1.5) + 15
    elif diff < 120:
        # 90-120°: SPECIAL - descent from 60 VR
        # Formula: 60 - (diff - 90)
        return 60 - (diff - 90)
    elif diff < 150:
        # 120-150°: Same as general - descent to 0
        return 150 - diff
    elif diff < 180:
        # 150-180°: Same as general - rise to 60 VR
        return (diff - 150) * 2
    elif diff < 210:
        # 180-210°: SPECIAL - Full aspect plateau (60 VR)
        return 60
    elif diff < 240:
        # 210-240°: SPECIAL - descent from 60 VR
        # Formula: 60 - (diff - 210)
        return 60 - (diff - 210)
    elif diff < 300:
        # 240-300°: Same as general
        return (300 - diff) / 2
    else:
        return 0


def calculate_jupiter_aspect(diff_degrees: float) -> float:
    """
    Calculate aspect strength for Jupiter (special full aspects at 5th and 9th houses).

    Jupiter has SPECIAL aspects at:
    - 120° (5th house): Full 60 VR
    - 180° (7th house): Full 60 VR (standard opposition)
    - 240° (9th house): Full 60 VR

    Based on Graha Sutras Table 3.

    Args:
        diff_degrees: Angular distance (0-360) from Jupiter to aspected planet

    Returns:
        Virupas (0-60 strength value)
    """
    diff = diff_degrees % 360

    if diff < 30:
        return 0
    elif diff < 60:
        # Same as general
        return (diff - 30) / 2
    elif diff < 90:
        # Same as general
        return (diff - 60) + 15
    elif diff < 120:
        # 90-120°: SPECIAL - rise from 45 to 60 VR
        # Formula: ((diff - 90) / 2) + 45
        return ((diff - 90) / 2) + 45
    elif diff < 150:
        # 120-150°: SPECIAL - descent from 60 VR
        # Formula: 60 - ((diff - 120) * 2)
        return 60 - ((diff - 120) * 2)
    elif diff < 180:
        # Same as general
        return (diff - 150) * 2
    elif diff < 210:
        # 180-210°: Descending from opposition
        return (300 - diff) / 2
    elif diff < 240:
        # 210-240°: SPECIAL - rise to 60 VR at 240°
        # Formula: ((diff - 210) / 2) + 45
        return ((diff - 210) / 2) + 45
    elif diff < 270:
        # 240-270°: SPECIAL - descent from 60 VR
        # Formula: 60 - ((diff - 240) * 1.5)
        excess = diff - 240
        return 60 - (excess * 1.5)
    elif diff < 300:
        # Same as general
        return (300 - diff) / 2
    else:
        return 0


def calculate_saturn_aspect(diff_degrees: float) -> float:
    """
    Calculate aspect strength for Saturn (special full aspects at 3rd and 10th houses).

    Saturn has SPECIAL aspects at:
    - 60° (3rd house): Full 60 VR
    - 180° (7th house): Full 60 VR (standard opposition)
    - 270° (10th house): Full 60 VR

    Based on Graha Sutras Table 4.

    Args:
        diff_degrees: Angular distance (0-360) from Saturn to aspected planet

    Returns:
        Virupas (0-60 strength value)
    """
    diff = diff_degrees % 360

    if diff < 30:
        return 0
    elif diff < 60:
        # 30-60°: SPECIAL - steep rise to 60 VR at 60°
        # Formula: (diff - 30) * 2
        return (diff - 30) * 2
    elif diff < 90:
        # 60-90°: SPECIAL - descent from 60 VR
        # Formula: 60 - ((diff - 60) / 2)
        return 60 - ((diff - 60) / 2)
    elif diff < 120:
        # Same as general
        return ((120 - diff) / 2) + 30
    elif diff < 150:
        # Same as general
        return 150 - diff
    elif diff < 180:
        # Same as general
        return (diff - 150) * 2
    elif diff < 240:
        # 180-240°: Descending from opposition
        return (300 - diff) / 2
    elif diff < 270:
        # 240-270°: SPECIAL - rise to 60 VR at 270°
        # Formula: (diff - 240) + 30
        return (diff - 240) + 30
    elif diff < 300:
        # 270-300°: SPECIAL - descent from 60 VR
        # Formula: (300 - diff) * 2
        return (300 - diff) * 2
    else:
        return 0


def get_aspect_calculator(planet_name: str):
    """
    Get the appropriate aspect calculation function for a planet.

    Args:
        planet_name: Name of the aspecting planet

    Returns:
        Function to calculate aspect strength
    """
    if planet_name == "Mars":
        return calculate_mars_aspect
    elif planet_name == "Jupiter":
        return calculate_jupiter_aspect
    elif planet_name == "Saturn":
        return calculate_saturn_aspect
    else:
        return calculate_general_aspect


# ============================================================================
# ASPECT CLASSIFICATION
# ============================================================================

def classify_aspect(diff_degrees: float, aspecting_planet: str) -> tuple:
    """
    Classify an aspect by type (conjunction, square, trine, opposition, etc.)
    and indicate if it's a special aspect.

    Args:
        diff_degrees: Angular distance
        aspecting_planet: Name of the aspecting planet

    Returns:
        Tuple: (aspect_name, is_special)
    """
    diff = diff_degrees % 360

    # Determine aspect type based on angular distance
    if diff < 15 or diff > 345:
        return ("Conjunction", False)
    elif 45 <= diff <= 75:
        # 60° region
        if aspecting_planet == "Saturn" and 55 <= diff <= 65:
            return ("3rd house (Saturn)", True)
        return ("Sextile", False)
    elif 75 <= diff <= 105:
        # 90° region
        if aspecting_planet == "Mars" and 85 <= diff <= 95:
            return ("4th house (Mars)", True)
        return ("Square", False)
    elif 105 <= diff <= 135:
        # 120° region
        if aspecting_planet == "Jupiter" and 115 <= diff <= 125:
            return ("5th house (Jupiter)", True)
        return ("Trine", False)
    elif 165 <= diff <= 195:
        # 180° region - all planets have full opposition
        return ("Opposition", False)
    elif 195 <= diff <= 225:
        # 210° region
        if aspecting_planet == "Mars" and 205 <= diff <= 215:
            return ("8th house (Mars)", True)
        return ("Post-opposition", False)
    elif 225 <= diff <= 255:
        # 240° region
        if aspecting_planet == "Jupiter" and 235 <= diff <= 245:
            return ("9th house (Jupiter)", True)
        return ("Sesquiquadrate", False)
    elif 255 <= diff <= 285:
        # 270° region
        if aspecting_planet == "Saturn" and 265 <= diff <= 275:
            return ("10th house (Saturn)", True)
        return ("Contra-square", False)
    else:
        return ("General aspect", False)


# ============================================================================
# MAIN ASPECT CALCULATION
# ============================================================================

def calculate_all_aspects(chart, threshold: float = 0) -> dict:
    """
    Calculate all planetary aspects for a chart.

    Args:
        chart: libaditya Chart object
        threshold: Minimum Virupas to include in results (default: 0 = include all)

    Returns:
        dict: {
            "aspects": list of aspect records,
            "by_planet": dict of aspects organized by planet,
            "strongest_aspects": list of top 5 aspects by virupas,
            "mutual_aspects": list of mutual aspect pairs
        }
    """
    aspects = []
    by_planet = defaultdict(lambda: {"aspects_cast": [], "aspects_received": []})

    # Get positions of all planets (Issue 12: Chart or dict via adapter)
    positions = {}
    for planet in PLANETS:
        if has_planet(chart, planet):
            positions[planet] = get_planet_decimal_degrees(chart, planet)

    # Calculate aspects between all planet pairs
    # Note: Only real planets cast aspects (Rahu/Ketu are shadow planets - receive only)
    for aspecting in ASPECTING_PLANETS:
        if aspecting not in positions:
            continue

        asp_pos = positions[aspecting]
        calc_func = get_aspect_calculator(aspecting)

        for aspected in PLANETS:
            if aspected not in positions or aspected == aspecting:
                continue

            # Calculate angular distance (aspecting → aspected)
            distance = (positions[aspected] - asp_pos) % 360
            virupas = calc_func(distance)

            # Skip if below threshold
            if virupas < threshold:
                continue

            # Classify the aspect
            aspect_type, is_special = classify_aspect(distance, aspecting)

            aspect_record = {
                "aspecting": aspecting,
                "aspected": aspected,
                "distance": round(distance, 2),
                "virupas": round(virupas, 2),
                "strength_pct": round((virupas / 60) * 100, 1),
                "is_special": is_special,
                "aspect_type": aspect_type
            }

            aspects.append(aspect_record)
            by_planet[aspecting]["aspects_cast"].append(aspect_record)
            by_planet[aspected]["aspects_received"].append(aspect_record)

    # Find strongest aspects (top 5)
    strongest = sorted(aspects, key=lambda x: -x["virupas"])[:5]

    # Find mutual aspects (both planets aspect each other significantly)
    mutual_aspects = []
    seen_pairs = set()

    for asp in aspects:
        if asp["virupas"] < 30:  # Only consider significant aspects
            continue

        pair_key = tuple(sorted([asp["aspecting"], asp["aspected"]]))
        if pair_key in seen_pairs:
            continue

        # Find the reverse aspect
        reverse = None
        for asp2 in aspects:
            if asp2["aspecting"] == asp["aspected"] and asp2["aspected"] == asp["aspecting"]:
                reverse = asp2
                break

        if reverse and reverse["virupas"] >= 30:
            seen_pairs.add(pair_key)
            mutual_aspects.append({
                "planet_a": asp["aspecting"],
                "planet_b": asp["aspected"],
                "a_to_b": asp["virupas"],
                "b_to_a": reverse["virupas"],
                "combined": round(asp["virupas"] + reverse["virupas"], 2)
            })

    # Sort mutual aspects by combined strength
    mutual_aspects.sort(key=lambda x: -x["combined"])

    return {
        "aspects": aspects,
        "by_planet": dict(by_planet),
        "strongest_aspects": strongest,
        "mutual_aspects": mutual_aspects
    }


# ============================================================================
# CHART LOADING (same pattern as AI_main.py)
# ============================================================================

def parse_dms_to_decimal(dms_str):
    """Parse DMS string like '44n29' or '73w12' to decimal degrees."""
    import re

    if not dms_str:
        return 0.0

    dms_str = dms_str.strip().lower()
    match = re.match(r'(\d+)([nsew])(\d*)', dms_str)
    if not match:
        return 0.0

    degrees = int(match.group(1))
    direction = match.group(2)
    minutes = int(match.group(3)) if match.group(3) else 0

    decimal = degrees + (minutes / 60.0)

    if direction in ['s', 'w']:
        decimal = -decimal

    return decimal


def extract_from_chtk(chtk_path):
    """Extract planet data from CHTK file."""
    reader = CHTKReader()
    chtk_data = reader.read_chtk_file(chtk_path)

    year = chtk_data['year']
    month = chtk_data['month']
    day = chtk_data['day']
    hour = chtk_data['hour']
    minute = chtk_data['minute']
    second = chtk_data['second']

    coords = chtk_data['coordinates']
    lat = coords['latitude']
    lon = coords['longitude']

    if lat == 0.0 and 'latitude_dms' in coords:
        lat = parse_dms_to_decimal(coords['latitude_dms'])
    if lon == 0.0 and 'longitude_dms' in coords:
        lon = parse_dms_to_decimal(coords['longitude_dms'])

    # Parse timezone from CHTK
    tz_raw = chtk_data['timezone']
    time_change = int(chtk_data['time_change_flag'])

    if '/' in tz_raw:
        # IANA name in CHTK field: STANDARD sign, never CHTK-inverted. Do NOT invert.
        # chtk_reader passes pure IANA names through already sign-stripped; no manual
        # sign-strip parsing here (it would trip the W7 completeness grep).
        std_hours, _ = resolve_total_offset(tz_raw, year, month, day)  # errors propagate loudly
        total = std_hours + (time_change if time_change in (1, 2) else 0)
        utc = local_to_utc_total(year, month, day, hour, minute, second, total)
    else:
        # Input convention: RAW CHTK (inverted sign)
        std_str = invert_chtk_timezone(tz_raw)
        utc = local_to_utc(year, month, day, hour, minute, second, std_str, time_change)
    utc_year, utc_month, utc_day, utc_hour, utc_minute, utc_second = utc

    from core.chart_factory import build_chart_from_params
    from libaditya import swe
    hour_decimal = utc_hour + utc_minute / 60.0 + utc_second / 3600.0
    jd = swe.julday(utc_year, utc_month, utc_day, hour_decimal)
    chart = build_chart_from_params(jd=jd, lat=lat, lon=lon, mode="aditya", ayanamsa=1)

    return chart, chtk_data['name']


def extract_from_datetime(date_str, time_str, lat, lon):
    """Extract planet data from date/time and coordinates."""
    date_parts = date_str.split('-')
    year = int(date_parts[0])
    month = int(date_parts[1])
    day = int(date_parts[2])

    if time_str:
        time_parts = time_str.split(':')
        hour = int(time_parts[0])
        minute = int(time_parts[1]) if len(time_parts) > 1 else 0
    else:
        hour = 12
        minute = 0

    from core.chart_factory import build_chart_from_params
    from libaditya import swe
    hour_decimal = hour + minute / 60.0
    jd = swe.julday(year, month, day, hour_decimal)
    chart = build_chart_from_params(jd=jd, lat=lat, lon=lon, mode="aditya", ayanamsa=1)

    name = f"Chart for {date_str}"
    if time_str:
        name += f" {time_str}"
    name += f" @ ({lat:.2f}, {lon:.2f})"

    return chart, name


# ============================================================================
# OUTPUT FORMATTING
# ============================================================================

def format_table_output(person_name: str, aspects_data: dict, planets_data: dict,
                        show_full: bool = False, chart=None) -> str:
    """
    Format aspects as a matrix table.

    Args:
        person_name: Name of the chart
        aspects_data: Result from calculate_all_aspects()
        planets_data: Original planets data (for positions)
        show_full: Include interpretations

    Returns:
        Formatted string
    """
    lines = []
    lines.append("=" * 70)
    lines.append(f"PLANETARY ASPECTS (Graha Sphuta Drishti): {person_name}")
    lines.append("=" * 70)
    lines.append("")

    # Build aspect matrix
    lines.append("ASPECT TABLE (Virupas, 60 = Full Aspect)")
    lines.append("-" * 70)

    # Header row
    short_names = {
        "Sun": "Sun", "Moon": "Moon", "Mars": "Mars*", "Mercury": "Merc",
        "Jupiter": "Jupi*", "Venus": "Venu", "Saturn": "Satu*",
        "Rahu": "Rahu", "Ketu": "Ketu"
    }

    header = "         "
    for p in PLANETS:
        header += f"{short_names[p]:>7}"
    lines.append(header)

    # Create lookup dict for quick access
    aspect_lookup = {}
    for asp in aspects_data["aspects"]:
        key = (asp["aspecting"], asp["aspected"])
        aspect_lookup[key] = asp["virupas"]

    # Build sign lookup for conjunction detection — chart_helpers needs Chart, not dict
    _chart_input = chart if chart is not None else planets_data
    sign_lookup = {}
    for planet in PLANETS:
        if has_planet(_chart_input, planet):
            sign_lookup[planet] = get_planet_sign_name(_chart_input, planet, default="")

    # Data rows (only real planets cast aspects - Rahu/Ketu are shadow planets)
    for aspecting in ASPECTING_PLANETS:
        row = f"{short_names[aspecting]:<9}"
        for aspected in PLANETS:
            if aspecting == aspected:
                row += "      -"
            else:
                # Check if same sign (conjunction = full aspect equivalent)
                asp_sign = sign_lookup.get(aspecting, "")
                ted_sign = sign_lookup.get(aspected, "")
                if asp_sign and ted_sign and asp_sign == ted_sign:
                    row += "      Y"  # Y = Yuti (conjunction/same sign)
                else:
                    vr = aspect_lookup.get((aspecting, aspected), 0)
                    if vr >= 45:
                        row += f"  {vr:>4.1f}!"  # Mark strong aspects
                    elif vr > 0:
                        row += f"  {vr:>5.1f}"
                    else:
                        row += "      ."
        lines.append(row)

    lines.append("-" * 70)
    lines.append("* = Has special aspects (Mars: 4th/8th, Jupiter: 5th/9th, Saturn: 3rd/10th)")
    lines.append("! = Strong aspect (>= 45 VR)")
    lines.append("Y = Yuti (conjunction/same sign) - equivalent to full aspect (60 VR)")
    lines.append("Note: Rahu/Ketu are shadow planets - they receive aspects but don't cast them")
    lines.append("")

    # Strongest aspects section
    lines.append("STRONGEST ASPECTS (> 45 Virupas)")
    lines.append("-" * 70)

    strong_aspects = [a for a in aspects_data["aspects"] if a["virupas"] >= 45]
    strong_aspects.sort(key=lambda x: -x["virupas"])

    if strong_aspects:
        for asp in strong_aspects[:10]:
            special_marker = " [SPECIAL]" if asp["is_special"] else ""
            lines.append(
                f"  {asp['aspecting']:<8} -> {asp['aspected']:<8}  "
                f"{asp['virupas']:>5.1f} VR ({asp['strength_pct']:>5.1f}%)  "
                f"[{asp['aspect_type']}]{special_marker}"
            )
    else:
        lines.append("  (No aspects above 45 Virupas)")

    lines.append("")

    # Mutual aspects section
    if aspects_data["mutual_aspects"]:
        lines.append("MUTUAL ASPECTS (both planets aspect each other strongly)")
        lines.append("-" * 70)

        for mutual in aspects_data["mutual_aspects"][:5]:
            lines.append(
                f"  {mutual['planet_a']:<8} <-> {mutual['planet_b']:<8}  "
                f"{mutual['a_to_b']:.1f} + {mutual['b_to_a']:.1f} = "
                f"{mutual['combined']:.1f} VR combined"
            )

        lines.append("")

    # Full interpretations
    if show_full:
        lines.append("ASPECT INTERPRETATIONS")
        lines.append("-" * 70)
        lines.append("  Virupas Scale:")
        lines.append("    60 VR = Full aspect (100%) - Maximum influence")
        lines.append("    45 VR = Strong aspect (75%) - Significant influence")
        lines.append("    30 VR = Moderate aspect (50%) - Noticeable influence")
        lines.append("    15 VR = Weak aspect (25%) - Subtle influence")
        lines.append("     0 VR = No aspect - No direct influence")
        lines.append("")
        lines.append("  Special Aspects (enhanced planetary glance):")
        lines.append("    Mars:    Full at 90° (4th house) and 180-210° (7th-8th houses)")
        lines.append("    Jupiter: Full at 120° (5th house), 180° (7th), and 240° (9th)")
        lines.append("    Saturn:  Full at 60° (3rd house), 180° (7th), and 270° (10th)")
        lines.append("")

    lines.append("=" * 70)

    return "\n".join(lines)


def format_list_output(person_name: str, aspects_data: dict, planets_data: dict,
                       threshold: float = 0, show_full: bool = False) -> str:
    """
    Format aspects as a sorted list.

    Args:
        person_name: Name of the chart
        aspects_data: Result from calculate_all_aspects()
        planets_data: Original planets data
        threshold: Minimum VR to display
        show_full: Include interpretations

    Returns:
        Formatted string
    """
    lines = []
    lines.append("=" * 70)
    lines.append(f"PLANETARY ASPECTS (Graha Sphuta Drishti): {person_name}")
    lines.append("=" * 70)
    lines.append("")

    # Sort all aspects by strength
    sorted_aspects = sorted(aspects_data["aspects"], key=lambda x: -x["virupas"])

    # Filter by threshold
    if threshold > 0:
        sorted_aspects = [a for a in sorted_aspects if a["virupas"] >= threshold]

    lines.append(f"ALL ASPECTS (sorted by strength, threshold >= {threshold:.0f} VR)")
    lines.append("-" * 70)
    lines.append(f"{'Aspecting':<10} {'Aspected':<10} {'Dist':>6} {'VR':>6} {'%':>6}  Type")
    lines.append(f"{'-'*10} {'-'*10} {'-'*6} {'-'*6} {'-'*6}  {'-'*20}")

    for asp in sorted_aspects:
        special_marker = " *" if asp["is_special"] else ""
        lines.append(
            f"{asp['aspecting']:<10} {asp['aspected']:<10} "
            f"{asp['distance']:>5.1f}° {asp['virupas']:>5.1f} "
            f"{asp['strength_pct']:>5.1f}%  {asp['aspect_type']}{special_marker}"
        )

    lines.append("")
    lines.append(f"Total: {len(sorted_aspects)} aspects")
    lines.append("* = Special aspect (Mars 4th/8th, Jupiter 5th/9th, Saturn 3rd/10th)")

    lines.append("")
    lines.append("=" * 70)

    return "\n".join(lines)


# ============================================================================
# CLI INTERFACE
# ============================================================================

def main():
    """Command-line interface."""
    parser = argparse.ArgumentParser(
        description="Calculate planetary aspects using Graha Sphuta Drishti (Vedic)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python AI_aspects.py                     # Default chart (Lorris.chtk)
  python AI_aspects.py chart.chtk          # Specific chart
  python AI_aspects.py --list              # List format instead of table
  python AI_aspects.py --strong            # Only show aspects > 30 VR
  python AI_aspects.py --full              # Include aspect interpretations
  python AI_aspects.py --json              # JSON output
  python AI_aspects.py --date 1991-02-22 --time 10:30 --lat 48.98 --lon 2.27

Special Aspects:
  Mars:    Full (60 VR) at 90° (4th) and 210° (8th house)
  Jupiter: Full (60 VR) at 120° (5th) and 240° (9th house)
  Saturn:  Full (60 VR) at 60° (3rd) and 270° (10th house)
        """
    )

    parser.add_argument("chtk_file", nargs="?", help="Path to CHTK file")
    parser.add_argument("--date", "-d", help="Birth date (YYYY-MM-DD)")
    parser.add_argument("--time", "-t", help="Birth time (HH:MM)")
    parser.add_argument("--lat", type=float, help="Latitude")
    parser.add_argument("--lon", type=float, help="Longitude")
    parser.add_argument("--list", "-l", action="store_true",
                        help="List format output (sorted by strength)")
    parser.add_argument("--strong", "-s", action="store_true",
                        help="Only show aspects > 30 VR")
    parser.add_argument("--full", "-f", action="store_true",
                        help="Include aspect interpretations")
    parser.add_argument("--json", action="store_true",
                        help="JSON output")
    parser.add_argument("--threshold", type=float, default=0,
                        help="Minimum VR to display (default: 0)")

    args = parser.parse_args()

    # Determine input method
    if args.date:
        if args.lat is None or args.lon is None:
            print("Error: --lat and --lon are required when using --date")
            sys.exit(1)

        chart, person_name = extract_from_datetime(
            args.date, args.time, args.lat, args.lon
        )
    else:
        chtk_path = args.chtk_file if args.chtk_file else DEFAULT_CHTK

        if not os.path.exists(chtk_path):
            print(f"Error: CHTK file not found: {chtk_path}")
            sys.exit(1)

        chart, person_name = extract_from_chtk(chtk_path)

    # Set threshold
    threshold = args.threshold
    if args.strong:
        threshold = max(threshold, 30)

    # Calculate aspects
    aspects_data = calculate_all_aspects(chart, threshold=0)

    # Output
    if args.json:
        result = {
            "name": person_name,
            "aspects": aspects_data["aspects"],
            "strongest_aspects": aspects_data["strongest_aspects"],
            "mutual_aspects": aspects_data["mutual_aspects"],
            "by_planet": aspects_data["by_planet"]
        }
        print(json.dumps(result, indent=2))
    elif args.list:
        print(format_list_output(person_name, aspects_data, chart,
                                 threshold=threshold, show_full=args.full))
    else:
        print(format_table_output(person_name, aspects_data, chart,
                                  show_full=args.full, chart=chart))


if __name__ == "__main__":
    main()
