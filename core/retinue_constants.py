"""
Retinue constants shared by Core and Pro panels.

Moved from AI_tools/AI_main_function/retinue.py for Lite-First access.
The original module still uses these via its own local copies (no circular import).
"""

# Positional order: index 0=Dhata, 1=Aryama, ..., 11=Parjanya.
# Per SPEC-ZOD-001 §4.2: Division #1 = Dhata in ALL zodiac systems.
ADITYA_SIGN_ORDER = [
    'Dhata', 'Aryama', 'Mitra', 'Varuna', 'Indra', 'Vivasvan',
    'Tvasta', 'Vishnu', 'Amzu', 'Bhaga', 'Pusha', 'Parjanya',
]

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
