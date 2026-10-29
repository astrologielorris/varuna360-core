# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The one hint-text colour of the Settings pages.

Every italic description under a Settings row (Appearance, Chart Display,
Zodiac & Calculation, the folders page, Pro's General page) is styled here and
nowhere else. Before this, the pages used three recipes: a fixed ``#888``, a
fixed ``#aaa`` and the theme text colour baked once at construction. The baked
one never followed a theme switch, so a page built under a light theme kept
dark grey hints on a dark background (and white hints on a light one).

The colour is the theme text blended toward the page ground, so it reads as a
quieter tier than the row labels on every theme, edited themes included, and
:func:`refresh_hints` repaints it on a live theme switch.
"""
from __future__ import annotations

import re

from ui.qt_theme import _mix, get_theme_colors, is_light_theme, scaled_area_px

HINT_PROPERTY = "_settings_hint"

# How far the hint ink sits from the ground toward the text colour. Dark themes
# text is white, so 0.70 is a clear grey (about 6:1 rendered); light themes text
# is already a grey (#555555), and thin italic strokes render lighter than the
# token, so light hints keep the full text colour.
_DARK_WEIGHT = 0.70
_LIGHT_WEIGHT = 1.0

_COLOR_RE = re.compile(r"(?<![-\w])color\s*:\s*[^;]+;")


def hint_color() -> str:
    """The live hint ink: theme text blended toward the page ground."""
    theme = get_theme_colors()
    weight = _LIGHT_WEIGHT if is_light_theme() else _DARK_WEIGHT
    return _mix(theme["secondary_dark"], theme["secondary_text"], weight)


def hint_style(area: str = "info_text", extra: str = "") -> str:
    """The QSS of a hint label: hint ink, italic, the font area's size.
    Every Settings hint uses the ``info_text`` area so they share one size."""
    return (f"color: {hint_color()}; font-style: italic; "
            f"font-size: {scaled_area_px(area)}px;{(' ' + extra) if extra else ''}")


def mark(label):
    """Flag ``label`` as a hint so :func:`refresh_hints` repaints it."""
    label.setProperty(HINT_PROPERTY, True)
    return label


def style(label, area: str = "info_text", extra: str = ""):
    """Style ``label`` as a hint and flag it. Returns the label."""
    label.setStyleSheet(hint_style(area, extra))
    return mark(label)


def refresh_hints(root) -> None:
    """Re-ink every flagged hint under ``root`` from the live theme, keeping the
    rest of each label's stylesheet (font size, margins) as it is."""
    from PySide6.QtWidgets import QLabel
    ink = f"color: {hint_color()};"
    for label in root.findChildren(QLabel):
        if not label.property(HINT_PROPERTY):
            continue
        css = label.styleSheet()
        new = _COLOR_RE.sub(ink, css, count=1) if _COLOR_RE.search(css) else f"{ink} {css}"
        if new != css:
            label.setStyleSheet(new)
