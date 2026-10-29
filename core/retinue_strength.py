# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Retinue strength display: options, per-planet strength, colour maths (SPEC-RST-001).
Qt-free, RAW hex and floats; the paint points desaturate once (SPEC-SAT-001, INV-4); nothing
cached: every rebuild asks ``planet_strengths`` for the chart on screen (INV-3). Formulas
(plan §6): ``A = amount / 100``, ``f = A(1-q)``, ``g = A*max(0, q-.5)*2``."""
from __future__ import annotations

import colorsys
from dataclasses import dataclass
from typing import Callable, Dict, NamedTuple, Optional, Tuple

from core import bala_calculator, stained_glass as sg

# Source -> field of get_all_bala_data().
SOURCES: Tuple[str, ...] = ("duc", "digbala", "uccha", "chesta")
_FIELD = {"duc": "duc_bala", "digbala": "digbala", "uccha": "uccha", "chesta": "chesta"}
duc_method_from = bala_calculator.duc_method_from   # the DUC method of a get(key, default)

KEY_ON = "chart.retinue_strength_on"
KEY_SOURCE = "chart.retinue_strength_source"
KEY_AMOUNT = "chart.retinue_strength_amount"
KEY_SIGN_RIBBON = "chart.retinue_strength_sign_ribbon"
KEYS = (KEY_ON, KEY_SOURCE, KEY_AMOUNT, KEY_SIGN_RIBBON)

DEFAULT_AMOUNT = 60

# Lamplight pool colours (raw; the paint module desaturates once).
GLOW_SUN = "#FFE6A0"      # Hora Aditya half (Sun)
GLOW_MOON = "#E4EEFF"     # Hora Naga half (Moon)
GLOW_TRIM = "#FFF6DC"     # Trimsamsa cells
SHADOW_DARK = "#000000"
SHADOW_WOOD = "#2a1a08"
INK_DARK = "#1a1a1a"
INK_LIGHT = "#FFFFFF"
INK_WOOD_RIBBON = "#352c20"
CONTRAST_TARGET = 4.5


@dataclass(frozen=True)
class StrengthOptions:
    """The four display preferences, as data (never a global, never cached)."""
    enabled: bool = False
    source: str = "duc"
    amount: int = DEFAULT_AMOUNT
    sign_ribbon: bool = True

    @property
    def A(self) -> float:
        return max(0, min(100, int(self.amount))) / 100.0

    @classmethod
    def from_settings(cls, get: Callable) -> "StrengthOptions":
        """Build from a ``get(key, default)`` reader; invalid values fall back."""
        enabled = bool(get(KEY_ON, False))
        if not enabled:
            return cls.OFF
        source = get(KEY_SOURCE, "duc")
        if source not in SOURCES:
            source = "duc"
        try:
            amount = int(get(KEY_AMOUNT, DEFAULT_AMOUNT))
        except (TypeError, ValueError):
            amount = DEFAULT_AMOUNT
        amount = max(0, min(100, amount))
        return cls(True, source, amount, bool(get(KEY_SIGN_RIBBON, True)))


StrengthOptions.OFF = StrengthOptions()


def strength_values(chart, source: str, duc_method=None) -> Dict[str, float]:
    """``{planet: bala value}`` of the source, 7 planets, one D1 bala call, never cached;
    ``duc_method`` the DUC Bala method (SPEC-STR-001 §7.5, None: "equal")."""
    field = _FIELD.get(source, "duc_bala")
    rows = bala_calculator.get_all_bala_data(chart, duc_method=duc_method)
    return {planet: row[field] for planet, row in rows.items()}


def to_q(value: float) -> float:
    """``clamp(value / 60, 0, 1)``: absolute, never normalised to the chart."""
    return max(0.0, min(1.0, value / 60.0))


def planet_strengths(chart, source: str, duc_method=None) -> Dict[str, float]:
    """``{planet: q}``, ``q = clamp(value/60, 0, 1)``, absolute (never normalised); D1 bala
    of the chart passed (the view's own chart), one bala call (0.1 ms after W0)."""
    values = strength_values(chart, source, duc_method)
    return {planet: to_q(value) for planet, value in values.items()}


# ---------------------------------------------------------------- colour maths
RGB = Tuple[float, float, float]


def hex_rgb(value: str) -> RGB:
    v = value.lstrip("#")
    if len(v) == 3:
        v = "".join(ch * 2 for ch in v)
    v = v[-6:]
    return (int(v[0:2], 16) / 255.0, int(v[2:4], 16) / 255.0, int(v[4:6], 16) / 255.0)


def rgb_hex(rgb: RGB) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02X}" for c in rgb)


def luminance(rgb: RGB) -> float:
    def ch(c):
        return c / 12.92 if c <= 0.04045 else ((c + .055) / 1.055) ** 2.4
    return .2126 * ch(rgb[0]) + .7152 * ch(rgb[1]) + .0722 * ch(rgb[2])


def contrast(a: RGB, b: RGB) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + .05) / (lo + .05)


def over(bg: RGB, fg: RGB, alpha: float) -> RGB:
    """``fg`` painted at ``alpha`` over an opaque ``bg``."""
    return tuple(b * (1 - alpha) + f * alpha for b, f in zip(bg, fg))


def lightness(value: str) -> float:
    return colorsys.rgb_to_hls(*hex_rgb(value))[1]


def is_light_ground(card: str) -> bool:
    return lightness(card) > .5


def _fg(q: float, A: float) -> Tuple[float, float]:
    return A * (1 - q), A * max(0.0, q - .5) * 2


def lamp_fill(base: str, q: float, A: float, card: str) -> str:
    """Lamplight fill (RAW hex in and out). Weak lord: saturation drops, lightness sinks toward
    the card. Strong lord: richer pigment; on a light card also deeper. ``A == 0``: ``base``."""
    f, g = _fg(q, A)
    if f == 0 and g == 0:
        return base
    h, l, s = colorsys.rgb_to_hls(*hex_rgb(base))
    lc = lightness(card)
    s = s * (1 - .9 * f) + (1 - s) * .45 * g
    l = l + (lc - l) * .7 * f
    if lc > .5:
        l = l - (l - .42) * .6 * g
        s = s + (1 - s) * .35 * g
    return rgb_hex(colorsys.hls_to_rgb(h, max(0.0, min(1.0, l)), max(0.0, min(1.0, s))))


def bright_fill(base: str, q: float, A: float, card: str = "") -> str:
    """Wheel fill (td-9scg9, D-30): the stained glass colour of the lamplight pulls."""
    return bright_pulls(base, A * max(0.0, 1 - 2 * q), _fg(q, A)[1])


def bright_pulls(base: str, f: float, g: float) -> str:
    return sg.from_pulls(base, f, g)          # stained glass (SPEC-RST-001 D-30, td-9scg9)


def wood_opacity(o: float, q: float, A: float) -> float:
    """Wood finishes keep the stain colour; only its opacity moves."""
    if A == 0:
        return o
    return max(.04, min(.92, o * (1 + A * (2 * q - 1) * 1.1)))


def glow_colour(ring: str, lord: str) -> str:
    if ring == "hora" or lord in ("Sun", "Moon"):
        return GLOW_SUN if lord == "Sun" else GLOW_MOON
    return GLOW_TRIM


def glow_alpha(q: float, A: float, ring: str, cap: float = .75) -> float:
    """Uncapped-by-contrast centre alpha of the light pool (0 when q <= .5)."""
    if q <= .5:
        return 0.0
    _, g = _fg(q, A)
    return min(cap, (.25 + .8 * g) * A * (1.6 if ring == "hora" else 1.0))


def shadow_alpha(q: float, A: float, wood: bool = False) -> float:
    f, _ = _fg(q, A)
    return min(.55, .6 * f * (.6 if wood else 1.0))


def shadow_colour(card: str, wood: bool) -> str:
    return SHADOW_WOOD if wood else card if is_light_ground(card) else SHADOW_DARK


class LampParams(NamedTuple):
    fill: str               # raw hex (standard) or the unchanged stain (wood)
    opacity: Optional[float]  # wood stain opacity, None for standard
    glow: str               # raw hex
    glow_alpha: float       # before the contrast cap
    shadow: str             # raw hex
    shadow_alpha: float


def lamp_params(base: str, q: float, A: float, card: str, *, ring: str, lord: str,
                wood_o: Optional[float] = None, bright: bool = False) -> LampParams:
    wood = wood_o is not None   # ``bright`` (wheel): bright_fill, no rim shadow (td-9scg9)
    fill = base if wood else (bright_fill if bright else lamp_fill)(base, q, A, card)
    opacity = wood_opacity(wood_o, q, A) if wood else None
    glow = sg.wheel_glow(base, fill, glow_colour(ring, lord), bright, wood)
    return LampParams(fill, opacity, glow, glow_alpha(q, A, ring),
                      shadow_colour(card, wood), 0.0 if bright else shadow_alpha(q, A, wood))


class RibbonParams(NamedTuple):
    width: float          # reference px (SI: x box scale)
    fraction: float       # filled length = q, exactly
    track_alpha: float
    fill_alpha: float
    thread_ratio: float   # hue thread width / ribbon width
    thread_alpha: float


def ribbon_params(q: float, A: float, wheel: bool = False) -> RibbonParams:
    return RibbonParams((3 + 13 * A) if wheel else (3 + 8 * A), max(0.0, min(1.0, q)),
                        .14, .45 + .45 * A, .28, .35 + .65 * A)


# ------------------------------------------------------------- readability
def text_threshold(today_text: RGB, today_bg: RGB, opacity: float) -> float:
    """``min(4.5, today's contrast)``: never ask more than today delivers (D-6)."""
    return min(CONTRAST_TARGET, contrast(over(today_bg, today_text, opacity), today_bg))


def readable_text(today_text: str, bg: RGB, opacity: float, threshold: float) -> str:
    """Today's text colour if it still meets ``threshold``, else the better ink."""
    t = hex_rgb(today_text)
    if contrast(over(bg, t, opacity), bg) >= threshold - 1e-9:
        return today_text
    return max((INK_DARK, INK_LIGHT), key=lambda ink: contrast(over(bg, hex_rgb(ink), opacity), bg))


def cap_glow(alpha: float, text: str, bg: RGB, glow: RGB, opacity: float,
             threshold: float, card: Optional[RGB] = None) -> float:
    """Largest glow centre alpha <= ``alpha`` keeping the text readable. Without ``card``: the
    glow is its own layer over the composited ground ``bg`` and inherits ``opacity`` (the SI
    sector's .86) like the text. With ``card``: the glow is mixed into the opaque cell fill
    ``bg`` (one gradient brush) and that mix is composited on ``card`` at ``opacity``."""
    if alpha <= 0:
        return 0.0
    t = hex_rgb(text)

    def ok(a):
        under = over(bg, glow, opacity * a) if card is None else over(card, over(bg, glow, a), opacity)
        return contrast(over(under, t, opacity), under) >= threshold - 1e-9

    if ok(alpha):
        return alpha
    lo, hi = 0.0, alpha
    if not ok(lo):
        return 0.0
    for _ in range(12):                   # alpha to 1/4096 of the cap
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if ok(mid) else (lo, mid)
    return lo
