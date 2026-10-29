# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""Painting helpers for the nakshatra property outer ring (Core and Lite).

The nakshatra wheel's summary ring (apps/widgets/nakshatra_summary_layer.py)
and Pro's Antikythera map layers share these: the annulus wedge path, the polar
point, the summary word wrap and the Gunas colour pairs.
"""
import math

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainterPath

# Self-contained, high-contrast pairs are legible in either application theme.
GUNA_COLORS = {'Rajasic': '#e3bd64', 'Tamasic': '#702c45', 'Sattvic': '#78add6', None: '#d0d2d4'}
GUNA_TEXT = {'Rajasic': '#18232b', 'Tamasic': '#fff4f6', 'Sattvic': '#18232b', None: '#18232b'}


def ring_point(center, radius, angle):
    rad = math.radians(angle)
    return center + radius*math.cos(rad), center - radius*math.sin(rad)


def annulus_path(center, inner, outer, start, width):
    path = QPainterPath()
    path.moveTo(*ring_point(center, inner, start))
    path.lineTo(*ring_point(center, outer, start))
    path.arcTo(QRectF(center-outer, center-outer, 2*outer, 2*outer), start, width)
    path.lineTo(*ring_point(center, inner, start+width))
    path.arcTo(QRectF(center-inner, center-inner, 2*inner, 2*inner), start+width, -width)
    path.closeSubpath()
    return path


def wrap_summary(value, metrics, width, max_lines=3):
    """Fit short summaries without shrinking the font; retain full tooltip text."""
    lines, current, truncated = [], '', False
    for word in (value or '—').split():
        candidate = (current+' '+word).strip()
        if current and metrics.horizontalAdvance(candidate) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines-1] + [' '.join(lines[max_lines-1:])]
        truncated = True
    for index, line in enumerate(lines):
        if metrics.horizontalAdvance(line) > width:
            lines[index] = metrics.elidedText(line, Qt.ElideRight, width)
            truncated = True
    return '\n'.join(lines), truncated
