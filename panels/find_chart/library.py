# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The Library sheet's content (SPEC-FIND-005 §3.7, §4.8 T4, §4.9 slot).

``LibraryContent`` is a QWidget the host places inside a ``kit.Sheet``
titled "Library" (full page at T4: ``Sheet.set_full_page``). It scrolls and
holds, in order:

- DATABASE: the database path (elided from the left, full path in the
  tooltip), SHOW LOCATION, EXPORT, IMPORT;
- CHART FOLDERS ("checked = searched"): three slots (tick, path field,
  BROWSE, x), then "Loaded charts (no file)";
- RATE AND SORT (SPEC-LIB-002, the slot once called UNSORTED DOWNLOADS): an
  empty slot, hidden until ``set_unsorted_section``;
- CHECK CHARTS: an empty slot, hidden until ``set_check_section``;
- INDEX: "7,659 charts in the index", REBUILD INDEX and its menu (Refresh
  index (keep cache), Full rebuild (clear cache));
- COVERAGE, folded to one line (SPEC-LIB-002 §4.12: state dot, "5 of 7
  computed", SHOW DETAILS, the state in ``ui.find_chart_coverage_open``);
  opened, one row per ``Coverage`` item (ring, label, "5,120 of 5,720
  birth moments", COMPUTE n / RETRY n / RECOMPUTE n or DONE, the elsewhere
  explanation in the tooltip), COMPUTE EVERYTHING, and the CPU share line
  with its "change in Settings" link.

It only presents and emits; the host keeps every policy (consent, scans,
computes: INV-2). Signals:

    browse_requested(int)          slot index
    remove_requested(int)          slot index (the x)
    folders_edited()               a path field's editingFinished
    checks_changed()               a folder tick or the fileless tick toggled
    show_location_requested()  export_requested()  import_requested()
    rebuild_requested()  refresh_requested()  full_rebuild_requested()
    coverage_action_requested(str extractor_id, str kind)
                                   kind in {"compute", "retry", "recompute"}
    compute_everything_requested()
    settings_requested()

Methods: ``set_database(path_text)``, ``set_folders(paths, checked)``,
``set_fileless(checked)``, ``set_index_count(n)``, ``set_index_text(text,
tone)``, ``set_coverage(snapshot)``, ``set_running(extractor_id | None)``,
``set_cpu_percent(p)``, ``set_busy(bool)``, ``set_unsorted_section(widget)``,
``refresh_theme()``, ``refresh_metrics()``. The folder widgets are the host's
folder entries: ``folder_fields()`` (QLineEdit), ``folder_checks()``
(checkable ``KitCheckBox``: ``isChecked``/``setChecked``/``toggled``, no
``stateChanged``), ``fileless_check()``.

Wiring sketch for the host::

    lib = LibraryContent(); sheet.content_layout.addWidget(lib)
    self.folder_entries = lib.folder_fields()
    self.folder_checkboxes = lib.folder_checks()
    self.fileless_checkbox = lib.fileless_check()
    lib.browse_requested.connect(lambda i: self._browse_folder(self.folder_entries[i]))
    lib.remove_requested.connect(<clear slot i, then _on_folder_list_edited>)
    lib.folders_edited.connect(self._on_folder_list_edited)
    lib.checks_changed.connect(self._on_scope_changed)  # quiet (INV-3)
    lib.rebuild_requested.connect(self._rebuild_index)   # consented scan
    lib.coverage_action_requested.connect(<coverage_moments + compute.plan>)
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from apps.widgets.action_bar.bar_types import BarMetrics, Role
from core.chart_search.search import Coverage
from core.settings_registry import default as registry_default
from managers.settings_manager import get_settings
from panels.find_chart import kit, states
from ui.qt_theme import scaled_area_px

FOLDER_SLOTS = 3
COVERAGE_OPEN_KEY = "ui.find_chart_coverage_open"
FILELESS_LABEL = "Loaded charts (no file)"
FOLDER_PLACEHOLDER = "Browse for folder..."


def button_metrics() -> BarMetrics:
    """Sheet buttons size from the ``buttons`` font area (INV-10)."""
    return BarMetrics(kit.area_fs("buttons"))


def _tone_color(t: dict, tone: str) -> QColor:
    if tone == states.ERROR:
        return t["red"]
    if tone == states.WARN:
        return t["gold"]
    return t["secondary_text"]


class StaleRing(kit.CoverageRing):
    """A ``CoverageRing`` with the stale dot (§3.7 "stale rows"); size in
    px x the ``area`` font scale, re-read by ``refresh_metrics``."""

    def __init__(self, size: int = 14, area: str = "info_text", parent=None):
        super().__init__(size, parent)
        self._base = size
        self._area = area
        self._stale = False
        self.refresh_metrics()

    def set_coverage(self, fraction: float, *, empty: bool, stale: bool,
                     running: bool = False) -> None:
        self._stale = stale
        if empty:
            state = "empty"
        elif running:
            state = "run"
        else:
            state = "ok"
        self.set_value(fraction, state)

    @property
    def state(self) -> str:
        return self._state

    @property
    def fraction(self) -> float:
        return self._fraction

    @property
    def stale(self) -> bool:
        return self._stale

    def refresh_metrics(self) -> None:
        d = round(self._base * kit.area_fs(self._area))
        self.setFixedSize(d, d)

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._stale:
            return
        t = kit.tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        d = max(3.0, self.width() * 0.36)
        p.setPen(Qt.NoPen)
        p.setBrush(t["gold"])
        p.drawEllipse(QRectF(self.width() - d, 0, d, d))
        p.end()


class ElidedLabel(QLabel):
    """A label that elides its full text to fit (left for paths); the full
    text stays in ``full_text()`` and the tooltip."""

    def __init__(self, text: str = "", mode=Qt.ElideLeft, parent=None):
        super().__init__(parent)
        self._full = ""
        self._mode = mode
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(24)
        self.set_full_text(text)

    def set_full_text(self, text: str, tooltip: str | None = None) -> None:
        self._full = text
        self.setToolTip(text if tooltip is None else tooltip)
        self._elide()

    def full_text(self) -> str:
        return self._full

    def _elide(self) -> None:
        width = max(0, self.contentsRect().width() - 2)
        self.setText(self.fontMetrics().elidedText(self._full, self._mode, width)
                     if width > 0 else self._full)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._elide()

    def refresh(self) -> None:
        self.ensurePolished()
        self._elide()


class StateDot(QWidget):
    """The 6 px state dot before a status line (green, gold, red)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tone = states.NORMAL
        self.refresh_metrics()

    def refresh_metrics(self) -> None:
        d = round(6 * kit.area_fs("status"))
        self.setFixedSize(d, d)

    def paintEvent(self, _event):
        t = kit.tokens()
        color = {states.WARN: t["gold"], states.ERROR: t["red"]}.get(self.tone, t["green"])
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawEllipse(QRectF(QPointF(0, 0), QPointF(self.width(), self.height())))
        p.end()


class _Section(QWidget):
    """A Library section: uppercase header, an optional muted aside on its
    right, and a body."""

    def __init__(self, title: str, aside: str = "", parent=None):
        super().__init__(parent)
        self.header = kit.SectionHeader(title)
        self.aside = QLabel(aside)
        self.aside.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.addWidget(self.header, 1)
        head.addWidget(self.aside)
        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(head)
        lay.addLayout(self.body)
        self.refresh_theme()

    def refresh_theme(self) -> None:
        t = kit.tokens()
        fs = kit.area_fs("info_text")
        self.body.setSpacing(round(6 * fs))
        self.layout().setSpacing(round(7 * fs))
        self.header.refresh_theme()
        self.aside.setStyleSheet(
            f"color: {t['muted'].name()}; font-size: {scaled_area_px('info_text')}px;"
            " background: transparent;"
        )


class _CoverageRow:
    """The widgets of one coverage row inside the grid."""

    def __init__(self, owner: "LibraryContent", extractor_id: str):
        self.extractor_id = extractor_id
        m = button_metrics()
        self.ring = StaleRing(14, "info_text")
        self.label = QLabel()
        self.count = QLabel()
        self.count.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.actions = QWidget()
        lay = QHBoxLayout(self.actions)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(round(4 * m.fs))
        self.buttons: dict[str, kit.KitSegment] = {}
        for kind, word, _attr in states.ACTION_KINDS:
            button = kit.KitSegment(f"cov_{kind}_{extractor_id}", word, m,
                                    tooltip=f"{word.capitalize()} these charts")
            button.clicked.connect(
                lambda _c=False, k=kind: owner.coverage_action_requested.emit(
                    self.extractor_id, k
                )
            )
            button.hide()
            lay.addWidget(button)
            self.buttons[kind] = button
        lay.addStretch(1)
        self.actions.hide()
        # DONE / RUNNING / "Nothing in scope" at the row's right end; the
        # buttons take their own line under the label (three do not fit
        # the 380 px sheet beside the counts).
        self.state_box = QWidget()
        state_lay = QHBoxLayout(self.state_box)
        state_lay.setContentsMargins(0, 0, 0, 0)
        self.done = QLabel("DONE")
        self.done.hide()
        state_lay.addWidget(self.done)
        self.empty = QLabel("Nothing in scope")
        self.empty.hide()
        state_lay.addWidget(self.empty)
        self.row: states.CoverageRow | None = None

    def widgets(self) -> list[QWidget]:
        """The first line's cells, in grid column order."""
        return [self.ring, self.label, self.count, self.state_box]

    def all_widgets(self) -> list[QWidget]:
        return self.widgets() + [self.actions]

    def show(self, row: states.CoverageRow, running: bool) -> None:
        self.row = row
        self.ring.set_coverage(row.fraction, empty=row.empty, stale=row.stale,
                               running=running)
        self.label.setText(row.label)
        self.count.setText(row.count_text)
        for w in self.all_widgets():
            w.setToolTip(row.tooltip)
        shown = dict(row.actions)
        self.actions.setVisible(bool(shown))
        for kind, button in self.buttons.items():
            text = shown.get(kind)
            button.setVisible(text is not None)
            if text is not None:
                button.compact_label(text)
        self.done.setText("RUNNING" if running else "DONE")
        self.done.setVisible(running or (row.done and not shown))
        self.empty.setVisible(row.empty and not running)

    def refresh_theme(self, busy: bool) -> None:
        t = kit.tokens()
        info = scaled_area_px("info_text")
        self.label.setStyleSheet(
            f"color: {t['primary_text'].name()}; font-size: {info}px; background: transparent;"
        )
        self.count.setStyleSheet(
            f"color: {t['muted'].name()}; font-size: {info}px; background: transparent;"
        )
        running = self.done.text() == "RUNNING"
        self.done.setStyleSheet(
            f"color: {(t['primary'] if running else t['green']).name()};"
            f" font-size: {scaled_area_px('buttons')}px; font-weight: 600;"
            " letter-spacing: 0.06em; background: transparent;"
        )
        self.empty.setStyleSheet(
            f"color: {t['muted'].name()}; font-size: {info}px; background: transparent;"
        )
        for button in self.buttons.values():
            button.setEnabled(not busy)
            button.update()
        self.ring.update()

    def refresh_metrics(self) -> None:
        m = button_metrics()
        self.actions.layout().setSpacing(round(4 * m.fs))
        for button in self.buttons.values():
            button.set_metrics(m)
        self.ring.refresh_metrics()

    def dispose(self) -> None:
        for w in self.all_widgets():
            w.hide()
            w.deleteLater()


class LibraryContent(QWidget):
    browse_requested = Signal(int)
    remove_requested = Signal(int)
    folders_edited = Signal()
    checks_changed = Signal()
    show_location_requested = Signal()
    export_requested = Signal()
    import_requested = Signal()
    rebuild_requested = Signal()
    refresh_requested = Signal()
    full_rebuild_requested = Signal()
    coverage_action_requested = Signal(str, str)
    compute_everything_requested = Signal()
    settings_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._busy = False
        self._running: str | None = None
        self._cpu = 40
        self._index_tone = states.NORMAL
        self._snapshot: tuple[Coverage, ...] = ()
        self._rows: dict[str, _CoverageRow] = {}
        self._unsorted: QWidget | None = None
        self._check: QWidget | None = None
        m = button_metrics()

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        kit.pin_left(self.scroll)
        self.inner = QWidget()
        self.inner.setObjectName("fc_library_inner")
        self.scroll.setWidget(self.inner)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.scroll)
        self.sections_layout = QVBoxLayout(self.inner)
        self.sections_layout.setContentsMargins(0, 0, 0, 0)

        # DATABASE
        self.database_section = _Section("Database")
        self.database_path = ElidedLabel("", Qt.ElideLeft)
        self.database_path.setObjectName("fc_library_db")
        self.show_location_button = kit.KitSegment(
            "lib_show_location", "SHOW LOCATION", m,
            tooltip="Show the index file in the file manager")
        self.export_button = kit.KitSegment("lib_export", "EXPORT", m,
                                            tooltip="Export the index to a file")
        self.import_button = kit.KitSegment("lib_import", "IMPORT", m,
                                            tooltip="Import computed results from an index file")
        self.show_location_button.clicked.connect(self.show_location_requested)
        self.export_button.clicked.connect(self.export_requested)
        self.import_button.clicked.connect(self.import_requested)
        self.database_section.body.addWidget(self.database_path)
        self.database_section.body.addLayout(self._row(
            self.show_location_button, self.export_button, self.import_button))

        # CHART FOLDERS
        self.folders_section = _Section("Chart folders", "checked = searched")
        self._fields: list[QLineEdit] = []
        self._checks: list[kit.KitCheckBox] = []
        self._browse: list[kit.KitSegment] = []
        self._remove: list[kit.IconButton] = []
        for i in range(FOLDER_SLOTS):
            self.folders_section.body.addLayout(self._folder_slot(i, m))
        self._fileless = kit.KitCheckBox(
            FILELESS_LABEL, "Charts loaded in the app that have no file on disk")
        self._fileless.setChecked(True)
        self._fileless.toggled.connect(lambda _on: self.checks_changed.emit())
        self.folders_section.body.addWidget(self._fileless)

        # UNSORTED DOWNLOADS (§4.9, its widget built elsewhere)
        self.unsorted_section = _Section("Unsorted downloads")
        self.unsorted_section.hide()

        # CHECK CHARTS (SPEC-LIB-001 §4.9, its widget built elsewhere)
        self.check_section = _Section("Check charts")
        self.check_section.hide()

        # INDEX
        self.index_section = _Section("Index")
        self.index_dot = StateDot()
        self.index_label = QLabel(states.index_count_text(0))
        self.index_label.setObjectName("fc_library_index")
        line = QHBoxLayout()
        line.setContentsMargins(0, 0, 0, 0)
        line.addWidget(self.index_dot)
        line.addWidget(self.index_label, 1)
        self.index_section.body.addLayout(line)
        self.rebuild_button = kit.KitSegment(
            "lib_rebuild", "REBUILD INDEX", m, role=Role.TINT_GREEN, icon="fc_rebuild",
            tooltip="Read the chart folders and update the index")
        self.rebuild_button.set_lit(True)
        self.rebuild_button.clicked.connect(self.rebuild_requested)
        self.index_menu_button = kit.KitSegment("lib_index_menu", "", m, icon="fc_chevr",
                                                tooltip="Index menu")
        self.index_menu = QMenu(self)
        self.refresh_action = self.index_menu.addAction("Refresh index (keep cache)")
        self.full_rebuild_action = self.index_menu.addAction("Full rebuild (clear cache)")
        self.refresh_action.triggered.connect(lambda _c=False: self.refresh_requested.emit())
        self.full_rebuild_action.triggered.connect(
            lambda _c=False: self.full_rebuild_requested.emit())
        self.index_menu_button.clicked.connect(self._popup_index_menu)
        self.index_cluster = kit.kit_cluster([self.rebuild_button, self.index_menu_button], m)
        self.index_section.body.addLayout(self._row(self.index_cluster))

        # COVERAGE, folded into one line (SPEC-LIB-002 §4.12)
        self.coverage_section = _Section("Coverage")
        self.coverage_dot = StateDot()
        self.coverage_summary = QLabel("Nothing indexed yet")
        self.coverage_summary.setObjectName("fc_library_coverage_summary")
        self.coverage_toggle = kit.KitSegment("lib_coverage_toggle", "SHOW DETAILS ›", m,
                                              tooltip="Show each domain's coverage")
        self.coverage_toggle.clicked.connect(lambda: self.set_coverage_open(
            not self.coverage_details.isVisible(), save=True))
        fold = QHBoxLayout()
        fold.setContentsMargins(0, 0, 0, 0)
        fold.addWidget(self.coverage_dot)
        fold.addWidget(self.coverage_summary, 1)
        fold.addWidget(self.coverage_toggle)
        self.coverage_section.body.addLayout(fold)
        self.coverage_details = QWidget()
        details = QVBoxLayout(self.coverage_details)
        details.setContentsMargins(0, 0, 0, 0)
        self.coverage_section.body.addWidget(self.coverage_details)
        self.coverage_grid = QGridLayout()
        self.coverage_grid.setContentsMargins(0, 0, 0, 0)
        self.coverage_grid.setColumnStretch(1, 1)
        details.addLayout(self.coverage_grid)
        self.compute_everything_button = kit.KitSegment(
            "lib_compute_all", "COMPUTE EVERYTHING", m, role=Role.PRIMARY, icon="fc_cpu",
            tooltip="Compute every domain for every chart in the index, in the background")
        self.compute_everything_button.clicked.connect(self.compute_everything_requested)
        details.addLayout(self._row(self.compute_everything_button))
        self.cpu_label = QLabel()
        self.cpu_label.setObjectName("fc_library_cpu")
        self.cpu_label.setWordWrap(True)
        self.cpu_label.setTextFormat(Qt.RichText)
        self.cpu_label.linkActivated.connect(lambda _href: self.settings_requested.emit())
        details.addWidget(self.cpu_label)
        self.set_coverage_open(bool(get_settings().get(
            COVERAGE_OPEN_KEY, registry_default(COVERAGE_OPEN_KEY))))

        for section in (self.database_section, self.folders_section, self.unsorted_section,
                        self.check_section,
                        self.index_section, self.coverage_section):
            self.sections_layout.addWidget(section)
        self.sections_layout.addStretch(1)
        self.set_cpu_percent(self._cpu)
        self.refresh_metrics()

    # ------------------------------------------------------------ building

    @staticmethod
    def _row(*widgets: QWidget) -> QHBoxLayout:
        lay = QHBoxLayout()
        lay.setContentsMargins(0, 0, 0, 0)
        for w in widgets:
            lay.addWidget(w)
        lay.addStretch(1)
        return lay

    def _folder_slot(self, i: int, m: BarMetrics) -> QHBoxLayout:
        check = kit.KitCheckBox("", f"Folder {i + 1}: checked = searched")
        check.setAccessibleName(f"Search folder {i + 1}")
        check.setChecked(True)
        check.toggled.connect(lambda _on: self.checks_changed.emit())
        field = QLineEdit()
        field.setObjectName(f"fc_library_folder_{i}")
        field.setPlaceholderText(FOLDER_PLACEHOLDER)
        field.editingFinished.connect(self.folders_edited)
        field.textChanged.connect(lambda _t, k=i: self._sync_remove(k))
        browse = kit.KitSegment(f"lib_browse_{i}", "BROWSE", m,
                                tooltip=f"Choose folder {i + 1}")
        browse.clicked.connect(lambda _c=False, k=i: self.browse_requested.emit(k))
        remove = kit.IconButton("x", "Remove folder", size=18)
        remove.clicked.connect(lambda _c=False, k=i: self.remove_requested.emit(k))
        policy = remove.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        remove.setSizePolicy(policy)
        remove.hide()
        self._checks.append(check)
        self._fields.append(field)
        self._browse.append(browse)
        self._remove.append(remove)
        lay = QHBoxLayout()
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(check)
        lay.addWidget(field, 1)
        lay.addWidget(browse)
        lay.addWidget(remove)
        return lay

    def _sync_remove(self, i: int) -> None:
        self._remove[i].setVisible(bool(self._fields[i].text().strip()))

    def _popup_index_menu(self) -> None:
        b = self.index_menu_button
        self.index_menu.popup(b.mapToGlobal(b.rect().bottomLeft()))

    # ------------------------------------------------------------ host API

    def folder_fields(self) -> list[QLineEdit]:
        return list(self._fields)

    def folder_checks(self) -> list[kit.KitCheckBox]:
        return list(self._checks)

    def fileless_check(self) -> kit.KitCheckBox:
        return self._fileless

    def browse_buttons(self) -> list[kit.KitSegment]:
        return list(self._browse)

    def remove_buttons(self) -> list[kit.IconButton]:
        return list(self._remove)

    def set_database(self, path_text: str) -> None:
        self.database_path.set_full_text(path_text)

    def set_folders(self, paths, checked) -> None:
        """Fill the slots without emitting edit or tick signals."""
        paths = list(paths)[:FOLDER_SLOTS]
        checked = list(checked)[:FOLDER_SLOTS]
        for i in range(FOLDER_SLOTS):
            field, check = self._fields[i], self._checks[i]
            field.blockSignals(True)
            check.blockSignals(True)
            field.setText(paths[i] if i < len(paths) else "")
            check.setChecked(bool(checked[i]) if i < len(checked) else True)
            field.blockSignals(False)
            check.blockSignals(False)
            check.update()
            self._sync_remove(i)

    def set_fileless(self, checked: bool) -> None:
        self._fileless.blockSignals(True)
        self._fileless.setChecked(checked)
        self._fileless.blockSignals(False)
        self._fileless.update()

    def set_index_count(self, n: int) -> None:
        self.set_index_text(states.index_count_text(n),
                            states.NORMAL if n > 0 else states.WARN)

    def set_index_text(self, text: str, tone: str = states.NORMAL) -> None:
        self._index_tone = tone
        self.index_label.setText(text)
        self.index_dot.tone = tone
        self._style_index()

    def set_coverage(self, snapshot: tuple[Coverage, ...]) -> None:
        snapshot = tuple(snapshot)
        self._snapshot = snapshot
        ids = [c.extractor_id for c in snapshot]
        if ids != list(self._rows):
            self._rebuild_rows(ids)
        for c in snapshot:
            self._rows[c.extractor_id].show(states.coverage_row(c),
                                            running=c.extractor_id == self._running)
        n = states.scope_moments(snapshot)
        self.coverage_section.aside.setText(
            f"{n:,} birth {'moment' if n == 1 else 'moments'}" if snapshot else "")
        self.coverage_summary.setText(self.coverage_summary_text())
        self.coverage_dot.tone = states.NORMAL if self.coverage_complete() else states.WARN
        self.coverage_dot.update()
        self._style_rows()

    def coverage_summary_text(self) -> str:
        """The folded line: "5 of 7 computed"."""
        if not self._snapshot:
            return "Nothing indexed yet"
        done = sum(states.complete(c) for c in self._snapshot)
        return f"{done} of {len(self._snapshot)} computed"

    def coverage_complete(self) -> bool:
        return bool(self._snapshot) and all(states.complete(c) for c in self._snapshot)

    def set_coverage_open(self, on: bool, *, save: bool = False) -> None:
        """Open or fold the coverage details (``ui.find_chart_coverage_open``)."""
        self.coverage_details.setVisible(bool(on))
        self.coverage_toggle.setText("HIDE DETAILS ‹" if on else "SHOW DETAILS ›")
        if save:
            get_settings().set(COVERAGE_OPEN_KEY, bool(on))

    def _rebuild_rows(self, ids: list[str]) -> None:
        for row in self._rows.values():
            for w in row.all_widgets():
                self.coverage_grid.removeWidget(w)
            row.dispose()
        self._rows = {}
        for r, eid in enumerate(ids):
            row = _CoverageRow(self, eid)
            for col, w in enumerate(row.widgets()):
                align = Qt.AlignRight if col >= 2 else Qt.Alignment()
                self.coverage_grid.addWidget(w, 2 * r, col, align)
            self.coverage_grid.addWidget(row.actions, 2 * r + 1, 1, 1, 3)
            self._rows[eid] = row

    def coverage_rows(self) -> dict[str, _CoverageRow]:
        return dict(self._rows)

    def set_running(self, extractor_id: str | None) -> None:
        """The extractor a compute is running for (its ring and row read
        RUNNING), or ``None``."""
        self._running = extractor_id
        if self._snapshot:
            self.set_coverage(self._snapshot)

    def set_cpu_percent(self, percent: int) -> None:
        self._cpu = int(percent)
        self._style_cpu()

    def set_busy(self, busy: bool) -> None:
        """While a job runs: no rebuild, no compute, no export or import."""
        self._busy = bool(busy)
        for w in (self.rebuild_button, self.index_menu_button, self.export_button,
                  self.import_button, self.compute_everything_button):
            w.setEnabled(not self._busy)
            w.update()
        self.refresh_action.setEnabled(not self._busy)
        self.full_rebuild_action.setEnabled(not self._busy)
        self._style_rows()

    def is_busy(self) -> bool:
        return self._busy

    def set_unsorted_section(self, widget: QWidget | None) -> None:
        """Place the UNSORTED DOWNLOADS widget (§4.9); ``None`` hides the
        section. A previous widget is detached, not deleted."""
        if self._unsorted is not None:
            self.unsorted_section.body.removeWidget(self._unsorted)
            self._unsorted.setParent(None)
        self._unsorted = widget
        if widget is not None:
            self.unsorted_section.body.addWidget(widget)
        # A widget with its own title (the Sort with AI section) replaces
        # the slot's header: "UNSORTED DOWNLOADS" showed twice (W10 capture).
        self.unsorted_section.header.setVisible(not hasattr(widget, "header"))
        self.unsorted_section.setVisible(widget is not None)

    def unsorted_widget(self) -> QWidget | None:
        return self._unsorted

    def set_check_section(self, widget: QWidget | None) -> None:
        """Place the CHECK CHARTS widget (``chart_check.CheckSection``);
        ``None`` hides the section. A previous widget is detached."""
        if self._check is not None:
            self.check_section.body.removeWidget(self._check)
            self._check.setParent(None)
        self._check = widget
        if widget is not None:
            self.check_section.body.addWidget(widget)
        self.check_section.header.setVisible(not hasattr(widget, "header"))
        self.check_section.setVisible(widget is not None)

    # ------------------------------------------------------------ style

    def _style_index(self) -> None:
        t = kit.tokens()
        color = _tone_color(t, self._index_tone)
        if self._index_tone == states.NORMAL:
            color = t["secondary_text"]
        self.index_label.setStyleSheet(
            f"color: {color.name()}; font-size: {scaled_area_px('info_text')}px;"
            " background: transparent;"
        )
        self.index_dot.update()

    def _style_cpu(self) -> None:
        t = kit.tokens()
        link = t["primary"].name()
        self.cpu_label.setText(
            f"{states.cpu_text(self._cpu)} · "
            f"<a href=\"settings\" style=\"color: {link}; text-decoration: none;\">"
            "change in Settings</a>"
        )
        self.cpu_label.setStyleSheet(
            f"color: {t['muted'].name()}; font-size: {scaled_area_px('info_text')}px;"
            " background: transparent;"
        )

    def _style_rows(self) -> None:
        for row in self._rows.values():
            row.refresh_theme(self._busy)

    def _style_fields(self) -> None:
        t = kit.tokens()
        px = scaled_area_px("info_text")
        css = (
            f"QLineEdit {{ background: {t['well'].name(QColor.HexArgb)};"
            f" color: {t['secondary_text'].name()};"
            f" border: 1px solid {t['well_line'].name(QColor.HexArgb)};"
            f" border-radius: 6px; padding: 2px 6px; font-size: {px}px; }}"
            f"QLineEdit:focus {{ border: 1px solid {t['ring'].name(QColor.HexArgb)}; }}"
        )
        for field in self._fields:
            field.setStyleSheet(css)
        self.database_path.setStyleSheet(
            f"QLabel {{ background: {t['well'].name(QColor.HexArgb)};"
            f" color: {t['secondary_text'].name()};"
            f" border: 1px solid {t['well_line'].name(QColor.HexArgb)};"
            f" border-radius: 6px; padding: 3px 8px; font-size: {px}px; }}"
        )
        self.database_path.refresh()

    def refresh_theme(self) -> None:
        """Restyle live from the current tokens (Rule 20)."""
        self.inner.setStyleSheet("QWidget#fc_library_inner { background: transparent; }")
        self.scroll.setStyleSheet("QScrollArea { background: transparent; }")
        self.scroll.viewport().setAutoFillBackground(False)
        for section in (self.database_section, self.folders_section, self.unsorted_section,
                        self.check_section,
                        self.index_section, self.coverage_section):
            section.refresh_theme()
        self._style_fields()
        self._style_index()
        self._style_cpu()
        self.coverage_summary.setStyleSheet(
            f"color: {kit.tokens()['secondary_text'].name()};"
            f" font-size: {scaled_area_px('info_text')}px; background: transparent;")
        self.coverage_dot.update()
        self._style_rows()
        t = kit.tokens()
        kit.style_menu(self.index_menu)
        if self._unsorted is not None and hasattr(self._unsorted, "refresh_theme"):
            self._unsorted.refresh_theme()
        if self._check is not None and hasattr(self._check, "refresh_theme"):
            self._check.refresh_theme()
        for w in self._checks + [self._fileless]:
            w.update()
        for w in self._remove:
            w.update()
        self.update()

    def refresh_metrics(self) -> None:
        """A font change: buttons follow ``buttons``, text ``info_text``,
        headers ``panel_titles``; relayout without a rebuild."""
        m = button_metrics()
        fs = kit.area_fs("info_text")
        self.sections_layout.setSpacing(round(16 * fs))
        for b in (self.show_location_button, self.export_button, self.import_button,
                  self.rebuild_button, self.index_menu_button,
                  self.compute_everything_button, self.coverage_toggle, *self._browse):
            b.set_metrics(m)
        self.index_cluster.set_metrics(m)
        self.coverage_grid.setHorizontalSpacing(round(8 * fs))
        self.coverage_grid.setVerticalSpacing(round(4 * fs))
        for row in self._rows.values():
            row.refresh_metrics()
        for field in self._fields:
            field.setMinimumHeight(round(26 * fs))
        self.index_dot.refresh_metrics()
        self.coverage_dot.refresh_metrics()
        for w in self._checks + [self._fileless]:
            w.updateGeometry()
        for w in self._remove:
            w.updateGeometry()
        if self._unsorted is not None and hasattr(self._unsorted, "refresh_metrics"):
            self._unsorted.refresh_metrics()
        if self._check is not None and hasattr(self._check, "refresh_metrics"):
            self._check.refresh_metrics()
        self.refresh_theme()
