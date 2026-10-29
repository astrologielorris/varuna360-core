# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""How far a main sign cell's lamplight may go before its labels lose
readability (SPEC-RST-001 D-13, td-w6xja). Qt-free, maths on RAW hex.

Each pull (the weak sink, the strong richness, the rim shadow, the glow) gets
its own largest value at which every ink on the cell keeps
``min(4.5, KEEP x today's contrast)``. The limits do not depend on ``q``.
"""
from __future__ import annotations

from core import retinue_strength as rs

# Each label keeps min(4.5, KEEP x its contrast today): the labels keep their
# colour, so the effect is held back instead (D-13).
KEEP = .75


def _largest(ok, top: float, steps: int = 8) -> float:
    """Largest x in [0, top] with ok(x), ok assumed monotone (True at 0)."""
    if top <= 0 or ok(top):
        return max(0.0, top)
    lo, hi = 0.0, top
    for _ in range(steps):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if ok(mid) else (lo, mid)
    return lo


def fill_fg(base: str, f: float, g: float, card: str, bright: bool = False) -> str:
    """``lamp_fill`` (``bright``: ``bright_fill``) with its two pulls given directly (weak ``f``,
    strong ``g``): ``A = 2f + g`` and ``q = 1 - f/A`` give back exactly f and g."""
    a = 2 * f + g      # ``bright``: the pulls as such (weak ``A*max(0, 1-2q)``, rs.bright_pulls)
    return rs.bright_pulls(base, f, g) if bright else base if a <= 0 else rs.lamp_fill(base, 1 - f / a, a, card)


def _stain_opacity(wood_o: float, k: float) -> float:
    """Wood: the stain's opacity moved by ``k = A(2q-1)`` (``rs.wood_opacity``)."""
    return max(.04, min(.92, wood_o * (1 + k * 1.1))) if k else wood_o


def _readable(inks, today):
    """``readable(ground)``: every ink keeps ``min(4.5, KEEP x today's contrast)``."""
    limits = [min(rs.CONTRAST_TARGET, KEEP * rs.contrast(rs.over(today, colour, alpha), today))
              for colour, alpha in inks]
    return lambda ground: all(rs.contrast(rs.over(ground, colour, alpha), ground) >= limit - 1e-9
                              for (colour, alpha), limit in zip(inks, limits))


def _ground(base, card, under, desat, wood_o, bright=False):
    """``ground(weak, strong)``: the cell's composited fill for the two pulls."""
    if wood_o is None:
        return lambda weak, strong: rs.over(
            under, rs.hex_rgb(desat(fill_fg(base, weak, strong, card, bright))), 1.0)
    return lambda weak, strong: rs.over(under, rs.hex_rgb(desat(base)),
                                        _stain_opacity(wood_o, strong - weak))


def _limits(base, card, inks, A, desat, wood_o, glow_cap, bright=False):
    """(largest weak pull, largest strong pull, largest rim shadow, largest glow)
    the cell's labels allow; independent of q, so shareable between cells."""
    under = rs.hex_rgb(desat(card))
    readable = _readable([(rs.hex_rgb(c), a) for c, a in inks],
                         rs.over(under, rs.hex_rgb(desat(base)), 1.0 if wood_o is None else wood_o))
    ground = _ground(base, card, under, desat, wood_o, bright)
    f_max = _largest(lambda x: readable(ground(x, 0)), A)
    g_max = _largest(lambda x: readable(ground(0, x)), A)
    glow = rs.hex_rgb(desat(rs.glow_colour("sign", "")))
    shadow = rs.hex_rgb(desat(rs.shadow_colour(card, wood_o is not None)))
    return (f_max, g_max, _largest(lambda x: readable(rs.over(ground(f_max, 0), shadow, x)), .55),
            _largest(lambda x: readable(rs.over(ground(0, g_max), glow, x)), glow_cap))
