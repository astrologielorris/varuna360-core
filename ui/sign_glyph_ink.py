# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Ink and user colour schemes for the SVG sign glyphs.

A vector sign symbol with a scheme in Settings -> SVG colors
(``display.planet_svg_colors``, keyed by the Western sign name) is drawn in that
scheme in every view: a solid colour, or two-tone (outer frame + inside line,
like the planet SVGs). Without a scheme it keeps the view's own ink (or the wood
carving). Read live, so an Apply shows on the next redraw.
"""
import xml.etree.ElementTree as ET
from functools import lru_cache

from PySide6.QtGui import QColor

from ui.sign_display_modes import VECTOR_FILES, vector_svg
from ui.sign_glyph_layers import layer

SVG = 'http://www.w3.org/2000/svg'
# Stroke width multipliers, the planet SVGs' non-simple proportions (7 / 3.5 / 5).
OUTER, INNER, SOLID = 1.4, 0.7, 1.0


def recolor_tree(root, ink_str):
    """Apply flat ink and report whether the SVG declares a colour stroke."""
    has_explicit_stroke = False
    for node in root.iter():
        for attribute in ('fill', 'stroke'):
            value = node.get(attribute)
            if not value or value == 'none':
                continue
            is_colour = value == 'currentColor' or QColor(value).isValid()
            if is_colour:
                node.set(attribute, ink_str)
            if attribute == 'stroke' and is_colour:
                has_explicit_stroke = True
    return has_explicit_stroke


def sign_scheme(index):
    """The user's scheme for vector sign #index, or None (keep the view ink)."""
    from managers.settings_manager import get_settings
    if not 0 <= index < len(VECTOR_FILES):
        return None
    colors = get_settings().get('display.planet_svg_colors', {})
    return clean_scheme(colors.get(VECTOR_FILES[index])) if isinstance(colors, dict) else None


@lru_cache(maxsize=128)
def _scheme_svg(index, scheme_key):
    data = vector_svg(index)
    if data is None:
        return None
    root = ET.fromstring(data)
    groups = [g for g in root if g.tag == f'{{{SVG}}}g']
    for group in groups:
        root.remove(group)
    kind, first, second = scheme_key
    for group in groups:
        if kind == 'solid':
            root.append(layer(group, first, SOLID))
        else:
            root.append(layer(group, first, OUTER))
    if kind == 'pair':
        for group in groups:
            root.append(layer(group, second, INNER))
    return ET.tostring(root)


def scheme_svg(index, scheme):
    """Vector sign #index drawn in ``scheme`` (a colour or {outer, inner})."""
    scheme = clean_scheme(scheme)
    if scheme is None:
        return vector_svg(index)
    key = (('solid', scheme, None) if isinstance(scheme, str)
           else ('pair', scheme['outer'], scheme['inner']))
    return _scheme_svg(index, key)


def vector_passes(index, ink, finish):
    """South Indian (svg, offset, alpha) passes for vector sign #index: the
    user scheme if set, else carved (lit edge + dark groove) on a wood finish,
    else flat in ``ink``."""
    from ui.qt_theme import desat_hex
    from ui.south_indian_finishes import WOOD
    carve = WOOD.get(finish, {}).get('carve')
    if carve is None or sign_scheme(index) is not None:
        data = sign_svg(index, ink)
        return ((data, 0, 1.0),) if data else None
    passes = tuple((data, offset, alpha) for data, offset, alpha in (
        (vector_svg(index, desat_hex(carve['lit'])), 1.0, .52),
        (vector_svg(index, desat_hex(carve['dark'])), 0, .88)) if data)
    return passes or None


def sign_svg(index, ink):
    """What a view draws for vector sign #index: the user scheme, else its ink."""
    scheme = sign_scheme(index)
    return scheme_svg(index, scheme) if scheme is not None else vector_svg(index, ink)


# Imported last: apps.widgets' package init reaches aditya_glyph_render, which imports
from apps.widgets.planet_icon_palette import clean_scheme  # noqa: E402 (this module back)
