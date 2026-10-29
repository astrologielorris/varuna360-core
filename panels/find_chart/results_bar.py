# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The results bar (SPEC-FIND-005 §3.5, §4.6).

``6 charts of 7,659   SORT [Name v][^v]   GROUP [None v]   [PLACEMENTS · 3|ALL]``
and, under it, one checkable chip per column group (``facts.COLUMN_GROUPS``),
an amber dot when the group is not computed for some displayed charts. The
chips row scrolls sideways when it does not fit (T1 and narrower).

The host keeps its ``sort_combo`` (SortKey data, Pro A.2) and
``group_combo``; the bar only lays them out and restyles them
(``kit.restyle_combo``). It never searches or computes (INV-3): it only
reports choices.

API
- ``ResultsBar(sort_combo, group_combo)``
- signals: ``reverse_toggled(bool)``, ``placements_changed(bool all)``,
  ``groups_changed(tuple[str, ...])`` (canonical order)
- ``set_count(shown, of, partial)``, ``set_reverse(on)``,
  ``set_columns(all_placements, groups)`` (no signal), ``set_group_dots({group:
  n_missing})``, ``set_tier(t)``, ``refresh_theme()``, ``refresh_metrics()``

Host wiring: ``bar = ResultsBar(self.sort_combo, self.group_combo)``;
``bar.set_columns(*result_columns.load_columns_setting(saved))``;
connect ``groups_changed`` / ``placements_changed`` to save the setting,
re-apply ``result_columns.model`` and ``_refresh_quietly()``; after each
search ``bar.set_count(...)`` and ``bar.set_group_dots(
result_columns.group_missing_counts(entries, facts.group_missing_moments(...)))``.
"""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from apps.widgets.action_bar.bar_types import Role
from core.chart_search import facts
from panels.find_chart import kit, responsive
from panels.find_chart.result_columns import GROUP_KEYS, chip_tooltip, normalise_groups
from ui.qt_theme import get_theme_colors, scaled_area_px


def count_text(shown: int, of: int, partial: bool = False) -> str:
    """"6 charts of 7,659", plus " (partial)" when a filter's coverage is
    incomplete."""
    charts = "chart" if shown == 1 else "charts"
    text = f"{shown:,} {charts} of {of:,}"
    return text + " (partial)" if partial else text


class ResultsBar(QWidget):
    reverse_toggled = Signal(bool)
    placements_changed = Signal(bool)
    groups_changed = Signal(tuple)

    def __init__(self, sort_combo: QComboBox, group_combo: QComboBox, parent=None):
        super().__init__(parent)
        self.sort_combo = sort_combo
        self.group_combo = group_combo
        self._tier = responsive.T0
        self._count = (0, 0, False)
        m = kit.metrics()
        self._m = m

        self.count_label = QLabel()
        self.count_label.setObjectName("fc_results_count")
        self.of_label = QLabel()
        self.sort_caption = kit.SectionHeader("Sort")
        self.group_caption = kit.SectionHeader("Group")
        self.reverse = kit.KitSegment(
            "reverse", "", m, icon="fc_sort", checkable=True, tooltip="Reverse order"
        )
        self.reverse.toggled.connect(self._on_reverse)
        self.reverse_cluster = kit.kit_cluster([self.reverse], m)

        self.place3 = kit.KitSegment(
            "placements_3", "PLACEMENTS · 3", m, icon="fc_expand", role=Role.TINT_BLUE,
            tooltip="Show the Ascendant, Sun and Moon",
        )
        self.place_all = kit.KitSegment(
            "placements_all", "ALL", m, role=Role.TINT_BLUE,
            tooltip="Show every placement and every body in the column groups",
        )
        self.place3.clicked.connect(lambda: self._on_placements(False))
        self.place_all.clicked.connect(lambda: self._on_placements(True))
        self.placements_cluster = kit.kit_cluster([self.place3, self.place_all], m)
        self._all = False

        self.chips: dict[str, kit.Chip] = {}
        chips_row = QWidget()
        self._chips_lay = QHBoxLayout(chips_row)
        self._chips_lay.setContentsMargins(0, 0, 0, 0)
        display_order = ("dignity", "avasthas", "houses", "nakshatras", "d9",
                         "shayanadi", "retinue", "cards", "human_design")
        for key in display_order:
            group = facts.GROUPS_BY_KEY[key]
            chip = kit.Chip(group.label, checkable=True, tooltip=chip_tooltip(group.key, 0))
            chip.toggled.connect(self._on_chip)
            self.chips[group.key] = chip
            self._chips_lay.addWidget(chip)
        self._chips_lay.addStretch(1)
        self.chips_strip = QScrollArea()
        self.chips_strip.setFrameShape(QFrame.NoFrame)
        self.chips_strip.setWidgetResizable(True)
        self.chips_strip.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.chips_strip.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.chips_strip.setWidget(chips_row)

        # Wraps at narrow widths (review r6: phone width).
        self.top_line = QWidget()
        top = kit.FlowLayout(self.top_line, m.grp_gap, round(4 * m.fs))
        self._top = top
        for w in (self.count_label, self.of_label, self.sort_caption, sort_combo,
                  self.reverse_cluster, self.group_caption, group_combo,
                  self.placements_cluster):
            top.addWidget(w)
        lay = QVBoxLayout(self)
        lay.addWidget(self.top_line)
        lay.addWidget(self.chips_strip)
        self._sync_placements()
        self.set_count(0, 0, False)
        self.refresh_metrics()

    # ------------------------------------------------------------ signals
    def _on_reverse(self, on: bool) -> None:
        self.reverse.set_lit(on)
        self.reverse_toggled.emit(on)

    def _on_placements(self, all_: bool) -> None:
        changed = all_ != self._all
        self._all = all_
        self._sync_placements()
        if changed:
            self.placements_changed.emit(all_)

    def _on_chip(self, _on: bool) -> None:
        self.groups_changed.emit(self.groups())

    # -------------------------------------------------------------- state
    def groups(self) -> tuple[str, ...]:
        return tuple(k for k in GROUP_KEYS if self.chips[k].isChecked())

    def all_placements(self) -> bool:
        return self._all

    def is_reversed(self) -> bool:
        return self.reverse.isChecked()

    def set_reverse(self, on: bool) -> None:
        self.reverse.blockSignals(True)
        self.reverse.setChecked(on)
        self.reverse.blockSignals(False)
        self.reverse.set_lit(on)

    def set_columns(self, all_placements: bool, groups) -> None:
        """Show the saved choices without emitting."""
        self._all = bool(all_placements)
        self._sync_placements()
        wanted = set(normalise_groups(groups))
        for key, chip in self.chips.items():
            chip.blockSignals(True)
            chip.setChecked(key in wanted)
            chip.blockSignals(False)
            chip.update()

    def _sync_placements(self) -> None:
        self.place3.set_lit(not self._all)
        self.place_all.set_lit(self._all)
        self.placements_cluster.notify_state_changed()

    def set_group_dots(self, missing: Mapping[str, int]) -> None:
        """``{group: entries missing}``: amber dot and tooltip when > 0."""
        for key, chip in self.chips.items():
            n = int(missing.get(key, 0))
            chip.set_dot("amber" if n > 0 else "")
            chip.setToolTip(chip_tooltip(key, n))

    def set_count(self, shown: int, of: int, partial: bool = False) -> None:
        self._count = (shown, of, partial)
        charts = "chart" if shown == 1 else "charts"
        self.count_label.setText(f"{shown:,} {charts}")
        tail = f"of {of:,}"
        self.of_label.setText(tail + " (partial)" if partial else tail)

    def count_text(self) -> str:
        return count_text(*self._count)

    def set_tier(self, tier: int) -> None:
        """T3 and narrower drop the SORT / GROUP captions (mockup)."""
        self._tier = tier
        captions = tier < responsive.T3
        self.sort_caption.setVisible(captions)
        self.group_caption.setVisible(captions)
        self.chips_strip.setHorizontalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff if tier == responsive.T0 else Qt.ScrollBarAsNeeded
        )
        self._fit_strip()

    # ------------------------------------------------------- theme, fonts
    def _fit_strip(self) -> None:
        h = round(26 * kit.area_fs("info_text"))
        if self.chips_strip.horizontalScrollBarPolicy() != Qt.ScrollBarAlwaysOff:
            h += self.chips_strip.horizontalScrollBar().sizeHint().height()
        self.chips_strip.setFixedHeight(h)

    def refresh_metrics(self) -> None:
        m = kit.metrics()
        self._m = m
        for cluster in (self.reverse_cluster, self.placements_cluster):
            cluster.set_metrics(m)
        fs = kit.area_fs("info_text")
        self._chips_lay.setSpacing(round(5 * fs))
        for chip in self.chips.values():
            chip.refresh_metrics()
        self._top.set_spacing(m.grp_gap, round(4 * m.fs))
        self.layout().setContentsMargins(round(14 * m.fs), round(6 * m.fs),
                                         round(14 * m.fs), round(4 * m.fs))
        self.layout().setSpacing(round(4 * m.fs))
        self.set_tier(self._tier)
        self.refresh_theme()

    def refresh_theme(self) -> None:
        t = kit.tokens()
        self.count_label.setStyleSheet(
            f"color: {t['primary_text'].name()}; font-size: {scaled_area_px('table_headers') + 1}px;"
            " font-weight: 600; background: transparent;"
        )
        self.of_label.setStyleSheet(
            f"color: {t['muted'].name()}; font-size: {scaled_area_px('table_headers')}px;"
            " background: transparent;"
        )
        self.chips_strip.setStyleSheet("QScrollArea { background: transparent; }")
        self.chips_strip.widget().setStyleSheet("background: transparent;")
        for caption in (self.sort_caption, self.group_caption):
            caption.refresh_theme()
        for combo in (self.sort_combo, self.group_combo):
            kit.restyle_combo(combo)
        for cluster in (self.reverse_cluster, self.placements_cluster):
            cluster.update()
            for b in cluster.buttons():
                b.update()
        theme = get_theme_colors()
        for chip in self.chips.values():
            # Qt styles the tooltip from its carrier's nearest stylesheet.
            # The transparent scroll-strip surface otherwise makes it black.
            chip.setStyleSheet(
                f"QToolTip {{ background-color: {theme['secondary_light']};"
                f" color: {theme['secondary_text']};"
                f" border: 1px solid {theme['secondary_dark']};"
                " border-radius: 4px; padding: 4px; }"
            )
            chip.update()
