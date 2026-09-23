"""
Retinue constants and pure lookups shared by Core and Pro.

This module is dependency-free (no libaditya, no swe, no chart loaders) so it can
be imported from Lite, from the Pro Antikythera FT layer and from the pure FT
module without pulling the ephemeris. The named-being tables and the Hora /
Trimsamsa lookups moved here from ``AI_tools/AI_main_function/retinue.py`` in the
Aditya FT wave 0 refactor (SPEC-ANT-FT-001 §2.3, §3.2); that module now
re-imports them and keeps its chart-facing helpers.
"""

# Positional order: index 0=Dhata, 1=Aryama, ..., 11=Parjanya.
# Per SPEC-ZOD-001 §4.2: Division #1 = Dhata in ALL zodiac systems.
ADITYA_SIGN_ORDER = [
    'Dhata', 'Aryama', 'Mitra', 'Varuna', 'Indra', 'Vivasvan',
    'Tvasta', 'Vishnu', 'Amzu', 'Bhaga', 'Pusha', 'Parjanya',
]

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
        "naga": "Kacchanira", "yaksha": "Rathauja", "rakshasa": "Praheti",
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

# Trimsamsa degree boundaries: (start_deg, end_deg, planet_lord, being_type_key, element)
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
# RETINUE RING PALETTE — shared by the wheel view and the Antikythera FT layer
# =============================================================================
# The raw hex literals for the Hora and Trimsamsa rings (SPEC-ANT-FT-001 §3.5).
# These were locals in apps/widgets/wheel_view.py; extracted here in the FT wave 2
# refactor (c2-0) so the FT map layer draws the SAME colours the wheel does,
# from one source. Callers apply their own saturation transform (the wheel wraps
# every background in desat_hex, SPEC-SAT-001) -- these are the pre-desaturation
# values, byte-identical to the former literals (frozen by test_retinue_palette).
HORA_COLORS = {
    "sun_bg":   "#E57373",   # Fire red, Sun / Aditya half
    "sun_text": "#1a1a1a",   # dark text on the Sun half
    "moon_bg":  "#1E4D8C",   # Water blue, Moon / Naga half
    "moon_text": "#FFFFFF",  # white text on the Moon half
}

# Element -> {bg, text}. Earth is darkened (#8B6340, not the rasi #A67C52) for a
# flat fill and Ether uses the panel violet; both differ from the main element
# colour cycle, which is why the palette is its own constant.
TRIMSAMSA_COLORS = {
    "Fire":  {"bg": "#E57373", "text": "#1a1a1a"},
    "Earth": {"bg": "#8B6340", "text": "#FFFFFF"},
    "Air":   {"bg": "#F0C75E", "text": "#1a1a1a"},
    "Water": {"bg": "#1E4D8C", "text": "#FFFFFF"},
    "Ether": {"bg": "#3D1A5C", "text": "#CE93D8"},
}

# =============================================================================
# HOUSE CONNECTION DATA — classical sign lordships
# =============================================================================
# Inlined from ``libaditya.constants.lords`` so this module stays dependency-free
# (SPEC-ANT-FT-001 §2.3: no libaditya import here). Index = sign number 1..12
# (1=Aries ... 12=Pisces); value = ruling planet. These are the fixed classical
# rulerships; the wave-0 test asserts this dict still equals ``libaditya.constants
# .lords`` so the two can never silently drift.
_SIGN_LORDS = {
    1: 'Mars', 2: 'Venus', 3: 'Mercury', 4: 'Moon', 5: 'Sun', 6: 'Mercury',
    7: 'Venus', 8: 'Mars', 9: 'Jupiter', 10: 'Saturn', 11: 'Saturn', 12: 'Jupiter',
}

_PLANET_SIGN_POSITIONS = {}
for _sign_num, _planet in _SIGN_LORDS.items():
    _PLANET_SIGN_POSITIONS.setdefault(_planet, []).append(_sign_num)


def _house_from(current_pos: int, target_pos: int) -> int:
    """House number of target sign counted from current sign (1-indexed)."""
    return ((target_pos - current_pos) % 12) + 1


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
