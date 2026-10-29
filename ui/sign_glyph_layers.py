# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Recolour and layer helpers for the vector sign SVGs.

They handle strokes AND fills, so a filled symbol (the calligraphic Capricorn)
takes a view's ink or a user colour scheme exactly like the line symbols.
"""
import copy

PAINTED = ('stroke', 'fill')


def ink_all(root, ink):
    """Recolour every painted stroke and fill under ``root``."""
    for node in root.iter():
        for attr in PAINTED:
            if node.get(attr) not in (None, 'none'):
                node.set(attr, ink)


def layer(group, color, scale):
    """A copy of ``group`` in ``color`` with its strokes scaled by ``scale``.
    On a widened (outer frame) layer a filled shape gets an outline, so a
    two-tone scheme frames it the way it frames the line symbols."""
    result = copy.deepcopy(group)
    ink_all(result, color)
    for node in result.iter():
        if node.get('stroke-width'):
            node.set('stroke-width', f"{float(node.get('stroke-width')) * scale:g}")
        elif scale > 1 and node.get('fill') not in (None, 'none'):
            node.set('stroke', color)
            node.set('stroke-width', f'{3.5 * scale:g}')
    return result
