# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
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

        self._timer = QTimer(self)
        self._timer.setInterval(60_000)
        self._timer.timeout.connect(self._auto_refresh)

    def enable_transit(self):
        """Activate transit overlay in auto mode (current sky, 60s refresh)."""
        active = self._gui.state.active_chart
        if active is None:
            return
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
        self.transit_state_changed.emit()

    def lock_to_jd(self, target_jd):
        """Lock the overlay to a specific Julian Day (dasha-locked mode)."""
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
            rashi = chart.rashi()
            planets = rashi.planets()
            cusps = rashi.cusps()
            self.transit_jd = jd
            self.transit_chart = chart
            self.transit_rashi = rashi
            self.transit_planets = planets
            self.transit_cusps = cusps
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

    def _on_active_chart_changed(self, reason):
        """ChartState callback. Only act on active_chart changes."""
        if reason != "active_chart":
            return
        if self._gui.state.active_chart is None:
            self.disable_transit()
            return
        if self.transit_enabled:
            if self.transit_mode == "auto":
                self._calculate_now()
            else:
                self._calculate_for_jd(self.transit_jd)
            self.transit_state_changed.emit()

    def _on_aditya_mode_changed(self, new_mode):
        """Recalculate transit with new zodiac mode."""
        if not self.transit_enabled:
            return
        if self.transit_mode == "auto":
            self._calculate_now()
        else:
            self._calculate_for_jd(self.transit_jd)
        self.transit_state_changed.emit()
