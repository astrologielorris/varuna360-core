# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Aspects panel controller — Phase 4 W2.6.

Migration source: managers/panel_update_manager.py:615-706.

7×9 aspect matrix (rows: 7 planets that cast aspects; columns: 9 planets
including Rahu/Ketu that receive). Cells show virupas with Yuti markers
for same-sign conjunctions.

Sidereal-aware for Yuti detection only — the aspect math itself is
mode-agnostic, but same-sign conjunctions need sidereal sign values.

Aspects are D-1 only (no varga subscription) per project convention.
"""

from PySide6.QtWidgets import QTableWidgetItem
from PySide6.QtCore import Qt

from state import PanelControllerBase

_ROW_PLANETS = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]
_COL_PLANETS = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"]


class AspectsController(PanelControllerBase):
    """Subscribes to active_chart + aditya_mode events."""

    def __init__(self, gui):
        super().__init__(gui=gui, lazy=False)

    def _on_chart_changed(self):
        self._refresh()

    def _on_mode_changed(self):
        self._refresh()

    def _refresh(self):
        gui = self._gui
        if not hasattr(gui, "aspects_table"):
            return

        chart = getattr(self._state, 'active_chart', None) if self._state else None
        if not chart:
            return
        base_planets = chart
        if not base_planets:
            return

        gui.aspects_table.clearContents()

        try:
            from AI_tools.analysis.AI_aspects import calculate_all_aspects

            aspects_data = calculate_all_aspects(base_planets)

            aspect_lookup = {}
            for asp in aspects_data.get("aspects", []):
                key = (asp["aspecting"], asp["aspected"])
                aspect_lookup[key] = asp["virupas"]

            # Build sign lookup from Chart for Yuti detection
            sign_lookup = {}
            rashi = chart.rashi()
            rashi_planets = rashi.planets()
            for planet_name in _COL_PLANETS:
                try:
                    p = rashi_planets[planet_name]
                    sign_lookup[planet_name] = p.sign_name()
                except (KeyError, TypeError):
                    pass

            highlight_cells = set()

            for row_idx, aspecting in enumerate(_ROW_PLANETS):
                for col_idx, aspected in enumerate(_COL_PLANETS):
                    if aspecting == aspected:
                        item = QTableWidgetItem("-")
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                        gui.aspects_table.setItem(row_idx, col_idx, item)
                    else:
                        asp_sign = sign_lookup.get(aspecting, "")
                        ted_sign = sign_lookup.get(aspected, "")
                        if asp_sign and ted_sign and asp_sign == ted_sign:
                            item = QTableWidgetItem("Y")
                            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                            highlight_cells.add((row_idx, col_idx))
                        else:
                            vr = aspect_lookup.get((aspecting, aspected), 0)
                            if vr >= 45:
                                item = QTableWidgetItem(f"{vr:.0f}")
                                highlight_cells.add((row_idx, col_idx))
                            elif vr > 0:
                                item = QTableWidgetItem(f"{vr:.0f}")
                            else:
                                item = QTableWidgetItem(".")
                            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                        gui.aspects_table.setItem(row_idx, col_idx, item)

            if hasattr(gui, "aspects_delegate"):
                gui.aspects_delegate.update_highlights(highlight_cells)
                gui.aspects_table.viewport().update()

        except Exception as e:
            import traceback
            print(f"Error updating Aspects: {e}")
            traceback.print_exc()
