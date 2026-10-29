# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""Raw Jewel Lamp ink and light, fitted for label contrast (SPEC-RST-001 D-33).
Judge the radial core and ray crossing after an explicit display transform, keeping
as much light as the target allows. Paint still receives raw hex (SPEC-SAT-001).
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional, Tuple

from core.jewel_ink_display import evaluated, raw_light
from core.retinue_strength import contrast, hex_rgb, luminance, over, rgb_hex

TARGET = 3.0              # WCAG contrast the label keeps at the star centre (large text)
PREFER_DARK = .36         # fill luminance above which the dark ink is the usual one (as before D-33)
INK_DARK, INK_LIGHT = "#1B1A1F", "#F7F7F9"
SUB_DARK, SUB_LIGHT = .70, .74
WHITE = "#FFFFFF"
RAY_SHARE = .85           # the rays' mid stop alpha, x ray_alpha (light_layers)
STEPS = 14


def glow(star, k: float):
    """``star`` with its radial stops' alphas times ``k`` (the rays untouched)."""
    if star is None or k >= 1.0:
        return star
    return star._replace(stops=tuple((o, c, a * k) for o, c, a in star.stops))


def rays(star, k: float):
    """``star`` with its rays' alpha times ``k`` (the radial untouched)."""
    return star if star is None or k >= 1.0 else star._replace(ray_alpha=star.ray_alpha * k)


def centre(ground: str, star, burn: float = 0.0) -> str:
    """The colour painted at the cell centre: ground, radial centre stop, both rays, burn."""
    rgb = hex_rgb(ground)
    if star is not None:
        _o, core, alpha = star.stops[0]
        rgb = over(rgb, hex_rgb(core), alpha)
        for _ in range(2):                                   # the two crossed rays
            rgb = over(rgb, hex_rgb(star.ray_mid), RAY_SHARE * star.ray_alpha)
    if burn > .01:
        rgb = over(rgb, hex_rgb(WHITE), .95 * burn)
    return rgb_hex(rgb)


def points(ground: str, star, burn: float = 0.0):
    """The colours under the label: the radial core beside the rays, and the ray crossing."""
    return [centre(ground, star and star._replace(ray_alpha=0.0), burn), centre(ground, star, burn)]


def _c(ink: str, ground: str, star=None, burn: float = 0.0) -> float:
    """The ink's worst contrast on ``ground`` under ``star`` (``star`` None: the bare fill)."""
    return min(contrast(hex_rgb(ink), hex_rgb(p)) for p in points(ground, star, burn))


def _keep(ink: str, ground: str, star, burn: float, need: float, scale) -> float:
    """The largest ``k`` (0..1) for which ``ink`` keeps ``need`` under ``scale(star, k)``."""
    if _c(ink, ground, scale(star, 1.0), burn) >= need:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(STEPS):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if _c(ink, ground, scale(star, mid), burn) >= need else (lo, mid)
    return lo


def _fit(ink: str, ground: str, star, burn: float, need: float):
    """(light kept, star) for ``ink``: the glow dimmed for the label first, then the rays."""
    if star is None or _c(ink, ground) < need:
        return (-1.0 if star is not None else 0.0), None
    kg = _keep(ink, ground, star, burn, need, lambda st, k: glow(rays(st, 0.0), k))
    star = glow(star, kg)
    kr = _keep(ink, ground, star, burn, need, rays)
    return kg + kr, (None if kg <= .02 else rays(star, kr))


@lru_cache(maxsize=4096)            # pure: the same fill and star give the same ink
def readable(ground: str, star, burn: float = 0.0, *, transform=None,
             displayed_ground: Optional[str] = None) -> Tuple[Optional[object], str, float, str]:
    """(star, ink, sub alpha, centre colour) for a label centred on ``ground`` under ``star``:
    the ink that keeps the most light; on a tie the usual one for the fill's lightness."""
    raw_star = star
    displayed, star, inks = evaluated(ground, star, transform, displayed_ground, (INK_DARK, INK_LIGHT))
    if burn > .45:
        return raw_star, INK_DARK, SUB_DARK, centre(ground, raw_star, burn)
    need = min(TARGET, max(_c(i, displayed) for _raw, i in inks)) - 1e-9
    usual = INK_DARK if luminance(hex_rgb(displayed)) > PREFER_DARK else INK_LIGHT
    fits = [(_fit(i, displayed, star, burn, need), raw == usual, raw) for raw, i in inks]
    (_kept, fitted), _u, ink = max(fits, key=lambda r: (r[0][0], r[1]))
    star = raw_light(raw_star, fitted)
    return star, ink, SUB_DARK if ink == INK_DARK else SUB_LIGHT, centre(ground, star, burn)
