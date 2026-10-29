# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Avasthas (domain Avasthas, build step 2; Q2: libaditya is the reference).

Reference: ``chart.rashi().lajjitaadi_avasthas()`` and the planets'
``baladi_avastha()``, ``jagradadi_avastha()`` and ``deeptadi_avastha()`` on
the chart built in the system's frame (``libaditya/calc/avasthas.py``), as Planetary Condition reads
it. Not the ``get_avastha`` capability (Lorris's Drishti-Yuti matrix).
Shayanadi reads the ayanamsa in every mode, so it is its own extractor
(``shayanadi``, same domain).

**Lajjitaadi rows.** One row per cause: ``(planet, "lajjitaadi", state, by, via)``.
``state`` is the engine's key (``"shamed"``, not the label "Lajjita"); ``via``
is the factor's ``source``; ``by`` is the factor's ``planet``, or ``""`` for
causes without one (``dignity``, ``sign``, ``condition``); only karakas are
ever a factor's planet (Rahu and Ketu enter as the shamed ``condition``). A planet with no
state has no row. "Any cause" leaves q1/q2 unconstrained. Causes that repeat
(conjunct Jupiter, which is also a friend; conjunct Saturn, also an enemy) and
the several ``condition`` details of shamed collapse to one row.

**Subjects.** libaditya computes every avastha for ``KARAKAS`` only (the
seven); Rahu and Ketu keep the planet's empty default and get no row.
"""

from __future__ import annotations

from core.chart_search.extractors.base import Charts, Extractor, Row
from core.chart_search.extractors.subjects import KARAKAS
from core.chart_search.sources import Moment
from core.chart_search.system import Field, Projection, drop_ayanamsa_unless_sidereal
from core.chart_search.taxonomy import Codec, PropertySpec, Qualifier, ValueKind
from libaditya.calc.avasthas import (
    BALADI_STATES,
    DEEPTADI_STATES,
    JAGRADADI_STATES,
)

#: Engine keys (libaditya/calc/avasthas.py ``_add`` calls; no constant there, so a
#: test pins them against that source), "healthy" = Svastha.
LAJJITAADI: tuple[str, ...] = (
    "shamed",
    "proud",
    "starved",
    "thirsty",
    "delighted",
    "agitated",
    "healthy",
)
#: The states' Sanskrit names (Ernst Wilhelm's), parse-only: ``lajjita`` and
#: ``shamed`` are the same filter value; display keeps the engine key. Svastha
#: also as Swastha, the spelling of the deeptadi state.
LAJJITAADI_SANSKRIT: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("shamed", ("Lajjita",)),
    ("proud", ("Garvita",)),
    ("starved", ("Kshudhita",)),
    ("thirsty", ("Trishita",)),
    ("delighted", ("Mudita",)),
    ("agitated", ("Kshobhita",)),
    ("healthy", ("Svastha", "Swastha")),
)
LAJJITAADI_VIA: tuple[str, ...] = (
    "conjunction",
    "aspect",
    "sign",
    "dignity",
    "condition",
)
PROPERTIES = (
    PropertySpec(
        "lajjitaadi",
        KARAKAS,
        ValueKind.CODE,
        LAJJITAADI,
        Codec.ENGINE,
        qualifiers=(Qualifier("by", ("", *KARAKAS)), Qualifier("via", LAJJITAADI_VIA)),
        multi=True,
        aliases=LAJJITAADI_SANSKRIT,
    ),
    PropertySpec("baladi", KARAKAS, ValueKind.CODE, tuple(BALADI_STATES), Codec.ENGINE),
    PropertySpec(
        "jagradadi", KARAKAS, ValueKind.CODE, tuple(JAGRADADI_STATES), Codec.ENGINE
    ),
    PropertySpec(
        "deeptadi", KARAKAS, ValueKind.CODE, tuple(DEEPTADI_STATES), Codec.ENGINE
    ),
)


def extract(moment: Moment, projection: Projection, charts: Charts) -> tuple[Row, ...]:
    chart = charts.chart(
        mode=str(projection.value(Field.MODE.value)),
        ayanamsa_id=int(projection.value_or_neutral(Field.AYANAMSA_ID)),
        house_system=str(projection.value(Field.HOUSE_SYSTEM.value)),
    )
    rashi = chart.rashi()
    lajjitaadi = rashi.lajjitaadi_avasthas()
    planets = rashi.planets()
    rows: list[Row] = []
    for name in KARAKAS:
        causes = (
            (state, str(factor.get("planet", "")), str(factor["source"]))
            for state, factors in lajjitaadi.get(name, {}).items()
            for factor in factors
        )
        rows.extend(
            Row(name, "lajjitaadi", state, by, via)
            for state, by, via in dict.fromkeys(causes)
        )
        planet = planets[name]
        rows.append(Row(name, "baladi", str(planet.baladi_avastha())))
        rows.append(Row(name, "jagradadi", str(planet.jagradadi_avastha())))
        rows.append(Row(name, "deeptadi", str(planet.deeptadi_avastha())))
    return tuple(rows)


EXTRACTOR = Extractor(
    id="avasthas",
    label="Avasthas",
    version=1,
    domain="Avasthas",
    # house_system: shamed reads cusps[5].
    reads=frozenset({Field.MODE, Field.AYANAMSA_ID, Field.HOUSE_SYSTEM}),
    normalisers=(drop_ayanamsa_unless_sidereal,),
    properties=PROPERTIES,
    extract=extract,
)
