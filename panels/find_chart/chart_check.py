# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""The Library sheet's CHECK CHARTS section (SPEC-LIB-001 §4.9).

The engines are ``core/library/checks.py`` (rules, no AI) and
``core/library/ai_check.py`` (a local model only). This module shows and emits;
the host (``check_host.ChartCheckMixin``) picks the folder, runs the worker
and saves the result.

``CheckSection(QWidget)``: CHECK CHARTS, STOP, a summary of the last result,
OPEN REPORT; under "With a local model" the privacy notice, ASK THE LOCAL
MODEL and COPY PROMPT. Signals ``check_requested()``, ``local_requested()``,
``stop_requested()``, ``report_requested()``. Methods ``set_running(kind,
done, total)`` (kind "rules" / "local" / "" for idle), ``set_result(result)``,
``set_message(text)``, ``refresh_theme()``, ``refresh_metrics()``.

``CheckWorker(QThread)``: ``CheckWorker(kind, folder, library_root,
local=(url, model))``. Signals ``progress(int, int)``, ``done(object)`` (the
saved result), ``failed(str)``. ``cancel()``.
"""
from __future__ import annotations

import functools
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QApplication, QHBoxLayout, QVBoxLayout, QWidget

from core.library import checks
from panels.find_chart import kit
from panels.find_chart.sheet_parts import _label, _SheetButton, _style_label

SECTION_TITLE = "Check charts"
SUBTITLE = "no AI"
EXPLANATION = ("Looks for damaged chart files, the way Kala files get damaged, for "
               "timezones that are wrong for the place and date, and for copies of one "
               "chart that disagree. Nothing is changed.")
LOCAL_TITLE = "With a local model"
SUMMARY_ROWS = 8
_TONE = {"error": "gold", "warning": "gold", "check": "secondary", "info": "muted"}


def when_text(result: dict) -> str:
    return result.get("when", "")[:16].replace("T", " ")


def result_text(result: dict) -> str:
    total = sum(n for lv, _t, n in checks.summary(result) if lv != "info")
    head = f"Last check {when_text(result)}: {result['checked']:,} charts"
    if result.get("cancelled"):
        head += " (stopped before the end)"
    return head + (f", {total:,} to look at." if total else ", nothing wrong found.")


def local_check():
    """``core.library.ai_check`` through the one AI door, or None in Lite,
    which ships no AI file (SPEC-EDN-002 D-23)."""
    from core.edition_features import ai_features
    door = ai_features()
    return door.library_ai_check() if door is not None else None


class CheckSection(QWidget):
    check_requested = Signal()
    local_requested = Signal()
    stop_requested = Signal()
    report_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.header = kit.SectionHeader(SECTION_TITLE)
        self.subtitle = _label(SUBTITLE, wrap=False)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.addWidget(self.header)
        head.addWidget(self.subtitle)
        head.addStretch(1)
        self.explanation = _label(EXPLANATION)
        self.check_button = _SheetButton("CHECK CHARTS", "gold")
        self.check_button.clicked.connect(self.check_requested)
        self.stop_button = _SheetButton("STOP")
        self.stop_button.clicked.connect(self.stop_requested)
        self.report_button = _SheetButton("OPEN REPORT")
        self.report_button.clicked.connect(self.report_requested)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        for b in (self.check_button, self.stop_button, self.report_button):
            buttons.addWidget(b)
        buttons.addStretch(1)
        self.status = _label()
        self.rows = [_label(wrap=False) for _ in range(SUMMARY_ROWS)]

        self.local_header = _label(LOCAL_TITLE.upper(), wrap=False)
        ai = local_check()
        self.notice = _label(ai.PRIVACY_NOTICE if ai else "")
        self.local_button = _SheetButton("ASK THE LOCAL MODEL")
        self.local_button.clicked.connect(self.local_requested)
        self.copy_button = _SheetButton("COPY PROMPT")
        self.copy_button.clicked.connect(self._copy_prompt)
        local = QHBoxLayout()
        local.setContentsMargins(0, 0, 0, 0)
        local.addWidget(self.local_button)
        local.addWidget(self.copy_button)
        local.addStretch(1)
        self.message = _label()
        if ai is None:  # Lite: no local-model check (SPEC-EDN-002 D-23)
            for w in (self.local_header, self.notice, self.local_button, self.copy_button):
                w.hide()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(head)
        lay.addWidget(self.explanation)
        lay.addLayout(buttons)
        lay.addWidget(self.status)
        for r in self.rows:
            lay.addWidget(r)
        lay.addSpacing(6)
        lay.addWidget(self.local_header)
        lay.addWidget(self.notice)
        lay.addLayout(local)
        lay.addWidget(self.message)
        self._result = None
        self.set_running("", 0, 0)
        self.set_result(None)
        self.set_message("")
        self.refresh_theme()

    # ------------------------------------------------------------ state
    def set_running(self, kind: str, done: int, total: int) -> None:
        running = bool(kind)
        self.check_button.setVisible(not running)
        self.local_button.setEnabled(not running)
        self.stop_button.setVisible(running)
        if running:
            what = "Checking" if kind == "rules" else "Asking the local model about"
            self.status.setText(f"{what} {done:,} of {total:,} charts..." if total
                                else f"{what} the charts...")
        else:
            self.status.setText(result_text(self._result) if self._result is not None
                                else "No check run yet.")

    def set_result(self, result) -> None:
        self._result = result
        self.report_button.setVisible(result is not None)
        lines = checks.summary(result) if result else []
        for i, row in enumerate(self.rows):
            if i < len(lines):
                level, title, n = lines[i]
                row.setText(f"{n:>6,}   {title}")
                row.setProperty("tone", _TONE.get(level, "muted"))
                row.show()
            else:
                row.hide()
        self.status.setText(result_text(result) if result else "No check run yet.")
        self._style_rows()

    def set_message(self, text: str) -> None:
        self.message.setText(text)
        self.message.setVisible(bool(text))

    def _copy_prompt(self) -> None:
        QApplication.clipboard().setText(local_check().PROMPT)
        self.set_message("The prompt is copied. Paste it, then your charts' facts, "
                         "into the model of your choice.")

    # ------------------------------------------------------------ style
    def _style_rows(self) -> None:
        for row in self.rows:
            _style_label(row, row.property("tone") or "muted")

    def refresh_theme(self) -> None:
        self.header.refresh_theme()
        _style_label(self.subtitle, "muted")
        _style_label(self.explanation, "muted")
        _style_label(self.status, "primary")
        _style_label(self.local_header, "secondary", bold=True)
        _style_label(self.notice, "muted")
        _style_label(self.message, "secondary")
        for b in (self.check_button, self.stop_button, self.report_button,
                  self.local_button, self.copy_button):
            b.refresh_theme()
        self._style_rows()

    def refresh_metrics(self) -> None:
        self.refresh_theme()
        self.updateGeometry()


class CheckWorker(QThread):
    progress = Signal(int, int)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, kind: str, folder: str, library_root, local=None, parent=None):
        super().__init__(parent)
        self.kind, self.folder, self.library_root, self.local = kind, folder, library_root, local
        self._cancel = False
        self._connections = []  # the local model's open request, closed on cancel

    def cancel(self) -> None:
        self._cancel = True
        for conn in list(self._connections):
            try:
                conn.close()
            except OSError:
                pass

    def is_cancelled(self) -> bool:
        return self._cancel

    def run(self) -> None:
        try:
            folder = Path(self.folder)
            if self.kind == "rules":
                result = checks.run(folder, self.progress.emit, self.is_cancelled)
            else:
                url, model = self.local
                ai_check = local_check()
                result = checks.latest(self.library_root)
                if not result or result.get("root") != str(folder) or result.get("ai"):
                    result = checks.run(folder, cancelled=self.is_cancelled)
                known = {f["rel"]: f["findings"] for f in result["files"]}
                post = functools.partial(ai_check._post, holder=self._connections)
                ai = ai_check.run(folder, url, model, known=known, post=post,
                                  progress=self.progress.emit, cancelled=self.is_cancelled)
                result = ai_check.merge_into(result, ai)
            checks.save(result, self.library_root)
            self.done.emit(result)
        except Exception as exc:  # noqa: BLE001 - shown in the section, never a crash
            self.failed.emit(f"The check stopped: {exc}")


def report_text(library_root) -> str:
    from core.library import admin
    path = Path(library_root) / admin.ADMIN / "checks" / "REPORT.md"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return "No report yet."


__all__ = ["CheckSection", "CheckWorker", "report_text", "result_text"]
