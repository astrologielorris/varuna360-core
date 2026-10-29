# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Whole-sign house (domain Positions; houses.md D22). D1 only.

Reference: ``chart_snapshot``'s ``planet_houses[name]["whole_sign"]``, the
planet's sign counted from the Ascendant's sign (Ascendant's sign = 1).

Its own extractor because it does not read the house system: the Ascendant is
cusp 1 in every system, so the sign of ``cusps[1]`` is the Ascendant's sign
whatever the system (Whole Sign puts cusp 1 at 0 degrees of that sign, not at
the Ascendant's degree, but the sign is the same). The chart is built with the
neutral house system; the invariance test proves the system inert. Inside
``positions`` every house-system switch would recompute it. (Before libaditya
0.4.3, Whole Sign cusps at the Vedanga ids 99/100 were off the sign
boundaries and v1 read the house system there; varuna/57.)
"""

from __future__ import annotations

from core.chart_search.extractors.base import Charts, Extractor, Row
from core.chart_search.extractors.subjects import HOUSED
from core.chart_search.sources import Moment
from core.chart_search.system import Field, Projection, drop_ayanamsa_unless_sidereal
from core.chart_search.taxonomy import Codec, PropertySpec, ValueKind

PROPERTIES = (
    PropertySpec(
        "whole_sign_house", HOUSED, ValueKind.ORDINAL, tuple(range(1, 13)), Codec.NUMBER
    ),
)


def extract(moment: Moment, projection: Projection, charts: Charts) -> tuple[Row, ...]:
    chart = charts.chart(
        mode=str(projection.value(Field.MODE.value)),
        ayanamsa_id=int(projection.value_or_neutral(Field.AYANAMSA_ID)),
        house_system=str(projection.value_or_neutral(Field.HOUSE_SYSTEM)),
    )
    rashi = chart.rashi()
    asc = int(rashi.cusps()[1].sign())
    planets = rashi.planets()
    return tuple(
        Row(name, "whole_sign_house", (int(planets[name].sign()) - asc) % 12 + 1)
        for name in HOUSED
    )


EXTRACTOR = Extractor(
    id="whole_sign",
    label="Whole-sign houses",
    version=2,
    domain="Positions",
    # house_system is not read (module docstring). The invariance test decides.
    reads=frozenset({Field.MODE, Field.AYANAMSA_ID}),
    normalisers=(drop_ayanamsa_unless_sidereal,),
    properties=PROPERTIES,
    extract=extract,
)
