# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Jewel Lamp display-space adapters: captured palette, wood and wheel ink."""
from functools import lru_cache, partial
from PySide6.QtGui import QColor
from core import jewel_lamp as jl, jewel_star as jstar, retinue_strength as rs
from ui.qt_theme import _desat_hex_at, desat_hex, get_ui_saturation


@lru_cache(maxsize=101)
def _colour_transform(saturation):
    """A pure cache-stable callback that never reads mutable theme state."""
    return partial(_desat_hex_at, sat=saturation)


def colour_transform():
    return _colour_transform(get_ui_saturation())


def glass_look(base, parts, light, snap):
    return jl.glass_look(base, parts, light, transform=colour_transform(), **jstar.kw(snap))


def wood_ink(ground, stain, opacity, look, light):
    """Composite each painted wood layer after its own single display transform."""
    raw = rs.rgb_hex(rs.over(rs.hex_rgb(ground), rs.hex_rgb(stain), opacity))
    shown = rs.rgb_hex(rs.over(rs.hex_rgb(desat_hex(ground)), rs.hex_rgb(desat_hex(stain)), opacity))
    fitted = jl.ink_on(raw, look, light, transform=colour_transform(), displayed_ground=shown)
    return fitted.ink, fitted.sub_alpha, fitted


def wheel_style(look, ribbon):
    """Wheel text and ribbon share the displayed ink; fill stays raw for its painter."""
    from apps.widgets.retinue_strength_paint import CellStyle, qcolor
    ink = desat_hex(look.ink)
    filled = ribbon.fill_alpha + ribbon.track_alpha * (1 - ribbon.fill_alpha)
    return CellStyle(look.fill, None, ink, QColor('#00000000'), QColor('#00000000'),
                     ribbon.fraction, ribbon.width, qcolor(ink, ribbon.track_alpha),
                     qcolor(ink, filled), None)
