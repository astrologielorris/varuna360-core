# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The search trail (SPEC-FIND-005 §4.3): one quiet line under the toolbar.

"All sources 7,659 charts -- Aditya Circle, Campanus -- 6 matched" and the
search's duration at the right; a state line (§3.7 states) replaces the
sentence while it lasts ("No index yet", "The index is busy, retrying").
A state may carry one action (the partial state's "COMPUTE (about T)"):
``set_state(text, tone, action_label)``; a click emits ``action_clicked``."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from core.chart_search.search import Sources
from panels.find_chart import kit
from ui.qt_theme import scaled_area_px

SOURCE_TEXT = {
    Sources.ALL: "All sources",
    Sources.LOADED: "Loaded charts",
    Sources.FOLDERS: "Ticked folders",
}

#: State tones: the token each colours the text with.
NORMAL = ""
WARN = "warn"
ERROR = "error"


def trail_text(sources: Sources, candidates: int, system_text: str, matched: int,
               easy: bool) -> str:
    # Counts already appear beside the results and sources in the toolbar.
    # Keep the effective zodiac visible: Advanced may have a pinned system.
    return system_text


class Trail(QWidget):
    action_clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setMinimumWidth(0)
        self.label.setObjectName("fc_trail")
        self.duration = QLabel()
        self.duration.hide()
        self.duration.setObjectName("fc_trail_ms")
        lay = QHBoxLayout(self)
        self._lay = lay
        self._apply_metrics()
        self.action = QPushButton()
        self.action.setObjectName("fc_trail_action")
        self.action.setFlat(True)
        self.action.setCursor(Qt.CursorShape.PointingHandCursor)
        self.action.clicked.connect(self.action_clicked)
        self.action.hide()
        lay.addWidget(self.label, 1)
        lay.addWidget(self.action)
        lay.addWidget(self.duration)
        self._tone = NORMAL
        self.refresh_theme()

    def set_search(self, text: str, ms: float | None) -> None:
        self._tone = NORMAL
        self.label.setText(text)
        self.action.hide()
        self.duration.setText(f"{ms:.0f} ms" if ms is not None else "")
        self.label.setToolTip(f"Search: {ms:.0f} ms" if ms is not None else "")
        self.refresh_theme()

    def set_state(self, text: str, tone: str = NORMAL, action_label: str | None = None) -> None:
        self._tone = tone
        self.label.setText(text)
        self.action.setText(action_label or "")
        self.action.setVisible(bool(action_label))
        self.duration.setText("")
        self.refresh_theme()

    def text(self) -> str:
        return self.label.text()

    def _apply_metrics(self) -> None:
        m = kit.metrics()
        self._lay.setContentsMargins(m.side_pad, 0, m.side_pad, 0)
        self._lay.setSpacing(m.grp_gap)

    def refresh_metrics(self) -> None:
        """Margins and text size for a new scale (review r5 #9)."""
        self._apply_metrics()
        self.refresh_theme()

    def refresh_theme(self) -> None:
        t = kit.tokens()
        if self._tone == ERROR:
            color = t["red"]
        elif self._tone == WARN:
            color = t["gold"]
        else:
            color = t["secondary_text"]
        px = scaled_area_px("status")
        css = f"color: {color.name()}; font-size: {px}px;"
        self.label.setStyleSheet(css)
        self.duration.setStyleSheet(f"color: {t['secondary_text'].name()}; font-size: {px}px;")
        self.action.setStyleSheet(
            f"QPushButton {{ color: {t['primary'].name()}; background: transparent; "
            f"border: none; padding: 0 4px; font-size: {px}px; font-weight: bold; }}"
            f"QPushButton:hover {{ text-decoration: underline; }}"
        )
