# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Dignities-in-Vargas panel controller.

Populates the dignities table (Page 3 of the strength_elements_stack)
with planetary dignities across all 16 standard vargas, reusing the
CLI computation from AI_tools.AI_main_function.dignities_in_vargas.
"""

import shiboken6
from PySide6.QtWidgets import QTableWidgetItem, QStyledItemDelegate
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QBrush, QPalette

from state import PanelControllerBase
from ui.dignity_colors import dignity_colors, DIGNITY_CODE_ROLE
from ui.qt_theme import get_theme_colors


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
        option.palette.setColor(
            QPalette.ColorRole.HighlightedText,
            QColor(get_theme_colors()['primary_text']))
        super().paint(painter, option, index)

_PLANET_HEADERS = ["Su", "Mo", "Ma", "Me", "Ju", "Ve", "Sa"]
VARIANT_ROLE = Qt.ItemDataRole.UserRole + 41      # the style of a variant row (D2p, D10r...)


def _muted(th):
    a, b = QColor(th["secondary_text"]), QColor(th["secondary_dark"])
    return QColor(round(a.red() * 0.55 + b.red() * 0.45), round(a.green() * 0.55 + b.green() * 0.45),
                  round(a.blue() * 0.55 + b.blue() * 0.45)).name()



class DignitiesController(PanelControllerBase):
    """Subscribes to active_chart + aditya_mode events.
    Computes dignities across all 16 standard vargas.
    Supports cycling through varga calculation styles via toggle_varga_style().
    """

    def __init__(self, gui):
        super().__init__(gui=gui, lazy=False)
        self._varga_panel = None           # the VARGA panel, given by its builder

    def attach_panel(self, panel):
        """The VARGA panel (page 3 of the Strength stack), passed by the code
        that builds it (create_right_panels), never searched for."""
        self._varga_panel = panel

    # td-m6xyo (SPEC-DIG-001 §4.3): the style is ONE state, the setting
    # chart.varga_style, shared with the varga column, the chart and the CLIs.
    @property
    def varga_style(self):
        from managers.varga_style import current_style
        return current_style()

    @property
    def varga_style_label(self):
        """The header button's state: the style, or "All vargas" (the table view)."""
        from core.varga_codes import VARGA_TABLE, varga_style_short
        from managers.varga_style import table_view
        return varga_style_short(VARGA_TABLE if table_view() else self.varga_style)

    def _panel(self):
        panel = self._varga_panel
        return panel if panel is not None and shiboken6.isValid(panel) else None

    def toggle_varga_style(self):
        """The style button: cycle the shared style (the panel's controller
        relabels the column, redraws the styled varga and refreshes)."""
        panel = self._panel()
        if panel is not None:
            panel.style_controller.cycle()
        else:
            from core.varga_codes import VARGA_STYLE_KEY, next_varga_style
            from managers.settings_manager import get_settings
            get_settings().persist_runtime_change(VARGA_STYLE_KEY, next_varga_style(self.varga_style))
            self._refresh()

    def request_refresh(self):
        """One refresh of the table and the VARGA panel for a style or view
        change, through the same coalesced, visibility-gated bucket as a chart
        or varga change: a style click that also switches the varga refreshes
        once, and a hidden page waits for its next show (R1 review F5)."""
        if not self._effective_visible():     # SPEC-LAYOUT-001 B.6 (fold / tab hold)
            self._pending_chart_refresh = True
            return
        self._schedule_chart_refresh()

    def _on_chart_changed(self):
        self._refresh()

    def _on_varga_changed(self):
        """Never called: its presence puts ``current_varga`` in the coalesced
        chart bucket (state/panel_mixin.py), whose ``_on_chart_changed``
        refreshes the panel (and the table only when the chart or style changed)."""

    def _on_theme_changed(self):
        panel = self._panel()
        if panel is not None:
            panel.refresh_theme()
        self._table_key = None             # the cell colours follow the theme
        self._refresh()

    def _on_mode_changed(self):
        self._refresh()

    def _refresh(self):
        gui = self._gui
        if not hasattr(gui, "dignities_table"):
            return

        chart = getattr(self._state, 'active_chart', None) if self._state else None
        panel = self._panel()
        if panel is not None:
            panel.refresh()
        if not chart:
            gui.dignities_table.clearContents()
            gui.dignities_table.setRowCount(0)
            self._table_key = None
            return
        # td-m6xyo: a varga change reaches here too (the chart bucket); the full
        # 16-varga table only depends on the chart and the style (~37 ms)
        style = self.varga_style
        key = (getattr(self._state, 'aditya_mode', None), style)
        last = getattr(self, '_table_key', None)
        if (last is not None and last[0] is chart and last[1] == key
                and gui.dignities_table.rowCount()):
            return
        self._table_key = (chart, key)

        gui.dignities_table.clearContents()

        try:
            from AI_tools.AI_main_function.dignities_in_vargas import compute_dignities_table
            rows = compute_dignities_table(chart, varga_style=style)
            th = get_theme_colors()

            gui.dignities_table.setRowCount(len(rows))

            for i, row in enumerate(rows):
                varga_item = QTableWidgetItem(row["label"])
                varga_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
                if row.get("variant"):     # a styled row (D2p, D10r) in place of its classical one
                    varga_item.setData(VARIANT_ROLE, row["variant"])
                    varga_item.setForeground(QBrush(QColor(_muted(th))))
                    f = varga_item.font()
                    f.setItalic(True)
                    varga_item.setFont(f)
                gui.dignities_table.setItem(i, 0, varga_item)

                for j, dignity in enumerate(row["dignities"]):
                    item = QTableWidgetItem(dignity)
                    item.setData(DIGNITY_CODE_ROLE, dignity)  # INV-3: the code
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
                    colors = dignity_colors(dignity)
                    if colors:
                        bg, fg = colors
                        item.setForeground(QBrush(QColor(fg)))
                        item.setBackground(QBrush(QColor(bg)))
                    gui.dignities_table.setItem(i, j + 1, item)

        except Exception:
            pass
