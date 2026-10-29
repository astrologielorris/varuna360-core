# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The extra result columns (SPEC-FIND-005 §3.5, §3.8, INV-1, D-6). Qt-free.

The host's ``results_table`` keeps its ten LOGICAL columns 0-9
(``results.COLUMNS``, Pro A.2 reads 0, 1, 4, 5). Extra columns are only ever
APPENDED at logical 10 and up, and the ALL placements are MOVED visually right
after Moon (``horizontalHeader().moveSection``); nothing is inserted before 10.

Host wiring (W7)::

    model = result_columns.model(all_placements, groups)
    table.setColumnCount(result_columns.BASE + len(model.columns))
    for i, header in enumerate(model.headers, start=result_columns.BASE):
        table.setHorizontalHeaderItem(i, QTableWidgetItem(header))
    result_columns.apply_visual_order(table.horizontalHeader(), model.visual_order)
    values = facts.column_values(store, system, naming, moments, model.groups,
                                 model.all_placements)       # stored rows only
    for col, text in zip(model.logical, result_columns.cell_texts(entry, values, model)):
        table.setItem(row, col, QTableWidgetItem(text))

Setting ``ui.find_chart_result_columns``: ``load_columns_setting(raw)`` drops
unknown group keys; ``dump_columns_setting(all_placements, groups)`` writes it.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from core.chart_search import facts
from core.chart_search.search import ResultEntry
from panels.find_chart.results import COLUMNS, openable_path

#: The logical columns Pro reads stay 0-9; extras start here.
BASE: int = len(COLUMNS)
#: Logical index of Moon (the ALL placements follow it visually).
MOON: int = COLUMNS.index("Moon")
#: The group keys, in the chips' (and columns') canonical order.
GROUP_KEYS: tuple[str, ...] = tuple(g.key for g in facts.COLUMN_GROUPS)

SETTING_KEY = "ui.find_chart_result_columns"
DEFAULT_SETTING: Mapping[str, object] = {"all_placements": False, "groups": []}


def normalise_groups(groups: Iterable[str]) -> tuple[str, ...]:
    """Known group keys only, once each, in canonical order."""
    wanted = set(groups)
    return tuple(k for k in GROUP_KEYS if k in wanted)


@dataclass(frozen=True)
class ColumnModel:
    all_placements: bool
    groups: tuple[str, ...]
    #: The extra columns, logical BASE, BASE + 1, ... in this order.
    columns: tuple[facts.Column, ...]

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(c.key for c in self.columns)

    @property
    def headers(self) -> tuple[str, ...]:
        return tuple(c.header for c in self.columns)

    @property
    def logical(self) -> tuple[int, ...]:
        """The logical index of each extra column (BASE and up, never < 10)."""
        return tuple(range(BASE, BASE + len(self.columns)))

    @property
    def column_count(self) -> int:
        return BASE + len(self.columns)

    def logical_of(self, key: str) -> int:
        return BASE + self.keys.index(key)

    @property
    def visual_order(self) -> tuple[int, ...]:
        """Logical index per visual position: Name, Asc, Sun, Moon, the ALL
        placements, then City .. Source, then the group columns."""
        placements = [
            BASE + i for i, c in enumerate(self.columns) if c.group == facts.PLACEMENTS_KEY
        ]
        groups = [
            BASE + i for i, c in enumerate(self.columns) if c.group != facts.PLACEMENTS_KEY
        ]
        head = list(range(0, MOON + 1))
        tail = list(range(MOON + 1, BASE))
        return tuple(head + placements + tail + groups)


def model(all_placements: bool, groups: Iterable[str]) -> ColumnModel:
    """The extra-column model for these choices (``facts.columns``)."""
    keys = normalise_groups(groups)
    return ColumnModel(bool(all_placements), keys, facts.columns(keys, bool(all_placements)))


def apply_visual_order(header, order: Sequence[int]) -> None:
    """Move sections of ``header`` (a ``QHeaderView``, duck typed) so that
    visual position ``i`` shows logical ``order[i]``; logical indices never
    change (INV-1). Sections beyond ``order`` keep their relative order."""
    for visual, logical in enumerate(order):
        current = header.visualIndex(logical)
        if current != visual and current >= 0:
            header.moveSection(current, visual)


def cell_texts(
    entry: ResultEntry,
    values: Mapping[object, Mapping[str, str]],
    column_model: ColumnModel,
) -> list[str]:
    """The extra cells of one row, in logical order: the stored label, or
    ``""`` when nothing is stored (columns never compute, §3.5)."""
    cells = values.get(entry.moment_id, {}) if entry.moment_id is not None else {}
    return [cells.get(key, "") for key in column_model.keys]


def group_missing_counts(
    entries: Iterable[ResultEntry],
    missing_moments: Mapping[str, frozenset],
) -> dict[str, int]:
    """Per group: how many displayed ENTRIES sit on a moment the group lacks
    (``facts.group_missing_moments``), the unit of the result count."""
    entries = list(entries)
    return {
        group: sum(1 for e in entries if e.moment_id is not None and e.moment_id in moments)
        for group, moments in missing_moments.items()
    }


def chip_tooltip(group_key: str, n_missing: int) -> str:
    label = facts.GROUPS_BY_KEY[group_key].label
    if n_missing <= 0:
        return f"Show {label} columns"
    charts = "chart" if n_missing == 1 else "charts"
    return f"{label} not computed for {n_missing:,} {charts}: Compute in Library"


def source_pills(entry: ResultEntry) -> tuple[str, ...]:
    """The source as small pills (§4.6): ``file``, ``loaded (A, B)``,
    ``no file``, ``unsaved changes``."""
    profiles = ", ".join(entry.loaded_in)
    loaded = (f"loaded ({profiles})",) if profiles else ()
    if openable_path(entry):
        return ("file", *loaded)
    pills: tuple[str, ...] = loaded if entry.path else ("no file", *loaded)
    if not pills:
        pills = ("no file",)
    if entry.unsaved_changes:
        pills += ("unsaved changes",)
    return pills


# ------------------------------------------------------------------ setting


def load_columns_setting(raw) -> tuple[bool, tuple[str, ...]]:
    """``(all_placements, groups)`` from the stored setting (a dict, or its
    JSON text); unknown group keys and malformed values are dropped."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = None
    if not isinstance(raw, Mapping):
        return False, ()
    all_placements = raw.get("all_placements") is True
    groups = raw.get("groups")
    if not isinstance(groups, (list, tuple)):
        groups = ()
    return all_placements, normalise_groups(g for g in groups if isinstance(g, str))


def dump_columns_setting(all_placements: bool, groups: Iterable[str]) -> dict:
    return {"all_placements": bool(all_placements), "groups": list(normalise_groups(groups))}
