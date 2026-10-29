# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Retinue strength paint (SPEC-RST-001): lamplight colour + quiet ribbon per cell.

Options are read from the settings manager when a view draws (never cached);
``q`` comes from the view's own chart. Everything is built at rebuild time as
plain Qt path items (C++ paint, no Python ``paint()`` dispatch): ribbons are
outlines (SI capsules, stroked wheel arcs) filled with a hard-stop gradient
(track + filled part in one item), the pool a radial gradient brush. Colour maths stay in
``core.retinue_strength`` on RAW hex; this module desaturates each new colour once (SPEC-SAT-001).

- SI: the pool + rim shadow are each cell's own fill (one radial gradient brush:
  the lamplight colour, or on wood the stain with the pool composited on it, the
  relief still drawn on top); ribbons + hue threads: ONE item per sign
  (``SignRibbons``), never over a label;
- wheel: a pool item and a ribbon arc item per cell, children of the wedge (so they rise
  with it on hover and stay under the labels), inside it by construction. V2: jewel_lamp_*."""
import math
from typing import Dict, NamedTuple, Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QLinearGradient, QPainterPath,
                           QPainterPathStroker, QPen, QRadialGradient, QTransform)
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPathItem

from core import jewel_lamp as jl, retinue_strength as rs
from ui.qt_theme import desat_hex

TAG_DECOR = 'rst.decor'      # every item this feature adds to a retinue cell
TAG_RIBBON = 'rst.ribbon'    # the cell's ribbon (track + filled part), data(Q_ROLE) = q
Q_ROLE = Qt.ItemDataRole.UserRole + 2
SI_OPACITY = .86             # standard SI sector opacity (wood: 1)
SI_Z = 1                     # below the sector's labels (z 3)
NO_PEN = QPen(Qt.PenStyle.NoPen)


def strength_options():
    """The four preferences, read now from the settings manager (uncached)."""
    from managers.settings_manager import get_settings
    return rs.StrengthOptions.from_settings(get_settings().get)


class StrengthSnapshot(NamedTuple):
    options: rs.StrengthOptions
    q: Dict[str, float]

    @property
    def active(self):
        return bool(self.options.enabled and self.q)


OFF_SNAPSHOT = StrengthSnapshot(rs.StrengthOptions.OFF, {})


def snapshot(chart, need=True, options=None):
    """Options + ``q`` of ``chart``; bala runs only when enabled and needed (V2: + parts)."""
    from managers.settings_manager import get_settings
    options = strength_options() if options is None else options
    if not (options.enabled and need and chart):
        return StrengthSnapshot(options, {})
    get = get_settings().get       # DUC Bala: the strength.duc_method setting (SPEC-STR-001 §7.5)
    return (jl.snapshot(chart, options, get) or StrengthSnapshot(
        options, rs.planet_strengths(chart, options.source, rs.duc_method_from(get))))


def qcolor(value, alpha=1.0):
    color = QColor(value)
    color.setAlphaF(max(0.0, min(1.0, alpha)))
    return color


class CellStyle(NamedTuple):
    fill: str                  # raw hex handed to the existing paint point
    opacity: Optional[float]   # wood stain opacity (None: standard)
    text: str                  # raw text colour for the labels
    glow: QColor               # desaturated, contrast-capped centre colour
    shadow: QColor             # desaturated rim colour
    q: float
    width: float               # ribbon width in scene px
    track: QColor
    ink: QColor                # filled part of the ribbon
    thread: Optional[QColor]


def cell_style(snap, lord, ring, bg, text, card, wood_o=None, opacity=SI_OPACITY,
               scale=1.0, wheel=False, glow_cap=.75, merged=False):
    """Colours of one (lord, ring) cell, or None when the lord has no strength.

    ``merged``: the pool is mixed into the cell's own fill (standard SI)."""
    q = snap.q.get(lord)
    if q is None:
        return None
    A, wood = snap.options.A, wood_o is not None
    lamp = rs.lamp_params(bg, q, A, card, ring=ring, lord=lord, wood_o=wood_o, bright=wheel)
    under = rs.hex_rgb(desat_hex(card))
    ink_of = (lambda c: desat_hex(c)) if wood else (lambda c: c)
    today = rs.over(under, rs.hex_rgb(desat_hex(bg)), opacity * (wood_o if wood else 1))
    threshold = rs.text_threshold(rs.hex_rgb(ink_of(text)), today, opacity)
    fill_rgb = rs.hex_rgb(desat_hex(lamp.fill))
    ground = rs.over(under, fill_rgb, opacity * (lamp.opacity if wood else 1))
    text_out = text
    if rs.contrast(rs.over(ground, rs.hex_rgb(ink_of(text)), opacity), ground) < threshold - 1e-9:
        text_out = rs.readable_text(ink_of(text), ground, opacity, threshold)
    glow_hex = desat_hex(lamp.glow)
    alpha = (rs.cap_glow(min(lamp.glow_alpha, glow_cap), ink_of(text_out), fill_rgb,
                         rs.hex_rgb(glow_hex), opacity, threshold, card=under) if merged else
             rs.cap_glow(min(lamp.glow_alpha, glow_cap), ink_of(text_out), ground,
                         rs.hex_rgb(glow_hex), opacity, threshold))
    ribbon = rs.ribbon_params(q, A, wheel)
    ink = desat_hex(rs.INK_WOOD_RIBBON) if wood else ink_of(text_out)
    # The filled part lies over the track: one colour, alphas composited once here.
    filled = ribbon.fill_alpha + ribbon.track_alpha * (1 - ribbon.fill_alpha)
    return CellStyle(lamp.fill, lamp.opacity, text_out, qcolor(glow_hex, alpha),
                     qcolor(desat_hex(lamp.shadow), lamp.shadow_alpha), ribbon.fraction,
                     ribbon.width * scale, qcolor(ink, ribbon.track_alpha), qcolor(ink, filled),
                     None if wheel else qcolor(desat_hex(bg), ribbon.thread_alpha))


def lit(style):
    return style.glow.alphaF() > 0 or style.shadow.alphaF() > 0


def pool_gradient(style, centre, radius, stops=(.85, 1.0), base=None):
    """Radial pool + rim shadow. ``base`` (a QColor, maybe translucent like a wood
    stain): the pool is composited over it once here ("over" is associative, so
    one brush equals the stain layer with the pool layer on top)."""
    def mix(color):
        if base is None:
            return color
        a, b = color.alphaF(), base.alphaF()
        out = a + b * (1 - a)
        if out <= 0:
            return QColor.fromRgbF(0, 0, 0, 0)
        return QColor.fromRgbF(*((c * a + d * b * (1 - a)) / out for c, d in zip(
            color.getRgbF()[:3], base.getRgbF()[:3])), out)
    clear = QColor(style.glow)
    clear.setAlphaF(0)
    gradient = QRadialGradient(centre, radius)
    gradient.setColorAt(0, mix(style.glow))
    gradient.setColorAt(stops[0], mix(clear))
    gradient.setColorAt(stops[1], mix(style.shadow))
    return QBrush(gradient)


def lit_shape(shape, style, centre, radius, stop=.85):
    """The part of ``shape`` the pool brush actually tints (built at rebuild). Glow
    only: inside the clear stop's circle; rim shadow only: outside it."""
    glow, shadow = style.glow.alphaF() > 0, style.shadow.alphaF() > 0
    if glow and shadow:
        return shape
    circle = QPainterPath()
    circle.addEllipse(centre, radius * stop, radius * stop)
    return shape.intersected(circle) if glow else shape.subtracted(circle)


def outline(path, width):
    """The filled outline of a round-capped stroke (stroked once, at rebuild)."""
    stroker = QPainterPathStroker()
    stroker.setWidth(width)
    stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
    return stroker.createStroke(path)


def capsule(start, length, width, wide):
    """A round-capped straight band from ``start`` along +x (``wide``) or +y: one
    rounded rectangle, the stroker's shape without stroking (wheel arcs stroke)."""
    r = width / 2
    path = QPainterPath()
    path.addRoundedRect(QRectF(start.x() - r, start.y() - r,
                               length + width if wide else width,
                               width if wide else length + width), r, r)
    return path


def _hard_stops(gradient, style, q, end=1.0, wrap=False):
    """Filled colour up to ``q`` (of ``end``), track after; one item, two colours."""
    head = style.ink if q > 0 else style.track
    gradient.setColorAt(0, head)
    gradient.setColorAt(min(q * end, 1.0), head)
    gradient.setColorAt(min(q * end + 1e-4, 1.0), style.track)
    if wrap:   # conical: end cap past ``end``, start cap below 1.0; head again halfway
        gradient.setColorAt((end + 1) / 2, style.track)
        gradient.setColorAt(min((end + 1) / 2 + 1e-4, 1.0), head)
        gradient.setColorAt(1.0, head)
    else:
        gradient.setColorAt(1.0, style.track)
    return QBrush(gradient)


def add_item(parent, path, brush, tag=TAG_DECOR, z=SI_Z):
    item = QGraphicsPathItem(path, parent)
    item.setPen(NO_PEN)
    item.setBrush(brush)
    item.setZValue(z)
    item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
    item.setData(Qt.ItemDataRole.UserRole, tag)
    return item


def si_ribbon_band(rect, scale, width, label_rects):
    """Ribbon centre line + width along the cell's long side, clear of labels.

    Wide cells: bottom edge; tall cells: right edge (the mockup geometry). The
    band narrows to the free margin between the edge and the padded label rects
    (min 2 px) or is skipped (None)."""
    left, top, right, bottom = rect.getCoords()
    wide = right - left >= bottom - top
    pad, centre, keep = 9 * scale, 5.5 * scale, .5 * scale
    far, near = centre + width / 2, max(keep, centre - width / 2)
    lo, hi = (left + pad, right - pad) if wide else (top + pad, bottom - pad)
    for label in label_rects:
        l_left, l_top, l_right, l_bottom = label.getCoords()
        a, b = (l_left, l_right) if wide else (l_top, l_bottom)
        if b < lo - far or a > hi + far:
            continue
        room = bottom - l_bottom if wide else right - l_right
        far = min(far, room - keep)          # a hair clear of the padded label rect
    if far - near < width:
        near = max(keep, far - width)
    width = far - near
    if width < 2:
        return None
    mid = (far + near) / 2
    if wide:
        return QPointF(lo, bottom - mid), QPointF(hi, bottom - mid), width
    return QPointF(right - mid, lo), QPointF(right - mid, hi), width


def shared(cache, key, build):
    """Plain per-pass dict memo: one object per key within ONE rebuild."""
    value = cache.get(key)
    if value is None:
        value = cache[key] = build()
    return value


class SignRibbons(QGraphicsItem):
    """The seven cell ribbons (+ hue threads) of one SI sign as ONE item: prebuilt
    outlines and brushes, ``paint()`` only fills. Placed right after the sign's
    cells (same parent, same z, so under the guides and markers that follow) at
    the cells' own opacity. It never overlaps a label (INV-8, T-14), so drawing
    after the cells' labels looks exactly like drawing under them."""

    def __init__(self, parent, fills, cells, opacity, bounds):
        super().__init__(parent)
        self._fills = fills              # [(brush, outline)] in parent coordinates
        self.cells = cells               # [(sector key, ribbon outline, q)] for tests
        self._bounds = bounds
        self.setOpacity(opacity)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setData(Qt.ItemDataRole.UserRole, TAG_RIBBON)

    def boundingRect(self):
        return self._bounds

    def paint(self, painter, option, widget=None):
        for brush, path in self._fills:
            painter.fillPath(path, brush)


def _placed(brush, offset):
    placed = QBrush(brush)
    placed.setTransform(QTransform.fromTranslate(offset.x(), offset.y()))
    return placed


class StrengthPass:
    """One SI retinue rebuild: 14 (lord, ring) styles in a plain dict, the pool in
    each cell's own brush, one ribbon item per sign."""

    def __init__(self, snap, palette, wood, scale):
        self.snap = snap if snap is not None else OFF_SNAPSHOT
        self.on = self.snap.active
        self.card, self.wood, self.scale = palette['card'], bool(wood), scale
        self.styles, self.cache = {}, {}
        self.fills, self.cells = [], []

    def style(self, lord, ring, bg, text, wood_rec):
        key = (lord, ring)
        if key not in self.styles:
            self.styles[key] = cell_style(
                self.snap, lord, ring, bg, text, self.card,
                wood_o=wood_rec['o'] if wood_rec else None,
                opacity=1 if wood_rec else SI_OPACITY, scale=self.scale, merged=not wood_rec)
        return self.styles[key]

    def cell(self, layer, key, rect, lord, bg, text, wood_rec, label):
        """Build one retinue cell exactly as before, plus its strength when on."""
        style = self.style(lord, key[1], bg, text, wood_rec) if self.on else None
        opacity = (wood_rec['o'] if style is None else style.opacity) if wood_rec else 1
        item = layer.rect(rect, bg if style is None else style.fill, opacity=opacity,
                          pocket=bool(wood_rec))
        layer.sectors[key] = item
        item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        item.setOpacity(1 if wood_rec else SI_OPACITY)
        item.setFlag(QGraphicsPathItem.GraphicsItemFlag.ItemClipsChildrenToShape)
        first = len(layer._label_rects)
        layer.two_lines(*label, text if style is None else style.text, item)
        if style is not None:
            self.decorate(key, item, rect, style, layer._label_rects[first:])
            if key[1] == 'hora' and key[2] == 1:          # the sign's last cell
                self.flush(item.parentItem(), item.opacity())
        return item

    def flush(self, parent, opacity):
        if self.fills:
            bounds = QRectF()
            for _, path, _ in self.cells:   # the bands; each hue thread lies inside its band
                bounds = bounds.united(path.boundingRect())
            SignRibbons(parent, self.fills, self.cells, opacity, bounds)
        self.fills, self.cells = [], []

    def decorate(self, key, item, rect, style, label_rects):
        """Brushes and outlines live in cell-centred / band-start local
        coordinates, so all cells of one (lord, ring) and size share them; each
        cell only places them."""
        w, h = rect.width(), rect.height()
        if lit(style):   # the pool is the cell's own fill: lamplight colour or wood
            # stain with the pool composited on it (one brush, desaturated once)
            brush = shared(self.cache, ('pool', id(style), round(w, 2), round(h, 2)),
                           lambda: pool_gradient(style, QPointF(0, 0), max(w, h) * .62,
                                                 base=item.brush().color()))
            item.setBrush(_placed(brush, rect.center()))
        band = si_ribbon_band(rect, self.scale, style.width, label_rects)
        if band is None:
            return
        a, b, width = band
        wide = a.y() == b.y()
        length = (b.x() - a.x()) if wide else (b.y() - a.y())
        end = QPointF(length, 0) if wide else QPointF(0, length)

        # Straight bands: capsule + hard-stop brush built in place (no stroke, no transform).
        ribbon = capsule(a, length, width, wide)
        self.fills.append((_hard_stops(QLinearGradient(a, a + end), style, style.q), ribbon))
        self.cells.append((key, ribbon, style.q))
        if style.thread is not None and style.q > 0:
            thread = shared(self.cache, ('thread', id(style)), lambda: QBrush(style.thread))
            self.fills.append((thread, capsule(a, length * style.q, width * .28, wide)))


# ------------------------------------------------------------------- wheel
WHEEL_CARD = '#1a1a1e'     # the outer rim ground under the rings, always dark
WHEEL_RIBBON_INSET = 12    # ribbon centre, px inside the sector's outer radius


def wheel_snapshot(view):
    """Options + ``q`` of the wheel's own chart, read when it draws (never cached)."""
    options = strength_options()
    if not options.enabled:
        return OFF_SNAPSHOT
    return snapshot(view._chart, view.show_retinue_rings, options)


class WheelStrengthPass:
    """One wheel ring draw: lamplight colours handed to the existing sector
    (``bg_color``, so the hover restore stays right) plus a pool and a ribbon
    item inside the wedge."""

    def __init__(self, snap):
        self.snap = snap if snap is not None else OFF_SNAPSHOT
        self.on = self.snap.active
        self.styles, self.cache = {}, {}

    def style(self, lord, ring, raw_bg, text):
        key = (lord, ring)
        if key not in self.styles:
            self.styles[key] = cell_style(self.snap, lord, ring, raw_bg, text, WHEEL_CARD,
                                          opacity=1, wheel=True)
        return self.styles[key]

    def colours(self, lord, ring, raw_bg, bg, text):
        """(sector fill, label colour): unchanged when off, else the lamplight
        fill desaturated once (raw maths, SPEC-SAT-001) and a readable text."""
        style = self.style(lord, ring, raw_bg, text) if self.on else None
        if style is None:
            return bg, text
        return desat_hex(style.fill), style.text

    def _shapes(self, style, r_in, r_out, span):
        """Pool + ribbon of one (style, ring, span), built ONCE around the wheel
        centre at angle 0; each sector rotates the same items into place."""
        wedge = QPainterPath()
        wedge.arcMoveTo(QRectF(-r_out, -r_out, 2 * r_out, 2 * r_out), 0)
        wedge.arcTo(QRectF(-r_out, -r_out, 2 * r_out, 2 * r_out), 0, span)
        wedge.arcTo(QRectF(-r_in, -r_in, 2 * r_in, 2 * r_in), span, -span)
        wedge.closeSubpath()
        pool = None
        if lit(style):
            mid, r_mid = math.radians(span / 2), (r_in + r_out) / 2
            centre = QPointF(r_mid * math.cos(mid), -r_mid * math.sin(mid))
            radius = .75 * max(r_out - r_in, r_mid * math.radians(span))
            pool = (lit_shape(wedge, style, centre, radius, .8),
                    pool_gradient(style, centre, radius, stops=(.8, 1.0)))
        r = r_out - WHEEL_RIBBON_INSET
        circle = QRectF(-r, -r, 2 * r, 2 * r)
        sweep = span - 1.6
        arc = QPainterPath()
        arc.arcMoveTo(circle, .8)
        arc.arcTo(circle, .8, sweep)
        ribbon = outline(arc, style.width)
        # Inside the wedge by construction when the round cap fits the .8 deg inset;
        # otherwise cut to the wedge once, here (never a paint-time clip).
        if r * math.radians(.8) < style.width / 2 or r_out - r < style.width / 2 + 1:
            ribbon = ribbon.intersected(wedge)
        gradient = QConicalGradient(QPointF(0, 0), .8)
        return pool, ribbon, _hard_stops(gradient, style, style.q, sweep / 360, wrap=True)

    def decorate(self, sector, lord, ring, raw_bg, text, cx, cy, r_in, r_out, start, span):
        style = self.style(lord, ring, raw_bg, text) if self.on else None
        if style is None:
            return
        pool, ribbon, brush = shared(self.cache, (id(style), r_in, r_out, span),
                                     lambda: self._shapes(style, r_in, r_out, span))
        items = [add_item(sector, *pool, z=0)] if pool else []
        main = add_item(sector, ribbon, brush, TAG_RIBBON, z=0)
        main.setData(Q_ROLE, style.q)
        for item in items + [main]:
            item.setPos(cx, cy)
            item.setRotation(-start)         # angle 0 -> start (screen angles run CCW)
