# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under the GNU AGPL-3.0. See LICENSE at the repository root.
"""
Nakshatra position module for CLI and AI tools.
=================================================
Shows all planets, Lagna, and house cusps in their nakshatras,
with Vimshottari lords and dasha sequence numbering from Moon.

  CLI:  show_nakshatra.py -> nakshatra.py -> core/vimshottari_dasha.py
  GUI:  (future integration possible)

All nakshatra lookups delegate to core.vimshottari_dasha.get_nakshatra_for_longitude().
"""

import json
import os
import sys

# Add project root to path (AI_tools/AI_main_function/ -> repo root is 3 levels up;
# this module was relocated from the paid edition to Core, SPEC-NAK-LITE-001).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.vimshottari_dasha import (
    get_nakshatra_for_longitude,
    DASHAS,
    NAKSIZE,
)
from AI_tools.AI_main_function.dasha import (
    NAKSHATRA_NAMES_27,
    parse_chtk_tz_offset,
    load_birth_data_for_dasha,
    resolve_ayanamsa,
    list_ayanamsas,
    _get_ayanamsa_display_name,
)
from AI_tools.AI_main_function.constants import PLANETS

# Lord index (0-8) into DASHAS
LORD = 0


# =============================================================================
# Section 1: Single-Point Nakshatra Lookup
# =============================================================================

def get_planet_nakshatra(tropical_long, jd, ayanamsa=100):
    """
    Get nakshatra info for a single tropical longitude.

    Args:
        tropical_long: Tropical ecliptic longitude (0-360)
        jd: Julian Day (UT)
        ayanamsa: Ayanamsa ID

    Returns:
        dict with: name, index, lord, lord_idx, pada, deg_in_nakshatra, sidereal_long
    """
    nak_size = NAKSIZE

    sid_long, nak_index = get_nakshatra_for_longitude(
        tropical_long, jd, ayanamsa=ayanamsa
    )

    names = NAKSHATRA_NAMES_27
    name = names[nak_index] if 0 <= nak_index < len(names) else f"Nak#{nak_index}"

    # Vimshottari lord: cycle of 9 lords repeats across nakshatras
    lord_idx = nak_index % 9
    lord = DASHAS[lord_idx][LORD]

    # Degrees within this nakshatra
    deg_in_nak = sid_long - (nak_index * nak_size)
    if deg_in_nak < 0:
        deg_in_nak += nak_size

    # Pada (1-4): each nakshatra has 4 equal quarters
    pada_size = nak_size / 4
    pada = min(int(deg_in_nak / pada_size) + 1, 4)

    return {
        "name": name,
        "index": nak_index,
        "lord": lord,
        "lord_idx": lord_idx,
        "pada": pada,
        "deg_in_nakshatra": deg_in_nak,
        "sidereal_long": sid_long,
    }


# =============================================================================
# Section 2: Batch Lookups (All Planets + Houses)
# =============================================================================

def as_tropical_chart(chart):
    """Return a chart whose longitudes are TROPICAL, rebuilding if sidereal-built.

    The nakshatra engine (``get_planet_nakshatra``) expects TROPICAL longitudes
    and applies the ayanamsa itself. A chart built with the Sidereal zodiac
    carries ``FLG_SIDEREAL``, so ``ecliptic_longitude()`` is already sidereal;
    feeding that straight in double-subtracts the ayanamsa and yields wrong
    nakshatras/kuta scores. This is the single frame guard for the whole engine
    (td-lgiq): ``get_all_nakshatras`` / ``get_house_cusp_nakshatras`` call it, so
    no caller can double-subtract. The F2 wheel and ``core/nakshatra_kuta`` call
    it too rather than reimplementing the rebuild (td-bu8s BUG2, SPEC-KALA-REF-001
    O-4). A sidereal chart is rebuilt tropical from its own JD/location
    (``ayanamsa=0``); a tropical or Aditya chart (``sysflg`` without
    ``FLG_SIDEREAL``) passes through unchanged.

    A non-Chart argument (e.g. a legacy planets_data dict) raises ``AttributeError``
    loudly, as before. A Chart-like object whose frame cannot be read (``sysflg``
    is not an int) raises ``ValueError`` rather than being silently mis-framed.
    """
    from libaditya import swe as _swe
    sysflg = chart.context.sysflg  # AttributeError for a non-Chart (loud, by design)
    if not isinstance(sysflg, int):
        raise ValueError(
            "as_tropical_chart: cannot determine chart frame "
            f"(context.sysflg={sysflg!r}); expected a libaditya Chart built via "
            "core.chart_factory.build_chart_from_params")
    if not (sysflg & _swe.FLG_SIDEREAL):
        return chart
    from core.chart_factory import build_chart_from_params
    ctx = chart.context
    return build_chart_from_params(
        jd=ctx.timeJD.jd, lat=ctx.location.lat, lon=ctx.location.long,
        mode="tropical_classic", name=ctx.name,
        utcoffset=ctx.location.utcoffset, ayanamsa=0, hsys=ctx.hsys,
    )


def get_all_nakshatras(chart, jd_ut, ayanamsa=100):
    """
    Get nakshatra positions for all planets and Lagna (Ascendant).

    Args:
        chart: libaditya Chart object (any frame; a sidereal-built chart is
            normalised to tropical internally, td-lgiq).
        jd_ut: Julian Day (UT)

    Returns:
        dict: {body_name: nakshatra_info_dict, ...}
    """
    from core.chart_helpers import get_planet_decimal_degrees, has_planet

    chart = as_tropical_chart(chart)  # td-lgiq: frame guard, no caller can double-subtract
    result = {}

    if has_planet(chart, "Ascendant"):
        asc_deg = get_planet_decimal_degrees(chart, "Ascendant")
        result["Lagna"] = get_planet_nakshatra(asc_deg, jd_ut, ayanamsa)

    for planet in PLANETS:
        if has_planet(chart, planet):
            deg = get_planet_decimal_degrees(chart, planet)
            result[planet] = get_planet_nakshatra(deg, jd_ut, ayanamsa)

    return result


def get_house_cusp_nakshatras(chart, jd_ut, ayanamsa=100):
    """
    Get nakshatra positions for all Campanus house cusps.

    Args:
        chart: libaditya Chart object
        jd_ut: Julian Day (UT)

    Returns:
        list of (house_label, house_deg, nakshatra_info_dict) H1-H12
    """
    chart = as_tropical_chart(chart)  # td-lgiq: same frame guard as get_all_nakshatras
    cusps = chart.rashi().cusps()
    result = []

    for i in range(1, 13):
        try:
            c = cusps[i]
            ecl = c.ecliptic_longitude()
            label = "Lagna" if i == 1 else f"H{i}"
            nak_info = get_planet_nakshatra(ecl, jd_ut, ayanamsa)
            result.append((label, ecl, nak_info))
        except (KeyError, IndexError):
            pass

    return result


# =============================================================================
# Section 3: Dasha Numbering
# =============================================================================

def compute_dasha_numbers(planet_nakshatras):
    """
    Assign dasha sequence numbers (1-9) starting from Moon's lord.

    Moon always gets #1. Each subsequent lord in the Vimshottari cycle
    gets the next number. This shows the temporal relationship between
    each planet's nakshatra lord and the birth dasha sequence.

    Args:
        planet_nakshatras: dict from get_all_nakshatras()

    Returns:
        dict: same structure with added "dasha_number" key per body
    """
    moon_data = planet_nakshatras.get("Moon")
    if not moon_data:
        # No Moon data — can't compute dasha numbers
        return {k: {**v, "dasha_number": None} for k, v in planet_nakshatras.items()}

    moon_lord_idx = moon_data["lord_idx"]

    result = {}
    for body, nak_data in planet_nakshatras.items():
        planet_lord_idx = nak_data["lord_idx"]
        dasha_number = ((planet_lord_idx - moon_lord_idx) % 9) + 1
        result[body] = {**nak_data, "dasha_number": dasha_number}

    return result


def get_dasha_sequence(moon_lord_idx):
    """
    Get the full 9-lord dasha sequence starting from Moon's lord.

    Returns:
        list of lord names in dasha order (e.g., ["Jupiter", "Saturn", ...])
    """
    return [DASHAS[(moon_lord_idx + i) % 9][LORD] for i in range(9)]


# =============================================================================
# Section 4: Formatting Helpers
# =============================================================================

def _format_long(deg):
    """Format degrees as XXX° MM'."""
    d = int(deg)
    m = int(abs(deg - d) * 60)
    return f"{d:>3}° {m:02d}'"


# =============================================================================
# Section 5: Console Table Formatter
# =============================================================================

def format_nakshatra_table(planet_naks, house_naks, birth_data, settings):
    """
    Format nakshatra data as a human-readable console table.

    Args:
        planet_naks: dict from compute_dasha_numbers() (planets + Lagna)
        house_naks: list from get_house_cusp_nakshatras()
        birth_data: dict from load_birth_data_for_dasha()
        settings: dict with ayanamsa

    Returns:
        str: Multi-line formatted text
    """
    lines = []
    ayanamsa = settings["ayanamsa"]
    ayanamsa_name = _get_ayanamsa_display_name(ayanamsa)

    # Header
    name = birth_data.get('name', 'Unknown')
    birth_date = birth_data.get('birth_date', '')
    birth_time = birth_data.get('birth_time', '')
    birth_place = birth_data.get('birth_place', '')

    lines.append(f"Nakshatra Positions \u2014 {name}")
    lines.append("\u2550" * 66)
    lines.append(f"  Born: {birth_date}  {birth_time}")
    lines.append(f"  Place: {birth_place}")
    lines.append(f"  Ayanamsa: {ayanamsa_name} ({ayanamsa}) | 27 Nakshatras")
    lines.append("\u2550" * 66)
    lines.append("")

    # --- PLANETS section ---
    # Separate Lagna from planets for ordering
    lagna_data = planet_naks.get("Lagna")
    planet_entries = []
    for body in ["Moon"] + [p for p in PLANETS if p != "Moon"]:
        if body in planet_naks:
            planet_entries.append((body, planet_naks[body]))

    # Sort by dasha number (Moon = 1 always first)
    planet_entries.sort(key=lambda x: x[1].get("dasha_number", 99))

    lines.append("  PLANETS")
    lines.append("  " + "\u2500" * 62)
    lines.append(f"  {'D#':>2}  {'Planet':<9} {'Nakshatra':<20} {'Pada':>4}  {'Lord':<9} {'Long°'}")
    lines.append("  " + "\u2500" * 62)

    for body, data in planet_entries:
        dn = data.get("dasha_number", "?")
        nak_name = data["name"]
        pada = data["pada"]
        lord = data["lord"]
        sid_long = data["sidereal_long"]
        lines.append(
            f"  {dn:>2}  {body:<9} {nak_name:<20} {pada:>4}  {lord:<9} {_format_long(sid_long)}"
        )

    lines.append("  " + "\u2500" * 62)

    # Dasha sequence line
    moon_data = planet_naks.get("Moon")
    if moon_data:
        seq = get_dasha_sequence(moon_data["lord_idx"])
        arrow = " \u2192 "
        lines.append(f"  Dasha sequence: {arrow.join(seq)}")

    # Lagna line (not part of dasha numbering)
    if lagna_data:
        lines.append("")
        lines.append(
            f"  Lagna: {lagna_data['name']} (pada {lagna_data['pada']}) "
            f"| Lord: {lagna_data['lord']} | {_format_long(lagna_data['sidereal_long'])}"
        )

    # --- HOUSE CUSPS section ---
    if house_naks:
        lines.append("")
        lines.append("  HOUSE CUSPS (Campanus)")
        lines.append("  " + "\u2500" * 62)
        lines.append(f"  {'House':<7} {'Cusp':>9}    {'Nakshatra':<20} {'Lord'}")
        lines.append("  " + "\u2500" * 62)

        for label, cusp_deg, data in house_naks:
            nak_name = data["name"]
            lord = data["lord"]
            lines.append(
                f"  {label:<7} {_format_long(cusp_deg):>9}    {nak_name:<20} {lord}"
            )

        lines.append("  " + "\u2500" * 62)

    lines.append("")
    return "\n".join(lines)


# =============================================================================
# Section 6: JSON Formatter
# =============================================================================

def format_nakshatra_json(planet_naks, house_naks, birth_data, settings):
    """
    Format nakshatra data as JSON.

    Args:
        planet_naks: dict from compute_dasha_numbers()
        house_naks: list from get_house_cusp_nakshatras()
        birth_data: dict from load_birth_data_for_dasha()
        settings: dict with ayanamsa

    Returns:
        str: JSON string
    """
    ayanamsa = settings["ayanamsa"]

    # Dasha sequence
    moon_data = planet_naks.get("Moon")
    dasha_seq = get_dasha_sequence(moon_data["lord_idx"]) if moon_data else []

    # Planets
    planets_out = {}
    for body, data in planet_naks.items():
        planets_out[body] = {
            "nakshatra": data["name"],
            "nakshatra_index": data["index"],
            "lord": data["lord"],
            "pada": data["pada"],
            "dasha_number": data.get("dasha_number"),
            "sidereal_longitude": round(data["sidereal_long"], 4),
            "degrees_in_nakshatra": round(data["deg_in_nakshatra"], 4),
        }

    # Houses
    houses_out = []
    for label, cusp_deg, data in house_naks:
        houses_out.append({
            "house": label,
            "cusp_degrees": round(cusp_deg, 4),
            "nakshatra": data["name"],
            "nakshatra_index": data["index"],
            "lord": data["lord"],
            "pada": data["pada"],
            "sidereal_longitude": round(data["sidereal_long"], 4),
        })

    result = {
        "chart": {
            "name": birth_data.get('name', 'Unknown'),
            "birth_date": birth_data.get('birth_date', ''),
            "birth_time": birth_data.get('birth_time', ''),
            "birth_place": birth_data.get('birth_place', ''),
        },
        "settings": {
            "ayanamsa_id": ayanamsa,
            "ayanamsa_name": _get_ayanamsa_display_name(ayanamsa),
        },
        "dasha_sequence": dasha_seq,
        "planets": planets_out,
        "house_cusps": houses_out,
    }
    return json.dumps(result, indent=2, default=str)
