# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Elements panel controller — Phase 4 W1 proof-of-concept.

Self-updating Elements table that subscribes to ChartState.state_changed and
re-renders on chart, mode, or varga mutations. Replaces the push-based
PanelUpdateManager.update_elements() flow.

Migration source: managers/panel_update_manager.py:367-488 (extracted verbatim
into _refresh; structural logic unchanged).

Read pattern:
- Chart data: self._state.active_chart (Chart object, source of truth)
- Varga data + aditya_mode + ayanamsa_offset: self._gui (legacy attrs).
"""

from PySide6.QtWidgets import QTableWidgetItem
from PySide6.QtCore import Qt

from state import PanelControllerBase


class ElementsController(PanelControllerBase):
    """Subscribes to active_chart + aditya_mode events.
    Always uses D1 regardless of active varga.
    """

    def __init__(self, gui):
        super().__init__(gui=gui, lazy=False)

    def _on_chart_changed(self):
        self._refresh()

    def _on_mode_changed(self):
        self._refresh()

    def _refresh(self):
        gui = self._gui
        if not hasattr(gui, "elements_table"):
            return

        # Read base planets from ChartState via Chart → dict bridge
        chart = getattr(self._state, 'active_chart', None) if self._state else None
        if not chart:
            return

        gui.elements_table.clearContents()

        try:
            from AI_tools.AI_main_function.dominant import get_dominant_elements

            planets = chart

            elements_data = get_dominant_elements(
                planets,
                luminary_weight=1.5,
            )

            element_display = {
                "Fire": ("🔥", "#FF6B6B"),
                "Earth": ("🌍", "#8B7355"),
                "Air": ("💨", "#87CEEB"),
                "Water": ("💧", "#4169E1"),
            }

            highlight_cells = set()

            for i, (element, raw_count, weighted, percent, planet_list) in enumerate(elements_data["dominant_elements"]):
                if i >= 4:
                    break

                symbol, _ = element_display.get(element, ("", "#FFFFFF"))

                dominant_marker = " ★" if percent >= 30 else ""
                elem_text = f"{symbol} {element}{dominant_marker}"
                item0 = QTableWidgetItem(elem_text)
                item0.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                if percent >= 30:
                    item0.setForeground(Qt.GlobalColor.yellow)
                    for c in range(3):
                        highlight_cells.add((i, c))
                gui.elements_table.setItem(i, 0, item0)

                item1 = QTableWidgetItem(f"{percent:.1f}%")
                item1.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
                if percent >= 30:
                    item1.setForeground(Qt.GlobalColor.yellow)
                gui.elements_table.setItem(i, 1, item1)

                planet_display = []
                for p in planet_list:
                    if p == "Sun":
                        planet_display.append("☉Sun")
                    elif p == "Moon":
                        planet_display.append("☽Moon")
                    else:
                        planet_display.append(p)
                planets_text = ", ".join(planet_display)
                item2 = QTableWidgetItem(planets_text)
                item2.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                gui.elements_table.setItem(i, 2, item2)

            displayed = len(elements_data["dominant_elements"])
            if displayed < 4:
                all_elements = ["Fire", "Earth", "Air", "Water"]
                present = [e[0] for e in elements_data["dominant_elements"]]
                missing = [e for e in all_elements if e not in present]

                for j, element in enumerate(missing):
                    row = displayed + j
                    if row >= 4:
                        break
                    symbol, _ = element_display.get(element, ("", "#FFFFFF"))
                    item0 = QTableWidgetItem(f"{symbol} {element}")
                    item0.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                    gui.elements_table.setItem(row, 0, item0)

                    item1 = QTableWidgetItem("0.0%")
                    item1.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
                    gui.elements_table.setItem(row, 1, item1)

                    item2 = QTableWidgetItem("—")
                    item2.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                    gui.elements_table.setItem(row, 2, item2)

            if hasattr(gui, "elements_delegate"):
                gui.elements_delegate.update_highlights(highlight_cells)
            gui.elements_table.viewport().update()

        except Exception as e:
            print(f"Error updating Elements: {e}")
            import traceback
            traceback.print_exc()
