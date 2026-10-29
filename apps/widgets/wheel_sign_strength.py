# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Wheel main sign sectors: sign-lord colour and ribbon (SPEC-RST-001 D-12..D-15, td-w6xja).

Called once at the end of ``WheelView.draw_wheel``. Reuses the draw's retinue snapshot
when the rings are on, else takes its own (one bala call per draw at most). Every added
item is a plain C++ path item and a CHILD of its sector, so it rises with the
sector on hover and stays under the names, glyphs, cards and planets. Feature
OFF, or sign colour and sign ribbon both off: nothing is read beyond the options,
nothing is added.
"""
import math
from typing import NamedTuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QConicalGradient, QFontMetricsF, QPainterPath, QRadialGradient
from PySide6.QtWidgets import QGraphicsPathItem, QGraphicsSimpleTextItem, QGraphicsTextItem

from apps.widgets.wheel_items import ZodiacSectorItem
from apps.widgets.jewel_lamp_wheel import jewel_sectors
from apps.widgets.retinue_strength_paint import (
    NO_PEN, OFF_SNAPSHOT, WHEEL_CARD, _hard_stops, lit, lit_shape, outline, pool_gradient, qcolor, snapshot,
    strength_options)
from core import retinue_strength as rs
from core import sign_strength as ss
from core.retinue_constants import sign_lord
from ui.qt_theme import desat_hex
from visualizations.wheel_constants import element_text_color, get_element_for_sign
from visualizations.wheel_geometry import get_sector_start_angle

TAG_SIGN_POOL = 'rst.wheel_sign_pool'
TAG_SIGN_RIBBON = 'rst.wheel_sign_ribbon'
EDGE = 12                  # px between the ribbon and the sector's INNER radius (td-9scg9)
INSET_DEG = .8             # free angle kept at each sector edge (as the retinue arcs)
FOREGROUND_Z = 4           # names, glyphs, cards, planets and their labels sit at z >= 4


class Ribbon(NamedTuple):
    ink: QColor
    track: QColor


class Pool(NamedTuple):
    glow: QColor
    shadow: QColor


def _element_colour(sector):
    return ZodiacSectorItem.ELEMENT_COLORS[ZodiacSectorItem.ELEMENT_CYCLE[sector.sign_index % 4]]


def sign_options():
    from managers.settings_manager import get_settings
    return ss.SignOptions.from_settings(get_settings().get)


def _child(sector, path, brush, tag, z):
    item = QGraphicsPathItem(path, sector)
    item.setPen(NO_PEN)
    item.setBrush(brush)
    item.setZValue(z)
    item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
    item.setData(Qt.ItemDataRole.UserRole, tag)
    return item


def _sector_of(cx, cy, point, starts):
    """Sign index whose 30 deg sector contains the direction of ``point``."""
    a = math.degrees(math.atan2(cy - point.y(), point.x() - cx))
    for sign, start in starts.items():
        if (a - start) % 360 < 30:
            return sign
    return None


def _foreground(view):
    """Items drawn above the sectors (z >= 4), divider lines excepted, with their
    scene bounding rects (one pass; a path query of the scene index measured
    slower). No ``parentItem()`` call: on this scene it let PySide delete the
    wrapped C++ items (measured: 500 items -> 109)."""
    out = []
    for item in view.scene.items():
        if item.zValue() >= FOREGROUND_Z and item.isVisible() \
                and str(item.data(Qt.ItemDataRole.UserRole)) != 'sector_line':
            out.append((item, item.sceneBoundingRect()))
    return out


def _inks(foreground, view, starts):
    """{sign: [(text colour, alpha)]} of the text drawn on each sector (centre
    between the sectors' inner and outer radius)."""
    cx, cy, inks = view.cx, view.cy, {}
    for item, rect in foreground:
        if not view.r_center <= math.hypot(rect.center().x() - cx, rect.center().y() - cy) <= view.r_middle:
            continue
        if isinstance(item, QGraphicsTextItem):
            colour = item.defaultTextColor()
        elif isinstance(item, QGraphicsSimpleTextItem):
            colour = item.brush().color()
        else:
            continue
        if str(item.data(Qt.ItemDataRole.UserRole)).startswith('wheel.cot'):
            continue                                       # the card has its own fill
        inks.setdefault(_sector_of(cx, cy, rect.center(), starts), []).append(
            (colour.name(), colour.alphaF()))
    return inks


def colour_sector(sector, q, A, inks, view, start, memo=None):
    """The sector's gradient recipe on the lamplit base, plus a pool child."""
    base = _element_colour(sector)
    lamp = ss.sign_lamp(base, q, A, WHEEL_CARD, inks, desat_hex, memo=memo, bright=True)
    colour = QColor(desat_hex(lamp.fill))
    gradient = QRadialGradient(view.cx, view.cy, view.r_middle)
    gradient.setColorAt(0.3, colour.lighter(115))
    gradient.setColorAt(0.7, colour)
    gradient.setColorAt(1.0, colour.darker(110))
    sector.setBrush(QBrush(gradient))
    pool = Pool(qcolor(desat_hex(lamp.glow), lamp.glow_alpha),
                qcolor(desat_hex(lamp.shadow), lamp.shadow_alpha))
    if lit(pool):
        mid, r_mid = math.radians(start + 15), (view.r_center + view.r_middle) / 2
        centre = QPointF(view.cx + r_mid * math.cos(mid), view.cy - r_mid * math.sin(mid))
        radius = .75 * max(view.r_middle - view.r_center, r_mid * math.radians(30))
        _child(sector, lit_shape(sector.path(), pool, centre, radius, .8),
               pool_gradient(pool, centre, radius, stops=(.8, 1.0)), TAG_SIGN_POOL, 0)



def ribbon_width(style, A, name_height):
    return rs.ribbon_params(0, A, wheel=True).width if style == 'full' else max(2.0, name_height * .18)


def ribbon_sector(sector, q, A, style, view, start, ink, width):
    """One sign ribbon at ONE fixed place, the same in every sector (td-9scg9, supersedes
    the free-arc rule): an arc just outside the hub (``r_center + EDGE``) over the full
    30 deg, .8 deg margins at each edge (as the retinue arcs), filled from its start by ``q``."""
    params = rs.ribbon_params(q, A, wheel=True)
    full = style == 'full'
    r = view.r_center + EDGE + width / 2
    cap = math.degrees(width / 2 / r)
    a0, a1 = INSET_DEG + cap, 30 - INSET_DEG - cap
    colour, sweep, begin = ink[0], a1 - a0, start + a0
    filled = params.fill_alpha + params.track_alpha * (1 - params.fill_alpha) if full else .45 + .45 * A
    circle = QRectF(view.cx - r, view.cy - r, 2 * r, 2 * r)
    arc = QPainterPath()
    arc.arcMoveTo(circle, begin)
    arc.arcTo(circle, begin, sweep)
    brush = _hard_stops(QConicalGradient(QPointF(view.cx, view.cy), begin),
                        Ribbon(qcolor(colour, filled), qcolor(colour, params.track_alpha)),
                        q, sweep / 360, wrap=True)
    _child(sector, outline(arc, width), brush, TAG_SIGN_RIBBON, 1).setData(
        Qt.ItemDataRole.UserRole + 2, q)
    if full and q > 0:
        thread = QPainterPath()
        thread.arcMoveTo(circle, begin)
        thread.arcTo(circle, begin, sweep * q)
        hue = qcolor(desat_hex(_element_colour(sector)), params.thread_alpha)
        _child(sector, outline(thread, width * params.thread_ratio), QBrush(hue), TAG_SIGN_RIBBON, 1)


def _name_ink(foreground, sign):
    """(colour, font height) of the sign's name text, or the element fallback."""
    for item, _rect in foreground:
        if item.data(Qt.ItemDataRole.UserRole) == f'sign_name_{sign}' and isinstance(item, QGraphicsTextItem):
            return item.defaultTextColor(), QFontMetricsF(item.font()).height()
    return QColor(element_text_color(get_element_for_sign(sign))), 24.0


def _resolve(view, strength):
    """(snapshot, sign options) to draw, else None; reuses the rings' snapshot (options: on only)."""
    snap = strength.snap if strength is not None else OFF_SNAPSHOT
    options = snap.options if strength is not None else strength_options()
    if not (options.enabled and view._chart and view._zodiac_sector_items):
        return None
    sign = sign_options()
    if not (sign.colour or options.sign_ribbon):
        return None
    snap = snap if snap.q else snapshot(view._chart, True, options)
    return (snap, sign) if snap.q else None


def _colour(view, snap, starts, foreground):
    """The sign colour: V2 jewels, else the V1 lamplight (brighter since td-9scg9)."""
    lords = {i: sign_lord(i) for i in view._zodiac_sector_items}
    bases = {i: _element_colour(s) for i, s in view._zodiac_sector_items.items()}
    if jewel_sectors(view, snap, starts, lords, bases):
        return
    inks, memo = _inks(foreground, view, starts), {}
    for i, sector in view._zodiac_sector_items.items():
        q = snap.q.get(lords[i])
        if q is not None:
            colour_sector(sector, q, snap.options.A, inks.get(i, ()), view, starts[i], memo)


def wheel_signs(view, strength=None):
    """Sign colour and sign ribbons on the wheel's twelve sign sectors."""
    resolved = _resolve(view, strength)
    if resolved is None:
        return
    snap, sign = resolved
    A = snap.options.A
    starts = {i: get_sector_start_angle(i, view.rotation_offset) for i in view._zodiac_sector_items}
    foreground = _foreground(view)
    if sign.colour:
        _colour(view, snap, starts, foreground)
    if not snap.options.sign_ribbon:
        return
    names = {i: _name_ink(foreground, i) for i in starts}   # read after a V2 ink change
    width = ribbon_width(sign.style, A, max(h for _c, h in names.values()))
    for i, sector in view._zodiac_sector_items.items():
        q = snap.q.get(sign_lord(i))
        if q is not None:
            ribbon_sector(sector, q, A, sign.style, view, starts[i], names[i], width)
