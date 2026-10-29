# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Boot "Now" chart fallback.

When boot restores no session, the window shows a chart for the current
moment a little later (``NOW_CHART_DELAY_MS`` after ``_delayed_startup``).
A chart opened inside that window, by the user, the remote control or an AI
app's "open chart in app", must win over it: the Now chart used to be decided
when the timer was SCHEDULED, so a chart loaded in the gap was replaced by it
(seen 2026-10-27 in the Stained Light fixtures: a ``load_chart`` running when
the timer fired lost to the Now chart).

The decision is now taken when the timer FIRES. The Now chart loads only if,
since the guard was armed, no chart became active, none is active now, and no
chart load is running (``ChartManager._loading_chart``, which every file load
goes through: the GUI, the remote control and the MCP link).

The guard is held by its own timer callback, never by ``ChartGUI`` (Rule 4b).
"""

from __future__ import annotations

NOW_CHART_DELAY_MS = 200


class NowChartGuard:
    """Arms on construction; ``fire()`` loads the Now chart or stands down."""

    def __init__(self, gui) -> None:
        self._gui = gui
        self._state = gui.state
        self._chart_seen = False
        self._done = False
        self._state.connect(self._on_state)

    def _on_state(self, reason: str) -> None:
        if reason == "active_chart":
            self._chart_seen = True

    def _disarm(self) -> None:
        if self._done:
            return
        self._done = True
        try:
            self._state.disconnect(self._on_state)
        except ValueError:
            pass

    def _chart_loading(self) -> bool:
        cm = getattr(self._gui, "chart_manager", None)
        return bool(cm is not None and getattr(cm, "_loading_chart", False))

    def should_load(self) -> bool:
        return not (self._chart_seen
                    or self._state.active_chart is not None
                    or self._chart_loading())

    def fire(self) -> bool:
        """Load the Now chart if nothing else claimed the window. Returns
        True when it loaded it. Runs once; later calls do nothing."""
        if self._done:
            return False
        load = self.should_load()
        self._disarm()
        if not load:
            return False
        try:
            import shiboken6
            if not shiboken6.isValid(self._gui):
                return False
        except (ImportError, TypeError):
            pass
        self._gui._load_now_chart()
        return True


def schedule_now_chart(gui, delay_ms: int = NOW_CHART_DELAY_MS) -> NowChartGuard:
    """Arm the guard now and fire it ``delay_ms`` later."""
    from PySide6.QtCore import QTimer

    guard = NowChartGuard(gui)
    QTimer.singleShot(delay_ms, guard.fire)
    return guard
