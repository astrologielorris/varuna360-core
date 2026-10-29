# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Bala planet table and the tropical fast path (SPEC-STR-001 §6.3, v1.3).

Swiss Ephemeris ids of the 7 classical planets used by core.bala_calculator,
and their tropical longitude + speed read straight from one default-flag
swe.calc_ut tuple each, so the bala of a sidereal chart needs no whole
tropical Chart rebuild (td-9x5dr W0); tropical_rebuild is the fallback.
"""

try:
    from libaditya import swe
except ImportError:
    swe = None

# Swiss Ephemeris planet IDs
PLANET_IDS = {
    'Sun': 0,       # swe.SUN
    'Moon': 1,      # swe.MOON
    'Mars': 4,      # swe.MARS
    'Mercury': 2,   # swe.MERCURY
    'Jupiter': 5,   # swe.JUPITER
    'Venus': 3,     # swe.VENUS
    'Saturn': 6,    # swe.SATURN
}


def tropical_positions(jd):
    """Tropical (longitude, speed) per planet from one default-flag calc_ut each.

    Default flags (SWIEPH | SPEED, no SIDEREAL) give the same longitude as the
    tropical chart's flag 0 and the speed get_planet_speed() already reads
    (SPEC-STR-001 §6.3). None without Swiss Ephemeris or when any call fails
    (the caller then falls back to tropical_rebuild).
    """
    if swe is None:
        return None
    try:
        out = {}
        for name, planet_id in PLANET_IDS.items():
            xx = swe.calc_ut(jd, planet_id)[0]
            out[name] = (xx[0], xx[3])
        return out
    except Exception:
        return None


def tropical_rebuild(chart):
    """Whole tropical Chart rebuild (fallback when tropical_positions fails)."""
    from core.chart_factory import rebuild_chart
    from libaditya import constants as _const
    chart = rebuild_chart(chart, mode="tropical_classic")
    if chart.context.sysflg == _const.SID:
        raise ValueError("rebuild_chart failed to produce tropical chart")
    return chart
