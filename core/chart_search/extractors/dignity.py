# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Dignity (domain Dignity, build step 1). D1 only.

Reference: ``planet.dignity()`` on the chart built in the system's frame, as
the panels read it. Outer planets have none (libaditya returns "").
"""

from __future__ import annotations

from core.chart_search.extractors.base import Charts, Extractor, Row
from core.chart_search.extractors.subjects import GRAHAS
from core.chart_search.sources import Moment
from core.chart_search.system import Field, Projection, drop_ayanamsa_unless_sidereal
from core.chart_search.taxonomy import Codec, PropertySpec, ValueKind

#: libaditya/objects/planets.py ``attributes["dignity"]`` codes.
DIGNITIES: tuple[str, ...] = ("EX", "MT", "OH", "GF", "F", "N", "E", "GE", "DB")

PROPERTIES = (
    PropertySpec("dignity", GRAHAS, ValueKind.CODE, DIGNITIES, Codec.DIGNITY),
)


def extract(moment: Moment, projection: Projection, charts: Charts) -> tuple[Row, ...]:
    chart = charts.chart(
        mode=str(projection.value(Field.MODE.value)),
        ayanamsa_id=int(projection.value_or_neutral(Field.AYANAMSA_ID)),
        house_system=str(projection.value_or_neutral(Field.HOUSE_SYSTEM)),
    )
    planets = chart.rashi().planets()
    return tuple(Row(name, "dignity", str(planets[name].dignity())) for name in GRAHAS)


EXTRACTOR = Extractor(
    id="dignity",
    label="Dignity",
    version=1,
    domain="Dignity",
    # house_system is not read: dignity is sign-based. The invariance test decides.
    reads=frozenset({Field.MODE, Field.AYANAMSA_ID}),
    normalisers=(drop_ayanamsa_unless_sidereal,),
    properties=PROPERTIES,
    extract=extract,
)
