# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Retinue beings (domain Retinue, build step 2).

Reference: ``AI_tools/AI_main_function/retinue.get_chart_retinue`` on the
chart built in the system's frame, as the sidebar Hora and Trimsamsa panels
read it (``core.capabilities.retinue.sidebar_retinue``; its mode flags and
ayanamsa offset change labels only). It calls ``get_retinue`` on each
``RETINUE_PLANETS`` body's sign and degree. Values are the being names.

**Domains.** The hora being is the sign's Aditya (Sun hora) or its Naga (Moon
hora); the trimsamsa being is its Rishi, Gandharva, Apsara, Yaksha or Rakshasa.
``ALL_BEING_NAMES`` (the dropdown) holds the Nagas and the trimsamsa beings but
not the Adityas.
"""

from __future__ import annotations

from AI_tools.AI_main_function.retinue import (
    ADITYA_RETINUE,
    ADITYA_SIGN_ORDER,
    BEING_TYPE_LABELS,
    RETINUE_PLANETS,
    get_chart_retinue,
)
from core.chart_search.errors import InvariantError
from core.chart_search.extractors.base import Charts, Extractor, Row
from core.chart_search.sources import Moment
from core.chart_search.system import Field, Projection, drop_ayanamsa_unless_sidereal
from core.chart_search.taxonomy import Codec, PropertySpec, ValueKind

SUBJECTS: tuple[str, ...] = tuple(RETINUE_PLANETS)
#: What ``get_trimsamsa_being`` can return, sorted (Vishvavasu serves two signs).
TRIMSAMSA_BEINGS: tuple[str, ...] = tuple(
    sorted(
        {
            str(data[key])
            for data in ADITYA_RETINUE.values()
            for key in BEING_TYPE_LABELS
        }
    )
)
#: What ``get_hora`` can return: the twelve Adityas, then the twelve Nagas.
HORA_BEINGS: tuple[str, ...] = (
    *(str(name) for name in ADITYA_SIGN_ORDER),
    *(str(ADITYA_RETINUE[name]["naga"]) for name in ADITYA_SIGN_ORDER),
)

PROPERTIES = (
    PropertySpec(
        "trimsamsa_being", SUBJECTS, ValueKind.CODE, TRIMSAMSA_BEINGS, Codec.ENGINE
    ),
    PropertySpec("hora_being", SUBJECTS, ValueKind.CODE, HORA_BEINGS, Codec.ENGINE),
)


def extract(moment: Moment, projection: Projection, charts: Charts) -> tuple[Row, ...]:
    chart = charts.chart(
        mode=str(projection.value(Field.MODE.value)),
        ayanamsa_id=int(projection.value_or_neutral(Field.AYANAMSA_ID)),
        house_system=str(projection.value_or_neutral(Field.HOUSE_SYSTEM)),
    )
    found = {r["planet"]: r for r in get_chart_retinue(chart)["planets"]}
    rows: list[Row] = []
    for name in SUBJECTS:
        # get_chart_retinue skips a body it cannot place; a row must never come of it.
        retinue = found.get(name)
        if retinue is None:
            raise InvariantError(f"invariant: get_chart_retinue places {name}")
        rows.append(
            Row(name, "trimsamsa_being", str(retinue["trimsamsa"]["being_name"]))
        )
        rows.append(Row(name, "hora_being", str(retinue["hora"]["being_name"])))
    return tuple(rows)


EXTRACTOR = Extractor(
    id="retinue",
    label="Retinue",
    version=1,
    domain="Retinue",
    reads=frozenset({Field.MODE, Field.AYANAMSA_ID}),
    normalisers=(drop_ayanamsa_unless_sidereal,),
    properties=PROPERTIES,
    extract=extract,
)
