# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The extractor contract (design.md §4.4).

An ``Extractor`` is data plus one function, like ``catalog.Capability``: no
class hierarchy, no dynamic dispatch beyond the ``extract`` callable.

**Splitting rule.** One extractor per distinct projection or cost. Rows are
keyed by ``(moment, extractor, projection)``, so properties that read
different fields belong to different extractors or a cheap field change would
recompute (and re-store) the expensive ones. Hence Positions and Nakshatras
are two extractors in one UI domain.

**Contract checked by compute, not trusted.** Every row's property must be
declared, its subject listed, its value in the domain and its qualifiers
filled to the declared count. A violation is recorded as a failed computation
with an error starting ``contract:``, never raised (principle 6); the
extractor tests assert there are none.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from core.chart_factory import build_chart_from_params
from core.chart_search.sources import Moment
from core.chart_search.system import (
    Field,
    Normaliser,
    Projection,
    SearchSystem,
    engine_ayanamsa_id,
    project,
)
from core.chart_search.taxonomy import PropertySpec, Value
from core.house_systems import get_house_system_code

#: A libaditya ``Chart``. ``Any`` because libaditya ships no type information.
LibChart = Any


@dataclass(frozen=True)
class Row:
    subject: str
    property: str
    value: Value
    q1: str | None = None
    q2: str | None = None


class Charts(Protocol):
    """Charts for one moment, memoised for one compute batch, so Positions,
    Dignity and Avasthas in one system build the chart once. Built through
    ``core.chart_factory.build_chart_from_params``, as ``ChartManager.load_chart``."""

    def chart(self, *, mode: str, ayanamsa_id: int, house_system: str) -> LibChart: ...


class MomentCharts:
    """``Charts`` for one moment. Compute makes one per moment of a batch and
    hands it to every extractor; the invariance and screen-agreement tests
    use it too, so they build charts exactly as compute does."""

    def __init__(self, moment: Moment) -> None:
        self._moment = moment
        self._built: dict[tuple[str, int, str], LibChart] = {}

    def chart(self, *, mode: str, ayanamsa_id: int, house_system: str) -> LibChart:
        key = (mode, ayanamsa_id, house_system)
        if key not in self._built:
            m = self._moment
            self._built[key] = build_chart_from_params(
                jd=m.jd_ut,
                lat=m.lat,
                lon=m.lon,
                mode=mode,
                utcoffset=m.utc_offset_hours,
                ayanamsa=engine_ayanamsa_id(ayanamsa_id),
                hsys=get_house_system_code(house_system),
            )
        return self._built[key]


@dataclass(frozen=True)
class Extractor:
    id: str
    version: int  # hand-bumped on any change to what it writes (D10)
    domain: str  # UI domain: "Positions", "Dignity", "Avasthas", ...
    reads: frozenset[Field]  # what the code reads, not what the astrology says (D6)
    normalisers: tuple[Normaliser, ...]
    properties: tuple[PropertySpec, ...]
    #: Gets the projection, never the system: rows are a function of the
    #: projection by construction, so two systems sharing it cannot compute
    #: different rows. A field the projection dropped is passed to the engine
    #: as its ``system.NEUTRAL`` value; the invariance test proves it inert.
    #: Raises on a calculation failure; compute records it.
    extract: Callable[[Moment, Projection, Charts], tuple[Row, ...]]
    #: What the coverage lines call it (the CLI, ``search_charts`` and the
    #: panel strip): two extractors may share a domain, never a label.
    label: str = ""

    def projection(self, system: SearchSystem) -> Projection:
        return project(system, self.id, self.reads, self.normalisers)
