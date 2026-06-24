# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
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
    "Moveable": "Rope. Pulled from experience to experience, charming, vivid presence in each moment.",
    "Fixed": "Pestle. Sustained accumulative labor, each pass refining what came before.",
    "Dual": "Reed. Rapid growth, bridging categories, incorporating and transforming.",
}

MODALITY_YOGA_FULL = {
    "Moveable": (
        "Rajju Yoga arises when the majority of the seven planets occupy movable signs. "
        "Rajju means rope or string. The person is pulled from place to place, from one "
        "attachment to the next. They bring the full force of their enthusiasm to each new "
        "beginning, producing a kind of aliveness that others find attractive. But charm is "
        "not the same as reliability. Each experience is fully entered without the weight of "
        "previous experience present. The cost is continuity: nothing accumulates, nothing is "
        "built on what came before. With healthy avasthas, the Rajju person drops genuine magic "
        "wherever they go. With unhealthy avasthas, they are running from what catches up with "
        "them wherever they land."
    ),
    "Fixed": (
        "Musala Yoga arises when the majority of the seven planets occupy fixed signs. "
        "Musala means pestle: the instrument used to grind herbs in a mortar. Each pass breaks "
        "down the material a little more, and the result is a progressively finer powder. Nothing "
        "is wasted. The Musala person returns to the grindstone each day, carrying everything they "
        "have learned into each new encounter. Character, skill, and self-knowledge compound over "
        "time through sustained return to the same work. The cost is that no single experience is "
        "fully undivided: the weight of accumulated context is always present. With healthy avasthas, "
        "they build toward something of genuine beauty. With unhealthy avasthas, they grind to escape "
        "pain, working to shut down painful feelings rather than building toward a vision."
    ),
    "Dual": (
        "Nala Yoga arises when the majority of the seven planets occupy dual signs. "
        "Nala means reed or grass: something growing rapidly upward from the ground, transitioning "
        "elements from the earth into a living form. The Nala person retains some liveliness and "
        "enthusiasm of the movable signs while also having some capacity for building from the fixed "
        "nature. They can be pulled into new experiences without losing the thread of where they came "
        "from. They are lively enough to be genuinely enjoyable, dependable enough to be genuinely "
        "useful to their community, and adaptable enough to shift between building and exploring "
        "without losing either capacity entirely. Nala Yoga is the most versatile of the three in "
        "many practical situations."
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
# PARIVARTANA YOGA DESCRIPTIONS (Maha / Khala / Dainya)
# =============================================================================

PARIVARTANA_YOGA_SHORT = {
    "MAHA": (
        "Grace circuit between good houses. "
        "Luck carries you even when skill fails, creating a self-reinforcing destiny loop of abundance."
    ),
    "KHALA": (
        "Skill circuit through the 3rd house of martial focus. "
        "Success lasts only as long as raw effort is applied; a single mistake causes a dramatic tumble."
    ),
    "DAINYA_6": (
        "Friction circuit through the 6th house of struggle. "
        "Creates an arduous uphill climb; productivity requires constant effort just to stay afloat."
    ),
    "DAINYA_8": (
        "Shock circuit through the 8th house of risk. "
        "Brings disruptions from left field; stability is undermined by unpredictable events."
    ),
    "DAINYA_12": (
        "Surrender circuit through the 12th house of loss. "
        "Expenses and surrenders arise from forces beyond control; resources flow outward relentlessly."
    ),
    "DAINYA_DOUBLE": (
        "Double misery circuit between two dusthana houses. "
        "Two weak links fused together create the most structurally compromised life theme."
    ),
}

PARIVARTANA_YOGA_FULL = {
    "MAHA": (
        "A Maha (Great) Yoga occurs when two planets interchange signs between good houses "
        "(1, 2, 4, 5, 7, 9, 10, 11). This creates an energy circuit that functions as a permanent "
        "life theme of abundance. Unlike a standard placement where a planet simply occupies a space, "
        "an interchange fuses two houses into a self-reinforcing destiny loop. The energy flows in a "
        "circle, making the resulting life patterns nearly impossible to break. These themes manifest "
        "with peak intensity during the Dashas of the planets involved.\n\n"
        "What the ancients call 'grace' or 'luck' is the practical result: things work out even when "
        "the native makes mistakes. A Maha Yoga between the 1st and 9th houses, for instance, aligns "
        "the native's existence with their life purpose, allowing them to rise after any setback. "
        "Between the 1st and 4th, innate happiness arises without external cause, like a spring "
        "bubbling up from the earth in the safety of one's burrow. The hierarchy is absolute: "
        "Maha Yogas provide the grace that Khala Yogas lack and Dainya Yogas desperately need."
    ),
    "KHALA": (
        "A Khala (Cruel) Yoga occurs when the 3rd house (self-will, martial focus) interchanges "
        "with any non-misery house. The word 'cruel' does not mean evil; it means there is no luck, "
        "no grace, no margin for error. Success depends entirely on raw skill and sustained effort. "
        "Like an athlete who must keep running, the moment the native relaxes they are overtaken. "
        "In a Maha Yoga, you can make a mistake and the grace of the chart saves you. In a Khala "
        "Yoga, a single bad decision causes everything to collapse.\n\n"
        "The 3rd house acts as the 'exam,' and the house it interchanges with determines the nature "
        "of the test. With the 1st house, the test is sheer strength of character. With the 2nd, the "
        "test is follow-through and resource management. With the 4th, the test is restlessness: a "
        "struggle to find peace, seeking happiness through external thrills rather than inner safety. "
        "A behavioral dichotomy also emerges: when you are the object of the native's goal, they have "
        "'sweet speech.' The moment you are no longer relevant to their focus, they become indifferent. "
        "They are not mean; they are intensely focused elsewhere."
    ),
    "DAINYA_6": (
        "A Dainya (Misery) Yoga through the 6th house creates a life theme of 'real world struggle.' "
        "The 6th house represents productivity under adversity: enemies, debts, illness, service. When "
        "fused with another house by interchange, it ensures that every life project connected to that "
        "house involves an arduous, uphill climb. No matter how hard the native works, they only stay "
        "afloat. An extra expense, a new obstacle, or an unexpected rival always arrives to swallow "
        "any surplus. It is the most 'livable' misery because the native can still function.\n\n"
        "Because every life project requires all twelve houses to complete, a 6th house Dainya Yoga "
        "shows exactly where the chain will strain. If fused with the 1st house, delays in finding "
        "purpose emerge. If fused with the 2nd, financial maintenance becomes the permanent theme: "
        "the native works hard but only breaks even. The remedy is not to fight the friction but to "
        "accept that this area of life requires more effort than others, and to build routines that "
        "account for the extra resistance."
    ),
    "DAINYA_8": (
        "A Dainya Yoga through the 8th house is the most painful variant because the disruptions come "
        "from 'left field.' The 8th house is the House of Risk: shocks, sudden reversals, and hidden "
        "dangers. When it interchanges with another house, the life theme connected to that house is "
        "permanently subject to unpredictable upheaval. Stability is undermined not by a steady "
        "struggle (like the 6th) but by sudden collapses. One day the floor simply falls away.\n\n"
        "The traditional warning is absolute: no one with an 8th house interchange should ever gamble. "
        "They will inevitably bet on the wrong outcome right at the moment of peak risk. If fused "
        "with the 1st house, there is zero stability; the native feels the floor is always waiting "
        "to drop. If fused with the 5th, tragic inconsistencies emerge: inspiration arrives this week "
        "and vanishes the next, or creative projects and children are subject to sudden shocks. "
        "The 8th house Dainya teaches the hardest lesson: some losses cannot be prevented, only endured."
    ),
    "DAINYA_12": (
        "A Dainya Yoga through the 12th house carries themes of loss, expense, and surrender. The "
        "native often feels like a puppet of greater forces: institutions, bodily frailties, family "
        "obligations, or spiritual currents larger than the individual will. When the 12th house "
        "interchanges with another house, resources connected to that house flow outward relentlessly. "
        "The native pays more in time, energy, and money than everyone else to achieve the same result.\n\n"
        "If fused with the 1st house, the native surrenders self-purpose to escapism or higher powers; "
        "they become a 'spendthrift' of their own identity. If fused with the 2nd house, overwhelming "
        "responsibility drives the expenses: the native must carry financial weight that logic says "
        "should not be theirs alone. The 12th house Dainya is not always tragic; for a spiritually "
        "oriented person, surrender to forces greater than oneself can be the path itself. The "
        "question is whether the surrender is conscious or imposed."
    ),
    "DAINYA_DOUBLE": (
        "When two dusthana houses (6th, 8th, 12th) interchange, both weak links in the life process "
        "are fused into a single circuit. This is the most structurally compromised yoga because both "
        "sides of the exchange represent areas of difficulty. The 6th/8th combination merges chronic "
        "struggle with sudden shocks. The 8th/12th merges hidden dangers with inevitable loss. The "
        "6th/12th merges daily adversity with surrender to forces beyond control.\n\n"
        "The practical result is that the native cannot compensate for one weakness by leaning on the "
        "other house, because both houses are already compromised. The energy circuit feeds difficulty "
        "back into itself. However, even the most challenging yoga is not a sentence; it is a "
        "description of the terrain. Understanding where the chain strains most allows the native to "
        "stop fighting the wrong battles and to direct their limited energy where it will actually "
        "produce results."
    ),
}

# Sign Rulers (Aditya Zodiac) - needed by interchange and avastha modules
SIGN_RULERS = {
    "Dhata": "Mars", "Aryama": "Venus", "Mitra": "Mercury", "Varuna": "Moon",
    "Indra": "Sun", "Vivasvan": "Mercury", "Tvasta": "Venus", "Vishnu": "Mars",
    "Amzu": "Jupiter", "Bhaga": "Saturn", "Pusha": "Saturn", "Parjanya": "Jupiter"
}
