# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Planet strength glow, "Ember Aura" (SPEC-RST-001 D-21, td-e6jsp). Qt-free.

The PLANET key of the Strength panel, or Settings > Planet glow: Strength, is
``chart.planet_glow_mode`` = "strength". It works only with a lit strength key
(``chart.retinue_strength_on``): then every classical planet on the charts wears
one radial disc in its strength colour, sized and lit by the value of the lit
source. Otherwise the planets keep the manual glow (``planet_shadows``).

Maths on RAW hex and floats (the paint points desaturate once, SPEC-SAT-001).
``t = clamp(value / 60, 0, 1)``. The aura itself (D-21a, td-647kl) is in
``core.planet_aura``: radius ``R = r_ref (1.10 + 1.10 t)`` from ONE reference
half size per view, centre alpha ``min(.85, V / d)``, ``V = 0.08 + 0.52 t``, ``d``
the colour's difference to the ground under the planet, only its own colour fading
out (no edge ring, no shade: td-3zaz7, td-ws82s). Strength table
PLANET column: a disc, alpha .12 + .55 t at the centre to 0 at the edge; low
contrast adds a ring at alpha .12 + .30 t.
"""
from __future__ import annotations

from typing import Callable, Optional

from core.retinue_strength import KEY_ON, KEY_SOURCE, SOURCES, hex_rgb, luminance

KEY_MODE = "chart.planet_glow_mode"
MANUAL = "manual"
STRENGTH = "strength"
MODES = (MANUAL, STRENGTH)

# One strength palette: the auras, the PLANET column discs and the value stones
# of the lit strength column (Lorris 2026-10-12: the Moon is white, as in the sky).
STRENGTH_PALETTE = {
    "Sun": "#FFFF00", "Moon": "#FFFFFF", "Mars": "#FF0000", "Mercury": "#AA5500",
    "Jupiter": "#AA00FF", "Venus": "#0055FF", "Saturn": "#00FF00",
}



def strength_t(value) -> float:
    """``clamp(value / 60, 0, 1)``."""
    try:
        return max(0.0, min(1.0, float(value) / 60.0))
    except (TypeError, ValueError):
        return 0.0


def weak_on_theme(colour: str, light: bool) -> bool:
    """True where the planet colour reads weakly on the theme ground (the
    Strength table PLANET column ring)."""
    lum = luminance(hex_rgb(colour))
    return lum > 0.60 if light else lum < 0.18


def tint_alpha(value) -> float:
    """PLANET column disc: centre alpha 0.12 + 0.55 t (lighter than the stones)."""
    return 0.12 + 0.55 * strength_t(value)


def tint_ring_alpha(value) -> float:
    """PLANET column disc ring (low contrast only): 0.12 + 0.30 t."""
    return 0.12 + 0.30 * strength_t(value)


def glow_source(get: Callable) -> Optional[str]:
    """The lit strength source while PLANET and a strength key are both lit, else
    None (PLANET never works without a strength key)."""
    if get(KEY_MODE, MANUAL) != STRENGTH or not bool(get(KEY_ON, False)):
        return None
    source = get(KEY_SOURCE, "duc")
    return source if source in SOURCES else "duc"
