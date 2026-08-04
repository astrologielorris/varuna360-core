# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
What the click means: Ascendant preview for the place picker (SPEC-MAP-002).

The picker is the last surface in the app where the astrologer works blind.
Everywhere else an input shows its consequence; here a click showed a dot, and
learning the Ascendant meant applying the location, waiting for a chart
rebuild, reading it, and coming back if it was wrong.

This controller closes that loop. It owns three things:

* the **time basis** — the local civil time the host is editing, which is what
  makes an Ascendant computable at all;
* the **band scan** — twelve sign bands for one fixed instant, computed a
  slice at a time on the GUI thread under a generation guard (never on a
  worker: see core.ascendant_field.BandScan for why Swiss Ephemeris forbids
  it);
* the **readout** — the Ascendant under the cursor, using that point's own
  timezone.

TWO CLOCKS, DELIBERATELY
------------------------
Bands are drawn for ONE instant. The readout follows the hovered point's
timezone. They disagree across a timezone border and that is not a bug: the
bands answer "where does each sign rise at this moment", the readout answers
"what would I get if I clicked here". Only the second is the chart the user is
about to build, so only the second may drive a decision. The card names the
band instant on its own line so the two are never silently conflated
(SPEC-MAP-002 §4.4, the two-clock trap).

WHY THE READOUT IS NOT A SHORTCUT
---------------------------------
It would be quicker to add the point's UTC offset to the local time and probe.
That is a second local-to-UTC road, and SPEC-TZ-001 exists because this
codebase has been bitten by second roads. The conversion here goes through
`core.time_utils.local_to_utc_total` with the offset pytz reports for the birth
DATE — the same function and the same total-offset convention
`BirthDataManager` uses, so a previewed Ascendant and an applied one cannot
drift apart.
"""

import math
from datetime import datetime
from typing import Optional, Tuple

from PySide6.QtCore import QObject, QTimer, Signal

__all__ = ["MapAscendantController", "format_degree"]

#: Timezone lookups are memoised on this grid. Adjacent pixels almost always
#: share a timezone, so a hover sweep collapses to a handful of real lookups.
#: 0.25 degrees is ~28 km at the equator — fine enough that the memo does not
#: straddle a zone border in populated areas, coarse enough to actually hit.
TZ_GRID_DEG = 0.25

#: Cap on the memo, so a long session cannot grow it without bound.
TZ_MEMO_MAX = 4000


def format_degree(deg_in_sign: float) -> str:
    """12.3856 -> "12 23'". Degrees and arcminutes, the way a chart reads."""
    total_min = int(round(deg_in_sign * 60.0))
    return f"{total_min // 60}°{total_min % 60:02d}'"


class MapAscendantController(QObject):
    """Drives the Ascendant layer and the card's Ascendant/timezone lines."""

    #: (sign_index, degree_in_sign, sign_name, tz_name, offset_string) or None
    readout_changed = Signal(object)
    bands_changed = Signal(bool)

    def __init__(self, map_widget, card, parent=None):
        super().__init__(parent)
        self.map_widget = map_widget
        self.card = card

        self._local: Optional[dict] = None      # y/m/d/h/mi/s of the form
        self._mode = "aditya"
        self._ayanamsa = 1
        self._sign_names = []
        self._utc_input = False
        self._basis_dt: Optional[datetime] = None

        self._enabled = False
        self._gen = 0
        self._tz_memo = {}
        self._point: Optional[Tuple[float, float]] = None

        # The scan runs on THIS thread, one slice per timer tick. See
        # core.ascendant_field.BandScan for why it is not a worker: Swiss
        # Ephemeris keeps global mutable state that a background scan can
        # corrupt for a chart the GUI is building at the same time.
        self._scan = None
        self._scan_gen = -1
        self._scan_timer = QTimer(self)
        self._scan_timer.setInterval(0)      # next event-loop turn
        self._scan_timer.timeout.connect(self._scan_step)

    # -- configuration -----------------------------------------------------

    def set_time_basis(self, local_fields: Optional[dict], mode: str = None,
                       ayanamsa: int = None, sign_names=None,
                       utc_input: bool = False):
        """Tell the controller what chart is being edited.

        `local_fields` None means the host has no birth instant (Birth Finder,
        Lunar New Year, the Eclipse panel). Everything switches off and no
        probe ever runs — SPEC-MAP-002 INV-4.

        `utc_input` mirrors the form's `time_mode == 'UTC'`.

        A CHANGED basis invalidates whatever is on screen. Bands belong to one
        instant in one zodiac frame; edit the birth time, the mode or the
        ayanamsa and the drawn bands are simply wrong. They used to survive the
        change, because nothing here bumped the generation — and the host calls
        `set_marker()` (which queues a scan) BEFORE it pushes the new basis, so
        the stale scan was not merely kept, it was re-requested.
        """
        previous = (self._local, self._mode, self._ayanamsa, self._utc_input)

        self._local = dict(local_fields) if local_fields else None
        self._utc_input = bool(utc_input)
        if mode:
            self._mode = mode
        if ayanamsa is not None:
            self._ayanamsa = int(ayanamsa)
        if sign_names:
            self._sign_names = list(sign_names)

        if self._local is None:
            self.set_bands_enabled(False)
            return

        if previous != (self._local, self._mode, self._ayanamsa,
                        self._utc_input):
            self._gen += 1              # abandon anything in flight
            if self._enabled:
                self.map_widget.clear_ascendant()
                self.request_bands()

    def has_time_basis(self) -> bool:
        return self._local is not None

    def set_bands_enabled(self, enabled: bool):
        enabled = bool(enabled) and self.has_time_basis()
        if enabled == self._enabled:
            return
        self._enabled = enabled
        if not enabled:
            self._gen += 1               # abandon any scan in flight
            self.map_widget.clear_ascendant()
            if self.card is not None:
                self.card.set_basis("")
            self.bands_changed.emit(False)
        else:
            self.request_bands()

    def bands_enabled(self) -> bool:
        return self._enabled

    # -- band scan ---------------------------------------------------------

    def request_bands(self, lat: float = None, lon: float = None):
        """(Re)compute the bands for the current selection's instant.

        The instant depends on the selected place's timezone, so moving the
        selection moves the instant and the bands must follow.
        """
        if lat is not None and lon is not None:
            self._point = (lat, lon)
        if not self._enabled or not self.has_time_basis():
            # Remember the point anyway: the user may turn the bands on later,
            # and re-deriving it from the widget's marker does not work — a
            # programmatic selection (remote control, a search result, the host
            # restoring a chart) never goes through mousePressEvent, so the
            # widget's marker can be unset while a place IS selected.
            return
        if lat is None or lon is None:
            point = self._point
            if point is None:
                marker = (self.map_widget.marker_lat, self.map_widget.marker_lon)
                point = marker if marker[0] is not None else None
            if point is None:
                return
            lat, lon = point

        dt_utc = self._utc_at(lat, lon, exact_tz=True)
        if dt_utc is None:
            return
        self._basis_dt = dt_utc

        from core.ascendant_field import BandScan, julian_day_utc

        # Starting a new scan REPLACES the old one outright. There is no queue
        # to pile up: a burst of selections costs one scan, the last one.
        self._gen += 1
        self._scan_gen = self._gen
        self._scan = BandScan(julian_day_utc(dt_utc), self._mode,
                              self._ayanamsa)
        self._scan_timer.start()

    def _scan_step(self):
        """One slice of the current scan, on the GUI thread, under a frame."""
        scan = self._scan
        if scan is None or self._scan_gen != self._gen or not self._enabled:
            self._abort_scan()            # superseded or switched off
            return
        try:
            finished = scan.step()
        except Exception:
            self._abort_scan()
            return
        if not finished:
            return

        self._abort_scan()
        try:
            # left/right travel with the polygon: only those two edges are real
            # Ascendant boundaries, and the view layer must know which is which
            # so it does not stroke the latitude where the data simply stops.
            payload = [(b.sign_index, b.coords, b.left, b.right)
                       for b in scan.result()]
        except Exception:
            return
        self._deliver_bands(payload)

    def _abort_scan(self):
        self._scan = None
        self._scan_timer.stop()

    def _deliver_bands(self, payload):
        labels = {i: self._sign_name(i) for i in range(12)}
        self.map_widget.set_ascendant_bands(payload, labels)
        if self.card is not None and self._basis_dt is not None:
            self.card.set_basis(
                "bands: " + self._basis_dt.strftime("%Y-%m-%d %H:%M UTC"))
        self.bands_changed.emit(bool(payload))

    def _sign_name(self, index: int) -> str:
        if 0 <= index < len(self._sign_names):
            return self._sign_names[index]
        return ""

    # -- readout -----------------------------------------------------------

    def readout_at(self, lat: float, lon: float):
        """(sign_index, degree, name, tz_name, offset) for a point, or None.

        Cheap enough for the hover throttle: one memoised timezone lookup plus
        one ~0.3 ms Ascendant probe.
        """
        if not self.has_time_basis():
            return None
        tz_name = self._tz_at(lat, lon)
        dt_utc = self._utc_at(lat, lon, tz_name=tz_name)
        if dt_utc is None:
            return None
        try:
            from core.ascendant_field import julian_day_utc
            from core.chart_helpers import ascendant_probe
            idx, deg = ascendant_probe(julian_day_utc(dt_utc), lat, lon,
                                       self._mode, self._ayanamsa)
        except Exception:
            return None
        return (idx, deg, self._sign_name(idx), tz_name,
                self._offset_string(tz_name))

    def apply_readout_to_card(self, lat: float, lon: float) -> bool:
        """Update the card's Ascendant + timezone lines. False if unavailable."""
        if self.card is None:
            return False
        data = self.readout_at(lat, lon)
        if data is None:
            self.card.set_ascendant("")
            return False
        _idx, deg, name, tz_name, offset = data
        label = f"Ascendant  {format_degree(deg)}"
        self.card.set_ascendant(f"{label}  {name}".rstrip())
        self.card.set_timezone(tz_name, offset)
        self.readout_changed.emit(data)
        return True

    # -- time / timezone ---------------------------------------------------

    def _tz_at(self, lat: float, lon: float, exact: bool = False) -> str:
        """Timezone at a point. `exact` bypasses the memo.

        The memo answers a whole 0.25-degree cell with the first point looked
        up in it, so near an IANA boundary — a US county line, say — it can be
        an hour wrong. That is acceptable for a HOVER readout, which is a
        pointer-rate preview, and not acceptable for anything that feeds a
        selection: pass exact=True there so the band instant and the selected
        place agree with the chart that gets applied.
        """
        from core.tz_finder import timezone_at_or_offset
        if exact:
            return timezone_at_or_offset(lat, lon)

        key = (int(math.floor(lat / TZ_GRID_DEG)),
               int(math.floor(lon / TZ_GRID_DEG)))
        hit = self._tz_memo.get(key)
        if hit is not None:
            return hit
        name = timezone_at_or_offset(lat, lon)
        if len(self._tz_memo) >= TZ_MEMO_MAX:
            self._tz_memo.clear()
        self._tz_memo[key] = name
        return name

    def _offset_string(self, tz_name: str) -> str:
        hours = self._total_offset_hours(tz_name)
        if hours is None:
            return ""
        sign = "+" if hours >= 0 else "-"
        mins = int(round(abs(hours) * 60))
        return f"UTC{sign}{mins // 60:02d}:{mins % 60:02d}"

    def _total_offset_hours(self, tz_name: str) -> Optional[float]:
        """Offset at the BIRTH date, not today.

        A chart from 1920 Paris is +00:00 even though Paris is +01:00 now; the
        rest of the app already knows this (time_utils._parse_offset carries a
        ref_year for exactly this reason) and a preview that used today's
        offset would disagree with the chart it is previewing.
        """
        if not tz_name or self._local is None:
            return None
        try:
            import pytz
            naive = datetime(self._local["year"], self._local["month"],
                             self._local["day"], self._local["hour"],
                             self._local["minute"], self._local.get("second", 0))
            aware = pytz.timezone(tz_name).localize(naive, is_dst=None)
        except Exception:
            try:
                # Ambiguous or non-existent local time (a DST transition). Let
                # pytz pick rather than refusing to show anything: an hour of
                # ambiguity is still a usable Ascendant preview, and the chart
                # itself resolves this through the form's own DST flag.
                aware = pytz.timezone(tz_name).localize(naive, is_dst=False)
            except Exception:
                return None
        offset = aware.utcoffset()
        if offset is None:
            return None
        return offset.total_seconds() / 3600.0

    def _utc_at(self, lat: float, lon: float, tz_name: str = None,
                exact_tz: bool = False) -> Optional[datetime]:
        if self._local is None:
            return None

        if self._utc_input:
            # A UTC-ENTERED chart: utc_* == local_* by definition and the
            # timezone field is informational (BirthDataManager
            # create_from_form_data, SPEC-TZ-001 8a). Subtracting the place's
            # offset here would have moved the instant by the whole UTC offset
            # — two hours of Ascendant for a Paris preview — while the chart
            # the user then applied kept the entered time. Same road, or none.
            try:
                return datetime(self._local["year"], self._local["month"],
                                self._local["day"], self._local["hour"],
                                self._local["minute"],
                                self._local.get("second", 0))
            except Exception:
                return None

        tz_name = tz_name or self._tz_at(lat, lon, exact=exact_tz)
        hours = self._total_offset_hours(tz_name)
        if hours is None:
            return None
        from core.time_utils import local_to_utc_total
        try:
            y, mo, d, h, mi, s = local_to_utc_total(
                self._local["year"], self._local["month"], self._local["day"],
                self._local["hour"], self._local["minute"],
                self._local.get("second", 0), hours)
            return datetime(y, mo, d, h, mi, s)
        except Exception:
            return None

    # -- lifecycle ---------------------------------------------------------

    def shutdown(self, timeout_ms: int = 0):
        """Abandon any scan. Returns immediately and never blocks.

        There is nothing to wait for any more: the scan lives on this thread,
        so stopping its timer stops it. The previous version blocked the GUI
        thread in QThreadPool.waitForDone() for up to three seconds, which
        meant closing a dialog mid-scan froze the app. `timeout_ms` is kept
        only so existing callers do not have to change.
        """
        self._gen += 1
        self._abort_scan()

    def wait_for_bands(self, timeout_ms: int = 8000) -> bool:
        """Offscreen/test helper: run the current scan to completion NOW.

        Never call this from an interactive path — it is the blocking form that
        the interactive path exists to avoid.
        """
        import time
        deadline = time.perf_counter() + timeout_ms / 1000.0
        while self._scan is not None and time.perf_counter() < deadline:
            self._scan_step()
        return self._scan is None
