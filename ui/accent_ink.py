# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under the GNU AGPL-3.0. See LICENSE at the repository root.
"""Readable ink for every theme (SPEC-THM-001 §13).

qt-material's ``primaryTextColor`` has TWO jobs at once: it is the text of
every input, list and combo on the GROUND, and the text on a ``primaryColor``
FILL (selected rows, checked buttons, the list selection). No single colour
does both on a bright accent: white on Dark Amber's #ffd740 reads 1.4:1, and
the dark ink the app used to force there (#212121) reads 1.4:1 on the dark
ground, which is what made Dark Amber / Yellow / Orange unreadable.

So the two jobs are split:

* the theme XML keeps a GROUND-readable ``primaryTextColor``
  (:func:`ground_readable_text`, applied by ``desaturated_theme_path``), so the
  ~190 ``primary_text`` call sites that draw on the ground stay readable;
* every accent FILL asks :func:`on_accent_ink` for its label colour, and
  qt-material's own accent-filled selections are re-inked by
  ``ui.accent_ink_qss.accent_selection_qss``, appended to the app sheet after each
  ``apply_stylesheet``.

Lives in its own module because ``ui/qt_theme.py`` is under the SI
architecture down-only line ratchet.
"""
from __future__ import annotations

import os
import re

from PySide6.QtGui import QColor

#: The two inks on_accent_ink() falls back to. Not chrome: they are the white
#: and near-black ends of the contrast test (like the bar's literal #fff label).
ACCENT_INK_LIGHT = "#ffffff"
ACCENT_INK_DARK = "#1b1b1f"

#: The theme's own ink is kept on an accent fill down to this WCAG ratio (3:1,
#: the floor for bold UI labels). Dark Blue / Pink / Red / Purple keep their
#: white labels (3.3-4.8:1); the bright accents (teal, cyan, green, amber,
#: yellow, orange: 1.1-2.2:1 with white) switch to the dark ink, which reads
#: 8-16:1 on them.
ACCENT_INK_MIN_CONTRAST = 3.0

#: Text on the ground (input / list / combo text) is body text: WCAG AA.
GROUND_TEXT_MIN_CONTRAST = 4.5

#: The applied theme's accent ink, set by xml_palette() on every theme apply
#: (every apply goes through ui.qt_theme.desaturated_theme_path).
ACCENT_INK_ENV = "VARUNA360_ACCENT_INK"



def _qcolor(color) -> QColor:
    c = color if isinstance(color, QColor) else QColor(str(color))
    return c if c.isValid() else QColor(128, 128, 128)


def relative_luminance(color) -> float:
    """WCAG 2.x relative luminance of a hex string or QColor (0..1)."""
    c = _qcolor(color)

    def lin(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(c.red()) + 0.7152 * lin(c.green()) + 0.0722 * lin(c.blue())


def contrast_ratio(fg, bg) -> float:
    """WCAG 2.x contrast ratio between two colours (1..21); alpha ignored."""
    a, b = relative_luminance(fg), relative_luminance(bg)
    hi, lo = (a, b) if a >= b else (b, a)
    return (hi + 0.05) / (lo + 0.05)


def _hex(color) -> str:
    return color if isinstance(color, str) else _qcolor(color).name()


def _applied_accent_ink():
    """The accent ink xml_palette() recorded, only while that theme is the one
    qt-material applied (QTMATERIAL_THEME is its file or a generated variant
    named after it), so a theme applied some other way never reads a stale one."""
    stem, _, ink = os.environ.get(ACCENT_INK_ENV, "").partition(":")
    applied = os.path.basename(os.environ.get("QTMATERIAL_THEME", ""))
    return ink if stem and ink and applied.startswith(stem) else None


def on_accent_ink(fill=None, preferred=None,
                  min_ratio: float = ACCENT_INK_MIN_CONTRAST) -> str:
    """The label colour (hex) for text drawn ON an accent fill.

    ``fill`` defaults to the live ``primary``; ``preferred`` to the live
    ``primary_text`` (the theme's own ink). The preferred ink is kept while it
    reads at ``min_ratio`` on the fill; otherwise the better of the light and
    dark inks wins. Call it at paint / style time, never cache the result in a
    widget, so a theme switch recomputes it.
    """
    from ui.qt_theme import get_theme_colors
    theme = get_theme_colors()
    fill = _hex(fill if fill is not None else theme["primary"])
    preferred = _hex(preferred if preferred is not None else theme["primary_text"])
    # The applied theme's ACCENT ink (the editor's "Text on accent", or the
    # shipped dark ink of Dark Amber / Yellow / Orange) comes first: the XML's
    # primaryTextColor may have been replaced by the ground ink (xml_palette).
    for ink in (_applied_accent_ink(), preferred):
        if ink and QColor(ink).isValid() and contrast_ratio(ink, fill) >= min_ratio:
            return _hex(ink)
    # White first (Material's convention on mid-tone accents, and the bar
    # mockup's own label); the dark ink only where white cannot read.
    light = contrast_ratio(ACCENT_INK_LIGHT, fill)
    if light >= min_ratio:
        return ACCENT_INK_LIGHT
    dark = contrast_ratio(ACCENT_INK_DARK, fill)
    return ACCENT_INK_LIGHT if light >= dark else ACCENT_INK_DARK


def ground_readable_text(ink, grounds, fallback,
                         min_ratio: float = GROUND_TEXT_MIN_CONTRAST) -> str:
    """``ink`` when it reads at ``min_ratio`` on every colour in ``grounds``,
    else ``fallback`` (the theme's own text colour) if that reads, else the
    best-reading of white / the dark ink / the fallback. Used when a theme XML is
    written, so qt-material's input / list text never inherits an ink that was
    picked for an accent fill."""
    grounds = [g for g in grounds if g and QColor(str(g)).isValid()]

    def worst(c):
        return min((contrast_ratio(c, g) for g in grounds), default=21.0)
    if worst(ink) >= min_ratio:
        return ink
    if fallback and QColor(str(fallback)).isValid() and worst(fallback) >= min_ratio:
        return fallback
    # A saved palette can break both (e.g. a white ground with white text):
    # the better of the two inks on the worst ground.
    return max((ACCENT_INK_LIGHT, ACCENT_INK_DARK, fallback or ink), key=worst)


def xml_palette(theme_file, applied: bool = True) -> dict:
    """The palette overrides written into a generated theme XML.

    ``ui.theme_palette.transformed_palette`` gives ``primaryTextColor`` as the
    ACCENT ink (the editor's "Text on accent", and the shipped dark ink of
    Dark Amber / Yellow / Orange). qt-material also inks every input, list and
    combo on the GROUND with that key, so here it is kept only when it reads
    on the ground too; otherwise the theme's own text colour takes its place.
    Accent fills get their ink from :func:`on_accent_ink` instead, which
    reads the accent ink recorded here in ``ACCENT_INK_ENV``.
    """
    from ui.theme_palette import theme_base_palette, transformed_palette
    palette = transformed_palette(theme_file, applied=applied)
    ink = palette.get("primaryTextColor")
    if ink:
        stem = os.path.splitext(os.path.basename(str(theme_file)))[0]
        os.environ[ACCENT_INK_ENV] = f"{stem}:{ink}"   # read by on_accent_ink()
    else:
        os.environ.pop(ACCENT_INK_ENV, None)
        return palette
    full = {**theme_base_palette(theme_file), **palette}
    fallback = full.get("secondaryTextColor") or ink
    grounds = (full.get("secondaryDarkColor"), full.get("secondaryColor"))
    palette["primaryTextColor"] = ground_readable_text(ink, grounds, fallback)
    return palette


def has_xml_override(theme_file) -> bool:
    """True when ``theme_file`` needs a generated XML for its palette: the user
    saved an applied override, or it ships a dark accent ink (DARK_ACCENT_INK)."""
    from ui.theme_palette import DARK_ACCENT_INK, theme_override
    return (bool(theme_override(theme_file, applied=True))
            or os.path.basename(str(theme_file)) in DARK_ACCENT_INK)


#: qt-material's stock Dark Blue accent pair. The action bar's dark mockup was
#: drawn for this theme, so on it the bar keeps the mockup's own blue.
_STOCK_DARK_BLUE = ("#448aff", "#83b9ff")


def dark_bar_pure(frozen: dict) -> dict:
    """The bar's eight pure keys on a DARK theme (``ui.qt_theme._build_bar_tokens``).

    ``frozen`` is the mockup's dark table (already desaturated). The surface
    family (``secondary*``) stays the mockup's: the bar owns its material. The
    ACCENT family (``primary``, ``primary_dark``, ``primary_light``) and
    ``primary_text`` follow the live theme, so a checked TRANSIT, the ADD CHART
    label and every focus ring take the theme's accent. On stock Dark Blue the
    mockup's blue is kept, which is what the bar was drawn and gated in.
    """
    from ui.qt_theme import _desat_hex_at, get_theme_colors, get_ui_saturation
    live = get_theme_colors()
    pure = dict(frozen)
    pure["primary_text"] = live["primary_text"]
    sat = get_ui_saturation()
    stock = tuple(_desat_hex_at(c, sat).lower() for c in _STOCK_DARK_BLUE)
    if (live["primary"].lower(), live["primary_light"].lower()) != stock:
        for key in ("primary", "primary_dark", "primary_light"):
            pure[key] = live[key]
    return pure
