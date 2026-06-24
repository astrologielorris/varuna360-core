# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Varga code definitions and utilities.
"""

ADITYA_SIGNS = [
    None,
    "Dhata", "Aryama", "Mitra", "Varuna",
    "Indra", "Vivasvan", "Tvasta", "Vishnu",
    "Amzu", "Bhaga", "Pusha", "Parjanya"
]

VARGA_NAMES = {
    1: "Rasi", 2: "Hora", 3: "Drekkana", 4: "Chaturthamsa",
    7: "Saptamsa", 9: "Navamsa", 10: "Dasamsa", 1010: "Dasamsa-R",
    12: "Dwadasamsa", 16: "Shodasamsa", 20: "Vimshamsa",
    24: "Chaturvimshamsa", 2424: "Siddhamsa-R", 27: "Bhamsha",
    30: "Trimshamsa", 40: "Khavedamsa", 45: "Akshavedamsa",
    60: "Shashtiamsa",
}

_VALID_ADITYA_MODES = frozenset({'aditya', 'tropical_classic', 'sidereal'})

_GUI_TO_LIBADITYA_VARGA = {
    1: 1,
    2: -2,    # Hora (Sun/Moon classical)
    3: -3,    # Drekkana
    4: -4,    # Chaturthamsha
    7: 7,     # Saptamsa: parivritti == classical
    9: 9,     # Navamsa: parivritti == classical
    10: -10,  # Dasamsa
    1010: -100,  # Dasamsa-R (reverse for even rashis)
    12: -12,  # Dvadasamsa
    16: -16,  # Shodasamsa
    20: -20,  # Vimshamsa
    24: -24,  # Parashara Chaturvimshamsa
    2424: -240,  # Siddhamsha-R
    27: -27,  # Bhamsha
    30: 30,   # Trimshamsha — libaditya has no -30; parivritti fallback
    40: -40,  # Khavedamsha
    45: -45,  # Akshavedamsha
    60: -60,  # Shashtyamsha
}


def get_varga_name(varga_number: int) -> str:
    return VARGA_NAMES.get(varga_number, f"D-{varga_number}")


def is_varga_implemented(varga_number: int) -> bool:
    return varga_number in VARGA_NAMES


def to_libaditya_varga_code(gui_varga_number: int) -> int:
    """Translate the GUI's varga number to libaditya's Chart.varga(N) code."""
    return _GUI_TO_LIBADITYA_VARGA.get(gui_varga_number, gui_varga_number)


VARGA_STYLES = {
    "classical": {
        "label": "Classical (Parashara)",
        "short": "Classical",
        "overrides": {},
    },
    "parivritti": {
        "label": "Parivritti (cyclic)",
        "short": "Parivritti",
        "overrides": {
            2: (2, "D2p"),
            3: (3, "D3p"),
            4: (4, "D4p"),
        },
    },
    "reversed": {
        "label": "Reversed variants",
        "short": "Reversed",
        "overrides": {
            10: (-100, "D10r"),
            24: (-240, "D24s"),
        },
    },
}

VARGA_STYLE_ORDER = ["classical", "parivritti", "reversed"]


def get_varga_overrides(style_key):
    """Return the amsha overrides dict for a given varga style.

    Each override maps gui_code -> (libaditya_amsha, display_label).
    Vargas not in the overrides dict use the default classical mapping.
    """
    style = VARGA_STYLES.get(style_key)
    if not style:
        return {}
    return style["overrides"]


def to_libaditya_varga_code_styled(gui_varga_number, style_key="classical"):
    """Like to_libaditya_varga_code but applies style overrides first."""
    overrides = get_varga_overrides(style_key)
    if gui_varga_number in overrides:
        return overrides[gui_varga_number][0]
    return _GUI_TO_LIBADITYA_VARGA.get(gui_varga_number, gui_varga_number)


def get_varga_display_label(gui_varga_number, style_key="classical"):
    """Return the display label for a varga under the given style.

    Classical mode: 'D1', 'D2', etc.
    Parivritti mode: 'D2p', 'D3p' for overridden vargas.
    Reversed mode: 'D10r', 'D24s' for overridden vargas.
    """
    overrides = get_varga_overrides(style_key)
    if gui_varga_number in overrides:
        return overrides[gui_varga_number][1]
    return f"D{gui_varga_number}"
