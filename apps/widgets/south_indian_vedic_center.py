# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""The Vedic aspects drawn in the vector South Indian center box ("Stained Light",
SPEC-VAC-001 §3.4-§3.6).

ONE ``VedicCenterItem`` per rebuild paints the Qt-free model of ``core.vedic_center``: the
pearl plate, the shared loom frame and track, the Yuti bars, the casts weakest first (glow,
ray, white core, cone), their glass lenses, the exact-degree marks and the studs (champagne
with an enamel ring in the caster's hue; pewter for Rahu and Ketu). Every pen, brush,
gradient, path and font of the Vedic layers is built ONCE in the constructor (``CastInk``,
``YutiInk``, ``PlateInk``); ``paint`` only draws (the shared painters of
``center_drawing_paint`` for the frame, marks and studs; ``RevealCache`` during the reveal).

``paint_cast``, ``paint_lens`` and ``paint_yuti`` are module functions: the tour overlay
(``south_indian_vedic_tour``) paints its focus with the drawing item's own inks through
them, so no second item exists (§4.6). A cast is a direction and a strength only: no
aspect kind, no Tajika glyph (INV-11).

The switch-on animation never holds the item: it asks its ``elapsed`` callable how far the
reveal is (None = the full drawing). Tooltips: a hover hit-test; no mouse buttons (INV-6).
"""
from __future__ import annotations

import math
from functools import lru_cache, partial
from typing import Callable, Dict, Mapping, NamedTuple, Optional, Tuple

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath,
                           QPen, QRadialGradient)
from PySide6.QtWidgets import QGraphicsObject, QToolTip

from core import center_geometry as cg
from core import vedic_center as vc
from core.capabilities.karakas_aspects import YUTI
from core.vedic_center_text import bead_tooltip, lens_tooltip, stud_tooltip
from core.strength_stone import BLACK, WHITE, mix
from apps.widgets import center_drawing_item as cdi
from apps.widgets import center_drawing_paint as cdp
from apps.widgets.center_drawing_item import FADE_MS, STUD_POP_MS, stagger_ms
from apps.widgets.center_drawing_paint import colour as _c, is_light as _is_light
from apps.widgets.center_drawing_reveal import RevealCache
from apps.widgets.south_indian_geometry import center_rect
from apps.widgets.south_indian_tajika_center import palette as _frame_palette
from ui.qt_theme import get_theme_colors, get_ui_saturation

TAG_VEDIC_CENTER = "si.vector.vedic_center"
Z_VEDIC_CENTER = 10             # the Tajika item's z (above the medallion ring, below minis)

# ---- named material constants (§3.6, D-10; Rule 20 exception) ----------------------------
VEDIC_HUE = dict(zip(vc.CASTERS, ("#D69500", "#7A8FB2", "#C7362F", "#97561D", "#8741C6",
                                  "#2D63D4", "#36904A")))
NODE_HUE = cdp.PEWTER[1]                       # pewter body #C4C9CD
STRONG_GOLD, STRONG_HALO = "#E39A08", "#FFD25E"
PLATE_LIGHT = ("#F7F5F0", "#ECE8E0", "#E0DBD1")
PLATE_STOPS = (0.0, 0.72, 1.0)
YUTI_SHADOW = "#3B3326"
BEAD_FACE, BEAD_RIM, BEAD_INK = "#FFFDF8", "#6B5F4B", "#3D362B"
CONE_TIP = "#FFFEF8"
TOUR_DIM = "#30281E"                           # rgba(48, 40, 30) of the mockup's plate dim
RAIL_BANDS = ((45.0, "#E39A08"), (30.0, "#DE742A"), (15.0, "#C2577E"), (0.0, "#8389B4"))

# ---- plate, Yuti, rays, lenses, studs (§3.4) ---------------------------------------------
PLATE_INSET, PLATE_RADIUS, PLATE_RIM = 3.0, 24.0, 3.0
PLATE_ALPHA, WOOD_PLATE_ALPHA = 0.92, 0.85
YUTI_WIDTHS = (31.0, 26.0, 5.0)                # shadow, bar, highlight
YUTI_GLINT = (-4.0, -5.0)
BEAD_R = 17.0
BEAD_NUDGE_BELOW = 2 * cg.STUD_R + 50          # studs closer than this: bead moved inward
BEAD_NUDGE = cg.STUD_R + 16
BEAD_STEP, BEAD_MAX_STEPS = 8.0, 12          # never left under one of its two studs
GLOW_FROM = 30.0                               # casts of 30 virupas and more glow ...
NUMBER_FROM = 30.0                             # ... and carry their number on the lens
CONE_SEGMENTS = 16
INK_CACHE = 512                                # cast inks kept across rebuilds
_CONE_STEPS = tuple((i / CONE_SEGMENTS, (1.0 - i / CONE_SEGMENTS) ** 1.15)
                    for i in range(CONE_SEGMENTS + 1))
ENAMEL_INSET, ENAMEL_WIDTH, INNER_INSET = 4.5, 5.0, 7.5
# The catch-light arc of the mockup (SVG "M -.55 -.35 A .7 .7 0 0 1 .2 -.66", lens radii).
CATCH_FROM, CATCH_TO, CATCH_R = (-0.55, -0.35), (0.20, -0.66), 0.70

# ---- switch-on animation (§4.2; pop, fade and stagger shared, center_drawing_item) ------
CAST_START_MS = 250.0           # the studs pop and the Yutis fade in, then the casts


def animation_total_ms(count: int) -> float:
    """Studs, then ``count`` casts: always under 1.2 s (the stagger budget is 700 ms)."""
    return CAST_START_MS + max(0, count - 1) * stagger_ms(count) + FADE_MS


def palette(style) -> Dict[str, object]:
    """The §3.6 palette: the shared frame rows (SPEC-TJK-003 §3.7), the plate stops and
    alpha, the planet hues (lighter on a dark theme)."""
    base = _frame_palette(style)
    wood = bool(getattr(style, "wood", None))
    dark = not wood and not _is_light()
    if dark:
        th = get_theme_colors()
        plate = (th["secondary_light"], th["secondary"], th["secondary_dark"])
    else:
        plate = PLATE_LIGHT
    hues = {n: (mix(h, WHITE, .15) if dark else h) for n, h in VEDIC_HUE.items()}
    pal = {k: base[k] for k in ("line", "tick", "accent", "rim_dark", "text")}
    pal.update(plate=plate, plate_alpha=WOOD_PLATE_ALPHA if wood else PLATE_ALPHA,
               hues=hues, dark=dark)
    return pal


# ================================================================== inks (built once)
class PlateInk(NamedTuple):
    rect: QRectF
    brush: QBrush
    rim: QPen


class RayInk(NamedTuple):
    path: QPainterPath            # A .. lens
    glows: Tuple[QPen, ...]       # wide soft strokes under the ray (30 virupas and more)
    pen: QPen                     # hue -> lighter hue gradient
    core: QPen                    # thin white core
    cone: QPainterPath            # tapered ribbon lens .. receiver
    cone_brush: QBrush
    cone_pen: QPen


class LensInk(NamedTuple):
    center: QPointF
    r: float
    halos: Tuple[Tuple[float, QBrush], ...]   # gold glow discs (strong)
    rings: Tuple[Tuple[float, QPen], ...]     # gold ring (strong), dashed ring (special)
    glass: QBrush
    rim: QPen
    catch: QPainterPath
    catch_pen: QPen
    number: str                               # "" under 30 virupas
    font: QFont
    ink: QPen
    box: QRectF


class HueInk(NamedTuple):
    """One planet hue and the shades its casts are made of, desaturated once."""
    base: QColor
    ray_end: QColor           # mix(hue, white, .25)
    cone_start: QColor        # mix(hue, white, .45)
    glass_mid: QColor         # mix(hue, white, .62)
    glass_edge: QColor        # mix(hue, white, .10)
    rim: QColor               # mix(hue, black, .25)
    ink: QColor               # mix(hue, black, .45)


class Materials(NamedTuple):
    """The colours of one item: the hues and the fixed materials (§3.6)."""
    hues: Dict[str, HueInk]
    white: QColor
    tip: QColor
    gold: QColor
    halo: QColor


class CastInk(NamedTuple):
    cast: vc.Cast
    ray: RayInk
    lens: LensInk


class YutiInk(NamedTuple):
    yuti: vc.Yuti
    line: QLineF
    glint: QLineF
    shadow: QPen
    bar: QPen
    highlight: QPen
    bead: QPointF
    face: QBrush
    rim: QPen
    font: QFont
    ink: QPen
    box: QRectF


def hue_ink(hexv: str) -> HueInk:
    return HueInk(_c(hexv), _c(mix(hexv, WHITE, .25)), _c(mix(hexv, WHITE, .45)),
                  _c(mix(hexv, WHITE, .62)), _c(mix(hexv, WHITE, .10)),
                  _c(mix(hexv, BLACK, .25)), _c(mix(hexv, BLACK, .45)))


def materials(pal: Mapping) -> Materials:
    return Materials({n: hue_ink(h) for n, h in pal["hues"].items()}, _c(WHITE), _c(CONE_TIP),
                     _c(STRONG_GOLD), _c(STRONG_HALO))


def _a(colour: QColor, alpha: float) -> QColor:
    """A copy of ``colour`` with ``alpha`` (the colour itself is never changed)."""
    out = QColor(colour)
    out.setAlphaF(max(0.0, min(1.0, alpha)))
    return out


def _pen(fill, width: float) -> QPen:
    """A round-capped pen (a colour or a brush)."""
    return QPen(QBrush(fill), width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin)


def _quad(points) -> QPainterPath:
    a, q, b = points
    path = QPainterPath(QPointF(*a))
    path.quadTo(QPointF(*q), QPointF(*b))
    return path


def cone_path(points, r: float) -> QPainterPath:
    """The tapered ribbon on the cone part: half width ``r * .62 * (1 - s) ** 1.15 + .9``,
    ``s`` 0 at the lens and 1 at the receiver, CONE_SEGMENTS segments."""
    (ax, ay), (qx, qy), (bx, by) = points
    dx, dy = 2 * (qx - ax), 2 * (qy - ay)                # p(s) = A + s d + s^2 e
    ex, ey = ax - 2 * qx + bx, ay - 2 * qy + by
    left, right = [], []
    for s, taper in _CONE_STEPS:
        tx, ty = dx + 2 * s * ex, dy + 2 * s * ey
        k = (r * .62 * taper + .9) / (math.hypot(tx, ty) or 1.0)
        px, py = ax + s * (dx + s * ex), ay + s * (dy + s * ey)
        left.append((px - ty * k, py + tx * k))
        right.append((px + ty * k, py - tx * k))
    outline = left + right[::-1]
    path = QPainterPath()
    path.moveTo(*outline[0])
    for x, y in outline[1:]:
        path.lineTo(x, y)
    path.closeSubpath()
    return path


def ray_ink(cast: vc.Cast, lens: vc.Lens, hue: HueInk, mat: Materials) -> RayInk:
    v = cast.virupas
    w = 2.0 + 0.17 * v
    a, _q, m = lens.ray
    glows = ()
    if v >= GLOW_FROM:
        g = .18 + .25 * (v - 30.0) / 30.0
        glows = (_pen(_a(hue.base, g * .5), w + 12), _pen(_a(hue.base, g * .8), w + 6))
    op = .5 + .45 * v / 60.0
    grad = QLinearGradient(QPointF(*a), QPointF(*m))
    grad.setColorAt(0.0, _a(hue.base, op))
    grad.setColorAt(1.0, _a(hue.ray_end, op * .8))
    cone = QLinearGradient(QPointF(*lens.cone[0]), QPointF(*lens.cone[2]))
    cone.setColorAt(0.0, _a(hue.cone_start, .9))
    cone.setColorAt(1.0, mat.tip)
    return RayInk(_quad(lens.ray), glows, _pen(grad, w),
                  _pen(_a(mat.white, .25 + .35 * v / 60.0), max(.8, .22 * w)),
                  cone_path(lens.cone, lens.r), QBrush(cone), QPen(_a(hue.base, .45), 1.0))


def _catch_light(x: float, y: float, r: float) -> QPainterPath:
    """The white catch-light arc: the mockup's SVG arc (radius .7 r, sweep 1, small arc)."""
    (x1, y1), (x2, y2) = CATCH_FROM, CATCH_TO
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    half = math.hypot(x2 - x1, y2 - y1) / 2
    h = math.sqrt(max(0.0, CATCH_R ** 2 - half ** 2))
    ux, uy = (x2 - x1) / (2 * half), (y2 - y1) / (2 * half)
    cx, cy = mx - uy * h, my + ux * h                # the centre that gives sweep 1, small arc
    start = math.degrees(math.atan2(-(y1 - cy), x1 - cx))
    end = math.degrees(math.atan2(-(y2 - cy), x2 - cx))
    sweep = (end - start + 180.0) % 360.0 - 180.0
    rect = QRectF(x + (cx - CATCH_R) * r, y + (cy - CATCH_R) * r, 2 * CATCH_R * r, 2 * CATCH_R * r)
    path = QPainterPath(QPointF(x + x1 * r, y + y1 * r))
    path.arcTo(rect, start, sweep)
    return path


def _lens_marks(cast: vc.Cast, r: float, hue: HueInk, mat: Materials):
    """The strong halo and gold ring, the special dashed ring."""
    halos, rings = (), ()
    if cast.strong:
        halos = ((r + 9.0, QBrush(_a(mat.halo, .55 * .45))),
                 (r + 5.0, QBrush(_a(mat.halo, .55 * .55))))
        rings = ((r + 3.5, QPen(mat.gold, 3.2)),)
    if cast.special:
        dash = QPen(hue.rim, 1.8)
        dash.setCapStyle(Qt.PenCapStyle.FlatCap)
        dash.setDashPattern([3.0 / 1.8, 3.5 / 1.8])
        rings += ((r + 9.0, dash),)
    return halos, rings


def lens_font(r: float, code_px: int) -> QFont:
    """The lens number font: bold, ``min(17, 9 + .42 r) * code_px / 26`` pixels."""
    return cdp.code_font(max(6, round(min(17.0, 9.0 + .42 * r) * code_px / 26.0)))


def lens_ink(cast: vc.Cast, lens: vc.Lens, hue: HueInk, mat: Materials,
             font: QFont) -> LensInk:
    x, y = lens.center
    r = lens.r
    halos, rings = _lens_marks(cast, r, hue, mat)
    glass = QRadialGradient(QPointF(x - .2 * r, y - .32 * r), 1.4 * r)
    glass.setColorAt(0.0, mat.white)
    glass.setColorAt(.45, hue.glass_mid)
    glass.setColorAt(1.0, hue.glass_edge)
    number = f"{cast.virupas:.0f}" if cast.virupas >= NUMBER_FROM else ""
    return LensInk(QPointF(x, y), r, halos, rings, QBrush(glass), QPen(hue.rim, 1.7),
                   _catch_light(x, y, r), _pen(_a(mat.white, .95), max(1.2, .13 * r)), number,
                   font, QPen(hue.ink), QRectF(x - r, y - r + 1.0, 2 * r, 2 * r))


@lru_cache(maxsize=64)
def _hue_materials(hue_hex: str, saturation: int) -> Materials:
    """The materials of one hue (``saturation``: a key only), shared by its casts."""
    return materials({"hues": {hue_hex: hue_hex}})


@lru_cache(maxsize=INK_CACHE)
def cast_ink(cast: vc.Cast, lens: vc.Lens, hue_hex: str, code_px: int,
             saturation: int) -> CastInk:
    """The inks of one cast, built once. Cached across rebuilds: a theme, font or chart
    redraw with the same cast, lens, hue, label size and UI ``saturation`` (a key only:
    ``colour`` reads it) reuses them; pens, brushes and paths are value types, never
    changed after this."""
    mat = _hue_materials(hue_hex, saturation)
    hue = mat.hues[hue_hex]
    return CastInk(cast, ray_ink(cast, lens, hue, mat),
                   lens_ink(cast, lens, hue, mat, lens_font(lens.r, code_px)))


def bead_point(a: cg.Point, b: cg.Point) -> cg.Point:
    """The Y bead: midway; studs closer than BEAD_NUDGE_BELOW: moved toward the centre by
    BEAD_NUDGE, then on in BEAD_STEP steps while either stud would still cover it."""
    m = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    if math.hypot(b[0] - a[0], b[1] - a[1]) >= BEAD_NUDGE_BELOW:
        return m
    ux, uy = cg.toward_center(m)
    reach = BEAD_NUDGE
    for _ in range(BEAD_MAX_STEPS):
        p = (m[0] + ux * reach, m[1] + uy * reach)
        if min(math.dist(p, a), math.dist(p, b)) >= cg.STUD_R + BEAD_R:
            break
        reach += BEAD_STEP
    return p


def yuti_ink(yuti: vc.Yuti, bodies: Mapping[str, cg.Body], hues: Mapping[str, str],
             code_px: int) -> YutiInk:
    a, b = bodies[yuti.a].stud, bodies[yuti.b].stud
    shadow_w, bar_w, glint_w = YUTI_WIDTHS
    grad = QLinearGradient(QPointF(*a), QPointF(*b))
    grad.setColorAt(.15, _c(hues.get(yuti.a, NODE_HUE), .8))
    grad.setColorAt(.85, _c(hues.get(yuti.b, NODE_HUE), .8))
    line = QLineF(QPointF(*a), QPointF(*b))
    bx, by = bead_point(a, b)
    font = QFont()
    font.setBold(True)
    font.setPixelSize(max(8, round(min(22.0, 19.0 * code_px / 26.0))))
    return YutiInk(yuti, line, line.translated(*YUTI_GLINT), _pen(_c(YUTI_SHADOW, .25), shadow_w),
                   _pen(grad, bar_w), _pen(_c(WHITE, .55), glint_w), QPointF(bx, by),
                   QBrush(_c(BEAD_FACE)), QPen(_c(BEAD_RIM), 2.2), font, QPen(_c(BEAD_INK)),
                   QRectF(bx - BEAD_R, by - BEAD_R, 2 * BEAD_R, 2 * BEAD_R))


def plate_ink(pal: Mapping, rect: QRectF, alpha: Optional[float] = None) -> PlateInk:
    """The pearl plate: ``center_rect()`` inset 3, radial gradient (§3.6), white rim."""
    r = rect.adjusted(PLATE_INSET, PLATE_INSET, -PLATE_INSET, -PLATE_INSET)
    a = pal["plate_alpha"] if alpha is None else alpha
    grad = QRadialGradient(QPointF(r.center().x(), r.top() + .45 * r.height()), .74 * r.width())
    for stop, hexv in zip(PLATE_STOPS, pal["plate"]):
        grad.setColorAt(stop, _c(hexv, a))
    return PlateInk(r, QBrush(grad), QPen(_c(WHITE, .55), PLATE_RIM))


def ring_pens(hues: Mapping[str, str]) -> Dict[str, Tuple[QPen, QPen]]:
    """The casters' enamel ring and white inner ring (the nodes have none)."""
    return {n: (QPen(_c(h), ENAMEL_WIDTH), QPen(_c(WHITE, .7), 1.0)) for n, h in hues.items()}


# ================================================================== painters
def paint_plate(p: QPainter, plate: PlateInk):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(plate.brush)
    p.drawRoundedRect(plate.rect, PLATE_RADIUS, PLATE_RADIUS)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(plate.rim)
    p.drawRoundedRect(plate.rect, PLATE_RADIUS, PLATE_RADIUS)


def paint_cast(p: QPainter, ink: CastInk, alpha: float = 1.0):
    """One cast, complete: glow, ray, white core, cone (its lens is a later layer)."""
    ray = ink.ray
    p.setOpacity(alpha)
    p.setBrush(Qt.BrushStyle.NoBrush)
    for pen in ray.glows + (ray.pen, ray.core):
        p.setPen(pen)
        p.drawPath(ray.path)
    p.setPen(ray.cone_pen)
    p.setBrush(ray.cone_brush)
    p.drawPath(ray.cone)
    p.setOpacity(1.0)


def paint_lens(p: QPainter, ink: CastInk, alpha: float = 1.0):
    """The glass lens: halo, rings, glass disc, catch-light, number (30 and more)."""
    lens = ink.lens
    p.setOpacity(alpha)
    p.setPen(Qt.PenStyle.NoPen)
    for radius, brush in lens.halos:
        p.setBrush(brush)
        p.drawEllipse(lens.center, radius, radius)
    p.setBrush(Qt.BrushStyle.NoBrush)
    for radius, pen in lens.rings:
        p.setPen(pen)
        p.drawEllipse(lens.center, radius, radius)
    p.setPen(lens.rim)
    p.setBrush(lens.glass)
    p.drawEllipse(lens.center, lens.r, lens.r)
    p.setPen(lens.catch_pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(lens.catch)
    if lens.number:
        p.setFont(lens.font)
        p.setPen(lens.ink)
        p.drawText(lens.box, Qt.AlignmentFlag.AlignCenter, lens.number)
    p.setOpacity(1.0)


def paint_yuti(p: QPainter, ink: YutiInk, alpha: float = 1.0):
    """The Yuti bar blended from the two hues, and its Y bead."""
    p.setOpacity(alpha)
    p.setBrush(Qt.BrushStyle.NoBrush)
    for pen, line in ((ink.shadow, ink.line), (ink.bar, ink.line), (ink.highlight, ink.glint)):
        p.setPen(pen)
        p.drawLine(line)
    p.setPen(ink.rim)
    p.setBrush(ink.face)
    p.drawEllipse(ink.bead, BEAD_R, BEAD_R)
    p.setFont(ink.font)
    p.setPen(ink.ink)
    p.drawText(ink.box, Qt.AlignmentFlag.AlignCenter, YUTI)
    p.setOpacity(1.0)


def reveal_layers(plate: PlateInk, rect: QRectF, pal: Mapping, yutis, early, casts, alphas):
    """Plate, frame, Yutis and casts (weakest first) as (alpha, paint) in paint order."""
    layers = [(1.0, partial(paint_plate, plate=plate)),
              (1.0, partial(cdp.paint_frame, rect=rect, pal=pal))]
    layers += [(early, partial(paint_yuti, ink=ink, alpha=early)) for ink in yutis]
    return layers + [(a, partial(paint_cast, ink=ink, alpha=a)) for ink, a in zip(casts, alphas)]


def paint_enamel_ring(rings: Mapping[str, Tuple[QPen, QPen]], p: QPainter, x: float, y: float,
                      r: float, body=None):
    """The stud ring of ``center_drawing_paint.paint_studs`` for the Vedic drawing."""
    pens = rings.get(body.name) if body is not None else None
    if pens is None:
        return
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(pens[0])
    p.drawEllipse(QPointF(x, y), r - ENAMEL_INSET, r - ENAMEL_INSET)
    p.setPen(pens[1])
    p.drawEllipse(QPointF(x, y), r - INNER_INSET, r - INNER_INSET)


# ================================================================== the item
class VedicCenterItem(QGraphicsObject):
    """Paints one ``VedicModel`` inside ``center_rect()`` (see module docstring)."""

    def __init__(self, model: vc.VedicModel, pal: Dict[str, object],
                 elapsed: Callable[[], Optional[float]],
                 sign_name: Callable[[int], str], code_px: int):
        super().__init__()
        self._model = model
        self._pal = pal
        self._elapsed = elapsed
        self._sign_name = sign_name
        self._code_px = max(12, int(code_px))
        self._rect = center_rect()
        self._stagger = stagger_ms(len(model.drawn_casts))
        cdi.setup_item(self, Z_VEDIC_CENTER, TAG_VEDIC_CENTER)
        hues, saturation = pal["hues"], get_ui_saturation()
        self._casts = tuple(cast_ink(c, model.lenses[(c.caster, c.receiver)], hues[c.caster],
                                     self._code_px, saturation)
                            for c in model.drawn_casts)            # strongest first
        self._reveal = RevealCache()                # the finished layers of a running reveal
        self._yutis = tuple(yuti_ink(y, model.full.bodies, hues, self._code_px)
                            for y in model.drawn_yutis)
        self._inks = {ink.cast.key: ink for ink in self._casts}
        self._inks.update((ink.yuti.key, ink) for ink in self._yutis)
        self._plate = plate_ink(pal, self._rect)
        self._ring = partial(paint_enamel_ring, ring_pens(hues))
        self._font = cdp.code_font(self._code_px)
        self._studs = self.studs_painter()

    # ---------------------------------------------------------------- reading
    def boundingRect(self) -> QRectF:
        return self._rect

    @property
    def model(self) -> vc.VedicModel:
        return self._model

    @property
    def pal(self) -> Dict[str, object]:
        return self._pal

    @property
    def code_px(self) -> int:
        return self._code_px

    @property
    def sign_name(self) -> Callable[[int], str]:
        return self._sign_name

    def ink_for(self, key):
        """The prepared ink of a drawn cast (``("cast", c, r)``) or Yuti
        (``("yuti", frozenset)``), or None (§4.6 typed keys)."""
        return self._inks.get(key)

    def studs_painter(self, lit=None, faded=None) -> Callable[..., None]:
        """The shared stud painter bound to this drawing's bodies, rings and font
        (``lit`` / ``faded`` default to the model's); call it with the painter."""
        model = self._model
        return partial(cdp.paint_studs, bodies=model.full.bodies, order=vc.BODY_ORDER,
                       codes=vc.CODE_OF,
                       faded=model.faded if faded is None else faded,
                       lit=(model.lit_casters | model.lit_receivers) if lit is None else lit,
                       accent=self._pal["accent"], rim_dark=float(self._pal["rim_dark"]),
                       text_hex=self._pal["text"], font=self._font, ring=self._ring)

    # ----------------------------------------------------------------- paint
    def paint(self, painter: QPainter, option, widget=None):
        t_ms = self._elapsed()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        early = 1.0 if t_ms is None else max(0.0, min(1.0, t_ms / STUD_POP_MS))
        casts = self._casts[::-1]                                   # weakest first
        alphas = [self._alpha_at(rank, t_ms) for rank in range(len(casts))]
        layers = reveal_layers(self._plate, self._rect, self._pal, self._yutis, early, casts, alphas)
        self._reveal.paint(painter, layers, t_ms is not None)      # W6 S2: finished run once
        for ink, alpha in zip(casts, alphas):                       # strongest lens on top
            if alpha > 0.0:
                paint_lens(painter, ink, alpha)
        cdp.paint_marks(painter, self._model.full.bodies.values(), self._pal["tick"])
        self._studs(painter, scale=0.6 + 0.4 * early)
        painter.restore()

    def _alpha_at(self, rank: int, t_ms: Optional[float]) -> float:
        """Rank 0 = the weakest cast, the first to appear."""
        return cdi.reveal_alpha(t_ms, CAST_START_MS + rank * self._stagger)

    # --------------------------------------------------------------- tooltips
    def hoverMoveEvent(self, event):
        cdi.hover_tooltip(self, event)
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event):
        QToolTip.hideText()
        super().hoverLeaveEvent(event)

    def tooltip_at(self, x: float, y: float) -> str:
        """Stud, then lens (strongest on top), then Y bead: the paint order reversed."""
        bodies = self._model.full.bodies
        for b in bodies.values():
            if math.dist(b.stud, (x, y)) <= cg.STUD_R:
                return stud_tooltip(b, self._sign_name, bodies)
        for ink in self._casts:
            lens = ink.lens
            if math.hypot(lens.center.x() - x, lens.center.y() - y) <= lens.r:
                return lens_tooltip(ink.cast)
        for ink in self._yutis:
            if math.hypot(ink.bead.x() - x, ink.bead.y() - y) <= BEAD_R:
                return bead_tooltip(ink.yuti, self._sign_name)
        return ""
