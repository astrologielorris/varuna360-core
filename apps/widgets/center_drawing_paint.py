# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""Painting shared by the drawings in the South Indian center (SPEC-VAC-001 §4.0).

The loom frame with its nails, the squircle track (built once per process), the sign
nails and rays, the exact-degree ticks / pins / leaders and the studs, from the Qt-free
geometry of ``core.center_geometry``. A drawing passes its own fill for the frame (the
Tajika frosted veil) and its own stud ring; everything else is painted the same way for
every drawing (SPEC-TJK-003 §3.7).

Functions only: the drawing items (``TajikaCenterItem``) own their state and call these
from ``paint``.
"""
from __future__ import annotations

from typing import Callable, Iterable, Mapping, Optional, Sequence

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QRadialGradient

from apps.widgets.center_degree_ruler import paint_ruler
from core import center_geometry as cg
from core.strength_stone import BLACK, WHITE, mix
from ui.qt_theme import desat_hex

# Stud metals (named material constants, SPEC-TJK-003 §3.7): (highlight, body, rim
# stop), stroke.
CHAMPAGNE = ("#FFFEFA", "#EBE4D4", "#A79E8A", "#81796A")
PEWTER = ("#F6F7F8", "#C4C9CD", "#7A8187", "#6D747A")
BRASS = "#B08D57"

_TRACK = []                      # the squircle track path, built on first use


def colour(hex_value: str, alpha: float = 1.0) -> QColor:
    """A material or theme colour, desaturated once (SPEC-SAT-001), with ``alpha``."""
    col = QColor(desat_hex(hex_value))
    col.setAlphaF(max(0.0, min(1.0, alpha)))
    return col


def is_light() -> bool:
    from apps.delegates.highlight_delegate import AvasthaHighlightDelegate
    return AvasthaHighlightDelegate._is_light_theme()


def track_path() -> QPainterPath:
    """The squircle track (points every 2 degrees, closed), built once per process."""
    if not _TRACK:
        track = QPainterPath()
        for i in range(0, 361, 2):
            pt = cg.point_on_ray(float(i), cg.track_radius(float(i)))
            track.moveTo(*pt) if i == 0 else track.lineTo(*pt)
        track.closeSubpath()
        _TRACK.append(track)
    return _TRACK[0]


def frame_rect(rect: QRectF) -> QRectF:
    """The loom frame: ``center_rect()`` inset by FRAME_INSET."""
    return rect.adjusted(cg.FRAME_INSET, cg.FRAME_INSET, -cg.FRAME_INSET, -cg.FRAME_INSET)


def paint_frame(p: QPainter, rect: QRectF, pal: Mapping,
                fill: Optional[Callable[[QPainter, QRectF], None]] = None):
    """Fill (the drawing's own), loom frame, nails, track, sign rays and nails, ruler."""
    r = frame_rect(rect)
    if fill is not None:
        fill(p, r)
    line = colour(pal["line"], .75)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(line, 2.0))
    p.drawRoundedRect(r, cg.FRAME_RADIUS, cg.FRAME_RADIUS)
    _paint_frame_nails(p, r, pal)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(colour(pal["line"], .80), 2.2))
    p.drawPath(track_path())
    _paint_sign_boundaries(p, r.width(), pal)
    paint_ruler(p, pal)


def _paint_frame_nails(p: QPainter, r: QRectF, pal: Mapping):
    """Nails along the frame, evenly spaced (step = side / 21.5)."""
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(colour(pal["line"], .65))
    side, step = r.width(), r.width() / 21.5
    k = step
    while k <= side - step * 0.9:
        for x, y in ((r.left() + k, r.top()), (r.left() + k, r.bottom()),
                     (r.left(), r.top() + k), (r.right(), r.top() + k)):
            p.drawEllipse(QPointF(x, y), cg.FRAME_NAIL_R, cg.FRAME_NAIL_R)
        k += step


def _paint_sign_boundaries(p: QPainter, side: float, pal: Mapping):
    """Sign boundaries: a faint ray to the frame and a nail on the track."""
    ray_pen = QPen(colour(pal["line"], .30), 1.6)
    for k30 in range(12):
        th = k30 * 30.0
        t0 = cg.track_radius(th)
        ux, uy = cg.ray(th)
        t1 = (side / 2) / max(abs(ux), abs(uy))
        p.setPen(ray_pen)
        p.drawLine(QPointF(*cg.point_on_ray(th, t0)), QPointF(*cg.point_on_ray(th, t1)))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(colour(pal["line"], .90))
        p.drawEllipse(QPointF(*cg.point_on_ray(th, t0)), cg.BOUNDARY_NAIL_R, cg.BOUNDARY_NAIL_R)
        p.setBrush(Qt.BrushStyle.NoBrush)


def paint_marks(p: QPainter, bodies: Iterable, tick_hex: str):
    """The exact degree of every body: a tick across the track; for a pushed stud a
    brass leader from the exact point and a brass pin on it."""
    for b in bodies:
        t = b.track_r
        p.setPen(QPen(colour(tick_hex, .85), 2.2))
        p.drawLine(QPointF(*cg.point_on_ray(b.theta, t - cg.TICK_IN)),
                   QPointF(*cg.point_on_ray(b.theta, t + cg.TICK_OUT)))
        if b.push_level:
            p.setPen(QPen(colour(BRASS, .9), 2.0))
            p.drawLine(QPointF(*b.exact), QPointF(*b.stud))
            p.setPen(QPen(colour(mix(BRASS, BLACK, .35)), 1.2))
            p.setBrush(colour(BRASS))
            p.drawEllipse(QPointF(*b.exact), cg.PIN_R, cg.PIN_R)


# ------------------------------------------------------------------ studs
def paint_stud_halo(p: QPainter, x: float, y: float, r: float, accent: str):
    """A lit body (its key pressed): accent glow and two accent rings."""
    halo = QRadialGradient(QPointF(x, y), r + 26)
    halo.setColorAt(0.0, colour(accent, .45))
    halo.setColorAt(1.0, colour(accent, 0.0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(halo))
    p.drawEllipse(QPointF(x, y), r + 26, r + 26)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(colour(accent, .30), 3.0))
    p.drawEllipse(QPointF(x, y), r + 10, r + 10)
    p.setPen(QPen(colour(accent), 4.5))
    p.drawEllipse(QPointF(x, y), r + 4, r + 4)


def paint_stud_body(p: QPainter, x: float, y: float, r: float, metal: Sequence[str],
                    rim_dark: float):
    """Shadow (concentric alpha-stepped discs, no QGraphicsEffect) and the metal disc."""
    p.setPen(Qt.PenStyle.NoPen)
    for k, a_ in ((3.0, .10), (1.5, .14), (0.0, .18)):
        p.setBrush(colour("#3A2C18", a_))
        p.drawEllipse(QPointF(x, y + 4), r + k, r + k)
    hi, body_hex, rim, stroke = metal
    if rim_dark:
        rim, stroke = mix(rim, BLACK, rim_dark), mix(stroke, BLACK, rim_dark)
    g = QRadialGradient(QPointF(x - .24 * r, y - .40 * r), r * 1.56)
    g.setColorAt(0.0, colour(hi))
    g.setColorAt(0.45, colour(body_hex))
    g.setColorAt(1.0, colour(rim))
    p.setBrush(QBrush(g))
    p.setPen(QPen(colour(stroke), 1.6))
    p.drawEllipse(QPointF(x, y), r, r)


def paint_stud_ring(p: QPainter, x: float, y: float, r: float, body=None):
    """The white inner ring at r - 5 (the Tajika stud ring; ``body`` unused here)."""
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(colour(WHITE, .6), 1.2))
    p.drawEllipse(QPointF(x, y), r - 5, r - 5)


def paint_stud_code(p: QPainter, x: float, y: float, r: float, font: QFont, code: str,
                    text_hex: str):
    """The body code with a white emboss one unit below."""
    p.setFont(font)
    box = QRectF(x - r, y - r, 2 * r, 2 * r)
    p.setPen(colour(WHITE, .7))
    p.drawText(box.translated(0, 1.2), Qt.AlignmentFlag.AlignCenter, code)
    p.setPen(colour(text_hex))
    p.drawText(box, Qt.AlignmentFlag.AlignCenter, code)


def code_font(code_px: int) -> QFont:
    font = QFont()
    font.setBold(True)
    font.setPixelSize(code_px)
    return font


def paint_studs(p: QPainter, bodies: Mapping, order: Sequence[str], codes: Mapping[str, str],
                *, faded, lit, accent: str, rim_dark: float, text_hex: str, font: QFont,
                scale: float = 1.0, ring=paint_stud_ring):
    """Every stud, earlier priority painted on top; faded / lit as SPEC-TJK-003 §3.5.
    ``scale`` < 0.99 (the switch-on pop) paints no code."""
    for name in reversed(order):
        b = bodies.get(name)
        if b is None:
            continue
        x, y = b.stud
        r = cg.STUD_R * scale
        p.setOpacity(cg.FADED_OPACITY if name in faded else 1.0)
        if name in lit:
            paint_stud_halo(p, x, y, r, accent)
        paint_stud_body(p, x, y, r, PEWTER if b.pewter else CHAMPAGNE, rim_dark)
        ring(p, x, y, r, b)
        if scale >= 0.99:
            paint_stud_code(p, x, y, r, font, codes[name], text_hex)
    p.setOpacity(1.0)
