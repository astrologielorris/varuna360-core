# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
New & Edit binding — the CONTROLLER of the redesigned New & Edit tab (WI-4).

The :class:`~apps.panels.new_edit_workspace.NewEditWorkspace` view is a dumb
surface of fields, a token bar and an embedded map; this object is its brain.
It owns the one thing a single surface serving BOTH "create a new chart" and
"edit the loaded one" cannot own itself: which of the two it is in, and what
each button, keystroke and map click MEANS in that state.

Why a controller at all
-----------------------
The old ``EditChartPanel`` fused three sub-tabs (Edit Info / New Chart / Map)
and their glue into one 1200-line widget. The redesign keeps every one of its
hard-won behaviours — the SPEC-EDIT-001 ten-step save, the SPEC-IMPORT-001 §6.7
metadata preservation, the SPEC-MAP-004 routed-selection adoption rules, the
SPEC-TZ-001 timezone contract — but moves them OFF the widget so the view can be
replaced without touching the logic (and the logic tested without a screen).

State machine (§5 of the redesign plan)
---------------------------------------
``NEW_CLEAN`` · ``NEW_DIRTY`` · ``EDIT_CLEAN(chart)`` · ``EDIT_DIRTY(chart)``.
The header segment switches New↔Edit; leaving a ``*_DIRTY`` state prompts
Save / Discard / Stay (the SPEC-EDIT-001 cancel contract). Ctrl+Enter creates in
New and saves in Edit; loading a chart from anywhere lands in ``EDIT_CLEAN``.
"""

import logging

from PySide6.QtCore import QObject, QTimer, Slot
from PySide6.QtWidgets import QApplication, QMessageBox

from core.map_selection import SelectionPolicy

logger = logging.getLogger(__name__)

#: SPEC-MAP-004 §4.1. New & Edit never snaps — "put the chart where the user
#: clicked" is its whole meaning (snap_max_km=None). The value equals the
#: component default; the map-host gate asserts identity against THIS constant,
#: so deleting the set_selection_policy call cannot stay green.
_EDIT_CHART_POLICY = SelectionPolicy()


def _writer_for(path):
    """Return the (writer, method_name) for ``path`` (SPEC-IMPORT-001 §6.1, B5).

    Pure dispatch on the file extension so the save path NEVER writes UTF-16 CHTK
    binary over a ``.toml`` file (irreversible corruption). ``.toml`` -> a writer
    with ``update_toml_birth_data(path, birth_data)``; everything else (``.chtk``
    and legacy extensionless paths) -> CHTKWriter for backward compatibility.
    """
    from pathlib import Path
    suffix = Path(str(path)).suffix.lower()
    if suffix == ".toml":
        from core.toml_chart import TOMLChartWriter
        return TOMLChartWriter(), "update_toml_birth_data"
    from core.chtk_reader import CHTKWriter
    return CHTKWriter(), "update_chtk_birth_data"


#: field_edited logical names that move the birth INSTANT or PLACE, and so must
#: re-push the map's Ascendant-preview time basis while the form and map are both
#: on screen (the old design only pushed on switch-to-Map-View; here they are
#: side by side, so the preview tracks every relevant keystroke).
_BASIS_FIELDS = frozenset({
    "date", "local_time", "utc_time", "offset", "timezone", "dst",
    "time_mode", "lat", "lon",
})

#: field_edited logical names that change what the "Auto from zone" DST resolver
#: sees (the birth instant, the IANA zone, the coordinates) and so must re-resolve
#: the displayed DST flag + standard offset while Auto is on (WI-3). The manual
#: offset field and the DST toggle itself are absent: editing them is the user
#: overriding the zone, not feeding it. ``time_mode`` IS here: it swaps which
#: clock is authoritative, and the create road persists that clock as ``local_*``
#: (the recipe ``timedec`` reload resolves), so a mode flip near a DST transition
#: changes the resolved flag (GPT-sol WI-3 finding 2).
_AUTO_DST_FIELDS = frozenset({
    "date", "local_time", "utc_time", "timezone", "lat", "lon", "time_mode",
    # "dst": turning "Auto from zone" ON as the last action must re-resolve the
    # flag from the zone, or create computes UTC from the stale displayed flag
    # while storing -1 -> create != reload by up to an hour (Fable BUG-2).
    # _reresolve_auto_dst early-returns when Auto is off, so the applied-toggle
    # (which turns Auto off) is a no-op here.
    "dst",
})

#: field_edited names that change the derived UTC clock (Local-input mode): the
#: local instant, the offset the flag is applied to, or the mode itself. The map
#: pick path calls the recompute directly (its offset lands via _adopt_timezone).
_UTC_DERIVE_FIELDS = frozenset({
    "date", "local_time", "offset", "dst", "timezone", "time_mode",
})

#: field_edited logical names -> the token-bar CHIP that owns them. Bar<->form
#: ownership (§2 item 13) is tracked per CHIP, not per widget: a user edit to any
#: field a chip filled takes the whole chip away from the bar, and a chip's ×
#: clears exactly the fields it wrote. Fields with no chip (offset/timezone/dst/
#: gender/time_mode) are never bar-owned and are absent here.
_FIELD_TO_CHIP = {
    "name": "name",
    "date": "date",
    "local_time": "time", "utc_time": "time",
    "city": "place", "country": "place", "lat": "place", "lon": "place",
}

#: the form keys each chip writes, so a chip × blanks exactly its own columns.
_CHIP_KEYS = {
    "name": ("name",),
    "date": ("year", "month", "day"),
    "time": ("local_time",),
    "place": ("city", "country"),
}


class NewEditBinding(QObject):
    """Drives a :class:`NewEditWorkspace`. View-agnostic; no widgets of its own.

    Parameters
    ----------
    workspace:
        The :class:`NewEditWorkspace` to drive. Its ``token_bar`` and ``map_tab``
        are used directly.
    gui:
        The ``ChartGUI`` orchestrator — canonical data stores, state dispatch,
        memory panel, loading manager, status bar.
    host:
        The thin ``EditChartPanel`` that owns this binding. Used only to
        re-emit ``chart_saved`` / ``chart_modified`` (the signals the wider app
        and the remote-control layer still expect) and as a dialog parent.
    """

    def __init__(self, workspace, gui, host=None):
        super().__init__(host)
        self.ws = workspace
        self.gui = gui
        self.host = host

        # --- state machine -------------------------------------------------
        self._mode = "new"          # 'new' | 'edit'
        self._dirty = False
        self.current_chart_data = None      # the loaded memory entry (Edit mode)
        #: the last chart that was in Edit, remembered across a trip through New so
        #: New->Edit re-shows it. current_chart_data is nulled entering New (so
        #: Create makes a fresh file instead of duplicating the loaded one); this
        #: survives that, and the Edit segment restores from it.
        self._last_edit_chart = None
        self.current_birth_metadata = None

        # --- SPEC-IMPORT-002 BUG-2: pristine _toml_extra snapshot ----------
        self._loaded_toml_extra = None
        self._loaded_toml_extra_path = None

        # --- bar<->form ownership (§2 item 13) -----------------------------
        #: token-bar CHIP names the USER has taken over by hand-editing any field
        #: that chip fills; the bar must never clobber these.
        self._hand_edited = set()
        #: token-bar CHIP names the bar currently owns (it wrote them and the
        #: user has not touched them since), so a chip × clears exactly its own
        #: fields and nothing the user typed.
        self._bar_written = set()

        #: WI-1: True while the current form's time is a NOON default we supplied
        #: (no time in the line, or a blank clock at create). Reset on every path
        #: that repopulates or empties the form; cleared on a hand time-edit or a
        #: parse that carries a real time. Gates the WI-2 missing-time warning.
        self._time_defaulted = False

        # --- async create geocode (§2 item 8) ------------------------------
        #: one revision shared across the create-geocode, map clicks and reverse
        #: geocode, so a late result never overwrites a newer pick.
        self._sel_gen = 0
        self._create_geo_gen = None     # generation of an in-flight create geocode
        self._geocoder = None           # lazily built GeocodeWorker

        # --- WI-4 parse->geocode bridge (map pin follows a parsed place) ----
        #: a SECOND, dedicated GeocodeWorker so the parse bridge has its own
        #: generation stream and never cross-supersedes the create-path geocoder.
        self._parse_geocoder = None     # lazily built GeocodeWorker
        #: binding-wide PLACE revision. The map's own _bump_selection only
        #: invalidates MAP-owned work, so a click there cannot cancel THIS
        #: worker. Every newer place input (bar place edit, city/country/coord
        #: hand-edit, map pick, search, load, clear) bumps this; a parse request
        #: captures it and its landing is dropped if it has since moved on.
        self._place_rev = 0
        self._parse_place_rev = -1      # revision captured by the in-flight parse
        self._pending_parse_place = ("", "")
        self._parse_had_qualifier = True
        self._parse_geo_debounce = QTimer(self)
        self._parse_geo_debounce.setSingleShot(True)
        self._parse_geo_debounce.setInterval(600)
        self._parse_geo_debounce.timeout.connect(self._fire_parse_geocode)

        # --- WI-7 elevation lookup (display-only; SPEC-ELEV-001) ------------
        #: a real ground-elevation lookup for the resolved-place chip. Off the
        #: GUI thread, generation-guarded in the worker; the chip shows what the
        #: view decides from the RAW metres (0 m is sea level, None/NaN unknown).
        from core.elevation_service import ElevationWorker, ATTRIBUTION
        self._elev_worker = ElevationWorker(self)
        self._elev_worker.resolved.connect(self._on_elevation_resolved)
        #: coordinate hand-edits debounce a lookup (a settled pair, not each
        #: keystroke); map picks / loads request immediately.
        self._elev_debounce = QTimer(self)
        self._elev_debounce.setSingleShot(True)
        self._elev_debounce.setInterval(600)
        self._elev_debounce.timeout.connect(self._request_elevation_from_form)
        # Attribution is a TERM of Open-Meteo's licence, so surface it LOUDLY:
        # the view owns the tooltip (set_elevation_attribution, -94's API). A
        # missing setter must RAISE, not be swallowed by a getattr-in-except that
        # would silently drop the credit if the chip is ever renamed.
        self.ws.set_elevation_attribution(ATTRIBUTION)

        self._wire()
        self.ws.set_mode("new")

    # =====================================================================
    # WIRING
    # =====================================================================

    def _wire(self):
        ws = self.ws
        ws.mode_changed.connect(self._on_mode_changed)
        ws.field_edited.connect(self._on_field_edited)
        ws.create_requested.connect(self._on_create_requested)
        ws.save_requested.connect(self._on_save_requested)
        ws.save_open_requested.connect(self._on_save_open_requested)
        ws.cancel_requested.connect(self._on_cancel_requested)
        ws.clear_requested.connect(self._on_clear_requested)
        ws.tz_locked_field_touched.connect(self._on_tz_locked_touched)

        # Map: never-snap policy, Ascendant preview add-on, routed adoption.
        # NO ApplyBarAddon — there is no tab to "Apply & Return" to; the map is
        # embedded beside the form and its picks route live into the fields.
        ws.map_tab.set_selection_policy(_EDIT_CHART_POLICY)
        try:
            from apps.widgets.map_addons import AscendantAddon
            ws.map_tab.add_addon(AscendantAddon())
        except Exception:  # noqa: BLE001 - a missing add-on must never block boot
            logger.exception("Could not attach AscendantAddon to the New & Edit map")
        ws.map_tab.selection_routed.connect(self._on_selection_routed)
        # WI-4: a user starting a place search supersedes an in-flight parse
        # geocode NOW (not only when the search resolves), or a stale parse
        # landing could preempt the search the user explicitly asked for.
        ws.map_tab.search_started.connect(self._supersede_place)

        # Token bar (WI-3): parsed chips fill the form under the ownership rules;
        # a chip × clears only what that chip wrote; Ctrl+Enter accepts by mode.
        ws.token_bar.parsed.connect(self._on_bar_parsed)
        ws.token_bar.token_cleared.connect(self._on_bar_token_cleared)
        ws.token_bar.accept_requested.connect(self._on_accept_requested)

    # =====================================================================
    # STATE MACHINE
    # =====================================================================

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    @property
    def is_modified(self) -> bool:
        """Legacy alias — the old panel exposed ``is_modified`` as an attribute."""
        return self._dirty

    def _state(self) -> str:
        return "%s_%s" % (self._mode.upper(), "DIRTY" if self._dirty else "CLEAN")

    def _set_dirty(self, dirty: bool):
        self._dirty = bool(dirty)

    def _mark_modified(self):
        """Enter a ``*_DIRTY`` state and re-emit the legacy ``chart_modified``."""
        self._set_dirty(True)
        if self.host is not None:
            try:
                self.host.chart_modified.emit(self.ws.collect_data())
            except Exception:  # noqa: BLE001
                logger.exception("chart_modified re-emit failed")

    @Slot(str)
    def _on_mode_changed(self, mode: str):
        """User clicked the New/Edit segment. Guard leaving a dirty state."""
        target = "edit" if str(mode).lower() == "edit" else "new"
        if target == self._mode:
            return
        if self._dirty and not self._confirm_leave_dirty():
            # Bounce the segment back — the view already flipped it.
            self.ws.set_mode(self._mode)
            return
        if target == "new":
            self._enter_new_clean()
        else:
            # Switching to Edit re-shows the chart that was being edited — the
            # current one, or the one remembered from before this trip through New
            # (the bug: entering New nulls current_chart_data, so without the
            # remembered ref the form came back BLANK). With neither, Edit is empty
            # and Save refuses (no chart to write).
            chart = self.current_chart_data or self._last_edit_chart
            if chart:
                self.load_chart_from_memory(chart)
            else:
                self.ws.set_mode("edit")
                self._mode = "edit"
                self._set_dirty(False)

    def _confirm_leave_dirty(self) -> bool:
        """SPEC-EDIT-001 cancel contract: Save / Discard / Stay. True = proceed."""
        box = QMessageBox(self.host)
        box.setWindowTitle("Unsaved changes")
        box.setText("This chart has unsaved changes.")
        box.setIcon(QMessageBox.Icon.Question)
        save = box.addButton("Save", QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Stay", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is save:
            # Edit-mode saves the loaded chart; New-mode "Save" means CREATE the
            # typed chart (there is no file yet). Proceed only if it succeeded —
            # a refused create (bad/blank place, validation) keeps the user on the
            # form instead of silently dropping their work on the mode switch.
            if self._mode == "edit":
                return self._save()
            return self._on_create_requested()
        if clicked is discard:
            return True
        return False

    def _enter_new_clean(self):
        # Leaving Edit for New starts a BLANK chart. Not clearing the form left
        # the loaded chart's values in place, so Create silently duplicated it —
        # and current_chart_data was already gone, so Edit could not restore it.
        self._mode = "new"
        # Remember the chart we're leaving so New->Edit can restore it (it is
        # still on disk / in the memory panel; only this form forgets it).
        if self.current_chart_data:
            self._last_edit_chart = self.current_chart_data
        self.current_chart_data = None
        self.current_birth_metadata = None
        self._loaded_toml_extra = None
        self._loaded_toml_extra_path = None
        self._hand_edited.clear()
        self._bar_written.clear()
        self._time_defaulted = False    # WI-1 lifecycle: blank New, no default yet
        self._create_geo_gen = None
        self._clear_elevation()         # WI-7: blank New ⇒ no elevation
        self._supersede_place()         # WI-4: drop any pending parse geocode
        self.ws.clear_fields()
        self.ws.token_bar.clear()
        self.ws.set_mode("new")
        self._set_dirty(False)

    @Slot(str)
    # ---- WI-1/WI-2: noon default + missing-time warning ------------------

    def _authoritative_time_blank(self):
        """``(all_blank, hour_blank)`` for the AUTHORITATIVE clock's RAW widget
        text — blank meaning the field has no text, which is DISTINCT from a
        typed ``0`` (``collect_data`` coerces ``int('' or 0)`` = 0, the very bug
        WI-1 closes). Read straight off the view widgets, exactly like the
        coordinate emptiness check in ``_on_create_requested``, so nothing needs
        to be added to the view's file (another session's lane)."""
        ws = self.ws
        if getattr(ws, "time_mode", "Local") == "UTC":
            h, m, s = ws.utc_hour, ws.utc_minute, ws.utc_second
        else:
            h, m, s = ws.local_hour, ws.local_minute, ws.local_second
        ht = (h.text() or "").strip()
        mt = (m.text() or "").strip()
        st = (s.text() or "").strip()
        return (not ht and not mt and not st), (not ht)

    def _both_clocks_blank(self):
        """True only when the LOCAL and the UTC clock are BOTH entirely blank —
        the one safe condition to assume 'no time was given' and default noon.
        A value in the non-authoritative clock (e.g. the user typed a UTC time
        then switched the input to Local) means a time WAS given, so noon must
        neither fire nor destroy it (review finding)."""
        ws = self.ws

        def _blank(h, m, s):
            return (not (h.text() or "").strip()
                    and not (m.text() or "").strip()
                    and not (s.text() or "").strip())
        return (_blank(ws.local_hour, ws.local_minute, ws.local_second)
                and _blank(ws.utc_hour, ws.utc_minute, ws.utc_second))

    def _notify_warning(self, kind: str, message: str):
        """Surface a ``(kind, message)`` warning to the user DIRECTLY on the
        status bar (WI-2), bypassing ``report_tz_warnings``' ``"Timezone:"``
        prefix filter — that filter is correct and untouched for real timezone
        warnings; this is a separate channel. None-guarded for headless tests."""
        text = message or ""
        first_line = text.splitlines()[0] if text else ""
        sb_fn = getattr(self.gui, "statusBar", None) if self.gui else None
        sb = sb_fn() if callable(sb_fn) else None
        if sb is not None and first_line:
            sb.showMessage("New & Edit: %s" % first_line)
        logger.info("[NEW-EDIT-WARN] %s: %s", kind, text.replace("\n", " "))

    def _on_tz_locked_touched(self):
        """A locked time-zone field was clicked. Tell the user how it fills."""
        self._notify_warning(
            "tz_locked",
            "Time-zone values fill automatically — click the map or search a "
            "place. Use the lock button to type them by hand.")

    def _warn_no_time(self):
        """Fire the canonical no-time warning (WI-2) on the New & Edit surface."""
        from managers.chart_creation_pipeline import WARN_NO_TIME, MSG_NO_TIME
        self._notify_warning(WARN_NO_TIME, MSG_NO_TIME)

    def _ensure_noon_before_collect(self):
        """Belt-and-braces on the create/save roads, BEFORE ``collect_data``: a
        wholly blank authoritative clock, or a blank HOUR alone (minutes/seconds
        typed), must resolve to a real time — never the ``int('' or 0)`` = 0
        midnight ``collect_data`` would otherwise produce (WI-1, both doors).

        Writes ONLY the authoritative clock widgets (suppressed). The earlier
        version round-tripped the WHOLE form through ``populate(collect_data())``,
        which materialised ``0.000000`` into blank coordinate fields — a
        blank-placed create then read those phantom coordinates and built a
        ``(0, 0)`` chart instead of geocoding the typed city (Fable BUG-1)."""
        all_blank, hour_blank = self._authoritative_time_blank()
        if not (all_blank or hour_blank):
            return
        merged = self.ws.collect_data()
        if not merged:
            # A transiently-invalid field (e.g. latitude "-") broke collect_data;
            # do not act on a form we cannot read (no-wipe invariant).
            return
        # A wholly blank authoritative clock while the OTHER clock holds a value
        # is a mode boundary, not a no-time: derive this clock from the other so
        # a UTC-entered instant is not silently lost (GPT-sol BUG-2 midnight).
        if all_blank and not self._both_clocks_blank():
            if self._derive_authoritative_clock():
                return
        if all_blank:
            h, m, s = 12, 0, 0
        else:  # hour alone blank → 12; KEEP the typed minute/second
            h = 12
            m = merged.get("minute", 0) or 0
            s = merged.get("second", 0) or 0
        self._set_authoritative_clock(h, m, s)
        self._time_defaulted = True

    def _authoritative_clock_widgets(self):
        """The (hour, minute, second) widget triple the current time_mode reads."""
        ws = self.ws
        if getattr(ws, "time_mode", "Local") == "UTC":
            return ws.utc_hour, ws.utc_minute, ws.utc_second
        return ws.local_hour, ws.local_minute, ws.local_second

    def _set_authoritative_clock(self, h, m, s):
        """Write the authoritative clock directly (suppressed), touching NOTHING
        else — so a create/save-time default cannot materialise phantom values
        into blank coordinate/date/offset fields."""
        ws = self.ws
        hh, mm, ss = self._authoritative_clock_widgets()
        ws._suppress = True
        try:
            ws._set_clock(hh, mm, ss, h, m, s)
        finally:
            ws._suppress = False

    def _derive_authoritative_clock(self):
        """Fill a blank authoritative clock from the value in the OTHER clock (a
        mode switch left it blank). Returns True if it set a time, False to let
        the caller fall back to noon. Local-authoritative derives from the UTC
        clock and vice versa, using the form's offset + DST flag."""
        ws = self.ws
        utc_mode = getattr(ws, "time_mode", "Local") == "UTC"
        src = ((ws.local_hour, ws.local_minute, ws.local_second) if utc_mode
               else (ws.utc_hour, ws.utc_minute, ws.utc_second))
        if not (src[0].text() or "").strip():
            return False
        form = ws.collect_data()
        if not form:
            return False
        try:
            from core.time_utils import local_to_utc, utc_to_local
            y, mo, d = int(form["year"]), int(form["month"]), int(form["day"])
            sh = int(src[0].text() or 0)
            sm = int(src[1].text() or 0)
            ssec = int(src[2].text() or 0)
            offset = form.get("timezone") or "+00:00"
            dst = int(form.get("dst") or 0)
            if utc_mode:   # authoritative UTC, derive FROM the local clock
                ay, amo, ad, ah, am, asec = local_to_utc(y, mo, d, sh, sm, ssec, offset, dst)
            else:          # authoritative Local, derive FROM the UTC clock
                ay, amo, ad, ah, am, asec = utc_to_local(y, mo, d, sh, sm, ssec, offset, dst)
        except Exception:  # noqa: BLE001 - incomplete/invalid instant, leave to noon
            return False
        # Set BOTH the derived DATE and clock: a near-midnight instant can roll the
        # authoritative date across a day boundary, and dropping it left the chart
        # 24h off (Codex C2). The date field's meaning flips with time_mode, so the
        # authoritative date is exactly the conversion's returned y/m/d.
        self._set_authoritative_date(ay, amo, ad)
        self._set_authoritative_clock(ah, am, asec)
        return True

    def _set_authoritative_date(self, y, mo, d):
        """Write the date fields directly (suppressed), matching the display width
        the rest of the form uses (YYYY / MM / DD)."""
        ws = self.ws
        ws._suppress = True
        try:
            ws.date_year.setText(f"{int(y):04d}")
            ws.date_month.setText(f"{int(mo):02d}")
            ws.date_day.setText(f"{int(d):02d}")
        finally:
            ws._suppress = False

    def _on_field_edited(self, name: str):
        """A real user edit (the view suppresses this during programmatic writes).

        Marks the form dirty, hands the whole chip that filled this field back to
        the user (so the bar cannot clobber it and its × cannot clear it), cancels
        any in-flight create-geocode for a place change, and re-pushes the map
        time basis for instant/place edits.
        """
        chip = _FIELD_TO_CHIP.get(name)
        if chip is not None:
            self._hand_edited.add(chip)
            self._bar_written.discard(chip)
        # A real time edit means the user owns the time; our noon default (and
        # its warning) no longer applies (WI-1 lifecycle).
        if name in ("local_time", "utc_time"):
            self._time_defaulted = False
        self._mark_modified()
        # A place edit supersedes any pending create-geocode: the resolved result
        # is for the OLD text and must not overwrite what the user just typed.
        if name in ("city", "country", "lat", "lon"):
            self._create_geo_gen = None
            # WI-4: a hand edit to place ALSO supersedes a pending parse-geocode
            # (the pin must follow what the user just typed, not the old line).
            self._supersede_place()
        # WI-7: a hand-edited coordinate must never sit beside a STALE elevation
        # from the previous place. Blank it now, drop any in-flight lookup, then
        # debounce a fresh one once the typed pair settles.
        if name in ("lat", "lon"):
            self.ws.set_elevation(None)
            self._elev_worker.cancel()
            self._elev_debounce.start()
        # A mode switch must not silently drop the time typed in the OTHER clock:
        # derive the now-authoritative clock from it BEFORE _recompute_derived_utc,
        # which blanks the derived UTC field when the local clock reads empty and
        # would otherwise erase a UTC-entered instant on the flip to Local (BUG-6).
        if name == "time_mode":
            self._derive_authoritative_clock()
        # WI-3: keep the Auto-resolved DST flag + offset current BEFORE the map
        # basis push, which reads the offset the resolver just refreshed.
        if name in _AUTO_DST_FIELDS:
            self._reresolve_auto_dst()
        # Live derived UTC: recompute AFTER the DST re-resolve (which may have
        # moved the offset/flag), so the UTC clock tracks every relevant edit
        # instead of appearing only at validation.
        if name in _UTC_DERIVE_FIELDS:
            self._recompute_derived_utc()
        if name in _BASIS_FIELDS:
            self._push_map_time_basis()

    # =====================================================================
    # MAP WIRING  (re-homed: _push_map_time_basis, _on_selection_routed)
    # =====================================================================

    def _recompute_derived_utc(self):
        """Show the UTC clock the birth instant implies, LIVE — on every map pick
        and local-instant/offset edit, NOT only at create/save (where Lorris saw
        it 'appear only after validation'). Local-input mode only: in UTC-input
        mode the UTC clock IS the input, so there is nothing to derive onto it.

        A blank/incomplete local clock blanks the UTC field rather than lie; a
        bad offset leaves the last value standing until the input settles."""
        if getattr(self.ws, "time_mode", "Local") == "UTC":
            return
        # An empty local clock has no derivable UTC — blank it, do not stamp 0.
        if not self.ws.local_hour.text().strip():
            self.ws.set_derived_utc(None, None, None)
            self.ws.set_day_offset("")
            return
        form = self.ws.collect_data()
        if not form:
            return
        try:
            import datetime
            from core.time_utils import local_to_utc
            y, mo, d = int(form["year"]), int(form["month"]), int(form["day"])
            hh = int(form.get("hour") or 0)
            mi = int(form.get("minute") or 0)
            ss = int(form.get("second") or 0)
            offset = form.get("timezone") or "+00:00"
            dst = int(form.get("dst") or 0)
            uy, um, ud, uh, umin, us = local_to_utc(
                y, mo, d, hh, mi, ss, offset, dst)
        except Exception:  # noqa: BLE001 - incomplete/invalid instant, leave as-is
            return
        self.ws.set_derived_utc(uh, umin, us)
        try:
            delta = (datetime.date(uy, um, ud) - datetime.date(y, mo, d)).days
        except Exception:  # noqa: BLE001 - BCE etc.; no marker rather than crash
            delta = 0
        self.ws.set_day_offset({-1: "(-1d)", 1: "(+1d)"}.get(delta, ""))

    def _push_map_time_basis(self):
        """Give the map the birth civil time, zodiac mode and labels.

        Basis-first ordering (SPEC-MAP-002): callers that follow with
        ``set_marker`` must push the basis first, or the band scan runs against
        the stale birth time and then accepts that stale result.
        """
        map_tab = self.ws.map_tab
        if not hasattr(map_tab, "set_time_basis"):
            return
        form_data = self.ws.collect_data()
        try:
            local_fields = {
                "year": int(form_data["year"]), "month": int(form_data["month"]),
                "day": int(form_data["day"]), "hour": int(form_data.get("hour", 0)),
                "minute": int(form_data.get("minute", 0)),
                "second": int(form_data.get("second", 0)),
            }
        except (KeyError, TypeError, ValueError):
            # An incomplete form is not an error — the preview stays off (INV-4).
            map_tab.set_time_basis(None)
            return

        # A live preview must NEVER break the form: any failure to build the
        # basis (a headless host with no gui.state, an ephemeris hiccup) leaves
        # the preview off, exactly like an incomplete form (INV-4). The old
        # panel only reached this on an explicit switch-to-Map; here it fires on
        # every instant/place keystroke, so the guard widens to match.
        try:
            from core.aditya_mode import displayed_sign_name
            mode = self.gui.state.aditya_mode
            # The label set (use_western_names) lives on the GUI and is
            # orthogonal to the mode (SPEC-ZOD-001 / SPEC-MODE-001) — read the
            # real flag, never derive it from the mode.
            use_western = getattr(self.gui, "use_western_names", False)
            language = getattr(self.gui, "sign_language", "en")
            names = [displayed_sign_name(i, mode, use_western, language)
                     for i in range(12)]
            map_tab.set_time_basis(
                local_fields, mode=mode,
                ayanamsa=getattr(self.gui, "chart_sidereal_ayanamsa_id", 100),
                sign_names=names,
                # A UTC-entered chart has utc_* == local_* by definition;
                # without this the preview subtracts the place offset and shows
                # an Ascendant a whole UTC offset away from the chart being built.
                utc_input=(form_data.get("time_mode") == "UTC"))
        except Exception:  # noqa: BLE001
            try:
                map_tab.set_time_basis(None)
            except Exception:  # noqa: BLE001
                pass

    @Slot(object)
    def _on_selection_routed(self, routed):
        """Adopt a routed map selection into the one form (SPEC-MAP-004 T-12).

        The timezone comes from the frozen ``RoutedSelection``, not a live
        ``get_detected_timezone()`` read beside signal-payload coordinates: one
        object closes the snapshot-vs-live window that produced the documented
        routed-Paris / legacy-Tokyo split. There is a single form now, so the
        old per-caller (info vs new_chart) routing collapses to this one path.
        """
        self._sel_gen += 1  # a fresh pick supersedes any in-flight create geocode
        self._create_geo_gen = None

        self.ws.set_coordinates(routed.lat, routed.lon)
        # WI-7: a routed pick has final coordinates — look up its elevation now
        # (set_coordinates is programmatic, so the coord-edit debounce never fires
        # for it; the worker's generation guard drops this if another pick lands).
        self._request_elevation(routed.lat, routed.lon)

        # CITY is written when present; otherwise cleared ONLY on a country
        # change. Writing it unconditionally erased a user-typed city offline
        # (the reverse geocode returns nothing, city stayed ""), so the empty
        # first pass must not blank the field. A city from another country is
        # not stale, it is wrong — hence the country-change clear. Read straight
        # off the field; the view exposes no getter.
        field = getattr(self.ws, "country_input", None)
        previous_country = (field.text() or "").strip() if field is not None else ""
        self.ws.set_country(routed.country)
        if routed.city:
            self.ws.set_city(routed.city)
        elif routed.country and previous_country and routed.country != previous_country:
            self.ws.set_city("")

        # Unconditional — a guarded assignment is exactly what F-1 was. A None
        # tz_name is a resolver failure: clearing the offset makes Save/Create
        # refuse visibly in Local mode (SPEC-MAP-004 §4.3) instead of a silent-
        # UTC chart wearing a resolved look.
        self._adopt_timezone(routed.tz_name)

        # Routing note on the form the user saves from (incl. "" — an unresolved
        # warning must not survive the next resolved pick). SPEC-MAP-004 §4.4.
        self.ws.set_location_note(routed.note or "")

        # Live derived UTC: a map pick just set the offset, so the UTC clock the
        # instant implies must update NOW, not wait for create/save validation.
        self._recompute_derived_utc()

        # WI-4: only a USER pick (click/search) is a place edit that takes the
        # 'place' chip from the bar. A PARSE-driven route must NOT — the bar keeps
        # the place text, or a later re-parse of the line could no longer move the
        # pin. A parse route also must not supersede ITSELF (it is the landing).
        origin = getattr(routed, "origin", "click")
        if origin in ("click", "search"):
            self._hand_edited.add("place")
            self._bar_written.discard("place")
            self._supersede_place()   # a user pick drops any pending parse geocode
        self._mark_modified()
        self._push_map_time_basis()

    def _adopt_timezone(self, tz_name):
        """Resolve a routed timezone into the form (the old set_timezone brain).

        The view's ``set_timezone`` is deliberately dumb (SPEC-UTC-001 keeps the
        arithmetic in one place), so the CONTROLLER decomposes an IANA name into
        the +HH:MM offset for the birth date and the DST flag — exactly what
        ``EditInfoSubTab.set_timezone`` used to do inline — and hands both to the
        view. A raw offset is passed straight through; ``None`` clears the offset
        so Local-mode Save/Create refuses (F-1).
        """
        if tz_name is None:
            self.ws.set_timezone("")
            return
        if "/" not in str(tz_name):
            self.ws.set_timezone(tz_name)   # already an offset
            return
        iana = str(tz_name)
        form = self.ws.collect_data()
        offset_format = None
        dst_flag = None
        try:
            from core.time_utils import resolve_total_offset, format_offset
            y = int(form.get("year") or 2000)
            mo = int(form.get("month") or 1)
            d = int(form.get("day") or 1)
            hh = int(form.get("hour") or 0)
            mi = int(form.get("minute") or 0)
            std_hours, dst_flag = resolve_total_offset(iana, y, mo, d, hh, mi)
            offset_format = format_offset(0, int(round(std_hours * 60)))
        except Exception:  # noqa: BLE001 - fall back to name-only, offset blank
            offset_format = None
        if offset_format is None:
            # Could not resolve (bad name / missing date): show the name, leave
            # the offset empty so the Local-mode refusal still fires.
            self.ws.set_timezone_resolved(iana, "", None)
        else:
            self.ws.set_timezone_resolved(iana, offset_format, dst_flag)

    def _reresolve_auto_dst(self):
        """WI-3 (SPEC-TZ-001 / project_dst_flag_minus1_resolution): while
        "Auto from zone" is on, keep the DISPLAYED DST flag and standard offset
        equal to what the stored ``-1`` sentinel resolves to on reload.

        The create/save road computes UTC from the displayed 0/1 flag but stores
        ``-1`` (see ``_finalize``/``_save`` ~L993); reload re-resolves ``-1`` from
        the IANA zone at the birth instant (``resolve_recipe_dst_flag`` ->
        ``resolve_auto_dst_flag(iana, y,m,d, h,m, longitude=lon)``). If the display
        went stale after a date/time/zone/coord edit, create-UTC and reload-UTC
        would part by an hour. So on every relevant edit under Auto, re-resolve
        and push offset+flag back silently (the ToggleSwitch emits ``toggled``
        only on a real click, so this cannot trip the un-Auto gate or echo a
        field_edited).

        To make the display equal reload *exactly*, this mirrors the create/reload
        road on three points the naive version got wrong (GPT-sol WI-3 review):

        1. **Blank form IANA is NOT "no zone".** ``create_from_form_data`` detects
           an IANA from the coordinates when the field is empty and PERSISTS it
           (birth_data_manager :627), so reload resolves ``-1`` against that
           detected zone. We detect the same way (warm ``tz_finder.timezone_at``)
           and resolve against it — only forcing 0 when there is genuinely no
           zone, which reload's falsy-IANA branch also yields 0 for.
        2. **The AUTHORITATIVE clock, not the local widget.** In UTC-input mode the
           create road stores the UTC clock as ``local_*`` (:584), and that becomes
           the recipe ``timedec`` reload resolves. So resolve at ``form['hour']``
           (the authoritative clock in either mode); a derived local widget would
           part from reload near a DST transition.
        3. **An invalid slash-IANA degrades to 0, it does not keep a stale flag.**
           A half-typed ``"Europe/Par"`` passes the '/' check, then resolution
           throws; reload's resolver hits the same lookup error and returns 0, and
           the chart is savable (the IANA field is not validated). So the except
           branch shows 0, never a possibly-``1`` leftover.
        """
        if not self.ws.dst_auto_enabled():
            return
        form = self.ws.collect_data()
        if not form:
            return  # a transiently invalid field ({} collect); nothing to resolve

        form_iana = str(form.get("iana_timezone") or "").strip()
        iana = form_iana
        if "/" not in iana:
            # Finding 1: match the create road's coord->IANA detection so we
            # resolve against the SAME zone reload will. Warm singleton (0.7 ms),
            # not birth_data_manager._detect_timezone (fresh 788 ms build).
            try:
                from core.tz_finder import timezone_at
                detected = timezone_at(form.get("latitude"), form.get("longitude"))
            except Exception:  # noqa: BLE001 - finder absent / not ready
                detected = None
            iana = detected if (detected and "/" in str(detected)) else ""

        if "/" not in iana:
            # Genuinely no zone (blank or unresolvable coords): reload's
            # resolve_auto_dst_flag(None) yields 0 (fail-loud, SPEC-TZ-001 5f).
            self.ws.set_dst_resolved(0)
            return

        try:
            from core.time_utils import resolve_total_offset, format_offset
            y = int(form.get("year") or 2000)
            mo = int(form.get("month") or 1)
            d = int(form.get("day") or 1)
            # Finding 2: the authoritative clock — the same value reload sees as
            # the recipe's local instant (UTC mode stores the UTC clock as
            # local_*). NEVER reach into the derived local widget.
            hh = int(form.get("hour") or 12)
            mi = int(form.get("minute") or 0)
            # Finding 4 (already committed): pass the raw float; a real Greenwich
            # longitude 0.0 must not be dropped, or the LMT correction the reload
            # road applies (recipe['lon'] verbatim) is skipped.
            lon = form.get("longitude")
            std_hours, dst_flag = resolve_total_offset(
                iana, y, mo, d, hh, mi, longitude=lon)
            offset_format = format_offset(0, int(round(std_hours * 60)))
        except Exception:  # noqa: BLE001 - Finding 3: invalid/partial IANA
            # Reload degrades an unresolvable zone's -1 to 0; match it rather
            # than keep a stale (maybe 1) flag. Leave the offset the user typed.
            self.ws.set_dst_resolved(0)
            return

        if form_iana:
            # The user/map own an explicit zone: it owns BOTH the offset and flag.
            self.ws.set_timezone_resolved(iana, offset_format, dst_flag)
        else:
            # Zone was detected from coords: create's UTC uses the offset FIELD
            # (unchanged) and only the FLAG diverges from reload, so fix only that.
            self.ws.set_dst_resolved(dst_flag)

    # =====================================================================
    # ELEVATION  (WI-7 / SPEC-ELEV-001 — display-only, never persisted)
    # =====================================================================

    def _request_elevation(self, lat, lon):
        """Mark the chip pending and fire a lookup for a VALID coordinate.

        Invalid/out-of-range/non-finite pairs are ignored (the service rejects
        them anyway); the chip keeps whatever it last showed rather than pretend
        to be asking about a point we will not query.
        """
        try:
            latf, lonf = float(lat), float(lon)
        except (TypeError, ValueError):
            return
        import math
        if not (math.isfinite(latf) and math.isfinite(lonf)):
            return
        if not (-90.0 <= latf <= 90.0 and -180.0 <= lonf <= 180.0):
            return
        self.ws.set_elevation_pending()
        self._elev_worker.request(latf, lonf)

    def _request_elevation_from_form(self):
        """Debounced coordinate-hand-edit landing: look up the typed pair ONLY
        when BOTH coordinate fields actually hold text.

        ``collect_data()`` coerces a blank field to ``0.0`` (the same trap WI-1
        closes for the clock), so reading it here would look up ``(0.0, lon)``
        and paint a wrong place's elevation beside an empty latitude field
        (GPT-sol WI-7 finding 2). Read the raw widgets, like the clock-emptiness
        check does, and require a complete pair."""
        lat_txt = self.ws.latitude_input.text().strip()
        lon_txt = self.ws.longitude_input.text().strip()
        if not lat_txt or not lon_txt:
            return  # incomplete pair; the chip is already blank from the edit
        self._request_elevation(lat_txt, lon_txt)

    def _clear_elevation(self):
        """Blank the chip and drop any in-flight lookup (clear / new / reset)."""
        self._elev_debounce.stop()
        self._elev_worker.cancel()
        self.ws.set_elevation(None)

    @Slot(object)
    def _on_elevation_resolved(self, value):
        """Worker landing (already generation-guarded inside the worker). Hand
        the RAW metres to the view — NEVER gate on truthiness, or a 0 m coastal
        birth would silently read as unknown (the falsy-zero trap)."""
        self.ws.set_elevation(value)

    # =====================================================================
    # PARSE -> GEOCODE BRIDGE  (WI-4: the map pin follows a parsed place)
    # =====================================================================

    def _ensure_parse_geocoder(self):
        if self._parse_geocoder is None:
            from core.geocode_service import GeocodeWorker
            self._parse_geocoder = GeocodeWorker(self)
            self._parse_geocoder.resolved.connect(self._on_parse_geocoded)
        return self._parse_geocoder

    def _supersede_place(self):
        """Any NEWER place input (hand-edit, map pick, search, load, clear) makes
        a pending parse-geocode stale. Bump the binding-wide revision so a late
        landing is dropped, stop the debounce, and cancel the in-flight worker so
        obsolete network work does not run. The map's own _bump_selection cannot
        do this — it only invalidates MAP-owned generations, not this bridge."""
        self._place_rev += 1
        self._parse_geo_debounce.stop()
        if self._parse_geocoder is not None:
            self._parse_geocoder.cancel()
        # A newer place also invalidates a pending CREATE-geocode: without this a
        # slow Create lookup could land after a load/clear/search and overwrite the
        # now-current form, then create from the mixture (GPT-sol/Fable BUG-3). Load,
        # clear, search-start and place hand-edits all route through here.
        self._create_geo_gen = None

    def _schedule_parse_geocode(self, city, country):
        """The bar wrote a place chip; debounce a geocode so a settled line (not
        every keystroke) moves the pin. Restarting the timer coalesces a burst of
        edits into one lookup.

        Supersede FIRST (GPT-sol WI-4 finding 1): a new parsed place must bump the
        revision and cancel any already-fired earlier request, or a stale landing
        for the PREVIOUS place could pass the guard during this debounce window
        and move the pin before this place's own request even fires."""
        self._supersede_place()
        self._pending_parse_place = (city or "", country or "")
        self._parse_geo_debounce.start()

    def _fire_parse_geocode(self):
        """Debounce landing: capture the CURRENT revision and geocode the parsed
        place. The captured revision is what the result is checked against, so a
        place input that arrives while the network is out drops the stale pin."""
        city, country = self._pending_parse_place
        query = ", ".join(p for p in (city, country) if p)
        if not query:
            return
        self._parse_place_rev = self._place_rev
        self._parse_had_qualifier = bool(country)
        self._ensure_parse_geocoder().request_forward(query)

    @Slot(object)
    def _on_parse_geocoded(self, result):
        """Parse-geocode landing. Drop it if any newer place input has arrived
        since the request was fired (binding-wide revision guard); otherwise hand
        it to the map through its own transaction, tagged origin='parse' so the
        pin moves WITHOUT the bar losing the place chip."""
        if self._parse_place_rev != self._place_rev:
            return  # superseded by a hand-edit / pick / search / load / clear
        self.ws.map_tab.apply_geocode_result(
            result, origin="parse", had_qualifier=self._parse_had_qualifier)

    # =====================================================================
    # TOKEN BAR  (bar<->form ownership, §2 item 13)
    # =====================================================================

    @Slot(dict)
    def _on_bar_parsed(self, parsed: dict):
        """Fill ONLY the fields this parse produced that the user has not
        hand-edited since. The bar owns what it wrote; the form owns what the
        user typed. A programmatic populate() is suppressed in the view, so it
        never re-marks these as user edits.
        """
        if not parsed:
            return
        merged = dict(self.ws.collect_data())
        wrote_chips = set()

        # NAME chip.
        if parsed.get("name") and "name" not in self._hand_edited:
            merged["name"] = parsed["name"]
            wrote_chips.add("name")
        # DATE chip.
        if parsed.get("has_date") and "date" not in self._hand_edited:
            merged["year"] = parsed.get("year")
            merged["month"] = parsed.get("month")
            merged["day"] = parsed.get("day")
            wrote_chips.add("date")
        # TIME chip — the parser reports a LOCAL wall-clock; land it on the local
        # clock and let the controller derive UTC on create/save.
        if parsed.get("has_time") and "time" not in self._hand_edited:
            merged["time_mode"] = merged.get("time_mode") or "Local"
            merged["local_hour"] = parsed.get("hour")
            merged["local_minute"] = parsed.get("minute")
            merged["local_second"] = parsed.get("second", 0)
            merged["hour"] = parsed.get("hour")
            merged["minute"] = parsed.get("minute")
            merged["second"] = parsed.get("second", 0)
            wrote_chips.add("time")
            self._time_defaulted = False   # a real time replaces any noon default
        # PLACE chip (city/country; the parser resolves no coordinates).
        # The parser returns city="Unknown" as its no-place sentinel (e.g. when
        # re-parsing an empty line on a bar clear); treat that as absent so a
        # clear cannot stamp "Unknown" into the city field.
        _city = parsed.get("city")
        if _city in ("Unknown", None, ""):
            _city = None
        _country = parsed.get("country") or None
        if "place" not in self._hand_edited and (_city or _country):
            if _city:
                merged["city"] = _city
            if _country:
                merged["country"] = _country
            wrote_chips.add("place")

        # No time in a REAL line → default to noon, never midnight (WI-1),
        # matching the canonical path (parser: has_time False, hour 12). Only
        # when a real chip was written, the user has not hand-edited the time,
        # the bar does not already own a time, and the clock is actually blank.
        # Ownership is NOT taken (no "time" in _bar_written): the parser emitted
        # no time chip, so a later real time or a hand edit overwrites noon freely.
        if (wrote_chips and not parsed.get("has_time")
                and "time" not in self._hand_edited
                and "time" not in self._bar_written):
            if self._both_clocks_blank():
                merged["time_mode"] = merged.get("time_mode") or "Local"
                merged["local_hour"], merged["local_minute"], merged["local_second"] = 12, 0, 0
                merged["hour"], merged["minute"], merged["second"] = 12, 0, 0
                self._time_defaulted = True
                self._warn_no_time()

        if not wrote_chips:
            return
        self._repopulate(merged)
        # A bar parse is a real edit (populate() is suppressed so it does not
        # self-report), so mark the form dirty -- otherwise a chart typed ONLY
        # into the token bar bypasses the Save/Discard/Stay guard on a mode
        # switch and is lost silently (smoke-test finding 2026-08-14).
        self._mark_modified()
        self._bar_written |= wrote_chips     # the bar now owns these chips
        # WI-4: a freshly parsed place must MOVE THE MAP, not just fill the text.
        # The parser resolves no coordinates, so geocode the "City, Country" the
        # bar just wrote (debounced) and route the pin to it. Only fires when the
        # bar actually took the place chip (user has not hand-owned place).
        if "place" in wrote_chips:
            self._schedule_parse_geocode(_city, _country)
        self._push_map_time_basis()

    @Slot(str)
    def _on_bar_token_cleared(self, chip: str):
        """A chip × was used. Blank ONLY the fields that chip wrote, and only if
        the bar still owns the chip (a hand-edit since dropped it)."""
        # Clearing the place chip must drop any in-flight parse geocode, or a
        # request fired before the × lands afterward and repopulates the place
        # the user just removed (GPT-sol WI-4 finding 3).
        if chip == "place":
            self._supersede_place()
        if chip not in self._bar_written:
            return
        merged = dict(self.ws.collect_data())
        for key in _CHIP_KEYS.get(chip, ()):
            if key == "name":
                merged["name"] = ""
            elif key in ("year", "month", "day"):
                merged[key] = None
            elif key == "local_time":
                merged["hour"] = merged["minute"] = merged["second"] = None
                merged["local_hour"] = merged["local_minute"] = merged["local_second"] = None
            elif key in ("city", "country"):
                merged[key] = ""
        self._repopulate(merged)
        self._bar_written.discard(chip)
        self._push_map_time_basis()

    def _repopulate(self, merged):
        """``populate`` for the token-bar round-trip paths that must NOT stamp
        phantom values into fields the user left blank. ``collect_data`` coerces a
        blank coordinate/date/offset to ``0``/``'+00:00'`` and reports the resolved
        0/1 DST flag; a plain ``populate`` would then write
        ``0.000000``/``0000``/``+00:00`` into the blanks (Fable BUG-1). Re-blank any
        coerce-prone field that was blank before AND still carries its
        coerced-blank value (a chip that genuinely filled it wins and is kept)."""
        ws = self.ws
        merged = dict(merged)
        probes = (("latitude_input", "latitude", 0.0),
                  ("longitude_input", "longitude", 0.0),
                  ("date_year", "year", 0), ("date_month", "month", 0),
                  ("date_day", "day", 0), ("timezone_input", "timezone", "+00:00"))
        blank_before = {attr for attr, _k, _c in probes
                        if getattr(ws, attr, None) is not None
                        and not (getattr(ws, attr).text() or "").strip()}
        ws.populate(merged)
        to_blank = [attr for attr, key, coerced in probes
                    if attr in blank_before and merged.get(key) in (coerced, None)]
        if to_blank:
            ws._suppress = True
            try:
                for attr in to_blank:
                    getattr(ws, attr).setText("")
            finally:
                ws._suppress = False

    @Slot()
    def _on_accept_requested(self):
        """Ctrl+Enter from the token bar — same as the mode's primary action."""
        if self._mode == "new":
            self._on_create_requested()
        else:
            self._on_save_requested()

    # =====================================================================
    # LOAD  (re-homed verbatim: load_chart_from_memory recipe resolution)
    # =====================================================================

    def load_chart_from_memory(self, chart_entry: dict):
        """Populate the form + map from a memory-panel entry → ``EDIT_CLEAN``."""
        if not chart_entry:
            return

        self.current_chart_data = chart_entry
        self._hand_edited.clear()
        self._bar_written.clear()
        self._time_defaulted = False    # WI-1 lifecycle: a loaded chart owns its time
        self._supersede_place()         # WI-4: a load supersedes a pending parse geocode

        # SPEC-IMPORT-002 BUG-2: snapshot the pristine _toml_extra NOW, before an
        # edit-save cycle can shed keys from the source file.
        self._loaded_toml_extra = None
        self._loaded_toml_extra_path = None
        _src_path = chart_entry.get("chtk_path")
        if _src_path and str(_src_path).lower().endswith(".toml"):
            from pathlib import Path as _Path
            if _Path(str(_src_path)).exists():
                try:
                    from core.toml_chart import TOMLChartReader
                    _pristine = TOMLChartReader().read_toml_file(
                        str(_src_path), canonicalize=False)
                    self._loaded_toml_extra = _pristine.get("_toml_extra")
                    self._loaded_toml_extra_path = str(_src_path)
                except Exception as exc:  # noqa: BLE001 - never block chart load
                    logger.warning("Could not snapshot _toml_extra at load (%s): %s",
                                   _src_path, exc)

        birth_data, merged_metadata, raw_dst_flag = self._resolve_load(chart_entry)

        # Populate the one form from the canonical birth_data. The DST-applied
        # toggle shows the RESOLVED flag (_resolve_load turned any CHTK -1 AUTO
        # sentinel into a concrete 0/1/2 via resolve_recipe_dst_flag), so re-save
        # reproduces the same UTC with a concrete flag. The old "Auto from zone"
        # restore was removed with that toggle; raw_dst_flag is unused here now.
        self.ws.populate(self._populate_dict(birth_data))

        self.ws.set_mode("edit")
        self._mode = "edit"
        self._set_dirty(False)

        # Map: basis first (SPEC-MAP-002), then the marker with the KNOWN name so
        # the resolver does not relabel an already-named place.
        self._push_map_time_basis()
        lat = merged_metadata.get("latitude")
        lon = merged_metadata.get("longitude")
        _city = birth_data.get("city", "") or merged_metadata.get("city", "")
        _country = birth_data.get("country", "") or merged_metadata.get("country", "")
        if lat is not None and lon is not None:
            self.ws.map_tab.set_marker(
                float(lat), float(lon), city=_city, country=_country)
            # WI-7: a loaded chart shows its ground elevation too (display-only;
            # never stored, never in collect_data). Absent coords ⇒ blank chip.
            self._request_elevation(lat, lon)
        else:
            self._clear_elevation()
        # WI-6: give the LOADED chart the same routing-note affordance a live map
        # pick gives (today the note is written only by _on_selection_routed, so a
        # freshly loaded chart shows nothing). Static text only — NO reverse
        # geocode: the name is KNOWN and a late geocode must never relabel it
        # (SPEC-MAP-003). A later map pick overwrites this unconditionally.
        if lat is not None and lon is not None:
            if _city or _country:
                self.ws.set_location_note(
                    "Saved location: %s"
                    % ", ".join(x for x in (_city, _country) if x))
            else:
                self.ws.set_location_note(
                    "Saved location: %.4f %s, %.4f %s" % (
                        abs(float(lat)), "N" if float(lat) >= 0 else "S",
                        abs(float(lon)), "E" if float(lon) >= 0 else "W"))
        else:
            self.ws.set_location_note("No saved coordinates")

    def load_from_gui(self):
        """Load the current memory-panel entry (the app's lazy first-open path)."""
        if not self.gui.state.active_chart:
            return
        mp = (getattr(self.gui, "chart_memory_panel", None)
              or getattr(self.gui, "memory_panel", None))
        if mp and 0 <= mp.current_index < len(mp.charts):
            self.load_chart_from_memory(mp.charts[mp.current_index])

    def _resolve_load(self, chart_entry: dict):
        """Recipe → (birth_data, merged_metadata, raw_dst_flag). Re-homed verbatim
        from the old panel; the only change is it RETURNS the dicts instead of
        writing three sub-tabs."""
        recipe = chart_entry.get("recipe")
        if recipe:
            from core.chart_factory import timedec_to_hms, resolve_recipe_dst_flag
            from core.time_utils import local_to_utc, resolve_total_offset, format_offset
            h, m, s = timedec_to_hms(recipe["timedec"])
            birth_metadata = chart_entry.get("birth_metadata", {})
            raw_dst_flag = recipe.get("time_change_flag", 0)
            # td-5w3c.1 guard: sessions saved before the CHTK auto-flag fix can
            # carry the Kala -1 AUTO sentinel; resolve it before it feeds
            # local_to_utc / birth_data.
            _tcf, _tcf_warnings = resolve_recipe_dst_flag(recipe)
            for _w in _tcf_warnings:
                logger.warning("%s (recipe %s)", _w, recipe.get("name", ""))
            _tz_display = recipe.get("timezone", "+00:00")

            _std_offset = None
            if "/" in _tz_display:
                try:
                    _std_offset, _computed_flag = resolve_total_offset(
                        _tz_display, recipe["year"], recipe["month"], recipe["day"],
                        h, m, longitude=recipe.get("lon"))
                except Exception:
                    pass
            if _std_offset is None:
                try:
                    from core.time_utils import _parse_offset
                    _std_h, _std_m = _parse_offset(_tz_display)
                    _std_offset = _std_h + _std_m / 60.0
                except Exception:
                    _raw_uo = recipe.get("utcoffset")
                    _tcf_delta = _tcf if _tcf in (1, 2) else 0
                    _std_offset = (float(_raw_uo) if _raw_uo is not None else 0.0) - _tcf_delta

            _tz_for_utc = _tz_display
            if "/" in _tz_display:
                _tz_for_utc = format_offset(0, int(round(_std_offset * 60)))
            try:
                _utc = local_to_utc(recipe["year"], recipe["month"], recipe["day"],
                                    h, m, s, _tz_for_utc, _tcf)
            except Exception:
                _utc = (recipe["year"], recipe["month"], recipe["day"], h, m, s)

            location = {"city": recipe.get("city", ""),
                        "country": recipe.get("country", ""),
                        "timezone": recipe.get("timezone", "UTC")}
            merged_metadata = {
                "name": recipe.get("name", ""),
                "year": recipe["year"], "month": recipe["month"], "day": recipe["day"],
                "hour": h, "minute": m, "second": s,
                "gender": recipe.get("gender", birth_metadata.get("gender", "")),
                "latitude": recipe["lat"], "longitude": recipe["lon"],
                "dst": _tcf, "location": location,
                "city": recipe.get("city", ""), "country": recipe.get("country", ""),
            }
            self.current_birth_metadata = birth_metadata
            birth_data = {
                "name": recipe.get("name", ""),
                "local_year": recipe["year"], "local_month": recipe["month"],
                "local_day": recipe["day"],
                "local_hour": h, "local_minute": m, "local_second": s,
                "utc_year": _utc[0], "utc_month": _utc[1], "utc_day": _utc[2],
                "utc_hour": _utc[3], "utc_minute": _utc[4], "utc_second": _utc[5],
                # BUG-8 (SPEC-IMPORT-002): recipe['utcoffset'] is the TOTAL offset
                # by construction (make_recipe stores jd.utcoffset). Read it
                # directly; re-deriving TOTAL as _std_offset+_tcf is lossy for
                # fractional-DST zones. Keep the reconstruction only as a
                # defensive fallback for a malformed recipe missing utcoffset.
                "utc_offset_hours": (float(recipe["utcoffset"])
                                     if recipe.get("utcoffset") is not None
                                     else _std_offset + (_tcf or 0)),
                "time_change_flag": _tcf,
                "latitude": recipe["lat"], "longitude": recipe["lon"],
                "city": recipe.get("city", ""), "country": recipe.get("country", ""),
                "gender": recipe.get("gender", birth_metadata.get("gender", "")),
                "iana_timezone": birth_metadata.get("iana_timezone", ""),
                "rodden": recipe.get("rodden"), "tags": recipe.get("tags"),
                "notes": recipe.get("notes"), "julian_day": recipe.get("julian_day"),
                "dst_offset_hours": recipe.get("dst_offset_hours"),
                "source_format": recipe.get("source_format"),
            }
            if _tcf_warnings:
                birth_data["tz_warnings"] = _tcf_warnings
            return birth_data, merged_metadata, raw_dst_flag

        # Legacy fallback for pre-recipe entries. The old panel fed all four
        # sources to info_tab.populate_from_chart; here we _pick across the same
        # sources and SYNTHESIZE a local-authoritative birth_data, because the
        # one form only reads birth_data — returning the (often empty) raw
        # birth_data alone loaded these charts as a blank form.
        planets_data = chart_entry.get("planets_data", {})
        birth_metadata = chart_entry.get("birth_metadata", {})
        self.current_birth_metadata = birth_metadata
        raw_bd = chart_entry.get("birth_data") or {}
        sp = chart_entry.get("source_params")
        sp_bd = dict((sp.get("birth_data") or {}) if sp else {})
        if sp_bd.get("timedec") is not None and sp_bd.get("hour") is None:
            from core.chart_factory import timedec_to_hms
            _h, _m, _s = timedec_to_hms(float(sp_bd["timedec"]))
            sp_bd["hour"], sp_bd["minute"], sp_bd["second"] = _h, _m, _s
        raw_dst_flag = birth_metadata.get("time_change_flag",
                                          birth_metadata.get("dst", 0))

        def _pick(*sources, key, default=None):
            for src in sources:
                v = src.get(key) if isinstance(src, dict) else None
                if v is not None and v != "":
                    return v
            return default

        loc = birth_metadata.get("location", {}) or {}
        city = _pick(loc, birth_metadata, raw_bd, key="city", default=chart_entry.get("city", ""))
        country = _pick(loc, birth_metadata, raw_bd, key="country",
                        default=chart_entry.get("country", ""))
        lat = _pick(birth_metadata, raw_bd, sp_bd, planets_data, key="latitude",
                    default=_pick(raw_bd, sp_bd, key="lat"))
        lon = _pick(birth_metadata, raw_bd, sp_bd, planets_data, key="longitude",
                    default=_pick(raw_bd, sp_bd, key="lon"))
        flag = (birth_metadata.get("dst") if birth_metadata.get("dst") is not None
                else birth_metadata.get("time_change_flag", 0)) or 0
        _tz = _pick(raw_bd, sp_bd, birth_metadata, key="iana_timezone",
                    default=_pick(loc, sp_bd, birth_metadata, planets_data, key="timezone",
                                  default="+00:00"))
        merged_metadata = {
            "name": chart_entry.get("person_name", "") or birth_metadata.get("name", ""),
            "year": _pick(birth_metadata, raw_bd, sp_bd, planets_data, key="year"),
            "month": _pick(birth_metadata, raw_bd, sp_bd, planets_data, key="month"),
            "day": _pick(birth_metadata, raw_bd, sp_bd, planets_data, key="day"),
            "hour": _pick(birth_metadata, raw_bd, sp_bd, planets_data, key="hour"),
            "minute": _pick(birth_metadata, raw_bd, sp_bd, planets_data, key="minute"),
            "second": _pick(birth_metadata, raw_bd, sp_bd, planets_data, key="second", default=0),
            "gender": birth_metadata.get("gender", ""),
            "latitude": lat, "longitude": lon,
            "dst": flag, "city": city, "country": country,
        }
        # Synthesize a local-authoritative birth_data the one form can populate.
        birth_data = dict(raw_bd)
        if "local_year" not in birth_data:
            birth_data.update({
                "name": merged_metadata["name"], "gender": merged_metadata["gender"],
                "local_year": merged_metadata["year"], "local_month": merged_metadata["month"],
                "local_day": merged_metadata["day"],
                "local_hour": merged_metadata["hour"] or 0,
                "local_minute": merged_metadata["minute"] or 0,
                "local_second": merged_metadata["second"] or 0,
                "latitude": lat, "longitude": lon, "city": city, "country": country,
                "time_change_flag": flag,
                "iana_timezone": _tz if "/" in str(_tz) else "",
                "utc_offset_hours": raw_bd.get("utc_offset_hours", 0.0) or 0.0,
            })
        # The "Auto from zone" mode is gone, so a raw CHTK -1 AUTO sentinel must be
        # RESOLVED to a concrete flag on this legacy pre-recipe path too (the recipe
        # path already does, via resolve_recipe_dst_flag). Done here on the FINAL
        # birth_data so it covers BOTH shapes -- a canonical-shaped raw_bd (keeps
        # its own -1) and the synthesized branch (took `flag`, itself possibly -1).
        # Letting -1 reach the form's -1->0 floor would drop the DST hour and
        # re-save a standard-offset summer chart an hour off (GPT-sol finding F).
        # Resolve against the IANA zone, detected from the coordinates when the tz
        # field is a bare offset, exactly as reload would.
        if birth_data.get("time_change_flag") == -1 or flag == -1:
            from core.time_utils import resolve_auto_dst_flag
            _blat = birth_data.get("latitude", lat)
            _blon = birth_data.get("longitude", lon)
            _iana = _tz if "/" in str(_tz) else (birth_data.get("iana_timezone") or None)
            if not _iana and _blat is not None and _blon is not None:
                try:
                    from core.tz_finder import timezone_at
                    _iana = timezone_at(float(_blat), float(_blon))
                except Exception:  # noqa: BLE001 - detection is best-effort
                    _iana = None
            _ry = birth_data.get("local_year") or merged_metadata.get("year")
            _rmo = birth_data.get("local_month") or merged_metadata.get("month")
            _rd = birth_data.get("local_day") or merged_metadata.get("day")
            _rh = birth_data.get("local_hour", merged_metadata.get("hour") or 12)
            _rmi = birth_data.get("local_minute", merged_metadata.get("minute") or 0)
            try:
                _resolved, _fw = resolve_auto_dst_flag(
                    _iana, int(_ry), int(_rmo), int(_rd),
                    int(_rh or 12), int(_rmi or 0),
                    longitude=(float(_blon) if _blon is not None else None))
                for _w in _fw:
                    logger.warning("%s (legacy load %s)", _w,
                                   chart_entry.get("person_name", ""))
            except Exception:  # noqa: BLE001 - never block a legacy load
                logger.exception("legacy load: -1 DST resolution failed")
                _resolved = 0
            birth_data["time_change_flag"] = _resolved
            merged_metadata["dst"] = _resolved
        return birth_data, merged_metadata, raw_dst_flag

    @staticmethod
    def _populate_dict(birth_data: dict) -> dict:
        """Map a canonical ``birth_data`` dict to the view's populate() shape.

        Edit loads are always LOCAL-authoritative (the chart was entered in local
        time); both clocks are supplied so the derived UTC shows correctly.

        The offset field must carry the STANDARD offset, not the total. The form's
        ``timezone`` is the base offset and ``create_from_form_data`` adds the DST
        delta back on save (``utc_offset_hours += dst``). ``utc_offset_hours`` in
        birth_data is already the TOTAL (base + DST), so feeding it verbatim and
        also ticking the DST radio would double-count DST — a summer chart would
        drift +1h (War time +2h) on every no-op save. Subtract the same delta
        create_from_form_data adds: the float ``dst_offset_hours`` when present
        (non-1h DST like Lord Howe 0.5h), else the integer flag gated on (1, 2).
        """
        from core.time_utils import format_offset
        uo = birth_data.get("utc_offset_hours", 0.0) or 0.0
        flag = birth_data.get("time_change_flag", 0)
        dst_float = birth_data.get("dst_offset_hours")
        if dst_float is not None:
            dst_delta = float(dst_float)
        elif flag in (1, 2):
            dst_delta = float(flag)
        else:
            dst_delta = 0.0
        std_offset = float(uo) - dst_delta
        off_str = format_offset(0, int(round(std_offset * 60)))
        return {
            "name": birth_data.get("name", ""),
            "gender": birth_data.get("gender", ""),
            "year": birth_data.get("local_year"),
            "month": birth_data.get("local_month"),
            "day": birth_data.get("local_day"),
            "hour": birth_data.get("local_hour"),
            "minute": birth_data.get("local_minute"),
            "second": birth_data.get("local_second", 0),
            "local_hour": birth_data.get("local_hour"),
            "local_minute": birth_data.get("local_minute"),
            "local_second": birth_data.get("local_second", 0),
            "utc_hour": birth_data.get("utc_hour"),
            "utc_minute": birth_data.get("utc_minute"),
            "utc_second": birth_data.get("utc_second", 0),
            "time_mode": "Local",
            "city": birth_data.get("city", ""),
            "country": birth_data.get("country", ""),
            "latitude": birth_data.get("latitude"),
            "longitude": birth_data.get("longitude"),
            "iana_timezone": birth_data.get("iana_timezone", ""),
            "timezone": off_str,
            "dst": birth_data.get("time_change_flag", 0),
            # Rodden is now an editable form field, so the loaded value MUST
            # reach the form: without it the chip shows unrated, collect_data
            # reports '', and a name-only save silently drops the rating (the
            # form value '' is not None, so _merge_preserved_metadata's guard
            # never restores it). With it, the form is authoritative -- a
            # deliberate clear still saves as unrated. tags/notes stay out (no
            # form field) so the merge keeps preserving them.
            "rodden": birth_data.get("rodden"),
        }

    # =====================================================================
    # CANCEL / CLEAR
    # =====================================================================

    @Slot()
    def _on_cancel_requested(self):
        """Edit-mode Cancel — reload the loaded values (SPEC-EDIT-001 §5.6)."""
        if self._dirty and not self._confirm_leave_dirty():
            return
        if self.current_chart_data:
            self.load_chart_from_memory(self.current_chart_data)
        else:
            self.load_from_gui()

    @Slot()
    def _on_clear_requested(self):
        """Clear form — New only. In Edit it means Cancel (restore loaded)."""
        if self._mode == "edit":
            self._on_cancel_requested()
            return
        self.ws.clear_fields()
        self._hand_edited.clear()
        self._bar_written.clear()
        self._time_defaulted = False    # WI-1 lifecycle: fresh form, no default yet
        self._clear_elevation()         # WI-7: no place ⇒ no elevation
        self._supersede_place()         # WI-4: drop any pending parse geocode
        self.ws.token_bar.clear()
        self._set_dirty(False)

    # =====================================================================
    # SAVE  (re-homed verbatim: SPEC-EDIT-001 ten steps + helpers)
    # =====================================================================

    @Slot()
    def _on_save_requested(self):
        if self._mode != "edit":
            return
        if not self._dirty:
            self._status("No changes to save.")
            return
        self._save()

    def _on_save_open_requested(self):
        """Save & open (Lorris): save, then leave the form and show the chart.

        Always saves — that is the button's contract — which also finalizes and
        displays the chart in the main view; only then do we switch tabs. A
        refused save (validation) keeps the user on the form to fix it."""
        if self._mode != "edit":
            return
        if self._save():
            self._open_current_chart()

    def _open_current_chart(self):
        """Switch the app to the Chart tab (the saved chart is already finalized
        into it by _save). Best-effort: a headless/embedded host may have neither
        the tab widget nor the chart tab, and that must not raise."""
        tabw = getattr(self.gui, "tab_widget", None)
        chart_tab = getattr(self.gui, "chart_tab", None)
        if tabw is not None and chart_tab is not None:
            try:
                tabw.setCurrentWidget(chart_tab)
            except Exception:  # noqa: BLE001 - navigation is best-effort
                logger.exception("Save & open: could not switch to Chart tab")

    def _save(self) -> bool:
        """SPEC-EDIT-001 steps 1-10. Returns True on a successful in-memory save."""
        try:
            # WI-1: a blank hour deleted mid-edit becomes noon, never 00:00,
            # before we collect (same guard as the create road).
            self._ensure_noon_before_collect()
            data = self.ws.collect_data()
            if not data:
                QMessageBox.warning(self.host, "Error", "Could not collect form data")
                return False
            if not self._validate_data(data):
                return False
            if self._time_defaulted:
                self._warn_no_time()    # WI-2: restate at save when we defaulted

            from managers.birth_data_manager import BirthDataManager

            if self.current_chart_data is None:
                # Empty Edit (no chart was loaded into the panel): there is no target
                # to write. The old fallback to gui.current_chart_path wrote the typed
                # form OVER the app's active chart file (Fable BUG-5). Refuse instead.
                self._status("Open a chart to edit before saving.")
                return False

            chtk_path = (self.current_chart_data.get("chtk_path")
                         or getattr(self.gui, "current_chart_path", None))

            # SPEC-IMPORT-001 §6.7 (DST ordering): seed the preserved source float
            # DST before the UTC conversion, but ONLY when the user kept DST ON
            # (flag 1/2) and the form has no explicit float — a toggle-off or an
            # explicit integer change must win over a stale source float.
            if data.get("dst_offset_hours") is None and data.get("dst") in (1, 2):
                _src_bd = self._source_birth_data(chtk_path)
                _src_dst = _src_bd.get("dst_offset_hours")
                if _src_dst is not None:
                    data["dst_offset_hours"] = float(_src_dst)

            birth_data = BirthDataManager.create_from_form_data(data, chtk_path=chtk_path)

            # Verbatim line-13 (SPEC-TZ-001 / td-5w3c): the CHTK -1 AUTO side-key
            # is written raw. UTC was already computed from the resolved 0/1/2
            # flag the radios show; only the STORED flag becomes -1.
            #
            # BUT -1 is a CHTK/Kala-only convention. The Open Astrology Chart .toml
            # format (the DEFAULT) has NO auto sentinel (SPEC open-astrology-chart
            # §4.3: utc_offset = standard base, dst_offset = DST hours): feeding -1
            # to the TOML writer makes _recover_offsets emit a nonsensical
            # utc_offset/dst_offset (3.0 / -1.0 for Paris summer). So bake -1 ONLY
            # for a CHTK target; a TOML target keeps the resolved 0/1/2 flag, which
            # decomposes to a spec-correct base + dst_offset. (Verified by a 3-model
            # blind spec audit, 2026-08-12.)
            # ...and NEVER for a UTC-input chart: it is an absolute instant, so a
            # stored -1 would re-resolve the derived local on load and drift the
            # UTC by an hour at a DST transition (GPT-sol review 2026-08-13).
            _is_toml_target = (str(chtk_path).lower().endswith(".toml")
                               if chtk_path else False)
            if (self.ws.dst_auto_enabled() and not _is_toml_target
                    and self.ws.time_mode != "UTC"):
                birth_data["time_change_flag"] = -1

            self._merge_preserved_metadata(birth_data, chtk_path)

            BirthDataManager.report_tz_warnings(
                BirthDataManager.validate_birth_data(birth_data),
                status_bar=self.gui.statusBar() if self.gui else None,
                context="New & Edit")

            # File write-back FIRST (transactional, Codex C4/C6): the write only
            # needs birth_data, and a failed OR missing target must abort BEFORE we
            # recalculate and mutate any in-memory/app state — otherwise a later
            # Discard restores the half-applied edit instead of the on-disk version,
            # and a vanished file is silently reported as a successful save.
            chtk_write_ok = True
            if chtk_path:
                from pathlib import Path
                p = Path(chtk_path)
                if not p.exists():
                    chtk_write_ok = False
                    QMessageBox.warning(
                        self.host, "File Missing",
                        "The chart file no longer exists on disk; the changes were "
                        "not saved. Re-open the chart and try again.")
                else:
                    writer, method_name = _writer_for(p)
                    file_label = ("TOML" if method_name == "update_toml_birth_data"
                                  else "CHTK")
                    try:
                        getattr(writer, method_name)(str(p), birth_data)
                    except Exception as e:  # noqa: BLE001
                        chtk_write_ok = False
                        QMessageBox.warning(
                            self.host, "File Write Error",
                            f"The {file_label} file could not be saved:\n{e}")
            if not chtk_write_ok:
                # Keep the form DIRTY and report failure. Clearing dirty / emitting
                # chart_saved / returning True made "Save & open" navigate away and
                # the edit look saved while the file still held the old data
                # (GPT-sol/Fable BUG-5).
                self._set_dirty(True)
                return False

            _chart = self._recalculate_chart(data, birth_data)
            if _chart is None:
                QMessageBox.critical(self.host, "Error",
                                     "Chart recalculation failed. Changes not saved.")
                return False

            # Canonical stores (mirrors chart_manager.load_chart).
            from core.time_utils import julday
            _stored_jd = birth_data.get("julian_day")
            if _stored_jd is not None:
                birth_jd = float(_stored_jd)
            else:
                hour_decimal = (birth_data["utc_hour"]
                                + birth_data["utc_minute"] / 60.0
                                + birth_data["utc_second"] / 3600.0)
                birth_jd = julday(birth_data["utc_year"], birth_data["utc_month"],
                                  birth_data["utc_day"], hour_decimal)
            self.gui.birth_jd = birth_jd
            self.gui.birth_lat = birth_data["latitude"]
            self.gui.birth_lon = birth_data["longitude"]
            self.gui.person_name = birth_data.get("name", "")
            self.gui.current_timezone = birth_data.get("iana_timezone", "UTC")
            if chtk_path:
                self.gui.current_chart_path = str(chtk_path)
            self.gui._current_chart_data = None
            self.gui._current_birth_data = birth_data

            if self.current_chart_data:
                self.current_chart_data["birth_data"] = birth_data
                self.current_chart_data["person_name"] = birth_data.get("name", "")

            # Memory panel BEFORE finalize (dasha lazy-rebuild reads the recipe).
            if hasattr(self.gui, "memory_panel"):
                h = birth_data.get("local_hour", 0)
                m = birth_data.get("local_minute", 0)
                s = birth_data.get("local_second", 0)
                self.gui.memory_panel.update_current_chart({
                    "name": birth_data.get("name", ""),
                    "year": birth_data.get("local_year"),
                    "month": birth_data.get("local_month"),
                    "day": birth_data.get("local_day"),
                    "timedec": float(h) + float(m) / 60.0 + float(s) / 3600.0,
                    "utcoffset": birth_data.get("utc_offset_hours", 0.0),
                    "lat": birth_data.get("latitude"),
                    "lon": birth_data.get("longitude"),
                    "city": birth_data.get("city", ""),
                    "country": birth_data.get("country", ""),
                    "timezone": birth_data.get("iana_timezone", "") or data.get("timezone", ""),
                    "julian_day": birth_data.get("julian_day"),
                    "dst_offset_hours": birth_data.get("dst_offset_hours"),
                    "rodden": birth_data.get("rodden"),
                    "tags": birth_data.get("tags"),
                    "notes": birth_data.get("notes"),
                })

            # (File write-back already happened above, before any mutation.)
            self.gui._finalize_chart_load(skip_varga_reset=True)

            self._set_dirty(False)
            if self.host is not None:
                self.host.chart_saved.emit(str(chtk_path) if chtk_path else "")

            self._status("Chart information updated.")
            return True
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self.host, "Error", f"Failed to save: {e}")
            return False

    # =====================================================================
    # CREATE  (§2 item 7 FORM path; §2 item 8 async geocode)
    # =====================================================================

    @Slot()
    def _on_create_requested(self):
        """New-mode Create. Returns True if a chart was created or a create-
        geocode is in flight, False if the create was refused.

        Placement rules (§2 item 8, no silent (0,0)/UTC chart):
          * both coordinate fields explicitly filled -> create now;
          * otherwise a typed city -> geocode it, then create on resolve;
          * neither -> refuse with a status hint. Blank coordinate fields collect
            as 0.0, so a raw-widget emptiness check (not the collected value) is
            what distinguishes "unplaced" from a deliberate 0, and it also catches
            a half-entered coordinate (only latitude typed).
        """
        # WI-1: a blank clock (or a blank hour alone) becomes noon, never 00:00,
        # BEFORE we collect — this also stamps _time_defaulted for the warning.
        self._ensure_noon_before_collect()
        data = self.ws.collect_data()
        lat_raw = ((self.ws.latitude_input.text() or "").strip()
                   if getattr(self.ws, "latitude_input", None) is not None else "")
        lon_raw = ((self.ws.longitude_input.text() or "").strip()
                   if getattr(self.ws, "longitude_input", None) is not None else "")
        both_coords = bool(lat_raw) and bool(lon_raw)
        city = (data.get("city") or "").strip()

        if both_coords:
            return self._create_now(data)
        if city:
            query = ", ".join(x for x in (data.get("city", ""), data.get("country", "")) if x)
            self._status("Looking up %s…" % query)
            worker = self._ensure_geocoder()
            self._create_geo_gen = worker.request_forward(query)
            return True     # in flight; the resolve callback creates
        self._status("Enter a place — type a city, pick it on the map, or type "
                     "both coordinates — before creating.")
        return False

    def _ensure_geocoder(self):
        if self._geocoder is None:
            from core.geocode_service import GeocodeWorker
            self._geocoder = GeocodeWorker(self)
            self._geocoder.resolved.connect(self._on_create_geocode_resolved)
        return self._geocoder

    @Slot(object)
    def _on_create_geocode_resolved(self, result):
        """A create-geocode returned. Ignore stale generations; on success fill
        the place and create; on failure refuse with a status hint (never a
        silent (0,0)/UTC chart)."""
        if self._create_geo_gen is None:
            return
        self._create_geo_gen = None
        if result is None:
            self._status("Could not resolve that place — pick it on the map or "
                         "type coordinates.")
            return
        # Adopt the resolved place, then create from the completed form.
        self.ws.set_coordinates(result.lat, result.lon)
        if getattr(result, "city", ""):
            self.ws.set_city(result.city)
        if getattr(result, "country", ""):
            self.ws.set_country(result.country)
        # Resolve + adopt the TIMEZONE for the geocoded coordinates. The create-
        # geocode result carries no zone (GeocodeResult has no tz), so without this
        # the locked tz fields keep the PREVIOUS place's offset (wrong UTC by hours)
        # or stay blank and validation refuses (GPT-sol/Fable BUG-4).
        iana = None
        try:
            from managers.birth_data_manager import BirthDataManager
            iana = BirthDataManager._detect_timezone(result.lat, result.lon)
        except Exception:  # noqa: BLE001 - never let zone lookup crash the create
            logger.exception("create-geocode: timezone lookup failed")
        if not iana:
            # Coordinates resolved but their zone did not: proceeding would build the
            # chart with the PREVIOUS place's offset (or a silent UTC+0). Refuse and
            # let the user place it on the map, where the zone is resolved (Codex C3).
            self._status("Found the place, but could not determine its timezone — "
                         "pick it on the map to set the zone.")
            return
        self._adopt_timezone(iana)
        self._recompute_derived_utc()
        # WI-1: guard this SECOND create caller too — a blank hour edited while
        # the geocode was in flight would otherwise collect as 00:00 here.
        self._ensure_noon_before_collect()
        self._create_now(self.ws.collect_data())

    def _create_now(self, data: dict) -> bool:
        """The FORM create path (SPEC §2 item 7). NEVER create_chart_from_text.
        Returns True on a successful create, False on refusal/failure."""
        if not self._validate_data(data):
            return False
        try:
            from managers.birth_data_manager import BirthDataManager
            from core.chart_factory import (
                build_chart_from_params, make_recipe, timedec_to_hms,
            )
            from core.time_utils import julday
            from managers.chart_creation_pipeline import persist_birth_data

            bd = BirthDataManager.create_from_form_data(data)
            # The RECIPE carries -1 (auto re-resolves on reselect); the FILE keeps
            # the resolved 0/1/2 flag so persist_birth_data recovers the STANDARD
            # base offset. Baking -1 into bd BEFORE persist made create_chtk store
            # the DST-inclusive total AS the base offset and still set the flag, so
            # the saved CHTK reloaded one hour early (GPT-sol BUG-1). Only .chtk was
            # affected (TOML's negative-dst representation happened to round-trip),
            # but both formats are now clean.
            # A UTC-input chart is an ABSOLUTE instant: the -1 "auto, re-resolve
            # from the zone on load" sentinel must NOT be stored for it. Reload
            # would re-resolve the derived local clock, which at a DST transition
            # is ambiguous, and reconstruct a UTC an hour off (GPT-sol review
            # 2026-08-13). The resolved 0/1/2 flag reload inverts exactly.
            if self.ws.dst_auto_enabled() and self.ws.time_mode != "UTC":
                recipe_flag = -1
            else:
                recipe_flag = bd.get("time_change_flag", 0)
                if recipe_flag == -1:
                    # A UTC form left on Auto can still carry -1; store the
                    # resolved value (0) so reload never re-resolves it.
                    recipe_flag = 0
            BirthDataManager.report_tz_warnings(
                BirthDataManager.validate_birth_data(bd),
                status_bar=self.gui.statusBar() if self.gui else None,
                context="New & Edit")
            # WI-2: restate the missing-time warning at the moment of creation
            # (the canonical pipeline warns at create, not only at parse).
            if self._time_defaulted:
                self._warn_no_time()

            hour_decimal = (bd["utc_hour"] + bd["utc_minute"] / 60.0
                            + bd["utc_second"] / 3600.0)
            jd = julday(bd["utc_year"], bd["utc_month"], bd["utc_day"], hour_decimal)
            mode = self.gui.state.aditya_mode
            chart = build_chart_from_params(
                jd=jd, lat=bd.get("latitude", 0), lon=bd.get("longitude", 0),
                mode=mode, name=bd.get("name", ""),
                utcoffset=bd.get("utc_offset_hours", 0.0),
                ayanamsa=getattr(self.gui, "chart_sidereal_ayanamsa_id", 100),
                hsys=self.gui.state.house_system_code)

            timedec = (bd["local_hour"] + bd["local_minute"] / 60.0
                       + bd["local_second"] / 3600.0)
            recipe = make_recipe(
                name=bd.get("name", ""),
                year=bd["local_year"], month=bd["local_month"], day=bd["local_day"],
                timedec=timedec, utcoffset=bd.get("utc_offset_hours", 0.0),
                timezone=(bd.get("iana_timezone") or data.get("timezone") or "+00:00"),
                lat=bd.get("latitude", 0), lon=bd.get("longitude", 0),
                city=bd.get("city", ""), country=bd.get("country", ""),
                gender=bd.get("gender", "") or "Unknown",
                time_change_flag=recipe_flag,
                house_system=self.gui.state.house_system,
                rodden=bd.get("rodden"), tags=bd.get("tags"), notes=bd.get("notes"),
                julian_day=bd.get("julian_day"),
                dst_offset_hours=bd.get("dst_offset_hours"))

            file_path, _fmt, persist_error = persist_birth_data(
                bd, name=data.get("name", ""), julian_day=jd)
            if persist_error:
                # Persisting the file failed: do NOT register a pathless chart in the
                # memory panel (selecting it would drop the user into an Edit with no
                # file to save back to — a false retry, Codex C5). Keep the form dirty
                # in New mode; fixing the folder + Create again re-persists. Do NOT
                # report success (GPT-sol/Fable BUG-6).
                logger.warning("Create: persistence failed: %s", persist_error)
                try:
                    from ui.sticky_status import report_write_failure
                    report_write_failure(self.host, persist_error, data.get("name", ""))
                except Exception:  # noqa: BLE001
                    pass
                self._set_dirty(True)
                return False

            # Memory-panel registration (create path): add + select drives the
            # chart to active. (_add_to_memory_panel semantics, moved here.)
            mp = getattr(self.gui, "memory_panel", None)
            if mp is not None:
                idx = mp.add_chart(recipe, chtk_path=file_path or None, chart_obj=chart)
                mp.select_chart(idx)

            # Selecting the new chart loads it as the active chart; move into
            # EDIT_CLEAN on it so the user can immediately refine.
            self._set_dirty(False)
            self._status("Chart created.")
            if self.host is not None:
                self.host.chart_saved.emit(str(file_path) if file_path else "")
            # One click, one button (Lorris 2026-08-14): Create already persisted
            # the file AND selected the chart above, so the old flow of
            # Create-then-Save&open re-saved redundantly just to reach the chart.
            # Open it here so New finishes in a single click, exactly as Edit's
            # "Save & open" does. Best-effort: a no-op on a host without tabs.
            self._open_current_chart()
            return True
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self.host, "Error", f"Failed to create chart: {e}")
            return False

    # =====================================================================
    # VALIDATION / METADATA PRESERVATION / RECALC  (re-homed verbatim)
    # =====================================================================

    def _validate_data(self, data: dict) -> bool:
        errors = []
        if not data.get("name", "").strip():
            errors.append("Name is required")
        month = data.get("month", 0)
        day = data.get("day", 0)
        year = data.get("year", 0)
        if not (1 <= month <= 12):
            errors.append("Month must be 1-12")
        if not (1 <= year <= 9999):
            errors.append("Year must be valid")
        if 1 <= month <= 12:
            import calendar
            max_day = calendar.monthrange(year if 1 <= year <= 9999 else 2000, month)[1]
            if not (1 <= day <= max_day):
                errors.append(f"Day must be 1-{max_day} for month {month}")
        elif not (1 <= day <= 31):
            errors.append("Day must be 1-31")
        hour = data.get("hour", 0)
        minute = data.get("minute", 0)
        second = data.get("second", 0)
        if not (0 <= hour <= 23):
            errors.append("Hour must be 0-23")
        if not (0 <= minute <= 59):
            errors.append("Minute must be 0-59")
        if not (0 <= second <= 59):
            errors.append("Second must be 0-59")
        lat = data.get("latitude", 0)
        lon = data.get("longitude", 0)
        if not (-90 <= lat <= 90):
            errors.append("Latitude must be -90 to 90")
        if not (-180 <= lon <= 180):
            errors.append("Longitude must be -180 to 180")
        if data.get("time_mode") != "UTC":
            # SPEC-MAP-004 §4.3 (F-1 refusal): read the RAW offset widget, because
            # collect_data substitutes '+00:00' for an empty field, so a silent-
            # UTC chart could otherwise wear a resolved look.
            raw_tz = ((self.ws.timezone_input.text() or "").strip()
                      if getattr(self.ws, "timezone_input", None) is not None else "")
            if not raw_tz:
                errors.append("Timezone is unresolved for this location. Pick a "
                              "location whose timezone resolves, type the offset, "
                              "or switch to UTC mode.")
            tz = data.get("timezone", "")
            if not tz:
                errors.append("Timezone is required")
            elif not tz.startswith(("+", "-")) and "/" not in tz:
                errors.append("Timezone must be in +HH:MM format or an IANA name")
            elif tz.startswith(("+", "-")):
                # Bound the numeric offset: real UTC offsets run -12:00..+14:00.
                # startswith('+') alone let "+25:00" through and built a chart a
                # day-plus off with no refusal (smoke-test finding 2026-08-14).
                try:
                    from core.time_utils import _parse_offset
                    _h, _m = _parse_offset(tz)
                    if not (-12.0 <= _h + _m / 60.0 <= 14.0):
                        errors.append(
                            "Timezone offset must be between -12:00 and +14:00")
                except (ValueError, TypeError):
                    errors.append("Timezone offset could not be parsed")
        if errors:
            QMessageBox.warning(self.host, "Validation Error", "\n".join(errors))
            return False
        return True

    def _source_birth_data(self, chart_path):
        """Recover the canonical birth_data the active chart loaded from
        (SPEC-IMPORT-001 §6.7). Returns a dict (possibly empty), never None."""
        src = {}
        cd = self.current_chart_data or {}
        stored_bd = cd.get("birth_data")
        if isinstance(stored_bd, dict) and stored_bd:
            src = dict(stored_bd)
        elif cd.get("recipe"):
            try:
                from core.chart_factory import birth_data_from_recipe
                src = dict(birth_data_from_recipe(cd["recipe"]) or {})
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not rebuild birth_data from recipe: %s", exc)

        from pathlib import Path
        if chart_path and Path(str(chart_path)).suffix.lower() == ".toml":
            if (src.get("_toml_extra") is None
                    and self._loaded_toml_extra is not None
                    and self._loaded_toml_extra_path == str(chart_path)):
                src["_toml_extra"] = self._loaded_toml_extra
            if src.get("_toml_extra") is None:
                try:
                    from core.toml_chart import TOMLChartReader
                    reread = TOMLChartReader().read_toml_file(
                        str(chart_path), canonicalize=False)
                    for _k in ("_toml_extra", "rodden", "tags", "notes",
                               "julian_day", "dst_offset_hours"):
                        if src.get(_k) is None and reread.get(_k) is not None:
                            src[_k] = reread[_k]
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Could not re-read .toml source for metadata "
                                   "preservation (%s): %s", chart_path, exc)
        return src

    def _merge_preserved_metadata(self, birth_data: dict, chart_path):
        """Re-supply uneditable metadata onto form-derived birth_data (§6.7)."""
        src = self._source_birth_data(chart_path)
        for key in ("rodden", "tags", "notes", "dst_offset_hours", "_toml_extra"):
            if birth_data.get(key) is None and src.get(key) is not None:
                birth_data[key] = src[key]

        from pathlib import Path
        if chart_path:
            suffix = Path(str(chart_path)).suffix.lower()
            if suffix == ".toml":
                birth_data["source_format"] = "toml"
            elif suffix == ".chtk":
                birth_data["source_format"] = "chtk"
            elif src.get("source_format"):
                birth_data["source_format"] = src["source_format"]
        elif src.get("source_format"):
            birth_data["source_format"] = src["source_format"]

        src_jd = src.get("julian_day")
        if src_jd is not None and self._same_instant(src, birth_data):
            birth_data["julian_day"] = src_jd
        else:
            birth_data["julian_day"] = None

        is_toml = bool(chart_path) and Path(str(chart_path)).suffix.lower() == ".toml"
        if is_toml and birth_data.get("_toml_extra") is None:
            if not chart_path or not Path(str(chart_path)).exists():
                logger.warning("Editing a .toml chart with no readable source file "
                               "(path=%r): unknown TOML keys (_toml_extra) cannot be "
                               "preserved on save.", chart_path)

    @staticmethod
    def _same_instant(src: dict, edited: dict) -> bool:
        """True when ``edited`` has the same local civil time AND total offset."""
        def _local(d):
            if "local_year" in d:
                return (int(d.get("local_year", 0)), int(d.get("local_month", 0)),
                        int(d.get("local_day", 0)), int(d.get("local_hour", 0)),
                        int(d.get("local_minute", 0)), int(d.get("local_second", 0)))
            from core.chart_factory import timedec_to_hms
            td = d.get("timedec")
            if td is None:
                return None
            h, m, s = timedec_to_hms(float(td))
            return (int(d.get("year", 0)), int(d.get("month", 0)),
                    int(d.get("day", 0)), h, m, s)

        def _offset(d):
            o = d.get("utc_offset_hours")
            if o is None:
                o = d.get("utcoffset")
            return None if o is None else round(float(o), 9)

        sl, el = _local(src), _local(edited)
        if sl is None or el is None or sl != el:
            return False
        so, eo = _offset(src), _offset(edited)
        if so is None or eo is None:
            return False
        return so == eo

    def _recalculate_chart(self, data: dict, birth_data: dict = None):
        """Build a Chart from pre-converted birth_data and dispatch it."""
        try:
            from core.chart_factory import build_chart_from_params, make_source_params
            from core.time_utils import julday
        except ImportError as e:
            QMessageBox.critical(self.host, "Import Error",
                                 f"Could not import chart_factory: {e}")
            return None

        self.gui.loading_manager.start("Recalculating chart...")
        try:
            if birth_data is None:
                from managers.birth_data_manager import BirthDataManager
                birth_data = BirthDataManager.create_from_form_data(data)
                BirthDataManager.report_tz_warnings(
                    BirthDataManager.validate_birth_data(birth_data),
                    status_bar=self.gui.statusBar() if self.gui else None,
                    context="New & Edit")

            stored_jd = birth_data.get("julian_day")
            if stored_jd is not None:
                jd = float(stored_jd)
            else:
                hour_decimal = (birth_data["utc_hour"] + birth_data["utc_minute"] / 60.0
                                + birth_data["utc_second"] / 3600.0)
                jd = julday(birth_data["utc_year"], birth_data["utc_month"],
                            birth_data["utc_day"], hour_decimal)
            mode = self.gui.state.aditya_mode
            _chart = build_chart_from_params(
                jd=jd, lat=birth_data.get("latitude", 0),
                lon=birth_data.get("longitude", 0), mode=mode,
                name=birth_data.get("name", ""),
                utcoffset=birth_data.get("utc_offset_hours", 0.0),
                ayanamsa=getattr(self.gui, "chart_sidereal_ayanamsa_id", 100),
                hsys=self.gui.state.house_system_code)
            QApplication.processEvents()

            from state.events import SetActiveChart
            chtk_path = ((self.current_chart_data.get("chtk_path")
                          if self.current_chart_data else None)
                         or getattr(self.gui, "current_chart_path", None))
            self.gui.state.dispatch(SetActiveChart(
                chart=_chart,
                source_params=make_source_params(
                    chtk_path=str(chtk_path) if chtk_path else None,
                    birth_data=birth_data, mode=mode,
                    ayanamsa=self.gui.chart_sidereal_ayanamsa_id,
                    house_system=self.gui.state.house_system,
                    is_human_design=getattr(self.gui, "is_human_design", False))))
            return _chart
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self.host, "Calculation Error",
                                 f"Error recalculating chart: {e}")
            return None
        finally:
            self.gui.loading_manager.finish()

    # =====================================================================
    # MISC
    # =====================================================================

    def _status(self, text: str):
        try:
            self.ws.set_status(text)
        except Exception:  # noqa: BLE001
            pass

    def refresh_theme(self):
        self.ws.refresh_theme()

    def shutdown(self, drain: bool = True):
        if self._geocoder is not None:
            try:
                self._geocoder.cancel()
                if drain:
                    # Drain like the parse/elevation pools below: a create-geocode
                    # in flight at exit, cancelled but not waited on, keeps a
                    # runnable emitting into a torn-down scene (GPT-sol/Fable BUG-7).
                    self._geocoder.wait(6000)
            except Exception:  # noqa: BLE001
                pass
        # WI-4: the parse-bridge geocoder is a SECOND pool — cancel its generation
        # (drops any landing) and drain it, same cancel-then-drain ordering, so a
        # runnable is not still emitting into a torn-down scene at process exit.
        # Stop the debounce UNCONDITIONALLY first (GPT-sol WI-4 finding 4): before
        # the first parse it is armed while the worker is still None, so gating the
        # stop on the worker would let it fire post-teardown and build a worker
        # that touches the gone workspace.
        try:
            self._parse_geo_debounce.stop()
        except Exception:  # noqa: BLE001
            pass
        if getattr(self, "_parse_geocoder", None) is not None:
            try:
                self._parse_geocoder.cancel()
                if drain:
                    self._parse_geocoder.wait(6000)
            except Exception:  # noqa: BLE001
                pass
        # WI-7: cancel the elevation generation FIRST (any landing is then inert),
        # THEN drain — the ordering that does not SIGSEGV (edit_map_subtab:1531).
        if getattr(self, "_elev_worker", None) is not None:
            try:
                self._elev_debounce.stop()
                self._elev_worker.cancel()
                if drain:
                    self._elev_worker.wait(6000)
            except Exception:  # noqa: BLE001
                pass
        try:
            self.ws.shutdown(drain=drain)
        except Exception:  # noqa: BLE001
            logger.exception("workspace shutdown failed")
