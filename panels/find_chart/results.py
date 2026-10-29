# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""What the results table shows (design.md §4.9). Qt-free.

The nine columns stay in place (Pro reads 0 Name, 1 Asc, 4 City, 5 Country,
pro-boundary.md A.2) and **Source** comes last. Asc, Sun and Moon are labels
in the search system (``search.result_labels``).
"""

from __future__ import annotations

import datetime
import os
from functools import lru_cache
from collections.abc import Callable, Mapping, Sequence

from core.chart_search.search import ResultEntry, SortKey

COLUMNS: tuple[str, ...] = (
    "Name",
    "Asc",
    "Sun",
    "Moon",
    "City",
    "Country",
    "Birth",
    "Modified",
    "Path",
    "Source",
)
#: Header click -> sort; Path and Source do not sort.
COLUMN_SORTS: Mapping[int, SortKey] = {
    0: SortKey.NAME,
    1: SortKey.ASCENDANT,
    2: SortKey.SUN,
    3: SortKey.MOON,
    4: SortKey.CITY,
    5: SortKey.COUNTRY,
    6: SortKey.BIRTH_DATE,
    7: SortKey.FILE_MODIFIED,
}
#: The group combo's keys (item data); "none" groups nothing.
GROUPS: tuple[str, ...] = (
    "none",
    "folder",
    "ascendant",
    "sun",
    "moon",
    "country",
    "city",
)


def openable_path(entry: ResultEntry) -> str:
    """The file a double-click opens: a file entry's path, ``""`` for a
    session entry (its stale or unscanned ``chtk_path`` is not opened)."""
    if entry.file_modified is None:
        return ""
    return entry.path or ""


def source_text(entry: ResultEntry) -> str:
    """``file``, ``file · loaded (A, B)``, ``loaded · A``, ``no file · A``,
    plus ``unsaved changes`` when the session differs from the file."""
    profiles = ", ".join(entry.loaded_in)
    if entry.file_modified is not None:
        return f"file · loaded ({profiles})" if profiles else "file"
    text = f"loaded · {profiles}" if entry.path else f"no file · {profiles}"
    if entry.unsaved_changes:
        text += " · unsaved changes"
    return text


@lru_cache(maxsize=8192)
def _modified_date(timestamp: float) -> str:
    return datetime.datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")


def row_values(entry: ResultEntry, labels: Mapping[str, str]) -> list[str]:
    """The ten cells, in ``COLUMNS`` order."""
    path = entry.path or ""
    modified = (
        _modified_date(entry.file_modified)
        if entry.file_modified is not None
        else ""
    )
    return [
        entry.name,
        labels["ascendant"],
        labels["sun"],
        labels["moon"],
        entry.place,
        entry.country,
        entry.birth_local[:16],  # "YYYY-MM-DD HH:MM"
        modified,
        os.path.basename(os.path.dirname(path)) if path else "",
        source_text(entry),
    ]


def grouped(
    entries: Sequence[ResultEntry],
    group: str,
    labels: Callable[[ResultEntry], Mapping[str, str]],
) -> dict[str, list[ResultEntry]]:
    """Entries by group header, groups in first-seen order (the sort order).
    An entry without the value goes under ``"(none)"``."""
    out: dict[str, list[ResultEntry]] = {}
    for entry in entries:
        if group == "folder":
            key = os.path.basename(os.path.dirname(entry.path)) if entry.path else ""
        elif group in ("ascendant", "sun", "moon"):
            key = labels(entry)[group]
        elif group == "country":
            key = entry.country
        else:
            key = entry.place
        out.setdefault(key or "(none)", []).append(entry)
    return out
