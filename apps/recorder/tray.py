# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Tray icon during a take (SPEC-REC-001 §4.9): Stop from any app, elapsed
time and the microphone warning in the tooltip. The desktop counterpart of the
Android notification; nothing is drawn inside the app window (INV-2)."""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

# Draft wording (orchestrator draft, for Lorris's review).
TEXT = {
    "stop": "Stop recording",
    "pause": "Pause recording",
    "resume": "Resume recording",
    "open": "Open recordings folder",
    "starting": "Screen recording: starting",
    "recording": "Screen recording {mm:02d}:{ss:02d}",
    "finalizing": "Screen recording: saving",
    "paused": "Screen recording paused {mm:02d}:{ss:02d}",
    "quiet": "The microphone hears no voice: check it",
}


def _icon(colour: str, muted: bool = False) -> QIcon:
    pm = QPixmap(32, 32)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(colour))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(4, 4, 24, 24)
    if muted:
        p.setPen(QColor("white"))
        p.drawLine(9, 23, 23, 9)
    p.end()
    return QIcon(pm)


class RecorderTray(QObject):
    stop_requested = Signal()
    pause_requested = Signal()               # pause, or resume while paused
    open_folder_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self._tray = QSystemTrayIcon(_icon("#E53935"), self)
        menu = QMenu()
        stop = QAction(TEXT["stop"], menu)
        stop.triggered.connect(self.stop_requested.emit)
        opener = QAction(TEXT["open"], menu)
        opener.triggered.connect(self.open_folder_requested.emit)
        pause = QAction(TEXT["pause"], menu)
        pause.triggered.connect(self.pause_requested.emit)
        self._pause = pause
        menu.addAction(pause)
        menu.addAction(stop)
        menu.addAction(opener)
        self._menu = menu
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._activated)
        self._quiet = False

    @property
    def available(self) -> bool:
        return self._tray is not None

    def _activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.stop_requested.emit()               # one click on the icon stops

    def show_phase(self, phase: str, elapsed: float = 0.0) -> None:
        if self._tray is None:
            return
        if phase == "idle":
            self._tray.hide()
            return
        self._pause.setText(TEXT["resume"] if phase == "paused" else TEXT["pause"])
        self._pause.setEnabled(phase in ("recording", "paused"))
        if phase in ("recording", "paused"):
            s = int(elapsed)
            tip = TEXT[phase].format(mm=s // 60, ss=s % 60)
        else:
            tip = TEXT[phase]
        if self._quiet:
            tip += "\n" + TEXT["quiet"]
        self._tray.setToolTip(tip)
        if not self._tray.isVisible():
            self._tray.show()

    def set_quiet(self, quiet: bool) -> None:
        self._quiet = quiet
        if self._tray is not None:
            self._tray.setIcon(_icon("#E53935", muted=quiet))
