# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Positions: sign per varga, cusp house and cusp conjunction, retrograde
(domain Positions, build step 1; houses.md).

Reference: the main chart (``core/chart_factory``, ``core/chart_helpers``) and
the varga column (``chart.varga(core.varga_codes.to_libaditya_varga_code(n))``,
classical style, as ``panels/sign_selector_column`` and ``get_chart`` read it;
the Dignities panel's style toggle is a view of that panel, not a setting).
Each value delegates to what ``core.capabilities.chart.chart_snapshot`` reports:

- sign: ``sign()`` on ``varga_source(chart, n)``; the Ascendant is ``cusps[1]``
  as the chart views draw it. Under Whole Sign houses that cusp is 0 degrees of
  the rising sign, so in a varga it is that point's varga sign, not the true
  Ascendant's: the screens show it so, and so does Find Chart.
- cusp_house: the cusp house (``planet_cusp_house``), D1: house *n* spans
  cusp *n* to cusp *n+1* under the house system. Under Whole Sign it equals
  ``whole_sign_house`` (its own extractor, which does not read the system).
- cusp_conjunction: Ernst Wilhelm's cusps as points, D1: one row per cusp
  (value 1-12, cusp 1 the Ascendant) in the planet's sign, so 0 to many rows.
  Stored per planet only (houses.md D26).
- Planets only, for both house properties: the Ascendant is cusp 1, a value
  of them, not a subject (D25).
- retrograde: ``Planet.retrograde()`` (speed below 0), D1; the Ascendant is 0.
- cusps 2-12: sign at D1 only, ``cusps[n].sign()`` as the snapshot's
  ``houses_cusp`` reports it; no house or retrograde rows. Their varga signs
  are deferred (filter-redesign.md §5); the Ascendant keeps every varga.
"""

from __future__ import annotations

from core.capabilities.chart import planet_cusp_house, varga_source
from core.chart_search.extractors.base import Charts, Extractor, LibChart, Row
from core.chart_search.extractors.subjects import BODIES, HOUSE_CUSPS, HOUSED, LAGNA
from core.chart_search.sources import Moment
from core.chart_search.system import Field, Projection, drop_ayanamsa_unless_sidereal
from core.chart_search.taxonomy import Codec, PropertySpec, Qualifier, ValueKind
from core.varga_codes import VARGA_NAMES, varga_display_label

#: Varga qualifier values: "D" + core.varga_codes.varga_display_label(n) for
#: every n in VARGA_NAMES, in its order ("D1" ... "D10R", "D24R", "D2p" ...
#: "D60"): derived, so a varga added to the app is searchable. The rashi is
#: "D1", never NULL.
VARGAS: tuple[str, ...] = tuple("D" + varga_display_label(n) for n in VARGA_NAMES)
#: The rashi's qualifier, the only varga cusps 2-12 are stored at.
RASHI = VARGAS[0]

PROPERTIES = (
    PropertySpec(
        "sign",
        (*BODIES, *HOUSE_CUSPS),
        ValueKind.ORDINAL,
        tuple(range(1, 13)),
        Codec.SIGN,
        qualifiers=(Qualifier("varga", VARGAS, default=RASHI),),
    ),
    PropertySpec(
        "cusp_house", HOUSED, ValueKind.ORDINAL, tuple(range(1, 13)), Codec.NUMBER
    ),
    PropertySpec(
        "cusp_conjunction",
        HOUSED,
        ValueKind.ORDINAL,
        tuple(range(1, 13)),
        Codec.NUMBER,
        multi=True,
    ),
    PropertySpec("retrograde", BODIES, ValueKind.ORDINAL, (0, 1), Codec.BOOLEAN),
)


#: (GUI varga number, qualifier value), in ``VARGAS`` order.
_VARGA_QUALIFIERS: tuple[tuple[int, str], ...] = tuple(
    (number, "D" + varga_display_label(number)) for number in VARGA_NAMES
)


def _body(source: LibChart, name: str) -> LibChart:
    """The object the chart views read for ``name`` in a rashi or varga."""
    if name == LAGNA:
        return source.cusps()[1]
    return source.planets()[name]


def extract(moment: Moment, projection: Projection, charts: Charts) -> tuple[Row, ...]:
    chart = charts.chart(
        mode=str(projection.value(Field.MODE.value)),
        ayanamsa_id=int(projection.value_or_neutral(Field.AYANAMSA_ID)),
        house_system=str(projection.value(Field.HOUSE_SYSTEM.value)),
    )
    rows: list[Row] = []
    for number, qualifier in _VARGA_QUALIFIERS:
        source = varga_source(chart, number)
        rows.extend(
            Row(name, "sign", int(_body(source, name).sign()), qualifier)
            for name in BODIES
        )
    rashi = chart.rashi()
    cusps = rashi.cusps()
    rows.extend(
        Row(name, "sign", int(cusps[number].sign()), RASHI)
        for number, name in enumerate(HOUSE_CUSPS, start=2)
    )
    cusp_signs = {number: int(cusps[number].sign()) for number in range(1, 13)}
    rows.append(Row(LAGNA, "retrograde", 0))
    for name in HOUSED:
        body = _body(rashi, name)
        house = planet_cusp_house(float(body.ecliptic_longitude()), cusps)
        rows.append(Row(name, "cusp_house", house))
        sign = int(body.sign())
        rows.extend(
            Row(name, "cusp_conjunction", number)
            for number, cusp_sign in cusp_signs.items()
            if cusp_sign == sign
        )
        rows.append(Row(name, "retrograde", int(body.retrograde())))
    return tuple(rows)


EXTRACTOR = Extractor(
    id="positions",
    label="Positions",
    version=3,
    domain="Positions",
    reads=frozenset({Field.MODE, Field.AYANAMSA_ID, Field.HOUSE_SYSTEM}),
    normalisers=(drop_ayanamsa_unless_sidereal,),
    properties=PROPERTIES,
    extract=extract,
)
