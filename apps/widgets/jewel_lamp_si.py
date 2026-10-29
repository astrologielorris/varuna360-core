# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Jewel Lamp (V2) on the vector South Indian chart (SPEC-RST-001 §4.6, td-9scg9).

``strength_pass`` picks the retinue pass of the draw: the V1 ``StrengthPass``
unchanged, or ``JewelPass`` when the snapshot is a V2 one. ``JewelPass`` keeps the
V1 cell build and its ribbon (one ribbon, the lit key's value) and swaps the colours:
an opaque Uccha fill (wood: the stain, its opacity moved by Uccha as in V1), the
cell's own ink, and the light, cut, rim and burn as one prebuilt child under the
labels. ``jewel_cards`` does the same for the twelve main sign squares when the sign
colour option is on. The aim of the cut points from the chart centre to the square of
the planet's best house, snapped to the axis for a side square.
"""
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsItem, QGraphicsSimpleTextItem

from apps.widgets import jewel_lamp_items as jli
from apps.widgets.jewel_lamp_display import colour_transform, wood_ink
from apps.widgets.jewel_lamp_fill import card_look, cell_look
from apps.widgets.retinue_strength_paint import CellStyle, StrengthPass, qcolor
from apps.widgets.south_indian_geometry import cell_rect
from core import jewel_lamp as jl
from core import retinue_strength as rs
from core.retinue_constants import sign_lord
from core.south_indian_retinue import Box
from ui.qt_theme import desat_hex, is_light_theme

CLEAR = '#00000000'
REFERENCE_BOX = 388.0      # the mockup's outer sign tile, px (``px`` = scene px per mockup px)


def is_jewel(snap):
    return isinstance(snap, jl.JewelSnapshot) and snap.active


def si_aims(ascendant):
    """{planet: unit vector} from the chart centre to its best-house square, snapped."""
    centres = [cell_rect(sign).center() for sign in range(12)]
    mid = QPointF(sum(c.x() for c in centres) / 12, sum(c.y() for c in centres) / 12)
    aims = {}
    for planet, house in jl.BEST_HOUSE.items():
        c = centres[(int(ascendant) + house - 1) % 12]
        aims[planet] = jl.snapped_aim(c.x() - mid.x(), c.y() - mid.y())
    return aims


def strength_pass(snap, palette, wood, scale, ascendant=0):
    """The retinue pass of one SI rebuild: V2 when the snapshot is a V2 one, else V1."""
    if is_jewel(snap):
        return JewelPass(snap, palette, wood, scale, ascendant)
    return StrengthPass(snap, palette, wood, scale)


def wood_light(card):
    return rs.is_light_ground(card)


def centre_ink(ground_rgb, look, light_theme, displayed_ground=None):   # wood: (ink, sub alpha, look) on the stain (D-33)
    lk = jl.ink_on(rs.rgb_hex(ground_rgb), look, light_theme,
                   transform=colour_transform(), displayed_ground=displayed_ground)
    return lk.ink, lk.sub_alpha, lk


class JewelPass(StrengthPass):
    """One SI retinue rebuild in the V2 look (the V1 cell build, V2 colours + layers)."""

    def __init__(self, snap, palette, wood, scale, ascendant=0):
        super().__init__(snap, palette, wood, scale)
        self.aims = si_aims(ascendant)
        self.light = wood_light(self.card) if self.wood else is_light_theme()
        self.px = Box(0).card[2] / REFERENCE_BOX
        self.looks = {}

    def style(self, lord, ring, bg, text, wood_rec):
        key = (lord, ring, bg)
        if key not in self.styles:
            parts = self.snap.parts.get(lord)
            if parts is None:
                return None
            self.styles[key] = self._style(lord, parts, bg, wood_rec)
        return self.styles[key]

    def _style(self, lord, parts, bg, wood_rec):
        A, q = self.snap.options.A, self.snap.q.get(lord, 0.0)
        base = wood_rec['c'] if wood_rec else bg
        look = cell_look(self, base, parts, q, wood_rec)
        opacity = None
        ink, sub = look.ink, look.sub_alpha
        if wood_rec:
            u = jl.inputs(parts, self.snap.options.source, self.snap.options.amount).u
            opacity = rs.wood_opacity(wood_rec['o'], u, A)
            ink, sub, look = wood_ink(self.card, base, opacity, look, self.light)
        ribbon = rs.ribbon_params(q, A)
        filled = ribbon.fill_alpha + ribbon.track_alpha * (1 - ribbon.fill_alpha)
        line = desat_hex(rs.INK_WOOD_RIBBON if wood_rec else ink)
        style = CellStyle(base if wood_rec else look.fill, opacity, ink if wood_rec else desat_hex(ink), QColor(CLEAR), QColor(CLEAR),
                          ribbon.fraction, ribbon.width * self.scale, qcolor(line, ribbon.track_alpha),
                          qcolor(line, filled), qcolor(desat_hex(bg), ribbon.thread_alpha))
        self.looks[id(style)] = (look, self.aims.get(lord, (0.0, -1.0)), sub)
        return style

    def decorate(self, key, item, rect, style, label_rects):
        look, aim, sub = self.looks[id(style)]
        item.setOpacity(1)                         # V2: the fill is opaque
        dim_sub_line(item, sub)
        jli.decorate(item, jli.RectCell(rect, 4 * self.scale), look, aim, self.light, self.px)
        super().decorate(key, item, rect, style, label_rects)   # the ribbon (no V1 pool)


def dim_sub_line(item, alpha):
    """The cell's second text line (being type, Hora range) at the sub line alpha."""
    texts = [c for c in item.childItems() if isinstance(c, QGraphicsSimpleTextItem)]
    if len(texts) >= 2:
        brush = texts[1].brush()
        tone = QColor(brush.color())
        tone.setAlphaF(tone.alphaF() * alpha)
        texts[1].setBrush(tone)


# ------------------------------------------------------------- sign squares
def _set_ink(item, ink):
    """Recolour one text item, keeping its alpha."""
    if isinstance(item, QGraphicsSimpleTextItem):
        tone = QColor(desat_hex(ink))
        tone.setAlphaF(item.brush().color().alphaF())
        item.setBrush(tone)
    elif hasattr(item, 'setDefaultTextColor'):
        tone = QColor(desat_hex(ink))
        tone.setAlphaF(item.defaultTextColor().alphaF())
        item.setDefaultTextColor(tone)


class CardFrame:
    """What every sign square of one draw shares: ground, theme, aims, scale, texts."""

    def __init__(self, foreground, snap, style, view):
        from apps.widgets.south_indian_material import outer_wood_palette
        from apps.widgets.south_indian_retinue_layer import outer_palette
        from apps.widgets.south_indian_sign_ribbon import _sign_of
        from apps.widgets.south_indian_strength import INKED
        self.snap, self.wood = snap, style.wood
        palette = outer_wood_palette(style.finish) if self.wood else outer_palette(is_light_theme())
        self.ground = palette['card']
        self.light = wood_light(self.ground) if self.wood else is_light_theme()
        self.aims = si_aims(view.projection._effective_ascendant_sign_index())
        self.px = Box(0).card[2] / REFERENCE_BOX
        self.texts = {}
        for tag, item, rect in foreground:
            if tag in INKED:
                self.texts.setdefault(_sign_of(rect), []).append(item)

    def paint(self, sign, card, lord, parts):
        """One card: the V2 fill (wood: the stain at its Uccha opacity), the jewel
        layers under the labels, and the card's texts in its ink."""
        from apps.widgets.south_indian_material import pigment
        from apps.widgets.south_indian_strength import _material
        from visualizations.wheel_constants import get_element_for_sign
        opts = self.snap.options
        base, stain_o = _material(self.wood, get_element_for_sign(sign))
        look = card_look(self, base, parts, sign, lord)
        ink = look.ink
        if self.wood:
            opacity = rs.wood_opacity(stain_o, jl.inputs(parts, opts.source, opts.amount).u, opts.A)
            card.setBrush(pigment(base, opacity))
            ink, _sub, look = wood_ink(self.ground, base, opacity, look, self.light)
        else:
            card.setBrush(QColor(desat_hex(look.fill)))
        rect = card.rect if self.wood else card.path().boundingRect()
        card.setFlag(QGraphicsItem.GraphicsItemFlag.ItemClipsChildrenToShape)
        jli.decorate(card, jli.RectCell(rect, card_radius(card)), look,
                     self.aims.get(lord, (0.0, -1.0)), self.light, self.px, z=.5)
        for text in self.texts.get(sign, ()):
            _set_ink(text, ink)


def jewel_cards(cards, foreground, snap, style, view):
    """V2 sign squares: the sign lord's jewel on each card. False (nothing done) for V1."""
    if not is_jewel(snap):
        return False
    from apps.widgets.south_indian_strength import COLOURED_ROLE
    frame = CardFrame(foreground, snap, style, view)
    for sign, card in cards.items():
        lord = sign_lord(sign) if sign is not None else None
        parts = snap.parts.get(lord)
        if parts is not None:
            frame.paint(sign, card, lord, parts)
            card.setData(COLOURED_ROLE, True)
    return True


def card_radius(card):
    """A card's corner radius: the wood face's own, else the standard card's."""
    from apps.widgets.south_indian_items import CARD_RADIUS
    return getattr(card, 'radius', None) or CARD_RADIUS
