# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""
Tajika relationships panel controller (Phase 4 W2.10, delegated td-n3h3.13).

Rendering is delegated to the shared fill_relations in
apps/widgets/tajika_grid_widget.py (SPEC-ECL-002 section 9.1): the SR grid's
canonical output replaces the old local copy (ASCII hyphen pair separator,
orb without the degree symbol, SR empty-state text). This controller keeps
only the PanelControllerBase lifecycle and the gui.* widget bindings.

NOT sidereal-aware. Subscribes to active_chart only.
"""

from state import PanelControllerBase


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
        if not hasattr(gui, "tajika_rel_delegate"):
            return

        chart = getattr(self._state, 'active_chart', None) if self._state else None
        if not chart:
            return

        try:
            from AI_tools.AI_main_function.tajika import calculate_all_tajika_aspects
            from apps.widgets.tajika_grid_widget import fill_relations

            result = calculate_all_tajika_aspects(chart)
            fill_relations(gui.tajika_rel_table, gui.tajika_rel_delegate, result)
        except Exception as e:
            import traceback
            print(f"Error updating Tajika Relationships: {e}")
            traceback.print_exc()
