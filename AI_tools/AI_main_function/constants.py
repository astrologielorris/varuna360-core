# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Constants and small getter functions for AI_main.
==================================================
All shared constants used across the AI_main_function modules.
"""

import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Try to import Qt-dependent modules, but don't fail if not available
try:
    from core.aditya_data import (
        check_planet_dignity,
        ADITYA_DIGNITIES,
        get_dignity_description,
        get_aditya_description
    )
    QT_AVAILABLE = True
except ImportError:
    QT_AVAILABLE = False
    ADITYA_DIGNITIES = {}
    def check_planet_dignity(*args, **kwargs): return "Unknown"
    def get_dignity_description(*args, **kwargs): return ""
    def get_aditya_description(*args, **kwargs): return ""

# Canonical source: core.bala_calculator.STRENGTH_THRESHOLD (mirrored here)
STRENGTH_THRESHOLD = 45

# Default CHTK file
DEFAULT_CHTK = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "Lorris.chtk")

# Planets to analyze
PLANETS = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"]

# Aditya sign order (1-indexed for house calculations)
ADITYA_SIGNS = ["Dhata", "Aryama", "Mitra", "Varuna", "Indra", "Vivasvan",
                "Tvasta", "Vishnu", "Amzu", "Bhaga", "Pusha", "Parjanya"]

# Aditya Sign -> Element mapping
ADITYA_SIGN_ELEMENTS = {
    "Dhata": "Fire",
    "Aryama": "Earth",
    "Mitra": "Air",
    "Varuna": "Water",
    "Indra": "Fire",
    "Vivasvan": "Earth",
    "Tvasta": "Air",
    "Vishnu": "Water",
    "Amzu": "Fire",
    "Bhaga": "Earth",
    "Pusha": "Air",
    "Parjanya": "Water",
}

# Tropical Sign -> Element mapping (Western astrology)
TROPICAL_SIGN_ELEMENTS = {
    "Aries": "Fire",
    "Taurus": "Earth",
    "Gemini": "Air",
    "Cancer": "Water",
    "Leo": "Fire",
    "Virgo": "Earth",
    "Libra": "Air",
    "Scorpio": "Water",
    "Sagittarius": "Fire",
    "Capricorn": "Earth",
    "Aquarius": "Air",
    "Pisces": "Water",
}


def get_sign_elements(mode="aditya"):
    """Get the appropriate sign-to-element mapping based on mode."""
    if mode == "tropical_classic":
        return TROPICAL_SIGN_ELEMENTS
    return ADITYA_SIGN_ELEMENTS


# Legacy alias for backwards compatibility
SIGN_ELEMENTS = ADITYA_SIGN_ELEMENTS

# Element order for display
ELEMENT_ORDER = ["Fire", "Earth", "Air", "Water"]

# Element descriptions
ELEMENT_DESCRIPTIONS = {
    "Fire": "Action, initiative, transformation, vision (Mars/Sun/Jupiter)",
    "Earth": "Stability, material, skin, equilibrium (Venus/Mercury/Saturn)",
    "Air": "Movement, change, communication, frequency (Mercury/Venus/Saturn)",
    "Water": "Emotion, intuition, regeneration, comfort (Moon/Mars/Jupiter)",
}

# Luminary weights (Sun/Moon appear ~30x larger than planets visually)
LUMINARY_PLANETS = ["Sun", "Moon"]
DEFAULT_LUMINARY_WEIGHT = 1.5
LUMINARY_WEIGHT_OPTIONS = [1.0, 1.5, 2.0]

# =============================================================================
# MODALITY (Moveable / Fixed / Dual)
# =============================================================================

ADITYA_SIGN_MODALITIES = {
    "Dhata": "Moveable",
    "Aryama": "Fixed",
    "Mitra": "Dual",
    "Varuna": "Moveable",
    "Indra": "Fixed",
    "Vivasvan": "Dual",
    "Tvasta": "Moveable",
    "Vishnu": "Fixed",
    "Amzu": "Dual",
    "Bhaga": "Moveable",
    "Pusha": "Fixed",
    "Parjanya": "Dual",
}

TROPICAL_SIGN_MODALITIES = {
    "Aries": "Moveable",
    "Taurus": "Fixed",
    "Gemini": "Dual",
    "Cancer": "Moveable",
    "Leo": "Fixed",
    "Virgo": "Dual",
    "Libra": "Moveable",
    "Scorpio": "Fixed",
    "Sagittarius": "Dual",
    "Capricorn": "Moveable",
    "Aquarius": "Fixed",
    "Pisces": "Dual",
}


def get_sign_modalities(mode="aditya"):
    """Get the appropriate sign-to-modality mapping based on mode."""
    if mode == "tropical_classic":
        return TROPICAL_SIGN_MODALITIES
    return ADITYA_SIGN_MODALITIES


# Modality order for display
MODALITY_ORDER = ["Moveable", "Fixed", "Dual"]

# Modality descriptions
MODALITY_DESCRIPTIONS = {
    "Moveable": "Initiating, action-oriented, leadership, starting new things",
    "Fixed": "Stable, persistent, determined, sustaining energy",
    "Dual": "Balanced, contains both Fixed and Movable, adaptable, flexible, changeable",
}

MODALITY_YOGA_NAMES = {
    "Moveable": "Rajju",
    "Fixed": "Musala",
    "Dual": "Nala",
}

MODALITY_YOGA_SHORT = {
    "Moveable": "",
    "Fixed": "",
    "Dual": "",
}

MODALITY_YOGA_FULL = {
    "Moveable": (
        " "
        " "
        " "
        " "
        " "
        " "
        " "
        " "
        "them wherever they land."
    ),
    "Fixed": (
        " "
        " "
        " "
        " "
        " "
        " "
        " "
        " "
        ""
    ),
    "Dual": (
        " "
        " "
        " "
        " "
        " "
        " "
        " "
        " "
        ""
    ),
}

# House significations (brief)
HOUSE_MEANINGS = {
    1: "Self, Body, Personality",
    2: "Wealth, Speech, Family",
    3: "Siblings, Courage, Communication",
    4: "Mother, Home, Happiness",
    5: "Children, Intelligence, Creativity",
    6: "Enemies, Health, Service",
    7: "Spouse, Partnership, Business",
    8: "Longevity, Obstacles, Transformation",
    9: "Fortune, Father, Dharma",
    10: "Career, Status, Authority",
    11: "Gains, Friends, Aspirations",
    12: "Loss, Expenses, Liberation"
}

# Dignity labels for display
DIGNITY_LABELS = {
    "exaltation": "EX",
    "mulatrikona": "MK",
    "own_sign": "OH",
    "debilitation": "DB"
}

DIGNITY_FULL_NAMES = {
    "exaltation": "Exalted",
    "mulatrikona": "Mulatrikona",
    "own_sign": "Own House",
    "debilitation": "Debilitated"
}

# House Manifestation Power
HOUSE_POWER = {
    1: ("STRONGEST", "Angle + Trine"),
    10: ("STRONGEST", "Best Angle"),
    4: ("STRONG", "Angle"),
    7: ("STRONG", "Angle"),
    5: ("STRONG", "Trine"),
    9: ("STRONG", "Trine"),
    11: ("GOOD", "Gains"),
    2: ("MODERATE", "Wealth"),
    3: ("MODERATE", "Effort"),
    6: ("WEAK", "Dusthana"),
    8: ("WEAK", "Dusthana"),
    12: ("WEAK", "Dusthana"),
}

POWER_ORDER = ["STRONGEST", "STRONG", "GOOD", "MODERATE", "WEAK"]

# Divine Cow Signs (Kamadhenu)
DIVINE_COW_SIGNS = {
    "Varuna": {
        "cow": "Nandini",
        "power": "STRONGEST",
        "description": "Krishna energy - divine love. Most powerful Aditya, linked to meditation and learning. Manifests through consciousness."
    },
    "Indra": {
        "cow": "Kamadhenu",
        "power": "STRONG",
        "description": "King of the gods. Possesses Kamadhenu, the wish-fulfilling cow. Direct manifestation of desires through authority."
    },
    "Tvasta": {
        "cow": "Kamadhenu (Creator)",
        "power": "STRONG",
        "description": "Divine architect. Created Kamadhenu. Manifests through creative skill, design, and artistry."
    },
}

# Vishnu - Special case
VISHNU_SENSITIVE = {
    "sign": "Vishnu",
    "power": "SENSITIVE",
    "description": "Can manifest powerfully, but very sensitive. If hurt, can manifest very negatively."
}

# Cruel planets for Shame Avastha
CRUEL_PLANETS = ["Mars", "Saturn", "Sun"]

# Dusthana houses (difficult/malefic houses)
DUSTHANA_HOUSES = {6, 8, 12}

# Good interchange houses (angles + trines = best Parivartana)
GOOD_INTERCHANGE_HOUSES = {1, 4, 5, 7, 9, 10}

# Supportive houses (wealth + gains, positive but weaker)
SUPPORTIVE_INTERCHANGE_HOUSES = {2, 11}

# Bad Interchange severity categories
INTERCHANGE_SEVERITY = {
    (6, 8): "WORST", (8, 12): "WORST", (6, 12): "WORST",
    (1, 8): "BAD", (2, 8): "BAD", (3, 8): "BAD", (4, 8): "BAD",
    (5, 8): "BAD", (7, 8): "BAD", (9, 8): "BAD", (10, 8): "BAD", (11, 8): "BAD",
    (1, 12): "MODERATE_BAD", (2, 12): "MODERATE_BAD", (3, 12): "MODERATE_BAD",
    (4, 12): "MODERATE_BAD", (5, 12): "MODERATE_BAD", (7, 12): "MODERATE_BAD",
    (9, 12): "MODERATE_BAD", (10, 12): "MODERATE_BAD", (11, 12): "MODERATE_BAD",
    (1, 6): "LESS_BAD", (2, 6): "LESS_BAD", (3, 6): "LESS_BAD",
    (4, 6): "LESS_BAD", (5, 6): "LESS_BAD", (6, 7): "LESS_BAD",
    (6, 9): "LESS_BAD", (6, 10): "LESS_BAD", (6, 11): "LESS_BAD",
}

# =============================================================================
# 
# =============================================================================

PARIVARTANA_YOGA_SHORT = {
    "MAHA": (
        " "
        ""
    ),
    "KHALA": (
        " "
        ""
    ),
    "DAINYA_6": (
        " "
        ""
    ),
    "DAINYA_8": (
        " "
        ""
    ),
    "DAINYA_12": (
        " "
        ""
    ),
    "DAINYA_DOUBLE": (
        " "
        ""
    ),
}

PARIVARTANA_YOGA_FULL = {
    "MAHA": (
        " "
        " "
        " "
        " "
        " "
        ""
        " "
        " "
        " "
        " "
        " "
        ""
    ),
    "KHALA": (
        " "
        " "
        " "
        " "
        " "
        ""
        " "
        " "
        " "
        " "
        " "
        " "
        ""
    ),
    "DAINYA_6": (
        " "
        " "
        " "
        " "
        " "
        ""
        " "
        " "
        " "
        " "
        " "
        ""
    ),
    "DAINYA_8": (
        " "
        " "
        " "
        " "
        ""
        " "
        " "
        " "
        " "
        " "
        ""
    ),
    "DAINYA_12": (
        " "
        " "
        " "
        " "
        ""
        " "
        " "
        " "
        " "
        " "
        ""
    ),
    "DAINYA_DOUBLE": (
        " "
        " "
        " "
        " "
        ""
        " "
        " "
        " "
        " "
        " "
        "produce results."
    ),
}

# Sign Rulers (Aditya Zodiac) - needed by interchange and avastha modules
SIGN_RULERS = {
    "Dhata": "Mars", "Aryama": "Venus", "Mitra": "Mercury", "Varuna": "Moon",
    "Indra": "Sun", "Vivasvan": "Mercury", "Tvasta": "Venus", "Vishnu": "Mars",
    "Amzu": "Jupiter", "Bhaga": "Saturn", "Pusha": "Saturn", "Parjanya": "Jupiter"
}
