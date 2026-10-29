# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Dignity overlay on the chart planets, "Burnish Clear" (SPEC-DIG-001 §4.1, td-m6xyo).

While ``chart.planet_glow_mode`` is "dignity", each of the seven classical planets
of the Wheel and the South Indian views (vector and classic) wears its dignity in
the varga the view draws: a sheen of polished light from the upper left whose
length steps down from EX to N, tarnish grain for E / GE, and for a Debilitated
planet the kind of host: a short WHITE sunk sheen in a friend's sign, a still
OCHRE arc in a neutral's sign, ash and fissures (glyph greyed) in an enemy's sign.

Maths and parameters are Qt-free in ``core.planet_dignity``. Items have an empty
shape (seen, never hit). Animation: ONE timer per scene, each moving part is its
own small item and only its transform / opacity changes (no blur, no effect).
Rule 18: every item goes to the scene or under a parent at once.
"""
from __future__ import annotations

import math
import time

import shiboken6
from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (QBrush, QColor, QImage, QLinearGradient, QPainter, QPainterPath,
                           QPen, QPixmap, QPolygonF, QTransform)
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPixmapItem

from core import planet_dignity as pd
from ui.qt_theme import desat_hex

TAG = 'dig.overlay'           # data(UserRole) of every overlay item
TAG_GREY = 'dig.grey'         # the greyed glyph child of a DB-enemy icon
STEP_ROLE = Qt.ItemDataRole.UserRole + 7
PLANET_ROLE = Qt.ItemDataRole.UserRole + 8
Z_ABOVE_ICON = 0.6
FRAME_MS = 125                # 8 frames a second: subtle motion, little CPU (CPU budget)
IDLE_MS = 1000                # no visible view: wake once a second only
WHITE = "#FFFFFF"
_GREY_CACHE = {}              # pixmap cacheKey -> grayscale QImage (80 % brightness)
_GREY_MAX = 64


def _c(hex_colour, alpha=1.0):
    c = QColor(desat_hex(hex_colour))
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def _poly(points):
    path = QPainterPath()
    path.addPolygon(QPolygonF([QPointF(x, y) for x, y in points]))
    path.closeSubpath()
    return path


def _crescent(R, W, a0, a1, cx=0.0, cy=0.0):
    return _poly(pd.crescent_points(cx, cy, R, W, a0, a1))


def _arc(R, a0, a1):
    path = QPainterPath()
    n = max(8, int(abs(a1 - a0) / 3))
    for k in range(n + 1):
        x, y = pd.polar(0, 0, R, a0 + (a1 - a0) * k / n)
        if k:
            path.lineTo(x, y)
        else:
            path.moveTo(x, y)
    return path


def _polyline(points):
    path = QPainterPath()
    for i, (x, y) in enumerate(points):
        if i:
            path.lineTo(x, y)
        else:
            path.moveTo(x, y)
    return path


def _star(x, y, z):
    """The mockup's 4-point star glint centred at (x, y), half size z."""
    path = QPainterPath(QPointF(x, y - z))
    path.quadTo(x, y, x + z, y)
    path.quadTo(x, y, x, y + z)
    path.quadTo(x, y, x - z, y)
    path.quadTo(x, y, x, y - z)
    path.closeSubpath()
    return path


def _pen(colour, width, cap=Qt.PenCapStyle.RoundCap):
    return QPen(QBrush(colour), width, Qt.PenStyle.SolidLine, cap, Qt.PenJoinStyle.RoundJoin)


def _gradient(path, tint, vertical=False, stops=None):
    r = path.boundingRect()
    g = QLinearGradient(r.topLeft(), r.bottomLeft() if vertical else r.bottomRight())
    for pos, colour in (stops or ((0.0, WHITE), (0.5, tint), (1.0, WHITE))):
        g.setColorAt(pos, _c(colour))
    return QBrush(g)


class _Layer:
    """One painted shape: path + pen / brush + opacity."""
    __slots__ = ("path", "pen", "brush", "opacity", "offset")

    def __init__(self, path, pen=None, brush=None, opacity=1.0, offset=None):
        self.path, self.pen, self.brush = path, pen, brush
        self.opacity, self.offset = opacity, offset


class _Painted(QGraphicsItem):
    """Paints its layers; empty shape, so clicks, hover and ``items(pos)`` pass."""

    def __init__(self, layers, parent=None):
        super().__init__(parent)
        self._layers = layers
        rect = QRectF()
        for layer in layers:
            r = layer.path.boundingRect()
            if layer.offset is not None:
                r = r.translated(layer.offset)
            w = layer.pen.widthF() if layer.pen is not None else 0.0
            rect = rect.united(r.adjusted(-w, -w, w, w))
        self._rect = rect.adjusted(-1, -1, 1, 1)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setAcceptHoverEvents(False)
        self.setData(Qt.ItemDataRole.UserRole, TAG)

    def boundingRect(self):
        return self._rect

    def shape(self):                          # seen, never hit
        return QPainterPath()

    def paint(self, painter, _option, _widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for layer in self._layers:
            painter.save()
            if layer.offset is not None:
                painter.translate(layer.offset)
            painter.setOpacity(painter.opacity() * layer.opacity)
            painter.setPen(layer.pen if layer.pen is not None else Qt.PenStyle.NoPen)
            painter.setBrush(layer.brush if layer.brush is not None else Qt.BrushStyle.NoBrush)
            painter.drawPath(layer.path)
            painter.restore()


class SheenItem(_Painted):
    """The still part of one planet's dignity mark, at the planet centre."""


class _Part(_Painted):
    """A moving part: ``motion(t)`` sets its transform / opacity (one per item)."""

    def __init__(self, layers, motion, parent):
        super().__init__(layers, parent)
        self.motion = motion


# ------------------------------------------------------------------ motions
def _sweep_motion(span, period=pd.SWEEP_PERIOD):
    """The light patch travels along the crescent: 0 -> span over 45 % of the
    period, fading in by 8 %, out by 45 % (the mockup's keyframes)."""
    def motion(item, t):
        f = (t % period) / period
        if f < 0.45:
            angle = span * _ease(f / 0.45)
            alpha = 0.95 * (f / 0.08 if f < 0.08 else 1.0 - (f - 0.08) / 0.37)
        else:
            angle, alpha = span, 0.0
        item.setTransform(QTransform().rotate(angle))
        item.setOpacity(max(0.0, alpha))
    return motion


def _glint_motion(cx, cy, delay=0.0, period=pd.GLINT_PERIOD):
    """The star glint breathes: scale .78 -> 1.08, rotation 0 -> 14, opacity .5 -> 1."""
    def motion(item, t):
        f = 0.5 - 0.5 * math.cos(2 * math.pi * ((t + delay) % period) / period)
        sc, rot = 0.78 + 0.30 * f, 14.0 * f
        tr = QTransform().translate(cx, cy).rotate(rot).scale(sc, sc).translate(-cx, -cy)
        item.setTransform(tr)
        item.setOpacity(0.5 + 0.5 * f)
    return motion


def _fall_motion(cx, cy, dx, dy, delay, period=pd.FLAKE_PERIOD):
    def motion(item, t):
        f = ((t + delay) % period) / period
        e = f * f                                  # ease-in
        tr = QTransform().translate(dx * e, dy * e).translate(cx, cy).rotate(40 * e).translate(-cx, -cy)
        item.setTransform(tr)
        item.setOpacity(0.9 * (f / 0.15) if f < 0.15 else 0.9 * (1.0 - (f - 0.15) / 0.85))
    return motion


def _breathe_motion(period=pd.EMBER_PERIOD):
    def motion(item, t):
        item.setOpacity(0.65 + 0.35 * (0.5 - 0.5 * math.cos(2 * math.pi * (t % period) / period)))
    return motion


def _rise_motion(dy, delay, period=pd.SPARK_PERIOD):
    def motion(item, t):
        f = ((t + delay) % period) / period
        e = 1.0 - (1.0 - f) ** 2                   # ease-out
        item.setTransform(QTransform().translate(0.0, dy * e))
        item.setOpacity(0.95 * (f / 0.2) if f < 0.2 else 0.95 * (1.0 - (f - 0.2) / 0.8))
    return motion


def _ease(x):
    return 0.5 - 0.5 * math.cos(math.pi * max(0.0, min(1.0, x)))


# ------------------------------------------------------------------ steps
def _crack_layers(cx, cy, a, r0, r1, R, s, dark):
    path = _polyline(pd.crack_points(cx, cy, a, r0, r1, R))
    lip = QColor(255, 240, 225)
    lip.setAlphaF(0.6)
    return [_Layer(path, _pen(lip, 2.8 * s)), _Layer(path, _pen(_c(dark), 1.4 * s))]


def _sheen_layers(step, s, R):
    """EX..N: shadow, keyline, gradient fill, spine and the still extras.
    Returns (layers, moving parts as (layers, motion))."""
    spec = pd.SHEEN[step]
    RR, C = pd.SHEEN_R * s, pd.CENTRE
    a0, a1 = C - spec["span"] / 2, C + spec["span"] / 2
    key, tint = spec["key"], spec["tint"]
    path = _crescent(RR, spec["W"] * s, a0, a1)
    fill = _gradient(path, tint)
    layers = [
        _Layer(path, brush=QBrush(_c(key)), opacity=0.32, offset=QPointF(1.3 * s, 1.3 * s)),
        _Layer(path, pen=_pen(_c(key, 0.82), 2.4 * s, Qt.PenCapStyle.FlatCap)),
        _Layer(path, brush=fill, opacity=spec["op"]),
    ]
    parts = []
    if spec.get("spine"):
        h = spec["span"] * spec["spine"] / 2
        layers.append(_Layer(_arc(RR, C - h, C + h), pen=_pen(_c(WHITE), 1.4 * s)))
    if spec.get("dbl"):
        d2 = _crescent(RR - 9 * s, spec["W"] * 0.5 * s, C - spec["span"] * .28, C + spec["span"] * .28)
        layers += [_Layer(d2, pen=_pen(_c(key, 0.6), 1.6 * s)), _Layer(d2, brush=QBrush(_c(WHITE)))]
    if spec.get("rim"):
        d3 = _crescent(RR - 1 * s, 3 * s, 0, 50)
        layers += [_Layer(d3, pen=_pen(_c(key, 0.55), 1.3 * s)), _Layer(d3, brush=_gradient(d3, tint))]
    if spec.get("dot"):
        x, y = pd.polar(0, 0, RR, C)
        dot = QPainterPath()
        dot.addEllipse(QPointF(x, y), 2.6 * s, 2.6 * s)
        layers.append(_Layer(dot, pen=_pen(_c(key, 0.6), 0.7 * s), brush=QBrush(_c(WHITE))))
    if spec.get("sweep"):
        d4 = _crescent(RR, spec["W"] * 1.1 * s, a0, a0 + 24)
        parts.append(([_Layer(d4, brush=QBrush(_c(WHITE)))], _sweep_motion(spec["span"] - 24)))
    if spec.get("star"):
        z = spec["star"] * s
        x, y = pd.polar(0, 0, RR + 3 * s, C)
        parts.append(([_Layer(_star(x, y, z), pen=_pen(_c(key, 0.8), 0.9 * s), brush=QBrush(_c(WHITE)))],
                      _glint_motion(x, y)))
        if spec.get("star2"):
            x2, y2 = pd.polar(0, 0, RR + 2 * s, -190)
            parts.append(([_Layer(_star(x2, y2, z * .55), pen=_pen(_c(key, 0.8), 0.7 * s),
                                  brush=QBrush(_c(WHITE)))], _glint_motion(x2, y2, delay=2.7)))
    return layers, parts


def _matte_layers(step, s, R):
    """E / GE: the sheen dulled to a flat two-tone grain band, blots, cracks."""
    spec = pd.SHEEN[step]
    RR, C = pd.SHEEN_R * s, pd.CENTRE
    a0, a1 = C - spec["span"] / 2, C + spec["span"] / 2
    key, gaps = spec["key"], spec["gaps"]
    layers = []
    for b0, b1 in pd.segments(a0, a1, gaps):
        d = _crescent(RR, 4.8 * s, b0, b1)
        layers += [_Layer(d, brush=QBrush(_c(key)), opacity=0.3, offset=QPointF(1.1 * s, 1.1 * s)),
                   _Layer(d, pen=_pen(_c(key, 0.8), 2 * s, Qt.PenCapStyle.FlatCap)),
                   _Layer(d, brush=QBrush(_c(spec["band"])), opacity=0.85)]
    grain_pen, grain_brush = _pen(_c(key, 0.9), 0.7 * s), QBrush(_c(spec["dot"]))
    a = a0 + 3
    while a <= a1 - 3:
        if not pd.in_gap(a, gaps):
            t = (a - a0) / (a1 - a0)
            x, y = pd.polar(0, 0, RR + (R() - .5) * 7 * s, a + (R() - .5) * 2)
            r = (0.9 + 1.2 * math.sin(math.pi * t) * R() + .3) * s
            dot = QPainterPath()
            dot.addEllipse(QPointF(x, y), r, r)
            layers.append(_Layer(dot, pen=grain_pen, brush=grain_brush))
        a += 5.5
    for _ in range(spec["blots"]):
        x, y = pd.polar(0, 0, RR + (R() - .5) * 8 * s, a0 + R() * (a1 - a0))
        rx, ry, rot = (2.5 + R() * 2.5) * s, (1.6 + R() * 1.4) * s, R() * 180
        blot = QPainterPath()
        blot.addEllipse(QPointF(0, 0), rx, ry)
        blot = QTransform().translate(x, y).rotate(rot).map(blot)
        layers.append(_Layer(blot, brush=QBrush(_c(key)), opacity=0.5))
    for ca in spec["cracks"]:
        layers += _crack_layers(0, 0, ca, RR - 10 * s, RR + 11 * s, R, s, key)
    return layers, []


def _ruin_layers(s, R):
    """DB in an enemy's sign: three ash fragments slipped outward, five
    fissures with a light lip, falling flakes (the glyph is greyed apart)."""
    spec = pd.SHEEN["DB"]
    RR = pd.SHEEN_R * s
    layers, parts = [], []
    for i, (a, b) in enumerate(((-178, -156), (-142, -122), (-108, -94))):
        dx, dy = (R() - .3) * 4 * s, (2 + i * 1.5) * s
        frag = _crescent(RR + 3 * s, 3.6 * s, a, b, dx, dy)
        frag = QTransform().rotate((R() - .5) * 14).map(frag)
        layers.append(_Layer(frag, pen=_pen(_c(spec["dark"], 0.8), 1 * s), brush=QBrush(_c(spec["ash"]))))
    for a in (150, 205, 255, 330, 32):
        layers += _crack_layers(0, 0, a, 30 * s, (53 + R() * 6) * s, R, s, spec["dark"])
    lip = QColor(237, 227, 223)
    lip.setAlphaF(0.5)
    for i in range(5):
        a = 120 + i * 75 + R() * 20
        x, y = pd.polar(0, 0, (34 + R() * 8) * s, a)
        sz = (1.7 + R() * 1.6) * s
        flake = _poly([(x - sz, y), (x, y - sz), (x + sz, y + sz * .4)])
        dx = (R() - .5) * 8 * s
        parts.append(([_Layer(flake, pen=_pen(lip, 0.5 * s), brush=QBrush(_c(spec["ash"])))],
                      _fall_motion(x, y, dx, 16 * s, i * 1.3)))
    return layers, parts


def _sunk_white_layers(s, R):
    """DB in a friend's sign: a short WHITE sheen sunk to the lower left, a soft
    white glow on its arc, two sparks rising: low, but still producing."""
    spec = pd.SHEEN["DBF"]
    RR, C, half = pd.SHEEN_R * s, pd.SUNK_CENTRE, pd.SUNK_SPAN / 2
    a0, a1 = C - half, C + half
    path = _crescent(RR, spec["W"] * s, a0, a1)
    g_colour, g_alpha, g_w = spec["glow"]
    g2_colour, g2_alpha, g2_w = spec["glow2"]
    stops = tuple(zip((0.0, 0.55, 1.0), spec["grad"]))
    layers = [
        _Layer(_arc(RR, a0 + 6, a1 - 6), pen=_pen(_c(g2_colour, g2_alpha), g2_w * s)),
        _Layer(path, brush=QBrush(_c(spec["key"])), opacity=0.3, offset=QPointF(1.1 * s, 1.1 * s)),
        _Layer(path, pen=_pen(_c(spec["key"], 0.82), 2.2 * s, Qt.PenCapStyle.FlatCap)),
        _Layer(path, brush=_gradient(path, None, vertical=True, stops=stops)),
    ]
    parts = [([_Layer(_arc(RR, a0 + 4, a1 - 4), pen=_pen(_c(g_colour, g_alpha), g_w * s))],
              _breathe_motion())]
    for a, delay in ((C - 9, 0.0), (C + 11, 3.2)):
        x, y = pd.polar(0, 0, RR + 2 * s, a)
        spark = QPainterPath()
        spark.addEllipse(QPointF(x, y), 1.5 * s, 1.5 * s)
        parts.append(([_Layer(spark, pen=_pen(_c(spec["key"], 0.8), 0.6 * s),
                              brush=QBrush(_c(spec["spark"])))], _rise_motion(-14 * s, delay)))
    return layers, parts


def _sunk_ochre_layers(s, R):
    """DB in a neutral's sign: one still OCHRE arc at the same sunk place,
    unlit, at rest: no glow, no particle, no motion."""
    spec = pd.SHEEN["DBN"]
    RR, C, half = pd.SHEEN_R * s, pd.SUNK_CENTRE, pd.SUNK_SPAN / 2
    arc = _arc(RR, C - half, C + half)
    return [_Layer(arc, pen=_pen(_c(spec["key"], spec["key_alpha"]), spec["key_w"] * s)),
            _Layer(arc, pen=_pen(_c(spec["line"]), spec["line_w"] * s))], []


def step_layers(step, s, seed=11):
    """``(still layers, moving parts)`` of ``step`` at scale ``s`` around (0, 0)."""
    R = pd.rng(seed)
    if step in ("EX", "MT", "OH", "GF", "F", "N"):
        return _sheen_layers(step, s, R)
    if step in ("E", "GE"):
        return _matte_layers(step, s, R)
    if step == "DBF":
        return _sunk_white_layers(s, R)
    if step == "DBN":
        return _sunk_ochre_layers(s, R)
    if step == "DB":
        return _ruin_layers(s, R)
    return [], []


# ------------------------------------------------------------------ the grey glyph
def grey_image(pixmap: QPixmap) -> QImage:
    """The icon in grayscale at 80 % brightness (cached per pixmap)."""
    key = pixmap.cacheKey()
    image = _GREY_CACHE.get(key)
    if image is None:
        if len(_GREY_CACHE) >= _GREY_MAX:
            _GREY_CACHE.clear()
        src = pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32)
        alpha = src.convertToFormat(QImage.Format.Format_Alpha8)
        image = src.convertToFormat(QImage.Format.Format_Grayscale8).convertToFormat(
            QImage.Format.Format_ARGB32)
        dim = QPainter(image)
        dim.fillRect(image.rect(), QColor(0, 0, 0, round(255 * (1 - pd.SHEEN["DB"]["grey_level"]))))
        dim.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        dim.drawImage(0, 0, alpha)
        dim.end()
        image.setDevicePixelRatio(pixmap.devicePixelRatio())
        _GREY_CACHE[key] = image
    return image


class _GreyGlyph(QGraphicsPixmapItem):
    def shape(self):                          # seen, never hit
        return QPainterPath()


def grey_glyph(icon, radius_scene):
    """Lay the greyed glyph over ``icon`` (its child), clipped to a disc of
    ``radius_scene`` scene units around the icon centre."""
    pixmap = icon.pixmap()
    if pixmap.isNull():
        return None
    image = grey_image(pixmap)
    dpr = pixmap.devicePixelRatio() or 1.0
    rect = icon.boundingRect()
    sx, sy = _scale_of(icon)
    r_local = radius_scene / max(0.5 * (sx + sy), 1e-6)
    clipped = QImage(image.size(), QImage.Format.Format_ARGB32_Premultiplied)
    clipped.setDevicePixelRatio(dpr)
    clipped.fill(Qt.GlobalColor.transparent)
    p = QPainter(clipped)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    centre = rect.center() - icon.offset()
    clip = QPainterPath()
    clip.addEllipse(centre, r_local, r_local)
    p.setClipPath(clip)
    p.drawImage(0, 0, image)
    p.end()
    child = _GreyGlyph(QPixmap.fromImage(clipped), icon)
    child.setOffset(icon.offset())
    child.setTransformationMode(icon.transformationMode())
    child.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
    child.setData(Qt.ItemDataRole.UserRole, TAG_GREY)
    return child


def _scale_of(item):
    t = item.sceneTransform()
    return math.hypot(t.m11(), t.m12()), math.hypot(t.m21(), t.m22())


# ------------------------------------------------------------------ animator
class DignityAnimator(QObject):
    """ONE timer per scene for every moving part; idles while no view is visible."""
    NAME = "dignity_overlay_animator"

    def __init__(self, scene):
        super().__init__(scene)
        self.setObjectName(self.NAME)
        self._scene = scene
        self._parts = []
        self._t0 = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self.tick)

    @classmethod
    def of(cls, scene, create=True):
        found = scene.findChild(QObject, cls.NAME)
        return cls(scene) if found is None and create else found

    def reset(self, parts):
        self._parts = list(parts)
        if not self._parts:
            return self._timer.stop()
        self.tick()
        self._timer.start()

    @property
    def active(self):
        return self._timer.isActive()

    def tick(self):
        parts = [p for p in self._parts if shiboken6.isValid(p) and p.scene() is self._scene]
        self._parts = parts
        if not parts:
            self._timer.stop()
            return
        views = self._scene.views()
        visible = not views or any(v.isVisible() for v in views)
        self._timer.setInterval(FRAME_MS if visible else IDLE_MS)
        if not visible:
            return                            # nothing to see: no repaint, slow wake
        t = time.monotonic() - self._t0
        for part in parts:
            part.motion(part, t)


# ------------------------------------------------------------------ the pass
def overlay_planet(scene, icon, step, s, planet=None):
    """Decorate one planet ``icon`` (in ``scene``) with ``step`` at scale ``s``.
    Returns the moving parts."""
    planet = planet or getattr(icon, "planet_name", None)
    seed = pd.planet_seed(planet)
    layers, moving = step_layers(step, s, seed)
    centre = icon.mapToScene(icon.boundingRect().center())
    item = SheenItem(layers)
    # still sheen cached once: the moving parts above repaint only their small rects
    item.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)
    item.setPos(centre)
    item.setZValue(icon.zValue() + Z_ABOVE_ICON)
    item.setData(STEP_ROLE, step)
    item.setData(PLANET_ROLE, planet)
    scene.addItem(item)                       # Rule 18: the scene owns it
    parts = []
    for part_layers, motion in moving:
        part = _Part(part_layers, motion, item)   # the sheen item owns its parts
        motion(part, 0.0)                      # the still frame (CLI renders, hidden views)
        parts.append(part)
    if step == "DB":
        grey_glyph(icon, pd.SHEEN["DB"]["grey_r"] * s)
    del item
    return parts


def _steps(chart, varga_code, get):
    """``{planet: step}`` while the glow mode is "dignity", else None."""
    if not chart or not pd.dignity_on(get):
        return None
    return pd.overlay_steps(chart, varga_code)      # an engine error: the caller logs it


def dignity_scene(scene, chart, varga_code, planet_type, r_ref, wheel=False, get=None):
    """The view post-pass: while the glow mode is "dignity", every classical
    ``planet_type`` item gets the Burnish Clear mark of its dignity in the varga
    ``varga_code`` (libaditya code, None = rashi). ``r_ref``: the view's ONE
    reference half size (or a callable). Off: one settings read, nothing added.
    Returns the planets decorated."""
    if get is None:
        from managers.settings_manager import get_settings
        get = get_settings().get
    steps = _steps(chart, varga_code, get)
    icons = [i for i in scene.items() if isinstance(i, planet_type)
             and getattr(i, "planet_name", None) in steps] if steps else []
    animator = DignityAnimator.of(scene, create=bool(icons))
    if not icons:
        if animator is not None:
            animator.reset([])
        return 0
    s = pd.sheen_scale(r_ref() if callable(r_ref) else r_ref, wheel)
    parts = []
    for icon in icons:
        parts += overlay_planet(scene, icon, steps[icon.planet_name], s)
    animator.reset(parts)
    return len(icons)


def overlay_items(scene):
    """The overlay's still items in ``scene`` (tests, visual checks)."""
    return [i for i in scene.items() if isinstance(i, SheenItem)]
