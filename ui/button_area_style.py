# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under the GNU AGPL-3.0. See LICENSE at the repository root.
"""Area-aware wrapper for the shared 3D button style (td-to202 part C).

`get_3d_button_style` (ui/qt_theme.py) sets the button font from the Display
Scale only, so text-bearing 3D buttons -- the dasha level selectors 1-5, the
eclipse / Lunar-New-Year action buttons -- stayed FROZEN when only a per-area
font size changed. The right fix binds that font to the 'buttons' font area
(SPEC-FONT-001), but qt_theme.py is at its SI-decomposition ceiling and is not
edited here (same ruling as the G9d / settings_manager cases this release).

Instead this wrapper returns the unchanged qt_theme stylesheet with ONE trailing
`QPushButton { font-size: ... }` rule appended. A later rule for the same
selector wins in a Qt stylesheet, so the appended, area-bound size overrides the
Display-Scale size the base produced -- without touching qt_theme.py.

The readability floors mirror the constants in qt_theme's own size table; the
unit test asserts they still match so the two cannot drift. When qt_theme.py is
next decomposed, fold this font logic back into get_3d_button_style and drop the
wrapper (tracked in the fonts AUDIT deferred list).
"""
from ui.qt_theme import get_3d_button_style, scaled_area_px

# Readability floors, one per size, mirroring the max(...) constants in the
# qt_theme get_3d_button_style size table (small/medium max(9,..), large
# max(10,..), text scaled_px(12)). test_to202_button_font_area pins these against
# the live qt_theme output so a change there fails loudly here.
_BUTTON_FONT_FLOORS = {"small": 9, "medium": 9, "large": 10, "text": 12}


def button_area_font_px(size: str = "medium") -> int:
    """Effective font px for a text 3D button of ``size``: the 'buttons' area
    size, floored at this size's readability minimum."""
    floor = _BUTTON_FONT_FLOORS.get(size, _BUTTON_FONT_FLOORS["medium"])
    return max(floor, scaled_area_px("buttons"))


def get_3d_button_style_area(accent_name: str = "blue", size: str = "medium") -> str:
    """Like ``get_3d_button_style`` but with the button FONT bound to the
    'buttons' font area. Drop-in for text-bearing 3D buttons; icon-only buttons
    can keep the plain ``get_3d_button_style``."""
    base = get_3d_button_style(accent_name, size)
    return f"{base}\nQPushButton {{ font-size: {button_area_font_px(size)}px; }}\n"
