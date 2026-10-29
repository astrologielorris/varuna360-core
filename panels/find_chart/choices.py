# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""What the filter rows offer (filter-redesign.md §1-§2), the store side.
Qt-free.

The navigation and the labels are ``core.chart_search.facets``'s; this module
answers its ``Narrow`` question: the values stored at a property's projection
of the search system (``SELECT DISTINCT``), or ``None`` when that projection
has nothing computed, never run or every moment failed (the facet then offers
its whole domain: narrowing to no stored value would leave only "Any").
"""

from __future__ import annotations

import sqlite3

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from core.chart_search import taxonomy
from core.chart_search.errors import NoIndexError, StoreBusyError
from core.chart_search.extractors import registry
from core.chart_search.store import ProjectionId, StoreReader
from core.chart_search.system import SearchSystem
from core.chart_search.taxonomy import Naming, Value


@dataclass(frozen=True)
class Item:
    value: Value | None  # None: the combo's blank "pick one"
    label: str
    tooltip: str | None = None


class FilterChoices:
    """The search system and naming the rows label in, and ``facets.Narrow``
    over the store. ``open_store`` returns a reader or raises
    ``NoIndexError``; each call opens and closes one, so a choice list never
    holds the store."""

    def __init__(
        self,
        system: SearchSystem,
        naming: Naming,
        open_store: Callable[[], StoreReader] = StoreReader.open,
    ) -> None:
        self.system = system
        self.naming = naming
        self._open_store = open_store

    def __call__(
        self, property_name: str, column: str, fixed: Mapping[str, Value]
    ) -> tuple[Value, ...] | None:
        """``facets.Narrow``: the stored values of ``column``, or None when
        the projection has nothing computed (or there is no store). A busy
        or locked store is treated like no store: the whole domain is
        offered and picks are kept (review r6 #7); other database errors
        still raise."""
        extractor = registry.get(taxonomy.owner(property_name))
        try:
            with self._open_store() as store:
                pid: ProjectionId | None = store.projection_id(
                    extractor.projection(self.system)
                )
                if pid is None or not store.any_computed(pid, extractor.version):
                    return None
                return store.distinct(pid, property_name, column, **fixed)
        except (NoIndexError, StoreBusyError):
            return None
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc) or "busy" in str(exc):
                return None
            raise
