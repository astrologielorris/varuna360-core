# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Jewel Lamp, the V2 retinue strength look (SPEC-RST-001 §4.6, td-9scg9). Qt-free.

One job per channel, from the ruling planet's three DUC parts (each ``value / 60``):
Uccha = COLOUR, fully opaque (the wheel: ``core.stained_glass``, D-30; the South Indian
standard cells: the V1 colour, D-31; wood: the "Morning Prism" curve); Digbala = CUT, four
bevel facets, the one facing the best house lit, the far one a tinted shade (never black),
a table edge and past k 0.5 a glint, flat when ``k < 0.03``; Chesta = LIGHT, the "Rose
Prism" star (centred radial light, two crossed rays), nothing when ``c < 0.03``. Two great
add a fine rim, three full burn white; each cell picks dark or light ink at its centre.
Keys: DUC = all channels, one key = its own (others neutral: u .5, no cut, no light); the
amount scales each input from its plain value by ``amount / 60``. RAW hex (SPEC-SAT-001)."""
from __future__ import annotations

import colorsys
import math
from typing import Dict, NamedTuple, Optional, Tuple

from core import bala_calculator
from core import jewel_ink as jink, jewel_light as jlight, jewel_star as jstar, stained_glass as sg
from core.retinue_strength import _FIELD, hex_rgb, rgb_hex, to_q

# The V1 | V2 switch of the Strength panel (td-9scg9); its own key, not a Settings page
# key (``core.retinue_strength.KEYS`` are the page's own).
KEY_STYLE = "chart.retinue_strength_style"
STYLES = ("v1", "v2")
DEFAULT_STYLE = "v2"
PARTS = ("digbala", "uccha", "chesta")

# Best house of each planet for the cut's aim (directional strength).
BEST_HOUSE = {"Sun": 10, "Mars": 10, "Jupiter": 1, "Mercury": 1, "Saturn": 7,
              "Moon": 4, "Venus": 4}
# Which channels a lit source key shows: (colour, cut, light).
CHANNELS = {"duc": (True, True, True), "uccha": (True, False, False),
            "digbala": (False, True, False), "chesta": (False, False, True)}
PLAIN_AMOUNT = 60          # the amount at which the look equals the mockup
NEUTRAL_U = .5             # the colour of a channel not shown: medium richness
MIN_EFFECT = .03           # below this, no cut / no light at all
INK_DARK, INK_LIGHT = jink.INK_DARK, jink.INK_LIGHT   # the inks (D-33: chosen in core.jewel_ink)
SUB_DARK, SUB_LIGHT = jink.SUB_DARK, jink.SUB_LIGHT
WHITE = "#FFFFFF"
BURN_MID = "#FFF6DC"

Vec = Tuple[float, float]


def style_from_settings(get) -> str:
    """The stored look, ``"v1"`` or ``"v2"`` (an unknown value falls back to the default)."""
    style = get(KEY_STYLE, DEFAULT_STYLE)
    return style if style in STYLES else DEFAULT_STYLE


class JewelSnapshot(NamedTuple):
    """The V2 snapshot of one draw: options (``jewel_star.LitOptions``, Light strength f), ``q``
    of the lit source (ribbons), the three DUC parts per planet (ONE bala call); duck-types V1."""
    options: object
    q: Dict[str, float]
    parts: Dict[str, Tuple[float, float, float]]

    @property
    def active(self) -> bool:
        return bool(self.options.enabled and self.q)


def snapshot(chart, options, get) -> Optional[JewelSnapshot]:
    """V2 only (else None): ``q`` as ``planet_strengths`` and the parts Digbala, Uccha, Chesta
    (``value / 60``; Chesta times the light strength f, its star size too, D-32), ONE bala call."""
    if style_from_settings(get) != "v2":
        return None
    field, light = _FIELD.get(options.source, "duc_bala"), jlight.scale(get(jlight.KEY_LIGHT, None))
    rows = bala_calculator.get_all_bala_data(chart, duc_method=bala_calculator.duc_method_from(get))
    return JewelSnapshot(jstar.lit(options, light), {p: to_q(row[field]) for p, row in rows.items()}, {p: (
        to_q(row["digbala"]), to_q(row["uccha"]), to_q(row["chesta"]) * light) for p, row in rows.items()})



def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def smoothstep(e0: float, e1: float, x: float) -> float:
    t = clamp((x - e0) / (e1 - e0))
    return t * t * (3 - 2 * t)


def hsl(value: str) -> Tuple[float, float, float]:
    """(hue degrees, saturation, lightness) of a hex colour."""
    h, l, s = colorsys.rgb_to_hls(*hex_rgb(value))
    return h * 360.0, s, l


def hsl_hex(h: float, s: float, l: float) -> str:
    return rgb_hex(colorsys.hls_to_rgb((h % 360.0) / 360.0, clamp(l), clamp(s)))


def mix(a: str, b: str, t: float) -> str:
    """Linear RGB mix of two hex colours (``t`` = share of ``b``)."""
    ra, rb = hex_rgb(a), hex_rgb(b)
    return rgb_hex(tuple(x + (y - x) * t for x, y in zip(ra, rb)))


class Inputs(NamedTuple):
    """The three parts after the source mask and the amount scale, 0..1."""
    d: float
    u: float
    c: float
    together: bool     # all three channels shown: the rim and the burn may appear


def inputs(parts: Tuple[float, float, float], source: str = "duc",
           amount: float = PLAIN_AMOUNT) -> Inputs:
    """Mask by the lit key; the colour strength scales colour and cut (light: D-32, in the snapshot)."""
    colour, cut, light = CHANNELS.get(source, CHANNELS["duc"])
    s = max(0.0, float(amount)) / PLAIN_AMOUNT
    d, u, c = (clamp(v) for v in parts)
    return Inputs(clamp(d * s) if cut else 0.0,
                  clamp(NEUTRAL_U + (u - NEUTRAL_U) * s) if colour else NEUTRAL_U,
                  c if light else 0.0,
                  colour and cut and light)


class Light(NamedTuple):
    """The prism star (Rose Prism), sizes as factors of ``g = sqrt(w * h)``."""
    core: str
    halo: str
    radius: float            # R / g
    stops: Tuple[Tuple[float, str, float], ...]   # (offset, colour, alpha)
    ray_alpha: float         # 0: no rays
    ray_half: float          # Lr / g
    ray_width: float         # px (mockup scale)
    ray_tints: Tuple[str, str]
    ray_mid: str


class Look(NamedTuple):
    fill: str                # opaque, raw hex
    hue: float
    sat: float
    lum: float
    hot: str
    shade: str
    k: float                 # cut depth, 0 = flat
    harm: float              # two great rim
    burn: float              # three full
    light: Optional[Light]   # None: no light at all
    ink: str
    sub_alpha: float
    centre: str              # the colour the ink was judged on
    chesta: float            # the light input c after the mask and the amount


def colour_curve(base: str, u: float, light_theme: bool) -> Tuple[float, float, float]:
    """Morning Prism (H, S, Lum) of the fill for Uccha ``u``: pale to rich, never dark."""
    h0, s0, l0 = hsl(base)
    r = 1 - (1 - u) ** 2.4
    if light_theme:
        return h0, min(1.0, s0 * (.18 + .90 * r)), .90 - .30 * r
    return h0, min(1.0, s0 * (.22 + .86 * r)), max(l0, .50) + .16 * (1 - r) - .04 * r


def prism_star(h: float, s: float, c: float, light_theme: bool) -> Optional[Light]:
    if c < MIN_EFFECT:
        return None
    halo = hsl_hex(h, min(1.0, s + .30), .80) if light_theme else hsl_hex(h, min(1.0, .8 * s + .2), .80)
    core = WHITE if light_theme else mix(WHITE, halo, .10)
    stops = ((0.0, core, .90 * c ** .9), (.22, halo, .55 * c), (.60, halo, .14 * c), (1.0, halo, 0.0))
    return Light(core, halo, .16 + .40 * c, stops, smoothstep(.15, .60, c), .18 + .42 * c,
                 1.8 if light_theme else 1.5,
                 (hsl_hex(h - 45, .9, .75), hsl_hex(h + 45, .9, .75)),
                 hsl_hex(h, .85, .60) if light_theme else WHITE)


def look(base: str, parts: Tuple[float, float, float], light_theme: bool, *, source: str = "duc",
         amount: float = PLAIN_AMOUNT, curve: str = "prism", fill: Optional[str] = None,
         size: float = 1.0, transform=None) -> Look:
    """The whole V2 look of one cell. ``base`` = the being or element colour (raw). The fill:
    ``fill`` as given (South Indian: the V1 colour, D-31), else ``curve`` "glass" (the wheel,
    ``core.stained_glass``, D-30) or "prism" (Morning Prism, wood). ``size``: the star's f (D-32)."""
    d, u, c, together = inputs(parts, source, amount)
    ranked = sorted((d, u, c), reverse=True)
    harm = smoothstep(.55, .92, ranked[1]) if together else 0.0
    burn = smoothstep(.80, .97, ranked[2]) if together else 0.0
    h, s, lum, fill = _fill(base, u, light_theme, curve, fill, harm, burn)
    hot = hsl_hex(h, min(1.0, s + .15), min(.95, lum + .25))
    shade = (hsl_hex(h, min(1.0, .9 * s + .1), .40) if light_theme else
             hsl_hex(h, min(1.0, 1.05 * s), max(.16, .42 * lum)))
    k = min(1.0, min(1.0, 1.08 * d) + .30 * burn)
    star = jstar.star(prism_star, h, s, c, light_theme, size, parts[2])     # D-32: its size
    star, ink, sub, centre = jink.readable(fill, star, burn, transform=transform)                  # D-33
    return Look(fill, h, s, lum, hot, shade, k if k >= MIN_EFFECT else 0.0, harm, burn, star, ink, sub, centre, c)


def _fill(base, u, light_theme, curve, fill, harm, burn):
    """(H, S, Lum, fill): a given fill as is, else the curve lifted by the rim and burn."""
    if fill is not None:
        return hsl(fill) + (fill,)
    h, s, lum = hsl(sg.colour(base, 2 * u - 1, light_theme)) if curve == "glass" else colour_curve(base, u, light_theme)
    s, lum = min(1.0, s + .06 * harm + .30 * burn), min(.94, lum + (.02 if light_theme else .04) * harm + .18 * burn)
    return h, s, lum, hsl_hex(h, s, lum)


def glass_look(*args, **kw) -> Look:   # ``look`` with the wheel's stained glass fill (D-30)
    return look(*args, curve="glass", **kw)


def ink_on(ground: str, lk: Look, light_theme: bool = False, *, transform=None,
           displayed_ground: Optional[str] = None) -> Look:
    """``lk`` painted over another ground (a wood stain): the ink judged there, the star
    dimmed if the label needs it (D-33), as ``look`` does on its own fill."""
    star, ink, sub, centre = jink.readable(ground, lk.light, lk.burn, transform=transform,
                                              displayed_ground=displayed_ground)
    return lk._replace(light=star, ink=ink, sub_alpha=sub, centre=centre)


# ------------------------------------------------------------------ the cut
def bevel(size: float, k: float, px: float = 1.0) -> float:
    """Bevel width: ``max(2, size * (0.04 + 0.12k))`` (2 in mockup px)."""
    return max(2.0 * px, size * (.04 + .12 * k))


def facet_tone(dot: float, k: float, light_theme: bool, shade: str) -> Tuple[str, float]:
    """(colour, alpha) of a facet whose outward normal makes ``dot`` with the aim."""
    if dot > .05:
        return WHITE, (.80 if light_theme else .58) * k * dot
    if dot < -.05:
        return shade, (.30 if light_theme else .50) * k * -dot
    return WHITE, .10 * k


def glint_alpha(k: float) -> float:
    return min(1.0, (k - .5) * 1.8) if k > .5 else 0.0


def glint_tints(h: float) -> Tuple[str, str]:
    return hsl_hex(h - 50, .9, .78), hsl_hex(h + 50, .9, .78)


# ------------------------------------------------------------------ the aim
def unit(x: float, y: float) -> Vec:
    n = math.hypot(x, y)
    return (x / n, y / n) if n else (0.0, -1.0)


def snapped_aim(dx: float, dy: float) -> Vec:
    """South Indian aim: centre -> best-house square, snapped to the axis for a side
    square and kept diagonal for a corner square (screen space, y down)."""
    if abs(dx) > 2 * abs(dy):
        dy = 0.0
    elif abs(dy) > 2 * abs(dx):
        dx = 0.0
    return unit(dx, dy)


def angle_aim(angle_deg: float) -> Vec:
    """Wheel aim: the screen direction of a polar angle (0 = right, CCW, y down)."""
    a = math.radians(angle_deg)
    return math.cos(a), -math.sin(a)
