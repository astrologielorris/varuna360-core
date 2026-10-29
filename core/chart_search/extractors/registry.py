# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Explicit list of extractors, in build order (design.md §4.4, Q6).

Static on purpose, like ``core/capabilities/registry.py``: PyInstaller and the
Lite manifest gate follow these imports; nothing is discovered at runtime. A
new domain is a new module plus one line here; no store or UI change.
"""

from __future__ import annotations

from core.chart_search.extractors import (
    avasthas,
    cards_of_truth,
    dignity,
    human_design,
    nakshatras,
    positions,
    retinue,
    shayanadi,
    whole_sign,
)
from core.chart_search.errors import BadFilterError, InvariantError
from core.chart_search.extractors.base import Extractor

EXTRACTORS: tuple[Extractor, ...] = (
    positions.EXTRACTOR,
    whole_sign.EXTRACTOR,
    nakshatras.EXTRACTOR,
    dignity.EXTRACTOR,
    avasthas.EXTRACTOR,
    shayanadi.EXTRACTOR,
    retinue.EXTRACTOR,
    human_design.EXTRACTOR,
    cards_of_truth.EXTRACTOR,
)


def get(extractor_id: str) -> Extractor:
    """``InvariantError`` for an unknown id: ids come from code or the store."""
    for extractor in EXTRACTORS:
        if extractor.id == extractor_id:
            return extractor
    raise InvariantError(f"invariant: extractor {extractor_id!r} is registered")


def for_domains(domains: tuple[str, ...]) -> tuple[Extractor, ...]:
    """``chart_index compute --domains``; raises ``BadFilterError`` listing the domains."""
    known = tuple(dict.fromkeys(extractor.domain for extractor in EXTRACTORS))
    unknown = [domain for domain in domains if domain not in known]
    if unknown:
        raise BadFilterError(f"unknown domain(s): {', '.join(unknown)}", known)
    return tuple(extractor for extractor in EXTRACTORS if extractor.domain in domains)


def for_ids(extractor_ids: tuple[str, ...]) -> tuple[Extractor, ...]:
    """``chart_index compute --extractors``, in build order; raises
    ``BadFilterError`` listing the ids. The coverage lines' commands name the
    one extractor that is missing, not its whole domain."""
    known = tuple(extractor.id for extractor in EXTRACTORS)
    unknown = [eid for eid in extractor_ids if eid not in known]
    if unknown:
        raise BadFilterError(f"unknown extractor(s): {', '.join(unknown)}", known)
    return tuple(extractor for extractor in EXTRACTORS if extractor.id in extractor_ids)


def label(extractor_id: str) -> str:
    """What a coverage line calls an extractor: its own label, else (an
    extractor this list does not know, e.g. a test double) the id spelled out."""
    for extractor in EXTRACTORS:
        if extractor.id == extractor_id:
            return extractor.label or extractor.domain
    return extractor_id.replace("_", " ")
