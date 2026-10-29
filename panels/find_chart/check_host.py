# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""CHECK CHARTS, wired into the Find Chart panel (SPEC-LIB-001 §4.9).

``ChartCheckMixin`` is the host side of ``panels/find_chart/chart_check.py``:
the check runs on the first chart folder (the one the app searches), in a
panel-owned ``CheckWorker``; the result and the report are saved in the
library's ``.library/checks`` (owner only) and the last one shows when the
panel opens. OPEN REPORT shows the report in a sheet, inside the app. The
local-model check asks only the Local AI server, and only when its address is
on this computer or the home network (``ai_check.endpoint``).
"""

from __future__ import annotations

import warnings

from PySide6.QtWidgets import QTextBrowser

from core.library import checks
from core.library.paths import library_root
from managers.settings_manager import get_settings
from panels.find_chart import kit
from panels.find_chart.chart_check import CheckSection, CheckWorker, local_check, report_text
from ui.qt_theme import scaled_area_px

REPORT_SHEET_W = 640
#: Workers a panel close left running: kept alive until they finish.
_PARKED = set()


class ChartCheckMixin:
    """``FindChartPanel``'s CHECK CHARTS (see the module docstring)."""

    def _create_check_section(self):
        self._check_worker = None
        self.check_section = CheckSection()
        self.check_section.check_requested.connect(lambda: self._start_check("rules"))
        self.check_section.local_requested.connect(lambda: self._start_check("local"))
        self.check_section.stop_requested.connect(self._cancel_check)
        self.check_section.report_requested.connect(self._open_check_report)
        self.library.set_check_section(self.check_section)
        self.check_report = QTextBrowser()
        self.check_report.setOpenLinks(False)
        self.check_sheet = kit.Sheet(self, "Chart check", width=REPORT_SHEET_W)
        self.check_sheet.content_layout.addWidget(self.check_report)
        try:
            self.check_section.set_result(checks.latest(self._check_library_root()))
        except Exception:  # noqa: BLE001 - a damaged result file is no result
            self.check_section.set_result(None)

    @staticmethod
    def _check_library_root():
        return library_root(get_settings().get("paths.library_root", ""))

    def _start_check(self, kind):
        if self._check_worker is not None:
            return
        folder = self._first_folder()
        if not folder:
            self.check_section.set_message("Add a chart folder first.")
            return
        local = None
        if kind == "local":
            ai_check = local_check()
            if ai_check is None:
                return
            try:
                local = ai_check.endpoint()
            except ai_check.LocalOnly as exc:
                self.check_section.set_message(str(exc))
                return
        self.check_section.set_message("")
        worker = CheckWorker(kind, folder, self._check_library_root(), local)
        worker.progress.connect(
            lambda d, t, w=worker, k=kind: w is self._check_worker
            and self.check_section.set_running(k, d, t))
        worker.done.connect(lambda r, w=worker: w is self._check_worker and self._check_done(r))
        worker.failed.connect(lambda m, w=worker: w is self._check_worker and self._check_failed(m))
        worker.finished.connect(lambda w=worker: self._release_check_worker(w))
        self._check_worker = worker
        self.check_section.set_running(kind, 0, 0)
        worker.start()

    def _check_done(self, result):
        self.check_section.set_result(result)
        self.check_section.set_running("", 0, 0)
        if "ai" in result and result["ai"].get("failed_batches"):
            self.check_section.set_message(
                f"The local model did not answer {result['ai']['failed_batches']} times, so "
                "those charts were not checked. Is it running?")

    def _check_failed(self, message):
        self.check_section.set_running("", 0, 0)
        self.check_section.set_message(message)

    def _release_check_worker(self, worker):
        if worker is self._check_worker:
            self._check_worker = None
            self.check_section.set_running("", 0, 0)
            worker.deleteLater()

    def _cancel_check(self):
        if self._check_worker is not None:
            self._check_worker.cancel()

    def _open_check_report(self):
        t = kit.tokens()
        self.check_report.setStyleSheet(
            f"QTextBrowser {{ color: {t['primary_text'].name()}; background: transparent;"
            f" border: none; font-size: {scaled_area_px('info_text')}px; }}")
        self.check_report.setMarkdown(report_text(self._check_library_root()))
        self.library_sheet.close_sheet()
        self.check_sheet.open_sheet()

    def _stop_check_worker(self, *, app_quit=False):
        """Panel close: the check stops after the current chart (a local-model
        request is closed); a worker still running after 5 s is parked, never
        destroyed while it runs. App quit: waited for."""
        worker = self._check_worker
        if app_quit:  # workers an earlier panel close parked join too
            for parked in list(_PARKED):
                parked.cancel()
                parked.wait()
        if worker is None:
            return
        self._check_worker = None
        worker.cancel()
        with warnings.catch_warnings():  # a signal with no slot warns
            warnings.simplefilter("ignore", RuntimeWarning)
            for signal in (worker.progress, worker.done, worker.failed):
                try:
                    signal.disconnect()
                except (RuntimeError, TypeError):
                    pass
        finished = worker.wait() if app_quit else worker.wait(5000)
        if finished and not worker.isRunning():
            worker.deleteLater()
            return
        _PARKED.add(worker)
        worker.finished.connect(lambda w=worker: (_PARKED.discard(w), w.deleteLater()))
