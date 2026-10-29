# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""Prebuilt Jewel Lamp (V2) layers kept between draws (SPEC-RST-001 §4.6, td-9scg9 review).

Geometry, raw Look, aim, theme, scale and palette variant identify shared Qt layers.
A palette transition drops old brushes; otherwise least-used entries go past LIMIT.
"""
from collections import OrderedDict
from ui.qt_theme import sat_key

LIMIT = 4096
_CACHE: "OrderedDict[tuple, list]" = OrderedDict()
_VARIANT = None

def _round(*values):
    return tuple(round(float(v), 4) for v in values)

def cell_key(cell) -> tuple:
    """A cell's geometry as a key: ``('r', x, y, w, h, radius)`` or ``('s', cx, cy, r0, r1, a0, a1)``."""
    rect = getattr(cell, 'rect', None)
    if rect is not None:
        return ('r',) + _round(rect.x(), rect.y(), rect.width(), rect.height(), cell.radius)
    return ('s',) + _round(cell.cx, cell.cy, cell.r0, cell.r1, cell.a0, cell.a1)

def layers(cell, look, aim, light_theme, px):
    """``jewel_lamp_items.layers`` through the cache."""
    global _VARIANT
    variant = sat_key()
    if variant != _VARIANT:
        clear()                         # bounded memory, also on a palette transition
        _VARIANT = variant
    key = (cell_key(cell), look, _round(*aim), bool(light_theme), round(float(px), 6), variant)
    fills = _CACHE.get(key)
    if fills is not None:
        _CACHE.move_to_end(key)
        return fills
    from apps.widgets import jewel_lamp_items as jli
    fills = jli.layers(cell, look, aim, light_theme, px)
    _CACHE[key] = fills
    if len(_CACHE) > LIMIT:
        _CACHE.popitem(last=False)
    return fills

def clear():
    _CACHE.clear()
