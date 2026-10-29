# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Vector SI strength glue: one options + q snapshot per retinue refresh, the sign ribbons
(fine or full style) and the sign colour (SPEC-RST-001 §4.3, D-12..D-15; V2: jewel_lamp_si).

Nothing is stored on the view: the sign-ribbon item is found by its type, a
coloured card carries a data mark, so ``scene.clear()`` resets both. Feature
OFF: no scan, no bala, nothing added. The new options are read only when the
feature is on; when they are off, the scene is exactly what it was before them.
"""
from typing import NamedTuple

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QFontMetricsF, QLinearGradient, QRadialGradient
from PySide6.QtWidgets import QGraphicsPathItem, QGraphicsSimpleTextItem

from apps.widgets.retinue_strength_paint import (
    NO_PEN, OFF_SNAPSHOT, _hard_stops, capsule, lit, lit_shape, pool_gradient, qcolor, snapshot,
    strength_options)
from apps.widgets.south_indian_geometry import (
    TAG_CARD, TAG_CUSP, TAG_HOUSE_NUMBER, TAG_LAGNA_LABEL, TAG_PLANET_TEXT)
from apps.widgets.south_indian_items import SignCardItem
from apps.widgets.south_indian_material import WoodFaceItem, outer_wood_palette, pigment
from apps.widgets.south_indian_retinue_layer import outer_palette
from apps.widgets.jewel_lamp_si import jewel_cards
from apps.widgets.south_indian_sign_ribbon import (
    SignRibbonItem, _current, _foreground, _sign_of, ribbon_fills, ribbon_spans, signs_eligible)
from core import retinue_strength as rs
from core import sign_strength as ss
from core.retinue_constants import sign_lord
from core.south_indian_retinue import Box
from ui.qt_theme import desat_hex, is_light_theme
from visualizations.wheel_constants import ELEMENT_COLORS, get_element_for_sign

COLOURED_ROLE = Qt.ItemDataRole.UserRole + 3     # set on a sign card once it is coloured
TAG_SIGN_POOL = 'rst.sign_pool'
INKED = (TAG_HOUSE_NUMBER, TAG_CUSP, TAG_PLANET_TEXT, TAG_LAGNA_LABEL)   # text drawn on the card


def sign_options():
    from managers.settings_manager import get_settings
    return ss.SignOptions.from_settings(get_settings().get)


class Ribbon(NamedTuple):
    """Filled and track colours, as ``_hard_stops`` reads them."""
    ink: QColor
    track: QColor


class Pool(NamedTuple):
    """Glow and rim colours, as ``pool_gradient`` / ``lit`` read them."""
    glow: QColor
    shadow: QColor


def full_fills(foreground, q, A):
    """The "full" style: the retinue ribbon's width, one outline with the track and the filled
    part (hard-stop gradient) and the element hue thread, on the fine style's free bottom line."""
    fills = []
    ribbon_style = rs.ribbon_params(0, A)
    for sign, house, lo, hi, y, fine, lord_q in ribbon_spans(foreground, q):
        width = min(ribbon_style.width * Box(sign).scale, .6 * QFontMetricsF(house.font()).height())
        lo, hi = lo - fine / 2 + width / 2, hi + fine / 2 - width / 2
        if hi <= lo:
            continue
        ink = house.defaultTextColor()
        filled = ribbon_style.fill_alpha + ribbon_style.track_alpha * (1 - ribbon_style.fill_alpha)
        start = QPointF(lo, y)
        brush = _hard_stops(QLinearGradient(start, QPointF(hi, y)),
                            Ribbon(qcolor(ink, filled), qcolor(ink, ribbon_style.track_alpha)), lord_q)
        fills.append((brush, capsule(start, hi - lo, width, True)))
        if lord_q > 0:
            thread = qcolor(desat_hex(ELEMENT_COLORS[get_element_for_sign(sign)]), ribbon_style.thread_alpha)
            fills.append((QBrush(thread), capsule(start, (hi - lo) * lord_q, width * ribbon_style.thread_ratio, True)))
    return fills


def _ink(item):
    color = item.brush().color() if isinstance(item, QGraphicsSimpleTextItem) else item.defaultTextColor()
    return color.name(), color.alphaF()


def _cards(items, wood):
    """This draw's sign cards not yet coloured: {sign: card}."""
    kind = WoodFaceItem if wood else SignCardItem
    out = {}
    for item in items:
        if type(item) is kind and item.data(Qt.ItemDataRole.UserRole) == TAG_CARD \
                and not item.data(COLOURED_ROLE):
            out[_sign_of(item.sceneBoundingRect())] = item
    return out


def _inks(foreground):
    """{sign: [(painted text colour, alpha)]} of the text drawn on each card."""
    inks = {}
    for tag, item, rect in foreground:
        if tag in INKED:
            inks.setdefault(_sign_of(rect), []).append(_ink(item))
    return inks


def _standard_card(card, lamp, pool, centre, radius):
    """Standard finish: the card's own gradient recipe on the lamplit base, plus
    one glow item inside the card."""
    rect = card.path().boundingRect()
    colour = QColor(desat_hex(lamp.fill))
    gradient = QRadialGradient(centre.x(), centre.y() - rect.height() * .15, rect.width() * .75)
    gradient.setColorAt(0.0, colour.lighter(120))
    gradient.setColorAt(0.5, colour)
    gradient.setColorAt(1.0, colour.darker(115))
    card.setBrush(QBrush(gradient))
    if lit(pool):
        item = QGraphicsPathItem(lit_shape(card.path(), pool, centre, radius), card)
        item.setPen(NO_PEN)
        item.setBrush(pool_gradient(pool, centre, radius))
        item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        item.setData(Qt.ItemDataRole.UserRole, TAG_SIGN_POOL)


def _material(wood, element):
    """(raw base colour, wood stain opacity or None): wood takes the stain's own
    opacity, as a retinue card, never the plain-card wash (.04-.08: invisible)."""
    if not wood:
        return ELEMENT_COLORS[element], None
    return wood['stain'][element]['c'], wood['stain'][element]['o']


def colour_cards(cards, foreground, snap, style):
    """Lamplight on the main sign cells by each sign lord's ``q``: a new card fill
    (standard: its gradient on the lamplit base, plus one glow item; wood: the stain at its
    moved opacity, glow composited in). No rim shadow: a square got it in its corners only.
    Labels keep their colours; the effect is held back instead (``sign_lamp``)."""
    inks, wood, A, memo = _inks(foreground), style.wood, snap.options.A, {}
    card_ground = (outer_wood_palette(style.finish) if wood else outer_palette(is_light_theme()))['card']
    for sign, card in cards.items():
        q = snap.q.get(sign_lord(sign), None) if sign is not None else None
        if q is None:
            continue
        base, stain_o = _material(wood, get_element_for_sign(sign))
        lamp = ss.sign_lamp(base, q, A, card_ground, inks.get(sign, ()), desat_hex, stain_o, memo=memo)
        pool = Pool(qcolor(desat_hex(lamp.glow), lamp.glow_alpha), qcolor(desat_hex(lamp.shadow), 0))
        rect = card.rect if wood else card.path().boundingRect()
        centre, radius = rect.center(), max(rect.width(), rect.height()) * .62
        if wood:
            colour = pigment(base, lamp.opacity)
            card.setBrush(pool_gradient(pool, centre, radius, base=colour) if lit(pool) else colour)
        else:
            _standard_card(card, lamp, pool, centre, radius)
        card.setData(COLOURED_ROLE, True)


def colour_eligible(view, sign):
    return bool(sign.colour and view._chart and view.center_box_enabled
                and view.retinue.style_active and view.placement_frame is None)


def _plain_cards(view, sign, items):
    """(cards still to colour, the draw's style) when the sign colour applies."""
    if not colour_eligible(view, sign):
        return {}, None
    style = view.appearance.style()
    return _cards(items, style.wood), style


def _decorate(scene, items, snap, sign, build, cards, style, view=None):
    """Colour the cards still plain and build the sign ribbons when missing."""
    foreground = _foreground(items)
    if cards:
        jewel_cards(cards, foreground, snap, style, view) or colour_cards(cards, foreground, snap, style)
    if build:
        fills = (full_fills if sign.style == 'full' else ribbon_fills)(foreground, snap.q, snap.options.A)
        if fills:
            scene.addItem(SignRibbonItem(fills))


def retinue_strength(view):
    """ONE options + q snapshot per retinue refresh, shared with the sign ribbons
    and the sign colour.

    Called from the view's ``_refresh_retinue`` (full draw, ring toggle, style
    switch, deferred reveal). Sign ribbons and colours are reconciled, never
    rebuilt when present, so ring toggles and reveals leave them alone."""
    options = strength_options()
    if not options.enabled:
        return OFF_SNAPSHOT
    sign = sign_options()
    scene, signs = view.scene, signs_eligible(view, options)
    items = scene.items()
    current = _current(items)
    build = signs and not current
    cards, style = _plain_cards(view, sign, items)
    snap = snapshot(view._chart, view.retinue_effective or build or bool(cards), options)
    for item in current if not signs else ():
        scene.removeItem(item)
    if snap.q and (build or cards):
        _decorate(scene, items, snap, sign, build, cards, style, view)
    return snap
