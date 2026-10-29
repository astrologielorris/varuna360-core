# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The index file actions of the Library's DATABASE section (varuna/50,
SPEC-FIND-005 §3.7): SHOW LOCATION, EXPORT, IMPORT.

The index lives in the user data folder (``store.store_path``), outside the
install, so upgrades keep it; an export is for another machine or a backup.
The CLI twin is ``chart_index export`` / ``chart_index import``.
"""

from datetime import date
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QMessageBox

from core.chart_search.store import StoreWriter, export_store
from panels.find_chart import workers as fc_workers
from panels.find_chart import kit
from panels.find_chart.workers import StoreFileWorker

FILE_FILTER = "Find Chart index (*.sqlite);;All files (*)"


class IndexMenuMixin:
    """``FindChartPanel``'s index file actions (the Library's DATABASE)."""

    def _store_file_running(self):
        """An import or export owns its slot until its result is delivered
        (review r11), like the sync and compute."""
        return self._store_file_worker is not None or fc_workers.parked(StoreFileWorker)

    def _store_file_busy(self):
        if self._store_file_running() or self._index_running() or self._compute_running():
            self.index_status.setText("The index is busy, try again after.")
            return True
        return False

    def _export_index(self):
        if self._store_file_busy():
            return
        if not self.cache.path.is_file():
            self.index_status.setText(
                "Nothing to export yet: click REBUILD INDEX first."
            )
            return
        default = Path.home() / f"varuna360-chart-index-{date.today():%Y-%m-%d}.sqlite"
        name, _ = QFileDialog.getSaveFileName(
            self, "Export Chart Index", str(default), FILE_FILTER
        )
        if not name:
            return
        dest = Path(name)
        source = self.cache.path

        def job():
            export_store(dest, source)
            return f"Index exported to {dest.name}"

        self._run_store_file_job(job, "Exporting the index...")

    def _import_index(self):
        if self._store_file_busy():
            return
        name, _ = QFileDialog.getOpenFileName(
            self, "Import Computed Results", str(Path.home()), FILE_FILTER
        )
        if not name:
            return
        source = Path(name)
        path = self.cache.path

        def job():
            with StoreWriter.open(path) as store:
                report = store.import_computations(source)
            text = (
                f"Imported {report.taken:,} results for "
                f"{report.moments_matched:,} charts"
            )
            if report.moments_skipped:
                text += (
                    f"; {report.moments_skipped:,} charts of the file are not "
                    "indexed here with the same birth data (not added yet, or "
                    "their birth data differ: those are left as they are)"
                )
            return text

        self._run_store_file_job(job, "Importing computed results...", refresh=True)

    def _run_store_file_job(self, job, status, *, refresh=False):
        # Checked again at the start (review r12): the file chooser's own
        # event loop may have let a compute or a rebuild start meanwhile.
        if self._store_file_busy() or self._closing:
            return
        self.index_status.setText(status)
        worker = StoreFileWorker(job, refresh)
        relay = fc_workers.relay_for(worker, lambda w=worker: self._store_file_worker is w, self)
        relay.bind(worker.done, self._on_store_file_done)
        relay.bind(worker.error, self._on_store_file_error)
        self._store_file_worker = worker
        worker.start()

    def _release_store_file_worker(self):
        worker = self._store_file_worker
        self._store_file_worker = None
        if worker is not None:
            worker.wait()
            worker.deleteLater()

    def _on_store_file_done(self, text, refresh):
        if not self._from(self._store_file_worker):
            return
        self._release_store_file_worker()
        self.index_status.setText(text)
        print(f"[FIND_CHART] {text}")
        if refresh:
            self._store_changed()
            self._declined.clear()
            self._refresh_quietly()

    def _on_store_file_error(self, message):
        if not self._from(self._store_file_worker):
            return
        self._release_store_file_worker()
        self.index_status.setText("Index file operation failed")
        kit.message(self, QMessageBox.Icon.Warning, "Chart Index", message)

    def _open_index_folder(self):
        folder = self.cache.path.parent
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
