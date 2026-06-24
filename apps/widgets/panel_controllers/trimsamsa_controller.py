# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Trimsamsa panel controller — Phase 4 W2.3.

Migration source: managers/panel_update_manager.py:1422-1521.
Same retinue-based pattern as hora; 4-column being-type breakdown.
"""

from PySide6.QtWidgets import QTableWidgetItem
from PySide6.QtCore import Qt

from state import PanelControllerBase

_BEING_TYPE_COLORS_DARK = {
    "Gandharva": ("#5C1A1A", "#E57373"),
    "Rakshasa":  ("#4D4D10", "#F0C75E"),
    "Rishi":     ("#3D1A5C", "#CE93D8"),
    "Yaksha":    ("#4D3818", "#D4A76A"),
    "Apsara":    ("#102E5C", "#64B5F6"),
}
_BEING_TYPE_COLORS_LIGHT = {
    "Gandharva": ("#FFEBEE", "#B71C1C"),
    "Rakshasa":  ("#FFFDE7", "#F57F17"),
    "Rishi":     ("#F3E5F5", "#6A1B9A"),
    "Yaksha":    ("#FBE9E7", "#4E342E"),
    "Apsara":    ("#E3F2FD", "#1565C0"),
}
_PLANET_SYMBOLS = {
    "Ascendant": "Asc", "Sun": "☉", "Moon": "☽", "Mars": "♂",
    "Mercury": "☿", "Jupiter": "♃", "Venus": "♀", "Saturn": "♄",
    "Rahu": "☊", "Ketu": "☋",
}


class TrimsamsaController(PanelControllerBase):
    """Subscribes to active_chart, aditya_mode events.

    Trimsamsa (D-30 varga) is computed once per chart + mode change.
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
        if not hasattr(gui, "trimsamsa_table"):
            return

        chart = getattr(self._state, 'active_chart', None) if self._state else None
        if not chart:
            return
        base_planets = chart
        if not base_planets:
            return

        gui.trimsamsa_table.clearContents()

        try:
            from AI_tools.AI_main_function.retinue import get_chart_retinue
            from PySide6.QtGui import QFont, QColor, QBrush
            from ui.qt_theme import scaled_size, scaled_area_size, is_light_theme

            light = is_light_theme()
            being_type_colors = _BEING_TYPE_COLORS_LIGHT if light else _BEING_TYPE_COLORS_DARK
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

            gui.trimsamsa_table.setRowCount(len(planets) + 1)
            bold = QFont()
            bold.setBold(True)

            for i, r in enumerate(planets):
                btype = r["trimsamsa"]["being_type"]
                element = r["trimsamsa"]["element"]
                bg_hex, fg_hex = being_type_colors.get(btype, default_cell)
                bg = QBrush(QColor(bg_hex))
                fg = QColor(fg_hex)

                sym = _PLANET_SYMBOLS.get(r["planet"], "")
                item0 = QTableWidgetItem(f"{sym} {r['planet']}")
                item0.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                item0.setBackground(bg)
                item0.setForeground(fg)
                gui.trimsamsa_table.setItem(i, 0, item0)

                item1 = QTableWidgetItem(r["trimsamsa"]["being_name"])
                item1.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                item1.setBackground(bg)
                item1.setForeground(fg)
                item1.setFont(bold)
                gui.trimsamsa_table.setItem(i, 1, item1)

                item2 = QTableWidgetItem(btype)
                item2.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
                item2.setBackground(bg)
                item2.setForeground(fg)
                gui.trimsamsa_table.setItem(i, 2, item2)

                item3 = QTableWidgetItem(element)
                item3.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
                item3.setBackground(bg)
                item3.setForeground(fg)
                gui.trimsamsa_table.setItem(i, 3, item3)

            ts = summary["trimsamsa"]
            type_order = ["Gandharva", "Rakshasa", "Rishi", "Yaksha", "Apsara"]
            key_order = ["gandharva", "rakshasa", "rishi", "yaksha", "apsara"]
            parts = []
            for label, key in zip(type_order, key_order):
                c = ts[key]["count"]
                if c > 0:
                    parts.append(f"{label[:4]}:{c}")
            dominant = summary.get("dominant_force", "")
            summary_text = "  ".join(parts) + f"  ▸ {dominant}" if parts else "No data"
            summary_item = QTableWidgetItem(summary_text)
            summary_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            bold_lg = QFont()
            bold_lg.setBold(True)
            bold_lg.setPointSize(scaled_area_size("buttons"))
            summary_item.setFont(bold_lg)
            dom_bg, dom_fg = being_type_colors.get(
                dominant,
                ("#E8EAF6", "#1A237E") if light else ("#1A1A2E", "#E0E0E0"),
            )
            summary_item.setBackground(QBrush(QColor(dom_bg)))
            summary_item.setForeground(QColor(dom_fg))
            gui.trimsamsa_table.setItem(len(planets), 0, summary_item)
            gui.trimsamsa_table.setSpan(len(planets), 0, 1, 4)

        except Exception as e:
            print(f"Error updating Trimsamsa table: {e}")
