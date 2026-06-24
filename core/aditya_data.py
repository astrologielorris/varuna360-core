#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Aditya Circle Data Module
=========================
Shared constants and descriptions for Vedic astrology.

Contains:
- Planet dignities (exaltation, mulatrikona, own sign)
- Proud state descriptions for dignified planets
- Body parts for each Aditya sign
- Description loader from reference markdown
"""
import json
import re
from pathlib import Path

# Project root for locating reference files
PROJECT_ROOT = Path(__file__).parent.parent

# Path to Aditya descriptions markdown (bundled in Core under core/data/).
# This file contains the 12 Aditya (solar deity) reference descriptions used
# by load_aditya_descriptions() below. It is bundled with Core so a fresh
# clone of the public repo gets the full descriptions out of the box.
ADITYA_REF_PATH = PROJECT_ROOT / "core" / "data" / "adityas-complete.md"


# =============================================================================
# ADITYA NAMES - Code names used throughout the app
# =============================================================================
ADITYA_NAMES = [
    "Dhata", "Aryama", "Mitra", "Varuna", "Indra", "Vivasvan",
    "Tvasta", "Vishnu", "Amzu", "Bhaga", "Pusha", "Parjanya"
]

# Mapping from code names to reference file names (handles diacritics)
ADITYA_REF_NAMES = {
    "Dhata": "Dhaataa",
    "Aryama": "Aryamaa",
    "Mitra": "Mitra",
    "Varuna": "Varuṇa",
    "Indra": "Indra",
    "Vivasvan": "Vivasvān",
    "Tvasta": "Tvashtar",
    "Vishnu": "Vishnu",
    "Amzu": "Amzu",
    "Bhaga": "Bhaga",
    "Pusha": "Pusha",
    "Parjanya": "Parjanya",
}


# =============================================================================
# PLANET DIGNITY DATA (exaltation, mulatrikona, own sign, debilitation)
# Copied from wheel chart for consistent behavior
# =============================================================================
ADITYA_DIGNITIES = {
    "Sun": {
        "exaltation": ("Dhata", 0, 30),  # Whole sign
        "mulatrikona": [("Indra", 0, 20)],
        "own_sign": [("Indra", 20, 30)],  # 20-30° Indra
        "debilitation": ("Tvasta", 0, 30),  # 180° opposite exaltation
    },
    "Moon": {
        "exaltation": ("Aryama", 0, 3),  # 0-3° Aryama only
        "mulatrikona": [("Aryama", 3, 27)],
        "own_sign": [("Varuna", 0, 30)],  # Whole Varuna
        "debilitation": ("Vishnu", 0, 30),  # 180° opposite exaltation
    },
    "Mars": {
        "exaltation": ("Bhaga", 0, 30),  # Whole sign
        "mulatrikona": [("Dhata", 0, 12)],
        "own_sign": [("Dhata", 12, 30), ("Vishnu", 0, 30)],  # 12-30° Dhata & whole Vishnu
        "debilitation": ("Varuna", 0, 30),  # 180° opposite exaltation
    },
    "Mercury": {
        "exaltation": ("Vivasvan", 0, 15),  # 0-15° Vivasvan only
        "mulatrikona": [("Vivasvan", 15, 20)],
        "own_sign": [("Vivasvan", 20, 30), ("Mitra", 0, 30)],  # 20-30° Vivasvan & whole Mitra
        "debilitation": ("Parjanya", 0, 30),  # 180° opposite exaltation
    },
    "Jupiter": {
        "exaltation": ("Varuna", 0, 30),  # Whole sign
        "mulatrikona": [("Amzu", 0, 10)],
        "own_sign": [("Amzu", 10, 30), ("Parjanya", 0, 30)],  # 10-30° Amzu & whole Parjanya
        "debilitation": ("Bhaga", 0, 30),  # 180° opposite exaltation
    },
    "Venus": {
        "exaltation": ("Parjanya", 0, 30),  # Whole sign
        "mulatrikona": [("Tvasta", 0, 15)],
        "own_sign": [("Tvasta", 15, 30), ("Aryama", 0, 30)],  # 15-30° Tvasta & whole Aryama
        "debilitation": ("Vivasvan", 0, 30),  # 180° opposite exaltation
    },
    "Saturn": {
        "exaltation": ("Tvasta", 0, 30),  # Whole sign
        "mulatrikona": [("Pusha", 0, 20)],
        "own_sign": [("Pusha", 20, 30), ("Bhaga", 0, 30)],  # 20-30° Pusha & whole Bhaga
        "debilitation": ("Dhata", 0, 30),  # 180° opposite exaltation
    },
}


# =============================================================================
# PROUD STATE DESCRIPTIONS for exalted/mulatrikona/own sign planets
# =============================================================================
PROUD_STATE_TEXTS = {
    "exaltation": """
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✦ EXALTED — Proud State (Avastha) ✦
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

This planet is EXALTED — in its most powerful and dignified position.

• The planet is fully mature and displays its qualities at maximum strength
• People with this placement tend to behave more proudly and confidently
• They can endure more difficulties in life and emerge stronger
• The planet's natural significations flourish and bring success
• This is considered one of the highest dignities a planet can achieve

✦ BODY PART: {body_part}
The body part associated with this sign ({sign_name}) will often be STRONGER
and more able to deliver its functionality. This area of the body tends to
be robust, resilient, and capable of handling greater demands.

The exalted planet acts like a king in his own kingdom — commanding respect,
radiating authority, and manifesting its best qualities without obstruction.
""",
    "mulatrikona": """
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✦ MULATRIKONA — Proud State (Avastha) ✦
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

This planet is in MULATRIKONA — its office or place of power.

"Mula" means ROOT — this is where the planet's root strength originates.
The planet draws its fundamental power and vitality from this sign.

• The planet is fully mature and expresses its qualities strongly
• People with this placement display confident, proud behavior
• They possess natural resilience and can handle life's challenges
• The planet functions with authority in its domain of expertise
• This dignity is second only to exaltation in strength

✦ BODY PART: {body_part}
The body part associated with this sign ({sign_name}) benefits from the
planet's root strength here. This area tends to function well and reliably.

The mulatrikona planet is like an official in their office — working at full
capacity, wielding their expertise, and producing excellent results in their
natural domain. This is the planet's ROOT source of strength.
""",
    "own_sign": """
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✦ OWN SIGN — At Home (Swa Rasi) ✦
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

This planet is in its OWN SIGN — it feels completely at home here.

• The planet expresses its natural qualities more freely and authentically
• Its attributes are more present and readily apparent in the person
• The natural characteristics of this Aditya shine through clearly
• The planet delivers its significations with comfort and ease
• There is a natural affinity between the planet and this sign's energy

✦ BODY PART: {body_part}
The body part associated with this sign ({sign_name}) reflects the planet's
comfortable expression here. This area functions naturally and harmoniously.

The planet at home is like a person in their own house — relaxed, natural,
and expressing their true character without pretense or effort. The qualities
of both the planet and the Aditya sign blend harmoniously.
""",
}


# =============================================================================
# ADITYA BODY PARTS for dignity descriptions
# =============================================================================
ADITYA_BODY_PARTS = {
    "Dhata": "Head, Skull, Bones, Structure",
    "Aryama": "Face, Neck",
    "Mitra": "Arms",
    "Varuna": "Chest",
    "Indra": "Abdominal Cavity, Vital Organs",
    "Vivasvan": "Hips, Intestines",
    "Tvasta": "Pelvic Triangle",
    "Vishnu": "Intimate Parts",
    "Amzu": "Buttocks",
    "Bhaga": "Thighs",
    "Pusha": "Shanks, Calves",
    "Parjanya": "Feet",
}


# =============================================================================
# PLANET COLORS for display
# =============================================================================
PLANET_COLORS = {
    "Sun": "#FFD700",       # Gold
    "Moon": "#C0C0C0",      # Silver
    "Mars": "#FF4444",      # Red
    "Mercury": "#90EE90",   # Light green
    "Jupiter": "#FFA500",   # Orange
    "Venus": "#FF69B4",     # Pink
    "Saturn": "#4169E1",    # Royal blue
    "Rahu": "#696969",      # Dim gray
    "Ketu": "#A0522D",      # Sienna
    "Uranus": "#40E0D0",    # Turquoise
    "Neptune": "#7B68EE",   # Medium slate blue
    "Pluto": "#8B0000",     # Dark red
}


# =============================================================================
# ELEMENT COLORS by zodiac index
# Must match wheel_items.py ZodiacSectorItem.ELEMENT_COLORS (single source of truth)
# Fire=Coral Red, Earth=Brown/Tan, Air=Golden Yellow, Water=Deep Blue
# =============================================================================
ELEMENT_COLORS = {
    0: "#E57373",   # Dhata (Aries) - Fire - Coral red
    1: "#A67C52",   # Aryama (Taurus) - Earth - Brown/tan
    2: "#F0C75E",   # Mitra (Gemini) - Air - Golden yellow
    3: "#1E4D8C",   # Varuna (Cancer) - Water - Deep blue
    4: "#E57373",   # Indra (Leo) - Fire - Coral red
    5: "#A67C52",   # Vivasvan (Virgo) - Earth - Brown/tan
    6: "#F0C75E",   # Tvasta (Libra) - Air - Golden yellow
    7: "#1E4D8C",   # Vishnu (Scorpio) - Water - Deep blue
    8: "#E57373",   # Amzu (Sagittarius) - Fire - Coral red
    9: "#A67C52",   # Bhaga (Capricorn) - Earth - Brown/tan
    10: "#F0C75E",  # Pusha (Aquarius) - Air - Golden yellow
    11: "#1E4D8C",  # Parjanya (Pisces) - Water - Deep blue
}


# =============================================================================
# FUNCTIONS
# =============================================================================

def load_aditya_descriptions() -> dict:
    """
    Load Aditya descriptions from the reference markdown file.

    Returns:
        dict: Mapping of Aditya code names to their full descriptions
    """
    descriptions = {}

    # Find the reference file
    ref_path = ADITYA_REF_PATH

    if not ref_path.exists():
        print(f"Warning: Aditya reference file not found at {ref_path}")
        return descriptions

    try:
        with open(ref_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Split by section headers (## 1. Dhaataa, ## 2. Aryamaa, etc.)
        sections = re.split(r'\n(?=## \d+\. )', content)

        for section in sections:
            # Extract the Aditya name from the header
            header_match = re.match(r'## \d+\. (\w+)', section)
            if header_match:
                ref_name = header_match.group(1)

                # Find the code name for this reference name
                code_name = None
                for code, ref in ADITYA_REF_NAMES.items():
                    # Handle Unicode characters in comparison
                    ref_normalized = ref.replace("ṇ", "n").replace("ā", "a").replace("ū", "u")
                    name_normalized = ref_name.replace("ṇ", "n").replace("ā", "a").replace("ū", "u")
                    if ref_normalized == name_normalized:
                        code_name = code
                        break
                    # Also try exact match
                    if ref == ref_name:
                        code_name = code
                        break

                if code_name:
                    # Store the full section (removing the header)
                    descriptions[code_name] = section.strip()

    except Exception as e:
        print(f"Warning: Could not load Aditya descriptions: {e}")

    return descriptions


def check_planet_dignity(planet_name: str, sign_name: str, deg_in_sign: float) -> str:
    """
    Check if a planet is in exaltation, mulatrikona, own sign, or debilitation.

    Args:
        planet_name: Name of the planet
        sign_name: Aditya sign name the planet is in
        deg_in_sign: Degree position within the sign (0-30)

    Returns:
        "exaltation", "mulatrikona", "own_sign", "debilitation", or None
    """
    if planet_name not in ADITYA_DIGNITIES:
        return None

    dignity = ADITYA_DIGNITIES[planet_name]

    # Check exaltation first (highest priority)
    exalt_sign, exalt_start, exalt_end = dignity["exaltation"]
    if sign_name == exalt_sign and exalt_start <= deg_in_sign <= exalt_end:
        return "exaltation"

    # Check mulatrikona (second priority)
    for mula_sign, start_deg, end_deg in dignity["mulatrikona"]:
        if sign_name == mula_sign and start_deg <= deg_in_sign <= end_deg:
            return "mulatrikona"

    # Check own sign (third priority)
    for own_sign, start_deg, end_deg in dignity.get("own_sign", []):
        if sign_name == own_sign and start_deg <= deg_in_sign <= end_deg:
            return "own_sign"

    # Check debilitation (lowest priority)
    if "debilitation" in dignity:
        deb_sign, deb_start, deb_end = dignity["debilitation"]
        if sign_name == deb_sign and deb_start <= deg_in_sign <= deb_end:
            return "debilitation"

    return None


def get_dignity_description(dignity_type: str, sign_name: str) -> str:
    """
    Get the proud state description for a dignity type.

    Args:
        dignity_type: "exaltation", "mulatrikona", or "own_sign"
        sign_name: Aditya sign name

    Returns:
        Formatted description text with placeholders filled
    """
    if dignity_type not in PROUD_STATE_TEXTS:
        return ""

    body_part = ADITYA_BODY_PARTS.get(sign_name, "Unknown")
    return PROUD_STATE_TEXTS[dignity_type].format(
        body_part=body_part,
        sign_name=sign_name
    )


# Cache for loaded descriptions
_cached_descriptions = None


def get_aditya_description(sign_name: str) -> str:
    """
    Get the full description for an Aditya sign.

    Args:
        sign_name: Aditya code name (e.g., "Dhata", "Aryama")

    Returns:
        Full description text or default message
    """
    global _cached_descriptions
    if _cached_descriptions is None:
        _cached_descriptions = load_aditya_descriptions()

    return _cached_descriptions.get(
        sign_name,
        f"No description available for {sign_name}"
    )


_HORA_TRIMSAMSA_CACHE = None


def load_hora_trimsamsa_descriptions() -> dict:
    path = Path(__file__).parent / "data" / "hora_trimsamsa_reference.json"
    global _HORA_TRIMSAMSA_CACHE
    if _HORA_TRIMSAMSA_CACHE is not None:
        return _HORA_TRIMSAMSA_CACHE
    if not path.exists():
        _HORA_TRIMSAMSA_CACHE = {"horas": {}, "trimsamsas": {}}
        return _HORA_TRIMSAMSA_CACHE
    try:
        _HORA_TRIMSAMSA_CACHE = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        _HORA_TRIMSAMSA_CACHE = {"horas": {}, "trimsamsas": {}}
    return _HORA_TRIMSAMSA_CACHE


def get_being_description(sign_name: str, ring: str, being_type: str):
    data = load_hora_trimsamsa_descriptions()
    try:
        return data[ring + "s"][sign_name][being_type]
    except (KeyError, TypeError, AttributeError):
        return None
