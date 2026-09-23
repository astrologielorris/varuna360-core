# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
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
        _on_chart_changed(self) — required, called when the chart-relevant state
                                  (active_chart / aditya_mode / current_varga)
                                  changes; the single coalesced refresh entry.
        _on_view_changed(self)  — optional, called when chart_view_style changes;
                                  INDEPENDENT of the chart refresh (see contract).

    Coalescing contract (td-yymp — READ THIS BEFORE ADDING A CONTROLLER):
        ChartState._emit is a synchronous listener loop, so one user gesture can
        fan out several reasons in a single event-loop pass BEFORE any
        QTimer.singleShot(0) fires. A zodiac-mode toggle, for example, emits
        `aditya_mode` (SetZodiacMode) and then `active_chart` (the rebuilt chart)
        in the same pass. Left un-coalesced, a controller that reacts to both
        recomputed twice for one toggle (measured 2x on strength/karakas/etc.).

        CHART BUCKET — `active_chart`, `aditya_mode`, `current_varga` collapse to
        EXACTLY ONE _on_chart_changed per pass. A reason enters the bucket only
        if this controller would have reacted to it individually: `active_chart`
        always; `aditya_mode` iff the subclass defines `_on_mode_changed`;
        `current_varga` iff it defines `_on_varga_changed`. This preserves the
        deliberate mode-invariance of controllers that omit `_on_mode_changed`
        (the Tajika controllers — Tajika aspects are a pure function of the chart
        object, so a mode flip alone must NOT refresh them). Historically those
        optional handlers all delegated to the same `_refresh()` as
        `_on_chart_changed`, so folding them into one `_on_chart_changed` is
        behaviourally identical, not a shortcut. `_on_mode_changed` /
        `_on_varga_changed` are therefore no longer dispatched directly; define a
        controller's whole chart-relevant refresh in `_on_chart_changed` and it
        will run once per pass.

        VIEW is INDEPENDENT — `chart_view_style` coalesces to its own single
        _on_view_changed per pass and never merges into the chart bucket, because
        a view change is a cheap display-only tweak (e.g. nabhasa toggling its
        wheel-mode affordance), not a recompute.

    Lazy mode:
        When lazy=True, the chart-bucket refresh is deferred until
        set_visible(True) is called. This mirrors the pre-Phase-4 avastha/shame
        behavior where computation only happens on tab show.

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
        # Retained for API/back-compat; the coalesced dispatch routes a hidden
        # aditya_mode into _pending_chart_refresh (mode folds into the chart
        # bucket), so this flag is no longer set True by _dispatch_state_change.
        self._pending_mode_refresh = False
        # td-yymp coalescing: at most one scheduled flush per bucket per event-
        # loop pass. The first chart-bucket / view reason of a pass schedules the
        # singleShot; later ones in the same pass see the flag set and no-op.
        self._chart_refresh_scheduled = False
        self._view_refresh_scheduled = False

    def connect_to_state(self, state):
        """Hook into ChartState.state_changed. Call after widgets exist.

        batchable=True (td-yymp Block 4): panel controllers are terminal repaint
        listeners, so inside a `with state.batching()` block their reasons are
        buffered and replayed once at drain — the single coalesced refresh that
        Block 3's per-pass flag then collapses to one _on_chart_changed."""
        self._state = state
        state.connect(self._dispatch_state_change, batchable=True)

    def _dispatch_state_change(self, reason: str):
        """Route state_changed signals into the two coalesced buckets.

        Each bucket flushes via a single QTimer.singleShot(0) per event-loop
        pass — the yield keeps a fan-out of 10+ controllers from freezing the GUI
        thread, and the per-pass coalescing (td-yymp) means one user gesture that
        emits several reasons synchronously (a mode toggle emits `aditya_mode`
        then `active_chart`) triggers the controller's refresh ONCE, not once per
        reason. See the class docstring for the full contract and membership rule.

        Visibility guard (td-7932): a hidden controller records a pending chart
        refresh and does NOT schedule; set_visible(True) drains it. Only the
        CHART bucket is gated; the VIEW bucket (chart_view_style) fires even when
        hidden — a display-only tweak, deliberately left un-gated (decision #2).
        current_varga now folds into the gated chart bucket, which is identical to
        its sole responder's (shame) pre-existing self-gating.
        """
        # --- CHART BUCKET membership: a reason counts only if this controller
        #     would have reacted to it individually under the old routing. ---
        in_chart_bucket = (
            reason == "active_chart"
            or (reason == "aditya_mode" and hasattr(self, '_on_mode_changed'))
            or (reason == "current_varga" and hasattr(self, '_on_varga_changed'))
        )
        if in_chart_bucket:
            if not self._is_visible:
                self._pending_chart_refresh = True
                return
            self._schedule_chart_refresh()
        elif reason == "chart_view_style" and hasattr(self, '_on_view_changed'):
            self._schedule_view_refresh()

    def _schedule_chart_refresh(self):
        """Coalesce: schedule at most one _on_chart_changed flush per pass."""
        if self._chart_refresh_scheduled:
            return
        self._chart_refresh_scheduled = True
        QTimer.singleShot(0, self._flush_chart_refresh)

    def _flush_chart_refresh(self):
        # MED-1: the scheduled flag is the single "a refresh is owed" token. A
        # show-drain (set_visible) can consume it first — if it did, this timer is
        # stale (the refresh already happened) and must no-op, not fire a second.
        if not self._chart_refresh_scheduled:
            return
        self._chart_refresh_scheduled = False
        # Visibility can have flipped off between scheduling and this flush (a tab
        # switch in a later turn); re-check so a coalesced refresh never runs on a
        # now-hidden panel — it re-defers to the next show, hardening td-7932.
        if not self._is_visible:
            self._pending_chart_refresh = True
            return
        self._on_chart_changed()

    def _schedule_view_refresh(self):
        """Coalesce: schedule at most one _on_view_changed flush per pass."""
        if self._view_refresh_scheduled:
            return
        self._view_refresh_scheduled = True
        QTimer.singleShot(0, self._flush_view_refresh)

    def _flush_view_refresh(self):
        self._view_refresh_scheduled = False
        self._on_view_changed()

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
            # MED-1: a show-drain satisfies BOTH a deferred pending refresh AND an
            # already-scheduled flush timer (the panel was hidden after a visible
            # emit scheduled one). Consume _chart_refresh_scheduled so that stale
            # singleShot no-ops instead of firing a SECOND refresh after this one.
            if self._pending_chart_refresh or self._chart_refresh_scheduled:
                self._pending_chart_refresh = False
                self._chart_refresh_scheduled = False
                self._on_chart_changed()
            # Vestigial after td-yymp: aditya_mode folds into _pending_chart_refresh,
            # so _pending_mode_refresh is never set True any more. Drained here only
            # to stay correct if some external caller ever sets it. Safe to remove
            # once the stale state/test_panel_controllers.py is rewritten.
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
