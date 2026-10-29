# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Draw the rectangle to record (SPEC-REC-001 §4.2): a dimmed overlay over the
whole desktop; drag a rectangle; Enter or release confirms, Esc cancels."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QEventLoop, QPoint, QRect, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

TEXT = {"hint": "Drag over the part of the screen to record. Esc cancels."}


def virtual_desktop() -> QRect:
    rect = QRect()
    for s in QGuiApplication.screens():
        rect = rect.united(s.geometry())
    return rect


class RegionPicker(QWidget):
    def __init__(self):
        flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                 | Qt.WindowType.Tool)
        super().__init__(None, flags)
        self.setObjectName("recorder_region_picker")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setGeometry(virtual_desktop())
        self._a: Optional[QPoint] = None
        self._b: Optional[QPoint] = None
        self.result: Optional[QRect] = None
        self._loop: Optional[QEventLoop] = None

    def pick(self) -> Optional[QRect]:
        """Blocks until a rectangle is drawn (global logical coordinates) or
        the pick is cancelled (None)."""
        self.show()
        self.activateWindow()
        self.raise_()
        self.grabKeyboard()
        self._loop = QEventLoop()
        self._loop.exec()
        self.releaseKeyboard()
        self.hide()
        return self.result

    def _finish(self, rect: Optional[QRect]) -> None:
        self.result = rect
        if self._loop is not None:
            self._loop.quit()

    def _selection(self) -> Optional[QRect]:
        if self._a is None or self._b is None:
            return None
        return QRect(self._a, self._b).normalized()

    def keyPressEvent(self, e):                         # noqa: N802 (Qt API)
        if e.key() == Qt.Key.Key_Escape:
            self._finish(None)
        elif e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            sel = self._selection()
            self._finish(sel.translated(self.geometry().topLeft()) if sel else None)

    def mousePressEvent(self, e):                       # noqa: N802
        if e.button() == Qt.MouseButton.RightButton:
            self._finish(None)
            return
        self._a = self._b = e.position().toPoint()
        self.update()

    def mouseMoveEvent(self, e):                        # noqa: N802
        if self._a is not None:
            self._b = e.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, e):                     # noqa: N802
        if self._a is None:
            return
        self._b = e.position().toPoint()
        sel = self._selection()
        if sel is not None and sel.width() >= 64 and sel.height() >= 64:
            self._finish(sel.translated(self.geometry().topLeft()))
        else:
            self._a = self._b = None
            self.update()

    def paintEvent(self, _e):                           # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 110))
        sel = self._selection()
        if sel is not None:
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            p.fillRect(sel, Qt.GlobalColor.transparent)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            p.setPen(QPen(QColor("#E53935"), 2, Qt.PenStyle.DashLine))
            p.drawRect(sel)
        p.setPen(QColor("white"))
        p.drawText(self.rect().adjusted(0, 40, 0, 0),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, TEXT["hint"])
