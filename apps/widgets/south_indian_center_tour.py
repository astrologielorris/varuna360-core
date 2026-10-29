# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""The tour overlay of the center drawings (SPEC-VAC-001 §4.6, SPEC-TJK-003 §4.9).

One focus per (vector view, drawing kind), stored with a typed key (Tajika
``("tajika", frozenset({b1, b2}))``) and a generation number, so a stale clear never
removes a newer focus. ``tour_draw`` drops the kind's overlay and places it again for its
focus: after every rebuild (the center pass calls it for the drawn kind only) and on each
step. ``CenterTourItem`` is the overlay: veil, focused mark and caption are painted by the
kind's own callable; this module also holds the caption pill (fonts that shrink to fit,
the pill and its two lines). The controller owns the timer.
"""
from __future__ import annotations

import itertools
import weakref
from typing import Callable, NamedTuple, Optional

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QGraphicsObject

from core import center_geometry as cg
from apps.widgets.center_drawing_paint import frame_rect
from apps.widgets.south_indian_center_pass import vector_child
from apps.widgets.south_indian_geometry import center_rect

CAPTION_SCALE = (1.35, 1.1)             # head / tail text vs the stud code size

_FOCUS = weakref.WeakKeyDictionary()    # vector view -> {kind: TourFocus}
_GENERATIONS = itertools.count(1)


class TourFocus(NamedTuple):
    key: tuple                # typed key: ("tajika", frozenset), ("cast", c, r), ("yuti", frozenset)
    label: str                # "3 / 18"
    payload: object           # the kind's own focus, as the controller gave it
    generation: int


class TourKind(NamedTuple):
    """What ``tour_draw`` needs from a drawing kind."""
    kind: str
    item_tag: str             # the drawing item's tag
    tour_tag: str             # the overlay's tag
    make_overlay: Callable    # (drawing item, TourFocus) -> overlay item or None


# ------------------------------------------------------------ focus per (view, kind)
def set_tour_focus(target, kind: str, key: tuple, label: str = "", payload=None) -> int:
    """Focus one mark of ``kind``; returns the focus generation (0: no vector view)."""
    view = vector_child(target)
    if view is None:
        return 0
    generation = next(_GENERATIONS)
    _FOCUS.setdefault(view, {})[kind] = TourFocus(key, label, payload, generation)
    return generation


def clear_tour_focus(target, kind: str, generation: Optional[int] = None) -> bool:
    """Drop the kind's focus; with ``generation``, only when it is still that focus."""
    view = vector_child(target)
    focus = tour_focus(view, kind) if view is not None else None
    if focus is None or generation not in (None, focus.generation):
        return False
    del _FOCUS[view][kind]
    return True


def tour_focus(target, kind: str) -> Optional[TourFocus]:
    view = vector_child(target)
    return _FOCUS.get(view, {}).get(kind) if view is not None else None


def tour_draw(view, hooks: TourKind) -> bool:
    """Drop the kind's overlay and place it again for its focus (after a rebuild, or on a
    step). Nothing is placed when the drawing is not on screen or the mark is not drawn."""
    scene = view.scene
    for old in view.items_by_tag(hooks.tour_tag):
        scene.removeItem(old)
        old.deleteLater()
    focus = tour_focus(view, hooks.kind)
    drawings = view.items_by_tag(hooks.item_tag) if focus else []
    if not drawings:
        return False
    item = hooks.make_overlay(drawings[0], focus)
    if item is None:
        return False
    scene.addItem(item)
    del item                                            # the scene owns it (Rule 18)
    return True


# ------------------------------------------------------------ the overlay item
class CenterTourItem(QGraphicsObject):
    """The tour overlay: ``paint_focus(painter, frame)`` paints veil, focused mark and
    caption inside the loom frame. No hover, no mouse buttons (INV-6)."""

    def __init__(self, tag: str, z: float, paint_focus: Callable[[QPainter, QRectF], None]):
        super().__init__()
        self._paint_focus = paint_focus
        self._rect = center_rect()
        self.setAcceptHoverEvents(False)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setZValue(z)
        self.setData(Qt.ItemDataRole.UserRole, tag)
        self.setCacheMode(self.CacheMode.DeviceCoordinateCache)

    def boundingRect(self) -> QRectF:
        return self._rect

    def paint(self, painter: QPainter, option, widget=None):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._paint_focus(painter, frame_rect(self._rect))
        painter.restore()


def paint_veil(p: QPainter, frame: QRectF, colour: QColor):
    """The tour's veil over the whole drawing, inside the loom frame."""
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(colour)
    p.drawRoundedRect(frame, cg.FRAME_RADIUS, cg.FRAME_RADIUS)


# ------------------------------------------------------------ the caption pill
def caption_fonts(code_px: int, lines, room: float):
    """Head and tail fonts and the text width; large Chart Labels shrink to ``room``."""
    head, tail, fit = QFont(), QFont(), 1.0
    head.setBold(True)
    for _ in range(3):
        head.setPixelSize(max(8, int(code_px * CAPTION_SCALE[0] * fit)))
        tail.setPixelSize(max(8, int(code_px * CAPTION_SCALE[1] * fit)))
        width = max(QFontMetricsF(head).horizontalAdvance(lines[0]),
                    QFontMetricsF(tail).horizontalAdvance(lines[1]))
        if width <= room:
            break
        fit *= room / width
    return head, tail, min(width, room)


class CaptionLayout(NamedTuple):
    head: QFont
    tail: QFont
    width: float
    height: float
    pad: float


def caption_layout(code_px: int, lines, frame: QRectF) -> CaptionLayout:
    """The pill's fonts and size for two lines inside ``frame``."""
    pad = code_px * 0.6
    head, tail, text_w = caption_fonts(code_px, lines, frame.width() - 4 * pad)
    height = QFontMetricsF(head).height() + QFontMetricsF(tail).height() + 1.6 * pad
    return CaptionLayout(head, tail, text_w + 2 * pad, height, pad)


def paint_caption(p: QPainter, box: QRectF, lines, layout: CaptionLayout, border: QColor,
                  fill: QColor, ink: QColor):
    """The pill (rounded, ``border`` 3 wide) and its two centred lines."""
    p.setPen(QPen(border, 3.0))
    p.setBrush(fill)
    p.drawRoundedRect(box, layout.height / 4, layout.height / 4)
    p.setPen(ink)
    p.setFont(layout.head)
    top = QRectF(box.left(), box.top() + 0.8 * layout.pad, box.width(),
                 QFontMetricsF(layout.head).height())
    p.drawText(top, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, lines[0])
    p.setFont(layout.tail)
    bottom = QRectF(box.left(), top.bottom(), box.width(), QFontMetricsF(layout.tail).height())
    p.drawText(bottom, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, lines[1])
