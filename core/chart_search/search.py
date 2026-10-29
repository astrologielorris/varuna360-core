# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Query, filters, results and coverage (design.md §4.7). Read only, never computes.

FTS ∩ scope ∩ kinds gives candidate entries; each filter becomes a moment set
at its extractor's projection; the sets are intersected (AND only). **A moment
not computed for a needed extractor never matches**: it is counted in that
extractor's ``Coverage`` instead, so a partial answer always says so.
"""

from __future__ import annotations

import json
import shlex
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from core.chart_search import taxonomy
from core.chart_search.errors import BadFilterError
from core.chart_search.extractors import positions, registry
from core.chart_search.extractors.base import Extractor
from core.chart_search.extractors.subjects import LAGNA
from core.chart_search.sources import EntryId, EntryKind, FileOrigin, SessionOrigin
from core.chart_search.stamp import computation_stamp
from core.chart_search.store import (
    EntryRow,
    MomentId,
    ProjectionId,
    RowConstraint,
    StoreReader,
)
from core.chart_search.system import Field as SystemField
from core.chart_search.system import Scalar, SearchSystem
from core.chart_search.taxonomy import Naming, PropertySpec, Qualifier, Value

#: The result columns: Positions' D1 sign of these subjects.
COLUMN_SUBJECTS: Mapping[str, str] = {
    "ascendant": LAGNA,
    "sun": "Sun",
    "moon": "Moon",
}
COLUMN_VARGA = "D1"


class Sources(StrEnum):
    ALL = "all"
    LOADED = "loaded"
    FOLDERS = "folders"


class SortKey(StrEnum):
    """The panel's ``sort_combo`` item data (Pro selects with ``findData``)."""

    NAME = "name"
    ASCENDANT = "ascendant"
    SUN = "sun"
    MOON = "moon"
    CITY = "city"
    COUNTRY = "country"
    BIRTH_DATE = "birth_date"
    FILE_MODIFIED = "file_modified"


@dataclass(frozen=True)
class Scope:
    sources: Sources = Sources.ALL
    folders: tuple[str, ...] = ()  # used when sources is FOLDERS
    include_fileless: bool = True  # the "Loaded charts (no file)" folder entry
    hidden: tuple[str, ...] = ()  # unticked folders, left out under ALL
    #: Folders that left the folder list whose files are still being taken
    #: out of the index (the forget is asynchronous, and saved until it
    #: commits: review r10). Every source leaves out a FILE entry under one
    #: of them unless it is loaded (a loaded chart stays, as the session
    #: entry it becomes); session entries are never left out by it.
    forgetting: tuple[str, ...] = ()
    #: The folders still on the list: a file under one of them is never left
    #: out by ``forgetting`` (a removed parent with a listed child keeps the
    #: child's charts, as the committed forget does; review r11).
    retained: tuple[str, ...] = ()
    kinds: frozenset[EntryKind] = frozenset({EntryKind.BIRTH})


#: Every entry of every kind: REBUILD INDEX, "Compute everything" and
#: ``chart_index compute`` cover it, whatever scope a search shows.
EVERYTHING = Scope(kinds=frozenset(EntryKind))


@dataclass(frozen=True)
class Filter:
    """As a caller gives it: ``value`` and qualifier values may be stored
    values or labels; ``resolve`` checks and translates them. ``subject`` may
    be a group name (``subjects.SUBJECT_GROUPS``); ``subject`` and ``value``
    may be ``None`` or ``taxonomy.ANY`` (any). Still exactly one property."""

    subject: str | None
    property: str
    value: Value | None
    qualifiers: tuple[tuple[str, str], ...] = ()  # (name, value); absent = any


@dataclass(frozen=True)
class ResolvedFilter:
    """A filter in stored values, bound to its property and extractor.
    ``subjects`` is what the subject slot matches (a group's members), ``None``
    any; ``value`` ``None`` is any."""

    subjects: tuple[str, ...] | None
    spec: PropertySpec
    extractor: Extractor
    value: Value | None
    q1: str | None
    q2: str | None


def resolve(f: Filter) -> ResolvedFilter:
    """Raises ``BadFilterError`` (unknown property, subject or group, a group
    with no subject of the property, a value or label that does not resolve,
    an undeclared qualifier name or value)."""
    extractor = registry.get(taxonomy.owner(f.property))
    spec = taxonomy.catalogue()[f.property]
    subjects = taxonomy.parse_subjects(spec, f.subject)
    value = taxonomy.parse_value_or_any(spec, f.value)
    names = tuple(q.name for q in spec.qualifiers)
    given: dict[str, str] = {}
    for name, raw in f.qualifiers:
        if name not in names:
            raise BadFilterError(f"{spec.name} has no qualifier {name!r}", names)
        if name in given:
            raise BadFilterError(f"qualifier {name!r} given twice", names)
        given[name] = raw
    q1, q2 = _qualifier_columns(spec, given)
    return ResolvedFilter(subjects, spec, extractor, value, q1, q2)


def _qualifier_columns(
    spec: PropertySpec, given: Mapping[str, str]
) -> tuple[str | None, str | None]:
    """``(q1, q2)`` in declaration order; an absent qualifier is its default,
    ``None`` (any) when it has none; ``taxonomy.ANY`` is any."""
    columns: list[str | None] = [
        _parse_qualifier(spec, q, given[q.name]) if q.name in given else q.default
        for q in spec.qualifiers
    ]
    columns += [None] * (2 - len(columns))
    return columns[0], columns[1]


def _parse_qualifier(spec: PropertySpec, qualifier: Qualifier, raw: str) -> str | None:
    """A qualifier value or its label, case-insensitive; ``taxonomy.ANY``
    is ``None`` (any) where the qualifier ``allows_any``. An open set
    (``values`` None) takes the value as given."""
    if raw.strip() == taxonomy.ANY:
        if not qualifier.allows_any:
            raise BadFilterError(
                f"{spec.name} {qualifier.name} cannot be any "
                f"(absent means {qualifier.default})",
                qualifier.values or (),
            )
        return None
    if qualifier.values is None:
        return raw
    typed = raw.strip().casefold()
    labels = {
        value: taxonomy.qualifier_label(
            spec, qualifier.name, value, taxonomy.ENGLISH_WESTERN
        )
        for value in qualifier.values
    }
    for value, text in labels.items():
        if typed in (value.casefold(), text.casefold()):
            return value
    raise BadFilterError(
        f"{raw!r} is not a value of {spec.name} {qualifier.name}",
        tuple(labels.values()),
    )


@dataclass(frozen=True)
class Query:
    system: SearchSystem
    text: str = ""
    scope: Scope = field(default_factory=Scope)
    filters: tuple[Filter, ...] = ()
    sort: SortKey = SortKey.NAME
    reverse: bool = False
    limit: int | None = None  # None = all


@dataclass(frozen=True)
class ResultEntry:
    entry_id: EntryId
    name: str
    path: str | None  # None for file-less entries
    kind: EntryKind
    place: str
    country: str
    birth_local: str
    file_modified: float | None
    loaded_in: tuple[str, ...]  # profiles
    unsaved_changes: bool
    #: D1 sign ordinals in the query's system; None when Positions is not
    #: computed for the entry's moment (labels via taxonomy.label at display).
    ascendant: int | None
    sun: int | None
    moon: int | None
    #: The entry's birth moment (SPEC-FIND-005: the inspector and the extra
    #: result columns read its stored facts). Not part of the JSON output.
    moment_id: MomentId | None = None


@dataclass(frozen=True)
class Elsewhere:
    """Moments one extractor has computed in another projection: the
    projection's own fields (only what the extractor reads, never a whole
    system) and how many of the query's moments it holds."""

    fields: tuple[tuple[str, Scalar], ...]
    computed: int

    def search_flags(self) -> tuple[str, ...]:
        """The ``--search-system.*`` flags that search this projection, or
        ``()`` when it cannot be asked for (a custom ayanamsa definition that
        is not the installed one is no input, FIND-004 §3.4)."""
        names = {field.value for field in SystemField}
        if any(name not in names for name, _ in self.fields):
            return ()
        flags: list[str] = []
        for name, value in self.fields:
            flags += [f"--search-system.{name.replace('_', '-')}", str(value)]
        return tuple(flags)


@dataclass(frozen=True)
class Coverage:
    """One needed extractor's state over the query's candidate moments."""

    extractor_id: str
    domain: str
    in_scope: int
    computed: int
    failed: int
    computed_with: tuple[str, ...]  # app versions other than the running one
    #: Incomplete only: the same extractor's other projections with ok rows
    #: over the same moments, most computed first (plan R10). Never used to
    #: answer: a search reads its own system's rows only.
    elsewhere: tuple[Elsewhere, ...] = ()
    #: ok moments stamped with another app version (Recompute's work).
    stale: int = 0

    @property
    def missing(self) -> int:
        """In scope with no computation at the current extractor version."""
        return self.in_scope - self.computed - self.failed

    @property
    def complete(self) -> bool:
        """Every in-scope moment computed ok; a stale stamp does not count."""
        return self.computed == self.in_scope


@dataclass(frozen=True)
class SearchResult:
    entries: tuple[ResultEntry, ...]
    total: int  # before ``limit``
    system: SearchSystem
    coverage: tuple[Coverage, ...]  # every needed extractor, complete or not


def needed(query: Query) -> tuple[Extractor, ...]:
    """Extractors that own the query's filters, plus Positions for the result
    columns. A text-only query still needs Positions (for Asc/Sun/Moon) but
    matches without it."""
    ids = {taxonomy.owner(f.property) for f in query.filters} | {positions.EXTRACTOR.id}
    return tuple(e for e in registry.EXTRACTORS if e.id in ids)


def candidates(
    store: StoreReader, scope: Scope, text: str = ""
) -> tuple[EntryRow, ...]:
    """FTS ∩ scope ∩ kinds, the entries a search (or a compute plan) covers."""
    return store.candidates(
        text,
        paths_under=scope.folders if scope.sources is Sources.FOLDERS else None,
        include_fileless=scope.include_fileless,
        loaded_only=scope.sources is Sources.LOADED,
        kinds=frozenset(kind.value for kind in scope.kinds),
        paths_hidden=scope.hidden if scope.sources is Sources.ALL else (),
        paths_forgetting=scope.forgetting,
        paths_retained=scope.retained,
    )


def extractor_coverage(
    store: StoreReader,
    extractor: Extractor,
    projection_id: ProjectionId | None,
    moments: frozenset[MomentId],
    running: str,
) -> Coverage:
    """One extractor's state over ``moments`` at ``projection_id`` (None:
    never computed in that system)."""
    counts = store.coverage(projection_id, extractor.version, moments, running)
    elsewhere: tuple[Elsewhere, ...] = ()
    if counts.computed < counts.in_scope:
        elsewhere = tuple(
            Elsewhere(tuple(sorted(json.loads(key).items())), computed)
            for key, computed in store.computed_elsewhere(
                extractor.id, extractor.version, moments, projection_id
            )
        )
    return Coverage(
        extractor.id,
        extractor.domain,
        counts.in_scope,
        counts.computed,
        counts.failed,
        counts.stale_app_versions,
        elsewhere,
        counts.stale,
    )


def coverage_snapshot(
    store: StoreReader, system: SearchSystem, scope: Scope
) -> tuple[Coverage, ...]:
    """Every registered extractor's coverage over ``scope``'s moments in
    ``system`` (the Find Chart Library and status bar rings, SPEC-FIND-005
    §3.7). Counts are moments. Read only; never computes."""
    moments = frozenset(row.moment_id for row in candidates(store, scope))
    running = computation_stamp()
    return tuple(
        extractor_coverage(
            store,
            extractor,
            store.projection_id(extractor.projection(system)),
            moments,
            running,
        )
        for extractor in registry.EXTRACTORS
    )


@dataclass(frozen=True)
class CoverageMoments:
    """One extractor's in-scope moments by state (the Library's COMPUTE /
    RETRY / RECOMPUTE buttons plan exactly these, SPEC-FIND-005 §3.7)."""

    extractor_id: str
    missing: frozenset[MomentId]
    failed: frozenset[MomentId]
    stale: frozenset[MomentId]


def coverage_moments(
    store: StoreReader, system: SearchSystem, scope: Scope, extractor: Extractor
) -> CoverageMoments:
    """``extractor``'s in-scope moments in ``system`` split by state: missing
    (no computation at the current version), failed, stale (ok, stamped by
    another app version). Read only."""
    moments = frozenset(row.moment_id for row in candidates(store, scope))
    pid = store.projection_id(extractor.projection(system))
    states = {} if pid is None else store.states(pid, extractor.version, moments)
    running = computation_stamp()
    return CoverageMoments(
        extractor.id,
        frozenset(m for m in moments if m not in states),
        frozenset(m for m, st in states.items() if not st.ok),
        frozenset(m for m, st in states.items() if st.ok and st.app_version != running),
    )


def search(store: StoreReader, query: Query) -> SearchResult:
    """Raises ``BadFilterError``; never computes, never writes."""
    resolved = tuple(resolve(f) for f in query.filters)
    rows = candidates(store, query.scope, query.text)
    moments = frozenset(row.moment_id for row in rows)
    running = computation_stamp()

    coverage: list[Coverage] = []
    # extractor id -> (projection id, moments ok at the current version)
    done: dict[str, tuple[ProjectionId | None, frozenset[MomentId]]] = {}
    for extractor in needed(query):
        pid = store.projection_id(extractor.projection(query.system))
        coverage.append(extractor_coverage(store, extractor, pid, moments, running))
        ok = (
            frozenset()
            if pid is None
            else store.computed(pid, extractor.version, moments)
        )
        done[extractor.id] = (pid, ok)

    matched = moments
    for rf in resolved:
        pid, ok = done[rf.extractor.id]
        if pid is None:
            matched = frozenset()
            break
        constraint = RowConstraint(rf.subjects, rf.spec.name, rf.value, rf.q1, rf.q2)
        matched = store.matching(pid, constraint, matched & ok)

    columns: dict[MomentId, dict[str, int | str]] = {}
    pid, ok = done[positions.EXTRACTOR.id]
    if pid is not None and matched & ok:
        columns = store.rows_for(
            pid,
            matched & ok,
            tuple(COLUMN_SUBJECTS.values()),
            "sign",
            q1=COLUMN_VARGA,
        )

    entries = _sorted(
        [
            _result(row, columns.get(row.moment_id, {}))
            for row in rows
            if row.moment_id in matched
        ],
        query.sort,
        query.reverse,
    )
    limited = entries if query.limit is None else entries[: query.limit]
    return SearchResult(tuple(limited), len(entries), query.system, tuple(coverage))


def _result(row: EntryRow, columns: Mapping[str, int | str]) -> ResultEntry:
    entry = row.entry
    origin = entry.origin

    def sign(column: str) -> int | None:
        value = columns.get(COLUMN_SUBJECTS[column])
        return None if value is None else int(value)

    return ResultEntry(
        entry_id=entry.entry_id,
        name=entry.name,
        path=entry.path,
        kind=entry.kind,
        place=entry.place,
        country=entry.country,
        birth_local=entry.birth_local,
        file_modified=origin.mtime if isinstance(origin, FileOrigin) else None,
        loaded_in=row.loaded_in,
        unsaved_changes=isinstance(origin, SessionOrigin) and origin.unsaved_changes,
        ascendant=sign("ascendant"),
        sun=sign("sun"),
        moon=sign("moon"),
        moment_id=row.moment_id,
    )


_TEXT_SORTS: Mapping[SortKey, Callable[[ResultEntry], str]] = {
    SortKey.NAME: lambda e: e.name,
    SortKey.CITY: lambda e: e.place,
    SortKey.COUNTRY: lambda e: e.country,
    SortKey.BIRTH_DATE: lambda e: e.birth_local,  # "YYYY-MM-DD HH:MM:SS"
}
#: Sorts on a value an entry may lack; those entries go last either way.
_OPTIONAL_SORTS: Mapping[SortKey, Callable[[ResultEntry], float | None]] = {
    SortKey.ASCENDANT: lambda e: e.ascendant,
    SortKey.SUN: lambda e: e.sun,
    SortKey.MOON: lambda e: e.moon,
    SortKey.FILE_MODIFIED: lambda e: e.file_modified,
}


def _sorted(
    entries: Sequence[ResultEntry], key: SortKey, reverse: bool
) -> list[ResultEntry]:
    """Ties broken by name, then entry id, so the order is stable across runs."""

    def tie(e: ResultEntry) -> tuple[str, str]:
        return (e.name.casefold(), e.entry_id)

    text = _TEXT_SORTS.get(key)
    if text is not None:
        return sorted(
            entries, key=lambda e: (text(e).casefold(), *tie(e)), reverse=reverse
        )
    get = _OPTIONAL_SORTS[key]
    known = [e for e in entries if get(e) is not None]
    unknown = [e for e in entries if get(e) is None]
    return sorted(known, key=lambda e: (get(e), *tie(e)), reverse=reverse) + sorted(
        unknown, key=tie
    )


def compute_command(coverage: Coverage, system: SearchSystem) -> str:
    """The exact ``python -m AI_tools.cli.chart_index compute ...`` line that
    fills this coverage (headless callers print it). The system flags are
    spelled as ``--tool`` spells options (``core.capabilities.cli.option_flag``:
    ``--search-system.ayanamsa-id``), so the CLIs and ``--tool`` agree."""
    argv = ["python", "-m", "AI_tools.cli.chart_index", "compute"]
    for system_field in SystemField:
        argv += [
            f"--search-system.{system_field.value.replace('_', '-')}",
            str(getattr(system, system_field.value)),
        ]
    argv += ["--extractors", coverage.extractor_id]
    if coverage.failed:
        argv.append("--retry-failed")
    return shlex.join(argv)


def result_labels(
    entry: ResultEntry, system: SearchSystem, naming: Naming
) -> dict[str, str]:
    """``{"ascendant", "sun", "moon"}`` labels for the table and the JSON output;
    ``""`` when not computed."""
    spec = taxonomy.catalogue()["sign"]
    values = {"ascendant": entry.ascendant, "sun": entry.sun, "moon": entry.moon}
    return {
        column: ""
        if value is None
        else taxonomy.label(spec, value, system.mode, naming)
        for column, value in values.items()
    }
