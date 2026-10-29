# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""RATE AND SORT, the Library sheet section (SPEC-LIB-002 §4).

The widgets only; ``rate_sort_host.RateSortController`` holds the visit, the
writes and the workers. Constellation Desk's layout in every theme (D-2);
Night Orbit's session ring, WHY THIS GUESS evidence and keyboard keys.

From the top: the "Search Web saves here" path, the summary (``SessionRing``
and the counts), the reason line (Kala folder, no index), the chart card
(name, birth line, zone badge, WHY THIS GUESS, ``RatePlane``, four
``RatingRow``, the read-outs, SKIP / UNDO / CONFIRM AND NEXT, the key hint),
the visit-done line with RATE 5 MORE, READY TO FILE, SORTING PROFILE, the
AI suggestions slot (the existing Sort with AI section), LIBRARY STATS.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QSizePolicy,
                               QVBoxLayout, QWidget)

from core.library import rating
from panels.find_chart import kit, zone_tones
from panels.find_chart.rate_plane import RatePlane
from panels.find_chart.rate_rows import RatingRow
from panels.find_chart.rate_stats import SessionRing, ZoneTiles
from panels.find_chart.sheet_parts import _SheetButton, _hexa, _label, _px, _style_label

SECTION_TITLE = "Rate and sort"
SUBTITLE = "Search Web saves here"
KEYS_HINT = ("↑ ↓ row · ← → or 0 to 5 set (1 to 7 on the first row) · Space accept guess · "
             "Enter confirm · S skip · Z undo")
WHY_LINES = 4
FILE_ROWS = 12
DONE_TEXT = "All rated for this visit."
UP_TO_DATE = "Your library is up to date. New downloads will wait here."


def _row(*widgets, stretch_after=True) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setContentsMargins(0, 0, 0, 0)
    for w in widgets:
        lay.addWidget(w)
    if stretch_after:
        lay.addStretch(1)
    return lay


class _FileRow(QWidget):
    """One READY TO FILE row: zone dot, "Downloads/<file> → <folder>/", select."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.dot = QLabel()
        self.text = _label(wrap=False)
        self.text.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.combo = QComboBox()
        kit.restyle_combo(self.combo)
        self.zone = None
        self.filename = ""
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.dot)
        lay.addWidget(self.text, 1)
        lay.addWidget(self.combo)
        self.combo.currentTextChanged.connect(self._sync_text)

    def set_move(self, filename: str, zone, folders, default: str) -> None:
        self.filename, self.zone = filename, zone
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItems(list(folders))
        self.combo.setCurrentText(default)
        self.combo.blockSignals(False)
        self._sync_text()
        self.refresh_theme()

    def folder(self) -> str:
        return self.combo.currentText()

    def _sync_text(self, *_a) -> None:
        self.text.setText(f"Downloads/{self.filename} → {self.folder()}/")
        self.text.setToolTip(self.text.text())

    def refresh_theme(self) -> None:
        d = max(6, round(_px("info_text") * 0.6))
        self.dot.setFixedSize(d, d)
        self.dot.setStyleSheet(f"background: {zone_tones.tone(self.zone).name()};"
                               f" border-radius: {d // 2}px;")
        _style_label(self.text, "primary")
        kit.restyle_combo(self.combo)


class RateSortSection(QWidget):
    """See the module docstring. Every part is a public attribute the
    controller fills; nothing here decides."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.header = kit.SectionHeader(SECTION_TITLE)
        self.subtitle = _label(SUBTITLE, wrap=False)
        self.path_label = _label(wrap=False)
        self.path_label.setObjectName("fc_rate_path")
        self.path_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

        # summary
        self.ring = SessionRing()
        self.waiting_dot = QLabel()
        self.waiting_label = _label(wrap=False)
        self.progress_label = _label()
        summary_text = QVBoxLayout()
        summary_text.setContentsMargins(0, 0, 0, 0)
        summary_text.addLayout(_row(self.waiting_dot, self.waiting_label))
        summary_text.addWidget(self.progress_label)
        summary_text.addStretch(1)
        self.summary = QHBoxLayout()
        self.summary.setContentsMargins(0, 0, 0, 0)
        self.summary.addWidget(self.ring)
        self.summary.addLayout(summary_text, 1)
        self.reason_label = _label()

        # the card
        self.card = QFrame()
        self.card.setObjectName("fc_rate_card")
        self.card.setFocusPolicy(Qt.StrongFocus)
        self.name_label = _label(wrap=False)
        self.badge = QLabel()
        self.birth_label = _label(wrap=False)
        self.why_header = _label("WHY THIS GUESS", wrap=False)
        self.why_lines = [_label() for _ in range(WHY_LINES)]
        self.plane = RatePlane()
        self.rows = {r: RatingRow(r) for r in rating.ROWS}
        self.readout_label = _label(wrap=False)
        self.skip_button = _SheetButton("SKIP")
        self.undo_button = _SheetButton("UNDO")
        self.confirm_button = _SheetButton("CONFIRM AND NEXT", "gold")
        self.convert_button = _SheetButton("CONVERT AND RATE", "gold")
        self.keys_label = _label(KEYS_HINT)
        self.card_message = _label()
        card = QVBoxLayout(self.card)
        card.addLayout(_row(self.name_label, stretch_after=False))
        self.name_row = card.itemAt(0).layout()
        self.name_row.addStretch(1)
        self.name_row.addWidget(self.badge)
        card.addWidget(self.birth_label)
        card.addWidget(self.why_header)
        for w in self.why_lines:
            card.addWidget(w)
        card.addWidget(self.plane)
        for r in self.rows.values():
            card.addWidget(r)
        card.addWidget(self.readout_label)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.addWidget(self.skip_button)
        actions.addWidget(self.undo_button)
        actions.addStretch(1)
        actions.addWidget(self.convert_button)
        actions.addWidget(self.confirm_button)
        card.addLayout(actions)
        card.addWidget(self.keys_label)
        card.addWidget(self.card_message)

        self.done_label = _label()
        self.more_button = _SheetButton("RATE 5 MORE")
        self.undo_done_button = _SheetButton("UNDO")
        self.done_row = QWidget()
        self.done_row.setLayout(_row(self.more_button, self.undo_done_button))

        # READY TO FILE
        self.file_header = kit.SectionHeader("Ready to file")
        self.preview_button = _SheetButton("PREVIEW MOVES")
        self.file_note = _label()
        self.file_rows = [_FileRow() for _ in range(FILE_ROWS)]
        self.file_more = _label(wrap=False)
        self.preview_text = _label()
        self.file_button = _SheetButton("FILE CHARTS", "gold")
        self.file_result = _label()
        self.file_undo_button = _SheetButton("UNDO")
        self.sort_log_button = _SheetButton("SORT LOG")
        self.file_box = QFrame()
        self.file_box.setObjectName("fc_rate_file")
        fl = QVBoxLayout(self.file_box)
        head = _row(self.file_header, stretch_after=True)
        head.addWidget(self.preview_button)
        fl.addLayout(head)
        fl.addWidget(self.file_note)
        for r in self.file_rows:
            fl.addWidget(r)
        fl.addWidget(self.file_more)
        fl.addWidget(self.preview_text)
        fl.addLayout(_row(self.file_button))
        fl.addWidget(self.file_result)
        fl.addLayout(_row(self.file_undo_button, self.sort_log_button))

        # SORTING PROFILE
        self.profile_box = QFrame()
        self.profile_box.setObjectName("fc_rate_profile")
        self.profile_header = kit.SectionHeader("Sorting profile")
        self.profile_aside = _label("fills the guesses", wrap=False)
        self.profile_name = _label(wrap=False)
        self.profile_writer = _label()
        self.profile_last = _label()
        self.run_button = _SheetButton("RUN NOW", "gold")
        self.rules_button = _SheetButton("SHOW RULES")
        self.rules_text = _label()
        pl = QVBoxLayout(self.profile_box)
        head = _row(self.profile_header)
        head.addWidget(self.profile_aside)
        pl.addLayout(head)
        top = _row(self.profile_name)
        top.addWidget(self.run_button)
        pl.addLayout(top)
        pl.addWidget(self.profile_writer)
        pl.addWidget(self.profile_last)
        pl.addLayout(_row(self.rules_button))
        pl.addWidget(self.rules_text)

        # AI suggestions (the Sort with AI section, placed by the host)
        self.ai_slot = QVBoxLayout()
        self.ai_slot.setContentsMargins(0, 0, 0, 0)

        # LIBRARY STATS
        self.stats_header = kit.SectionHeader("Library stats")
        self.stats_aside = _label("computed locally, no AI", wrap=False)
        self.tiles = ZoneTiles()
        self.stats_line = _label()
        self.chtk_label = _label(wrap=False)
        self.convert_all_button = _SheetButton("CONVERT TO TOML")
        self.stats_message = _label()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        head = _row(self.header, self.subtitle)
        lay.addLayout(head)
        lay.addWidget(self.path_label)
        lay.addLayout(self.summary)
        lay.addWidget(self.reason_label)
        lay.addWidget(self.card)
        lay.addWidget(self.done_label)
        lay.addWidget(self.done_row)
        lay.addWidget(self.file_box)
        lay.addWidget(self.profile_box)
        lay.addLayout(self.ai_slot)
        stats_head = _row(self.stats_header)
        stats_head.addWidget(self.stats_aside)
        lay.addLayout(stats_head)
        lay.addWidget(self.tiles)
        lay.addWidget(self.stats_line)
        lay.addLayout(_row(self.chtk_label, self.convert_all_button))
        lay.addWidget(self.stats_message)
        lay.addStretch(1)
        self._zone = None
        self._badge_guess = True
        self._ai_widget = None
        for w in (self.file_undo_button, self.sort_log_button, self.rules_text,
                  self.convert_all_button, self.chtk_label, self.done_row):
            w.hide()
        self.refresh_theme()

    # ------------------------------------------------------------ small setters
    def set_badge(self, zone, guess: bool) -> None:
        self._zone, self._badge_guess = zone, guess
        self.badge.setText((f"{zone} guess" if guess else zone) if zone else "")
        self.badge.setVisible(bool(zone))
        self._style_badge()

    def set_ai_widget(self, widget: QWidget) -> None:
        self.ai_slot.addWidget(widget)
        self._ai_widget = widget

    def set_waiting(self, n: int, unrated: int = 0) -> None:
        """"N charts waiting to be rated" counts the queue's first three
        tiers (§4.3); with none, the unrated rest is named instead."""
        self._waiting = n
        if n or not unrated:
            text = f"{n:,} chart{'' if n == 1 else 's'} waiting to be rated"
        else:
            text = f"{unrated:,} chart{'' if unrated == 1 else 's'} not rated yet"
        self.waiting_label.setText(text)
        self._style_dot()

    # ------------------------------------------------------------ style
    def _style_dot(self) -> None:
        n = getattr(self, "_waiting", 0)
        t = kit.tokens()
        d = max(6, round(_px("info_text") * 0.6))
        self.waiting_dot.setFixedSize(d, d)
        self.waiting_dot.setStyleSheet(
            f"background: {(t['gold'] if n else t['muted']).name()}; border-radius: {d // 2}px;")

    def _style_badge(self) -> None:
        c = zone_tones.tone(self._zone)
        border = "dashed" if self._badge_guess else "solid"
        fill = "transparent" if self._badge_guess else zone_tones.cell(self._zone).name()
        self.badge.setStyleSheet(
            f"color: {c.name()}; background: {fill}; border: 1px {border} {c.name()};"
            f" border-radius: 9px; padding: 1px 7px; font-size: {round(_px('info_text') * .85)}px;"
            f" font-weight: 700; font-style: {'italic' if self._badge_guess else 'normal'};")

    def refresh_theme(self) -> None:
        t = kit.tokens()
        for h in (self.header, self.file_header, self.profile_header, self.stats_header):
            h.refresh_theme()
        well = (f"color: {t['secondary_text'].name()}; background: {_hexa(t['well'])};"
                f" border: 1px solid {_hexa(t['well_line'])}; border-radius: 6px;"
                f" padding: 4px 8px; font-size: {_px('info_text')}px;")
        self.path_label.setStyleSheet(well)
        for w in (self.subtitle, self.profile_aside, self.stats_aside, self.keys_label,
                  self.progress_label, self.birth_label, self.file_note, self.file_more,
                  self.profile_last, self.rules_text, self.stats_line, self.readout_label):
            _style_label(w, "muted")
        for w in (self.waiting_label, self.profile_name):
            _style_label(w, "primary", bold=True)
        for w in (self.reason_label, self.done_label, self.card_message, self.preview_text,
                  self.file_result, self.profile_writer, self.chtk_label, self.stats_message):
            _style_label(w, "secondary")
        _style_label(self.why_header, "secondary", bold=True)
        for w in self.why_lines:
            _style_label(w, "secondary")
        self.name_label.setStyleSheet(
            f"color: {t['primary_text'].name()}; background: transparent;"
            f" font-size: {round(_px('info_text') * 1.3)}px; font-weight: 700;")
        box = (f"background: {_hexa(t['ctl'])}; border: 1px solid {_hexa(t['hair_soft'])};"
               " border-radius: 8px;")
        for name, frame in (("fc_rate_card", self.card), ("fc_rate_file", self.file_box),
                            ("fc_rate_profile", self.profile_box)):
            frame.setStyleSheet(f"QFrame#{name} {{ {box} }}")
        for b in (self.skip_button, self.undo_button, self.confirm_button, self.convert_button,
                  self.more_button, self.undo_done_button, self.preview_button,
                  self.file_button, self.file_undo_button, self.sort_log_button,
                  self.run_button, self.rules_button, self.convert_all_button):
            b.refresh_theme()
        for r in self.file_rows:
            r.refresh_theme()
        self._style_badge()
        self._style_dot()
        for w in (self.plane, self.ring, *self.rows.values()):
            w.update()
        self.tiles.refresh_metrics()
        if self._ai_widget is not None and hasattr(self._ai_widget, "refresh_theme"):
            self._ai_widget.refresh_theme()

    def refresh_metrics(self) -> None:
        fs = kit.area_fs("info_text")
        m = round(8 * fs)
        for frame in (self.card, self.file_box, self.profile_box):
            frame.layout().setContentsMargins(m, m, m, m)
            frame.layout().setSpacing(round(4 * fs))
        self.layout().setSpacing(round(6 * fs))
        self.plane.refresh_metrics()
        self.ring.refresh_metrics()
        for r in self.rows.values():
            r.refresh_metrics()
        self.refresh_theme()
        if self._ai_widget is not None and hasattr(self._ai_widget, "refresh_metrics"):
            self._ai_widget.refresh_metrics()
        self.updateGeometry()


__all__ = ["RateSortSection"]
