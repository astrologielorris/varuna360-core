# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Draggable chart button for the Chart Memory Panel (SPEC-TRN-006).

A QPushButton subclass that behaves exactly like a normal memory button (click to
select, right-click for the context menu) but can also be dragged onto the TRANSIT
button to overlay that chart. The drag carries the memory entry's stable id via a
custom MIME type; the drop side (ChartOverlayManager) rebuilds the chart from a
deep copy of the entry's recipe (INV-5: it must NOT mutate the persisted entry the
way get_or_build_chart does), so indices (which shift on repagination) are never
carried across.
"""

from PySide6.QtCore import QByteArray, QMimeData, Qt
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QApplication, QPushButton

# The single source of this string. Imported by the drop side (TransitDropButton).
CHART_ENTRY_MIME = "application/x-varuna360-chart-entry"


class ChartMemoryButton(QPushButton):
    """Memory chart button that is also a drag source for chart overlay."""

    def __init__(self, text, entry_id, parent=None, draggable=True):
        super().__init__(text, parent)
        self.entry_id = entry_id
        self._draggable = draggable
        self._drag_start_pos = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.position().toPoint()
        # super() keeps the existing clicked / pressed behaviour intact.
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        # Drag is suppressed in select-mode (draggable=False) where the gesture
        # would conflict with checkbox toggling, and until the press moves past
        # the platform drag threshold — that gate is what keeps a normal click
        # from turning into a drag (the highest-risk regression here).
        if (not self._draggable
                or self.entry_id is None
                or self._drag_start_pos is None
                or not (event.buttons() & Qt.MouseButton.LeftButton)):
            return super().mouseMoveEvent(event)

        moved = (event.position().toPoint() - self._drag_start_pos).manhattanLength()
        if moved < QApplication.startDragDistance():
            return super().mouseMoveEvent(event)

        mime = QMimeData()
        mime.setData(CHART_ENTRY_MIME,
                     QByteArray(str(self.entry_id).encode("utf-8")))
        mime.setText(self.text())  # human-readable fallback

        drag = QDrag(self)
        drag.setMimeData(mime)  # Qt owns mime after this
        drag.setPixmap(self.grab())
        drag.setHotSpot(event.position().toPoint())
        drag.exec(Qt.DropAction.CopyAction)
        # Rule 18: Qt owns drag + mime after exec(); hold no reference to them.
        # QDrag.exec consumes the mouse release, so QAbstractButton's internal
        # 'down' flag never clears — reset it or the button stays visually pressed.
        self.setDown(False)
        self._drag_start_pos = None
