# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The Ember Aura items and their ground (SPEC-RST-001 D-21a, td-647kl, td-3zaz7, td-ws82s).

``AuraItem`` discs (empty shape: seen, never hit) sized and lit by
``core.planet_aura``, judged on the ground under each planet (``pa.own_ground`` of
ONE low-resolution render of the finished scene with the planet icons, texts and
pointers hidden); also the halo glyph outline cache.
"""
from __future__ import annotations

import math
import sys

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QGraphicsEllipseItem

from core import planet_aura as pa
from core.planet_strength_glow import STRENGTH_PALETTE
from ui.qt_theme import desat_hex, get_theme_colors, is_light_theme

TAG_AURA = 'psg.aura'      # data(UserRole) of every aura disc
VALUE_ROLE = Qt.ItemDataRole.UserRole + 4   # the strength value an aura shows
PLANET_ROLE = Qt.ItemDataRole.UserRole + 5  # the planet an aura belongs to
CARRIER_ROLE = Qt.ItemDataRole.UserRole + 6  # 'colour' or 'size': what shows the value (read by the PLANET_GLOW_CHECK gate)
NO_PEN = QPen(Qt.PenStyle.NoPen)
SAMPLE_PX = 3.0            # the reference half size, in ground-sample pixels
SAMPLE_REACH = pa.OWN_REACH  # default sampled half side, in r_ref (the planet's own ground)
# RGB32 pixels are 0xffRRGGBB words: the byte offsets of R, G, B in memory
R_AT, G_AT, B_AT = (2, 1, 0) if sys.byteorder == 'little' else (1, 2, 3)
_GLYPHS = {}               # (text, font) -> glyph outline at the baseline origin
_GLYPHS_MAX = 512


def ground_fill(scene):
    """What shows where no item paints: the scene's brush, else the theme ground."""
    brush = scene.backgroundBrush()
    if brush.style() != Qt.BrushStyle.NoBrush:
        return brush.color()
    return QColor(theme_ground())


def theme_ground():
    """The theme's chart ground (hex): ``secondary`` light, ``secondary_dark`` dark."""
    th = get_theme_colors()
    return th["secondary"] if is_light_theme() else th["secondary_dark"]


def _render(scene, src, scale, hide):
    """``src`` rendered at ``scale`` with the ``hide`` items hidden (restored)."""
    w, h = max(1, math.ceil(src.width() * scale)), max(1, math.ceil(src.height() * scale))
    image = QImage(w, h, QImage.Format.Format_RGB32)
    image.fill(ground_fill(scene))
    hidden = [i for i in hide if i.isVisible()]
    for item in hidden:
        item.setVisible(False)
    try:
        painter = QPainter(image)
        scene.render(painter, QRectF(0, 0, w, h), QRectF(src.left(), src.top(), w / scale, h / scale),
                     Qt.AspectRatioMode.IgnoreAspectRatio)
        painter.end()
    finally:
        for item in hidden:
            item.setVisible(True)
    return image


def _around(image, bits, fx, fy, scale, reach):
    """``[(dx, dy, rgb), ...]`` of the pixels within ``reach`` (+ one pixel) of the
    image point ``(fx, fy)``, offsets back in scene units; ``bits``: the image's
    bytes, read once per render."""
    stride = image.bytesPerLine()
    half, unit, inv = int(math.ceil(reach * scale)), 1.0 / scale, 1.0 / 255.0
    limit = (reach + unit) ** 2
    cx, cy = int(fx), int(fy)
    xs = [(x, (x + 0.5 - fx) * unit) for x in range(max(0, cx - half), min(image.width(), cx + half + 1))]
    px = []
    for y in range(max(0, cy - half), min(image.height(), cy + half + 1)):
        row, dy = y * stride, (y + 0.5 - fy) * unit
        for x, dx in xs:
            if dx * dx + dy * dy <= limit:
                i = row + 4 * x
                px.append((dx, dy, (bits[i + R_AT] * inv, bits[i + G_AT] * inv, bits[i + B_AT] * inv)))
    return px


def sample_grounds(scene, centres, r_ref, hide=(), reach=None):
    """The ground around each of ``centres``: one render (``SAMPLE_PX`` px per ``r_ref``),
    the pixels within ``reach`` of each point as ``[[(dx, dy, (r, g, b)), ...], ...]``."""
    if not centres:
        return []
    scale = SAMPLE_PX / max(r_ref, 1.0)
    reach = SAMPLE_REACH * r_ref if reach is None else reach
    xs, ys = [c.x() for c in centres], [c.y() for c in centres]
    src = QRectF(min(xs) - reach, min(ys) - reach, max(xs) - min(xs) + 2 * reach,
                 max(ys) - min(ys) + 2 * reach)
    image = _render(scene, src, scale, hide)
    bits = bytes(image.constBits())
    fill = ground_fill(scene)
    empty = [(0.0, 0.0, (fill.redF(), fill.greenF(), fill.blueF()))]
    return [_around(image, bits, (c.x() - src.left()) * scale, (c.y() - src.top()) * scale, scale, reach)
            or empty for c in centres]


class AuraItem(QGraphicsEllipseItem):
    def shape(self):                          # seen, never hit
        return QPainterPath()


def _disc(centre, radius, colour, stops, z, value, planet=None, carrier='colour'):
    grad = QRadialGradient(centre, radius)
    for pos, alpha in stops:
        c = QColor(colour)
        c.setAlphaF(max(0.0, min(1.0, alpha)))
        grad.setColorAt(pos, c)
    item = AuraItem(centre.x() - radius, centre.y() - radius, 2 * radius, 2 * radius)
    item.setPen(NO_PEN)
    item.setBrush(QBrush(grad))
    item.setZValue(z)
    item.setData(Qt.ItemDataRole.UserRole, TAG_AURA)
    item.setData(VALUE_ROLE, float(value))
    item.setData(PLANET_ROLE, planet)
    item.setData(CARRIER_ROLE, carrier)
    return item


def _rgb(colour):
    c = QColor(colour)
    return (c.redF(), c.greenF(), c.blueF())


def discs(planet, value, centre, r_ref, z, ground):
    """The aura of ``planet``: ONE disc of its own colour fading to fully
    transparent, nothing else (td-ws82s: no edge ring, no shade); radius from
    ``r_ref`` and the value, alpha from the value and the colour's difference to
    ``ground``, the rgb (0..1) under the planet itself (``pa.own_ground``)."""
    raw = STRENGTH_PALETTE.get(planet)
    if raw is None:
        return []
    colour = desat_hex(raw)
    rgb = _rgb(colour)
    carrier = 'colour' if pa.colour_carries(value, rgb, ground) else 'size'
    return [_disc(centre, pa.aura_radius(r_ref, value), colour, pa.aura_stops(value, rgb, ground),
                  z, value, planet, carrier)]


def unshadow(item, value):
    """Drop the manual drop shadow (Qt deletes it); keep the value for hover."""
    if item.graphicsEffect() is not None:
        item.setGraphicsEffect(None)
    item.setData(VALUE_ROLE, float(value))
    return item.boundingRect()


def decorate_planets(scene, entries, r_ref, hide=(), chart=None):
    """``entries`` = ``[(item, value), ...]``: swap each item's manual drop
    shadow for its aura (scene items, z - 0.5), all from the view's ONE
    reference half size, each judged on the ground under the planet itself
    (kept per scene for ``chart``: ``own_grounds``). Returns the discs added."""
    placed = []
    for item, value in entries:
        rect = unshadow(item, value)
        placed.append((item, value, QPointF(item.mapToScene(rect.center()))))
    from apps.widgets.planet_aura_ground import own_grounds
    grounds = own_grounds(scene, chart, [p[2] for p in placed], r_ref,
                          list(hide) + [p[0] for p in placed])
    count = 0
    for (item, value, centre), ground in zip(placed, grounds):
        for disc in discs(item.planet_name, value, centre, r_ref, item.zValue() - 0.5, ground):
            scene.addItem(disc)
            count += 1
    return count


def glyphs(text, font):
    """The glyph outline of ``text`` at the origin (one per text and font: a
    redraw of the same chart outlines nothing again)."""
    key = (text, font.toString())
    path = _GLYPHS.get(key)
    if path is None:
        if len(_GLYPHS) >= _GLYPHS_MAX:
            _GLYPHS.clear()
        path = QPainterPath()
        path.addText(0.0, 0.0, font, text)
        _GLYPHS[key] = path
    return path
