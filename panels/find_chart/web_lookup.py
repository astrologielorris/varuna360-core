# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Web lookup and CHTK creation, moved unchanged from ``find_chart_panel``
(design.md §4.9). A query with no local match offers a web search; the found
birth data becomes a CHTK file in ``celebrity_unsorted`` (FIND-003 §3.5: the
store learns that one file) and is opened.
"""

import os
import threading

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from managers import find_chart_sync
from ui.qt_theme import STATUS, desat_hex, get_primary_button_style, scaled_area_px


class WebDownloadWorker(QObject):
    """Download birth data from the web and create a CHTK file, on a daemon
    Python thread (review r11): a network call cannot be interrupted, and a
    daemon thread, unlike a running QThread, never aborts the app when the
    process exits. ``cancel()`` stops it before it writes a file; the file
    write itself is short and ``wait`` covers it on quit. Same API as the
    QThread it replaces: ``start``, ``isRunning``, ``wait(ms)``, signals
    ``finished(object)`` and ``status(str)`` (queued to the GUI thread)."""

    finished = Signal(object)  # dict with birth_data + chtk_path, or None
    status = Signal(str)  # progress messages

    def __init__(self, name, source, output_dir):
        super().__init__()
        self.name = name
        self.source = source
        self.output_dir = output_dir
        self._lock = threading.Lock()
        self._cancelled = False
        self._thread = threading.Thread(target=self.run, daemon=True,
                                        name="find-chart-web")

    def start(self):
        self._thread.start()

    def isRunning(self):  # noqa: N802 - the QThread name the panel uses
        return self._thread.is_alive()

    def wait(self, ms=None):
        self._thread.join(None if ms is None else ms / 1000)
        return not self._thread.is_alive()

    def quit(self):
        pass  # no event loop: ``cancel`` is the stop

    def cancel(self):
        with self._lock:
            self._cancelled = True

    def _emit(self, signal, value):
        try:
            signal.emit(value)
        except RuntimeError:  # the panel and this object are gone
            pass

    def run(self):
        try:
            from pathlib import Path

            from browser_tools.web_birth_data import extract_birth_data
            from core.library.convert import download_to_toml

            self._emit(self.status, f"Searching {self.source}...")
            birth_data = extract_birth_data(
                self.name, source=self.source, verbose=False
            )
            # The cancel check and the file write share the lock: a cancel
            # either lands first (no file) or waits for the write to end.
            with self._lock:
                if self._cancelled:
                    return
                if not birth_data:
                    self._emit(self.finished, None)
                    return
                self._emit(self.status, "Found! Creating chart file...")
                # A .toml, so the new chart can be rated (SPEC-LIB-001 D-37);
                # the result key keeps its old name for the panel.
                chtk_path = download_to_toml(birth_data, Path(self.output_dir))
            if chtk_path:
                self._emit(self.finished,
                           {"birth_data": birth_data, "chtk_path": str(chtk_path)})
            else:
                self._emit(self.finished, None)
        except Exception as e:
            self._emit(self.status, f"Error: {e}")
            self._emit(self.finished, None)


class WebLookupMixin:
    """``FindChartPanel``'s web lookup: the 0-results section and its worker."""

    def _create_web_download_section(self, results_layout, theme):
        # === WEB DOWNLOAD SECTION (visible when 0 results + query) ===
        self.web_download_widget = QWidget()
        self.web_download_widget.hide()
        dl_layout = QVBoxLayout(self.web_download_widget)
        dl_layout.setContentsMargins(10, 15, 10, 10)
        dl_layout.setSpacing(8)

        self.no_results_label = QLabel("")
        self.no_results_label.setStyleSheet(
            f"color: {theme['secondary_text']}; font-size: {scaled_area_px('status')}px;"
        )
        dl_layout.addWidget(self.no_results_label)

        # Search button row
        btn_row = QHBoxLayout()
        self.web_search_btn = QPushButton("Search Web")
        self.web_search_btn.setStyleSheet(get_primary_button_style())
        self.web_search_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        # td-2o8u: width floor (max(legacy 200, advance)) is derived in
        # _refresh_geometry, which _create_ui runs after this section is built.
        self.web_search_btn.clicked.connect(self._on_web_search_clicked)
        btn_row.addWidget(self.web_search_btn)
        btn_row.addStretch()
        dl_layout.addLayout(btn_row)

        self.web_status_label = QLabel("Click to search the web for birth data")
        self.web_status_label.setStyleSheet(
            f"color: {theme['secondary_text']}; font-size: {scaled_area_px('status')}px; font-style: italic;"
        )
        dl_layout.addWidget(self.web_status_label)

        self.web_result_label = QLabel("")
        self.web_result_label.setStyleSheet(
            f"color: {desat_hex(STATUS['success'])}; font-size: {scaled_area_px('status')}px; font-weight: bold;"
        )
        self.web_result_label.hide()
        dl_layout.addWidget(self.web_result_label)

        self.web_download_widget.setStyleSheet(f"""
            QWidget {{
                background-color: {theme["secondary"]};
                border: 1px solid {theme["primary"]};
                border-radius: 6px;
            }}
        """)
        results_layout.addWidget(self.web_download_widget)

    def _on_web_search_clicked(self):
        """Download birth data from web and create CHTK file."""
        query = self.search_entry.text().strip()
        if not query or self._web_worker is not None or self._closing:
            return

        source = "auto"

        # Ensure output directory exists
        os.makedirs(self._unsorted_dir, exist_ok=True)

        # Disable both buttons (inline + 0-results section)
        self.web_search_inline_btn.setEnabled(False)
        if self.web_search_btn:
            self.web_search_btn.setEnabled(False)
        self.web_status_label.setText("Searching web...")
        self.web_result_label.hide()

        from panels.find_chart import workers as fc_workers

        worker = WebDownloadWorker(query, source, self._unsorted_dir)
        relay = fc_workers.relay_for(worker, lambda w=worker: self._web_worker is w, self)
        relay.bind(worker.status, self.web_status_label.setText)
        relay.bind(worker.finished, self._on_web_download_finished)
        self._web_token += 1
        worker.token = self._web_token  # its deferred load is valid only for it
        self._web_worker = worker
        worker.start()

    def _load_web_chart(self, path, token):
        """The deferred load, unless the panel closed or another web job
        started since (review r12)."""
        if token == self._web_token:
            self.chart_selected.emit(path)

    def _on_web_download_finished(self, result):
        """Handle web download completion."""
        self.web_search_inline_btn.setEnabled(True)
        if self.web_search_btn:
            self.web_search_btn.setEnabled(True)

        # Clean up QThread before dropping reference (prevents C++ destructor deadlock)
        from panels.find_chart import workers as fc_workers

        worker = self._web_worker
        self._web_worker = None
        job_token = getattr(worker, "token", None)
        if worker is not None:
            fc_workers.disconnect_web(worker)
            worker.wait()
            worker.deleteLater()

        if result is None:
            self.web_status_label.setText(
                "Not found on the web. Try a different spelling."
            )
            return

        bd = result["birth_data"]
        chtk_path = result["chtk_path"]
        app_sync = find_chart_sync.current()
        if app_sync is not None:  # FIND-003 §3.5: the store learns this file
            self._refresh_when_done(app_sync.file_written(chtk_path))
        has_time = bd.get("hasBirthTime", False)
        time_str = (
            f"{bd.get('hour', 12):02d}:{bd.get('minute', 0):02d}"
            if has_time
            else "noon (unknown)"
        )

        self.web_status_label.setText("Chart saved and loaded!")
        self.web_result_label.setText(
            f"{bd.get('name', '?')} — {bd.get('day', '?')}/{bd.get('month', '?')}/{bd.get('year', '?')} "
            f"{time_str} — {bd.get('city', '?')}, {bd.get('country', '?')}"
        )
        self.web_result_label.show()

        # Defer chart loading to next event loop iteration so QThread
        # cleanup completes fully before heavy chart computation begins.
        # Without this, processEvents() inside load_chart can process
        # thread teardown events mid-computation, causing a freeze.
        QTimer.singleShot(0, lambda p=chtk_path, t=job_token: self._load_web_chart(p, t))

        # A new unsorted file: the Library section and badge recount (§4.9)
        self.refresh_unsorted_downloads(force_recount=True)

        # SPEC-FIND-003: no auto-rebuild. User clicks REBUILD INDEX when ready.
