# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""The tour of the Tajika center drawing (SPEC-TJK-003 §4.9): an overlay veils the
unchanged drawing and paints one aspect (bundle, bead, studs: a ``TajikaCenterItem`` on a
one-aspect copy of the model) with a caption. The focus per (view, kind), the overlay item,
its placement after every rebuild and the caption pill are the shared tour's
(``south_indian_center_tour``, SPEC-VAC-001 §4.0); this module holds the Tajika caption
and focus picture and the Tajika API (``set_tajika_tour_focus``, ``tour_focus``)."""
from __future__ import annotations

import math
from dataclasses import replace

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QPainter

from core import tajika_center as tc
from core.strength_stone import WHITE
from apps.widgets import south_indian_center_tour as ct
from apps.widgets.south_indian_center_tour import caption_fonts  # noqa: F401  (old name)
from apps.widgets.south_indian_geometry import center_rect  # noqa: F401  (tests use tour.center_rect)
from apps.widgets.south_indian_tajika_center import (TAG_TAJIKA_CENTER, Z_TAJIKA_CENTER,
                                                     TajikaCenterItem, _c, _is_light)
from ui.qt_theme import get_theme_colors

TAG_TAJIKA_TOUR = "si.vector.tajika_tour"
Z_TAJIKA_TOUR = Z_TAJIKA_CENTER + 1     # just above the drawing, below the transit mini (52)
VEIL_ALPHA = 0.78
CAPTION_GAP = 26.0                      # scene units between the bead and the caption pill
CAPTION_SCALE = ct.CAPTION_SCALE        # head / tail text vs the stud code size
KIND = tc.TAJIKA


def caption_lines(a: tc.Aspect, label: str):
    """The two caption lines: "3 / 18 · Sun trine Moon", "42 virupas · orb 1.2° · Friend"."""
    head = f"{a.body1} {a.kind} {a.body2}"
    tail = [f"{a.virupas:.0f} virupas", f"orb {a.orb:.1f}°"]
    tail += [x for x in (a.relationship, a.motion) if x and x != "unknown"]
    return (f"{label} · {head}" if label else head), " · ".join(tail)


def _find_aspect(model: tc.CenterModel, pair):
    return next((a for a in model.drawn if {a.body1, a.body2} == set(pair)), None)


def caption_box(a: tc.Aspect, bead, w: float, h: float, inside: QRectF) -> QRectF:
    """Beside the bead on the outer side of the bow (off the aspect's own threads); a
    straight line: across it, on the side that fits. Kept inside, never on the bead."""
    mx, my = (a.curve.a[0] + a.curve.b[0]) / 2, (a.curve.a[1] + a.curve.b[1]) / 2
    dx, dy = bead[0] - mx, bead[1] - my
    if math.hypot(dx, dy) < 10.0:                             # straight: across the line
        dx, dy = a.curve.offset_dir
    norm = math.hypot(dx, dy) or 1.0
    dx, dy = dx / norm, dy / norm
    reach = tc.BEAD_R + CAPTION_GAP + abs(dx) * w / 2 + abs(dy) * h / 2
    for side in (1.0, -1.0):
        box = QRectF(bead[0] + side * dx * reach - w / 2, bead[1] + side * dy * reach - h / 2, w, h)
        if inside.contains(box):
            break
    x = min(max(box.left(), inside.left()), inside.right() - w)
    y = min(max(box.top(), inside.top()), inside.bottom() - h)
    keep = tc.BEAD_R + 10.0                     # pushed back over the bead: above or below it
    if QRectF(x, y, w, h).intersects(QRectF(bead[0] - keep, bead[1] - keep, 2 * keep, 2 * keep)):
        y = bead[1] + keep if bead[1] + keep + h <= inside.bottom() else bead[1] - keep - h
        y = min(max(y, inside.top()), inside.bottom() - h)
    return QRectF(x, y, w, h)


class _TajikaFocus:
    """The focus picture of one aspect: veil, bundle and studs of the two bodies (a
    ``TajikaCenterItem`` on a one-aspect copy of the model, never in a scene), caption."""

    def __init__(self, drawing: TajikaCenterItem, aspect: tc.Aspect, label: str):
        model = drawing._model
        pair = (aspect.body1, aspect.body2)
        bodies = {n: model.full.bodies[n] for n in pair}
        one = replace(model, full=replace(model.full, bodies=bodies), drawn=(aspect,),
                      lit=frozenset(pair), faded=frozenset())
        self._focus = TajikaCenterItem(one, drawing._pal, lambda: None, drawing._sign_name,
                                       drawing._code_px)
        self._aspect = aspect
        self._lines = caption_lines(aspect, label)
        self._pal = drawing._pal
        self._code_px = drawing._code_px

    def paint(self, painter: QPainter, frame: QRectF):
        veil = QColor(WHITE if _is_light() else get_theme_colors()["secondary_dark"])
        veil.setAlphaF(VEIL_ALPHA)
        ct.paint_veil(painter, frame, veil)
        self._focus._paint_bundles(painter, None)
        self._focus._paint_studs(painter, None)
        self._paint_caption(painter, frame)

    def _paint_caption(self, p: QPainter, frame: QRectF):
        a = self._aspect
        bead = self._focus._model.beads[(a.body1, a.body2)]
        layout = ct.caption_layout(self._code_px, self._lines, frame)
        pad = layout.pad
        box = caption_box(a, bead, layout.width, layout.height,
                          frame.adjusted(pad, pad, -pad, -pad))
        col = self._pal["categories"].get(a.category, self._pal["categories"]["NEUTRAL"])
        ct.paint_caption(p, box, self._lines, layout, _c(col), _c(self._pal["bead"], .96),
                         _c(self._pal["text"]))


def TajikaTourItem(drawing: TajikaCenterItem, aspect: tc.Aspect, label: str):
    """The overlay for one aspect: veil, focused bundle and studs, caption (the shared
    ``CenterTourItem``; no hover, no mouse buttons, INV-6)."""
    return ct.CenterTourItem(TAG_TAJIKA_TOUR, Z_TAJIKA_TOUR,
                             _TajikaFocus(drawing, aspect, label).paint)


def _overlay(drawing, focus):
    aspect = _find_aspect(drawing._model, focus.payload)
    return None if aspect is None else TajikaTourItem(drawing, aspect, focus.label)


_HOOKS = ct.TourKind(KIND, TAG_TAJIKA_CENTER, TAG_TAJIKA_TOUR, _overlay)


# ------------------------------------------------------------ placement
def _vector_child(target):
    return ct.vector_child(target)


def set_tajika_tour_focus(target, pair=None, label=""):
    """Focus one aspect (a pair of body names) on a South Indian host or vector view, or
    clear it with ``pair=None``. Returns True when the overlay is on screen."""
    view = _vector_child(target)
    if view is None:
        return False
    if pair:
        ct.set_tour_focus(view, KIND, (KIND, frozenset(pair)), label, tuple(pair))
    else:
        ct.clear_tour_focus(view, KIND)
    return tour_draw(view)


def tour_focus(target):
    """(pair, step label) of the Tajika focus on the target's vector view, or None."""
    focus = ct.tour_focus(target, KIND)
    return None if focus is None else (focus.payload, focus.label)


def tour_draw(view):
    """Drop the view's overlay and place it again for its focus (after a rebuild, or on a
    step). Nothing is placed when the drawing is not on screen or the pair is not drawn."""
    return ct.tour_draw(view, _HOOKS)
