# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Constants for the round zodiac wheel.
Colors, radii, Aditya names, zodiac symbols, and element mappings.
"""

# Ring radii for 800x800 canvas (center at 400, 400)
WHEEL_RADII = {
    "outer": 360,       # Zodiac symbols ring (outermost)
    "middle": 300,      # Aditya names + colored sectors
    "inner": 220,       # Element imagery (Phase 4)
    "planets": 190,     # Planet positions (closer to sectors for clarity)
    "center": 80,       # Empty center circle
}

# Element colors (Fire-Earth-Air-Water cycle)
# Traditional Western astrology colors
ELEMENT_COLORS = {
    "Fire": "#E57373",      # Coral red (Dhata, Indra, Amzu)
    "Earth": "#A67C52",     # Brown/tan (Aryama, Vivasvan, Bhaga)
    "Air": "#F0C75E",       # Golden yellow (Mitra, Tvasta, Pusha)
    "Water": "#1E4D8C",     # Deep blue (Varuna, Vishnu, Parjanya)
}

# Element cycle pattern (repeats 3 times for 12 signs)
ELEMENT_CYCLE = ["Fire", "Earth", "Air", "Water"]

# Aditya names in order (index 0 = position at 0° / Aries equivalent)
ADITYA_NAMES = [
    "Dhata",        # 0 - Fire
    "Aryama",       # 1 - Earth
    "Mitra",        # 2 - Air
    "Varuna",       # 3 - Water
    "Indra",        # 4 - Fire
    "Vivasvan",     # 5 - Earth
    "Tvasta",       # 6 - Air
    "Vishnu",       # 7 - Water
    "Amzu",         # 8 - Fire
    "Bhaga",        # 9 - Earth
    "Pusha",        # 10 - Air
    "Parjanya",     # 11 - Water
]

# Western zodiac symbols (Unicode)
ZODIAC_SYMBOLS = [
    "\u2648",  # ♈ Aries
    "\u2649",  # ♉ Taurus
    "\u264A",  # ♊ Gemini
    "\u264B",  # ♋ Cancer
    "\u264C",  # ♌ Leo
    "\u264D",  # ♍ Virgo
    "\u264E",  # ♎ Libra
    "\u264F",  # ♏ Scorpio
    "\u2650",  # ♐ Sagittarius
    "\u2651",  # ♑ Capricorn
    "\u2652",  # ♒ Aquarius
    "\u2653",  # ♓ Pisces
]

# Western zodiac names (for Classic mode)
ZODIAC_NAMES = [
    "Aries", "Taurus", "Gemini", "Cancer",
    "Leo", "Virgo", "Libra", "Scorpio",
    "Sagittarius", "Capricorn", "Aquarius", "Pisces"
]

# Planet abbreviations for display
PLANET_ABBREV = {
    "Sun": "Su",
    "Moon": "Mo",
    "Mars": "Ma",
    "Mercury": "Me",
    "Jupiter": "Ju",
    "Venus": "Ve",
    "Saturn": "Sa",
    "Uranus": "Ur",
    "Neptune": "Ne",
    "Pluto": "Pl",
    "Rahu": "Ra",
    "Ketu": "Ke",
    "Ascendant": "Asc",
}

# Planet colors for visual distinction
PLANET_COLORS = {
    "Sun": "#FFD700",       # Gold
    "Moon": "#C0C0C0",      # Silver
    "Mars": "#FF4444",      # Red
    "Mercury": "#90EE90",   # Light green
    "Jupiter": "#FFA500",   # Orange
    "Venus": "#FF69B4",     # Pink
    "Saturn": "#4169E1",    # Royal blue
    "Uranus": "#00CED1",    # Dark cyan
    "Neptune": "#9370DB",   # Medium purple
    "Pluto": "#8B4513",     # Saddle brown
    "Rahu": "#696969",      # Dim gray
    "Ketu": "#A0522D",      # Sienna
}

# Planets to display (order matters for rendering)
DISPLAY_PLANETS = [
    "Sun", "Moon", "Mars", "Mercury", "Jupiter",
    "Venus", "Saturn", "Rahu", "Ketu"
]

# Optional outer planets
OUTER_PLANETS = ["Uranus", "Neptune", "Pluto"]

# ── Nakshatra Constants (27 nakshatras) ──────────────────────────

# Three-letter abbreviations for nakshatra wheel display
NAKSHATRA_ABBREV = [
    "Asv", "Bha", "Kri", "Roh", "Mri",  # 0-4
    "Ard", "Pun", "Pus", "Asl", "Mag",  # 5-9
    "PPh", "UPh", "Has", "Chi", "Sva",  # 10-14
    "Vis", "Anu", "Jye", "Mul", "PAs",  # 15-19
    "UAs", "Sra", "Dha", "Sat", "PBh",  # 20-24
    "UBh", "Rev",                         # 25-26
]

# Vimshottari lord for each nakshatra (index 0-26)
# Cycle: Ketu, Venus, Sun, Moon, Mars, Rahu, Jupiter, Saturn, Mercury × 3
NAKSHATRA_LORDS = [
    "Ketu", "Venus", "Sun", "Moon", "Mars",      # Ashvini..Mrigashira
    "Rahu", "Jupiter", "Saturn", "Mercury",       # Ardra..Ashlesha
    "Ketu", "Venus", "Sun", "Moon", "Mars",       # Magha..Chitra
    "Rahu", "Jupiter", "Saturn", "Mercury",       # Svati..Jyeshtha
    "Ketu", "Venus", "Sun", "Moon", "Mars",       # Mula..Dhanishta
    "Rahu", "Jupiter", "Saturn", "Mercury",       # Shatabhisha..Revati
]


def get_element_for_sign(sign_index: int) -> str:
    """Get element name for a sign index (0-11)."""
    return ELEMENT_CYCLE[sign_index % 4]


def get_element_color(sign_index: int) -> str:
    """Get element color for a sign index (0-11)."""
    element = get_element_for_sign(sign_index)
    return ELEMENT_COLORS[element]


def get_aditya_name(sign_index: int) -> str:
    """Get Aditya name for a sign index (0-11)."""
    return ADITYA_NAMES[sign_index % 12]


def get_zodiac_symbol(sign_index: int) -> str:
    """Get zodiac Unicode symbol for a sign index (0-11)."""
    return ZODIAC_SYMBOLS[sign_index % 12]


def get_zodiac_name(sign_index: int) -> str:
    """Get Western zodiac name for a sign index (0-11)."""
    return ZODIAC_NAMES[sign_index % 12]
