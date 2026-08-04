# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""
Tajika yogas panel controller (Phase 4 W2.11, delegated td-n3h3.13).

Rendering is delegated to the shared fill_yogas in
apps/widgets/tajika_grid_widget.py (SPEC-ECL-002 section 9.1): the SR grid's
canonical HTML replaces the old local copy. Intended changes vs the old
controller rendering: no title header, no summary footer, no out-of-orb
(Bhavishyata) highlighting, SR category colors and empty-state texts.
This controller keeps only the PanelControllerBase lifecycle, the gui.*
widget binding, and the refresh_theme() hook (re-render under the current
palette; fill_yogas reads get_theme_colors() at call time).

NOT sidereal-aware. Subscribes to active_chart only.
"""

from state import PanelControllerBase


class TajikaYogasController(PanelControllerBase):
    """Subscribes to active_chart events. Eager.

    Final controller in the W2 migration; completes the dissolution of
    panel_update_manager into self-updating PanelControllers.
    """

    def __init__(self, gui):
        super().__init__(gui=gui, lazy=False)

    def _on_chart_changed(self):
        self._refresh()

    def _refresh(self):
        gui = self._gui
        if not hasattr(gui, "tajika_placeholder"):
            return

        chart = getattr(self._state, 'active_chart', None) if self._state else None
        if not chart:
            gui.tajika_placeholder.setHtml("")
            return

        try:
            from AI_tools.AI_main_function.tajika import calculate_all_tajika_aspects
            from AI_tools.AI_main_function.tajika_yogas import detect_all_tajika_yogas
            from apps.widgets.tajika_grid_widget import fill_yogas

            result = calculate_all_tajika_aspects(chart)
            try:
                yogas = detect_all_tajika_yogas(chart, result)
            except Exception:
                yogas = None
            fill_yogas(gui.tajika_placeholder, yogas)
        except Exception as e:
            import traceback
            print(f"Error updating Tajika Yogas: {e}")
            traceback.print_exc()

    def refresh_theme(self):
        """Re-render the HTML with current theme colors (SPEC-THM-001 P-006)."""
        self._refresh()
