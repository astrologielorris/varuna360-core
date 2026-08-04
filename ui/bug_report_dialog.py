# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Bug report dialog (SPEC-SES-001 §4.5).

The user sees the exact payload before anything leaves the machine, and
nothing is sent until they press Send (INV-7). The preview is not a summary or
a sample — it is the same dict `send_report` transmits, rendered with the same
function, so "here is what we send" cannot drift from what is actually sent.

Sending happens on a worker thread: a 10-second network timeout on the GUI
thread would freeze the app, and freezing the app to report that saving is
degraded would be its own small joke.
"""
from pathlib import Path

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QVBoxLayout,
)

from core import bug_report
from ui.qt_theme import get_theme_colors


class _SendWorker(QThread):
    """Posts the report off the GUI thread."""
    finished_with = Signal(bool, str)

    def __init__(self, payload, parent=None):
        super().__init__(parent)
        self._payload = payload

    def run(self):
        ok, message = bug_report.send_report(self._payload)
        self.finished_with.emit(ok, message)


class BugReportDialog(QDialog):
    """Compose and send a diagnostic report.

    `health` is a SessionManager.health dict, or None for a general report.
    """

    def __init__(self, health=None, parent=None):
        super().__init__(parent)
        self._health = health
        self._worker = None
        # The payload the user is actually looking at. Send and Save must use
        # this object, never a fresh build (INV-7).
        self._payload_snapshot = None
        self.setWindowTitle("Report a problem")
        self.setMinimumSize(620, 620)
        self._build_ui()
        self._refresh_preview()

    def _build_ui(self):
        theme = get_theme_colors()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 14)
        layout.setSpacing(10)

        intro = QLabel(
            "This sends a technical report to 360heartsinthesky.com so the "
            "problem can be fixed.\n\n"
            "It contains no chart data, no birth details and no names. You "
            "can see exactly what will be sent below."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {theme['secondary_text']};")
        layout.addWidget(intro)

        layout.addWidget(QLabel("What happened?"))
        self.note_edit = QPlainTextEdit()
        self.note_edit.setPlaceholderText(
            "For example: it happened after I switched profiles, or while "
            "Dropbox was syncing."
        )
        self.note_edit.setMaximumHeight(110)
        self.note_edit.textChanged.connect(self._refresh_preview)
        layout.addWidget(self.note_edit)

        email_row = QHBoxLayout()
        email_row.addWidget(QLabel("Your email (optional):"))
        self.email_edit = QLineEdit()
        self.email_edit.setPlaceholderText("only if you want a reply")
        self.email_edit.textChanged.connect(self._refresh_preview)
        email_row.addWidget(self.email_edit)
        layout.addLayout(email_row)

        preview_label = QLabel("Exactly what will be sent:")
        preview_font = QFont()
        preview_font.setBold(True)
        preview_label.setFont(preview_font)
        layout.addWidget(preview_label)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        mono = QFont("monospace")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSize(8)
        self.preview.setFont(mono)
        layout.addWidget(self.preview, stretch=1)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        self.copy_button = QPushButton("Copy")
        self.copy_button.setToolTip("Copy the report to the clipboard")
        self.copy_button.clicked.connect(self._copy)
        buttons.addWidget(self.copy_button)

        self.save_button = QPushButton("Save to file…")
        self.save_button.clicked.connect(self._save)
        buttons.addWidget(self.save_button)
        buttons.addStretch()

        self.box = QDialogButtonBox()
        self.send_button = self.box.addButton(
            "Send", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.cancel_button = self.box.addButton(
            "Cancel", QDialogButtonBox.ButtonRole.RejectRole
        )
        self.send_button.clicked.connect(self._send)
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.box)
        layout.addLayout(buttons)

    # -- payload --------------------------------------------------------

    def current_payload(self):
        """The exact payload shown in the preview (INV-7).

        Returns the SNAPSHOT taken when the preview was last rendered, not a
        freshly built one. That distinction is the whole guarantee.

        build_payload() is not pure: it calls read_log_tail(), which re-reads
        the log file. The app keeps logging while the dialog is open (autosave
        alone fires every 30 s), so building it once for the preview and again
        on Send meant the user approved one set of bytes and a different set
        was transmitted - with a label above it reading "Exactly what will be
        sent". Informed consent to content nobody had seen.

        Rebuilding happens only when the user edits the note or the email
        field, and the preview is re-rendered in the same breath, so what is
        on screen and what would be sent stay the same object.
        """
        if self._payload_snapshot is None:
            self._rebuild_payload()
        return self._payload_snapshot

    def _rebuild_payload(self):
        self._payload_snapshot = bug_report.build_payload(
            health=self._health,
            user_note=self.note_edit.toPlainText(),
            contact_email=self.email_edit.text(),
        )
        return self._payload_snapshot

    def _refresh_preview(self):
        # Snapshot first, then render THAT. Rendering a fresh build here and
        # sending another one later is exactly the drift this avoids.
        self.preview.setPlainText(
            bug_report.payload_preview(self._rebuild_payload())
        )

    # -- actions --------------------------------------------------------

    def _copy(self):
        QGuiApplication.clipboard().setText(self.preview.toPlainText())
        self._set_status("Copied to the clipboard.", ok=True)

    def _save(self):
        default = str(Path.home() / "varuna360-report.json")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save report", default, "JSON (*.json);;All files (*)"
        )
        if not path:
            return
        ok, message = bug_report.save_report(self.current_payload(), path)
        self._set_status(message, ok=ok)

    def _send(self):
        self.send_button.setEnabled(False)
        self.cancel_button.setEnabled(False)   # see closeEvent
        self._set_status("Sending…", ok=None)
        # NOT parented to the dialog. A QThread whose parent is destroyed
        # while it is still running aborts the process, and this one can run
        # for the full 10 s request timeout — far longer than a user takes to
        # click Cancel.
        self._worker = _SendWorker(self.current_payload(), None)
        self._worker.finished_with.connect(self._on_sent)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def _on_sent(self, ok, message):
        self.send_button.setEnabled(True)
        self.cancel_button.setEnabled(True)
        self._set_status(message, ok=ok)
        if ok:
            self.accept()
        else:
            # Failure is expected while the endpoint is undeployed. Point at
            # the fallbacks rather than leaving the user at a dead end.
            self.copy_button.setDefault(True)

    def _set_status(self, message, ok=None):
        theme = get_theme_colors()
        if ok is True:
            color = "#4CAF50"
        elif ok is False:
            color = "#D9534F"
        else:
            color = theme["secondary_text"]
        self.status.setStyleSheet(f"color: {color};")
        self.status.setText(message)

    def closeEvent(self, event):
        """Never tear down while a send is in flight.

        The worker is unparented and self-deleting, so the old
        "QThread destroyed while running" abort is already off the table. What
        remains is _on_sent firing against a half-destroyed dialog, so detach
        the signal and let the thread finish on its own.

        wait() here must exceed the request timeout, not undercut it: the
        previous 2 s against a 10 s timeout guaranteed the wait expired first.
        """
        if self._worker is not None and self._worker.isRunning():
            try:
                self._worker.finished_with.disconnect(self._on_sent)
            except (RuntimeError, TypeError):
                pass
            self._worker.wait(int((bug_report.SEND_TIMEOUT_SECONDS + 2) * 1000))
        super().closeEvent(event)
