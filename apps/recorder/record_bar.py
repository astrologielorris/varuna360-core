# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The recording bar in the menu bar, right after Help (SPEC-REC-001 D-22,
Lorris 2026-10-24): red dot, the time recorded, Pause/Resume, Stop and
Delete. Shown only while a take runs; reverses INV-2 for the app window.

A child of the menu bar placed by hand after its last menu, never a layout
item or corner widget: the menu bar's own height and items stay untouched
(the menu bar blanks its items when its height is constrained, see
``ui.qt_theme.apply_menu_bar_style``).
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QWidget

# Draft wording (orchestrator draft, for Lorris's review).
TEXT = {
    "pause": "Pause the recording",
    "resume": "Resume the recording",
    "stop": "Stop and save the recording",
    "delete": "Delete this recording",
    "starting": "Starting",
    "paused": "Paused",
    "saving": "Saving",
}
GAP = 16                     # px between the last menu and the bar
RED = "#E53935"              # semantic recording red (Rule 20 exception)
AMBER = "#F9A825"            # semantic paused


def icon(kind: str, colour: str, size: int = 32) -> QIcon:
    """Pause, play, stop, delete or the dot, drawn (no emoji font needed)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    c = QColor(colour)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    u = size / 32.0
    if kind == "pause":
        p.drawRoundedRect(QRectF(8 * u, 7 * u, 6 * u, 18 * u), 1.5 * u, 1.5 * u)
        p.drawRoundedRect(QRectF(18 * u, 7 * u, 6 * u, 18 * u), 1.5 * u, 1.5 * u)
    elif kind == "play":
        p.drawPolygon(QPolygonF([QPointF(9 * u, 6 * u), QPointF(26 * u, 16 * u),
                                 QPointF(9 * u, 26 * u)]))
    elif kind == "stop":
        p.drawRoundedRect(QRectF(8 * u, 8 * u, 16 * u, 16 * u), 2 * u, 2 * u)
    elif kind == "delete":
        p.drawRoundedRect(QRectF(6 * u, 7 * u, 20 * u, 3 * u), 1 * u, 1 * u)
        p.drawRect(QRectF(13 * u, 4 * u, 6 * u, 3 * u))
        body = QPainterPath()
        body.moveTo(8 * u, 12 * u)
        body.lineTo(24 * u, 12 * u)
        body.lineTo(22.5 * u, 28 * u)
        body.lineTo(9.5 * u, 28 * u)
        body.closeSubpath()
        p.drawPath(body)
    else:                                         # the recording dot
        p.drawEllipse(QRectF(6 * u, 6 * u, 20 * u, 20 * u))
    p.end()
    return QIcon(pm)


def format_time(seconds: float) -> str:
    s = int(max(0.0, seconds))
    h, m, s = s // 3600, (s // 60) % 60, s % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class RecordBar(QWidget):
    pause_requested = Signal()
    resume_requested = Signal()
    stop_requested = Signal()
    delete_requested = Signal()

    def __init__(self, menubar):
        super().__init__(menubar)
        self.setObjectName("recorder_bar")
        self._menubar = menubar
        self._phase = "idle"
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 0, 6, 0)
        lay.setSpacing(4)
        self.dot = QLabel()
        self.dot.setObjectName("recorder_bar_dot")
        self.time = QLabel("00:00")
        self.time.setObjectName("recorder_bar_time")
        self.pause_btn = self._button("recorder_bar_pause", TEXT["pause"], self._pause_clicked)
        self.stop_btn = self._button("recorder_bar_stop", TEXT["stop"], self.stop_requested.emit)
        self.delete_btn = self._button("recorder_bar_delete", TEXT["delete"],
                                       self.delete_requested.emit)
        for w in (self.dot, self.time, self.pause_btn, self.stop_btn, self.delete_btn):
            lay.addWidget(w)
        self._restyle()
        self._follower = _Follower(self)
        menubar.installEventFilter(self._follower)
        self.hide()

    def _button(self, name, tip, slot) -> QToolButton:
        b = QToolButton(self)
        b.setObjectName(name)
        b.setToolTip(tip)
        b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        b.setAutoRaise(True)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(slot)
        return b

    def _pause_clicked(self) -> None:
        (self.resume_requested if self._phase == "paused" else self.pause_requested).emit()

    def _restyle(self) -> None:
        from ui.qt_theme import get_theme_colors
        c = get_theme_colors()
        px = max(11, self._menubar.fontMetrics().height() - 3)
        text = c["secondary_text"]
        side = px + 2
        self.dot.setPixmap(icon("dot", AMBER if self._phase == "paused" else RED, 64)
                           .pixmap(QSize(side, side)))
        paused = self._phase == "paused"
        for btn, kind, colour in ((self.pause_btn, "play" if paused else "pause", text),
                                  (self.stop_btn, "stop", text),
                                  (self.delete_btn, "delete", text)):
            btn.setIcon(icon(kind, colour, 64))
            btn.setIconSize(QSize(side, side))
        self.setStyleSheet(
            f"#recorder_bar QLabel {{ color: {text}; font-size: {px}px; }}"
            f"#recorder_bar QToolButton {{ padding: 1px 3px; border: none; border-radius: 3px;"
            f" background: transparent; }}"
            f"#recorder_bar QToolButton:hover {{ background: {c['secondary_light']}; }}")

    def show_phase(self, phase: str, elapsed: float = 0.0) -> None:
        """idle hides the bar; starting/recording/paused/finalizing show it."""
        changed = phase != self._phase
        self._phase = phase
        if phase == "idle":
            self.hide()
            return
        label = {"starting": TEXT["starting"], "finalizing": TEXT["saving"]}.get(phase)
        self.time.setText(label or (("%s " % TEXT["paused"] if phase == "paused" else "")
                                    + format_time(elapsed)))
        self.pause_btn.setToolTip(TEXT["resume"] if phase == "paused" else TEXT["pause"])
        self.pause_btn.setEnabled(phase in ("recording", "paused"))
        self.stop_btn.setEnabled(phase in ("starting", "recording", "paused"))
        self.delete_btn.setEnabled(phase in ("starting", "recording", "paused"))
        if changed:
            self._restyle()
        self.adjustSize()
        self.place()
        if not self.isVisible():
            self.show()
            self.raise_()

    def refresh_theme(self) -> None:
        self._restyle()
        self.place()

    def place(self) -> None:
        """Right after the last visible menu; at the right edge when the
        window is too narrow for that."""
        mb = self._menubar
        actions = [a for a in mb.actions() if a.isVisible() and not mb.actionGeometry(a).isEmpty()]
        x = (max(mb.actionGeometry(a).right() for a in actions) + GAP) if actions else GAP
        self.adjustSize()
        w, h = self.sizeHint().width(), min(self.sizeHint().height(), mb.height())
        x = min(x, max(0, mb.width() - w - 4))
        self.setGeometry(x, max(0, (mb.height() - h) // 2), w, h)


class _Follower(QObject):
    """Keeps the bar after the last menu when the menu bar resizes or its
    menus change (a theme or font change re-lays it out)."""

    def __init__(self, bar: RecordBar):
        super().__init__(bar)
        self._bar = bar

    def eventFilter(self, obj, event):                       # noqa: N802 (Qt API)
        if event.type() in (QEvent.Type.Resize, QEvent.Type.LayoutRequest,
                            QEvent.Type.FontChange, QEvent.Type.ActionChanged) \
                and self._bar.isVisible():
            self._bar.place()
        return False
