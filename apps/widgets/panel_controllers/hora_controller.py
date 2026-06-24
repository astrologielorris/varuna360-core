# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Hora panel controller — Phase 4 W2.2.

Migration source: managers/panel_update_manager.py:1332-1416.
Sign resolution is handled by get_chart_retinue via get_planet_sign_index()
from the Chart object (SPEC-ZOD-002). No manual zodiac math here.
"""

from PySide6.QtWidgets import QTableWidgetItem
from PySide6.QtCore import Qt

from state import PanelControllerBase

_HORA_COLORS_DARK = {
    "Aditya": ("#5C3D10", "#FFD54F"),
    "Naga":   ("#10354D", "#80DEEA"),
}
_HORA_COLORS_LIGHT = {
    "Aditya": ("#FFF3E0", "#E65100"),
    "Naga":   ("#E0F7FA", "#006064"),
}
_PLANET_SYMBOLS = {
    "Ascendant": "Asc", "Sun": "☉", "Moon": "☽", "Mars": "♂",
    "Mercury": "☿", "Jupiter": "♃", "Venus": "♀", "Saturn": "♄",
    "Rahu": "☊", "Ketu": "☋",
}


class HoraController(PanelControllerBase):
    """Subscribes to active_chart, aditya_mode events.

    Hora is computed once per chart and once per mode change. Varga doesn't
    affect hora (hora IS the H2 varga itself).
    """

    def __init__(self, gui):
        super().__init__(gui=gui, lazy=False)

    def _on_chart_changed(self):
        self._refresh()

    def _on_mode_changed(self):
        self._refresh()

    def _on_theme_changed(self):
        self._refresh()

    def _refresh(self):
        gui = self._gui
        if not hasattr(gui, "hora_table"):
            return

        chart = getattr(self._state, 'active_chart', None) if self._state else None
        if not chart:
            return
        base_planets = chart
        if not base_planets:
            return

        gui.hora_table.clearContents()

        try:
            from AI_tools.AI_main_function.retinue import get_chart_retinue
            from PySide6.QtGui import QFont, QColor, QBrush
            from ui.qt_theme import scaled_size, scaled_area_size, is_light_theme

            light = is_light_theme()
            hora_colors = _HORA_COLORS_LIGHT if light else _HORA_COLORS_DARK
            default_cell = ("#F5F5F5", "#333333") if light else ("#2A2A2A", "#FFFFFF")

            aditya_mode = self._state.aditya_mode
            ayanamsa_offset = 0.0
            if aditya_mode == "sidereal":
                ayanamsa_offset = getattr(gui, "chart_ayanamsa_offset", 0.0)
            tropical_mode = (aditya_mode == "tropical_classic")

            chart_data = get_chart_retinue(
                base_planets,
                ayanamsa_offset=ayanamsa_offset,
                tropical_mode=tropical_mode,
            )
            planets = chart_data["planets"]
            summary = chart_data["summary"]

            gui.hora_table.setRowCount(len(planets) + 1)
            bold = QFont()
            bold.setBold(True)

            for i, r in enumerate(planets):
                side = r["hora"]["side"]
                bg_hex, fg_hex = hora_colors.get(side, default_cell)
                bg = QBrush(QColor(bg_hex))
                fg = QColor(fg_hex)

                sym = _PLANET_SYMBOLS.get(r["planet"], "")
                item0 = QTableWidgetItem(f"{sym} {r['planet']}")
                item0.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                item0.setBackground(bg)
                item0.setForeground(fg)
                gui.hora_table.setItem(i, 0, item0)

                item1 = QTableWidgetItem(r["hora"]["being_name"])
                item1.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                item1.setBackground(bg)
                item1.setForeground(fg)
                item1.setFont(bold)
                gui.hora_table.setItem(i, 1, item1)

                ruler = "☉ Aditya" if side == "Aditya" else "☽ Naga"
                item2 = QTableWidgetItem(ruler)
                item2.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
                item2.setBackground(bg)
                item2.setForeground(fg)
                gui.hora_table.setItem(i, 2, item2)

            ha = summary["hora"]["aditya_side"]
            hn = summary["hora"]["naga_side"]
            summary_text = f"☉ Aditya: {ha['count']}   |   ☽ Naga: {hn['count']}"
            summary_item = QTableWidgetItem(summary_text)
            summary_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            bold_lg = QFont()
            bold_lg.setBold(True)
            bold_lg.setPointSize(scaled_area_size("buttons"))
            summary_item.setFont(bold_lg)
            sum_bg = "#E8EAF6" if light else "#1A1A2E"
            sum_fg = "#1A237E" if light else "#E0E0E0"
            summary_item.setBackground(QBrush(QColor(sum_bg)))
            summary_item.setForeground(QColor(sum_fg))
            gui.hora_table.setItem(len(planets), 0, summary_item)
            gui.hora_table.setSpan(len(planets), 0, 1, 3)

        except Exception as e:
            print(f"Error updating Hora table: {e}")
