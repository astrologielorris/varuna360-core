# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Jewel Lamp (V2) on the wheel (SPEC-RST-001 §4.6, td-9scg9).

``wheel_strength_pass`` picks the ring pass of one draw: the V1 ``WheelStrengthPass``
(its wheel colours brighter since td-9scg9, ``rs.bright_fill``), or ``JewelWheelPass``
for a V2 snapshot. ``JewelWheelPass`` hands the opaque Uccha fill and the cell's ink to
the existing sector (``bg_color``, so the hover restore stays right), keeps the V1
ribbon arc, and adds the light, cut, rim and burn as one prebuilt child of the wedge,
which then clips its children. ``jewel_sector`` does the same for a sign sector when
the sign colour option is on. Light at the centre of each cell (mid radius, mid angle);
the cut aims at the house axis as the wheel places it (H10, H1, H7, H4 of the hub).
"""
import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsItem, QGraphicsSimpleTextItem, QGraphicsTextItem

from apps.widgets import jewel_lamp_items as jli
from apps.widgets.jewel_lamp_display import glass_look, wheel_style
from apps.widgets.retinue_strength_paint import WheelStrengthPass, wheel_snapshot
from core import jewel_lamp as jl, retinue_strength as rs, stained_glass as sg
from ui.qt_theme import desat_hex, is_light_theme
sg.theme_probe = is_light_theme    # the stained glass weak end follows the theme (D-30)

REFERENCE_TRIM_OUTER = 476.0   # the mockup's Trimsamsa outer radius (px = scene px per mockup px)
FOREGROUND_Z = 4


def is_jewel(snap):
    return isinstance(snap, jl.JewelSnapshot) and snap.active


def house_angles(view):
    """{house: screen angle (deg)} of the hub's house numbers, as the wheel draws them."""
    asc = view._get_effective_ascendant_degrees()
    angles = {h: (int(asc // 30) * 30 + (h - 1) * 30 + 15 + view.rotation_offset) % 360
              for h in range(1, 13)}
    if view._effective_house_display == "standard_western" and view._cusps:
        part = 'amsha_raw_in_sign_longitude' if view._varga_code else 'real_in_sign_longitude'  # as the hub
        cusps = [(view._cusps[h].sign() - 1) * 30 + getattr(view._cusps[h], part)() for h in range(1, 13)]
        for h in range(1, 13):
            span = (cusps[h % 12] - cusps[h - 1]) % 360
            angles[h] = (cusps[h - 1] + span / 2 + view.rotation_offset) % 360
    return angles


def wheel_aims(view):
    """{planet: unit vector} toward its best house as placed on screen."""
    angles = house_angles(view)
    return {planet: jl.angle_aim(angles[house]) for planet, house in jl.BEST_HOUSE.items()}


def wheel_px(view):
    return (view.r_outer + 300) / REFERENCE_TRIM_OUTER


def wheel_strength_pass(view):
    """The ring pass of one wheel draw: V2 for a V2 snapshot, else V1."""
    snap = wheel_snapshot(view)
    if is_jewel(snap):
        return JewelWheelPass(snap, wheel_aims(view), is_light_theme(), wheel_px(view))
    return WheelStrengthPass(snap)


class JewelWheelPass(WheelStrengthPass):
    """One wheel ring draw in the V2 look."""

    def __init__(self, snap, aims, light, px):
        super().__init__(snap)
        self.aims, self.light, self.px, self.looks = aims, light, px, {}

    def style(self, lord, ring, raw_bg, text):
        key = (lord, ring, raw_bg)
        if key not in self.styles:
            parts = self.snap.parts.get(lord)
            if parts is None:
                return None
            opts = self.snap.options
            look = glass_look(raw_bg, parts, self.light, self.snap)
            q = self.snap.q.get(lord, 0.0)
            ribbon = rs.ribbon_params(q, opts.A, wheel=True)
            style = wheel_style(look, ribbon)
            self.looks[id(style)] = (look, self.aims.get(lord, (0.0, -1.0)))
            self.styles[key] = style
        return self.styles[key]

    def decorate(self, sector, lord, ring, raw_bg, text, cx, cy, r_in, r_out, start, span):
        style = self.style(lord, ring, raw_bg, text) if self.on else None
        if style is None:
            return
        look, aim = self.looks[id(style)]
        sector.setFlag(QGraphicsItem.GraphicsItemFlag.ItemClipsChildrenToShape)
        jli.decorate(sector, jli.SectorCell(cx, cy, r_in, r_out, start, start + span),
                     look, aim, self.light, self.px, z=0)
        super().decorate(sector, lord, ring, raw_bg, text, cx, cy, r_in, r_out, start, span)


# ------------------------------------------------------------- sign sectors
def sector_texts(view, starts):
    """{sign: [text items]} drawn on each sign sector (between ``r_center`` and
    ``r_middle``), Cards of Truth plaques excepted (they have their own fill). No
    ``parentItem()`` call (SPEC-RST-001 D-17)."""
    out = {}
    for item in view.scene.items():
        if item.zValue() < FOREGROUND_Z or not isinstance(item, (QGraphicsTextItem, QGraphicsSimpleTextItem)):
            continue
        if str(item.data(Qt.ItemDataRole.UserRole)).startswith('wheel.cot'):
            continue
        c = item.sceneBoundingRect().center()
        dx, dy = c.x() - view.cx, c.y() - view.cy
        if view.r_center <= math.hypot(dx, dy) <= view.r_middle:
            angle = math.degrees(math.atan2(-dy, dx))
            for sign, start in starts.items():
                if (angle - start) % 360 < 30:
                    out.setdefault(sign, []).append(item)
                    break
    return out


def set_ink(item, ink):
    """Recolour one text item, keeping its alpha."""
    tone = QColor(desat_hex(ink))
    if isinstance(item, QGraphicsSimpleTextItem):
        tone.setAlphaF(item.brush().color().alphaF())
        item.setBrush(tone)
    else:
        tone.setAlphaF(item.defaultTextColor().alphaF())
        item.setDefaultTextColor(tone)


class SectorFrame:
    """What every sign sector of one wheel draw shares (aims, theme, scale, texts)."""

    def __init__(self, view, starts):
        self.aims, self.light, self.px = wheel_aims(view), is_light_theme(), wheel_px(view)
        self.texts = sector_texts(view, starts)
        self.cx, self.cy, self.r0, self.r1 = view.cx, view.cy, view.r_center, view.r_middle

    def paint(self, sector, base, lord, parts, snap, start):
        look = glass_look(base, parts, self.light, snap)
        sector.setBrush(QColor(desat_hex(look.fill)))
        sector.setFlag(QGraphicsItem.GraphicsItemFlag.ItemClipsChildrenToShape)
        jli.decorate(sector, jli.SectorCell(self.cx, self.cy, self.r0, self.r1, start, start + 30),
                     look, self.aims.get(lord, (0.0, -1.0)), self.light, self.px, z=0)
        for text in self.texts.get(sector.sign_index, ()):
            set_ink(text, look.ink)


def jewel_sectors(view, snap, starts, lords, bases):
    """V2 sign sectors (sign colour on). False (nothing done) for a V1 snapshot."""
    if not is_jewel(snap):
        return False
    frame = SectorFrame(view, starts)
    for i, sector in view._zodiac_sector_items.items():
        parts = snap.parts.get(lords[i])
        if parts is not None:
            frame.paint(sector, bases[i], lords[i], parts, snap, starts[i])
    return True
