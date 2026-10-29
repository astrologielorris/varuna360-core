# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Sign-lord strength ribbons in the 12 vector SI sign cells + the view's strength glue.

SPEC-RST-001 §4.3/§4.4. One owned, independently clearable scene item holds all
twelve ribbons. No Python reference is kept: the item is found by its tag, so a
``scene.clear()`` can never leave a dangling handle. Geometry comes from the
existing ``H n`` and cusp items of the same draw (their painted bounds); the
ribbon sits on the bottom line between them, clear of every foreground item.
"""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QFontMetricsF, QPainterPath
from PySide6.QtWidgets import QGraphicsItem

from apps.widgets.retinue_strength_paint import outline, qcolor
from apps.widgets.south_indian_geometry import (
    CONTENT_PADDING, TAG_BADGE_PILL, TAG_COT_CARD, TAG_CUSP, TAG_HOUSE_NUMBER, TAG_LAGNA,
    TAG_LAGNA_LABEL, TAG_PLANET, TAG_PLANET_TEXT, TAG_SIGN_ICON, TAG_SIGN_NAME, cell_rect)
from core.retinue_constants import sign_lord

TAG_SIGN_RIBBON = 'rst.sign_ribbon'
FOREGROUND = frozenset((TAG_HOUSE_NUMBER, TAG_CUSP, TAG_PLANET, TAG_PLANET_TEXT, TAG_SIGN_ICON,
                        TAG_SIGN_NAME, TAG_BADGE_PILL, TAG_COT_CARD, TAG_LAGNA, TAG_LAGNA_LABEL))
GAP = 6.0
MIN_SPAN = 24.0
TRACK_ALPHA = .14


class SignRibbonItem(QGraphicsItem):
    """All sign ribbons of one scene as pre-stroked outlines; paint only fills."""

    def __init__(self, fills):
        super().__init__()
        self._fills = fills                 # [(brush, outline path)], track before fill
        rect = QRectF()
        for _, path in fills:
            rect = rect.united(path.boundingRect())
        self._bounds = rect
        self.setZValue(5)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setData(Qt.ItemDataRole.UserRole, TAG_SIGN_RIBBON)

    def boundingRect(self):
        return self._bounds

    def paint(self, painter, option, widget=None):
        for brush, path in self._fills:
            painter.fillPath(path, brush)


def _tag(item):
    return item.data(Qt.ItemDataRole.UserRole)


def _sign_of(rect):
    centre = rect.center()
    for sign in range(12):
        if cell_rect(sign).contains(centre):
            return sign
    return None


def _current(items):
    """The sign-ribbon item(s) of this scene: a type check, no Qt call per item."""
    return [item for item in items if type(item) is SignRibbonItem]


def _foreground(items):
    """Foreground items of this draw with their painted scene bounds (one pass,
    no index query per sign); only when ribbons are built."""
    out = []
    for item in items:
        tag = _tag(item)
        if tag in FOREGROUND:
            out.append((tag, item, item.sceneBoundingRect()))
    return out


def _labels(foreground):
    """{sign: (house item, house rect, cusp rect or None)} from this draw's items."""
    houses, cusps = {}, {}
    for tag, item, rect in foreground:
        if tag == TAG_HOUSE_NUMBER:
            houses[_sign_of(rect)] = (item, rect)
        elif tag == TAG_CUSP:
            cusps[_sign_of(rect)] = rect
    return {sign: (item, rect, cusps.get(sign)) for sign, (item, rect) in houses.items()}


def _free_span(foreground, lo, hi, y, width):
    """Longest part of [lo, hi] on line y not crossed by a foreground item."""
    band = QRectF(lo, y - width / 2 - 1, hi - lo, width + 2)
    cuts = sorted((o.left() - GAP, o.right() + GAP) for _, _, o in foreground if o.intersects(band))
    best, cursor = (lo, lo), lo
    for a, b in cuts + [(hi, hi)]:
        if min(a, hi) - cursor > best[1] - best[0]:
            best = (cursor, min(a, hi))
        cursor = max(cursor, b)
    return best


def ribbon_spans(foreground, q):
    """[(sign, H n item, lo, hi, y, width, q of the sign lord)]: each sign cell's
    free bottom line between ``H n`` and the cusp label (round caps inside)."""
    spans = []
    for sign, (house, rect, cusp) in sorted(_labels(foreground).items(), key=lambda kv: (kv[0] is None, kv[0])):
        lord_q = None if sign is None else q.get(sign_lord(sign))
        if lord_q is None:
            continue
        width = max(2.0, QFontMetricsF(house.font()).height() * .18)
        y = rect.center().y()
        hi = cusp.left() - GAP if cusp is not None else cell_rect(sign).right() - CONTENT_PADDING
        lo, hi = _free_span(foreground, rect.right() + GAP, hi, y, width)
        if hi - lo - width < MIN_SPAN:
            continue
        spans.append((sign, house, lo + width / 2, hi - width / 2, y, width, lord_q))
    return spans


def ribbon_fills(foreground, q, amount):
    """[(brush, outline)], the "fine" style: per cell the track, then the filled
    part (length = q of the sign lord), in the cell's ``H n`` ink."""
    fills = []
    for _sign, house, lo, hi, y, width, lord_q in ribbon_spans(foreground, q):
        ink = house.defaultTextColor()
        track = QPainterPath(QPointF(lo, y))
        track.lineTo(QPointF(hi, y))
        fills.append((QBrush(qcolor(ink, TRACK_ALPHA)), outline(track, width)))
        if lord_q > 0:
            filled = QPainterPath(QPointF(lo, y))
            filled.lineTo(QPointF(lo + (hi - lo) * lord_q, y))
            fills.append((QBrush(qcolor(ink, .45 + .45 * amount)), outline(filled, width)))
    return fills


def signs_eligible(view, options):
    """Enabled, sign ribbon on, chart drawn, vector style active, not a mini.

    A placement frame draws no ``H n`` items, so it yields no ribbon by itself."""
    return bool(options.enabled and options.sign_ribbon and view._chart
                and view.center_box_enabled and view.retinue.style_active)
