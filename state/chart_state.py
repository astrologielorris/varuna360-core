"""
Layer B State Container.

Owns the 5 engine state items managed in Phase 3 (from COMM-03 §4-6).
All mutations go through dispatch(event). Emits state_changed signal
after each mutation. Idempotent events are suppressed (COMM-06 §6).

Phase 4 W3: optional PrefsStore injection enables auto-persist of
aditya_mode + chart_view_style. Pre-mortem fix pm-20260503-005 adds
enum validation so invalid values can't silently propagate.

Current: single instance. Future: one per chart tab (WPM-05).
memory.charts and memory.active_id migrate here in Phase 4.
"""
import warnings

from core.house_systems import HOUSE_SYSTEM_CODES, get_house_system_code


VALID_ADITYA_MODES = frozenset({"aditya", "tropical_classic", "sidereal"})
VALID_VIEWS = frozenset({"south_indian", "north_indian", "wheel", "body_graph",
                         "cards_of_truth", "human_design", "nakshatra"})

# SPEC-COT-001 INV-14 — the ONE style -> chart_stack index mapping.
#
# This dict used to be copy-pasted into core_gui_qt._on_chart_display_changed,
# startup_state_manager.VIEW_INDEX and pro/remote_control.set_chart_view. Adding
# the 5th view surfaced why that is dangerous: two of the copies fall back to
# index 0 on an unknown key and one subscripts bare, so a style that is valid in
# VALID_VIEWS but missing from a copy either KeyErrors or silently lands on
# South Indian. Both are failures you only find at runtime. Consume this; never
# re-declare it.
VIEW_STACK_INDEX = {
    "south_indian": 0,
    "wheel": 1,
    "north_indian": 2,
    "body_graph": 3,
    "cards_of_truth": 4,
    # SPEC-HD-001 (WI-6): the Human Design BodyGraph view, chart-stack page 5.
    # NOTE the key is "human_design", NOT "body_graph" (index 3, the astrology
    # BodyAspectDualWidget / -88 HD button). They are different views.
    "human_design": 5,
    # SPEC-NAK-LITE-001: the restricted Core/Lite Nakshatra wheel, chart-stack
    # page 6. APPENDED at the end so indices 0-5 (and every persisted view index
    # / remote select_view mapping) are unshifted; it is not in
    # F2_RING_EXCLUDED_VIEWS, so it joins the F2 cycle automatically.
    "nakshatra": 6,
}
VIEW_BY_STACK_INDEX = {index: style for style, index in VIEW_STACK_INDEX.items()}

# td-iopy (Wave 5): the F2 view-cycle ring, DERIVED from INV-14 so no caller
# hardcodes a literal (0,1,2,3) and a newly-added mapped view joins the ring
# automatically. SPEC-BAR-001 D-23(d): Cards LEFT the F2 ring for its own Alt+K
# button, so the ring is every valid view in stack-index order MINUS the
# documented exclusions. Consume F2_RING_INDICES; never re-declare the tuple.
#
# Codex (td-iopy review) MED-4: a mapped-but-unringed view combined with the
# _last_chart_view_index return-target would leave F2 able to LAND on a view it
# can never leave; deriving the ring from the same map that assigns the index
# closes that — an added view is either in the ring or an explicit exclusion.
F2_RING_EXCLUDED_VIEWS = frozenset({"cards_of_truth", "human_design"})


def compute_f2_ring(view_stack_index=None, excluded=None):
    """Return (ring_views, ring_indices): the views NOT excluded, ordered by
    their stack index, plus the matching index tuple. Pure and parameterized so
    a new mapped view provably joins the ring with no edit to _toggle_wheel_view
    (oracle O4). Defaults to the live VIEW_STACK_INDEX / exclusion set."""
    vsi = VIEW_STACK_INDEX if view_stack_index is None else view_stack_index
    exc = F2_RING_EXCLUDED_VIEWS if excluded is None else excluded
    views = tuple(style for style, _idx in sorted(vsi.items(), key=lambda kv: kv[1])
                  if style not in exc)
    return views, tuple(vsi[v] for v in views)


F2_RING_VIEWS, F2_RING_INDICES = compute_f2_ring()

assert set(VIEW_STACK_INDEX) == set(VALID_VIEWS), \
    "VIEW_STACK_INDEX and VALID_VIEWS must describe the same set of views"
VALID_VARGAS = frozenset({1, 2, 3, 4, 7, 9, 10, 1010, 12, 16, 20, 24, 2424, 27, 30, 40, 45, 60})
# SPEC-HSY-001: the 7 human keys the Settings UI can store. SE codes are
# derived only at consumption via get_house_system_code().
VALID_HOUSE_SYSTEMS = frozenset(HOUSE_SYSTEM_CODES)


class ChartState:
    """Layer B engine state container. Pure Python — no Qt dependency."""

    # td-yymp Block 4 kill-switch. False == pre-batching behaviour byte-for-byte
    # (batching() becomes a pure passthrough; _emit always delivers immediately).
    BATCHING_ENABLED = True

    def __init__(self, prefs_store=None):
        self._listeners = []
        # td-yymp Block 4: listeners that opt into batching (their reason is
        # buffered across a batch and replayed once at drain). Everything not in
        # this set is delivered IMMEDIATELY even inside a batch — structural
        # observers (the western-names clamp mutates a primitive the final repaint
        # reads) and cheap state renders (action bar) must react per-emit.
        self._batchable = set()
        self._batch_depth = 0
        self._batch_buffer = []   # ordered, de-duped reasons pending drain
        # LOW-1: batchable listeners snapshotted at the OUTERMOST batch entry, so
        # the drain replays only to listeners that existed when the batch began.
        self._batch_listeners = frozenset()
        self._active_chart = None
        self._source_params = None
        self._current_varga = 1
        self._aditya_mode = "aditya"
        self._house_system = "campanus"  # SPEC-HSY-001 human key (default Campanus)
        self._time_adjust_mode = False
        self._human_design_mode = False
        self._chart_view_style = "south_indian"
        self._prefs_store = prefs_store

        if self._prefs_store is not None:
            self._load_persisted_prefs()

    # --- Properties (read access) ---

    @property
    def active_chart(self):
        return self._active_chart

    @property
    def current_varga(self):
        return self._current_varga

    @property
    def source_params(self):
        return self._source_params

    @property
    def aditya_mode(self):
        return self._aditya_mode

    @property
    def house_system(self):
        """Human key (e.g. 'campanus', 'placidus') — the storage representation."""
        return self._house_system

    @property
    def house_system_code(self):
        """Swiss Ephemeris code (e.g. 'C', 'P') — transient consumption value."""
        return get_house_system_code(self._house_system)

    @property
    def time_adjust_mode(self):
        return self._time_adjust_mode

    @property
    def human_design_mode(self):
        return self._human_design_mode

    @property
    def chart_view_style(self):
        return self._chart_view_style

    # --- Observer (replaces Qt Signal — keeps Layer B platform-agnostic) ---

    def connect(self, fn, batchable=False):
        """Subscribe to state changes. fn(reason: str) called after each mutation.

        batchable=True (td-yymp Block 4): inside a `with state.batching()` block
        this listener's reasons are buffered and replayed ONCE at drain, instead
        of firing per-emit. Only terminal repaint listeners (the panel
        controllers) opt in; structural/immediate observers keep the default.
        """
        self._listeners.append(fn)
        if batchable:
            self._batchable.add(fn)

    def disconnect(self, fn):
        self._listeners.remove(fn)
        self._batchable.discard(fn)

    def batching(self):
        """Re-entrant context manager: buffer batchable listeners' reasons for the
        span, then replay each unique reason once at the OUTERMOST exit.

        Immediate (non-batchable) listeners still fire per-emit inside the block,
        so a mid-batch processEvents (loading overlay) has nothing batchable
        scheduled to drain — the coalescing survives the pump. The drain runs
        after the block (post loading.finish), and the replayed burst collapses
        through PanelControllerBase's per-pass flag (Block 3) to one refresh.

        try/finally guarantees the drain even if the wrapped body raises — a
        failed recalc must not swallow the repaint.

        A batch must NEVER span a nested event loop (a modal dialog.exec()) — it
        would suppress every controller and hold queued dispatches hostage while
        the dialog sits open (MED-2). Batch only the accepted mutation+recalc.

        LOW-1: the batchable listener set is snapshotted at the OUTERMOST entry;
        the drain replays only to that snapshot, and a listener connected
        mid-batch is delivered to live instead (no stale replay of pre-connect
        reasons). LOW-2: BATCHING_ENABLED is captured PER context-manager instance
        at __enter__ and reused at __exit__, so flipping the kill-switch mid-batch
        can neither strand the buffer (entered enabled → still drains) nor drive
        depth negative (entered disabled → never decrements).
        """
        state = self

        class _Batch:
            def __enter__(_self):
                _self._enabled = ChartState.BATCHING_ENABLED   # LOW-2: capture once
                if _self._enabled:
                    if state._batch_depth == 0:                # outermost
                        state._batch_listeners = frozenset(state._batchable)
                    state._batch_depth += 1
                return _self

            def __exit__(_self, *exc):
                if not _self._enabled:
                    return False
                state._batch_depth -= 1
                if state._batch_depth == 0:
                    reasons = state._batch_buffer
                    state._batch_buffer = []
                    snapshot = state._batch_listeners
                    state._batch_listeners = frozenset()
                    for r in reasons:
                        for fn in list(state._listeners):
                            if fn in snapshot:                 # still connected
                                fn(r)
                return False

        return _Batch()

    def _emit(self, reason: str):
        batching = self.BATCHING_ENABLED and self._batch_depth > 0
        if not batching:
            for fn in list(self._listeners):
                fn(reason)
            return
        # Deliver live to everyone OUTSIDE the entry snapshot — non-batchable
        # observers AND any listener connected after the batch began (LOW-1);
        # buffer the reason once for the snapshot listeners to replay at drain.
        snapshot = self._batch_listeners
        for fn in list(self._listeners):
            if fn not in snapshot:
                fn(reason)
        if snapshot and reason not in self._batch_buffer:
            self._batch_buffer.append(reason)

    # --- Persistence (Phase 4 W3) ---

    def _load_persisted_prefs(self):
        """Restore aditya_mode, chart_view_style, house_system from PrefsStore on startup.

        Invalid persisted values fall back to safe defaults with a warning.
        """
        prefs = self._prefs_store.load()

        loaded_mode = prefs.get("aditya_mode", "aditya")
        # Backward compat: translate old enum values from saved sessions
        if loaded_mode == "zodiac":
            loaded_mode = "aditya"
        elif loaded_mode == "classic":
            loaded_mode = "tropical_classic"
        if loaded_mode not in VALID_ADITYA_MODES:
            warnings.warn(
                f"Invalid persisted aditya_mode {loaded_mode!r} — falling back to 'aditya'"
            )
            loaded_mode = "aditya"
        self._aditya_mode = loaded_mode

        loaded_view = prefs.get("chart_view_style", "south_indian")
        if loaded_view not in VALID_VIEWS:
            warnings.warn(
                f"Invalid persisted chart_view_style {loaded_view!r} — falling back to 'south_indian'"
            )
            loaded_view = "south_indian"
        self._chart_view_style = loaded_view

        # SPEC-HSY-001: the authoritative value comes from settings_manager
        # (zodiac.house_system), applied by core_gui_qt at startup via a
        # SetHouseSystem dispatch. PrefsStore is a defensive fallback so a
        # standalone ChartState still has a valid human key.
        loaded_hsys = prefs.get("house_system", "campanus")
        if loaded_hsys not in VALID_HOUSE_SYSTEMS:
            warnings.warn(
                f"Invalid persisted house_system {loaded_hsys!r} — falling back to 'campanus'"
            )
            loaded_hsys = "campanus"
        self._house_system = loaded_hsys

    # --- Dispatch ---

    def dispatch(self, event):
        """Route a typed event to its handler. Emit state_changed after."""
        handler_name = f'_handle_{type(event).__name__}'
        handler = getattr(self, handler_name, None)
        if handler is None:
            raise ValueError(f"Unknown event: {type(event).__name__}")
        handler(event)

    # --- Event handlers (idempotent guards per COMM-06 §6) ---

    def _handle_SetActiveChart(self, event):
        if event.source_params is not None:
            self._source_params = event.source_params
        if self._active_chart is event.chart:
            return
        self._active_chart = event.chart

        self._emit("active_chart")

    def _handle_SetVarga(self, event):
        if event.varga_number not in VALID_VARGAS:
            raise ValueError(
                f"Invalid varga {event.varga_number!r}; must be one of {sorted(VALID_VARGAS)}"
            )
        if self._current_varga == event.varga_number:
            return
        self._current_varga = event.varga_number

        self._emit("current_varga")

    def _handle_SetZodiacMode(self, event):
        if event.mode not in VALID_ADITYA_MODES:
            raise ValueError(
                f"Invalid aditya_mode {event.mode!r}; must be one of {sorted(VALID_ADITYA_MODES)}"
            )
        if self._aditya_mode == event.mode:
            return
        self._aditya_mode = event.mode
        # Invalidate varga cache: vargas computed under the previous mode would
        # use the wrong libaditya circle (Aditya vs Tropical) and stale signs.
        # Chart-Everywhere Issue 2b: the GUI's mode-toggle handler in
        # core_gui_qt.py rebuilds the Chart from source_params after this event
        # fires. State stays layer-primitive; orchestration lives upstream.

        self._emit("aditya_mode")

    def _handle_SetHouseSystem(self, event):
        if event.house_system not in VALID_HOUSE_SYSTEMS:
            raise ValueError(
                f"Invalid house_system {event.house_system!r}; must be one of {sorted(VALID_HOUSE_SYSTEMS)}"
            )
        if self._house_system == event.house_system:
            return
        self._house_system = event.house_system
        # Like SetZodiacMode: state stays layer-primitive. The GUI's handler
        # rebuilds the active Chart with the new house_system_code after this
        # fires; persistence is owned by settings_manager (zodiac.house_system).
        self._emit("house_system")

    def _handle_SetTimeAdjustMode(self, event):
        if self._time_adjust_mode == event.enabled:
            return
        self._time_adjust_mode = event.enabled
        self._emit("time_adjust_mode")

    def _handle_SetHumanDesignMode(self, event):
        # Idempotent guard (COMM-06 §6): a same-value dispatch must NOT emit.
        # This is what keeps the reset-to-False writes scattered through the
        # new-chart paths inert when HD is already off. The emit fans out to
        # ALL listeners unconditionally (see connect/_emit); it is inert only
        # because every current listener filters by `reason` and no-ops on an
        # unknown one. A FUTURE listener that reacts to every reason without
        # filtering would silently start responding to "human_design_mode".
        if self._human_design_mode == event.enabled:
            return
        self._human_design_mode = event.enabled
        self._emit("human_design_mode")

    def _handle_SetChartViewStyle(self, event):
        if event.style not in VALID_VIEWS:
            raise ValueError(
                f"Invalid chart_view_style {event.style!r}; must be one of {sorted(VALID_VIEWS)}"
            )
        if self._chart_view_style == event.style:
            return
        self._chart_view_style = event.style
        self._emit("chart_view_style")
