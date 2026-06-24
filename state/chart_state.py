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
VALID_VIEWS = frozenset({"south_indian", "north_indian", "wheel"})
VALID_VARGAS = frozenset({1, 2, 3, 4, 7, 9, 10, 1010, 12, 16, 20, 24, 2424, 27, 30, 40, 45, 60})
# SPEC-HSY-001: the 7 human keys the Settings UI can store. SE codes are
# derived only at consumption via get_house_system_code().
VALID_HOUSE_SYSTEMS = frozenset(HOUSE_SYSTEM_CODES)


class ChartState:
    """Layer B engine state container. Pure Python — no Qt dependency."""

    def __init__(self, prefs_store=None):
        self._listeners = []
        self._active_chart = None
        self._source_params = None
        self._current_varga = 1
        self._aditya_mode = "aditya"
        self._house_system = "campanus"  # SPEC-HSY-001 human key (default Campanus)
        self._time_adjust_mode = False
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
    def chart_view_style(self):
        return self._chart_view_style

    # --- Observer (replaces Qt Signal — keeps Layer B platform-agnostic) ---

    def connect(self, fn):
        """Subscribe to state changes. fn(reason: str) called after each mutation."""
        self._listeners.append(fn)

    def disconnect(self, fn):
        self._listeners.remove(fn)

    def _emit(self, reason: str):
        for fn in self._listeners:
            fn(reason)

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

    def _handle_SetChartViewStyle(self, event):
        if event.style not in VALID_VIEWS:
            raise ValueError(
                f"Invalid chart_view_style {event.style!r}; must be one of {sorted(VALID_VIEWS)}"
            )
        if self._chart_view_style == event.style:
            return
        self._chart_view_style = event.style
        self._emit("chart_view_style")
