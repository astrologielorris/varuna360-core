# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Nabhasa Yogas panel controller.

Frames the active chart (sidereal rebuild at THIS seam, hardening H3), calls the
pure Nabhasa adapter, and hands the result to the NabhasaWidget for rendering.
All presentation lives in the widget; this controller is the compute + wiring
seam. Mirrors interchange_controller.py.
"""

from state import PanelControllerBase


class NabhasaController(PanelControllerBase):
    """Subscribes to active_chart + aditya_mode (+ chart_view_style) events.
    Lazy: only refreshes when the Yogas tab is visible.
    """

    def __init__(self, gui):
        super().__init__(gui=gui, lazy=True)
        self._last_result = None

    def _on_chart_changed(self):
        self._refresh()

    def _on_mode_changed(self):
        self._refresh()

    def _on_view_changed(self):
        """Chart display style changed: the movable-diagram affordance is only
        meaningful against a diamond/square chart, so grey it out in wheel mode
        (spec §5 / R6). Optional hook fired by PanelControllerBase."""
        widget = getattr(self._gui, "nabhasa_display", None)
        if widget is not None and hasattr(widget, "set_wheel_mode"):
            widget.set_wheel_mode(self._is_wheel())

    def refresh_theme(self):
        """Theme changed: let the widget re-render from cached data (H2)."""
        widget = getattr(self._gui, "nabhasa_display", None)
        if widget is not None and hasattr(widget, "refresh_theme"):
            widget.refresh_theme()

    def _is_wheel(self):
        state = self._state
        return bool(state and getattr(state, "chart_view_style", None) == "wheel")

    def _refresh(self):
        """Recompute the Nabhasa yogas and push them to the widget.

        Kept named ``_refresh`` because the font-scale fan-out (core_gui_qt.py)
        calls it by that name (hardening H10).
        """
        gui = self._gui
        widget = getattr(gui, "nabhasa_display", None)
        if widget is None:
            return

        chart = getattr(self._state, 'active_chart', None) if self._state else None
        if not chart:
            self._last_result = None
            if hasattr(widget, "clear"):
                widget.clear()
            return

        try:
            from AI_tools.AI_main_function.nabhasa import get_nabhasa_yogas

            # Sidereal seam (H3): frame the chart ONCE here before the adapter,
            # so the yoga geometry is read in the displayed frame.
            if self._state and self._state.aditya_mode == "sidereal":
                from core.chart_factory import rebuild_chart
                chart = rebuild_chart(chart, mode="sidereal")

            result = get_nabhasa_yogas(chart)
            self._last_result = result
            widget.refresh(result, wheel_mode=self._is_wheel())

        except Exception as e:
            import traceback
            traceback.print_exc()
            self._last_result = None
            if hasattr(widget, "clear"):
                widget.clear()
            print(f"[nabhasa_controller] refresh failed: {e}")
