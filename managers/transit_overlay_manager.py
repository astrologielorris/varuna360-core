# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Transit Overlay Manager — shared transit state for all chart views.

Owns the transit Chart, 60-second auto-refresh timer, and the
transit_state_changed signal. Chart views consume this state via
core_gui_qt as mediator (no direct widget-to-manager coupling).

SPEC-TRN-002 Section 4.2.
"""
from datetime import datetime, timezone

from PySide6.QtCore import QObject, QTimer, Signal

from core.chart_factory import build_chart_from_params
from core.transit_utils import get_current_location
from libaditya import swe


class TransitOverlayManager(QObject):
    """Shared transit overlay state for wheel and South Indian chart views.

    First QObject manager in the managers/ directory. Inherits QObject
    because it owns a QTimer and emits Qt signals.
    """

    transit_state_changed = Signal()

    def __init__(self, gui, parent=None):
        super().__init__(parent)
        self._gui = gui

        self.transit_enabled = False
        self.transit_mode = "auto"
        self.transit_jd = None
        self.transit_chart = None
        self.transit_rashi = None
        self.transit_planets = None
        self.transit_cusps = None

        # SPEC-TRN-006: chart-overlay mode. When transit_mode == "overlay_chart"
        # the rim renders a user-chosen chart (an event, or a person for a fast
        # synastry peek) instead of the live sky. overlay_source is retained so a
        # later zodiac/house-system change can rebuild the overlay in the new frame.
        self.overlay_chart_obj = None
        self.overlay_label = ""
        self.overlay_source = None  # {"kind": "memory"|"file", "id": ..., "path": ...}
        self.overlay_frame = None   # (mode, ayanamsa, house_system) at build time (INV-3)

        self._timer = QTimer(self)
        self._timer.setInterval(60_000)
        self._timer.timeout.connect(self._auto_refresh)

    def enable_transit(self):
        """Activate transit overlay in auto mode (current sky, 60s refresh)."""
        active = self._gui.state.active_chart
        if active is None:
            return
        # SPEC-TRN-006 B-13: leaving overlay mode for live sky; drop stale overlay
        # metadata so the chip/label do not survive into auto mode.
        self._clear_overlay_metadata()
        self.transit_enabled = True
        self.transit_mode = "auto"
        self._calculate_now()
        self._timer.start()
        self.transit_state_changed.emit()

    def disable_transit(self):
        """Deactivate transit overlay and clear all state."""
        self.transit_enabled = False
        self._timer.stop()
        self.transit_jd = None
        self.transit_chart = None
        self.transit_rashi = None
        self.transit_planets = None
        self.transit_cusps = None
        self.transit_mode = "auto"
        # SPEC-TRN-006 INV: reachable from _on_active_chart_changed when the base
        # chart goes away; clear overlay metadata too or a ghost name lingers in
        # the title-bar chip.
        self._clear_overlay_metadata()
        self.transit_state_changed.emit()

    def _clear_overlay_metadata(self):
        """Drop the overlay-only fields. No signal, no view change."""
        self.overlay_chart_obj = None
        self.overlay_label = ""
        self.overlay_source = None
        self.overlay_frame = None

    @staticmethod
    def _read_transit_bundle(chart):
        """Derive (rashi, planets, cusps) from a Chart. Raises on failure.

        The one place the rim's render inputs are pulled off a Chart; both the
        live-sky path (_calculate_for_jd) and the overlay path (overlay_chart)
        use it so the two cannot drift.
        """
        rashi = chart.rashi()
        return rashi, rashi.planets(), rashi.cusps()

    def _set_transit_bundle(self, chart, rashi, planets, cusps, jd):
        """Assign the five rim render fields. Callers own atomicity: overlay_chart
        derives into locals first so a failure commits nothing (INV-2); the
        live-sky _calculate_for_jd keeps its legacy on-failure clear of
        planets/cusps only (it self-heals on the next 60s tick)."""
        self.transit_chart = chart
        self.transit_rashi = rashi
        self.transit_planets = planets
        self.transit_cusps = cusps
        self.transit_jd = jd

    def overlay_chart(self, chart, label="", source=None):
        """Overlay an already-built Chart on the rim (SPEC-TRN-006).

        Unlike the live-sky path, this NEVER recomputes at the observer's current
        location (INV-1): it renders the passed chart's own planets/cusps, so a
        person's chart shows their sky, not "their planets at the observer's house".

        Compute-then-commit (INV-2): rashi/planets/cusps/jd are derived into locals
        first; only if ALL succeed are the transit fields committed atomically. A
        failure mutates nothing (no half-applied transit_enabled=True +
        transit_chart=None, which the South Indian centre box rejects). Returns
        True on success, False if refused or the build failed.
        """
        if self._gui.state.active_chart is None:
            return False
        try:
            rashi, planets, cusps = self._read_transit_bundle(chart)
            jd = chart.context.timeJD.jd
        except Exception as e:
            print(f"[TRANSIT-OVERLAY] Error overlaying chart: {e}")
            import traceback
            traceback.print_exc()
            return False

        # --- atomic commit (nothing above mutated any field) ---
        self._timer.stop()  # an overlay is a frozen moment, never auto-refreshed
        self._set_transit_bundle(chart, rashi, planets, cusps, jd)
        self.overlay_chart_obj = chart
        self.overlay_label = label or ""
        self.overlay_source = source
        self.overlay_frame = self._current_frame()  # INV-3 frame diff baseline
        self.transit_mode = "overlay_chart"
        self.transit_enabled = True
        self.transit_state_changed.emit()
        return True

    def clear_overlay_chart(self):
        """Clear the overlay chart AND turn the rim off (chip x -> off path)."""
        self._clear_overlay_metadata()
        self.disable_transit()

    def clear_overlay_to_live_sky(self):
        """Drop the overlay but keep the rim ON, back on live-sky auto mode.

        This is the one path from overlay to live sky without a trip through OFF
        (chip x / 'Back to live sky' context action, SPEC-TRN-006 D-1).
        """
        self._clear_overlay_metadata()
        self.enable_transit()  # resets mode to "auto", restarts the 60s timer
        # SPEC-TRN-006 (review MAJOR-3): if the live-sky recompute failed (rare
        # ephemeris error), do not sit in an enabled-without-complete-chart state
        # the SI centre box rejects; fall fully OFF instead.
        if self.transit_enabled and (self.transit_planets is None
                                     or self.transit_chart is None):
            self.disable_transit()

    def lock_to_jd(self, target_jd):
        """Lock the overlay to a specific Julian Day (dasha-locked mode)."""
        # SPEC-TRN-006 B-13: dasha can lock time while an overlay is up; drop
        # overlay metadata so a stale chip name cannot linger in dasha_locked mode.
        self._clear_overlay_metadata()
        self.transit_mode = "dasha_locked"
        self._timer.stop()
        self._calculate_for_jd(target_jd)
        self.transit_state_changed.emit()

    def lock_to_datetime(self, target_dt):
        """Lock to a specific datetime (convenience wrapper)."""
        _hr = target_dt.hour + target_dt.minute / 60.0 + target_dt.second / 3600.0
        jd = swe.julday(target_dt.year, target_dt.month, target_dt.day, _hr)
        self.lock_to_jd(jd)

    def adjust_time(self, delta_seconds):
        """Shift transit time by delta_seconds. Positive = forward."""
        # SPEC-TRN-006 D-5 (v1): an overlay chart is a frozen moment. Time-adjust
        # does not apply; the caller surfaces a status message.
        if self.transit_mode == "overlay_chart":
            return
        if self.transit_jd is None:
            return
        if self.transit_mode == "auto":
            self.transit_mode = "dasha_locked"
            self._timer.stop()
        target_jd = self.transit_jd + delta_seconds / 86400.0
        self._calculate_for_jd(target_jd)
        self.transit_state_changed.emit()

    def _calculate_now(self):
        """Calculate transit for the current moment."""
        now = datetime.now(timezone.utc)
        _hr = now.hour + now.minute / 60.0 + now.second / 3600.0
        jd = swe.julday(now.year, now.month, now.day, _hr)
        self._calculate_for_jd(jd)

    def _calculate_for_jd(self, jd):
        """Build transit chart for a given Julian Day."""
        try:
            lat, lon = get_current_location()
            _local_off = datetime.now().astimezone().utcoffset()
            _utcoff = _local_off.total_seconds() / 3600.0 if _local_off else 0.0

            mode = self._gui.state.aditya_mode
            natal = self._gui.state.active_chart
            ayanamsa = natal.context.ayanamsa if natal else 1
            hsys = getattr(self._gui, '_house_system_code', 'C')

            chart = build_chart_from_params(
                jd=jd, lat=lat, lon=lon,
                mode=mode, ayanamsa=ayanamsa,
                hsys=hsys, utcoffset=_utcoff,
            )
            rashi, planets, cusps = self._read_transit_bundle(chart)
            self._set_transit_bundle(chart, rashi, planets, cusps, jd)
        except Exception as e:
            print(f"[TRANSIT-OVERLAY] Error calculating transit: {e}")
            import traceback
            traceback.print_exc()
            self.transit_planets = None
            self.transit_cusps = None

    def _auto_refresh(self):
        """Timer callback: recalculate for current time and notify."""
        if not self.transit_enabled or self.transit_mode != "auto":
            return
        self._calculate_now()
        self.transit_state_changed.emit()

    def _current_frame(self):
        """The (mode, ayanamsa, house_system) the active chart currently uses.

        The overlay must always render in this same frame (INV-3). Recorded at
        build time as overlay_frame and compared on every active-chart rebuild.
        """
        g = self._gui
        return (g.state.aditya_mode,
                getattr(g, 'chart_sidereal_ayanamsa_id', 100),
                g.state.house_system)

    def _on_active_chart_changed(self, reason):
        """ChartState callback (fn(reason) on every state mutation).

        SPEC-TRN-006 INV-3 (single authority): EVERY frame change (zodiac mode,
        ayanamsa, house system) rebuilds the base chart via _recalculate_chart ->
        SetActiveChart -> reason "active_chart". So an overlay is rebuilt here,
        keyed on a frame diff, regardless of which channel triggered the change
        (main toggle, _toggle_sidereal, ayanamsa dialog/settings, nakshatra panel,
        or a direct remote SetHouseSystem). No per-channel wiring needed.
        """
        if reason != "active_chart":
            return
        if self._gui.state.active_chart is None:
            self.disable_transit()
            return
        if not self.transit_enabled:
            return
        if self.transit_mode == "overlay_chart":
            if self._current_frame() != self.overlay_frame:
                # Frame changed -> rebuild the overlay in the new frame. Idempotent
                # across the several emits one change can produce (the first rebuild
                # updates overlay_frame; later emits find it matching and skip).
                mgr = getattr(self._gui, "chart_overlay_manager", None)
                if mgr is not None:
                    mgr.reoverlay_current()
                else:
                    self.clear_overlay_chart()
            else:
                # SPEC-TRN-006 D-4: only the base chart's identity changed (drop B
                # on A, then switch A->C). Keep the overlay; redraw with the new base.
                self.transit_state_changed.emit()
            return
        if self.transit_mode == "auto":
            self._calculate_now()
        else:
            self._calculate_for_jd(self.transit_jd)
        self.transit_state_changed.emit()

    def _on_aditya_mode_changed(self, new_mode):
        """Recalculate the LIVE-SKY transit on a zodiac mode change (ad-hoc signal).

        Overlay rebuilds are NOT handled here — they go through the authoritative
        frame-diff in _on_active_chart_changed (which also catches ayanamsa and
        house-system changes this ad-hoc signal never sees). Skip overlay mode.
        """
        if not self.transit_enabled:
            return
        if self.transit_mode == "overlay_chart":
            return
        if self.transit_mode == "auto":
            self._calculate_now()
        else:
            self._calculate_for_jd(self.transit_jd)
        self.transit_state_changed.emit()
