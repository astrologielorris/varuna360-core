# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""The size of the V2 star (SPEC-RST-001 D-32, td-9scg9). Qt-free.

The Light strength ``f = amount / 60`` (``core.jewel_light.scale``) scales the star twice:
its brightness (the snapshot's Chesta part is ``chesta / 60 x f``, unclamped, clamped by
``jewel_lamp.inputs``) and its pattern size: the radial radius R and the rays' half-length
Lr are those of the star at the planet's own Chesta, times ``f``, never past ``MAX_SIZE``
(about half the diagonal of a square cell). 60 = the first V2 star, 50 = 5/6 as bright and
5/6 as large, 0 = no star. ``LitOptions`` carries ``f`` in the V2 snapshot's options.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.retinue_strength import StrengthOptions

MAX_SIZE = .70             # R / g and Lr / g ceiling (g = sqrt(w h)): the star stays in its cell
MIN_EFFECT = .03


@dataclass(frozen=True)
class LitOptions(StrengthOptions):
    """The display options of a V2 draw plus the Light strength factor ``light`` (f)."""
    light: float = 1.0


def lit(options, light: float) -> LitOptions:
    o = options
    return LitOptions(o.enabled, o.source, o.amount, o.sign_ribbon, float(light))


def kw(snap) -> dict:
    """The ``jewel_lamp.look`` keywords a snapshot sets: key, colour strength, star size."""
    opts = snap.options
    return {"source": opts.source, "amount": opts.amount, "size": getattr(opts, "light", 1.0)}


def star(make, h: float, s: float, c: float, light_theme: bool, size: float = 1.0, chesta=None):
    """The star of a cell: ``make(h, s, c, light_theme)`` (``jewel_lamp.prism_star``) lit by
    the scaled Chesta ``c``, its R and Lr those of the planet's own Chesta times ``size``."""
    bright = make(h, s, c, light_theme)
    if bright is None or abs(size - 1.0) < 1e-12 or size <= 0:
        return bright
    own = max(MIN_EFFECT, min(1.0, (c if chesta is None else max(0.0, chesta)) / size))
    shape = make(h, s, own, light_theme)
    return bright._replace(radius=min(MAX_SIZE, shape.radius * size),
                           ray_half=min(MAX_SIZE, shape.ray_half * size))
