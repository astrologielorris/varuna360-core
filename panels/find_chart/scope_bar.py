# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The Advanced scope bar (SPEC-FIND-005 §4.4; design.md §4.2 "Scope").

SOURCES: ALL | LOADED | FOLDERS and the tick "Include transits, events,
trials" (birth charts only unless ticked). Same ``sources()`` / ``kinds()``
API as before FIND-005; ``buttons[source]`` stays a checkable button."""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QButtonGroup, QWidget

from core.chart_search.search import Sources
from core.chart_search.sources import EntryKind
from panels.find_chart import kit

SOURCE_LABELS: Mapping[Sources, str] = {
    Sources.ALL: "ALL",
    Sources.LOADED: "LOADED",
    Sources.FOLDERS: "FOLDERS",
}
SOURCE_TIPS: Mapping[Sources, str] = {
    Sources.ALL: (
        "Every chart in the index and every chart loaded in any profile, "
        "less the folders unticked in the Library"
    ),
    Sources.LOADED: "Charts loaded in any profile",
    Sources.FOLDERS: "The folders ticked in the Library",
}


class ScopeBar(QWidget):
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        m = kit.metrics()
        # Wraps at narrow widths (review r5 #4): its minimum is its widest
        # part, never the whole line.
        layout = kit.FlowLayout(self, m.grp_gap, round(4 * m.fs))
        self._flow = layout
        self.caption = kit.SectionHeader("Sources")
        layout.addWidget(self.caption)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[Sources, kit.KitSegment] = {}
        for source, label in SOURCE_LABELS.items():
            button = kit.KitSegment(
                "src_" + source.value, label, m, checkable=True, tooltip=SOURCE_TIPS[source]
            )
            self.group.addButton(button)
            self.buttons[source] = button
        self.cluster = kit.kit_cluster(list(self.buttons.values()), m)
        layout.addWidget(self.cluster)
        self.buttons[Sources.ALL].setChecked(True)
        self._sync_lit()
        self.group.buttonToggled.connect(self._on_toggled)
        self.kinds_check = kit.KitCheckBox(
            "Include transits, events, trials",
            "Birth charts only unless ticked: Now and dasha charts, eclipses and "
            "lunar charts, birth-time-finder candidates",
        )
        self.kinds_check.toggled.connect(lambda _on: self.changed.emit())
        layout.addWidget(self.kinds_check)

    def sources(self) -> Sources:
        for source, button in self.buttons.items():
            if button.isChecked():
                return source
        return Sources.ALL

    def kinds(self) -> frozenset[EntryKind]:
        if self.kinds_check.isChecked():
            return frozenset(EntryKind)
        return frozenset({EntryKind.BIRTH})

    def _sync_lit(self) -> None:
        for button in self.buttons.values():
            button.set_lit(button.isChecked())
        self.cluster.notify_state_changed()

    def _on_toggled(self, _button, checked: bool) -> None:
        self._sync_lit()
        if checked:  # one signal per switch, not two
            self.changed.emit()

    def refresh_style(self) -> None:
        m = kit.metrics()
        self.cluster.set_metrics(m)
        self._flow.set_spacing(m.grp_gap, round(4 * m.fs))
        self.caption.refresh_theme()
        self.kinds_check.updateGeometry()
        self.kinds_check.update()
