# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Jewel Lamp (V2) cell layers as prebuilt Qt paths and brushes (SPEC-RST-001 §4.6).

The maths is ``core.jewel_lamp`` (raw hex); every colour is desaturated ONCE here
(SPEC-SAT-001). A cell's fill stays its own item's brush; the light, the cut, the
two great rim and the burn are built at rebuild into ONE ``JewelCellItem`` per cell,
a child of the cell under its labels, whose ``paint()`` only fills prebuilt paths
(strokes are outlined once at rebuild). The parent clips it to the cell shape.

Geometry follows the mockups (``morning_prism.html``, ``rose_prism.html``): a rectangle (South
Indian) or an annular sector (wheel). ``px`` = scene pixels per mockup pixel.
"""
import math
from typing import List, NamedTuple, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QLinearGradient, QPainterPath, QPainterPathStroker,
                           QPolygonF, QRadialGradient)
from PySide6.QtWidgets import QGraphicsItem

from core import jewel_lamp as jl
from ui.qt_theme import desat_hex

TAG_JEWEL = 'rst.jewel'


def colour(value, alpha=1.0):
    out = QColor(desat_hex(value))
    out.setAlphaF(max(0.0, min(1.0, alpha)))
    return out


def stroke(path, width):
    """The filled outline of a stroke, built once (paint only fills)."""
    stroker = QPainterPathStroker()
    stroker.setWidth(width)
    stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
    stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return stroker.createStroke(path)


def polygon(points):
    path = QPainterPath()
    path.addPolygon(QPolygonF([QPointF(*p) for p in points]))
    path.closeSubpath()
    return path


def line(a, b):
    path = QPainterPath(QPointF(*a))
    path.lineTo(QPointF(*b))
    return path


def linear(a, b, stops):
    gradient = QLinearGradient(QPointF(*a), QPointF(*b))
    for offset, value, alpha in stops:
        gradient.setColorAt(offset, colour(value, alpha))
    return QBrush(gradient)


class Facet(NamedTuple):
    path: QPainterPath
    normal: Tuple[float, float]
    edge: QPainterPath        # the facet's inner edge (where the glint runs)


class Cell:
    """One cell's geometry: outline, centre, size, inset outline and facets."""

    def __init__(self, path, centre, w, h):
        self.path, self.centre, self.w, self.h = path, centre, w, h
        self.size = min(w, h)
        self.g = math.sqrt(max(w * h, 0.0))


class RectCell(Cell):
    def __init__(self, rect: QRectF, radius: float = 0.0):
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        super().__init__(path, (rect.center().x(), rect.center().y()), rect.width(), rect.height())
        self.rect, self.radius = QRectF(rect), radius

    def inset(self, b):
        rect = self.rect.adjusted(b, b, -b, -b)
        path = QPainterPath()
        path.addRoundedRect(rect, max(0.0, self.radius - b), max(0.0, self.radius - b))
        return path

    def facets(self, b) -> List[Facet]:
        x, y, X, Y = self.rect.left(), self.rect.top(), self.rect.right(), self.rect.bottom()
        return [Facet(polygon([(x, y), (X, y), (X - b, y + b), (x + b, y + b)]), (0, -1),
                      line((x + b, y + b), (X - b, y + b))),
                Facet(polygon([(X, y), (X, Y), (X - b, Y - b), (X - b, y + b)]), (1, 0),
                      line((X - b, y + b), (X - b, Y - b))),
                Facet(polygon([(X, Y), (x, Y), (x + b, Y - b), (X - b, Y - b)]), (0, 1),
                      line((X - b, Y - b), (x + b, Y - b))),
                Facet(polygon([(x, Y), (x, y), (x + b, y + b), (x + b, Y - b)]), (-1, 0),
                      line((x + b, Y - b), (x + b, y + b)))]

    def rays(self):
        return [jl.unit(self.w, self.h), jl.unit(self.w, -self.h)]


def _polar(cx, cy, r, a):
    t = math.radians(a)
    return cx + r * math.cos(t), cy - r * math.sin(t)


def wedge(cx, cy, r0, r1, a0, a1):
    """Annular sector, angles in degrees counter-clockwise (0 = right), screen y down."""
    outer, inner = QRectF(cx - r1, cy - r1, 2 * r1, 2 * r1), QRectF(cx - r0, cy - r0, 2 * r0, 2 * r0)
    path = QPainterPath()
    path.arcMoveTo(outer, a0)
    path.arcTo(outer, a0, a1 - a0)
    path.arcTo(inner, a1, a0 - a1)
    path.closeSubpath()
    return path


def arc(cx, cy, r, a0, a1):
    box = QRectF(cx - r, cy - r, 2 * r, 2 * r)
    path = QPainterPath()
    path.arcMoveTo(box, a0)
    path.arcTo(box, a0, a1 - a0)
    return path


class SectorCell(Cell):
    def __init__(self, cx, cy, r0, r1, a0, a1):
        mid, rm = (a0 + a1) / 2, (r0 + r1) / 2
        arc_len = math.radians(a1 - a0) * rm
        super().__init__(wedge(cx, cy, r0, r1, a0, a1), _polar(cx, cy, rm, mid), r1 - r0, arc_len)
        self.cx, self.cy, self.r0, self.r1, self.a0, self.a1, self.mid = cx, cy, r0, r1, a0, a1, mid

    def _da(self, b):
        return math.degrees(b / ((self.r0 + self.r1) / 2))

    def inset(self, b):
        da = self._da(b)
        return wedge(self.cx, self.cy, self.r0 + b, self.r1 - b, self.a0 + da, self.a1 - da)

    def facets(self, b) -> List[Facet]:
        cx, cy, r0, r1, a0, a1 = self.cx, self.cy, self.r0, self.r1, self.a0, self.a1
        da = self._da(b)
        A0, A1, R0, R1 = a0 + da, a1 - da, r0 + b, r1 - b
        p = lambda r, a: _polar(cx, cy, r, a)  # noqa: E731
        radial = jl.angle_aim(self.mid)
        s0 = (math.sin(math.radians(a0)), math.cos(math.radians(a0)))
        s1 = (-math.sin(math.radians(a1)), -math.cos(math.radians(a1)))
        return [Facet(wedge(cx, cy, R1, r1, a0, a1), radial, arc(cx, cy, R1, A0, A1)),
                Facet(wedge(cx, cy, r0, R0, a0, a1), (-radial[0], -radial[1]), arc(cx, cy, R0, A0, A1)),
                Facet(polygon([p(r1, a0), p(R1, A0), p(R0, A0), p(r0, a0)]), s0, line(p(R1, A0), p(R0, A0))),
                Facet(polygon([p(r1, a1), p(R1, A1), p(R0, A1), p(r0, a1)]), s1, line(p(R1, A1), p(R0, A1)))]

    def rays(self):
        er, a = jl.angle_aim(self.mid), math.radians(self.mid)
        et = (-math.sin(a), -math.cos(a))
        return [jl.unit(er[0] + et[0], er[1] + et[1]), jl.unit(er[0] - et[0], er[1] - et[1])]


# ------------------------------------------------------------------ layers
Fill = Tuple[QPainterPath, QBrush]


def light_layers(cell: Cell, look: jl.Look, px: float) -> List[Fill]:
    """The prism star: centred radial light + two crossed rays (Rose Prism)."""
    star = look.light
    if star is None:
        return []
    cx, cy = cell.centre
    radial = QRadialGradient(QPointF(cx, cy), max(1e-3, cell.g * star.radius))
    for offset, value, alpha in star.stops:
        radial.setColorAt(offset, colour(value, alpha))
    out = [(cell.path, QBrush(radial))]
    if star.ray_alpha > .01:
        half = cell.g * star.ray_half
        for (dx, dy), tint in zip(cell.rays(), star.ray_tints):
            a, b = (cx - dx * half, cy - dy * half), (cx + dx * half, cy + dy * half)
            out.append((stroke(line(a, b), star.ray_width * px),
                        linear(a, b, ((0, tint, 0), (.5, star.ray_mid, .85 * star.ray_alpha), (1, tint, 0)))))
    return out


def cut_layers(cell: Cell, look: jl.Look, aim, light_theme: bool, px: float) -> List[Fill]:
    """Four bevel facets lit toward ``aim``, the table edge and the prism glint (Morning Prism)."""
    if look.k <= 0:
        return []
    b = jl.bevel(cell.size, look.k, px)
    out, best, best_dot = [], None, -2.0
    for facet in cell.facets(b):
        dot = facet.normal[0] * aim[0] + facet.normal[1] * aim[1]
        if dot > best_dot:
            best, best_dot = facet, dot
        value, alpha = jl.facet_tone(dot, look.k, light_theme, look.shade)
        out.append((facet.path, QBrush(colour(value, alpha))))
    out.append((stroke(cell.inset(b), px), QBrush(colour(look.hot, .30 * look.k))))
    glint = jl.glint_alpha(look.k)
    if glint > 0 and best is not None:
        start, end = best.edge.pointAtPercent(0), best.edge.pointAtPercent(1)
        left, right = jl.glint_tints(look.hue)
        out.append((stroke(best.edge, 1.6 * px),
                    linear((start.x(), start.y()), (end.x(), end.y()),
                           ((0, left, glint), (.5, jl.WHITE, glint), (1, right, glint)))))
    return out


def finish_layers(cell: Cell, look: jl.Look, px: float) -> List[Fill]:
    """The two great rim and the three full burn."""
    out = []
    if look.harm > .02:
        out.append((stroke(cell.inset(1.4 * px), 1.3 * px), QBrush(colour(look.hot, .55 * look.harm))))
    if look.burn > .01:
        cx, cy = cell.centre
        glow = QRadialGradient(QPointF(cx, cy), .7 * max(cell.w, cell.h))
        glow.setColorAt(0, colour(jl.WHITE, .95 * look.burn))
        glow.setColorAt(.55, colour(jl.BURN_MID, .70 * look.burn))
        glow.setColorAt(1, colour(look.hot, .35 * look.burn))
        out += [(cell.path, QBrush(glow)),
                (stroke(cell.path, 7 * px), QBrush(colour(look.hot, .35 * look.burn))),
                (stroke(cell.path, 3 * px), QBrush(colour(look.hot, look.burn)))]
    return out


def layers(cell: Cell, look: jl.Look, aim, light_theme: bool, px: float) -> List[Fill]:
    """Paint order after the fill: light, cut, rim, burn (the text lies above)."""
    return (light_layers(cell, look, px) + cut_layers(cell, look, aim, light_theme, px)
            + finish_layers(cell, look, px))


class JewelCellItem(QGraphicsItem):
    """The prebuilt layers of one cell; ``paint()`` only fills them."""

    def __init__(self, parent, fills, z=1.0):
        super().__init__(parent)
        self._fills = fills
        bounds = QRectF()
        for path, _brush in fills:
            bounds = bounds.united(path.boundingRect())
        self._bounds = bounds
        self.setZValue(z)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setAcceptHoverEvents(False)
        self.setData(Qt.ItemDataRole.UserRole, TAG_JEWEL)

    def boundingRect(self):
        return self._bounds

    def paint(self, painter, option, widget=None):
        for path, brush in self._fills:
            painter.fillPath(path, brush)


def decorate(parent, cell: Cell, look: jl.Look, aim, light_theme: bool, px: float, z=1.0):
    """Add the cell's jewel layers under ``parent``'s labels; None when it is plain."""
    from apps.widgets.jewel_lamp_cache import layers as cached      # kept between draws
    fills = cached(cell, look, aim, light_theme, px)
    return JewelCellItem(parent, fills, z) if fills else None
