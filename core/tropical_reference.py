# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""True tropical reference values for output fields labelled "tropical".

A sidereal chart's own ``ecliptic_longitude()`` values are sidereal, so a CLI
that prints a "tropical" reference next to the chart's frame must read it off
the same moment built in tropical_classic (review round 15). Kept out of
``core.chart_factory`` (an SI-renderer-reachable module under the
architecture ratchet).
"""
from __future__ import annotations


def tropical_twin_chart(chart):
    """A chart whose ``ecliptic_longitude()`` values are TRUE tropical for the
    same moment, place and house system as ``chart``: ``chart`` itself when
    its longitudes are already tropical (aditya and tropical_classic charts
    read the tropical ephemeris), else the same moment rebuilt in
    tropical_classic."""
    from libaditya import swe
    from core.chart_factory import build_chart_from_params
    ctx = chart.context
    if not (int(getattr(ctx, "sysflg", 0) or 0) & swe.FLG_SIDEREAL):
        return chart
    utcoffset = getattr(ctx.timeJD, "utcoffset", 0.0)
    return build_chart_from_params(
        jd=ctx.timeJD.jd, lat=ctx.location.lat, lon=ctx.location.long,
        mode="tropical_classic", name=getattr(ctx, "name", "") or "",
        utcoffset=utcoffset if utcoffset is not None else 0.0,
        ayanamsa=ctx.ayanamsa, hsys=ctx.hsys)
