# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Interchange (Parivartana) + Final-Dispositor panel controller.

Frames the active chart (sidereal rebuild at THIS seam, hardening H3), computes
the exchange yogas and the final-dispositor themes with the pure engines, and
hands the results to the ParivartanaWidget for rendering. All presentation lives
in the widget; this controller is the compute + wiring seam.
"""

from state import PanelControllerBase


class InterchangeController(PanelControllerBase):
    """Subscribes to active_chart + aditya_mode events.
    Lazy: only refreshes when the Exchange tab is visible.
    """

    def __init__(self, gui):
        super().__init__(gui=gui, lazy=True)
        self._last_result = None
        self._wired = None          # the widget whose THREAD key / cards are connected
        self._switch = None         # the THREAD key's ExchangeChainSwitch (kept alive here)

    # ---- THREAD key + chain focus (SPEC-EXCH-002, td-m79zy) ----------------
    def _wire(self, widget):
        """Connect the widget's THREAD key and card clicks to the chain manager
        once, and keep its lamp on the setting whoever writes it."""
        if getattr(self, "_wired", None) is widget or not hasattr(widget, "thread_pressed"):
            return
        from core import exchange_chain as xc
        from managers.exchange_chain import ExchangeChainSwitch, toggle_focus
        from managers.settings_manager import get_settings
        # Held by the controller: PySide6 keeps a bound method's owner only
        # weakly, so a local switch was collected and the key went dead.
        self._switch = ExchangeChainSwitch(self._gui)
        widget.thread_pressed.connect(self._switch.toggle)
        widget.focus_requested.connect(lambda pair: self._focus(toggle_focus(pair)))
        settings = get_settings()

        def _lamp(_key, _value, w=widget):
            import shiboken6
            if shiboken6.isValid(w):
                w.set_thread_lit(xc.chain_on(settings.get))
        def _style(_key, _value, w=widget):
            import shiboken6
            if shiboken6.isValid(w):
                w.restyle_chains()
        settings.on_changed(xc.KEY_ON, _lamp)
        settings.on_changed(xc.KEY_STYLE, _style)
        widget.destroyed.connect(lambda *_: (settings.remove_on_changed(xc.KEY_ON, _lamp),
                                             settings.remove_on_changed(xc.KEY_STYLE, _style)))
        widget.set_thread_lit(xc.chain_on(settings.get))
        self._wired = widget

    def _dispatch_state_change(self, reason):
        """A new chart or zodiac mode drops the chain focus at once, even while
        the EXCH panel is hidden (the lazy refresh would only run at show)."""
        if reason in ("active_chart", "aditya_mode"):
            from managers.exchange_chain import set_focus
            set_focus(None)
        super()._dispatch_state_change(reason)

    def _focus(self, pair):
        widget = getattr(self._gui, "exchange_display", None)
        if widget is not None and hasattr(widget, "set_focus"):
            widget.set_focus(pair)

    def _on_chart_changed(self):
        self._refresh()

    def _on_mode_changed(self):
        self._refresh()

    def refresh_theme(self):
        """Theme changed: let the widget re-render its cards from cached data.

        Registered in the core_gui_qt theme fan-out (hardening H2) because the
        widget no longer restyles via the removed QTextBrowser stylesheet hook.
        """
        widget = getattr(self._gui, "exchange_display", None)
        if widget is not None and hasattr(widget, "refresh_theme"):
            widget.refresh_theme()

    def _refresh(self):
        """Recompute themes + interchanges and push them to the widget.

        Kept named ``_refresh`` because the font-scale fan-out
        (core_gui_qt.py) calls it by that name (hardening H10).
        """
        gui = self._gui
        widget = getattr(gui, "exchange_display", None)
        if widget is None:
            return

        chart = getattr(self._state, 'active_chart', None) if self._state else None
        if not chart:
            from managers.exchange_chain import set_focus
            set_focus(None)
            self._last_result = None
            if hasattr(widget, "clear"):
                widget.clear()
            return

        try:
            from AI_tools.AI_main_function.interchange import get_all_interchanges
            from AI_tools.AI_main_function.final_dispositor import get_dispositor_themes

            # Sidereal seam (H3): frame the chart ONCE here, then feed the SAME
            # framed object to both engines so the exchange cards and the theme
            # cards can never disagree (spec L11/L12 R4).
            if self._state and self._state.aditya_mode == "sidereal":
                from core.chart_factory import rebuild_chart
                chart = rebuild_chart(chart, mode="sidereal")

            interchanges = get_all_interchanges(chart)
            themes = get_dispositor_themes(chart)
            self._last_result = {"themes": themes, "interchanges": interchanges}
            self._wire(widget)
            from core import exchange_chain as xc
            from managers.exchange_chain import chart_changed
            from apps.widgets.exchange_chain_items import focus
            chart_changed(xc.links_from(interchanges, lambda _p: 0))
            if hasattr(widget, "set_focus"):
                widget.set_focus(focus())
            widget.refresh(themes, interchanges)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self._last_result = None
            if hasattr(widget, "clear"):
                widget.clear()
            print(f"[interchange_controller] refresh failed: {e}")
