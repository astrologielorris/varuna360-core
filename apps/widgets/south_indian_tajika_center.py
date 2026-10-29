# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""The Tajika aspects drawn in the vector South Indian center box (SPEC-TJK-003 §4.2).

ONE ``TajikaCenterItem`` per rebuild paints everything from the Qt-free model of
``core.tajika_center``: frosted veil and loom frame, squircle track with its sign
nails and boundary rays, the thread bundles (weakest first, so the strong ones pass
over), the glyph beads, the exact-degree ticks / pins / leaders and the studs. The
frame, track, marks and studs are the shared painters of ``center_drawing_paint``
(SPEC-VAC-001 §4.0); the veil, bundles and beads are Tajika's own.

The switch-on animation never holds the item: the item asks its ``elapsed`` callable
(owned by the view's CenterContentController) how far the reveal is, and paints the
final state when it answers None; during the reveal the finished leading layers (frame,
threads, beads) are painted once (``RevealCache``, SPEC-VAC-001 W6 S2). Tooltips come from
a hover hit-test; the item takes no mouse buttons, so the card clicks and hovers around it
are untouched (INV-6).
"""
from __future__ import annotations

import math
from functools import partial
from typing import Callable, Dict, Optional, Tuple

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QGraphicsObject, QToolTip

from core import tajika_center as tc
from core.planet_label import degree_text
from core.strength_stone import BLACK, WHITE, mix
from apps.widgets import center_drawing_item as cdi
from apps.widgets import center_drawing_paint as cdp
from apps.widgets.center_drawing_item import FADE_MS, STUD_POP_MS, stagger_ms
from apps.widgets.center_drawing_reveal import RevealCache, paint_layers
from apps.widgets.center_drawing_paint import colour as _c, is_light as _is_light
from apps.widgets.south_indian_geometry import center_rect
from ui.qt_theme import GOLD, get_theme_colors

TAG_TAJIKA_CENTER = "si.vector.tajika_center"


class TajikaStatusSignal(QObject):
    """Carries the vector view's Tajika precedence reason to the panel (§3.1)."""
    changed = Signal(str)
Z_TAJIKA_CENTER = 10            # above the medallion ring (2), below the transit mini (52)

# Lit-key discs for the bodies outside the Strength palette (§4.4).
EXTRA_DISC = {"Ascendant": "#6E7B8B", "Uranus": "#3D9A9A", "Neptune": "#7FA7C9",
              "Pluto": "#8E5A8E"}

SHORT = {"Ascendant": "LG", "Sun": "SU", "Moon": "MO", "Mars": "MA", "Mercury": "ME",
         "Jupiter": "JU", "Venus": "VE", "Saturn": "SA", "Uranus": "UR",
         "Neptune": "NE", "Pluto": "PL"}

# Animation timing (§4.2): studs pop over STUD_POP_MS, bundle i starts at
# BUNDLE_START_MS + i * stagger, fades over FADE_MS; running stitches lag a little. The
# pop, fade and stagger are the shared ones of ``center_drawing_item`` (W6 R2).
BUNDLE_START_MS = 200.0
STITCH_LAG_MS = 120.0


def animation_total_ms(count: int) -> float:
    return BUNDLE_START_MS + max(0, count - 1) * stagger_ms(count) + FADE_MS + STITCH_LAG_MS


def palette(style) -> Dict[str, object]:
    """The §3.7 palette for the current theme and chart finish (raw hex + alphas)."""
    from apps.delegates.highlight_delegate import TajikaHighlightDelegate
    th = get_theme_colors()
    light = _is_light()
    wood = bool(getattr(style, "wood", None))
    cmap = TajikaHighlightDelegate.CATEGORY_COLORS_MAP
    if wood:
        # wood faces are light with dark ink: a light halo under the threads (mockup)
        ink = style.ink("main", GOLD).name()
        brass = style.ink("brass", GOLD).name()
        pal = {"veil": (WHITE, .30, .08), "line": mix(brass, ink, .35), "tick": ink,
               "underlay": (mix(WHITE, brass, .10), .60), "bead": mix(WHITE, GOLD, .03),
               "categories": {k: v[3] for k, v in cmap.items()}, "rim_dark": 0.0}
    elif light:
        pal = {"veil": (WHITE, .36, .10), "line": mix(GOLD, th["secondary_text"], .45),
               "tick": mix(th["secondary_text"], GOLD, .25),
               "underlay": (mix(th["secondary"], WHITE, .80), .55),
               "bead": mix(WHITE, GOLD, .03),
               "categories": {k: v[3] for k, v in cmap.items()}, "rim_dark": 0.0}
    else:
        pal = {"veil": (th["secondary_light"], .30, .08),
               "line": mix(GOLD, th["secondary_text"], .25),
               "tick": mix(th["secondary_text"], GOLD, .15),
               "underlay": (mix(th["secondary_dark"], BLACK, .30), .55),
               "bead": th["secondary_light"],
               "categories": {k: v[1] for k, v in cmap.items()}, "rim_dark": .15}
    pal["accent"] = th["primary"]
    pal["text"] = "#2B2418"
    return pal


def stud_tooltip(body: tc.Body, sign_name: Callable[[int], str],
                 bodies: Dict[str, tc.Body]) -> str:
    names = (body.name,) + tuple(body.cluster)
    lines = []
    for n in names:
        b = bodies[n]
        sign = int(b.longitude // 30) % 12
        deg = degree_text(b.longitude - 30 * int(b.longitude // 30))   # the chart labels' (W6)
        lines.append(f"{n} · {sign_name(sign)} {deg}")
    return "\n".join(lines)


def bead_tooltip(a: tc.Aspect) -> str:
    motion = f" · {a.motion}" if a.motion and a.motion != "unknown" else ""
    return (f"{SHORT.get(a.body1, a.body1)}-{SHORT.get(a.body2, a.body2)}: {a.kind.capitalize()}\n"
            f"{a.virupas:.0f} VR | {a.orb:.1f} from exact\n{a.relationship}{motion}")


def paint_veil(pal: Dict[str, object], p: QPainter, r: QRectF):
    """The frosted veil inside the loom frame (the shared frame's fill)."""
    veil_hex, a0, a1 = pal["veil"]
    g = QRadialGradient(QPointF(*tc.SCENE_CENTER), r.width() * 0.7)
    g.setColorAt(0.0, _c(veil_hex, a0))
    g.setColorAt(1.0, _c(veil_hex, a1))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(g))
    p.drawRoundedRect(r, tc.FRAME_RADIUS, tc.FRAME_RADIUS)


def curve_path(curve: tc.Curve) -> QPainterPath:
    p = QPainterPath(QPointF(*curve.a))
    if curve.kind == "q":
        p.quadTo(QPointF(*curve.c1), QPointF(*curve.b))
    else:
        p.cubicTo(QPointF(*curve.c1), QPointF(*curve.c2), QPointF(*curve.b))
    return p


def thread_pens(pal: Dict[str, object], a: tc.Aspect, alpha: float) -> Tuple[QPen, QPen]:
    """One aspect's underlay and thread pens at ``alpha``."""
    cats = pal["categories"]
    under_hex, under_a = pal["underlay"]
    up = QPen(_c(under_hex, under_a * alpha), a.underlay_width)
    up.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen = QPen(_c(cats.get(a.category, cats["NEUTRAL"]), a.opacity * alpha), tc.THREAD_WIDTH)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    if a.secret:
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        pen.setDashPattern([15.0 / tc.THREAD_WIDTH, 10.0 / tc.THREAD_WIDTH])
    return up, pen


def bead_inks(pal: Dict[str, object], a: tc.Aspect) -> tuple:
    """One bead's shadow, face, rim pen and glyph colour (alpha-free: opacity paints it)."""
    cats = pal["categories"]
    col = cats.get(a.category, cats["NEUTRAL"])
    return _c("#000000", .14), _c(pal["bead"]), QPen(_c(col), 3.0), _c(col)


def paint_threads(pens: Tuple[QPen, QPen], threads, centre: QPainterPath, p: QPainter):
    """One aspect's underlay and threads (a layer of the reveal, W6 S2)."""
    p.setPen(pens[0])
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(centre)
    p.setPen(pens[1])
    for path in threads:
        p.drawPath(path)


def paint_bead(inks: tuple, a: tc.Aspect, xy, alpha: float, p: QPainter):
    """One aspect's glyph bead at ``alpha`` (a layer of the reveal, W6 S2)."""
    from apps.delegates.highlight_delegate import paint_aspect_shape
    shadow, face, rim, glyph = inks
    x, y = xy
    p.setOpacity(alpha)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(shadow)
    p.drawEllipse(QPointF(x, y + 2.5), tc.BEAD_R + 1, tc.BEAD_R + 1)
    p.setBrush(face)
    p.setPen(rim)
    p.drawEllipse(QPointF(x, y), tc.BEAD_R, tc.BEAD_R)
    paint_aspect_shape(p, a.kind, x, y, tc.BEAD_R * 0.62, glyph, 2.6)
    p.setOpacity(1.0)


class TajikaCenterItem(QGraphicsObject):
    """Paints one CenterModel inside ``center_rect()`` (see module docstring)."""

    def __init__(self, model: tc.CenterModel, pal: Dict[str, object],
                 elapsed: Callable[[], Optional[float]],
                 sign_name: Callable[[int], str], code_px: int):
        super().__init__()
        self._model = model
        self._pal = pal
        self._elapsed = elapsed
        self._sign_name = sign_name
        self._code_px = max(12, int(code_px))
        self._rect = center_rect()
        self._reveal = RevealCache()                # the finished layers of a running reveal
        cdi.setup_item(self, Z_TAJIKA_CENTER, TAG_TAJIKA_CENTER)   # T-11: repaints blit
        self._threads = [(a, [curve_path(a.curve.offset(o)) for o in a.thread_offsets()],
                          curve_path(a.curve), thread_pens(pal, a, 1.0), bead_inks(pal, a))
                         for a in model.drawn]                  # W6 S5: final inks built once

    # ---------------------------------------------------------------- geometry
    def boundingRect(self) -> QRectF:
        return self._rect

    # ----------------------------------------------------------------- paint
    def paint(self, painter: QPainter, option, widget=None):
        t = self._elapsed()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        layers = [(1.0, self._paint_frame)] + self._bundle_layers(t)
        self._reveal.paint(painter, layers, t is not None)          # W6 S2: finished run once
        cdp.paint_marks(painter, self._model.full.bodies.values(), self._pal["tick"])
        self._paint_studs(painter, t)
        painter.restore()

    def _alpha_at(self, rank: int, t: Optional[float], lag: float = 0.0) -> float:
        stagger = stagger_ms(len(self._model.drawn))
        return cdi.reveal_alpha(t, BUNDLE_START_MS + rank * stagger + lag)

    def _paint_frame(self, p: QPainter):
        cdp.paint_frame(p, self._rect, self._pal, partial(paint_veil, self._pal))

    def _bundle_layers(self, t: Optional[float]):
        """The threads of every aspect weakest first (the strong ones pass over), then the
        beads, strongest last (on top): (alpha, paint) in paint order."""
        ranks = {id(a): i for i, a in enumerate(self._model.drawn)}
        threads, beads = [], []
        for a, paths, centre, pens, inks in reversed(self._threads):
            alpha = self._alpha_at(ranks[id(a)], t, STITCH_LAG_MS if a.secret else 0.0)
            pens = pens if alpha >= 1.0 else thread_pens(self._pal, a, alpha)
            threads.append((alpha, partial(paint_threads, pens, paths, centre)))
            alpha = self._alpha_at(ranks[id(a)], t)
            xy = self._model.beads[(a.body1, a.body2)]
            beads.append((alpha, partial(paint_bead, inks, a, xy, alpha)))
        return threads + beads

    def _paint_bundles(self, p: QPainter, t: Optional[float]):
        paint_layers(p, self._bundle_layers(t))

    def _paint_studs(self, p: QPainter, t: Optional[float]):
        model = self._model
        scale = 1.0 if t is None else 0.6 + 0.4 * max(0.0, min(1.0, t / STUD_POP_MS))
        cdp.paint_studs(p, model.full.bodies, tc.BODY_ORDER, SHORT, faded=model.faded,
                          lit=model.lit, accent=self._pal["accent"],
                          rim_dark=float(self._pal.get("rim_dark", 0.0)),
                          text_hex=self._pal["text"], font=cdp.code_font(self._code_px),
                          scale=scale)

    # --------------------------------------------------------------- tooltips
    def hoverMoveEvent(self, event):
        cdi.hover_tooltip(self, event)
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event):
        QToolTip.hideText()
        super().hoverLeaveEvent(event)

    def tooltip_at(self, x: float, y: float) -> str:
        bodies = self._model.full.bodies
        for b in bodies.values():
            if math.dist(b.stud, (x, y)) <= tc.STUD_R:
                return stud_tooltip(b, self._sign_name, bodies)
        for a in self._model.drawn:
            if math.dist(self._model.beads[(a.body1, a.body2)], (x, y)) <= tc.BEAD_R:
                return bead_tooltip(a)
        return ""
