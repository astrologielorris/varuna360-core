# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Tajika relationships panel controller — Phase 4 W2.10.

Migration source: managers/panel_update_manager.py:1053-1176.
Grouped relationship rows (Openly Friendly → Openly Inimical) with shape
icons drawn by tajika_rel_delegate.

NOT sidereal-aware. Subscribes to active_chart only.
"""

from PySide6.QtWidgets import QTableWidgetItem
from PySide6.QtCore import Qt

from state import PanelControllerBase

_ASPECT_TO_SHAPE = {
    "Conjunction": "conjunction",
    "Sextile": "sextile",
    "Square": "square",
    "Trine": "trine",
    "Opposition": "opposition",
}

_REL_GROUP_TO_CATEGORY = {
    "Openly Friendly": "FRIENDLY_OPEN",
    "Secretly Friendly": "FRIENDLY_SECRET",
    "Neutral": "NEUTRAL",
    "Secretly Inimical": "INIMICAL_SECRET",
    "Openly Inimical": "INIMICAL_OPEN",
}


class TajikaRelationshipsController(PanelControllerBase):
    """Subscribes to active_chart events. Eager."""

    def __init__(self, gui):
        super().__init__(gui=gui, lazy=False)

    def _on_chart_changed(self):
        self._refresh()

    def _refresh(self):
        gui = self._gui
        if not hasattr(gui, "tajika_rel_table"):
            return

        chart = getattr(self._state, 'active_chart', None) if self._state else None
        if not chart:
            return
        base_planets = chart

        gui.tajika_rel_table.clearContents()
        gui.tajika_rel_table.setRowCount(0)

        try:
            from AI_tools.AI_main_function.tajika import calculate_all_tajika_aspects

            result = calculate_all_tajika_aspects(base_planets)
            aspects = result["aspects_within_orb"]

            if not aspects:
                gui.tajika_rel_table.setRowCount(1)
                item = QTableWidgetItem("No Tajika aspects within orb")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                gui.tajika_rel_table.setItem(0, 0, item)
                gui.tajika_rel_table.setSpan(0, 0, 1, 5)
                return

            groups = [
                ("Openly Friendly", []),
                ("Secretly Friendly", []),
                ("Neutral", []),
                ("Secretly Inimical", []),
                ("Openly Inimical", []),
            ]
            group_dict = {name: lst for name, lst in groups}
            for asp in aspects:
                rel = asp.get("relationship", "Neutral")
                if rel in group_dict:
                    group_dict[rel].append(asp)
                else:
                    group_dict["Neutral"].append(asp)

            total_rows = 0
            for name, lst in groups:
                if lst:
                    total_rows += 1 + len(lst)

            gui.tajika_rel_table.setRowCount(total_rows)

            cell_categories = {}
            cell_shapes = {}
            row = 0

            for group_name, group_aspects in groups:
                if not group_aspects:
                    continue

                cat = _REL_GROUP_TO_CATEGORY.get(group_name, "NEUTRAL")

                header_text = f"{group_name} ({len(group_aspects)})"
                header_item = QTableWidgetItem(header_text)
                header_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                gui.tajika_rel_table.setItem(row, 0, header_item)
                gui.tajika_rel_table.setSpan(row, 0, 1, 5)
                for c in range(5):
                    cell_categories[(row, c)] = cat
                row += 1

                for asp in group_aspects:
                    b1 = asp["body1"]
                    b2 = asp["body2"]
                    aspect_name = asp["aspect"]
                    vr = asp["virupas"]
                    dist = asp["distance_from_exact"]

                    shape_item = QTableWidgetItem("")
                    shape_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    gui.tajika_rel_table.setItem(row, 0, shape_item)
                    shape_key = _ASPECT_TO_SHAPE.get(aspect_name)
                    if shape_key:
                        cell_shapes[(row, 0)] = shape_key
                    cell_categories[(row, 0)] = cat

                    pair_item = QTableWidgetItem(f"{b1}–{b2}")
                    pair_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                    gui.tajika_rel_table.setItem(row, 1, pair_item)
                    cell_categories[(row, 1)] = cat

                    name_item = QTableWidgetItem(aspect_name)
                    name_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
                    gui.tajika_rel_table.setItem(row, 2, name_item)
                    cell_categories[(row, 2)] = cat

                    vr_item = QTableWidgetItem(f"{vr:.0f}")
                    vr_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
                    gui.tajika_rel_table.setItem(row, 3, vr_item)
                    cell_categories[(row, 3)] = cat

                    orb_item = QTableWidgetItem(f"{dist:.1f}°")
                    orb_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
                    gui.tajika_rel_table.setItem(row, 4, orb_item)
                    cell_categories[(row, 4)] = cat

                    row += 1

            if hasattr(gui, "tajika_rel_delegate"):
                gui.tajika_rel_delegate.update_categories(cell_categories)
                gui.tajika_rel_delegate.update_shapes(cell_shapes)
                gui.tajika_rel_table.viewport().update()

        except Exception as e:
            import traceback
            print(f"Error updating Tajika Relationships: {e}")
            traceback.print_exc()
