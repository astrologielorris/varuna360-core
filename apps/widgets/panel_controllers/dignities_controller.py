# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Dignities-in-Vargas panel controller.

Populates the dignities table (Page 3 of the strength_elements_stack)
with planetary dignities across all 16 standard vargas, reusing the
CLI computation from AI_tools.AI_main_function.dignities_in_vargas.
"""

from PySide6.QtWidgets import QTableWidgetItem, QStyledItemDelegate
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QBrush, QPalette

from state import PanelControllerBase


class DignityColorDelegate(QStyledItemDelegate):
    """Delegate that respects per-item ForegroundRole/BackgroundRole colors,
    overriding any stylesheet cascade that would otherwise flatten them."""

    def paint(self, painter, option, index):
        bg = index.data(Qt.ItemDataRole.BackgroundRole)
        if bg:
            painter.save()
            painter.fillRect(option.rect.adjusted(0, 0, -1, -1), bg)
            painter.restore()
        fg = index.data(Qt.ItemDataRole.ForegroundRole)
        if fg:
            option.palette.setColor(QPalette.ColorRole.Text, fg.color())
            option.palette.setColor(QPalette.ColorRole.HighlightedText, fg.color())
        super().paint(painter, option, index)

_PLANET_HEADERS = ["Su", "Mo", "Ma", "Me", "Ju", "Ve", "Sa"]

_DIGNITY_FG = {
    "EX": QBrush(QColor("#FF4444")),
    "MT": QBrush(QColor("#DD66FF")),
    "OH": QBrush(QColor("#44AAFF")),
    "GF": QBrush(QColor("#44DD44")),
    "F":  QBrush(QColor("#77CC77")),
    "N":  QBrush(QColor("#999999")),
    "E":  QBrush(QColor("#FFAA33")),
    "GE": QBrush(QColor("#FF7744")),
    "DB": QBrush(QColor("#FF3333")),
}

_DIGNITY_BG = {
    "EX": QBrush(QColor(255, 68, 68, 35)),
    "MT": QBrush(QColor(221, 102, 255, 30)),
    "OH": QBrush(QColor(68, 170, 255, 25)),
    "DB": QBrush(QColor(255, 51, 51, 35)),
}


class DignitiesController(PanelControllerBase):
    """Subscribes to active_chart + aditya_mode events.
    Computes dignities across all 16 standard vargas.
    Supports cycling through varga calculation styles via toggle_varga_style().
    """

    def __init__(self, gui):
        super().__init__(gui=gui, lazy=False)
        self._style_index = 0

    @property
    def varga_style(self):
        from core.varga_codes import VARGA_STYLE_ORDER
        return VARGA_STYLE_ORDER[self._style_index]

    @property
    def varga_style_label(self):
        from core.varga_codes import VARGA_STYLES, VARGA_STYLE_ORDER
        key = VARGA_STYLE_ORDER[self._style_index]
        return VARGA_STYLES[key]["short"]

    def toggle_varga_style(self):
        from core.varga_codes import VARGA_STYLE_ORDER
        self._style_index = (self._style_index + 1) % len(VARGA_STYLE_ORDER)
        self._refresh()

    def _on_chart_changed(self):
        self._refresh()

    def _on_mode_changed(self):
        self._refresh()

    def _refresh(self):
        gui = self._gui
        if not hasattr(gui, "dignities_table"):
            return

        chart = getattr(self._state, 'active_chart', None) if self._state else None
        if not chart:
            return

        gui.dignities_table.clearContents()

        try:
            from AI_tools.AI_main_function.dignities_in_vargas import compute_dignities_table
            rows = compute_dignities_table(chart, varga_style=self.varga_style)

            gui.dignities_table.setRowCount(len(rows))

            for i, row in enumerate(rows):
                varga_item = QTableWidgetItem(row["label"])
                varga_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
                gui.dignities_table.setItem(i, 0, varga_item)

                for j, dignity in enumerate(row["dignities"]):
                    item = QTableWidgetItem(dignity)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
                    fg = _DIGNITY_FG.get(dignity)
                    if fg:
                        item.setData(Qt.ItemDataRole.ForegroundRole, fg)
                    bg = _DIGNITY_BG.get(dignity)
                    if bg:
                        item.setData(Qt.ItemDataRole.BackgroundRole, bg)
                    gui.dignities_table.setItem(i, j + 1, item)

        except Exception:
            pass
