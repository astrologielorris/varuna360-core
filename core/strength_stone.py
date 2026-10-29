# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""Strength panel keys: the Qt-free colour maths (SPEC-RST-001 D-20, D-21).

Which key is lit, the hex colour blends of the keycaps, and the colours of the
value stones (Moonstone Pill MC-INTENT). ``stone_style`` runs on every paint of
every lit cell, so its result is kept per argument set (R2 review 2026-10-13).
The painting lives in ``apps/panels/strength_source_keys.py``.
"""
from __future__ import annotations

from functools import lru_cache

from core import planet_strength_glow as psg
from core.retinue_strength import StrengthOptions, contrast, hex_rgb, luminance, rgb_hex

# Strength table column of each source (Planet | Digbala | Uccha | Chesta | DUC Bala).
SOURCE_COLUMN = {"digbala": 1, "uccha": 2, "chesta": 3, "duc": 4}
WHITE = "#FFFFFF"
BLACK = "#000000"
INK_DARK = "#14171C"   # the stone's dark text (Moonstone contrast rule)


def active_column(get) -> int | None:
    """The lit column for a ``get(key, default)`` settings reader, or None while
    the strength display is off."""
    opts = StrengthOptions.from_settings(get)
    if not opts.enabled:
        return None
    return SOURCE_COLUMN.get(opts.source)


def planet_lit(get) -> bool:
    """True while PLANET is lit: glow mode Strength AND a strength key lit."""
    return psg.glow_source(get) is not None


def mix(a: str, b: str, t: float) -> str:
    """Linear RGB blend of two hex colours (t=0 -> a, t=1 -> b)."""
    ra, rb = hex_rgb(a), hex_rgb(b)
    t = max(0.0, min(1.0, t))
    return rgb_hex(tuple(x + (y - x) * t for x, y in zip(ra, rb)))


def push_to_contrast(c: str, toward: str, ref: str, target: float) -> str:
    """Mix ``c`` toward ``toward`` in small steps until its contrast against
    ``ref`` reaches ``target`` (or ``toward`` itself)."""
    ref_rgb = hex_rgb(ref)
    for i in range(0, 41):
        m = mix(c, toward, i / 40)
        if contrast(hex_rgb(m), ref_rgb) >= target:
            return m
    return toward


def tint_colour(planet_hex: str, cell: str, light: bool) -> str:
    """Moonstone ``tintCol``: dark theme lifts the hue until contrast 3.2 against
    the cell; light theme deepens it until contrast 1.7 against white."""
    if light:
        return push_to_contrast(planet_hex, BLACK, WHITE, 1.7)
    return push_to_contrast(planet_hex, WHITE, cell, 3.2)


def fit_mix(base: str, c: str, a: float) -> str:
    """Moonstone ``fit``: mix(base, c, a), moved out of the luminance band
    0.165..0.27 where neither light nor dark text reads. The amount moves up
    (more colour) when a >= 0.45, else down, to the nearest amount outside the
    band; when that side has none, the other side's nearest one."""
    def out(x):
        lum = luminance(hex_rgb(mix(base, c, x)))
        return not (0.165 < lum < 0.27)

    if out(a):
        return mix(base, c, a)
    steps = [i / 100 for i in range(101)]
    up = [x for x in steps if x > a and out(x)]
    down = [x for x in reversed(steps) if x < a and out(x)]
    first, second = (up, down) if a >= 0.45 else (down, up)
    pick = first[0] if first else (second[0] if second else a)
    return mix(base, c, pick)


def stone_style(planet_hex: str, value: float, cell: str, text: str, light: bool) -> dict:
    """Colours of one value stone (Moonstone Pill MC-INTENT).

    ``t = value / 60``; fill M = fit(cell, tintCol(planet), a) with
    a = 0.14 + 0.56 t^1.3 (light) or 0.12 + 0.60 t^1.3 (dark); a radial gradient from
    M 6 % toward white (12 % on a dark theme with a bright M) at the top centre to M
    30 % toward the cell at the rim; a 1 px rim in the planet ink (contrast 4.6 against
    the cell) at alpha 0.25 + 0.55 t; text = theme text unless its contrast against M
    is below 4.5, then white or dark ink, whichever reads better; bold above t 0.75.
    A new dict each call; the colours are computed once per argument set.
    """
    return dict(_stone_style(planet_hex, float(value), cell, text, bool(light)))


@lru_cache(maxsize=512)
def _stone_style(planet_hex, value, cell, text, light):
    t = max(0.0, min(1.0, value / 60.0))
    c = tint_colour(planet_hex, cell, light)
    a = (0.14 + 0.56 * t ** 1.3) if light else (0.12 + 0.60 * t ** 1.3)
    m = fit_mix(cell, c, a)
    lift = 0.12 if (not light and luminance(hex_rgb(m)) >= 0.27) else 0.06
    ink = push_to_contrast(planet_hex, BLACK if light else WHITE, cell, 4.6)
    m_rgb = hex_rgb(m)
    if contrast(hex_rgb(text), m_rgb) >= 4.5:
        fg = text
    else:
        fg = WHITE if contrast(hex_rgb(WHITE), m_rgb) >= contrast(hex_rgb(INK_DARK), m_rgb) else INK_DARK
    return (("t", t), ("fill", m), ("top", mix(m, WHITE, lift)), ("rim", mix(m, cell, 0.30)),
            ("edge", ink), ("edge_alpha", 0.25 + 0.55 * t), ("text", fg), ("bold", t > 0.75))


def parse_value(text) -> float | None:
    """The number of a Strength cell ("51.8 R*" -> 51.8), or None."""
    try:
        return float(str(text).split()[0])
    except (ValueError, IndexError):
        return None
