# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
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


class AspectsController(PanelControllerBase):
    """Subscribes to active_chart + aditya_mode events."""

    def __init__(self, gui):
        super().__init__(gui=gui, lazy=False)
        # The chart the table currently shows (None = not rendered): the AI
        # capture marks the region 'stale' otherwise (SPEC-AIC-001 INV-2).
        self.rendered_chart = None

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
        self.rendered_chart = None

        try:
            # One calculation for panel, CLI and MCP (SPEC-AIC-001 INV-1):
            # core/capabilities/karakas_aspects.aspect_matrix is get_aspects.
            from core.capabilities.karakas_aspects import aspect_matrix
            grid = aspect_matrix(base_planets)
            for row_idx, row in enumerate(grid["cells"]):
                for col_idx, text in enumerate(row):
                    item = QTableWidgetItem(text)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    gui.aspects_table.setItem(row_idx, col_idx, item)
            highlight_cells = {tuple(rc) for rc in grid["highlight"]}

            if hasattr(gui, "aspects_delegate"):
                gui.aspects_delegate.update_highlights(highlight_cells)
                gui.aspects_table.viewport().update()
            self.rendered_chart = chart

        except Exception as e:
            import traceback
            print(f"Error updating Aspects: {e}")
            traceback.print_exc()
