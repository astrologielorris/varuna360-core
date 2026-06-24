# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Hora & Trimsamsa Being Calculator — Aditya Retinue System
==========================================================

Determines which TWO beings each planet activates based on its degree:
  1. Hora Being: Aditya name (Sun Hora) or Naga name (Moon Hora)
  2. Trimsamsa Being: specific named being from the 5-5-8-7-5 division

Based on Ernst Wilhelm's Aditya Course Class 118 and Srimad Bhagavatam 12.11.33-44.

Usage:
    from AI_tools.AI_main_function.retinue import get_retinue, get_chart_retinue

    # Single lookup
    result = get_retinue("Dhata", 3.08)
    # → hora_being="Dhata" (Aditya), trimsamsa_being="Tumburu" (Gandharva)

    # Full chart
    results = get_chart_retinue(chart)
"""

# =============================================================================
# ADITYA RETINUE DATA — Srimad Bhagavatam 12.11.33-44
# =============================================================================
# Each Aditya sign has 7 beings in its retinue:
#   Aditya (the sign itself), Rishi, Gandharva, Apsara, Naga, Yaksha, Rakshasa
#
# The Hora determines whether the Aditya or Naga is active.
# The Trimsamsa determines which of the 5 other beings is active.
# =============================================================================

ADITYA_RETINUE = {
    "Dhata": {
        "number": 1, "type": "odd", "tropical": "Pisces",
        "rishi": "Pulastya", "gandharva": "Tumburu", "apsara": "Kritasthali",
        "naga": "Vasuki", "yaksha": "Rathakrit", "rakshasa": "Heti",
    },
    "Aryama": {
        "number": 2, "type": "even", "tropical": "Aries",
        "rishi": "Pulaha", "gandharva": "Narada", "apsara": "Punjikasthali",
        "naga": "Kacchanira", "yaksha": "Athauja", "rakshasa": "Praheti",
    },
    "Mitra": {
        "number": 3, "type": "odd", "tropical": "Taurus",
        "rishi": "Atri", "gandharva": "Haha", "apsara": "Menaka",
        "naga": "Takshaka", "yaksha": "Rathasvana", "rakshasa": "Pauruseya",
    },
    "Varuna": {
        "number": 4, "type": "even", "tropical": "Gemini",
        "rishi": "Vasishtha", "gandharva": "Huhu", "apsara": "Sahajanya",
        "naga": "Shukra", "yaksha": "Rathacitra", "rakshasa": "Citrasvana",
    },
    "Indra": {
        "number": 5, "type": "odd", "tropical": "Cancer",
        "rishi": "Angiras", "gandharva": "Vishvavasu", "apsara": "Pramloca",
        "naga": "Elapatra", "yaksha": "Shrota", "rakshasa": "Varya",
    },
    "Vivasvan": {
        "number": 6, "type": "even", "tropical": "Leo",
        "rishi": "Bhrigu", "gandharva": "Ugrasena", "apsara": "Anumloca",
        "naga": "Shankhapala", "yaksha": "Asarana", "rakshasa": "Vyaghra",
    },
    "Tvasta": {
        "number": 7, "type": "odd", "tropical": "Virgo",
        "rishi": "Jamadagni", "gandharva": "Dhritarashtra", "apsara": "Tilottama",
        "naga": "Kambala", "yaksha": "Shatajit", "rakshasa": "Brahmapeta",
    },
    "Vishnu": {
        "number": 8, "type": "even", "tropical": "Libra",
        "rishi": "Vishvamitra", "gandharva": "Suryavarcas", "apsara": "Rambha",
        "naga": "Ashvatara", "yaksha": "Satyajit", "rakshasa": "Makhapeta",
    },
    "Amzu": {
        "number": 9, "type": "odd", "tropical": "Scorpio",
        "rishi": "Kashyapa", "gandharva": "Ritasena", "apsara": "Urvashi",
        "naga": "Mahashankha", "yaksha": "Tarkshya", "rakshasa": "Vidyucchatru",
    },
    "Bhaga": {
        "number": 10, "type": "even", "tropical": "Sagittarius",
        "rishi": "Ayu", "gandharva": "Urna", "apsara": "Purvachitti",
        "naga": "Karkotaka", "yaksha": "Arishtanemi", "rakshasa": "Sphurja",
    },
    "Pusha": {
        "number": 11, "type": "odd", "tropical": "Capricorn",
        "rishi": "Gautama", "gandharva": "Suruci", "apsara": "Ghritaci",
        "naga": "Dhananjaya", "yaksha": "Sushena", "rakshasa": "Vata",
    },
    "Parjanya": {
        "number": 12, "type": "even", "tropical": "Aquarius",
        "rishi": "Bharadvaja", "gandharva": "Vishvavasu", "apsara": "Vishvaci",
        "naga": "Airavata", "yaksha": "Senajit", "rakshasa": "Varca",
    },
}

# Positional order: index 0=Dhata, 1=Aryama, ..., 11=Parjanya.
# Per SPEC-ZOD-001 §4.2: Division #1 = Dhata in ALL zodiac systems.
ADITYA_SIGN_ORDER = [
    'Dhata', 'Aryama', 'Mitra', 'Varuna', 'Indra', 'Vivasvan',
    'Tvasta', 'Vishnu', 'Amzu', 'Bhaga', 'Pusha', 'Parjanya',
]

# Tropical zodiac sign names by degree index (0=Aries ... 11=Pisces)
_TROPICAL_SIGN_NAMES = [
    'Aries', 'Taurus', 'Gemini', 'Cancer', 'Leo', 'Virgo',
    'Libra', 'Scorpio', 'Sagittarius', 'Capricorn', 'Aquarius', 'Pisces',
]


# =============================================================================
# TRIMSAMSA DEGREE BOUNDARIES — 5-5-8-7-5
# =============================================================================
# (start_deg, end_deg, planet_lord, being_type_key, element)

TRIMSAMSA_ODD = [
    (0,  5,  "Mars",    "gandharva", "Fire"),
    (5,  10, "Saturn",  "rakshasa",  "Air"),
    (10, 18, "Jupiter", "rishi",     "Ether"),
    (18, 25, "Mercury", "yaksha",    "Earth"),
    (25, 30, "Venus",   "apsara",    "Water"),
]

TRIMSAMSA_EVEN = [
    (0,  5,  "Venus",   "apsara",    "Water"),
    (5,  12, "Mercury", "yaksha",    "Earth"),
    (12, 20, "Jupiter", "rishi",     "Ether"),
    (20, 25, "Saturn",  "rakshasa",  "Air"),
    (25, 30, "Mars",    "gandharva", "Fire"),
]

# Being type labels for display
BEING_TYPE_LABELS = {
    "gandharva": "Gandharva",
    "rakshasa":  "Rakshasa",
    "rishi":     "Rishi",
    "yaksha":    "Yaksha",
    "apsara":    "Apsara",
}

# =============================================================================
# HOUSE CONNECTION DATA — lordship from libaditya
# =============================================================================

from libaditya.constants import lords as _LIB_LORDS

_PLANET_SIGN_POSITIONS = {}
for _sign_num, _planet in _LIB_LORDS.items():
    _PLANET_SIGN_POSITIONS.setdefault(_planet, []).append(_sign_num)


def _house_from(current_pos: int, target_pos: int) -> int:
    """House number of target sign counted from current sign (1-indexed)."""
    return ((target_pos - current_pos) % 12) + 1

# Trimsamsa element mapping
TRIMSAMSA_ELEMENTS = {
    "gandharva": "Fire",
    "rakshasa":  "Air",
    "rishi":     "Ether",
    "yaksha":    "Earth",
    "apsara":    "Water",
}

# Planets to analyze (no outer planets)
RETINUE_PLANETS = ["Ascendant", "Sun", "Moon", "Mars", "Mercury",
                   "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"]

# Reverse index: being_name.lower() → (sign, being_type_key)
BEING_NAME_INDEX = {}
for _sign, _data in ADITYA_RETINUE.items():
    for _btype in ["rishi", "gandharva", "apsara", "naga", "yaksha", "rakshasa"]:
        BEING_NAME_INDEX[_data[_btype].lower()] = (_sign, _btype)

# Reverse lookup: being_name → display type (e.g., "Tumburu" → "Gandharva")
BEING_TYPE_FOR_NAME = {}
for _sign, _data in ADITYA_RETINUE.items():
    for _btype in ["rishi", "gandharva", "apsara", "naga", "yaksha", "rakshasa"]:
        BEING_TYPE_FOR_NAME[_data[_btype]] = _btype.capitalize()

# All unique being names for dropdown population (trimsamsa + hora nagas)
_trimsamsa_names = {
    _data[_bt] for _data in ADITYA_RETINUE.values()
    for _bt in ["rishi", "gandharva", "apsara", "yaksha", "rakshasa"]
}
_hora_naga_names = {_data["naga"] for _data in ADITYA_RETINUE.values()}
ALL_BEING_NAMES = sorted(_trimsamsa_names | _hora_naga_names)

# being_name → (sign, start_deg, end_deg) for display in dropdowns
BEING_SIGN_DEGREES = {}
for _sign, _data in ADITYA_RETINUE.items():
    _is_odd = _data["type"] == "odd"
    _bounds = TRIMSAMSA_ODD if _is_odd else TRIMSAMSA_EVEN
    for _start, _end, _lord, _btype, _elem in _bounds:
        BEING_SIGN_DEGREES[_data[_btype]] = (_sign, _start, _end)
    # Nagas occupy the Moon hora half
    if _is_odd:
        BEING_SIGN_DEGREES[_data["naga"]] = (_sign, 15, 30)
    else:
        BEING_SIGN_DEGREES[_data["naga"]] = (_sign, 0, 15)


# =============================================================================
# CORE CALCULATION FUNCTIONS
# =============================================================================

def get_hora(aditya_sign_name: str, degree: float) -> dict:
    """
    Determine Hora (Sun/Moon) for a planet at a given degree.

    Args:
        aditya_sign_name: Aditya sign name (e.g., "Dhata")
        degree: Degree within sign (0.0 - 29.999)

    Returns:
        dict with lord, side, being_name
    """
    sign_data = ADITYA_RETINUE.get(aditya_sign_name)
    if not sign_data:
        return {"lord": "?", "side": "?", "being_name": "?"}

    is_odd = sign_data["type"] == "odd"

    # Odd signs: 0-15 = Sun, 15-30 = Moon
    # Even signs: 0-15 = Moon, 15-30 = Sun
    if is_odd:
        is_sun_hora = degree < 15.0
    else:
        is_sun_hora = degree >= 15.0

    current_pos = sign_data["number"]

    if is_sun_hora:
        target_pos = _PLANET_SIGN_POSITIONS["Sun"][0]
        house = _house_from(current_pos, target_pos)
        return {
            "lord": "Sun",
            "side": "Aditya",
            "being_name": aditya_sign_name,
            "house_connection": house,
            "house_sign": ADITYA_SIGN_ORDER[target_pos - 1],
        }
    else:
        target_pos = _PLANET_SIGN_POSITIONS["Moon"][0]
        house = _house_from(current_pos, target_pos)
        return {
            "lord": "Moon",
            "side": "Naga",
            "being_name": sign_data["naga"],
            "house_connection": house,
            "house_sign": ADITYA_SIGN_ORDER[target_pos - 1],
        }


def get_trimsamsa_being(aditya_sign_name: str, degree: float) -> dict:
    """
    Determine Trimsamsa being for a planet at a given degree.

    Args:
        aditya_sign_name: Aditya sign name (e.g., "Dhata")
        degree: Degree within sign (0.0 - 29.999)

    Returns:
        dict with lord, being_type, being_name, element
    """
    sign_data = ADITYA_RETINUE.get(aditya_sign_name)
    if not sign_data:
        return {"lord": "?", "being_type": "?", "being_name": "?", "element": "?"}

    is_odd = sign_data["type"] == "odd"
    boundaries = TRIMSAMSA_ODD if is_odd else TRIMSAMSA_EVEN

    current_pos = sign_data["number"]

    for start, end, planet_lord, being_type_key, element in boundaries:
        if start <= degree < end:
            target_positions = sorted(_PLANET_SIGN_POSITIONS[planet_lord])
            houses = sorted(_house_from(current_pos, tp) for tp in target_positions)
            signs = [ADITYA_SIGN_ORDER[tp - 1] for tp in target_positions]
            signs_by_house = [s for _, s in sorted(zip(
                [_house_from(current_pos, tp) for tp in target_positions], signs))]
            return {
                "lord": planet_lord,
                "being_type": BEING_TYPE_LABELS[being_type_key],
                "being_name": sign_data[being_type_key],
                "element": element,
                "house_connections": houses,
                "house_signs": signs_by_house,
            }

    last = boundaries[-1]
    planet_lord, being_type_key, element = last[2], last[3], last[4]
    target_positions = sorted(_PLANET_SIGN_POSITIONS[planet_lord])
    houses = sorted(_house_from(current_pos, tp) for tp in target_positions)
    signs = [ADITYA_SIGN_ORDER[tp - 1] for tp in target_positions]
    signs_by_house = [s for _, s in sorted(zip(
        [_house_from(current_pos, tp) for tp in target_positions], signs))]
    return {
        "lord": planet_lord,
        "being_type": BEING_TYPE_LABELS[being_type_key],
        "being_name": sign_data[being_type_key],
        "element": element,
        "house_connections": houses,
        "house_signs": signs_by_house,
    }


def get_retinue(aditya_sign_name: str, degree: float) -> dict:
    """
    Get complete Hora + Trimsamsa being data for a position.

    Args:
        aditya_sign_name: Aditya sign name (e.g., "Dhata")
        degree: Degree within sign (0.0 - 29.999)

    Returns:
        dict with hora, trimsamsa, two_beings, and full sign_retinue
    """
    sign_data = ADITYA_RETINUE.get(aditya_sign_name)
    if not sign_data:
        return None

    hora = get_hora(aditya_sign_name, degree)
    trimsamsa = get_trimsamsa_being(aditya_sign_name, degree)

    return {
        "aditya_sign": aditya_sign_name,
        "western_equivalent": sign_data["tropical"],
        "sign_number": sign_data["number"],
        "sign_type": sign_data["type"],
        "hora": hora,
        "trimsamsa": trimsamsa,
        "two_beings": [hora["being_name"], trimsamsa["being_name"]],
        "sign_retinue": {
            "aditya": aditya_sign_name,
            "naga": sign_data["naga"],
            "rishi": sign_data["rishi"],
            "gandharva": sign_data["gandharva"],
            "apsara": sign_data["apsara"],
            "yaksha": sign_data["yaksha"],
            "rakshasa": sign_data["rakshasa"],
        },
    }


_LORD_TO_BEING_KEY = {
    "Mars": "gandharva", "Saturn": "rakshasa", "Jupiter": "rishi",
    "Mercury": "yaksha", "Venus": "apsara",
}


def get_beings_for_house(aditya_sign_name: str, house_num: int) -> list[dict]:
    """Return the being(s) connecting to a given house from a sign."""
    sign_data = ADITYA_RETINUE.get(aditya_sign_name)
    if not sign_data or not (1 <= house_num <= 12):
        return []

    current_pos = sign_data["number"]
    results = []

    for lord, positions in _PLANET_SIGN_POSITIONS.items():
        houses = sorted(_house_from(current_pos, tp) for tp in positions)
        if house_num not in houses:
            continue

        if lord == "Sun":
            results.append({
                "being_name": aditya_sign_name,
                "being_type": "Aditya",
                "being_key": "aditya",
                "lord": lord,
                "ring": "hora",
                "house_connections": houses,
            })
        elif lord == "Moon":
            results.append({
                "being_name": sign_data["naga"],
                "being_type": "Naga",
                "being_key": "naga",
                "lord": lord,
                "ring": "hora",
                "house_connections": houses,
            })
        else:
            btk = _LORD_TO_BEING_KEY[lord]
            results.append({
                "being_name": sign_data[btk],
                "being_type": BEING_TYPE_LABELS[btk],
                "being_key": btk,
                "lord": lord,
                "ring": "trimsamsa",
                "house_connections": houses,
            })

    return results


def get_all_house_connections(aditya_sign_name: str) -> dict[int, dict]:
    """Return dict mapping house 1-12 to the connected being from a sign."""
    result = {}
    for h in range(1, 13):
        beings = get_beings_for_house(aditya_sign_name, h)
        if beings:
            result[h] = beings[0]
    return result


def get_chart_retinue(chart, ayanamsa_offset: float = 0.0,
                      tropical_mode: bool = False) -> dict:
    """
    Compute Hora + Trimsamsa beings for all planets in a chart.

    Sign resolution uses get_planet_sign_index() from the Chart object,
    which handles all zodiac modes internally (SPEC-ZOD-002). The
    tropical_mode and ayanamsa_offset params only affect the mode_label
    string and whether actual_sign is included in the output.

    Args:
        chart: libaditya Chart object (must be in the desired zodiac mode)
        ayanamsa_offset: Only affects mode_label display (sign resolution
            reads from Chart directly)
        tropical_mode: Only affects mode_label and actual_sign display

    Returns:
        dict with planet results list, chart name, summary, and mode label
    """
    results = []
    sidereal_mode = ayanamsa_offset != 0.0 and not tropical_mode

    from core.chart_helpers import (
        get_planet_in_sign_longitude as _get_in_sign,
        get_planet_sign_index as _get_sign_idx,
        has_planet as _has,
    )
    for planet_name in RETINUE_PLANETS:
        if not _has(chart, planet_name):
            continue

        actual_sign = None
        sign_idx = _get_sign_idx(chart, planet_name)
        aditya_sign = ADITYA_SIGN_ORDER[sign_idx]
        degree_decimal = _get_in_sign(chart, planet_name)
        degrees = int(degree_decimal)
        minutes = int((degree_decimal - degrees) * 60)

        if tropical_mode or sidereal_mode:
            actual_sign = _TROPICAL_SIGN_NAMES[sign_idx]

        if not aditya_sign or aditya_sign not in ADITYA_RETINUE:
            continue

        retinue = get_retinue(aditya_sign, degree_decimal)
        if not retinue:
            continue

        # Add planet metadata
        if actual_sign:
            retinue["actual_sign"] = actual_sign
        retinue["planet"] = planet_name
        retinue["degrees"] = degrees
        retinue["minutes"] = minutes
        retinue["degree_decimal"] = round(degree_decimal, 2)

        results.append(retinue)

    ctx = getattr(chart, "context", None)
    chart_name = (getattr(ctx, "name", "") if ctx else "") or "Unknown"
    summary = _build_summary(results)
    if tropical_mode:
        mode_label = "Tropical"
    elif sidereal_mode:
        mode_label = f"Sidereal (offset {ayanamsa_offset:.4f}°)"
    else:
        mode_label = "Tropical Aditya"

    return {
        "chart_name": chart_name,
        "planets": results,
        "summary": summary,
        "mode": mode_label,
    }


def _build_summary(results: list) -> dict:
    """Build Hora and Trimsamsa summary counts."""
    hora_aditya = []
    hora_naga = []
    trimsamsa_counts = {
        "gandharva": {"count": 0, "planets": [], "element": "Fire"},
        "rakshasa":  {"count": 0, "planets": [], "element": "Air"},
        "rishi":     {"count": 0, "planets": [], "element": "Ether"},
        "yaksha":    {"count": 0, "planets": [], "element": "Earth"},
        "apsara":    {"count": 0, "planets": [], "element": "Water"},
    }

    for r in results:
        planet = r["planet"]

        # Hora
        if r["hora"]["side"] == "Aditya":
            hora_aditya.append(planet)
        else:
            hora_naga.append(planet)

        # Trimsamsa
        being_type = r["trimsamsa"]["being_type"].lower()
        if being_type in trimsamsa_counts:
            trimsamsa_counts[being_type]["count"] += 1
            trimsamsa_counts[being_type]["planets"].append(planet)

    # Find dominant force(s) — detect ties
    max_count = max(v["count"] for v in trimsamsa_counts.values())
    dominant_keys = [k for k, v in trimsamsa_counts.items() if v["count"] == max_count]
    if len(dominant_keys) == 1:
        dominant_force = BEING_TYPE_LABELS[dominant_keys[0]]
    else:
        dominant_force = " / ".join(BEING_TYPE_LABELS[k] for k in dominant_keys) + " (tie)"

    return {
        "hora": {
            "aditya_side": {"count": len(hora_aditya), "planets": hora_aditya},
            "naga_side": {"count": len(hora_naga), "planets": hora_naga},
        },
        "trimsamsa": trimsamsa_counts,
        "dominant_force": dominant_force,
    }


# =============================================================================
# TABLE FORMATTER
# =============================================================================

def format_retinue_table(chart_data: dict) -> str:
    """Format chart retinue data as a human-readable table."""
    name = chart_data["chart_name"]
    planets = chart_data["planets"]
    summary = chart_data["summary"]

    mode_label = chart_data.get("mode", "Tropical Aditya")
    lines = [
        f"Hora & Trimsamsa Beings -- {name}  [{mode_label}]",
        "=" * 115,
        "",
        f"  {'Planet':<12} {'Sign':<22} {'Deg':>6}  {'Hora Being':<20} {'HH':>2}  {'Trimsamsa Being':<18} {'Type':<12} {'Element':<7} {'TH':<5}",
        f"  {'─' * 11}  {'─' * 21}  {'─' * 5}  {'─' * 19}  {'─' * 2}  {'─' * 17}  {'─' * 11}  {'─' * 7} {'─' * 5}",
    ]

    for r in planets:
        planet = r["planet"]
        sign_label = f"{r['aditya_sign']}/{r.get('actual_sign', r['western_equivalent'])}"
        deg = r["degrees"]
        mins = r["minutes"]
        deg_str = f"{deg:>2}°{mins:02d}'"

        hora_being = r["hora"]["being_name"]
        hora_side = r["hora"]["side"]
        hora_label = f"{hora_being} ({hora_side})"
        hh = r["hora"].get("house_connection", "")

        trim_being = r["trimsamsa"]["being_name"]
        trim_type = r["trimsamsa"]["being_type"]
        trim_element = r["trimsamsa"]["element"]
        th_list = r["trimsamsa"].get("house_connections", [])
        th = ",".join(str(h) for h in th_list)

        lines.append(
            f"  {planet:<12} {sign_label:<22} {deg_str:>6}  {hora_label:<20} {hh:>2}  {trim_being:<18} {trim_type:<12} {trim_element:<7} {th:<5}"
        )

    # Hora summary
    lines.append("")
    lines.append("=" * 100)
    lines.append("HORA SUMMARY")
    ha = summary["hora"]["aditya_side"]
    hn = summary["hora"]["naga_side"]
    lines.append(f"  Aditya side (Sun Hora):  {ha['count']} planets  -- {', '.join(ha['planets'])}")
    lines.append(f"  Naga side (Moon Hora):   {hn['count']} planets  -- {', '.join(hn['planets'])}")

    # Trimsamsa summary
    lines.append("")
    lines.append("TRIMSAMSA SUMMARY (5 forces)")
    type_order = ["gandharva", "rakshasa", "rishi", "yaksha", "apsara"]
    lord_map = {"gandharva": "Mars", "rakshasa": "Saturn", "rishi": "Jupiter",
                "yaksha": "Mercury", "apsara": "Venus"}
    for t in type_order:
        data = summary["trimsamsa"][t]
        label = BEING_TYPE_LABELS[t]
        lord = lord_map[t]
        elem = data["element"]
        count = data["count"]
        planet_list = ", ".join(data["planets"]) if data["planets"] else "--"
        lines.append(f"  {label:<12} ({lord:<7}/{elem:<6}):  {count}  -- {planet_list}")

    lines.append("")
    lines.append(f"DOMINANT FORCE: {summary['dominant_force']}")
    lines.append("=" * 100)

    return "\n".join(lines)


# =============================================================================
# HOUSE GRAPH — dominant / absent house analysis
# =============================================================================

def _build_house_tally(planets: list) -> dict[int, list[dict]]:
    """Tally all house connections across planets. Returns {house: [entries]}."""
    tally = {h: [] for h in range(1, 13)}
    for r in planets:
        planet = r["planet"]
        hh = r["hora"].get("house_connection")
        if hh:
            tally[hh].append({"planet": planet, "ring": "H"})
        for h in r["trimsamsa"].get("house_connections", []):
            tally[h].append({"planet": planet, "ring": "T"})
    return tally


def format_house_graph(chart_data: dict) -> str:
    """Format a sorted bar-graph of house connection density."""
    name = chart_data["chart_name"]
    planets = chart_data["planets"]
    tally = _build_house_tally(planets)

    active = [(h, entries) for h, entries in tally.items() if entries]
    absent = [(h, entries) for h, entries in tally.items() if not entries]
    active.sort(key=lambda x: (-len(x[1]), x[0]))

    max_count = max(len(e) for e in tally.values()) if tally else 0
    bar_width = max_count

    lines = [
        f"House Connection Density — {name}",
        "=" * 80,
        f"  {'House':>5}  {'Count':>5}  {'':>{bar_width}}  Planets (H=Hora, T=Trimsamsa)",
        f"  {'─' * 5}  {'─' * 5}  {'─' * bar_width}  {'─' * 44}",
    ]

    for h, entries in active:
        count = len(entries)
        bar = "█" * count
        planet_strs = " ".join(f"{e['planet']}({e['ring']})" for e in entries)
        lines.append(f"  {h:>5}  {count:>5}  {bar:<{bar_width}}  {planet_strs}")

    if absent:
        lines.append(f"  {'─' * 5}──{'─' * 5}──{'─' * bar_width}── ABSENT {'─' * 33}")
        for h, _ in absent:
            lines.append(f"  {h:>5}  {0:>5}  {'':>{bar_width}}  --")

    lines.append("")
    dom_houses = [h for h, e in active if len(e) == len(active[0][1])] if active else []
    sparse = [(h, len(e)) for h, e in active if len(e) == 1]
    dom_str = ", ".join(f"House {h} ({len(tally[h])})" for h in dom_houses)
    absent_str = ", ".join(f"House {h}" for h, _ in absent) if absent else "None"
    sparse_str = ", ".join(f"House {h} ({c} — {tally[h][0]['planet']} only)" for h, c in sparse) if sparse else "None"

    lines.append(f"  Dominant: {dom_str}")
    lines.append(f"  Absent:  {absent_str}")
    lines.append(f"  Sparse:  {sparse_str}")
    lines.append("=" * 80)

    return "\n".join(lines)


def house_tally_to_json(chart_data: dict) -> dict:
    """Build JSON-serializable house tally with dominant/absent/weak."""
    tally = _build_house_tally(chart_data["planets"])
    houses = {}
    for h in range(1, 13):
        entries = tally[h]
        houses[str(h)] = {
            "count": len(entries),
            "planets": [{"planet": e["planet"], "ring": e["ring"]} for e in entries],
        }

    counts = [len(e) for e in tally.values()]
    max_c = max(counts) if counts else 0
    dominant = [h for h in range(1, 13) if len(tally[h]) == max_c and max_c > 0]
    absent = [h for h in range(1, 13) if not tally[h]]
    sparse = [h for h in range(1, 13) if len(tally[h]) == 1]

    return {
        "chart_name": chart_data["chart_name"],
        "houses": houses,
        "dominant": dominant,
        "absent": absent,
        "sparse": sparse,
    }


# =============================================================================
# JSON FORMATTER
# =============================================================================

def retinue_to_json(chart_data: dict) -> dict:
    """Convert chart retinue data to JSON-serializable dict."""
    # Already JSON-serializable by construction
    return chart_data
