# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Modality panel controller — Phase 4 W2.1.

Migration source: managers/panel_update_manager.py:489-609.
Same shape as ElementsController; 3 rows (Moveable/Fixed/Dual) vs 4 elements.
Supports yoga mode toggle: Movable/Fixed/Dual <-> Rajju/Musala/Nala.
"""

from PySide6.QtWidgets import QTableWidgetItem, QMessageBox
from PySide6.QtCore import Qt

from state import PanelControllerBase


class ModalityController(PanelControllerBase):
    """Subscribes to active_chart + aditya_mode events.
    Always uses D1 regardless of active varga.
    """

    def __init__(self, gui):
        super().__init__(gui=gui, lazy=False)
        self._yoga_mode = False
        self._last_modality_data = None

    def _on_chart_changed(self):
        self._refresh()

    def _on_mode_changed(self):
        self._refresh()

    def toggle_yoga_mode(self):
        self._yoga_mode = not self._yoga_mode
        self._refresh()

    @property
    def yoga_mode(self):
        return self._yoga_mode

    def _refresh(self):
        gui = self._gui
        if not hasattr(gui, "modality_table"):
            return

        chart = getattr(self._state, 'active_chart', None) if self._state else None
        if not chart:
            return

        gui.modality_table.clearContents()

        try:
            from AI_tools.AI_main_function.dominant import get_dominant_modality
            from AI_tools.AI_main_function.constants import (
                MODALITY_DESCRIPTIONS, MODALITY_YOGA_NAMES,
                MODALITY_YOGA_SHORT, MODALITY_YOGA_FULL,
            )

            modality_data = get_dominant_modality(chart, luminary_weight=1.5)
            self._last_modality_data = modality_data

            modality_display = {
                "Moveable": ("⚡", "#FF9F43"),
                "Fixed": ("🔒", "#4ECDC4"),
                "Dual": ("⚖️", "#A29BFE"),
            }

            highlight_cells = set()

            if self._yoga_mode:
                gui.modality_table.setHorizontalHeaderLabels(["Yoga", "%", "Description"])
            else:
                gui.modality_table.setHorizontalHeaderLabels(["Modality", "%", "Planets"])

            for i, (modality, raw_count, weighted, percent, planet_list) in enumerate(modality_data["dominant_modalities"]):
                if i >= 3:
                    break

                symbol, _ = modality_display.get(modality, ("", "#FFFFFF"))

                if self._yoga_mode:
                    yoga_name = MODALITY_YOGA_NAMES.get(modality, modality)
                    dominant_marker = " ★" if percent >= 40 else ""
                    mod_text = f"{symbol} {yoga_name}{dominant_marker}"
                else:
                    dominant_marker = " ★" if percent >= 40 else ""
                    mod_text = f"{symbol} {modality}{dominant_marker}"

                item0 = QTableWidgetItem(mod_text)
                item0.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                if percent >= 40:
                    item0.setForeground(Qt.GlobalColor.yellow)
                    for c in range(3):
                        highlight_cells.add((i, c))
                gui.modality_table.setItem(i, 0, item0)

                item1 = QTableWidgetItem(f"{percent:.1f}%")
                item1.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
                if percent >= 40:
                    item1.setForeground(Qt.GlobalColor.yellow)
                gui.modality_table.setItem(i, 1, item1)

                if self._yoga_mode:
                    desc = MODALITY_YOGA_SHORT.get(modality, "")
                    item2 = QTableWidgetItem(desc)
                    item2.setData(Qt.ItemDataRole.UserRole, modality)
                else:
                    planet_display = []
                    for p in planet_list:
                        if p == "Sun":
                            planet_display.append("☉Sun")
                        elif p == "Moon":
                            planet_display.append("☽Moon")
                        else:
                            planet_display.append(p)
                    planets_text = ", ".join(planet_display)
                    desc = MODALITY_DESCRIPTIONS.get(modality, "")
                    if desc:
                        planets_text += f"\n{desc}"
                    item2 = QTableWidgetItem(planets_text)
                    item2.setData(Qt.ItemDataRole.UserRole, modality)

                item2.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                gui.modality_table.setItem(i, 2, item2)

            displayed = len(modality_data["dominant_modalities"])
            if displayed < 3:
                all_modalities = ["Moveable", "Fixed", "Dual"]
                present = [m[0] for m in modality_data["dominant_modalities"]]
                missing = [m for m in all_modalities if m not in present]

                for j, modality in enumerate(missing):
                    row = displayed + j
                    if row >= 3:
                        break
                    symbol, _ = modality_display.get(modality, ("", "#FFFFFF"))

                    if self._yoga_mode:
                        yoga_name = MODALITY_YOGA_NAMES.get(modality, modality)
                        item0 = QTableWidgetItem(f"{symbol} {yoga_name}")
                    else:
                        item0 = QTableWidgetItem(f"{symbol} {modality}")
                    item0.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                    gui.modality_table.setItem(row, 0, item0)

                    item1 = QTableWidgetItem("0.0%")
                    item1.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
                    gui.modality_table.setItem(row, 1, item1)

                    if self._yoga_mode:
                        desc = MODALITY_YOGA_SHORT.get(modality, "")
                    else:
                        desc = MODALITY_DESCRIPTIONS.get(modality, "")
                    item2 = QTableWidgetItem(f"{desc}" if desc else "")
                    item2.setData(Qt.ItemDataRole.UserRole, modality)
                    item2.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                    gui.modality_table.setItem(row, 2, item2)

            if hasattr(gui, "modality_delegate"):
                gui.modality_delegate.update_highlights(highlight_cells)
            gui.modality_table.viewport().update()

        except Exception as e:
            print(f"Error updating Modality: {e}")
            import traceback
            traceback.print_exc()

    @staticmethod
    def show_yoga_detail(gui, row):
        """Show full yoga description for the clicked row."""
        from AI_tools.AI_main_function.constants import (
            MODALITY_YOGA_NAMES, MODALITY_YOGA_FULL,
        )
        table = gui.modality_table
        item = table.item(row, 2)
        if not item:
            return
        modality = item.data(Qt.ItemDataRole.UserRole)
        if not modality:
            return

        yoga_name = MODALITY_YOGA_NAMES.get(modality, modality)
        full_text = MODALITY_YOGA_FULL.get(modality, "")
        if not full_text:
            return

        msg = QMessageBox(gui)
        msg.setWindowTitle(f"{yoga_name} Yoga ({modality})")
        msg.setText(full_text)
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setStyleSheet("QMessageBox { min-width: 500px; }")
        msg.exec()
