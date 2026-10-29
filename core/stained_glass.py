# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""Stained glass, the wheel strength colour of V1 and V2 (SPEC-RST-001 D-30, td-9scg9).

Lorris's choice of 2026-10-14 (Candidate D with the R5 glow). ``colour(base, t, light)``,
``t`` in -1..1: 0 = the plain colour (the wheel with the strength off), +1 = the strongest,
-1 = the weakest.

- Strong (t > 0): the hue moves to its pure pigment hue (OKLCH red 28, gold 88, blue 262,
  violet 305; browns keep their own), the OKLCH lightness to a gem level and the chroma to
  the sRGB gamut edge, all by ``smooth(t)``. A coral turns a clean deep red, never mush.
- Weak (t < 0): the chroma falls (to 35 % at -1), and only past t = -0.3 the colour leans up
  to 30 % toward the theme's cell grey: muted, washed only at the very low end.
- ``pool_glow``: on a red family cell (OKLCH hue within 30 deg of 25, browns excluded) the
  V1 light pool takes a light tint of the cell's own colour (L + 0.24, chroma x 0.55)
  instead of warm white, so the red never reads orange; other cells keep their pool.

V1: ``t = (g - f) / 0.6`` from the lamplight pulls (``retinue_strength.bright_pulls``).
V2: ``t = 2u - 1`` from the Uccha channel (``jewel_lamp.look(curve="glass")``).
Qt-free, raw hex in and out (the paint points desaturate once, SPEC-SAT-001). The theme
comes from ``theme_probe`` (the Qt glue sets it to ``ui.qt_theme.is_light_theme``).
"""
from __future__ import annotations

import math
from functools import lru_cache
from typing import Callable, Tuple

GREY_DARK, GREY_LIGHT = "#4A4D55", "#C9CBD0"     # the theme's cell grey (weak end)
FAMILY_HUE = (28, 88, 262, 305)                  # red, gold, blue, violet (OKLCH)
CHROMA_KEEP, GREY_MIX = .35, .30                 # weak end at t = -1
RED_HUE, RED_SPAN = 25, 30                       # the red family of the glow tint
theme_probe: Callable[[], bool] = lambda: False


# ------------------------------------------------------------- OKLab / OKLCH
def _lin(c):
    return c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4


def _gam(c):
    return 12.92 * c if c <= .0031308 else 1.055 * c ** (1 / 2.4) - .055


def hex_rgb(value: str) -> Tuple[float, float, float]:
    v = value.lstrip("#")[-6:]
    return tuple(int(v[i:i + 2], 16) / 255 for i in (0, 2, 4))


def rgb_hex(rgb) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02X}" for c in rgb)


def to_oklab(rgb):
    r, g, b = (_lin(c) for c in rgb)
    l = .4122214708 * r + .5363325363 * g + .0514459929 * b
    m = .2119034982 * r + .6806995451 * g + .1073969566 * b
    s = .0883024619 * r + .2817188376 * g + .6299787005 * b
    l, m, s = (math.copysign(abs(x) ** (1 / 3), x) for x in (l, m, s))
    return (.2104542553 * l + .7936177850 * m - .0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + .4505937099 * s,
            .0259040371 * l + .7827717662 * m - .8086757660 * s)


def from_oklab(lab):
    L, a, b = lab
    l = (L + .3963377774 * a + .2158037573 * b) ** 3
    m = (L - .1055613458 * a - .0638541728 * b) ** 3
    s = (L - .0894841775 * a - 1.2914855480 * b) ** 3
    return (4.0767416621 * l - 3.3077115913 * m + .2309699292 * s,
            -1.2684380046 * l + 2.6097574011 * m - .3413193965 * s,
            -.0041960863 * l - .7034186147 * m + 1.7076147010 * s)


def lch(value: str) -> Tuple[float, float, float]:
    """OKLCH (lightness, chroma, hue degrees) of a hex colour."""
    L, a, b = to_oklab(hex_rgb(value))
    return L, math.hypot(a, b), math.degrees(math.atan2(b, a)) % 360


def _lch_rgb(L, C, h):
    return from_oklab((L, C * math.cos(math.radians(h)), C * math.sin(math.radians(h))))


def _in_gamut(rgb, e=1e-6):
    return all(-e <= c <= 1 + e for c in rgb)


@lru_cache(maxsize=4096)
def max_chroma(L: float, h: float) -> float:
    lo, hi = 0.0, .4
    for _ in range(22):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if _in_gamut(_lch_rgb(L, mid, h)) else (lo, mid)
    return lo


def lch_hex(L: float, C: float, h: float) -> str:
    C = min(C, max_chroma(L, h))
    return rgb_hex(tuple(_gam(max(0.0, min(1.0, c))) for c in _lch_rgb(L, C, h)))


def _lerp(a, b, t):
    return a + (b - a) * t


def _hue_lerp(a, b, t):
    return (a + ((b - a + 180) % 360 - 180) * t) % 360


def smooth(t: float) -> float:
    return t * t * (3 - 2 * t)


def is_brown(L: float, h: float) -> bool:
    return 40 <= h < 75 and L < .62


def is_red(base: str) -> bool:
    L, C, h = lch(base)
    return C > .05 and not is_brown(L, h) and abs((h - RED_HUE + 180) % 360 - 180) < RED_SPAN


# ------------------------------------------------------------- the curve
def _muted(base: str, t: float, light: bool) -> str:
    L, C, h = lch(base)
    k = -t
    C2 = C * (1 - (1 - CHROMA_KEEP) * k)
    gL = lch(GREY_LIGHT if light else GREY_DARK)[0]
    w = GREY_MIX * smooth(max(0.0, (k - .3) / .7))
    return lch_hex(_lerp(L, gL, w), C2 * (1 - w), h)


@lru_cache(maxsize=8192)
def colour(base: str, t: float, light: bool = False) -> str:
    """The stained glass colour of ``base`` at strength ``t`` (-1..1, 0 = ``base``)."""
    if t <= 0:
        return _muted(base, t, light)
    L, C, h = lch(base)
    brown = is_brown(L, h)
    target_h = h if brown else min(FAMILY_HUE, key=lambda f: abs((h - f + 180) % 360 - 180))
    if brown:
        gem_L = .50
    elif 70 <= target_h <= 110:
        gem_L = max(.52, min(.80, L - .06))
    else:
        gem_L = max(.50, min(.62, L - .04))
    s = smooth(t)
    h2, L2 = _hue_lerp(h, target_h, s), _lerp(L, gem_L, s)
    return lch_hex(L2, _lerp(C, max_chroma(L2, h2), s), h2)


def from_pulls(base: str, f: float, g: float) -> str:
    """V1 wheel fill from the lamplight pulls (weak ``f``, strong ``g``)."""
    if f == g == 0:
        return base
    return colour(base, max(-1.0, min(1.0, (g - f) / .6)), bool(theme_probe()))


def tint(fill: str) -> str:
    L, C, h = lch(fill)
    return lch_hex(min(.93, L + .24), C * .55, h)


def pool_glow(base: str, fill: str, glow: str) -> str:
    """The V1 pool colour: a tint of the cell's own colour on a red family cell, else ``glow``."""
    return tint(fill) if is_red(base) else glow


def wheel_glow(base: str, fill: str, glow: str, bright: bool, wood: bool = False) -> str:
    """``pool_glow`` on the wheel (``bright``, never wood); ``glow`` unchanged elsewhere."""
    return pool_glow(base, fill, glow) if bright and not wood else glow
