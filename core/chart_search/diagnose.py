# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Why a search gives few or no results (SPEC-FIND-006 §3, td-k7fpy.6).

``diagnose(store, query, result, app_system=...)`` returns findings as codes
and facts (counts, engine identifiers, field values), never words and never a
chart name: the panel phrases them with approved copy, the Ask AI tools pass
them to the model as they are.

Read only, like ``search``: it runs a few more searches on the caller's
reader (at most one per finding; the dropped-filter one matches each filter
once and intersects) and never computes.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

from core.chart_search.search import (
    Query,
    Scope,
    SearchResult,
    Sources,
    candidates,
    needed,
    resolve,
    search,
)
from core.chart_search.store import RowConstraint
from core.chart_search.sources import EntryKind
from core.chart_search.store import StoreReader
from core.chart_search.system import SearchSystem
from core.capabilities.chart_search import coverage_dict

#: Filters tried one at a time by ``one_filter_empties``.
MAX_DROPPED = 6


class Code(StrEnum):
    NOT_COMPUTED = "not_computed"
    SYSTEM_DIFFERS = "system_differs"
    KINDS_LEFT_OUT = "kinds_left_out"
    FOLDERS_LEFT_OUT = "folders_left_out"
    TEXT_MATCHES_NOTHING = "text_matches_nothing"
    ONE_FILTER_EMPTIES = "one_filter_empties"
    TRUNCATED = "truncated"  # more filters than MAX_DROPPED: the rest untried


@dataclass(frozen=True)
class Finding:
    code: Code
    facts: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code.value, **self.facts}


@dataclass(frozen=True)
class Diagnosis:
    findings: tuple[Finding, ...]

    def as_list(self) -> list[dict[str, Any]]:
        return [f.as_dict() for f in self.findings]

    def codes(self) -> tuple[str, ...]:
        return tuple(f.code.value for f in self.findings)


def _total(store: StoreReader, query: Query) -> SearchResult:
    return search(store, replace(query, limit=None))


def _not_computed(result: SearchResult) -> list[Finding]:
    out = []
    for cov in result.coverage:
        if cov.complete or not cov.in_scope:
            continue
        item = coverage_dict(cov, result.system)
        out.append(
            Finding(
                Code.NOT_COMPUTED,
                {
                    "extractor_id": item["extractor_id"],
                    "label": item["label"],
                    "computed": item["computed"],
                    "failed": item["failed"],
                    "in_scope": item["in_scope"],
                    "computed_elsewhere": item["computed_elsewhere"],
                },
            )
        )
    return out


def _system_differs(query: Query, app_system: SearchSystem | None) -> list[Finding]:
    """Fields the query's needed extractors read whose value differs from the
    app's frame (after each extractor's normalisation: an ayanamsa a sign
    extractor drops outside Sidereal is no difference)."""
    if app_system is None:
        return []
    fields: dict[str, dict[str, Any]] = {}
    for extractor in needed(query):
        here = dict(extractor.projection(query.system).fields)
        app = dict(extractor.projection(app_system).fields)
        for name in sorted(set(here) | set(app)):
            if here.get(name) != app.get(name) and name not in fields:
                fields[name] = {"query": here.get(name), "app": app.get(name)}
    if not fields:
        return []
    return [Finding(Code.SYSTEM_DIFFERS, {"fields": fields})]


def _kinds_left_out(store: StoreReader, query: Query) -> list[Finding]:
    left_out = frozenset(EntryKind) - query.scope.kinds
    if not left_out:
        return []
    wider = replace(query, scope=replace(query.scope, kinds=left_out))
    counts = Counter(e.kind.value for e in _total(store, wider).entries)
    if not counts:
        return []
    return [Finding(Code.KINDS_LEFT_OUT, {"counts": dict(sorted(counts.items()))})]


def _folders_left_out(
    store: StoreReader, query: Query, result: SearchResult
) -> list[Finding]:
    """Matches the folder choice leaves out: unticked folders, and under
    ``folders`` the file-less entries when they are not included."""
    scope = query.scope
    narrowed = scope.sources is Sources.FOLDERS or (
        scope.sources is Sources.ALL and scope.hidden
    ) or not scope.include_fileless
    if not narrowed:
        return []
    everything = Scope(
        sources=Sources.ALL if scope.sources is not Sources.LOADED else Sources.LOADED,
        include_fileless=True,
        kinds=scope.kinds,
    )
    shown = {e.entry_id for e in _total(store, query).entries}
    wider = _total(store, replace(query, scope=everything))
    extra = sum(1 for e in wider.entries if e.entry_id not in shown)
    if not extra:
        return []
    return [Finding(Code.FOLDERS_LEFT_OUT, {"count": extra})]


def _text_matches_nothing(store: StoreReader, query: Query) -> list[Finding]:
    if not query.text.strip():
        return []
    if candidates(store, query.scope, query.text):
        return []
    return [Finding(Code.TEXT_MATCHES_NOTHING, {})]


def _one_filter_empties(
    store: StoreReader, query: Query, result: SearchResult
) -> list[Finding]:
    """Each filter's matching moments are computed once (as ``search`` does,
    over the computed moments of its extractor), then every drop-one total
    is a set intersection: one pass, whatever the number of filters.

    A filter whose extractor is not complete is never reported (its charts
    are missing, not contradictory: ``not_computed`` says so). More filters
    than ``MAX_DROPPED``: the first ones are tried and the finding set says
    ``truncated``."""
    incomplete = {c.extractor_id for c in result.coverage if not c.complete}
    rows = candidates(store, query.scope, query.text)
    moments = frozenset(row.moment_id for row in rows)
    sets: list[frozenset] = []
    owners: list[str] = []
    for f in query.filters:
        rf = resolve(f)
        owners.append(rf.extractor.id)
        pid = store.projection_id(rf.extractor.projection(query.system))
        if pid is None:
            sets.append(frozenset())
            continue
        ok = store.computed(pid, rf.extractor.version, moments)
        constraint = RowConstraint(rf.subjects, rf.spec.name, rf.value, rf.q1, rf.q2)
        sets.append(frozenset(store.matching(pid, constraint, ok)))
    out = []
    for index in range(min(MAX_DROPPED, len(sets))):
        if owners[index] in incomplete:
            continue
        kept = moments
        for other, matched in enumerate(sets):
            if other != index:
                kept = kept & matched
        total = sum(1 for row in rows if row.moment_id in kept)
        if total:
            out.append(
                Finding(Code.ONE_FILTER_EMPTIES, {"filter_index": index, "count": total})
            )
    if len(sets) > MAX_DROPPED:
        out.append(Finding(Code.TRUNCATED, {"tried": MAX_DROPPED, "filters": len(sets)}))
    return out


def diagnose(
    store: StoreReader,
    query: Query,
    result: SearchResult,
    *,
    app_system: SearchSystem | None = None,
) -> Diagnosis:
    """The findings for ``query`` and the ``result`` it gave, in SPEC-FIND-006
    §3 order. A query with results gets only ``not_computed`` and
    ``system_differs``. Raises what ``search`` raises (a query that searched
    once does not)."""
    findings = _not_computed(result) + _system_differs(query, app_system)
    if result.total:
        return Diagnosis(tuple(findings))
    findings += _kinds_left_out(store, query)
    findings += _folders_left_out(store, query, result)
    findings += _text_matches_nothing(store, query)
    if len(query.filters) >= 2:
        findings += _one_filter_empties(store, query, result)
    return Diagnosis(tuple(findings))
