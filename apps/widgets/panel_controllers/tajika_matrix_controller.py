# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""
Tajika matrix panel controller (Phase 4 W2.9, delegated td-n3h3.13).

Rendering is delegated to the shared fill_matrix in
apps/widgets/tajika_grid_widget.py (SPEC-ECL-002 section 9.1): the SR grid's
canonical output replaces the old local copy (ASCII '--' diagonal, SR tooltip
format without the degree symbol). This controller keeps only the
PanelControllerBase lifecycle and the gui.* widget bindings.

NOT sidereal-aware: Tajika aspects are angular relationships, mode-agnostic.
Subscribes only to active_chart events.
"""

from state import PanelControllerBase


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
        if not hasattr(gui, "tajika_delegate"):
            return

        chart = getattr(self._state, 'active_chart', None) if self._state else None
        if not chart:
            return

        try:
            from AI_tools.AI_main_function.tajika import calculate_all_tajika_aspects
            from apps.widgets.tajika_grid_widget import fill_matrix

            result = calculate_all_tajika_aspects(chart)
            fill_matrix(gui.tajika_matrix_table, gui.tajika_delegate, result)
        except Exception as e:
            import traceback
            print(f"Error updating Tajika Matrix: {e}")
            traceback.print_exc()
