# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Tajika matrix panel controller — Phase 4 W2.9.

Migration source: managers/panel_update_manager.py:952-1038.
11×11 aspect matrix with geometric shapes drawn by tajika_delegate.

NOT sidereal-aware: Tajika aspects are angular relationships, mode-agnostic.
Subscribes only to active_chart events.

Note: Tajika tab is shown via the Vedic/Tajika toggle in info_panels.py.
The toggle calls panel_manager.update_tajika_matrix() directly (strangler
fig). This controller fires on chart load, covering the initial render.
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

_REL_TO_CATEGORY = {
    "Openly Friendly": "FRIENDLY_OPEN",
    "Secretly Friendly": "FRIENDLY_SECRET",
    "Openly Inimical": "INIMICAL_OPEN",
    "Secretly Inimical": "INIMICAL_SECRET",
    "Neutral": "NEUTRAL",
}


class TajikaMatrixController(PanelControllerBase):
    """Subscribes to active_chart events. Eager (not lazy)."""

    def __init__(self, gui):
        super().__init__(gui=gui, lazy=False)

    def _on_chart_changed(self):
        self._refresh()

    def _refresh(self):
        gui = self._gui
        if not hasattr(gui, "tajika_matrix_table"):
            return

        chart = getattr(self._state, 'active_chart', None) if self._state else None
        if not chart:
            return
        base_planets = chart

        gui.tajika_matrix_table.clearContents()

        try:
            from AI_tools.AI_main_function.tajika import (
                calculate_all_tajika_aspects, TAJIKA_PLANETS, TAJIKA_SHORT_NAMES,
            )

            result = calculate_all_tajika_aspects(base_planets)
            matrix = result["matrix"]
            bodies = TAJIKA_PLANETS

            cell_categories = {}
            cell_shapes = {}

            for row_idx, body1 in enumerate(bodies):
                for col_idx, body2 in enumerate(bodies):
                    item = QTableWidgetItem("")
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

                    if body1 == body2:
                        item.setText("──")
                        cell_shapes[(row_idx, col_idx)] = "diagonal"
                        gui.tajika_matrix_table.setItem(row_idx, col_idx, item)
                        continue

                    record = matrix.get((body1, body2))
                    if record:
                        aspect_name = record.get("aspect", "")
                        symbol = record.get("symbol", "")
                        virupas = record.get("virupas", 0)
                        rel = record.get("relationship", "")
                        dist = record.get("distance_from_exact", 0)

                        item.setText(symbol)

                        shape = _ASPECT_TO_SHAPE.get(aspect_name)
                        if shape:
                            cell_shapes[(row_idx, col_idx)] = shape

                        short1 = TAJIKA_SHORT_NAMES.get(body1, body1)
                        short2 = TAJIKA_SHORT_NAMES.get(body2, body2)
                        item.setToolTip(
                            f"{short1}–{short2}: {aspect_name}\n"
                            f"{virupas:.0f} VR | {dist:.1f}° from exact\n"
                            f"{rel}"
                        )

                        if virupas >= 45:
                            cell_categories[(row_idx, col_idx)] = "STRONG"
                        elif rel in _REL_TO_CATEGORY:
                            cell_categories[(row_idx, col_idx)] = _REL_TO_CATEGORY[rel]

                    gui.tajika_matrix_table.setItem(row_idx, col_idx, item)

            if hasattr(gui, "tajika_delegate"):
                gui.tajika_delegate.update_categories(cell_categories)
                gui.tajika_delegate.update_shapes(cell_shapes)
                gui.tajika_matrix_table.viewport().update()

        except Exception as e:
            import traceback
            print(f"Error updating Tajika Matrix: {e}")
            traceback.print_exc()
