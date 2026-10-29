# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The panel's one effective search context (SPEC-FIND-005 §3.2, INV-4).

``SearchContext(system, naming, scope)`` is the frame, the labels and the
population of every read, plan, open and label path. Easy and Advanced differ
only in where its three parts come from; this module holds that rule as pure
functions, so the host only gathers the inputs.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from core.chart_search.search import Scope, Sources
from core.chart_search.sources import EntryKind
from core.chart_search.system import SearchSystem
from core.chart_search.taxonomy import Naming

EASY = "easy"
ADVANCED = "advanced"
LEVELS = (EASY, ADVANCED)
LEVEL_KEY = "ui.find_chart_search_level"


@dataclass(frozen=True)
class SearchContext:
    level: str
    system: SearchSystem
    naming: Naming
    scope: Scope


def level_of(value: object) -> str:
    """A saved level, or Easy (the factory default) for anything else."""
    return value if value in LEVELS else EASY


def easy_scope(
    unchecked_folders: Sequence[str],
    include_fileless: bool,
    forgetting: Sequence[str] = (),
    retained: Sequence[str] = (),
) -> Scope:
    """Easy's population: every source, birth charts only, still less the
    Library's unticked folders and, when unticked, the loaded charts.
    ``forgetting``: removed folders still in the index (``Scope.forgetting``)."""
    return Scope(
        sources=Sources.ALL,
        folders=(),
        include_fileless=include_fileless,
        kinds=frozenset({EntryKind.BIRTH}),
        hidden=tuple(unchecked_folders),
        forgetting=tuple(forgetting),
        retained=tuple(retained) if forgetting else (),
    )


def advanced_scope(
    sources: Sources,
    kinds: frozenset[EntryKind],
    checked_folders: Sequence[str],
    unchecked_folders: Sequence[str],
    include_fileless: bool,
    forgetting: Sequence[str] = (),
    retained: Sequence[str] = (),
) -> Scope:
    """The scope bar's population (as the panel built it before FIND-005)."""
    return Scope(
        sources=sources,
        folders=tuple(checked_folders) if sources is Sources.FOLDERS else (),
        include_fileless=include_fileless,
        kinds=kinds,
        hidden=tuple(unchecked_folders) if sources is Sources.ALL else (),
        forgetting=tuple(forgetting),
        retained=tuple(retained) if forgetting else (),
    )


def app_naming(use_western_names: object, sign_language: object) -> Naming:
    """The app's live naming (Easy), bypassing the panel's sign-name pick."""
    return Naming(bool(use_western_names), str(sign_language or "en"))


#: A filter's origin in the effective query (SPEC-FIND-006 §5.1).
ROW = "row"
TOKEN = "token"


@dataclass(frozen=True)
class FolderRef:
    path: str
    ticked: bool
    entries: int


@dataclass(frozen=True)
class QuerySnapshot:
    """The panel's whole effective query at one revision (SPEC-FIND-006
    §5.1, built by ``FindChartPanel.query_snapshot``): the ``Query`` (its
    ``text`` is the residual free text, its filters the chips then the
    resolving search-box tokens), each filter's stable id and origin
    (``ROW`` or ``TOKEN``; a token's id is ``t<offset>``, its position in
    the search text), the folders, the pinned fields (empty in Easy), the
    level and the revision."""

    query: object  # core.chart_search.search.Query
    filter_ids: tuple[str, ...]
    origins: tuple[str, ...]
    folders: tuple[FolderRef, ...]
    pinned: dict
    level: str
    revision: int
