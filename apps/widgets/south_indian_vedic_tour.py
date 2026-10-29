# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""The tour picture of the Vedic center drawing (SPEC-VAC-001 §4.6).

The overlay (the shared ``CenterTourItem``, just above the drawing) veils the drawing with
the plate at alpha .93 plus the mockup's plate dim, paints the frame again, then the one
focused cast (glow, ray, core, cone, lens) or Yuti (bar, bead) with the drawing item's
own prepared inks through ``paint_cast`` / ``paint_lens`` / ``paint_yuti``, the two studs
lit (the others faded) and a caption pill at 67.5 % of the scene height. No second
``VedicCenterItem`` exists: the overlay copies the item's value-type inks and never holds
the item (Rule 18).

The focus per (view, kind) with its typed key (``("cast", caster, receiver)`` or
``("yuti", frozenset({a, b}))``), the overlay placement after every rebuild and the
caption pill are the shared tour's (``south_indian_center_tour``).
"""
from __future__ import annotations

from typing import Optional, Tuple

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QPainter

from core import center_geometry as cg
from core import vedic_center as vc
from core import vedic_center_text as vtx
from apps.widgets import center_drawing_paint as cdp
from apps.widgets import south_indian_center_tour as ct
from apps.widgets import south_indian_vedic_center as vci
from apps.widgets.south_indian_geometry import center_rect

TAG_VEDIC_TOUR = "si.vector.vedic_tour"
Z_VEDIC_TOUR = vci.Z_VEDIC_CENTER + 1   # just above the drawing, below the transit mini (52)
VEIL_ALPHA = 0.93                       # the other casts show at about .07 (mockup fade)
DIM_ALPHA = 0.20
CAPTION_TOP = 1382.0                    # 67.5 % of the 2048 scene, centred horizontally
CAPTION_RIM = "#D8CCB2"
CAPTION_INK = "#2A2620"
KIND = vc.VEDIC


def caption_lines(ink, label: str, sign_name) -> Tuple[str, str]:
    """"1 / 19 · Saturn casts on Jupiter" / "58.1 virupas · strong · Jupiter casts 52.4
    back"; a Yuti: "... together in Varuna" / "Yuti · same sign, no virupa value"."""
    if isinstance(ink, vci.CastInk):
        head = vtx.cast_title(ink.cast)
        tail = " · ".join((vtx.cast_detail(ink.cast), vtx.cast_back(ink.cast)))
    else:
        head, tail = vtx.yuti_title(ink.yuti, sign_name), vtx.yuti_detail()
    return (f"{label} · {head}" if label else head), tail


def caption_box(width: float, height: float, frame: QRectF) -> QRectF:
    """The fixed pill: centred in the box, its top at CAPTION_TOP, kept inside the frame."""
    x = cg.SCENE_CENTER[0] - width / 2
    y = min(CAPTION_TOP, frame.bottom() - height)
    return QRectF(max(frame.left(), x), max(frame.top(), y), min(width, frame.width()), height)


class _VedicFocus:
    """The focus picture of one cast or Yuti, from the drawing item's prepared inks."""

    def __init__(self, drawing: vci.VedicCenterItem, ink, label: str):
        pair = (ink.cast.caster, ink.cast.receiver) if isinstance(ink, vci.CastInk) \
            else (ink.yuti.a, ink.yuti.b)
        others = frozenset(drawing.model.full.bodies) - frozenset(pair)
        self._rect = center_rect()
        self._pal = drawing.pal
        self._veil = vci.plate_ink(drawing.pal, self._rect, VEIL_ALPHA)
        self._dim = QBrush(cdp.colour(vci.TOUR_DIM, DIM_ALPHA))
        self._ink = ink
        self._studs = drawing.studs_painter(lit=frozenset(pair), faded=others)
        self._lines = caption_lines(ink, label, drawing.sign_name)
        frame = cdp.frame_rect(self._rect)
        self._layout = ct.caption_layout(drawing.code_px, self._lines, frame)
        pad = self._layout.pad
        self._box = caption_box(self._layout.width, self._layout.height,
                                frame.adjusted(pad, pad, -pad, -pad))
        self._caption_ink = (cdp.colour(CAPTION_RIM), cdp.colour(vci.BEAD_FACE, .96),
                             cdp.colour(CAPTION_INK))

    def paint(self, p: QPainter, frame: QRectF):
        vci.paint_plate(p, self._veil)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._dim)
        p.drawRoundedRect(self._veil.rect, vci.PLATE_RADIUS, vci.PLATE_RADIUS)
        cdp.paint_frame(p, self._rect, self._pal)
        if isinstance(self._ink, vci.CastInk):
            vci.paint_cast(p, self._ink)
            vci.paint_lens(p, self._ink)
        else:
            vci.paint_yuti(p, self._ink)
        self._studs(p)
        ct.paint_caption(p, self._box, self._lines, self._layout, *self._caption_ink)


def _overlay(drawing, focus):
    ink = drawing.ink_for(focus.key)
    if ink is None:
        return None
    return ct.CenterTourItem(TAG_VEDIC_TOUR, Z_VEDIC_TOUR,
                             _VedicFocus(drawing, ink, focus.label).paint)


_HOOKS = ct.TourKind(KIND, vci.TAG_VEDIC_CENTER, TAG_VEDIC_TOUR, _overlay)


def set_vedic_tour_focus(target, key: Optional[tuple] = None, label: str = "") -> bool:
    """Focus one drawn cast or Yuti (its typed key) on a South Indian host or vector view,
    or clear the Vedic focus with ``key=None``. Returns True when the overlay is on screen."""
    view = ct.vector_child(target)
    if view is None:
        return False
    if key:
        ct.set_tour_focus(view, KIND, tuple(key), label, tuple(key))
    else:
        ct.clear_tour_focus(view, KIND)
    return tour_draw(view)


def vedic_tour_focus(target):
    """(typed key, step label) of the Vedic focus on the target's vector view, or None."""
    focus = ct.tour_focus(target, KIND)
    return None if focus is None else (focus.key, focus.label)


def tour_draw(view) -> bool:
    """Drop the view's Vedic overlay and place it again for its focus (after a rebuild, or
    on a step). Nothing is placed when the drawing is not on screen or the mark is not
    drawn."""
    return ct.tour_draw(view, _HOOKS)
