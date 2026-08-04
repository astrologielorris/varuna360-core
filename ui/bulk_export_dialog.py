# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The bulk-export button and its dialog (SPEC-EXPORT-001, td-2by9).

Charts made before SPEC-PERSIST-001 exist only inside session.json. This is
the manual sweep that gives them a file, on the user's command — never
automatically, because rewriting a database nobody asked to have rewritten
is how you lose trust in a tool that holds thirteen years of work.

Everything expensive happens on a worker thread. Deciding whether an orphan
is a duplicate costs a chart BUILD per orphan (it has no stored positions),
and hundreds of those on the GUI thread would freeze the window with no
explanation.

The dialog shows the PLAN before it writes anything, and the two stages are
presented as what they are: charts already on disk are simply reported,
while a possible duplicate is a question the user answers, not a decision
the software makes quietly.
"""

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QTextEdit, QVBoxLayout,
)


class _PlanWorker(QThread):
    """Reads sessions and builds charts. Never writes."""
    done = Signal(object, object)          # {profile: plan}, error
    progress = Signal(str)

    def __init__(self, profiles, use_index=True):
        super().__init__()
        self.profiles = profiles
        self.use_index = use_index

    def run(self):
        try:
            import json
            from pathlib import Path
            from managers.bulk_export import index_positions, plan_export
            from state.user_data import get_user_data_dir

            haystack, position_fn = [], None
            if self.use_index:
                try:
                    from cache.chart_index_cache import ChartIndexCache
                    self.progress.emit("Reading the chart index…")
                    haystack = index_positions(ChartIndexCache().get_all_entries())
                    position_fn = _make_position_fn()
                except Exception:
                    haystack, position_fn = [], None

            base = Path(get_user_data_dir() or ".")
            plans = {}
            for profile in self.profiles:
                self.progress.emit(f"Checking {profile}…")
                path = base / "profiles" / profile / "session.json"
                try:
                    charts = json.loads(path.read_text(encoding="utf-8")).get("charts") or []
                except Exception:
                    charts = []
                plans[profile] = plan_export(charts, haystack=haystack,
                                             position_fn=position_fn)
            self.done.emit(plans, None)
        except Exception as e:                          # noqa: BLE001
            self.done.emit(None, f"{type(e).__name__}: {e}")


class _WriteWorker(QThread):
    done = Signal(object, object)
    progress = Signal(int, int, str)

    def __init__(self, entries, chart_folder=None, chart_format=None):
        super().__init__()
        self.entries = entries
        self.chart_folder = chart_folder
        self.chart_format = chart_format

    def run(self):
        try:
            from managers.bulk_export import export_entries
            result = export_entries(
                self.entries, chart_folder=self.chart_folder,
                chart_format=self.chart_format,
                progress_fn=lambda i, n, name: self.progress.emit(i, n, name))
            self.done.emit(result, None)
        except Exception as e:                          # noqa: BLE001
            self.done.emit(None, f"{type(e).__name__}: {e}")


def _make_position_fn():
    from core.chart_factory import build_chart_from_recipe

    def _positions(entry):
        from AI_tools.AI_main_function.chart_utils import get_planet_decimal_degrees
        chart = build_chart_from_recipe(entry.get("recipe") or {}, "aditya", 100)
        return (get_planet_decimal_degrees(chart, "Sun"),
                get_planet_decimal_degrees(chart, "Ascendant"))
    return _positions


class BulkExportDialog(QDialog):
    """Plan first, write second, and never both in one click."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Save charts that have no file")
        self.resize(640, 460)
        self._plans = {}
        self._plan_worker = None
        self._write_worker = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Charts created before Varuna360 started saving a file for every "
            "chart exist only in your session. This finds them and gives each "
            "one a file.\n\nNothing is written until you press Save."))

        self.include_flagged = QCheckBox(
            "Also save charts that look like duplicates of a file you already have")
        self.include_flagged.setToolTip(
            "A position match is a strong hint, not proof. Leave this off to "
            "review them yourself.")
        layout.addWidget(self.include_flagged)

        self.summary = QTextEdit()
        self.summary.setReadOnly(True)
        layout.addWidget(self.summary, 1)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        row = QHBoxLayout()
        row.addStretch()
        self.save_button = QPushButton("Save the missing files")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self._write)
        row.addWidget(self.save_button)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        row.addWidget(close)
        layout.addLayout(row)

        self._start_plan()

    # -- planning --------------------------------------------------------

    def _profiles(self):
        from pathlib import Path
        from state.user_data import get_user_data_dir
        root = Path(get_user_data_dir() or ".") / "profiles"
        if not root.is_dir():
            return []
        return sorted(p.name for p in root.iterdir()
                      if (p / "session.json").exists())

    def _start_plan(self):
        self.summary.setPlainText("Looking for charts with no file…")
        self._plan_worker = _PlanWorker(self._profiles())
        self._plan_worker.progress.connect(self.summary.setPlainText)
        self._plan_worker.done.connect(self._plan_ready)
        self._plan_worker.start()

    def _plan_ready(self, plans, error):
        if error:
            self.summary.setPlainText(f"Could not check your charts:\n{error}")
            return
        self._plans = plans or {}
        from managers.bulk_export import SKIPPED_HAS_FILE, SKIPPED_TRANSIT
        lines, orphans, flagged = [], 0, 0
        for profile, plan in sorted(self._plans.items()):
            if not plan.total:
                continue
            has_file = sum(1 for s in plan.skipped if s["reason"] == SKIPPED_HAS_FILE)
            transits = sum(1 for s in plan.skipped if s["reason"] == SKIPPED_TRANSIT)
            orphans += len(plan.to_write)
            flagged += len(plan.flagged)
            lines.append(
                f"{profile}: {len(plan.to_write)} with no file, "
                f"{len(plan.flagged)} possible duplicates, "
                f"{has_file} already saved, {transits} transits (not exported)")
        header = (f"{orphans} chart(s) have no file.\n"
                  f"{flagged} look like a chart you already have — "
                  f"tick the box above to save those too.\n\n")
        self.summary.setPlainText(header + "\n".join(lines))
        self.save_button.setEnabled(bool(orphans or flagged))

    # -- writing ---------------------------------------------------------

    def _batch(self):
        batch = []
        for plan in self._plans.values():
            batch.extend(plan.to_write)
            if self.include_flagged.isChecked():
                batch.extend(f["entry"] for f in plan.flagged)
        return batch

    def _write(self):
        batch = self._batch()
        if not batch:
            return
        self.save_button.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, len(batch))
        self._write_worker = _WriteWorker(batch)
        self._write_worker.progress.connect(self._on_progress)
        self._write_worker.done.connect(self._write_done)
        self._write_worker.start()

    def _on_progress(self, index, total, name):
        self.progress.setValue(index)
        self.progress.setFormat(f"{index}/{total}  {name}")

    def _write_done(self, result, error):
        self.progress.setVisible(False)
        if error or result is None:
            self.summary.setPlainText(f"The export stopped:\n{error}")
            self.save_button.setEnabled(True)
            return
        text = [f"Saved {len(result.written)} chart file(s)."]
        if result.failed:
            text.append(f"\n{len(result.failed)} could not be saved:")
            text += [f"  {f['name']}: {f['error']}" for f in result.failed[:20]]
        text.append("\nThe charts are unchanged; they now have files as well.")
        self.summary.setPlainText("\n".join(text))


def make_bulk_export_button(parent=None):
    """The button for the Settings folders page."""
    button = QPushButton("Save charts that have no file…", parent)
    button.setToolTip(
        "Find charts that exist only in your session and give each one a file.")
    button.clicked.connect(
        lambda: BulkExportDialog(button.window()).exec())
    return button
