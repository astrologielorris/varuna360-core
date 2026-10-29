# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
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
    # td-m6xyo (SPEC-DIG-001): the Parivritti D2/D3/D4, drawn when the varga
    # style is Parivritti; sentinel numbers like 1010 / 2424.
    202: "Hora-P", 303: "Drekkana-P", 404: "Chaturthamsa-P",
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
    202: 2,   # Hora Parivritti (style Parivritti, SPEC-DIG-001)
    303: 3,   # Drekkana Parivritti
    404: 4,   # Chaturthamsha Parivritti
}


def get_varga_name(varga_number: int) -> str:
    return VARGA_NAMES.get(varga_number, f"D-{varga_number}")


def is_varga_implemented(varga_number: int) -> bool:
    return varga_number in VARGA_NAMES


_LIBADITYA_TO_GUI_VARGA = {v: k for k, v in _GUI_TO_LIBADITYA_VARGA.items()}

# The GUI shows two vargas under a suffixed name: the reverse variants, which
# carry sentinel numbers (1010, 2424) rather than real divisions.
_VARGA_DISPLAY_LABEL = {1010: "10R", 2424: "24R", 202: "2p", 303: "3p", 404: "4p"}


def from_libaditya_varga_code(varga_code) -> int:
    """Inverse of to_libaditya_varga_code. None (the rashi) maps to 1."""
    if varga_code is None:
        return 1
    return _LIBADITYA_TO_GUI_VARGA.get(varga_code, varga_code)


def varga_display_label(gui_varga_number: int) -> str:
    """What the user sees for this varga: "9", "10R", "60".

    Single source of truth for the suffixed reverse variants — the varga
    column used to spell them inline, and the center-box label needs the
    same strings or the column and the chart would disagree.
    """
    return _VARGA_DISPLAY_LABEL.get(gui_varga_number, str(gui_varga_number))


def to_libaditya_varga_code(gui_varga_number: int) -> int:
    """Translate the GUI's varga number to libaditya's Chart.varga(N) code."""
    return _GUI_TO_LIBADITYA_VARGA.get(gui_varga_number, gui_varga_number)


# The style names on screen are the registry's choice labels of chart.varga_style,
# in the UI language (varga_style_short); this table holds codes only.
VARGA_STYLES = {
    "classical": {
        "overrides": {},
    },
    "parivritti": {
        "overrides": {
            2: (2, "D2p"),
            3: (3, "D3p"),
            4: (4, "D4p"),
        },
    },
    "reversed": {
        "overrides": {
            10: (-100, "D10r"),
            24: (-240, "D24s"),
        },
    },
}

VARGA_STYLE_ORDER = ["classical", "parivritti", "reversed"]
VARGA_TABLE = "table"   # SPEC-DIG-001 D-10: the VARGA panel's All vargas view
VARGA_VIEW_KEY = "chart.varga_panel_view"


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


# ---------------------------------------------------------------------------
# td-m6xyo (SPEC-DIG-001 §4.3): the varga style is ONE state (setting
# ``chart.varga_style``) shared by the varga column, the VARGA panel, the chart
# and render_chart. The column shows 16 base numbers; the style turns a base
# number into the GUI code the chart draws (10 + Reversed -> 1010 "10R").
VARGA_STYLE_KEY = "chart.varga_style"
COLUMN_VARGAS = [1, 2, 3, 4, 7, 9, 10, 12, 16, 20, 24, 27, 30, 40, 45, 60]
_STYLE_GUI_CODES = {
    "classical": {},
    "parivritti": {2: 202, 3: 303, 4: 404},
    "reversed": {10: 1010, 24: 2424},
}
_STYLED_TO_BASE = {code: base for table in _STYLE_GUI_CODES.values()
                   for base, code in table.items()}


def styled_gui_varga(base, style_key="classical"):
    """The GUI varga code the chart draws for the column number ``base`` under
    ``style_key``. An explicit styled code (1010, 202) is kept as it is."""
    if base in _STYLED_TO_BASE:
        return base
    return _STYLE_GUI_CODES.get(style_key, {}).get(base, base)


def base_gui_varga(code):
    """The column number of a GUI varga code: 1010 -> 10, 202 -> 2, 9 -> 9."""
    return _STYLED_TO_BASE.get(code, code)


def style_of_gui_varga(code):
    """The style a styled code belongs to ('reversed' for 1010), else None."""
    for key, table in _STYLE_GUI_CODES.items():
        if code in table.values():
            return key
    return None


def style_touches(base, style_key):
    """True when ``style_key`` changes the varga drawn for column ``base``."""
    return base in _STYLE_GUI_CODES.get(style_key, {})


def column_label(base, style_key="classical"):
    """What the varga column button shows under the style: "2p", "10R", "9"."""
    return varga_display_label(styled_gui_varga(base, style_key))


def next_varga_style(style_key):
    """Classical -> Parivritti -> Reversed -> Classical."""
    i = VARGA_STYLE_ORDER.index(style_key) if style_key in VARGA_STYLE_ORDER else -1
    return VARGA_STYLE_ORDER[(i + 1) % len(VARGA_STYLE_ORDER)]


def varga_style_short(style_key):
    """"Classical" / "Parivritti" / "Reversed" / "All vargas" (the table view):
    the registry's choice label, in the UI language (SPEC-LOC-002)."""
    from core.i18n import t
    from core.settings_registry.labels import value_label
    key = VARGA_VIEW_KEY if style_key == VARGA_TABLE else VARGA_STYLE_KEY
    value = style_key if style_key == VARGA_TABLE or style_key in VARGA_STYLES else "classical"
    return t(f"settings.{key}.choice.{value}", value_label(key, value))


def gui_varga_code_label(code):
    """The varga code the panel header shows: "D1", "D10r", "D24s", "D2p"."""
    style = style_of_gui_varga(code)
    return f"D{code}" if style is None else get_varga_display_label(base_gui_varga(code), style)
