# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Panel Controller Base — Layer B-to-D bridge for self-updating panels.

Subscribers to ChartState.state_changed. Each subclass owns the update logic
for one display panel; it reads from state and writes to a widget reference.

Phase 4: foundation class. Phase 5 will promote controllers to widget classes.

Pre-mortem fixes embedded:
- pm-20260503-002: QTimer.singleShot(0, handler) yields between heavy compute
  to prevent GUI freeze when 10+ panels respond to state_changed
- pm-20260503-003: lazy panels (avastha, shame) defer until set_visible(True);
  the trigger is a button click handler in core_gui_qt.py, not QWidget.shown
- pm-20260503-009: subclass end-to-end test pattern in test_panel_controllers.py
"""

from PySide6.QtCore import QTimer


class PanelControllerBase:
    """Abstract base for ChartState-subscribed panel controllers.

    Subclasses implement:
        _on_chart_changed(self) — required, called when active_chart mutates
        _on_mode_changed(self)  — optional, called when aditya_mode flips
        _on_varga_changed(self) — optional, called when current_varga changes
        _on_view_changed(self)  — optional, called when chart_view_style changes

    Lazy mode:
        When lazy=True, _on_chart_changed and _on_mode_changed are deferred
        until set_visible(True) is called. This mirrors the pre-Phase-4
        avastha/shame behavior where computation only happens on tab show.

    None-safety contract:
        Every subclass MUST handle state.active_chart=None gracefully —
        clear the widget and return. Tests enforce this.

    Note: This is a plain Python class (not QObject). ChartState IS the
    QObject; we just connect to its signal. This avoids the Qt diamond-
    inheritance trap when Phase 5 promotes controllers to QWidget subclasses.
    """

    def __init__(self, gui, lazy=False):
        """Args:
            gui: the main window (or any object holding the target widgets)
            lazy: if True, defer _on_*_changed handlers until set_visible(True)
        """
        self._gui = gui
        self._state = None
        self._lazy = lazy
        # Eager controllers start "visible"; lazy controllers start hidden.
        self._is_visible = not lazy
        self._pending_chart_refresh = False
        self._pending_mode_refresh = False

    def connect_to_state(self, state):
        """Hook into ChartState.state_changed. Call after widgets exist."""
        self._state = state
        state.connect(self._dispatch_state_change)

    def _dispatch_state_change(self, reason: str):
        """Route state_changed signals to the right handler.

        Uses QTimer.singleShot(0, handler) to yield between heavy panels —
        replaces the QApplication.processEvents() calls that lived in the
        old _update_all_panels() body. Without this yield, 10+ controllers
        firing synchronously freeze the GUI thread on heavy charts.

        Lazy guard: when not visible, mark the appropriate pending flag
        and return; set_visible(True) consumes the flag and fires the handler.
        """
        if reason == "active_chart":
            if self._lazy and not self._is_visible:
                self._pending_chart_refresh = True
                return
            QTimer.singleShot(0, self._on_chart_changed)
        elif reason == "aditya_mode":
            if not hasattr(self, '_on_mode_changed'):
                return
            if self._lazy and not self._is_visible:
                self._pending_mode_refresh = True
                return
            QTimer.singleShot(0, self._on_mode_changed)
        elif reason == "current_varga":
            if hasattr(self, '_on_varga_changed'):
                QTimer.singleShot(0, self._on_varga_changed)
        elif reason == "chart_view_style":
            if hasattr(self, '_on_view_changed'):
                QTimer.singleShot(0, self._on_view_changed)

    def set_visible(self, visible: bool):
        """Toggle visibility. Lazy controllers process pending refreshes here.

        Wired by core_gui_qt.py to the tab-button click handlers
        (avastha_tab_btn, shame_tab_btn at line 5102) — NOT to a non-existent
        QWidget.shown signal. Visibility transitions:
            False→True with pending: fire deferred handlers
            False→False or True→True: no-op
            True→False: stop processing (handlers will defer next time)
        """
        was_visible = self._is_visible
        self._is_visible = visible
        if visible and not was_visible:
            if self._pending_chart_refresh:
                self._pending_chart_refresh = False
                self._on_chart_changed()
            if self._pending_mode_refresh and hasattr(self, '_on_mode_changed'):
                self._pending_mode_refresh = False
                self._on_mode_changed()

    def _on_chart_changed(self):
        """MUST be implemented by every subclass.

        Contract:
        - Handle self._state.active_chart is None (clear widget, return)
        - Be idempotent (callable multiple times with same state)
        - Never raise — log and return on unexpected data
        """
        raise NotImplementedError(
            f"{type(self).__name__} must implement _on_chart_changed"
        )
