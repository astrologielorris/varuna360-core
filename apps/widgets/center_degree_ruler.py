# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""The degree ruler of the center drawings (SPEC-VAC-001 §4.0): on the outer side of the
track, a tick at every degree of each sign (longer at 5 and 10) and the numbers 10 and 20,
painted with the frame when ``chart.center_degree_numbers`` is on. The degree in the sign
is the bearing modulo 30 (``theta = L - 30``), so the ruler fits every zodiac frame."""
from __future__ import annotations

from typing import Mapping

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QFont, QPainter, QPainterPath, QPen

from core import center_geometry as cg

KEY = "chart.center_degree_numbers"
STEPS = ((10, 16.0, 2.0, .85), (5, 11.0, 1.6, .75), (1, 6.0, 1.1, .60))  # every, length, pen, alpha
NUMBERS = (10, 20)
NUMBER_PX = 26
NUMBER_GAP = 38.0               # number center, out from the track (a stud covers 30)
_PATHS = {}                     # tick paths per step, built on first use


def ruler_on() -> bool:
    from core import settings_registry as registry
    from managers.settings_manager import get_settings
    return bool(get_settings().get(KEY, registry.default(KEY)))


def tick_path(every: int, length: float) -> QPainterPath:
    """Ticks at the degrees that are multiples of ``every`` (and of no longer step), never
    on a sign boundary (its ray is there), built once per process."""
    if every not in _PATHS:
        path = QPainterPath()
        longer = [s[0] for s in STEPS if s[0] > every]
        for deg in range(0, 360, every):
            if deg % 30 == 0 or any(deg % step == 0 for step in longer):
                continue
            t = cg.track_radius(float(deg))
            path.moveTo(*cg.point_on_ray(float(deg), t))
            path.lineTo(*cg.point_on_ray(float(deg), t + length))
        _PATHS[every] = path
    return _PATHS[every]


def paint_ruler(p: QPainter, pal: Mapping):
    """The ticks in the frame line colour, the numbers in the tick ink, upright."""
    if not ruler_on():
        return
    from apps.widgets.center_drawing_paint import colour
    p.setBrush(Qt.BrushStyle.NoBrush)
    for every, length, width, alpha in STEPS:
        p.setPen(QPen(colour(pal["line"], alpha), width))
        p.drawPath(tick_path(every, length))
    font = QFont()
    font.setBold(True)
    font.setPixelSize(NUMBER_PX)
    p.setFont(font)
    p.setPen(colour(pal["tick"], .80))
    half = NUMBER_PX
    for sign in range(12):
        for deg in NUMBERS:
            th = sign * 30.0 + deg
            x, y = cg.point_on_ray(th, cg.track_radius(th) + NUMBER_GAP)
            p.drawText(QRectF(x - half, y - half, 2 * half, 2 * half),
                       Qt.AlignmentFlag.AlignCenter, str(deg))
