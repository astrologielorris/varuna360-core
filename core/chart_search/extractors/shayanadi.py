# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Shayanadi avastha (domain Avasthas, build step 2; Q2: libaditya is the reference).

Reference: the planets' ``shayanadi_avastha()`` on the chart built in the
system's frame (``libaditya/calc/avasthas.py``); no screen shows it.

A separate extractor from ``avasthas`` because it reads different fields: its
nakshatra term is ``planet.nakshatra()``, which libaditya makes sidereal with
the chart's ayanamsa whatever the mode, so the ayanamsa is never dropped; and
it reads no cusps. Subjects are ``KARAKAS``, as for the other avasthas.
"""

from __future__ import annotations

from core.chart_search.extractors.base import Charts, Extractor, Row
from core.chart_search.extractors.subjects import KARAKAS
from core.chart_search.sources import Moment
from core.chart_search.system import Field, Projection
from core.chart_search.taxonomy import Codec, PropertySpec, ValueKind
from libaditya.calc.avasthas import SHAYANADI_STATES

PROPERTIES = (
    PropertySpec(
        "shayanadi", KARAKAS, ValueKind.CODE, tuple(SHAYANADI_STATES), Codec.ENGINE
    ),
)


def extract(moment: Moment, projection: Projection, charts: Charts) -> tuple[Row, ...]:
    chart = charts.chart(
        mode=str(projection.value(Field.MODE.value)),
        ayanamsa_id=int(projection.value(Field.AYANAMSA_ID.value)),
        house_system=str(projection.value_or_neutral(Field.HOUSE_SYSTEM)),
    )
    planets = chart.rashi().planets()
    return tuple(
        Row(name, "shayanadi", str(planets[name].shayanadi_avastha()))
        for name in KARAKAS
    )


EXTRACTOR = Extractor(
    id="shayanadi",
    label="Shayanadi",
    version=1,
    domain="Avasthas",
    # ayanamsa_id in every mode: the nakshatra term is sidereal.
    reads=frozenset({Field.MODE, Field.AYANAMSA_ID}),
    normalisers=(),
    properties=PROPERTIES,
    extract=extract,
)
