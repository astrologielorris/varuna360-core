"""
Programmatic control layer for Varuna360 (SPEC-REM-001 v1.1).

Shared by every edition since SPEC-LMCP-001 D-24 (moved from
``pro/remote_control.py``, which stays the same module object): the local MCP
server's window actions (``apps/window_actions.py``) run through it. The Pro
commands (South Indian Compass reading, CLI parity) are registered by ``pro/remote_control_pro.py``.

Provides AppController: a stateless facade that exposes every user-triggerable
action as a named Python method. External callers (AI agents, scripts, tests)
use controller.execute("command_name", {params}) for text-based dispatch.

Thread-safe: calls from background threads are marshaled to the GUI thread
via a signal-based bridge with BlockingQueuedConnection.
"""
from __future__ import annotations

import functools
import inspect
import os
import threading
from dataclasses import dataclass
from typing import Any, Callable

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtWidgets import QApplication

from core.settings_registry import default as _registry_default
from core.chart_kind import entry_kind, is_transit_kind


# ---------------------------------------------------------------------------
# Command Registry Infrastructure
# ---------------------------------------------------------------------------

@dataclass
class ParamSpec:
    name: str
    type: type
    default: Any = inspect.Parameter.empty


@dataclass
class CommandEntry:
    method: Callable
    params: list
    description: str
    category: str


_REGISTRY: dict[str, CommandEntry] = {}

# verify_parity house-cusp agreement, in degrees. The CLI extractor emits
# cusps rounded to 2 decimals, so half of that quantum is the tightest
# threshold that can distinguish a real divergence from rounding.
_CUSP_PARITY_TOLERANCE_DEG = 0.005 + 1e-9


def _as_ai(fn):
    """``fn`` run as an AI-originated command (SPEC-SET-003 §4.5b, AI setting
    redesign fix round 3): every settings write it makes, on any path, passes
    the one AI write policy (``managers/ai_write_policy``: the saved AI
    toggle, the protected, panel-only and ask-first keys, the user's locks
    including a group's, the classification of the key really written). A
    refused write ends the command, puts back what it had already written
    (nothing is left half written) and becomes its refusal reply. Lite has
    no AI and ships no policy: there the command just runs."""
    @functools.wraps(fn)
    def run(self, *args, **kwargs):
        from core.edition_features import ai_features
        features = ai_features()
        if features is None:
            return fn(self, *args, **kwargs)
        features.write_policy()             # registers the policy
        from managers import ai_write_hook
        if ai_write_hook.active():          # a command run by another: the outer one answers
            return fn(self, *args, **kwargs)
        from managers.setting_live_apply import readopt
        window = getattr(self, "_window", None)
        try:
            with ai_write_hook.ai_writer(origin="remote",
                                         on_undone=lambda keys: readopt(window, keys)):
                return fn(self, *args, **kwargs)
        except ai_write_hook.AIWriteRefused as refused:
            return _refused(refused.reply.get("key"), refused.reply)
    return run


def _language_command_description(prefix: str) -> str:
    """"<prefix> (en/fr/...)": the codes come from the language registry (SPEC-LOC-002)."""
    from core.i18n import languages as _langs
    try:
        return f"{prefix} ({'/'.join(_langs.codes())})"
    except Exception:  # noqa: BLE001  (a broken registry must not break the command table)
        return prefix


def command(name: str, category: str = "", description: str = ""):
    """Register a method as a named command in the global registry. The
    registered (and returned) method runs as an AI-originated command
    (``_as_ai``)."""
    def decorator(fn):
        sig = inspect.signature(fn)
        params = []
        for pname, param in sig.parameters.items():
            if pname == "self":
                continue
            annotation = param.annotation if param.annotation != inspect.Parameter.empty else Any
            params.append(ParamSpec(
                name=pname,
                type=annotation,
                default=param.default,
            ))
        method = _as_ai(fn)
        _REGISTRY[name] = CommandEntry(
            method=method,
            params=params,
            description=description,
            category=category,
        )
        method._command_name = name
        return method
    return decorator


# ---------------------------------------------------------------------------
# Thread Safety Bridge
# ---------------------------------------------------------------------------

class _CommandBridge(QObject):
    """Cross-thread command marshaling via BlockingQueuedConnection."""
    request_execute = Signal(str, dict)

    def __init__(self, controller: "AppController"):
        super().__init__()
        self._controller = controller
        self._result: dict = {}
        self._error: Exception | None = None
        self._lock = threading.Lock()
        self.request_execute.connect(
            self._do_execute,
            Qt.ConnectionType.BlockingQueuedConnection,
        )

    @Slot(str, dict)
    def _do_execute(self, command_name: str, params: dict):
        try:
            entry = _REGISTRY[command_name]
            self._result = entry.method(self._controller, **params)
            self._error = None
        except Exception as e:
            self._result = {}
            self._error = e


# ---------------------------------------------------------------------------
# AppController
# ---------------------------------------------------------------------------

_CHART_DISPLAY_REFRESH_KEYS = None


def _chart_display_refresh_keys():
    """Settings keys whose remote change must fire apply_chart_display_settings, so
    a remote/CLI set is indistinguishable from a Settings Apply click (td-iaqm.2.1).

    Built from the Chart Display page's own allowlists (kept in sync by the pin
    tests) plus two documented exceptions:
      * chart.show_trimsamsha_degrees — a runtime South Indian vector toggle the
        page does NOT host (so it is not in OWNED_CHART_KEYS and Reset must not
        touch it), but its live effect needs the same refresh.
      * chart_display.house_number.font_size — a font key the page writes on
        Apply; Apply fires the refresh for it, so a remote set must too.
    """
    global _CHART_DISPLAY_REFRESH_KEYS
    if _CHART_DISPLAY_REFRESH_KEYS is None:
        # one list with the in-app request service (td-bztjj item 3)
        from managers.setting_live_apply import chart_tail_keys
        _CHART_DISPLAY_REFRESH_KEYS = chart_tail_keys()
    return _CHART_DISPLAY_REFRESH_KEYS


def _commit(sm, key, value):
    """One remote settings write through the request service's
    authoritative transaction (fix round 2, R2-1/R2-2): the saved AI toggle
    (``ai.allow_app_settings_changes``) and the saved and in-memory locks
    read again under the settings-file lock; its callbacks are held back for
    the caller. The reply is the service's (``applied`` or a refusal). Lite
    (no AI, no request service): a plain durable write."""
    from core.edition_features import ai_features
    features = ai_features()
    if features is not None:
        return features.commit_setting(sm, key, value)
    from managers.settings_write import write_or_restore
    ok, error = write_or_restore(sm, key, value)
    return {"status": "applied"} if ok else {"status": "refused",
                                             "reason": "save_failed", "error": error}


def _refused(key, reply):
    """A remote write's refusal (nothing written)."""
    reason = reply.get("reason") or reply.get("status")
    return {"ok": False, "key": key, "reason": reason,
            "error": f"refused ({reason}): {key}"}


def _named_write(key, value):
    """A named remote setter's settings write (``set_house_system`` and the
    other setters that write a setting, fix round 2): the same transaction as
    ``set_setting`` (fresh saved toggle, saved and in-memory locks), then the
    key's change callbacks. None when written, else the refusal reply."""
    from managers.settings_manager import get_settings
    sm = get_settings()
    reply = _commit(sm, key, value)
    if reply.get("status") != "applied":
        return _refused(key, reply)
    sm._notify_change(key, sm.get(key))
    return None


def _gate(*keys):
    """An early answer for a remote setter that drives one of the app's own
    controls (which then saves its setting), so the control is not touched
    at all when its write would be refused: the one AI write policy
    (``ai_write_policy.refusal``) for each of ``keys``. None = go on, else
    the refusal reply; nothing is changed either way. Correctness does not
    depend on it: the write itself passes the same policy (``_as_ai``)."""
    from managers.settings_manager import get_settings
    from core.edition_features import ai_features
    features = ai_features()
    if features is None:                    # Lite: no AI write policy
        return None
    ai_write_policy = features.write_policy()
    sm = get_settings()
    for key in keys:
        refused = ai_write_policy.refusal(sm, key)
        if refused is not None:
            return _refused(refused.get("key", key), refused)
    return None


class AppController:
    """Stateless programmatic facade for Varuna360.

    Holds no state of its own. All state lives in ChartState,
    SettingsManager, or SessionManager. Safe to construct/discard freely.
    """

    def __init__(self, window):
        self._window = window
        self._bridge = _CommandBridge(self)

    def _is_gui_thread(self) -> bool:
        app = QApplication.instance()
        if app is None:
            return True
        return QThread.currentThread() == app.thread()

    @staticmethod
    def _chart_name(chart) -> str | None:
        """Extract person name from a libaditya Chart object."""
        if chart is None:
            return None
        ctx = getattr(chart, "context", None)
        if ctx and hasattr(ctx, "name"):
            return ctx.name
        return getattr(chart, "name", None)

    def _get_zodiac_section(self):
        """Find the _ZodiacSection widget from the Settings tab.

        Returns the live widget so commands can interact with its combo
        boxes and Apply button, testing the same GUI path as the user.
        """
        tab = getattr(self._window, "settings_tab", None)
        if tab is None:
            return None
        if hasattr(tab, "zodiac_section"):
            return tab.zodiac_section
        return None

    def _get_index_cache(self):
        """Return the live Find Chart panel cache when available.

        SPEC-REM §4.6: reuse the GUI's cache so in-memory rebuilds and
        scan progress are shared. Falls back to a fresh disk-backed
        ChartIndexCache only when the panel doesn't exist or hasn't
        finished its lazy init.
        """
        panel = getattr(self._window, "find_chart_panel", None)
        cache = getattr(panel, "cache", None) if panel is not None else None
        if cache is not None:
            return cache
        from cache.chart_index_cache import ChartIndexCache
        return ChartIndexCache()

    def execute(self, command_name: str, params: dict | None = None) -> dict:
        """Dispatch a command by name. Thread-safe."""
        entry = _REGISTRY.get(command_name)
        if entry is None:
            raise KeyError(f"Unknown command: {command_name!r}")
        params = params or {}

        if not self._is_gui_thread():
            with self._bridge._lock:
                self._bridge.request_execute.emit(command_name, params)
                if self._bridge._error is not None:
                    raise self._bridge._error
                return self._bridge._result
        else:
            return entry.method(self, **params)

    # ===================================================================
    # 5.1 Chart Loading
    # ===================================================================

    @command("load_chart", category="chart",
             description="Load a chart from a CHTK file")
    def load_chart(self, path: str) -> dict:
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Chart file not found: {path!r}")
        self._window.chart_manager.load_chart(path)
        chart = self._window.state.active_chart
        name = self._chart_name(chart) or os.path.basename(path)
        planet_count = 0
        if chart:
            try:
                planet_count = len(chart.rashi().planets())
            except Exception:
                pass
        return {"ok": True, "name": name, "planets": planet_count}

    @command("load_now_chart", category="chart",
             description="Load a chart for the current moment")
    def load_now_chart(self) -> dict:
        self._window._load_now_chart()
        return {"ok": True, "name": "Now Chart"}

    @command("reload_chart", category="chart",
             description="Reload the current chart")
    def reload_chart(self) -> dict:
        if self._window.state.active_chart is None:
            return {"ok": False, "reason": "no chart loaded"}
        self._window.chart_manager.reload_current()
        return {"ok": True}

    @command("close_chart", category="chart",
             description="Close the current chart")
    def close_chart(self) -> dict:
        self._window.chart_manager.close_current_chart()
        return {"ok": True}

    # ===================================================================
    # 5.2 Chart View
    # ===================================================================

    @command("set_chart_view", category="view",
             description="Set chart view style "
                         "(south_indian/north_indian/wheel/body_graph/cards_of_truth/human_design/nakshatra)")
    def set_chart_view(self, style: str) -> dict:
        from state.chart_state import VALID_VIEWS, VIEW_STACK_INDEX
        if style not in VALID_VIEWS:
            raise ValueError(
                f"Invalid view style {style!r}; must be one of {sorted(VALID_VIEWS)}")
        refused = _gate("chart.view_type")
        if refused is not None:
            return refused
        # SPEC-COT-001 INV-14: this used to be a private dict subscripted bare,
        # so a style that was valid but missing from the copy raised KeyError
        # here — which is exactly what happened when the 5th view landed. The
        # shared map is asserted equal to VALID_VIEWS at import.
        view_index = VIEW_STACK_INDEX[style]
        self._window._switch_to_chart_index(view_index)
        return {"ok": True, "view": style}

    @command("cot_family", category="view",
             description="Set the Cards of Truth timing family "
                         "(progression/quadration) (SPEC-COT-007 WI-12)")
    def cot_family(self, family: str) -> dict:
        """Switch the Cards of Truth view to a named timing family.

        WI-12 (C-4). The keyboard ``F`` toggles; this NAMES the target, so an
        automation script lands on a known family rather than on "the other one"
        from an unknown starting state.

        Pre-validated before it delegates, because the recorded failure mode of
        this layer is the SILENT NO-OP (the ``select_chart`` trap): ``set_family``
        rebuilds, and rebuilding a view with no spread is a no-op that would
        report success while nothing changed on screen. So a missing view or an
        empty view returns ``ok: False`` with a reason, never a false green.
        """
        from state.chart_state import VIEW_STACK_INDEX
        from apps.widgets.cards_of_truth_view import FAMILY_ORDER

        if family not in FAMILY_ORDER:
            raise ValueError(
                f"Invalid family {family!r}; must be one of {sorted(FAMILY_ORDER)}")

        view = getattr(self._window, "cards_of_truth_view", None)
        if view is None:
            return {"ok": False, "error": "the Cards of Truth view is not available"}
        if getattr(view, "_data", None) is None:
            return {"ok": False,
                    "error": "no chart is loaded on the Cards of Truth view"}

        # Bring it to the front so the operator sees the switch, THEN delegate.
        self._window._switch_to_chart_index(VIEW_STACK_INDEX["cards_of_truth"])
        changed = view.set_family(family)
        return {"ok": True, "family": family, "changed": bool(changed)}

    @command("set_aspect_panel", category="view",
             description="Show/hide the Body Graph rashi aspect panel (SPEC-BODY-002)")
    def set_aspect_panel(self, visible: bool) -> dict:
        # Only meaningful on the Body Graph view (chart_stack index 3); switch there.
        self._window._switch_to_chart_index(3)
        widget = self._window.chart_stack.currentWidget()
        if hasattr(widget, "set_aspect_panel_visible"):
            widget.set_aspect_panel_visible(bool(visible))
            return {"ok": True, "aspect_panel": bool(visible)}
        return {"ok": False, "error": "aspect panel unavailable on current view"}

    @command("set_rashi_aspect_system", category="view",
             description="Set Body Graph rashi aspect system (quadrant/element/conventional)")
    def set_rashi_aspect_system(self, system: str) -> dict:
        valid = ("quadrant", "element", "conventional")
        if system not in valid:
            raise ValueError(f"Invalid system {system!r}; must be one of {valid}")
        from managers.settings_manager import get_settings
        from managers.live_frame_manager import publication_batch
        # One completed live frame for the write and its tail, as Apply (W5-fix2);
        # a failing write still runs the tail (reconcile, W5-fix3 P2).
        with publication_batch(reconcile=self._window.apply_chart_display_settings,
                               owns=_chart_display_refresh_keys()):
            refused = _named_write("chart.rashi_aspect_system", system)
            if refused is not None:
                return refused
            # chart.rashi_aspect_system is a Chart-Display-owned key; refresh live
            # via the same shared tail as Apply and set_setting (td-iaqm.2.1).
            self._window.apply_chart_display_settings()
        return {"ok": True, "rashi_aspect_system": system}

    @command("switch_varga", category="view",
             description="Switch divisional chart by number")
    def switch_varga(self, number: int) -> dict:
        from state.chart_state import VALID_VARGAS
        if number not in VALID_VARGAS:
            raise ValueError(
                f"Invalid varga {number!r}; must be one of {sorted(VALID_VARGAS)}")
        self._window._switch_varga(number)
        # td-m6xyo: the varga style may draw another code (10 + Reversed = 1010)
        drawn = getattr(getattr(self._window, "state", None), "current_varga", number)
        return {"ok": True, "varga": drawn,
                "in_center": bool(getattr(self._window, "varga_in_center", False))}

    @command("set_varga_in_center", category="view",
             description="Draw the divisional chart in the center box, "
                         "keeping D-1 in the main chart (SPEC-VGC-001)")
    def set_varga_in_center(self, enabled: bool) -> dict:
        """SPEC-VGC-001 D-9.

        Without this, automation could only reach the mode by poking
        `window.varga_center_button` in-process, and `switch_varga` would
        report D-10 for a chart whose main grid is visibly D-1.
        """
        refused = _gate("display.varga_in_center")
        if refused is not None:
            return refused
        window = self._window
        btn = getattr(window, "varga_center_button", None)
        if btn is not None:
            # Go through the button so its checked state, the flag and the
            # persisted setting can never disagree.
            btn.setChecked(bool(enabled))
        else:
            window._toggle_varga_in_center(bool(enabled))
        return {"ok": True, **self._read_varga_state()}

    def _read_varga_state(self) -> dict:
        """Selected / main chart / second surface, as separate facts.

        One `varga` field is a lie while the mode is on: the app would
        report D-10 for a main chart showing D-1. Consumers that only know
        the old key still get `varga`, unchanged in meaning.

        SPEC-VGO-001 added a SECOND kind of second surface — the wheel and
        North Indian rings — so which one is in play now depends on the
        visible view. `varga_in_center_box` keeps its exact old meaning
        (non-null only for the South Indian center box) rather than being
        widened to mean "wherever the varga went", which would silently
        change what every existing caller is told.
        """
        window = self._window
        selected = window.state.current_varga
        in_center = bool(getattr(window, "varga_in_center", False))
        suspended = None
        reader = getattr(window, "_center_varga_suspended_by", None)
        if reader is not None:
            try:
                suspended = reader()
            except Exception:
                suspended = None

        # A window that predates SPEC-VGO-001, or one whose view stack is
        # not built yet, must not be reported as "the varga is nowhere".
        # Anything unrecognised falls back to the historical assumption,
        # which is what every caller before this change was told.
        surface = "center_box"
        surface_reader = getattr(window, "_varga_second_surface", None)
        if surface_reader is not None:
            try:
                surface = surface_reader()
            except Exception:
                surface = "center_box"
        if surface not in ("center_box", "outer_ring", None):
            surface = "center_box"

        drawn_in_second = (in_center and selected != 1 and suspended is None
                           and surface is not None)
        in_center_box = drawn_in_second and surface == "center_box"
        in_outer_ring = drawn_in_second and surface == "outer_ring"
        return {
            "varga": selected,
            "varga_selected": selected,
            "varga_in_outer_chart": 1 if drawn_in_second else selected,
            "varga_in_center_box": selected if in_center_box else None,
            "varga_in_outer_ring": selected if in_outer_ring else None,
            "varga_second_surface": surface,
            "varga_in_center_mode": in_center,
            "varga_center_suspended_by": suspended,
        }

    # ===================================================================
    # 5.3 Zodiac & Calculation
    # ===================================================================

    def _read_zodiac_state(self) -> dict:
        """Read actual runtime zodiac state for command verification."""
        return {
            "actual_mode": self._window.state.aditya_mode,
            "actual_western_names": getattr(self._window, "use_western_names", False),
            "status": self._window.statusBar().currentMessage(),
        }

    @command("set_zodiac_mode", category="zodiac",
             description="Set zodiac mode (aditya/tropical_classic/sidereal)")
    def set_zodiac_mode(self, mode: str) -> dict:
        from state.chart_state import VALID_ADITYA_MODES
        if mode not in VALID_ADITYA_MODES:
            raise ValueError(
                f"Invalid zodiac mode {mode!r}; must be one of {sorted(VALID_ADITYA_MODES)}")
        from managers.settings_manager import get_settings
        # both keys checked first, so a lock on the second never leaves the
        # first written alone; then each through the transaction
        refused = (_gate("zodiac.mode", "zodiac.use_western_names")
                   or _named_write("zodiac.mode", mode)
                   or _named_write("zodiac.use_western_names", mode != "aditya"))
        if refused is not None:
            return refused
        ok = True
        self._window.zodiac_settings.apply_settings()
        return {"ok": ok, "mode": mode, **self._read_zodiac_state()}

    @command("set_ayanamsa", category="zodiac",
             description="Set ayanamsa by any AYANAMSA_OPTIONS ID (0-46, 98, 100, 255 custom, 999)")
    def set_ayanamsa(self, ayanamsa_id: int) -> dict:
        # SPEC-KUTA-AYA-001 8a: accept exactly the AYANAMSA_OPTIONS ID set (incl.
        # Vedanga 100, Dhruva 98, Tropical 999), not just 0-46. ID 99 is internal-only
        # (not in AYANAMSA_OPTIONS) and stays rejected. Strict int: bool/float would
        # pass set membership (True == 1, 1.0 == 1) and persist a non-int that
        # downstream isinstance(value, int) syncs then refuse.
        from core.ayanamsa_data import AYANAMSA_OPTIONS, get_ayanamsa_name
        if isinstance(ayanamsa_id, bool) or not isinstance(ayanamsa_id, int) \
                or ayanamsa_id not in {aid for aid, *_ in AYANAMSA_OPTIONS}:
            raise ValueError(f"Invalid ayanamsa_id {ayanamsa_id!r}; "
                             f"must be an int from the AYANAMSA_OPTIONS IDs")
        from managers.settings_manager import get_settings
        refused = _named_write("zodiac.ayanamsa_id", ayanamsa_id)
        if refused is not None:
            return refused
        ok = True
        self._window.zodiac_settings.apply_settings()
        return {"ok": ok, "ayanamsa_id": ayanamsa_id,
                "name": get_ayanamsa_name(ayanamsa_id),
                "status": self._window.statusBar().currentMessage()}

    @command("set_house_system", category="zodiac",
             description="Set house system (Swiss Ephemeris code letter)")
    def set_house_system(self, system: str) -> dict:
        from core.house_systems import HOUSE_SYSTEM_CODES
        from managers.settings_manager import get_settings
        inverse = {code: name for name, code in HOUSE_SYSTEM_CODES.items()}
        system = inverse.get(system, system)
        if system not in HOUSE_SYSTEM_CODES:
            raise ValueError(f"Unknown house system {system!r}")
        refused = _named_write("zodiac.house_system", system)
        if refused is not None:
            return refused
        ok = True
        self._window.zodiac_settings.apply_settings()
        return {"ok": ok, "system": system}

    @command("set_western_names", category="zodiac",
             description="Toggle western sign names on/off")
    def set_western_names(self, enabled: bool) -> dict:
        from managers.settings_manager import get_settings
        # SPEC-MODE-001 (path #3): the alternative label set is unreachable in
        # Beginner. Reject rather than silently writing zodiac.use_western_names,
        # so a caller gets clear feedback instead of a no-op.
        if get_settings().get("ui.experience_level", "beginner") != "advanced":
            return {
                "ok": False,
                "error": "set_western_names is gated in Beginner mode; set "
                         "ui.experience_level to 'advanced' first",
                "experience_level": "beginner",
            }
        refused = _named_write("zodiac.use_western_names", enabled)
        if refused is not None:
            return refused
        ok = True
        self._window.zodiac_settings.apply_settings()
        return {"ok": ok, "western_names": enabled, **self._read_zodiac_state()}

    @command("set_sign_language", category="zodiac",
             description=_language_command_description("Set sign display language"))
    def set_sign_language(self, lang: str) -> dict:
        # SPEC-LOC-002 §3.5: any language of the registry (i18n/languages.json)
        from core.i18n import languages as _langs
        valid = _langs.codes()
        if lang not in valid:
            raise ValueError(f"Invalid language {lang!r}; must be one of {list(valid)}")
        refused = _gate("zodiac.sign_language")
        if refused is not None:
            return refused
        self._window._set_sign_language(lang)
        return {"ok": True, "language": lang}

    @command("set_language", category="zodiac",
             description=_language_command_description(
                 "Set the app language (alias of set_sign_language)"))
    def set_language(self, lang: str) -> dict:
        return self.set_sign_language(lang)

    @command("list_languages", category="zodiac",
             description="List the app languages (code, endonym, English name, status)")
    def list_languages(self) -> dict:
        from core.i18n import languages as _langs
        current = getattr(self._window, "sign_language", None)
        return {"languages": [
            {"code": lang.code, "endonym": lang.endonym, "english_name": lang.english_name,
             "status": lang.status}
            for lang in _langs.user_languages()],
            "current": current if isinstance(current, str) else None}

    # ===================================================================
    # 5.4 Display Toggles
    # ===================================================================

    @command("set_outer_planets", category="display",
             description="Show/hide outer planets (Uranus, Neptune, Pluto)")
    def set_outer_planets(self, visible: bool) -> dict:
        refused = _gate("chart.show_outer_planets")
        if refused is not None:
            return refused
        action = getattr(self._window, "outer_planets_action", None)
        if action is not None:
            if action.isChecked() != visible:
                action.trigger()
        return {"ok": True}

    @command("set_retinue_rings", category="display",
             description="Show/hide retinue rings around planets")
    def set_retinue_rings(self, visible: bool) -> dict:
        refused = _gate("chart.show_retinue_rings")
        if refused is not None:
            return refused
        self._window._toggle_retinue_rings(visible)
        return {"ok": True}

    @command("set_element_pies", category="display",
             description="Show/hide element balance pie charts")
    def set_element_pies(self, visible: bool) -> dict:
        refused = _gate("chart.show_element_pies")
        if refused is not None:
            return refused
        self._window._toggle_pie_charts(visible)
        return {"ok": True}

    @command("set_cusp_glow", category="display",
             description="Set cusp glow mode (0=off, 1=angles, 2=all)")
    def set_cusp_glow(self, mode: int) -> dict:
        if mode not in (0, 1, 2):
            raise ValueError(f"Invalid cusp glow mode {mode!r}; must be 0, 1, or 2")
        from managers.settings_manager import get_settings
        refused = _named_write("chart.cusp_glow_mode", mode)
        if refused is not None:
            return refused
        chart_view = getattr(self._window, "chart_view", None)
        if chart_view and hasattr(chart_view, "set_cusp_glow_mode"):
            chart_view.set_cusp_glow_mode(mode)
        return {"ok": True, "mode": mode}

    @command("set_tropical_rim", category="display",
             description="Show/hide tropical rim overlay on wheel chart")
    def set_tropical_rim(self, visible: bool) -> dict:
        refused = _gate("chart.show_tropical_rim")
        if refused is not None:
            return refused
        current = getattr(self._window, "show_tropical_rim", False)
        if current != visible:
            self._window._toggle_dual_rim()
        return {"ok": True}

    @command("set_transit_rim", category="display",
             description="Show/hide transit rim on wheel chart")
    def set_transit_rim(self, visible: bool) -> dict:
        mgr = getattr(self._window, 'transit_overlay_manager', None)
        current = mgr.transit_enabled if mgr else False
        if current != visible:
            self._window._toggle_transit_rim()
        return {"ok": True}

    @command("overlay_chart", category="display",
             description="Overlay a chart on the active chart via the transit rim "
                         "(SPEC-TRN-006). Pass exactly one of memory_id / file_path.")
    def overlay_chart(self, memory_id: str = "", file_path: str = "") -> dict:
        mgr = getattr(self._window, 'chart_overlay_manager', None)
        if mgr is None:
            raise RuntimeError("chart_overlay_manager unavailable")
        if bool(memory_id) == bool(file_path):
            raise ValueError("pass exactly one of memory_id or file_path")
        if memory_id:
            ok = mgr.overlay_from_memory_id(memory_id)
        else:
            ok = mgr.overlay_from_file(file_path)
        tmgr = self._window.transit_overlay_manager
        return {"ok": bool(ok), "transit_mode": tmgr.transit_mode,
                "overlay_label": tmgr.overlay_label,
                "transit_enabled": tmgr.transit_enabled}

    @command("clear_overlay", category="display",
             description="Clear the overlay chart and turn the rim off (SPEC-TRN-006)")
    def clear_overlay(self) -> dict:
        mgr = getattr(self._window, 'chart_overlay_manager', None)
        if mgr is None:
            raise RuntimeError("chart_overlay_manager unavailable")
        refused = _gate("chart.show_transit_overlay")   # before the overlay changes
        if refused is not None:
            return refused
        mgr.clear()
        return {"ok": True, "transit_mode": self._window.transit_overlay_manager.transit_mode}

    @command("back_to_live_sky", category="display",
             description="Clear the overlay but keep the transit rim on live sky (SPEC-TRN-006)")
    def back_to_live_sky(self) -> dict:
        mgr = getattr(self._window, 'chart_overlay_manager', None)
        if mgr is None:
            raise RuntimeError("chart_overlay_manager unavailable")
        refused = _gate("chart.show_transit_overlay")   # before the overlay changes
        if refused is not None:
            return refused
        mgr.back_to_live_sky()
        return {"ok": True, "transit_mode": self._window.transit_overlay_manager.transit_mode}

    @command("set_human_design", category="display",
             description="Toggle Human Design overlay mode")
    def set_human_design(self, enabled: bool) -> dict:
        refused = _gate("zodiac.human_design")
        if refused is not None:
            return refused
        current = getattr(self._window, "is_human_design", False)
        if current != enabled:
            self._window._toggle_human_design()
        return {"ok": True}

    @command("set_time_adjust", category="display",
             description="Toggle birth time adjustment/rectification mode")
    def set_time_adjust(self, enabled: bool) -> dict:
        current = self._window.state.time_adjust_mode
        if current != enabled:
            self._window._toggle_time_adjust()
        return {"ok": True}

    @command("toggle_side_drawer", category="display",
             description="Toggle left or right side drawer panel")
    def toggle_side_drawer(self, side: str) -> dict:
        if side not in ("left", "right"):
            raise ValueError(f"Invalid side {side!r}; must be 'left' or 'right'")
        self._window._toggle_side_drawer(side)
        attr = f"{side}_drawer_visible"
        visible = getattr(self._window, attr, None)
        if visible is None:
            drawer = getattr(self._window, f"{side}_drawer", None)
            visible = drawer.isVisible() if drawer else True
        return {"ok": True, "visible": visible}

    @command("get_chart_layout", category="display",
             description="Chart tab layout: right dasha presentation, right drawer, info panel folds")
    def get_chart_layout(self) -> dict:
        return {"ok": True, **self._window.chart_layout.layout_state()}

    @command("set_chart_layout", category="display",
             description="Set the right dasha position (full/rail/bottom) and/or info panel state. "
                         "Transient: never written to settings (SPEC-LAYOUT-001 D5, INV-17)")
    def set_chart_layout(self, dasha_right: str = None, panels: dict = None) -> dict:
        mgr = self._window.chart_layout
        if dasha_right is not None:
            if dasha_right != "bottom" and mgr.two_chart():
                # SPEC-DUAL-001 INV-13: the dasha stays on the shelf while paired.
                return {"ok": False, "reason": "two-chart mode: the right dasha stays "
                                              "on the bottom shelf", **mgr.layout_state()}
            mgr.set_dasha_position(dasha_right, persist=False)
        if panels is not None:
            mgr.info_stack().apply_layout_state(panels, persist=False)
        return {"ok": True, **mgr.layout_state()}

    # SPEC-DUAL-001 §4.12: two-chart mode, delegating to the Core manager.
    # Every reply is the manager's real outcome; all of it is transient (INV-5).
    def _pair_reply(self, outcome) -> dict:
        ok, reason = outcome
        reply = {"ok": bool(ok), **self._window.chart_pair.state()}
        if not ok:
            reply["reason"] = reason
        return reply

    @command("get_dual_chart", category="display",
             description="Two-chart mode state: mode, chart B, remembered B, drawer, fullscreen")
    def get_dual_chart(self) -> dict:
        return {"ok": True, **self._window.chart_pair.state()}

    @command("set_dual_chart", category="display",
             description="Turn two-chart mode on or off (transient, SPEC-DUAL-001)")
    def set_dual_chart(self, enabled: bool) -> dict:
        return self._pair_reply(self._window.chart_pair.set_two(bool(enabled)))

    @command("set_chart_b", category="display",
             description="Set chart B from exactly one of memory_id, file_path or sky_now "
                         "(two-chart mode only)")
    def set_chart_b(self, memory_id: str = "", file_path: str = "",
                    sky_now: bool = False) -> dict:
        given = [bool(memory_id), bool(file_path), bool(sky_now)]
        if sum(given) != 1:
            return {"ok": False, "reason": "give exactly one of memory_id, file_path, sky_now"}
        pair = self._window.chart_pair
        if memory_id:
            return self._pair_reply(pair.set_b_from_memory(memory_id))
        if file_path:
            return self._pair_reply(pair.set_b_from_file(file_path))
        return self._pair_reply(pair.set_b_sky_now())

    @command("swap_charts", category="display",
             description="Swap chart A and chart B (two-chart mode with B filled)")
    def swap_charts(self) -> dict:
        return self._pair_reply(self._window.chart_pair.swap())

    @command("forget_chart_b", category="display",
             description="Forget chart B and go back to one chart")
    def forget_chart_b(self) -> dict:
        return self._pair_reply(self._window.chart_pair.forget_b())

    # ===================================================================
    # 5.5 Dasha Navigation
    # ===================================================================

    @command("set_dasha_type", category="dasha",
             description="Set a dasha panel's mode (vimshottari, nisarga, zr); "
                         "side 'right' (default) or 'left'")
    def set_dasha_type(self, panel: str, side: str = "right") -> dict:
        # SPEC-DSH-004: `panel` keeps its wire meaning (the MODE: existing
        # clients send {"panel": "zr"}); `side` picks the panel, both sides offer
        # every registry mode. Drive the reshaper directly (deterministic).
        from managers.dasha.modes import VALID_MODES
        if panel not in VALID_MODES:
            raise ValueError(
                f"Invalid dasha panel {panel!r}; must be one of {list(VALID_MODES)}")
        if side not in ("left", "right"):
            raise ValueError(f"Invalid side {side!r}; must be 'left' or 'right'")
        refused = _gate(f"dasha.{side}.mode")
        if refused is not None:
            return refused
        dm = self._window.dasha_manager
        if dm.mode(side) != panel:
            dm.configure_side(side, panel)
        # Persist so the choice survives a restart and get_state's stored
        # dasha.<side>.mode agrees with the runtime panel (idempotent).
        try:
            from managers.settings_manager import get_settings
            get_settings().persist_runtime_change(f"dasha.{side}.mode", panel)
        except Exception:
            pass
        return {"ok": True, "type": panel, "side": side}

    def _set_side_level(self, side, level):
        """Mode-routed level change on `side`; the max level is the mode's
        (SPEC-DSH-004 registry: Vimshottari/Nisarga 5, ZR 4). Reports the
        manager's ACTUAL resulting level (ZR stops where no period runs)."""
        from managers.dasha.modes import mode_spec
        dm = self._window.dasha_manager
        spec = mode_spec(dm.mode(side))
        if not (1 <= level <= spec.levels):
            raise ValueError(
                f"Invalid level {level!r}; {spec.label} has levels 1-{spec.levels}")
        dm.set_level(side, level)
        return {"ok": True, "level": int(dm.get_current_level(side))}

    @command("set_vedanga_level", category="dasha",
             description="Set the LEFT dasha panel's depth level (in its current mode)")
    def set_vedanga_level(self, level: int) -> dict:
        return self._set_side_level("left", level)

    @command("set_vimshottari_level", category="dasha",
             description="Set the RIGHT dasha panel's depth level (in its current "
                         "mode; Zodiacal Releasing 1-4, others 1-5)")
    def set_vimshottari_level(self, level: int) -> dict:
        return self._set_side_level("right", level)

    def _navigate_side(self, side, direction):
        if direction not in ("next", "prev"):
            raise ValueError(
                f"Invalid direction {direction!r}; must be 'next' or 'prev'")
        dm = self._window.dasha_manager
        if direction == "next":
            dm.nav_next(side)
        else:
            dm.nav_prev(side)
        return {"ok": True}

    @command("navigate_vedanga", category="dasha",
             description="Navigate the LEFT dasha panel (next/prev: 120-year cycle "
                         "in Vimshottari, back one level in Zodiacal Releasing)")
    def navigate_vedanga(self, direction: str) -> dict:
        return self._navigate_side("left", direction)

    @command("navigate_vimshottari", category="dasha",
             description="Navigate the RIGHT dasha panel (next/prev: 120-year cycle "
                         "in Vimshottari, back one level in Zodiacal Releasing)")
    def navigate_vimshottari(self, direction: str) -> dict:
        return self._navigate_side("right", direction)

    # ===================================================================
    # 5.6 Appearance
    # ===================================================================

    @command("set_theme", category="appearance",
             description="Set application theme by display name")
    def set_theme(self, name: str) -> dict:
        from ui.themes import AVAILABLE_THEMES
        name_to_file = {t[1]: t[0] for t in AVAILABLE_THEMES}
        if name not in name_to_file:
            valid = sorted(name_to_file.keys())
            raise ValueError(f"Unknown theme {name!r}; available: {valid}")
        refused = _gate("appearance.theme")
        if refused is not None:
            return refused
        self._window._on_theme_changed(name_to_file[name])
        return {"ok": True, "theme": name}

    @command("set_font_preset", category="appearance",
             description="Set font size preset (very_small/small/medium/large/very_large)")
    def set_font_preset(self, preset: str) -> dict:
        from managers.settings_manager import FONT_SIZE_PRESETS, get_settings
        if preset not in FONT_SIZE_PRESETS:
            raise ValueError(
                f"Unknown preset {preset!r}; must be one of {sorted(FONT_SIZE_PRESETS.keys())}")
        # The keys really written: the size map (R3-2), then the preset name.
        refused = _gate("font_sizes", "appearance.font_size_preset")
        if refused is not None:
            return refused
        get_settings().apply_font_preset(preset)
        return {"ok": True}

    # ===================================================================
    # 5.7 Memory Navigation
    # ===================================================================

    @command("prev_chart", category="navigation",
             description="Go to previous chart in memory stack")
    def prev_chart(self) -> dict:
        mp = getattr(self._window, "memory_panel", None)
        if mp is None or not getattr(mp, "charts", None):
            return {"ok": False, "reason": "no previous chart"}
        self._window._prev_chart()
        chart = self._window.state.active_chart
        name = self._chart_name(chart) or "Unknown"
        return {"ok": True, "name": name}

    @command("next_chart", category="navigation",
             description="Go to next chart in memory stack")
    def next_chart(self) -> dict:
        mp = getattr(self._window, "memory_panel", None)
        if mp is None or not getattr(mp, "charts", None):
            return {"ok": False, "reason": "no next chart"}
        self._window._next_chart()
        chart = self._window.state.active_chart
        name = self._chart_name(chart) or "Unknown"
        return {"ok": True, "name": name}

    @command("list_memory_charts", category="navigation",
             description="List all charts currently in the memory panel")
    def list_memory_charts(self) -> dict:
        mp = getattr(self._window, "memory_panel", None)
        if mp is None:
            return {"ok": True, "charts": [], "count": 0, "active_index": -1}
        charts_raw = getattr(mp, "charts", None) or []
        active_index = int(getattr(mp, "current_index", -1))
        charts = []
        for i, entry in enumerate(charts_raw):
            charts.append({
                "index": i,
                "name": entry.get("person_name", "") or "Unknown",
                "path": entry.get("chtk_path", "") or "",
                "is_transit": is_transit_kind(entry_kind(entry)),
                "kind": entry_kind(entry),
                "is_active": (i == active_index),
            })
        return {
            "ok": True,
            "charts": charts,
            "count": len(charts),
            "active_index": active_index,
        }

    @command("select_memory_chart", category="navigation",
             description="Jump to a memory chart by 0-based index or by name substring")
    def select_memory_chart(self, index_or_name) -> dict:
        mp = getattr(self._window, "memory_panel", None)
        if mp is None:
            return {"ok": False, "reason": "no memory panel available"}
        charts = getattr(mp, "charts", None) or []
        if not charts:
            return {"ok": False, "reason": "memory panel is empty"}

        target_index = None
        if isinstance(index_or_name, bool):
            return {"ok": False, "reason": "index_or_name must be int or str, got bool"}
        if isinstance(index_or_name, int):
            if not (0 <= index_or_name < len(charts)):
                return {"ok": False,
                        "reason": f"index {index_or_name} out of range (0-{len(charts) - 1})"}
            target_index = index_or_name
        else:
            query = str(index_or_name).lower().strip()
            if not query:
                return {"ok": False, "reason": "name query is empty"}
            for i, entry in enumerate(charts):
                name = (entry.get("person_name") or "").lower()
                if query in name:
                    target_index = i
                    break
            if target_index is None:
                return {"ok": False,
                        "reason": f"no chart name matches {index_or_name!r}"}

        mp.select_chart(target_index)
        selected_name = charts[target_index].get("person_name", "") or "Unknown"
        return {"ok": True, "name": selected_name, "index": target_index}

    @command("move_chart_to_profile", category="navigation",
             description="Move a memory chart (by 0-based index, name substring, or uuid) "
                         "into another profile (by profile id or name). Entry-only "
                         "membership move (SPEC-PROF-003).")
    def move_chart_to_profile(self, chart, profile) -> dict:
        mp = getattr(self._window, "memory_panel", None)
        if mp is None:
            return {"ok": False, "reason": "no memory panel available"}
        charts = getattr(mp, "charts", None) or []
        if not charts:
            return {"ok": False, "reason": "memory panel is empty"}

        # Resolve the chart to its uuid (uuid-capture: the panel method
        # re-resolves it again at execution time, SPEC-PROF-003 finding 1).
        chart_id = None
        if isinstance(chart, bool):
            return {"ok": False, "reason": "chart must be int, uuid or name, not bool"}
        if isinstance(chart, int):
            if not (0 <= chart < len(charts)):
                return {"ok": False,
                        "reason": f"index {chart} out of range (0-{len(charts) - 1})"}
            chart_id = charts[chart].get("id")
        else:
            q = str(chart).strip()
            # Exact uuid first, then name substring.
            for entry in charts:
                if entry.get("id") == q:
                    chart_id = q
                    break
            if chart_id is None:
                ql = q.lower()
                for entry in charts:
                    if ql and ql in (entry.get("person_name") or "").lower():
                        chart_id = entry.get("id")
                        break
            if chart_id is None:
                return {"ok": False, "reason": f"no chart matches {chart!r}"}
        if not chart_id:
            return {"ok": False, "reason": "resolved chart has no id"}

        # Resolve the destination profile id (accept id or display name).
        pm = getattr(self._window, "profile_manager", None)
        if pm is None:
            return {"ok": False, "reason": "no profile manager available"}
        dest_id = None
        try:
            profiles = pm.list_profiles()
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "reason": f"could not list profiles: {e}"}
        pq = str(profile).strip()
        for prof in profiles:
            if prof.get("id") == pq:
                dest_id = pq
                break
        if dest_id is None:
            for prof in profiles:
                if (prof.get("name") or "").lower() == pq.lower():
                    dest_id = prof.get("id")
                    break
        if dest_id is None:
            return {"ok": False, "reason": f"no profile matches {profile!r}"}

        outcome = mp._move_chart_to_profile(chart_id, dest_id)
        if not isinstance(outcome, dict):
            outcome = {"ok": False, "reason": "move returned no result"}
        result = {"ok": bool(outcome.get("ok")),
                  "moved": bool(outcome.get("moved")),
                  "message": outcome.get("message", ""),
                  "dest_id": dest_id}
        if not result["ok"]:
            result.setdefault("reason", outcome.get("message", "move failed"))
        return result

    @command("search_memory", category="navigation",
             description="Filter the in-memory chart list by name substring (does NOT search the database)")
    def search_memory(self, query: str) -> dict:
        mp = getattr(self._window, "memory_panel", None)
        if mp is None:
            return {"ok": True, "matches": [], "count": 0}
        charts = getattr(mp, "charts", None) or []
        q = (query or "").lower()
        matches = []
        for i, entry in enumerate(charts):
            name = (entry.get("person_name") or "")
            if q in name.lower():
                matches.append({"index": i, "name": name or "Unknown"})
        return {"ok": True, "matches": matches, "count": len(matches)}

    @command("search_profiles", category="navigation",
             description="Open the 'Search Charts — All Profiles' dialog (the memory panel's SEARCH button), type the query, return results visible in the dialog")
    def search_profiles(self, query: str = "", auto_close_ms: int = 2000) -> dict:
        # The button's click handler (apps/widgets/chart_title_widget.py:1004
        # -> _open_chart_search) uses dialog.exec() which is modal/blocking.
        # We construct the SAME ChartSearchDialog widget but use .show() so
        # the command can drive it programmatically. The user still sees the
        # actual dialog the button would have opened.
        try:
            from apps.widgets.chart_title_widget import ChartSearchDialog
        except ImportError as e:
            return {"ok": False, "reason": f"ChartSearchDialog unavailable: {e}"}

        # Switch to the Chart tab first so the dialog appears in the same
        # context as the Memory Panel's SEARCH button (which is the button
        # the user would click to open this dialog). Without this, the
        # dialog floats over whatever tab happened to be active (e.g.
        # Find Chart) and disconnects from the trigger context.
        tab_widget = getattr(self._window, "tab_widget", None)
        if tab_widget is not None:
            tab_widget.setCurrentIndex(0)

        dialog = ChartSearchDialog(self._window)
        # Keep a reference on the window so Qt doesn't garbage-collect the
        # dialog before the auto-close timer fires.
        self._window._search_profiles_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

        # Set the query in the search field (visible typing). The widget's
        # textChanged signal will call _filter_charts(); we also call it
        # explicitly so the results are populated synchronously before we
        # read them back, regardless of signal-queue timing.
        dialog.search_input.setText(query or "")
        dialog._filter_charts(query or "")

        # Read the populated results from dialog state. Each _filtered entry
        # is (profile_id, profile_name, chart_idx, chart_dict).
        matches = []
        for profile_id, profile_name, chart_idx, chart in dialog._filtered:
            matches.append({
                "name": (chart.get("person_name") or "Unknown"),
                "city": (chart.get("city") or ""),
                "country": (chart.get("country") or ""),
                "profile": profile_name,
                "profile_id": profile_id,
                "chart_index": chart_idx,
            })

        total = len(dialog._all_charts)
        result = {
            "ok": True,
            "query": query or "",
            "matches": matches,
            "count": len(matches),
            "total_in_profiles": total,
        }

        # Auto-close so the dialog doesn't strand the user. The delay lets
        # the visual test screenshot the dialog before it closes.
        if auto_close_ms and auto_close_ms > 0:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(auto_close_ms, dialog.close)

        return result

    # ===================================================================
    # 5.7b Chart Search (CHTK database)
    # ===================================================================

    _VALID_SORT_BY = (
        "name", "file_modified", "country", "birth_date",
        "ascendant", "sun", "moon", "city",
    )

    @staticmethod
    def _shape_find_result(entry: dict) -> dict:
        return {
            "name": entry.get("name", "") or "",
            "path": entry.get("filepath", "") or "",
            "city": entry.get("city", "") or "",
            "country": entry.get("country", "") or "",
            "ascendant": entry.get("ascendant", "") or "",
        }

    def _materialize_find_chart_panel(self):
        """Trigger lazy creation of the Find Chart tab and return the live panel.

        Find Chart starts as a placeholder; first access replaces it via
        `_create_find_chart_widget()`. Returns the panel or None if Pro
        is unavailable.
        """
        panel = getattr(self._window, "find_chart_panel", None)
        if panel is None:
            creator = getattr(self._window, "_create_find_chart_widget", None)
            if callable(creator):
                creator()
            panel = getattr(self._window, "find_chart_panel", None)
        return panel

    @command("find_chart", category="search",
             description="Drive the Find Chart tab: switch tab, set search field, trigger refresh, return populated results (SPEC-REM §4.6)")
    def find_chart(self, query: str, sort_by: str = "name", max_results: int = 20) -> dict:
        if sort_by not in self._VALID_SORT_BY:
            raise ValueError(
                f"Invalid sort_by {sort_by!r}; must be one of {list(self._VALID_SORT_BY)}")
        if not isinstance(max_results, int) or max_results <= 0:
            raise ValueError(f"max_results must be a positive int, got {max_results!r}")

        panel = self._materialize_find_chart_panel()
        if panel is None:
            return {"ok": False, "reason": "Find Chart panel unavailable (Pro feature missing)"}

        # Panel exists but its cache is lazy-init (deferred 100ms after creation).
        # Force load now so _refresh_results() doesn't early-return on cache=None.
        if getattr(panel, "cache", None) is None:
            loader = getattr(panel, "_load_cached_index", None)
            if callable(loader):
                loader()
        if getattr(panel, "cache", None) is None:
            return {"ok": False,
                    "reason": "chart index not yet built (try again in a moment)"}

        # Switch to the Find Chart tab (visible)
        tab_widget = getattr(self._window, "tab_widget", None)
        if tab_widget is not None:
            tab_idx = tab_widget.indexOf(panel)
            if tab_idx >= 0:
                tab_widget.setCurrentIndex(tab_idx)

        # Set sort_by on the panel's combo (visible dropdown change)
        sort_combo = getattr(panel, "sort_combo", None)
        if sort_combo is not None:
            # By item data (the sort key), never by item text (INV-3).
            sort_idx = sort_combo.findData(sort_by)
            if sort_idx >= 0:
                sort_combo.setCurrentIndex(sort_idx)

        # Set query text and trigger refresh directly (bypass 150ms debounce
        # per SPEC-REM §5.7b)
        panel.search_entry.setText(query or "")
        timer = getattr(panel, "search_timer", None)
        if timer is not None:
            timer.stop()
        panel._refresh_results()
        # SPEC-FIND-005 §3.7: a search that could not run leaves the table
        # empty and says why; never answer with rows of an earlier query.
        search_error = getattr(panel, "last_search_error", None)
        if isinstance(search_error, str) and search_error:
            return {"ok": False, "reason": f"search failed: {search_error}",
                    "error": search_error}

        # Read results from the populated table. tree_filepath_map only
        # contains entry rows (not group headers), so iterating it skips
        # headers automatically when grouping is on.
        table = panel.results_table
        rows = sorted(panel.tree_filepath_map.keys())
        total = len(rows)
        results = []
        for row in rows[:max_results]:
            def _cell(col: int) -> str:
                item = table.item(row, col)
                return item.text() if item is not None else ""
            results.append({
                "name": _cell(0),
                "ascendant": _cell(1),
                "city": _cell(4),
                "country": _cell(5),
                "path": panel.tree_filepath_map.get(row, "") or "",
            })

        return {
            "ok": True,
            "results": results,
            "count": len(results),
            "total_in_index": total,
        }

    @command("find_and_load_chart", category="search",
             description="Drive the Find Chart tab to search, then load top result via the panel's own double-click mechanism")
    def find_and_load_chart(self, query: str) -> dict:
        # Run a visible search first (sets search_entry, switches tab,
        # populates results). max_results=1 keeps the read cheap.
        search = self.find_chart(query, sort_by="name", max_results=1)
        if not search.get("ok"):
            return search
        if search["count"] == 0:
            return {"ok": False, "reason": f"no chart matches {query!r}"}

        top = search["results"][0]
        path = top.get("path", "") or ""
        if not path or not os.path.isfile(path):
            return {"ok": False,
                    "reason": f"top match has missing or invalid path: {path!r}"}

        panel = self._window.find_chart_panel  # materialized by find_chart above
        prev_chart = self._window.state.active_chart
        # Simulate a row double-click: the panel emits chart_selected,
        # which the main window's _on_find_chart_selected slot handles
        # by switching to the Chart tab and calling chart_manager.load_chart().
        panel.chart_selected.emit(path)
        chart = self._window.state.active_chart
        if chart is prev_chart:
            return {"ok": False,
                    "reason": f"load_chart silently failed for {path!r} (check app log for traceback)"}

        name = self._chart_name(chart) or top.get("name", "") or os.path.basename(path)
        planet_count = 0
        if chart:
            try:
                planet_count = len(chart.rashi().planets())
            except Exception:
                pass
        return {"ok": True, "name": name, "path": path, "planets": planet_count}

    @command("load_folder", category="navigation",
             description="Bulk-load all CHTK files from a folder into the memory panel (drives the Load Folder workflow visibly). IMPORTANT: automated callers should pass skip_confirmation=True for folders with >100 files, otherwise a modal QMessageBox will block the call until a human responds.")
    def load_folder(self, path: str, skip_confirmation: bool = False) -> dict:
        # Delegates to memory_panel.load_folder_charts_from_path — the same
        # method the GUI's "Load Folder" button calls after the folder picker.
        # The user SEES charts appear in the memory panel as they load
        # (refresh fires once at the end after every chart is added).
        #
        # path validation: we reject anything that isn't a str because remote
        # commands are JSON-driven and JSON has no Path type. pathlib.Path
        # objects can only arrive from in-process callers, who should str()
        # them at the call site. The panel itself accepts Path objects via
        # Path(folder_path), but the remote boundary enforces JSON shape.
        if not isinstance(path, str) or not path.strip():
            return {"ok": False, "reason": "path must be a non-empty string"}

        mp = getattr(self._window, "memory_panel", None)
        if mp is None:
            return {"ok": False, "reason": "no memory panel available"}

        try:
            result = mp.load_folder_charts_from_path(
                path,
                skip_confirmation=bool(skip_confirmation),
            )
        except Exception as e:
            return {"ok": False,
                    "reason": f"load_folder_charts_from_path raised {type(e).__name__}: {e}"}

        # Normalize the panel's dict return into the remote-command shape.
        return {
            "ok": bool(result.get("ok", False)),
            "loaded": int(result.get("loaded", 0)),
            "failed": int(result.get("failed", 0)),
            "total_in_folder": int(result.get("total_in_folder", 0)),
            "cancelled": bool(result.get("cancelled", False)),
            "over_cap": bool(result.get("over_cap", False)),
            **({"reason": result["reason"]} if "reason" in result else {}),
        }

    # ===================================================================
    # 5.7d Web Search (drives the chart title click action)
    # ===================================================================

    @command("google_image_search", category="search",
             description="Open Google Images for the current chart's person name (simulates clicking the chart title label)")
    def google_image_search(self) -> dict:
        from apps.widgets.chart_title_widget import _search_chart_name_google_images
        chart_data = getattr(self._window, "current_chart_data", None)
        if not chart_data:
            return {"ok": False, "reason": "no chart loaded"}
        name = chart_data.get("name", "")
        if not name or name in ("Unknown", "No Chart Loaded"):
            return {"ok": False, "reason": f"no usable name (got {name!r})"}
        _search_chart_name_google_images(self._window)
        return {"ok": True, "name": name,
                "url": f"https://www.google.com/search?q={name}&tbm=isch"}

    # ===================================================================
    # 5.8 Tab Navigation
    # ===================================================================

    @command("switch_tab", category="tab",
             description="Switch to tab by index (int) or name (str)")
    def switch_tab(self, index_or_name) -> dict:
        tw = self._window.tab_widget
        if isinstance(index_or_name, int):
            if not (0 <= index_or_name < tw.count()):
                raise ValueError(
                    f"Tab index {index_or_name} out of range (0-{tw.count() - 1})")
            tw.setCurrentIndex(index_or_name)
        else:
            # Stable tab id ("find_chart") or, as a back-compat alias, the
            # English title ("Find Chart", any case); never the live title,
            # which is translated (SPEC-LOC-002 INV-3).
            from ui.tab_ids import resolve_tab_selector
            found = resolve_tab_selector(self._window, str(index_or_name))
            if found >= 0:
                tw.setCurrentIndex(found)
            else:
                tabs = [tw.tabText(i) for i in range(tw.count())]
                raise ValueError(
                    f"Tab {index_or_name!r} not found; available: {tabs}")
        idx = tw.currentIndex()
        return {"ok": True, "tab": tw.tabText(idx), "index": idx}

    @command("prev_tab", category="tab",
             description="Go to previous tab")
    def prev_tab(self) -> dict:
        self._window._prev_tab()
        tw = self._window.tab_widget
        return {"ok": True, "tab": tw.tabText(tw.currentIndex())}

    @command("next_tab", category="tab",
             description="Go to next tab")
    def next_tab(self) -> dict:
        self._window._next_tab()
        tw = self._window.tab_widget
        return {"ok": True, "tab": tw.tabText(tw.currentIndex())}

    # ===================================================================
    # 5.9 Export & Screenshot
    # ===================================================================

    @command("take_screenshot", category="export",
             description="Take screenshot of current view (saves to screenshot_debug/). "
                         "full_window=True grabs the whole window instead of the chart scene.")
    def take_screenshot(self, full_window: bool = False) -> dict:
        result = self._window.chart_manager.take_screenshot(full_window=full_window)
        if not result:
            # Until 2026-08-04 this branch answered ok:True with an empty path,
            # so a swallowed save exception reported as success.
            return {"ok": False, "reason": "screenshot capture or save failed; "
                                           "see the app log for the traceback"}
        return {"ok": True, "path": str(result)}

    @command("select_settings_page", category="settings",
             description="Select a Settings page by row index or label "
                         "(General, Display Scale, Font Sizes, Chart Display, "
                         "Zodiac & Calculation, Paths & Folders, AI Settings)")
    def select_settings_page(self, row_or_name) -> dict:
        st = getattr(self._window, "settings_tab", None)
        if st is None:
            return {"ok": False, "reason": "settings tab not created yet; "
                                           "switch_tab to SETTINGS first"}
        nav = getattr(st, "nav_list", None)
        stack = getattr(st, "content_stack", None)
        if nav is None or stack is None:
            return {"ok": False, "reason": "settings tab has no nav_list/content_stack "
                                           "(Lite edition or layout changed)"}

        labels = [nav.item(i).text() for i in range(nav.count())]
        # Names are matched against the page list's English SOURCE names (the
        # remote API's stable vocabulary), never against the live labels, which
        # are translated (SPEC-LOC-002 INV-3). A tab without that list (tests,
        # other layouts) falls back to its labels.
        sections = getattr(st, "_SECTIONS", None)
        names = (list(sections) if isinstance(sections, (list, tuple))
                 and len(sections) == len(labels) else labels)
        if isinstance(row_or_name, bool):
            return {"ok": False, "reason": f"invalid page selector {row_or_name!r}"}
        if isinstance(row_or_name, int):
            row = row_or_name
        else:
            wanted = str(row_or_name).strip().lower()
            wanted = {"providers": "ai settings", "ai providers": "ai settings",
                      "ai provider": "ai settings"}.get(wanted, wanted)
            matches = [i for i, lbl in enumerate(names) if lbl.strip().lower() == wanted]
            if not matches:
                matches = [i for i, lbl in enumerate(names) if wanted in lbl.strip().lower()]
            if not matches:
                return {"ok": False, "reason": f"no settings page matching {row_or_name!r}",
                        "available": labels}
            row = matches[0]
        if not (0 <= row < nav.count()):
            return {"ok": False, "reason": f"row {row} out of range 0..{nav.count() - 1}",
                    "available": labels}

        nav.setCurrentRow(row)
        stack.setCurrentIndex(row)
        # A stacked page that was never current renders unlaid-out: rows come out
        # collapsed and any capture of it is worthless. Pump until Qt has laid it out.
        from PySide6.QtWidgets import QApplication
        page = stack.currentWidget()
        if page is not None:
            page.updateGeometry()
        for _ in range(12):
            QApplication.processEvents()
        return {"ok": True, "row": row, "label": labels[row],
                "widget": type(page).__name__ if page is not None else None}

    @command("capture_widget", category="export",
             description="Grab a named widget to a PNG path. name is an attribute path "
                         "from the main window (e.g. 'settings_tab.content_stack') or a "
                         "Qt class name to findChild.")
    def capture_widget(self, name: str, path: str) -> dict:
        from PySide6.QtWidgets import QApplication, QWidget

        widget = self._window
        resolved_as = "window"
        if name and name not in ("window", "main_window"):
            obj = self._window
            for part in str(name).split("."):
                obj = getattr(obj, part, None)
                if obj is None:
                    break
            if isinstance(obj, QWidget):
                widget = obj
                resolved_as = f"attribute:{name}"
            else:
                # Fall back to a class-name search. A QDialog is its own
                # top-level and is invisible to window.grab(), so it MUST be
                # found and grabbed directly.
                #
                # Taking the FIRST match is wrong: allWidgets() is creation
                # order, settings tabs and dialogs get rebuilt, and a stale
                # hidden instance created earlier wins -- a silent wrong-target
                # capture reported as ok:True. Prefer visible instances, and
                # refuse rather than guess when still ambiguous.
                matches = [w for w in QApplication.allWidgets()
                           if type(w).__name__ == name]
                if not matches:
                    return {"ok": False, "reason": f"no widget resolved for {name!r}"}
                visible = [w for w in matches if w.isVisible()]
                candidates = visible or matches
                if len(candidates) > 1:
                    return {"ok": False,
                            "reason": f"{len(candidates)} live widgets named {name!r} "
                                      f"({len(visible)} visible); refusing to guess. "
                                      "Use an attribute path instead.",
                            "ambiguous": True}
                widget = candidates[0]
                resolved_as = f"class:{name}" + ("" if visible else " (none visible)")

        if not widget.isVisible() and widget is not self._window:
            # A hidden widget still grabs a non-null pixmap, at its unlaid-out
            # size -- ok:True with a meaningless image. Pump, then say so in the
            # response so a caller cannot mistake it for a real capture.
            for _ in range(6):
                QApplication.processEvents()

        from managers.font_refresh_deferral import run_pending_for  # td-8m3kd
        run_pending_for(widget)
        pixmap = widget.grab()
        if pixmap.isNull():
            return {"ok": False, "reason": f"grab() returned a null pixmap for {name!r}"}
        if not pixmap.save(str(path), "PNG"):
            return {"ok": False, "reason": f"could not write {path!r}"}
        return {"ok": True, "path": str(path), "resolved_as": resolved_as,
                "size": [pixmap.width(), pixmap.height()],
                "visible": bool(widget.isVisible())}

    @command("export_chart_png", category="export",
             description="Export the CURRENTLY DISPLAYED chart view to a PNG. Grabs the "
                         "live chart_stack page, not the fixed south-indian attribute, so "
                         "it matches whatever style (north/wheel/south/...) the user sees.")
    def export_chart_png(self, path: str) -> dict:
        # `self._window.chart_view` is pinned to the south-indian view
        # (core_gui_qt.py:505, chart_stack index 0). Grabbing it exported a
        # hidden, unlaid-out page whenever any OTHER style was on screen -- a
        # blank 640x480 pixmap saved as ok:True. The live page is whatever the
        # stack currently shows.
        stack = getattr(self._window, "chart_stack", None)
        widget = None
        if stack is not None and hasattr(stack, "currentWidget"):
            widget = stack.currentWidget()
        if widget is None:
            widget = getattr(self._window, "chart_view", None)
        if widget is None:
            return {"ok": False, "reason": "no chart view available"}
        from managers.font_refresh_deferral import run_pending_for  # td-8m3kd
        run_pending_for(widget)
        pixmap = widget.grab()
        if pixmap.isNull():
            return {"ok": False, "reason": "grab() returned a null pixmap"}
        if not pixmap.save(path):
            return {"ok": False, "reason": f"Failed to save to {path!r}"}
        # A size-normalised 16x16 luminance FINGERPRINT. Pixel VARIANCE is not a
        # usable "did it draw" oracle -- a real Delon wheel and a blank themed
        # slate both sit near stddev 20, so any variance threshold either passes
        # the blank or fails a real chart (measured 2026-08-11). The fingerprint
        # is instead meant for a DIFFERENTIAL: two grabs of the SAME chart data
        # (e.g. CHTK-loaded vs map-rebuilt) must produce near-identical grids,
        # and a wrong chart -- different ascendant, a missing planet -- moves
        # cells. Grid is coarse and normalised so minor size/AA jitter is
        # absorbed while a real divergence is not. Computed Qt-side; the caller
        # needs no image library.
        img = pixmap.toImage()
        w, h = img.width(), img.height()
        G = 16
        fingerprint = []
        lum_all = []
        for gy in range(G):
            for gx in range(G):
                x = min(w - 1, (gx * w) // G + w // (2 * G))
                y = min(h - 1, (gy * h) // G + h // (2 * G))
                px = img.pixel(x, y)
                r, g, b = (px >> 16) & 0xFF, (px >> 8) & 0xFF, px & 0xFF
                v = round(0.299 * r + 0.587 * g + 0.114 * b)
                fingerprint.append(v)
                lum_all.append(v)
        mean = sum(lum_all) / (len(lum_all) or 1)
        stddev = (sum((v - mean) ** 2 for v in lum_all) / (len(lum_all) or 1)) ** 0.5
        return {"ok": True, "path": path,
                "size": [w, h], "visible": bool(widget.isVisible()),
                "fingerprint": fingerprint, "lum_stddev": round(stddev, 1)}

    # ===================================================================
    # 5.10 Ascendant Override
    # ===================================================================

    @command("cycle_ascendant", category="ascendant",
             description="Cycle to next ascendant sign override")
    def cycle_ascendant(self) -> dict:
        self._window._cycle_sign_ascendant()
        sign = getattr(self._window, "current_ascendant_override", None)
        return {"ok": True, "ascendant_sign": sign}

    @command("reset_ascendant", category="ascendant",
             description="Reset ascendant to computed (no override)")
    def reset_ascendant(self) -> dict:
        # SPEC-SIC-003 INV-10: the counter, the sign column and every view
        # describe ONE Ascendant. Clearing the counter alone used to leave a
        # button checked and the views still anchored on the override.
        if hasattr(self._window, "current_ascendant_override"):
            self._window.current_ascendant_override = None
        from apps.panels.sign_selector_column import set_column_selection
        set_column_selection(self._window, None)
        for attr in ("wheel_view", "chart_view", "north_indian_view"):
            view = getattr(self._window, attr, None)
            if view is not None:
                view.set_ascendant_override(None)
        if self._window.state.active_chart is not None:
            self._window.chart_manager.reload_current()
        return {"ok": True}

    # ===================================================================
    # 5.10a South Indian Compass (SPEC-SIC-004)
    # ===================================================================

    @command("toggle_compass", category="view",
             description="Toggle the South Indian Compass (Earth-fixed dial) "
                         "on the vector South Indian view")
    def toggle_compass(self) -> dict:
        # Shares the Pro handler so the refusal reasons match the status bar
        # exactly (SPEC-SIC-004 section 3.3; PM-10: never a silent no-op).
        return self._window._toggle_south_indian_compass()

    # ===================================================================
    # 5.10b Edit Chart (SPEC-EDIT-001)
    # ===================================================================

    def _get_edit_panel(self):
        ep = getattr(self._window, 'edit_chart_panel', None)
        if not ep:
            raise RuntimeError("Edit Chart panel not available")
        return ep

    @command("read_edit_form", category="edit",
             description="Read current Edit Info form field values")
    def read_edit_form(self) -> dict:
        ep = self._get_edit_panel()
        tab = ep.info_tab
        data = tab.collect_data()
        try:
            data["utc_hour"] = int(tab.utc_hour.text() or 0)
            data["utc_minute"] = int(tab.utc_minute.text() or 0)
            data["utc_second"] = int(tab.utc_second.text() or 0)
        except (ValueError, AttributeError):
            pass
        return {"ok": True, "fields": data}

    @command("set_edit_field", category="edit",
             description="Set one or more fields on the Edit Info form")
    def set_edit_field(self, **kwargs) -> dict:
        ep = self._get_edit_panel()
        tab = ep.info_tab
        field_map = {
            'name': lambda v: tab.name_input.setText(str(v)),
            'year': lambda v: tab.date_year.setText(str(v)),
            'month': lambda v: tab.date_month.setText(str(v)),
            'day': lambda v: tab.date_day.setText(str(v)),
            'hour': lambda v: tab.local_hour.setText(f"{int(v):02d}"),
            'minute': lambda v: tab.local_minute.setText(f"{int(v):02d}"),
            'second': lambda v: tab.local_second.setText(f"{int(v):02d}"),
            'latitude': lambda v: tab.latitude_input.setText(str(v)),
            'longitude': lambda v: tab.longitude_input.setText(str(v)),
            'timezone': lambda v: tab.timezone_input.setText(str(v)),
            'iana_timezone': lambda v: tab.timezone_iana_input.setText(str(v)),
            'city': lambda v: tab.city_input.setText(str(v)),
            'country': lambda v: tab.country_input.setText(str(v)),
            'dst': lambda v: (
                [tab.dst_none, tab.dst_yes, tab.dst_war][int(v)].setChecked(True),
                tab._on_dst_changed(),
            ),
            'gender': lambda v: (tab.male_radio if str(v).lower() in ('male', 'm', '1') else tab.female_radio).setChecked(True),
        }
        set_fields = []
        for key, value in kwargs.items():
            setter = field_map.get(key)
            if setter:
                setter(value)
                set_fields.append(key)
        return {"ok": True, "set": set_fields}

    @command("save_edit_chart", category="edit",
             description="Trigger save on the Edit Chart panel (full SPEC-EDIT-001 flow)")
    def save_edit_chart(self) -> dict:
        from unittest.mock import patch
        ep = self._get_edit_panel()
        saved = {"called": False, "path": ""}

        def _mock_info(*a, **kw):
            saved["called"] = True

        def _mock_warning(*a, **kw):
            saved["warning"] = a[2] if len(a) > 2 else str(kw)

        def _mock_critical(*a, **kw):
            saved["error"] = a[2] if len(a) > 2 else str(kw)

        from PySide6.QtWidgets import QMessageBox
        with patch.object(QMessageBox, 'information', _mock_info), \
             patch.object(QMessageBox, 'warning', _mock_warning), \
             patch.object(QMessageBox, 'critical', _mock_critical):
            ep.save_changes()

        if saved.get("error"):
            return {"ok": False, "error": saved["error"]}
        if saved.get("warning"):
            return {"ok": True, "warning": saved["warning"]}

        chtk_path = ''
        if ep.current_chart_data:
            chtk_path = ep.current_chart_data.get('chtk_path', '')
        return {
            "ok": saved["called"],
            "chtk_path": chtk_path or '',
            "birth_jd": getattr(self._window, 'birth_jd', None),
            "person_name": getattr(self._window, 'person_name', ''),
        }

    @command("load_edit_form", category="edit",
             description="Load the current chart into the Edit Info form")
    def load_edit_form(self) -> dict:
        ep = self._get_edit_panel()
        ep.load_from_gui()
        data = ep.info_tab.collect_data()
        return {"ok": True, "fields": data}

    # ===================================================================
    # 5.10a Add Chart Dialog (natural language parser + geocoding)
    # ===================================================================

    @command("add_chart_text", category="edit",
             description="Create chart via Add Chart dialog's natural language parser + geocoding. "
                         "Text format: 'Name, Date, Time, City'")
    def add_chart_text(self, text: str, auto_confirm: bool = True) -> dict:
        # Migrated to the shared chart-creation pipeline (SPEC-TRN-005 D-7):
        # parse -> geocode -> ZoneInfo offset -> UTC via
        # BirthDataManager.create_from_form_data -> JD -> build. No dialog
        # instantiation, no QMessageBox mocking. Observable contract parity
        # with the pre-pipeline dialog capture (SPEC-REM-001 consumers are
        # scripts):
        # * empty input -> ok=True + "Empty Input" warning (the old dialog
        #   warned and generated nothing; NOT an error shape);
        # * auto_confirm=True -> warnings ride `messages` as status-style
        #   info entries (the old dialog routed them to its status label;
        #   they are kept, never dropped);
        # * auto_confirm=False -> warnings captured as warning entries with
        #   the old QMessageBox titles/texts;
        # * `error`/`error_stage` keys appear ONLY on genuine failures
        #   (additive; never on the empty-input or success shapes).
        from managers.chart_creation_pipeline import (
            create_chart_from_text, STAGE_PARSE, STAGE_OFFSET,
            STAGE_GEOCODE, STAGE_UTC, STAGE_BUILD, STAGE_PERSIST,
            WARN_DATE_AMBIGUITY, WARN_NO_TIME, WARN_GEOCODE_FAILED,
            WARN_GAP_TIME,
        )
        from core.chart_factory import make_source_params, recipe_from_chart
        from state.events import SetActiveChart

        # Restore the historical AddChartDialog side effect (finding 4c): the
        # old path ran dialog._on_generate(), which stored the stripped input on
        # AddChartDialog._last_input_text on EVERY call (before the empty check),
        # clearing it to "" on empty input. Import the module (not the class)
        # so the caller-source grep test still proves pipeline delegation.
        text_stripped = (text or "").strip()
        try:
            import ui.add_chart_dialog_qt as _add_chart_dialog_mod
            _add_chart_dialog_mod.AddChartDialog._last_input_text = text_stripped
        except Exception:
            # Best-effort UI-memory side effect; never block chart creation.
            pass

        if not text_stripped:
            # Pre-pipeline shape parity: "Empty Input" QMessageBox.warning,
            # no generation attempted, ok stays True.
            return {
                "ok": True,
                "name": "",
                "location": "",
                "messages": [{
                    "type": "warning",
                    "title": "Empty Input",
                    "text": "Please enter birth information in the format:\n"
                            "Name Date Time Location",
                }],
            }

        captured_msgs = []
        win = self._window

        result = create_chart_from_text(
            text,
            mode=win.state.aditya_mode,
            ayanamsa=win.chart_sidereal_ayanamsa_id,
        )

        _warn_titles = {
            WARN_DATE_AMBIGUITY: "Date Ambiguity",
            WARN_NO_TIME: "No Time Found",
            WARN_GEOCODE_FAILED: "Geocoding Failed",
            WARN_GAP_TIME: "Nonexistent Local Time",
        }

        def _status_text(kind, message):
            # The old dialog's auto-confirm path routed warnings to its
            # status label with these short texts.
            if kind == WARN_NO_TIME:
                return "Warning: No time found, defaulting to 12:00 (noon)"
            if kind == WARN_GEOCODE_FAILED:
                return (f"Warning: Could not geocode "
                        f"'{result.city}, {result.country}' — using fallback")
            return f"Warning: {message}"

        for kind, message in result.warnings:
            if auto_confirm:
                captured_msgs.append({
                    "type": "info",
                    "title": "Status",
                    "text": _status_text(kind, message),
                })
            else:
                captured_msgs.append({
                    "type": "warning",
                    "title": _warn_titles.get(kind, "Warning"),
                    "text": message,
                })

        if not result.ok:
            # Explicit error surface (never a silent local-as-UTC fallback):
            # the human `messages` text mirrors the old dialog's
            # QMessageBox.critical shapes and must NOT carry the pipeline's
            # internal stage prefixes ("Chart build failed: ", ".chtk write
            # failed: ", ...) — those are stripped here (finding 4b). The
            # detailed, prefixed message rides the additive error/error_stage
            # keys for SPEC-REM-001 scripts (genuine failures only).
            error_msg = result.error or "Unknown error"
            stage = result.error_stage
            # Pipeline stage -> its "<prefix>: {detail}" lead, stripped to the
            # old bare exception text the legacy dialog showed.
            _stage_prefix = {
                STAGE_GEOCODE: "Location lookup failed: ",
                STAGE_UTC: "UTC conversion failed: ",
                STAGE_BUILD: "Chart build failed: ",
                STAGE_PERSIST: ".chtk write failed: ",
            }
            if stage == STAGE_PARSE:
                title = "Parse Error"
                body = (f"Could not parse birth data:\n\n{error_msg}\n\n"
                        "Please include at least a date "
                        "(e.g. 'January 15, 1990').")
            elif stage == STAGE_OFFSET:
                # Explicit UTC-resolution failure (SPEC-UTC-001) — the migrated
                # dialog's dedicated shape, not the generic one.
                title = "Timezone Resolution Error"
                body = ("Could not resolve the UTC offset for this chart:\n\n"
                        f"{error_msg}\n\n"
                        "The chart was NOT generated (a silent local-as-UTC "
                        "fallback would produce a wrong chart).")
            else:
                title = "Chart Generation Error"
                bare = error_msg
                pref = _stage_prefix.get(stage)
                if pref and bare.startswith(pref):
                    bare = bare[len(pref):]
                short = bare if len(bare) <= 150 else bare[:150] + "..."
                body = f"Failed to generate chart:\n\n{short}"
            captured_msgs.append(
                {"type": "critical", "title": title, "text": body})
            return {
                "ok": False,
                # Parity (finding 4a): the load callback never fired for a
                # failure at/after parse, so name/location stay empty exactly
                # as the baseline capture did (result_info was populated only
                # inside the callback).
                "name": "",
                "location": "",
                "error": result.error,
                "error_stage": result.error_stage,
                "messages": captured_msgs,
            }

        def on_chart_loaded(chart, name, location, *, planets_data=None,
                            file_path=None):
            # file_path: the file the pipeline wrote (SPEC-PERSIST-001 INV-7).
            ctx = chart.context
            lat = ctx.location.lat
            lon = ctx.location.long
            utcoffset = ctx.timeJD.utcoffset if hasattr(ctx.timeJD, 'utcoffset') else 0.0
            _pd = planets_data or {}
            country = _pd.get('country', 'Unknown')
            timezone_str = _pd.get('timezone', 'UTC')
            # NOTE: this is the TEXT-PARSED chart path (AddChartDialog free-text).
            # birth_data is assembled by hand from the computed chart context and
            # never carries rodden/tags/notes/julian_day/dst_offset_hours, so the
            # metadata forwarded to recipe_from_chart below is always None/omitted.
            # If a future path loads a real .toml file HERE, do not hand-build this
            # dict: use BirthDataManager.create_birth_data_from_file() so the
            # canonical rodden/tags/notes/julian_day fields are carried through.
            birth_data = {
                'name': name, 'year': ctx.timeJD.usryear(),
                'month': ctx.timeJD.usrmonth(), 'day': ctx.timeJD.usrday(),
                'timedec': ctx.timeJD.usrhour(), 'lat': lat, 'lon': lon,
                'utcoffset': utcoffset, 'city': location, 'country': country,
            }
            win.state.dispatch(SetActiveChart(
                chart=chart,
                source_params=make_source_params(
                    chtk_path=file_path, birth_data=birth_data,
                    mode=win.state.aditya_mode,
                    ayanamsa=win.chart_sidereal_ayanamsa_id,
                    house_system=win.state.house_system,
                    is_human_design=False,
                )))
            win.birth_jd = float(ctx.timeJD.jd)
            win.birth_lat = lat
            win.birth_lon = lon
            win.current_timezone = timezone_str
            win.person_name = name
            win.birth_country = country
            win.current_chart_path = file_path
            from state.events import SetHumanDesignMode
            win.state.dispatch(SetHumanDesignMode(enabled=False))  # Stage 2 td-ltha
            if hasattr(win, 'chart_memory_panel') and win.chart_memory_panel:
                _recipe = recipe_from_chart(
                    chart, timezone=timezone_str,
                    city=location, country=country,
                    # SPEC-IMPORT-001 §6.3: user chart (from parsed text);
                    # forward additive metadata if the parser supplied it
                    # (None -> conditionally omitted by make_recipe).
                    rodden=birth_data.get('rodden'),
                    tags=birth_data.get('tags'),
                    notes=birth_data.get('notes'),
                    julian_day=birth_data.get('julian_day'),
                    dst_offset_hours=birth_data.get('dst_offset_hours'),
                )
                win.chart_memory_panel.add_chart(
                    _recipe, chart_obj=win.state.active_chart,
                )
            win._current_chart_data = None
            win._current_birth_data = None
            win._finalize_chart_load()

        try:
            on_chart_loaded(
                result.chart, result.name, result.location_label,
                planets_data=result.planets_data,
            )
        except Exception as e:
            captured_msgs.append({
                "type": "critical",
                "title": "Chart Loading Error",
                "text": f"Chart was generated but failed to load:\n\n{e}",
            })
            return {
                "ok": False,
                "name": result.name,
                "location": result.location_label,
                "error": str(e),
                "error_stage": "load",
                "messages": captured_msgs,
            }

        captured_msgs.append({
            "type": "info",
            "title": "Success",
            "text": f"Chart successfully generated for:\n{result.name}\n"
                    f"{result.location_label}",
        })
        return {
            "ok": True,
            "name": result.name,
            "location": result.location_label,
            "messages": captured_msgs,
        }

    # ===================================================================
    # 5.10b New Chart Form
    # ===================================================================

    def _get_new_chart_tab(self):
        ep = self._get_edit_panel()
        nct = getattr(ep, 'new_chart_tab', None)
        if nct is None:
            raise RuntimeError("No new_chart_tab on edit_chart_panel")
        return nct, ep

    @command("switch_to_new_chart", category="edit",
             description="Switch to the New Chart subtab within Edit Chart")
    def switch_to_new_chart(self) -> dict:
        tw = self._window.tab_widget
        from ui.tab_ids import tab_index
        edit_index = tab_index(self._window, "new_edit")  # by widget (INV-3)
        if edit_index >= 0:
            tw.setCurrentIndex(edit_index)
        _nct, ep = self._get_new_chart_tab()
        ep.sidebar.setCurrentRow(1)
        return {"ok": True, "subtab": "New Chart"}

    @command("fill_new_chart", category="edit",
             description="Fill New Chart form fields (name, month, day, year, hour, minute, second, city, country, lat, lon, timezone, gender, dst)")
    def fill_new_chart(self, name=None, month=None, day=None, year=None,
                       hour=None, minute=None, second=None,
                       city=None, country=None, lat=None, lon=None,
                       timezone=None, gender=None, dst=None) -> dict:
        nct, ep = self._get_new_chart_tab()
        ep.sidebar.setCurrentRow(1)
        nct.clear_form()
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        if name is not None:
            nct.name_input.setText(str(name))
        if month is not None:
            nct.date_month.setText(str(int(month)))
        if day is not None:
            nct.date_day.setText(str(int(day)))
        if year is not None:
            nct.date_year.setText(str(int(year)))
        if hour is not None:
            nct.local_hour.setText(str(int(hour)))
        if minute is not None:
            nct.local_minute.setText(str(int(minute)))
        if second is not None:
            nct.local_second.setText(str(int(second)))
        if gender is not None:
            g = str(gender).lower()
            if g in ('male', 'm', '1'):
                nct.male_radio.setChecked(True)
            elif g in ('female', 'f', '2'):
                nct.female_radio.setChecked(True)
        if city is not None:
            nct.set_city(str(city))
        if country is not None:
            nct.set_country(str(country))
        if lat is not None and lon is not None:
            nct.set_coordinates(float(lat), float(lon))
        if timezone is not None:
            nct.set_timezone(str(timezone))
        if dst is not None:
            dst_val = int(dst)
            if dst_val == 0:
                nct.dst_none.setChecked(True)
            elif dst_val == 1:
                nct.dst_yes.setChecked(True)
            elif dst_val == 2:
                nct.dst_war.setChecked(True)
        QApplication.processEvents()
        return {"ok": True, "filled": nct.collect_data()}

    @command("submit_new_chart", category="edit",
             description="Click Create Chart on the New Chart form (must be filled first)")
    def submit_new_chart(self) -> dict:
        nct, _ep = self._get_new_chart_tab()
        from PySide6.QtWidgets import QMessageBox, QApplication
        _orig_info = QMessageBox.information
        _orig_warn = QMessageBox.warning
        _orig_crit = QMessageBox.critical
        _captured = []
        def _mock_dialog(dtype):
            def _mock(parent, title, text, *a, **kw):
                _captured.append({"type": dtype, "title": title, "text": text})
                return QMessageBox.StandardButton.Ok
            return _mock
        QMessageBox.information = _mock_dialog("info")
        QMessageBox.warning = _mock_dialog("warning")
        QMessageBox.critical = _mock_dialog("critical")
        try:
            nct._on_create_chart()
            QApplication.processEvents()
        finally:
            QMessageBox.information = _orig_info
            QMessageBox.warning = _orig_warn
            QMessageBox.critical = _orig_crit
        return {"ok": True, "messages": _captured}

    @command("read_new_chart_form", category="edit",
             description="Read current New Chart form field values")
    def read_new_chart_form(self) -> dict:
        nct, _ep = self._get_new_chart_tab()
        return {"ok": True, "fields": nct.collect_data()}

    @command("simulate_map_select", category="edit",
             description="Simulate a map click at given coordinates. Triggers the full "
                         "map→geocode→timezone→form pipeline exactly as a real user click.")
    def simulate_map_select(self, lat: float, lon: float,
                            target: str = "new_chart") -> dict:
        ep = self._get_edit_panel()
        map_tab = getattr(ep, 'map_tab', None)
        if map_tab is None:
            raise RuntimeError("No map_tab on edit_chart_panel")
        ep._map_caller = target
        from PySide6.QtWidgets import QApplication
        map_tab._on_map_clicked(float(lat), float(lon))
        QApplication.processEvents()
        tz = map_tab.get_detected_timezone()
        tgt = ep.new_chart_tab if target == "new_chart" else ep.info_tab
        data = tgt.collect_data()
        return {
            "ok": True,
            "detected_timezone": tz,
            "form_timezone": data.get('timezone', ''),
            "form_dst": data.get('dst', 0),
            "form_city": data.get('city', ''),
            "form_country": data.get('country', ''),
            "form_latitude": data.get('latitude', 0),
            "form_longitude": data.get('longitude', 0),
        }

    # ===================================================================
    # 5.11 Settings
    # ===================================================================

    @command("get_setting", category="settings",
             description="Read a setting by dotted key path")
    def get_setting(self, key: str) -> dict:
        from managers.settings_manager import get_settings
        value = get_settings().get(key)
        return {"ok": True, "key": key, "value": value}

    @command("set_setting", category="settings",
             description="Write a setting by dotted key path")
    def set_setting(self, key: str, value: Any = None) -> dict:
        from managers.settings_manager import get_settings
        from managers.live_frame_manager import publication_batch
        from core import settings_registry
        # A registry key takes only a value its declaration accepts (type,
        # choices, bounds, rules.validate): an invalid value is refused, never
        # stored for a view to choke on (W5-fix4: an invalid cusp glow mode made
        # every later chart display tail raise). Keys outside the registry keep
        # the plain set.
        if settings_registry.has(key) and not settings_registry.valid(key, value):
            return {"ok": False, "key": key,
                    "error": f"invalid value {value!r} for {key}"}
        # AI setting redesign fix RD-1: the request service's policy before
        # any write. Keys outside the registry (app and runtime state), the
        # consents, the screenshot notice flag, every key not classified
        # ``ai`` and a locked key are refused (the panel-only keys are
        # ordinary preferences here: Lorris, 2026-10-11); an
        # ask-first key too (its only Allow is the AI setting panel's, in
        # process; nothing a remote request carries counts as one).
        from core.edition_features import running_edition
        from core.settings_registry import app_requests
        refused = app_requests.direct_write_refusal(
            key, value, running_edition(), get_settings(), panel_only=True)
        if refused is not None:
            return {"ok": False, "key": key, "reason": refused.get("reason"),
                    "error": f"refused ({refused.get('reason')}): {key}"}
        # SPEC-SET-003 §4.6 (W5-fix2 P2): the write and the shared adoption tail
        # publish ONE completed live frame, exactly as a Settings Apply does; a
        # failing write or tail runs the tail again (reconcile, W5-fix3 P2).
        window = self._window
        # AI setting redesign (td-bztjj, item 3): the shared tail plus the key
        # family's live apply (fonts, scale, saturation, theme, planet sizes,
        # GUI toggles), the SAME function the in-app request service runs.
        # W5-fix4 P2: ``owns`` releases only what this tail adopts (the
        # written key, and the chart display family when the chart tail ran).
        # Fix round 2 (R2-1, R2-2, R2-3): the write is the request service's
        # authoritative transaction (``commit``): under the settings-file lock
        # the SAVED toggle and the saved and in-memory locks are read again, a
        # planet size scale expands there keeping each locked planet's saved
        # size, and the change is saved; its callbacks are held back until
        # then and run here, inside the one published frame.
        from core.settings_registry import planet_sizes
        from managers.setting_live_apply import window_tail
        sm = get_settings()
        path = planet_sizes.write_path(key)
        adopt, owns = window_tail(window, path)

        with publication_batch(reconcile=adopt, owns=owns):
            # The write inside the batch, as before: the batch sees the value
            # change, and a failing tail holds it (W5-fix3).
            reply = _commit(sm, key, value)
            if reply.get("status") != app_requests.APPLIED:
                return _refused(key, reply)
            sm._notify_change(path, sm.get(path))
            # Every key the Chart Display page OWNS must reach EVERY view live,
            # exactly like clicking its Settings Apply button. Apply and this remote
            # path both call the ONE shared window tail apply_chart_display_settings()
            # (chart views + icon views incl. open PlanetInfoDialog popups), so they
            # are indistinguishable and cannot drift (td-iaqm.2.1). Writing the key
            # alone left the vector view / Compass / popups stale on the remote/CLI
            # flip path (Rule 24 harness parity), so route the WHOLE owned
            # display/chart family through it; a key outside the set keeps plain-set
            # behaviour. td-iaqm.5 CP7c (sign_display) / td-iaqm.2.1 (the full family).
            # The set is pinned to the page's OWNED_CHART_KEYS / OWNED_DISPLAY_KEYS
            # allowlists (test_remote_display_routing).
            adopt()
        out = {"ok": True}
        if reply.get(app_requests.KEPT_FIELD):
            out[app_requests.KEPT_FIELD] = list(reply[app_requests.KEPT_FIELD])
        return out

    # ===================================================================
    # 5.12 State Inspection (read-only)
    # ===================================================================

    @command("get_state", category="state",
             description="Get full application state snapshot")
    def get_state(self) -> dict:
        from managers.settings_manager import get_settings
        s = get_settings()
        state = self._window.state
        tw = self._window.tab_widget
        mp = getattr(self._window, "memory_panel", None)

        chart = state.active_chart
        chart_name = self._chart_name(chart)
        chart_path = getattr(self._window, "current_chart_path", None)
        if chart_path:
            chart_path = str(chart_path)

        ayanamsa_id = s.get("zodiac.ayanamsa_id", _registry_default("zodiac.ayanamsa_id")) or 0
        ayanamsa_name = str(ayanamsa_id)
        try:
            from core.ayanamsa_data import get_ayanamsa_name
            ayanamsa_name = get_ayanamsa_name(ayanamsa_id)   # by id, never list position
        except (ImportError, IndexError, TypeError):
            pass

        action = getattr(self._window, "outer_planets_action", None)
        outer_planets = action.isChecked() if action else False

        # SPEC-ZR-001 (W6 review MINOR 6): active ZR releaser + depth from the
        # runtime state, falling back to settings when the panel is unbuilt.
        # (the right side's, the field's original meaning; SPEC-DSH-004)
        _dm = getattr(self._window, "dasha_manager", None)
        _zr = _dm.zr_state("right") if _dm is not None else None
        zr_releaser = (_zr.releaser if _zr is not None and getattr(_zr, "result", None) is not None
                       else s.get("dasha.zr.releaser", _registry_default("dasha.zr.releaser")))
        zr_level = _zr.level if _zr is not None else 1

        return {
            "chart": {
                "loaded": chart is not None,
                "name": chart_name,
                "path": chart_path,
                "view": state.chart_view_style,
                # SPEC-VGC-001 D-9: with the center mode on, one "varga"
                # field would claim D-10 for a main chart showing D-1.
                **self._read_varga_state(),
            },
            "zodiac": {
                "mode": state.aditya_mode,
                "western_names": getattr(self._window, "use_western_names", False),
                "western_names_setting": s.get("zodiac.use_western_names", _registry_default("zodiac.use_western_names")),
                "ayanamsa_id": ayanamsa_id,
                "ayanamsa_name": ayanamsa_name,
                "house_system": s.get("zodiac.house_system", _registry_default("zodiac.house_system")),
                "human_design": getattr(self._window, "is_human_design", False),
            },
            "display": {
                "outer_planets": outer_planets,
                "retinue_rings": s.get("chart.show_retinue_rings", False),
                "south_indian_retinue": self._window.chart_view.retinue_state(),
                "element_pies": s.get("chart.show_element_pies", False),
                "cusp_glow_mode": s.get("chart.cusp_glow_mode", 0),
                "tropical_rim": getattr(self._window, "show_tropical_rim", False),
                "transit_rim": getattr(getattr(self._window, 'transit_overlay_manager', None), 'transit_enabled', False),
                # SPEC-TRN-006: distinguish live-sky from chart-overlay so
                # automation can tell the two rims apart.
                "transit_mode": getattr(getattr(self._window, 'transit_overlay_manager', None), 'transit_mode', 'auto'),
                "overlay_label": getattr(getattr(self._window, 'transit_overlay_manager', None), 'overlay_label', ''),
            },
            "appearance": {
                "theme": s.get("appearance.theme", ""),
                "font_preset": s.get("appearance.font_size_preset", "medium"),
            },
            "navigation": {
                "active_tab": tw.currentIndex(),
                "active_tab_name": tw.tabText(tw.currentIndex()),
                "memory_count": len(getattr(mp, "charts", None) or []),
                "memory_index": getattr(mp, "current_index", 0) if mp else 0,
            },
            "dasha": {
                "right_panel_type": self._window.dasha_manager.mode("right"),
                # SPEC-DSH-004: the left panel has modes too (runtime + stored pair)
                "left_panel_type": self._window.dasha_manager.mode("left"),
                "left_mode": s.get("dasha.left.mode", _registry_default("dasha.left.mode")),
                "vedanga_level": self._window.dasha_manager.side_level("left"),
                "vimshottari_level": self._window.dasha_manager.side_level("right"),
                "left_ayanamsa_id": s.get("dasha.left.ayanamsa_id", _registry_default("dasha.left.ayanamsa_id")),
                "right_mode": s.get("dasha.right.mode", _registry_default("dasha.right.mode")),
                "right_ayanamsa_id": s.get("dasha.right.ayanamsa_id", _registry_default("dasha.right.ayanamsa_id")),
                # SPEC-ZR-001 (W6 review MINOR 6): the active ZR releaser and the
                # true ZR depth, so automation reads ZR state instead of the
                # unrelated vimshottari_level.
                "zr_releaser": zr_releaser,
                "zr_level": zr_level,
            },
        }

    @command("get_chart_info", category="state",
             description="Get current chart metadata")
    def get_chart_info(self) -> dict:
        chart = self._window.state.active_chart
        if chart is None:
            return {"ok": True, "chart": None}
        return {
            "ok": True,
            "chart": {
                "name": self._chart_name(chart),
                "path": str(getattr(self._window, "current_chart_path", "") or ""),
            },
        }

    @command("get_planet_positions", category="state",
             description="Get current planet positions from active chart")
    def get_planet_positions(self) -> dict:
        chart = self._window.state.active_chart
        if chart is None:
            return {"ok": True, "planets": {}, "mode": None}
        planets = {}
        try:
            rashi = chart.rashi()
            for name, p in rashi.planets().items():
                lon = p.ecliptic_longitude()
                speed = p.longitude_speed()
                sign_idx = p.sign() - 1
                planets[name] = {
                    "longitude": round(lon, 4),
                    "sign": sign_idx,
                    "sign_name": p.sign_name(),
                    "in_sign_degree": str(p.in_sign_longitude()),
                    "nakshatra": p.nakshatra_name(),
                    "retrograde": speed < 0,
                }
        except Exception:
            pass
        mode = self._window.state.aditya_mode
        return {"ok": True, "planets": planets, "mode": mode}

    # ===================================================================
    # 5.13 Chart Reading Layer (SPEC-REM-002 Wave 1)
    # ===================================================================

    # ---------- read_chart helpers ----------

    def _outer_visible(self) -> bool:
        action = getattr(self._window, "outer_planets_action", None)
        if action is None:
            return True
        return bool(action.isChecked())

    def _effective_ascendant_sign_index(self, computed_sign_index: int) -> int:
        override = getattr(self._window, "current_ascendant_override", None)
        if override is None:
            return computed_sign_index
        return int(override)

    @staticmethod
    def _in_sign_pair(p_or_cusp):
        from core.capabilities.chart import in_sign_pair
        return in_sign_pair(p_or_cusp)

    @staticmethod
    def _coerce_number(value):
        """A float, from either an attribute or a zero-argument accessor.

        libaditya is inconsistent about which of the two a value is, and the
        snapshot must never carry a callable — `json.dump(default=str)` turns
        one into a repr string that looks like data.
        """
        if callable(value):
            try:
                value = value()
            except Exception:
                return None
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _read_metadata(self, chart, varga: int,
                       varga_overridden: bool = False) -> dict:
        from managers.settings_manager import get_settings
        s = get_settings()
        ctx = getattr(chart, "context", None)

        if varga_overridden:
            drawn_in = "request"
        else:
            vs = self._read_varga_state()
            if vs.get("varga_in_center_box") == int(varga):
                drawn_in = "center_box"
            elif vs.get("varga_in_outer_ring") == int(varga):
                drawn_in = "outer_ring"
            else:
                drawn_in = "main_chart"

        name = self._chart_name(chart)
        chtk_path = getattr(self._window, "current_chart_path", None)
        if chtk_path is not None:
            chtk_path = str(chtk_path)

        birth_date = None
        birth_time = None
        utc_offset = None
        latitude = None
        longitude = None

        if ctx is not None:
            y = getattr(ctx, "year", None)
            mo = getattr(ctx, "month", None)
            d = getattr(ctx, "day", None)
            if y is not None and mo is not None and d is not None:
                try:
                    birth_date = f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
                except (TypeError, ValueError):
                    birth_date = None
            h = getattr(ctx, "hour", None)
            mi = getattr(ctx, "minute", None)
            if h is not None and mi is not None:
                sec = getattr(ctx, "second", 0) or 0
                try:
                    birth_time = f"{int(h):02d}:{int(mi):02d}:{int(sec):02d}"
                except (TypeError, ValueError):
                    birth_time = None
            utc_offset = getattr(ctx, "utc_offset", None)
            if utc_offset is None:
                utc_offset = getattr(ctx, "timezone", None)
            loc = getattr(ctx, "location", None)
            if loc is not None:
                # libaditya's Location exposes latitude/longitude as METHODS,
                # so a bare getattr yields the bound method and json.dump
                # serialised "<bound method Location.latitude of ...>" into
                # the snapshot instead of a number.
                latitude = self._coerce_number(getattr(loc, "latitude", None))
                longitude = self._coerce_number(getattr(loc, "longitude", None))
            if latitude is None:
                latitude = self._coerce_number(getattr(ctx, "latitude", None))
            if longitude is None:
                longitude = self._coerce_number(getattr(ctx, "longitude", None))

        return {
            "chart_name": name,
            "birth_date": birth_date,
            "birth_time": birth_time,
            "utc_offset": utc_offset,
            "latitude": latitude,
            "longitude": longitude,
            "chtk_path": chtk_path,
            "mode": getattr(self._window.state, "aditya_mode", None),
            "western_names": getattr(self._window, "use_western_names", False),
            "ayanamsa_id": getattr(self._window, "chart_sidereal_ayanamsa_id",
                                    s.get("zodiac.ayanamsa_id", _registry_default("zodiac.ayanamsa_id"))),
            "house_system": s.get("zodiac.house_system", _registry_default("zodiac.house_system")),
            "varga": int(varga),
            # SPEC-VGC-001 D-9 again, for the reading layer. `varga` alone
            # says WHICH divisional this snapshot is; with the center mode on
            # it does NOT say where the user sees it, and a consumer reading
            # "varga: 9" while the main grid draws D-1 is being misled in
            # exactly the way _read_varga_state exists to prevent.
            #   "main_chart"  the big South Indian / North Indian / wheel grid
            #   "center_box"  the mini inside the South Indian center box
            #   "outer_ring"  the ring around the wheel / North Indian chart
            #   "request"     the caller passed varga= explicitly, so this
            #                 snapshot describes neither of the two surfaces
            "varga_drawn_in": drawn_in,
        }

    def _build_sign_name_map(self, planets_dict, cusps) -> dict:
        from core.capabilities.chart import build_sign_name_map
        return build_sign_name_map(planets_dict, cusps)

    @staticmethod
    def _sign_name_for(sign_index: int, sign_names: dict) -> str:
        from core.capabilities.chart import sign_name_for
        return sign_name_for(sign_index, sign_names)

    def _planet_snapshot(self, name: str, p, outer_names: set, outer_visible: bool) -> dict:
        from core.capabilities.chart import planet_snapshot
        return planet_snapshot(name, p, outer_names, outer_visible)

    def _ascendant_snapshot(self, cusps) -> dict:
        from core.capabilities.chart import ascendant_snapshot
        return ascendant_snapshot(
            cusps, getattr(self._window, "current_ascendant_override", None))

    @staticmethod
    def _whole_sign_houses(eff_asc_idx: int, sign_names: dict, planets_dict) -> dict:
        from core.capabilities.chart import whole_sign_houses
        return whole_sign_houses(eff_asc_idx, sign_names, planets_dict)

    @staticmethod
    def _cusp_houses(cusps) -> dict:
        from core.capabilities.chart import cusp_houses
        return cusp_houses(cusps)

    @staticmethod
    def _planet_cusp_house(planet_lon: float, cusps) -> int:
        from core.capabilities.chart import planet_cusp_house
        return planet_cusp_house(planet_lon, cusps)

    def _planet_to_houses(self, planets_dict, cusps, eff_asc_idx: int) -> dict:
        from core.capabilities.chart import planet_to_houses
        return planet_to_houses(planets_dict, cusps, eff_asc_idx)

    @command("read_chart", category="reading",
             description="Full chart snapshot (planets, ascendant, houses) using libaditya accessors; respects current varga and ascendant override")
    def read_chart(self, varga: int = None) -> dict:
        chart = self._window.state.active_chart
        if chart is None:
            return {"ok": False, "reason": "no chart loaded"}

        state = self._window.state
        varga_overridden = varga is not None
        if varga is None:
            varga = getattr(state, "current_varga", 1) or 1

        from core.capabilities.chart import varga_source
        source = varga_source(chart, varga)

        metadata = self._read_metadata(chart, varga, varga_overridden)

        outer_visible = self._outer_visible()
        # The label set the drawings use (one rule, core.hd_model): in Human
        # Design mode the Design chart's own mode names, else the app's set.
        from core.hd_model import chart_display_for
        w = self._window
        hd = getattr(w, "is_human_design", False) is True
        disp_mode, disp_western = chart_display_for(
            getattr(state, "aditya_mode", None),
            getattr(w, "use_western_names", False),
            w.hd_manager.design_chart_mode() if hd else None)
        metadata["mode"], metadata["western_names"] = disp_mode, disp_western
        # AIC plan 2 (INV-1): one snapshot function for this live reader and
        # the headless get_chart capability.
        from core.capabilities.chart import chart_snapshot
        snap = chart_snapshot(
            source,
            getattr(self._window, "current_ascendant_override", None),
            outer_visible,
            # The label set and sign language on screen, so sign_name is what
            # the wheel shows.
            use_western_names=disp_western,
            sign_language=getattr(self._window, "sign_language", "en") or "en")
        return {"ok": True, "metadata": metadata, **snap}

    @command("verify_display", category="verify",
             description="Check all runtime/setting pairs for divergence (zodiac mode, western names, display toggles)")
    def verify_display(self) -> dict:
        from managers.settings_manager import get_settings
        s = get_settings()
        w = self._window
        checks = []

        def add(field, runtime, setting):
            checks.append({
                "field": field,
                "runtime": runtime,
                "setting": setting,
                "match": runtime == setting,
            })

        add("zodiac.mode",
            getattr(w.state, "aditya_mode", None),
            s.get("zodiac.mode", _registry_default("zodiac.mode")))

        add("western_names",
            getattr(w, "use_western_names", False),
            s.get("zodiac.use_western_names", _registry_default("zodiac.use_western_names")))

        add("ayanamsa_id",
            getattr(w, "chart_sidereal_ayanamsa_id", 0),
            s.get("zodiac.ayanamsa_id", _registry_default("zodiac.ayanamsa_id")))

        outer_action = getattr(w, "outer_planets_action", None)
        outer_runtime = outer_action.isChecked() if outer_action is not None else True
        add("outer_planets",
            outer_runtime,
            s.get("chart.show_outer_planets", _registry_default("chart.show_outer_planets")))

        add('retinue_rings', w.chart_view.show_retinue_rings,
            s.get('chart.show_retinue_rings', False))
        add('retinue_ruler', w.chart_view.show_trimsamsha_degrees,
            s.get('chart.show_trimsamsha_degrees', False))
        # Settings-only fields: runtime is the setting itself (no separate
        # window attribute exists; the chart_view reads the setting directly).
        for field, key, default in (
            ("element_pies",   "chart.show_element_pies", True),
            ("cusp_glow_mode", "chart.cusp_glow_mode", 0),
        ):
            v = s.get(key, default)
            add(field, v, v)

        add("tropical_rim",
            getattr(w, "show_tropical_rim", False),
            s.get("chart.show_tropical_rim", False))
        _mgr = getattr(w, 'transit_overlay_manager', None)
        _runtime_transit = _mgr.transit_enabled if _mgr else False
        # SPEC-TRN-006 B-8: a chart overlay is intentionally session-transient and
        # persisted False while the rim is on. Comparing runtime-on to persisted-off
        # would be a false divergence, so treat overlay mode as self-consistent.
        if _mgr is not None and getattr(_mgr, 'transit_mode', '') == "overlay_chart":
            add("transit_rim", _runtime_transit, _runtime_transit)
        else:
            add("transit_rim", _runtime_transit,
                s.get("chart.show_transit_overlay", s.get("chart.show_transit_rim", False)))
        add("human_design",
            getattr(w, "is_human_design", False),
            s.get("chart.show_human_design", False))

        divergences = sum(1 for c in checks if not c["match"])

        status = ""
        try:
            status = w.statusBar().currentMessage() or ""
        except Exception:
            status = ""

        return {
            "ok": True,
            "checks": checks,
            "divergences": divergences,
            "status_message": status,
        }

    # ===================================================================
    # 5.13b Chart Reading Layer (SPEC-REM-002 Wave 2)
    # ===================================================================

    @staticmethod
    def _normalize_sign_name(s) -> str:
        """IAST → ASCII, case-insensitive. 'varuṇa' → 'varuna'.

        Stripping diacritics alone is not enough to compare the two spellings
        this codebase actually produces. libaditya writes proper IAST (ṣ, ś,
        ṃ) which decomposes to a bare 's'; the CLI extractor and the website
        write the popular transliteration ('Pusha', 'Tvashta', 'Vishnu') and
        older material writes 'Amzu'. Folding the sibilant variants together
        takes agreement across the 12 Aditya names from 8/12 to 12/12 with no
        collisions — before this, verify_parity reported 'pūṣā' vs 'Pusha' as
        a DATA divergence, which is the loudest severity it has.
        """
        if not isinstance(s, str):
            return ""
        import unicodedata
        nfkd = unicodedata.normalize("NFKD", s)
        ascii_str = "".join(c for c in nfkd if not unicodedata.combining(c))
        folded = ascii_str.lower().strip()
        return folded.replace("sh", "s").replace("z", "s")

    @command("read_human_design", category="reading",
             description="Human Design BodyGraph model (SPEC-HD-001) for the active chart. Returns core.hd_model.build_hd_model output byte-identical to the show_human_design CLI (INV-1). Optional frame: standard (default)/aditya/sidereal.")
    def read_human_design(self, frame: str = None) -> dict:
        """The HDModel dict for the loaded chart, via the ONE producer.

        Byte-identical to ``python -m AI_tools.cli.show_human_design --json`` for
        the same chart + frame: both call ``build_hd_model`` on the same birth
        instant (the remote reuses the active chart's own ``context``; the CLI
        rebuilds it from the file). SPEC-REM-002 defensive: never raises,
        collects issues in ``errors[]``.
        """
        errors = []
        chart = self._window.state.active_chart
        if chart is None:
            return {"ok": False, "reason": "no chart loaded"}

        from core.hd_model import VALID_FRAMES
        mgr = getattr(self._window, "hd_manager", None)

        # Resolve the frame: explicit arg wins; else the manager's settings
        # frame; else Standard. An unknown explicit value is a caller error.
        if frame is not None and frame not in VALID_FRAMES:
            return {"ok": False,
                    "reason": f"invalid frame {frame!r}; must be one of {list(VALID_FRAMES)}"}

        try:
            if mgr is not None:
                model = mgr.model_for_active_chart(frame=frame)
            else:
                # Manager absent (defensive): build directly, same producer.
                from core.hd_model import (
                    build_hd_model, hd_frame_for, HD_EXPERIENCE_KEY)
                if frame is not None:
                    use_frame = frame
                else:
                    # the HD page's own rule (HDManager.frame)
                    from managers.settings_manager import get_settings
                    use_frame = hd_frame_for(
                        getattr(self._window.state, "aditya_mode", None),
                        get_settings().get(HD_EXPERIENCE_KEY, _registry_default(HD_EXPERIENCE_KEY)))
                model = build_hd_model(chart.context, use_frame)
        except Exception as e:
            return {"ok": False, "reason": f"build_hd_model raised {e!r}"}

        if model is None:
            return {"ok": False, "reason": "no chart loaded"}
        return {"ok": True, "model": model, "errors": errors}

    @command("read_elements", category="reading",
             description="Element (Fire/Earth/Air/Water) and modality balance, mode-aware (passes window.state.aditya_mode to dominant.py)")
    def read_elements(self) -> dict:
        chart = self._window.state.active_chart
        if chart is None:
            return {"ok": False, "reason": "no chart loaded"}

        mode = getattr(self._window.state, "aditya_mode", "aditya") or "aditya"
        # ayanamsa_offset is only meaningful for sidereal; harmless 0.0 elsewhere
        ayanamsa_offset = getattr(self._window, "chart_ayanamsa_offset", 0.0) or 0.0

        from AI_tools.AI_main_function.dominant import (
            get_dominant_elements, get_dominant_modality,
        )

        # CRITICAL: pass mode explicitly (P-005 — function defaults to "aditya"
        # which gives wrong counts when user is in Tropical Classic or Sidereal).
        elem_data = get_dominant_elements(
            chart, mode=mode, ayanamsa_offset=ayanamsa_offset
        )
        # get_dominant_modality has no ayanamsa_offset param (treats sidereal
        # as classic internally). Still pass mode so Tropical → classic
        # rather than silently falling back to aditya.
        mod_data = get_dominant_modality(chart, mode=mode)

        elements = {}
        elem_counts = elem_data.get("element_counts", {}) or {}
        for elem_name in ("Fire", "Earth", "Air", "Water"):
            entries = elem_counts.get(elem_name, []) or []
            elements[elem_name] = {
                "count": len(entries),
                "planets": [p for p, _sign in entries],
            }
        dom_elems = elem_data.get("dominant_elements") or []
        dominant_element = dom_elems[0][0] if dom_elems else None

        modality = {}
        mod_counts = mod_data.get("modality_counts", {}) or {}
        for mod_name in ("Moveable", "Fixed", "Dual"):
            entries = mod_counts.get(mod_name, []) or []
            modality[mod_name] = {
                "count": len(entries),
                "planets": [p for p, _sign in entries],
            }
        dom_mods = mod_data.get("dominant_modalities") or []
        dominant_modality = dom_mods[0][0] if dom_mods else None

        return {
            "ok": True,
            "mode": mode,
            "elements": elements,
            "modality": modality,
            "dominant_element": dominant_element,
            "dominant_modality": dominant_modality,
        }

    @command("read_aspects", category="reading",
             description="Tajika aspects between planets; field names match the Tajika API (body1/body2, virupas, applying_status)")
    def read_aspects(self, orb: float = 12.0) -> dict:
        chart = self._window.state.active_chart
        if chart is None:
            return {"ok": False, "reason": "no chart loaded"}

        from AI_tools.AI_main_function.tajika import calculate_all_tajika_aspects
        tajika = calculate_all_tajika_aspects(chart, include_minor=False)

        try:
            orb_limit = float(orb)
        except (TypeError, ValueError):
            orb_limit = 12.0

        raw_aspects = tajika.get("aspects_within_orb") or []
        aspects = []
        for a in raw_aspects:
            # Post-filter: Tajika already applied per-planet Deeptamsa orbs;
            # `orb` parameter tightens further by distance_from_exact.
            dfe = a.get("distance_from_exact")
            if dfe is not None and float(dfe) > orb_limit:
                continue
            aspects.append({
                "body1": a.get("body1"),
                "body2": a.get("body2"),
                "aspect": a.get("aspect"),
                "exact_angle": a.get("exact_angle"),
                "distance_from_exact": dfe,
                "orb_used": a.get("orb_used"),
                "virupas": a.get("virupas"),
                "relationship": a.get("relationship"),
                "applying_status": a.get("applying_status"),
            })

        return {"ok": True, "aspects": aspects}

    def _compare_planets_parity(self, chart, cli_data) -> tuple:
        """Compare live chart planets against CLI extraction. Returns (matches, mismatches)."""
        matches = 0
        mismatches = []

        try:
            rashi = chart.rashi()
            gui_planets = rashi.planets()
        except Exception:
            return 0, [{"field": "planets",
                        "gui_value": None,
                        "cli_value": "<cli extracted>",
                        "severity": "missing"}]

        # libaditya's Planets container defines __iter__ over planet OBJECTS
        # and no __contains__, so `"Sun" in gui_planets` fell back to
        # iteration and compared a string against Planet instances — False
        # for every planet. The comparator therefore reported all nine as
        # "missing" and only ever really compared the house cusps. Anything
        # exposing .items() (dict or container) becomes a name->planet dict.
        try:
            gui_planets = dict(gui_planets.items())
        except AttributeError:
            gui_planets = dict(gui_planets or {})

        cli_planets = (cli_data.get("planets") or {})

        for name, cli_p in cli_planets.items():
            if name not in gui_planets:
                mismatches.append({
                    "field": f"{name}",
                    "gui_value": None,
                    "cli_value": (cli_p.get("aditya") or {}).get("sign"),
                    "severity": "missing",
                })
                continue

            gui_p = gui_planets[name]
            cli_aditya = cli_p.get("aditya") or {}
            cli_trop = cli_p.get("tropical") or {}

            # Sign name comparison (IAST-normalized, case-insensitive)
            try:
                gui_sign_name = gui_p.sign_name()
            except Exception:
                gui_sign_name = None
            cli_sign_name = cli_aditya.get("sign")
            gui_norm = self._normalize_sign_name(gui_sign_name)
            cli_norm = self._normalize_sign_name(cli_sign_name)
            if gui_norm and cli_norm and gui_norm == cli_norm:
                matches += 1
            else:
                # Distinguish data error (different sign) vs cosmetic (same sign, different name)
                try:
                    gui_sign_idx = int(gui_p.sign()) - 1
                except Exception:
                    gui_sign_idx = None
                # CLI ascendant uses 'sign_number' nowhere on planets; sign_index only via name match.
                severity = "data" if gui_norm != cli_norm else "cosmetic"
                mismatches.append({
                    "field": f"{name}.sign_name",
                    "gui_value": gui_sign_name,
                    "cli_value": cli_sign_name,
                    "severity": severity,
                })

            # Longitude comparison (tropical, raw ecliptic — both sources agree on this)
            try:
                gui_lon = float(gui_p.ecliptic_longitude()) % 360.0
            except Exception:
                gui_lon = None
            cli_lon = cli_trop.get("longitude")
            if cli_lon is not None:
                try:
                    cli_lon_f = float(cli_lon) % 360.0
                except (TypeError, ValueError):
                    cli_lon_f = None
            else:
                cli_lon_f = None

            if gui_lon is not None and cli_lon_f is not None:
                if abs(gui_lon - cli_lon_f) <= 0.001:
                    matches += 1
                else:
                    mismatches.append({
                        "field": f"{name}.longitude",
                        "gui_value": round(gui_lon, 6),
                        "cli_value": round(cli_lon_f, 6),
                        "severity": "data",
                    })
            elif cli_lon is None:
                mismatches.append({
                    "field": f"{name}.longitude",
                    "gui_value": gui_lon,
                    "cli_value": None,
                    "severity": "missing",
                })

        return matches, mismatches

    def _compare_houses_parity(self, chart, cli_data) -> tuple:
        """Compare cusp longitudes. Returns (matches, mismatches)."""
        matches = 0
        mismatches = []

        try:
            cusps = chart.rashi().cusps()
        except Exception:
            return 0, [{"field": "houses",
                        "gui_value": None,
                        "cli_value": "<cli extracted>",
                        "severity": "missing"}]

        cli_cusps = (cli_data.get("house_cusps") or {})
        for h in range(1, 13):
            key = f"House_{h}"
            cli_entry = cli_cusps.get(key)
            try:
                gui_cusp_lon = float(cusps[h].ecliptic_longitude()) % 360.0
            except Exception:
                gui_cusp_lon = None

            if cli_entry is None:
                if gui_cusp_lon is not None:
                    mismatches.append({
                        "field": f"{key}.cusp_longitude",
                        "gui_value": round(gui_cusp_lon, 6),
                        "cli_value": None,
                        "severity": "missing",
                    })
                continue

            cli_lon = cli_entry.get("cusp_longitude")
            try:
                cli_lon_f = float(cli_lon) % 360.0 if cli_lon is not None else None
            except (TypeError, ValueError):
                cli_lon_f = None

            if gui_cusp_lon is None or cli_lon_f is None:
                mismatches.append({
                    "field": f"{key}.cusp_longitude",
                    "gui_value": gui_cusp_lon,
                    "cli_value": cli_lon,
                    "severity": "missing",
                })
                continue

            # The CLI publishes cusps rounded to 2 decimals, so 0.005 deg
            # (18 arcsec) is the finest comparison that carries information.
            # At the old 0.001 tolerance, 10 of 12 houses on a byte-perfect
            # chart reported as "data" mismatches — the gate was measuring
            # the CLI's own quantization, not a divergence.
            if abs(gui_cusp_lon - cli_lon_f) <= _CUSP_PARITY_TOLERANCE_DEG:
                matches += 1
            else:
                mismatches.append({
                    "field": f"{key}.cusp_longitude",
                    "gui_value": round(gui_cusp_lon, 6),
                    "cli_value": round(cli_lon_f, 6),
                    "severity": "data",
                })

        return matches, mismatches

    # ===================================================================
    # 5.13c Dasha Reading Layer (SPEC-REM-002 Wave 3)
    # ===================================================================
    #
    # Panel semantics (matching SPEC-REM-002 §5.2 to avoid terminology clash
    # with the older `set_dasha_type` which uses system names directly):
    #   panel="left" / "right" → that dasha panel in its current mode
    #   (SPEC-DSH-004: both offer every mode; `system` keeps "vedanga" for the
    #   left in Vimshottari, `mode` carries the registry key).
    #
    # Both commands are intentionally defensive: a partially-built window,
    # a chart with broken dasha data, or a Qt accessor that raises will all
    # produce a structured response with an "errors" list rather than
    # crashing the AI caller.

    _VALID_KARAKAS = ("AK", "AmK", "BK", "MK", "PiK", "GK", "DK")

    @staticmethod
    def _depth_from_indent(indent) -> int:
        """Return 1-based depth from a dasha entry's indent field.

        SPEC-ZR-001 DD7: Zodiacal Releasing carries ``indent`` as an INT
        (``level - 1``, one level listed at a time), so an int maps directly
        to ``indent + 1``. This MUST be the first check: the string path
        ``len("2") // 2 + 1`` would otherwise report level 1 for every ZR row.

        Vedanga / Vimshottari indent each sub-level with a 2-space string
        prefix (see ``VimshottariSideController.update``),
        so ``len(indent) // 2`` gives a 0-based depth shifted to 1-based. An
        empty / missing indent maps to level 1.
        """
        try:
            if isinstance(indent, int):
                return indent + 1
            return (len(str(indent)) // 2) + 1
        except Exception:
            return 1

    @staticmethod
    def _start_iso(jd, cycle_offset=0):
        """Derive a period's ISO start date from its JD (td-okit c0-2).

        The displayed `date` text is now a user-configurable field order
        (display.date_format), so it can no longer be parsed for an ISO date.
        The JD is the single source of truth; the 120-year cycle offset that the
        panel applies to the DISPLAYED year is applied here too so the ISO
        reflects the row the user sees. Returns None on failure.
        """
        if jd is None:
            return None
        try:
            from core.time_utils import display_revjul
            y, m, d, _h = display_revjul(float(jd))
            return f"{int(y) + cycle_offset * 120:04d}-{int(m):02d}-{int(d):02d}"
        except Exception:
            return None

    @staticmethod
    def _jd_to_iso(jd):
        """Convert a Julian Day (UTC) to ISO date. Returns None on failure.

        Lazy-imports pyswisseph to avoid a hard dependency in unit tests
        and on environments where ephe data is not yet wired up.
        """
        if jd is None:
            return None
        try:
            from libaditya import swe  # type: ignore
        except Exception:
            # td-tagx.8: swapped from `import swisseph`. This guard now also
            # covers a failure anywhere in libaditya's package-level import
            # chain (constants/utils/read/write), not just pyswisseph absence.
            return None
        try:
            jd_f = float(jd)
        except (TypeError, ValueError):
            return None
        try:
            # Gregorian flag (1) for any modern dasha period; pre-1582 dates
            # in the dasha tree are vanishingly rare and the AI caller can
            # always fall back to inspecting display_text for those.
            y, m, d, _h = swe.revjul(jd_f, 1)
            return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
        except Exception:
            return None

    def _dasha_combos(self, panel):
        """Return (karaka_combo, cusp_combo, ws_combo, panel_key) for a panel.

        w3-2 (SPEC-DSH-002): the combos now live on the DashaPanelWidget
        (gui.vedanga_panel / gui.vimshottari_panel). A missing panel yields three
        Nones, exactly as the old per-name getattr default did — SPEC-REM-002 and
        the per-combo error list are unchanged."""
        if panel in ("left", "right"):
            p = getattr(self._window,
                        "vedanga_panel" if panel == "left" else "vimshottari_panel", None)
            return (
                getattr(p, "karaka_combo", None),
                getattr(p, "cusp_combo", None),
                getattr(p, "ws_combo", None),
                panel,          # SPEC-DSH-004: the manager takes the side
            )
        raise ValueError(
            f"Invalid panel {panel!r}; must be 'left' or 'right'"
        )

    def _read_dasha_highlight_state(self, panel) -> dict:
        """Snapshot the karaka/cusp/house combo selections for a panel."""
        karaka_combo, cusp_combo, ws_combo, _ = self._dasha_combos(panel)

        def _read(combo):
            if combo is None:
                return None
            try:
                return combo.currentData()
            except Exception:
                return None

        return {
            "karaka": _read(karaka_combo),
            "cusp": _read(cusp_combo),
            "house": _read(ws_combo),
        }

    def _periods_from_rows(self, displayed_rows, cycle_offset=0) -> list:
        """Normalize displayed_rows into the spec's `periods` array.

        Filters out separator / notice rows that have no `lord` field.
        Each kept row becomes {level, ruler, start, end, display_text,
        is_current}. `start` is derived from the entry's `jd` (+ the panel's
        120-year cycle offset), independent of the displayed date format; `end`
        from `end_jd` if present, else None.
        """
        periods = []
        for r in displayed_rows:
            if not isinstance(r, dict):
                continue
            if r.get("is_separator"):
                continue
            lord = r.get("lord")
            if not lord:
                # Nisarga has text-only rows (e.g. maturation header) and
                # any leftover notice rows from the QListWidget. Skip those.
                continue
            periods.append({
                "level": self._depth_from_indent(r.get("indent", "")),
                "ruler": lord,
                "start": self._start_iso(r.get("jd"), cycle_offset),
                "end": self._jd_to_iso(r.get("end_jd")),
                "display_text": r.get("display_text", ""),
                "is_current": bool(r.get("is_current", False)),
            })
        return periods

    @command("read_dasha", category="reading",
             description="Snapshot the current dasha period chain (panel='left'=Vedanga, 'right'=Vimshottari/Nisarga). Returns periods, displayed_rows, highlight_state, errors. Defensively handles broken dasha data.")
    def read_dasha(self, panel: str = "right", level: int = None) -> dict:
        if panel not in ("left", "right"):
            raise ValueError(
                f"Invalid panel {panel!r}; must be 'left' or 'right'"
            )
        if level is not None:
            try:
                level_int = int(level)
            except (TypeError, ValueError):
                raise ValueError(f"Invalid level {level!r}; must be 1-5")
            if not (1 <= level_int <= 5):
                raise ValueError(f"Invalid level {level!r}; must be 1-5")
        else:
            level_int = None

        errors: list[str] = []
        dm = getattr(self._window, "dasha_manager", None)
        if dm is None:
            return {
                "ok": False,
                "reason": "no dasha_manager available on window",
            }

        # Resolve which system this panel currently shows. Done BEFORE
        # any level switch because Nisarga vs Vimshottari uses different
        # set_*_level methods.
        try:
            system = dm.get_current_system(panel)
        except Exception as e:
            system = "unknown"
            errors.append(f"get_current_system({panel!r}) raised {e!r}")

        # Optional level switch, mode-routed on the panel's side; the max level
        # is the mode's (SPEC-DSH-004 registry: ZR 4, others 5). A level past it
        # is reported, never silently clamped (W6 review MINOR 7).
        if level_int is not None:
            try:
                from managers.dasha.modes import mode_spec
                spec = mode_spec(dm.mode(panel))
                if not (1 <= level_int <= spec.levels):
                    errors.append(
                        f"{spec.label} has levels 1-{spec.levels}, not {level_int}")
                else:
                    dm.set_level(panel, level_int)
            except Exception as e:
                errors.append(
                    f"set level {level_int} for panel={panel!r}, system={system!r} "
                    f"raised {e!r}"
                )

        # Read current level after any switch
        try:
            current_level = dm.get_current_level(panel)
        except Exception as e:
            current_level = None
            errors.append(f"get_current_level({panel!r}) raised {e!r}")

        # Snapshot the QListWidget
        try:
            displayed_rows = dm.get_displayed_rows(panel)
        except Exception as e:
            displayed_rows = []
            errors.append(f"get_displayed_rows({panel!r}) raised {e!r}")

        # The panel's 120-year cycle offset (Vimshottari-family only; Nisarga
        # and ZR have no cycling). read_dasha derives ISO `start` from jd + this.
        try:
            cycle_offset = (dm.cycle_offset(panel)
                            if dm.mode(panel) == "vimshottari" else 0)
        except Exception:
            cycle_offset = 0
        # Only a genuine int counts (a mock window's attribute is not one, and
        # MagicMock.__int__ would otherwise coerce to 1).
        if not isinstance(cycle_offset, int) or isinstance(cycle_offset, bool):
            cycle_offset = 0

        # Build normalized periods array (filters separators / notice rows)
        try:
            periods = self._periods_from_rows(displayed_rows, cycle_offset)
        except Exception as e:
            periods = []
            errors.append(f"_periods_from_rows raised {e!r}")

        # Highlight combo state
        try:
            highlight_state = self._read_dasha_highlight_state(panel)
        except Exception as e:
            highlight_state = {"karaka": None, "cusp": None, "house": None}
            errors.append(f"_read_dasha_highlight_state raised {e!r}")

        # Current date for the AI's "what period are we in?" reasoning
        try:
            from datetime import date as _date
            current_date = _date.today().isoformat()
        except Exception:
            current_date = None

        result = {
            "ok": True,
            "panel": panel,
            "system": system,
            # SPEC-DSH-004 D-7: the registry key (system keeps "vedanga" for the
            # left Vimshottari, its legacy wire value).
            "mode": (dm.mode(panel) if hasattr(dm, "mode") else None),
            "level": current_level,
            "periods": periods,
            "displayed_rows": displayed_rows,
            "highlight_state": highlight_state,
            "current_date": current_date,
        }
        if errors:
            result["errors"] = errors
        return result

    @command("set_dasha_highlight", category="dasha",
             description="Set karaka/cusp/house highlight combos on a dasha panel. Pass null to clear an individual highlight. Triggers refresh_dasha_lord_highlights().")
    def set_dasha_highlight(self, panel: str, karaka=None, cusp=None,
                            house=None) -> dict:
        if panel not in ("left", "right"):
            raise ValueError(
                f"Invalid panel {panel!r}; must be 'left' or 'right'"
            )
        if karaka is not None and karaka not in self._VALID_KARAKAS:
            raise ValueError(
                f"Invalid karaka {karaka!r}; must be null or one of "
                f"{list(self._VALID_KARAKAS)}"
            )
        if cusp is not None:
            try:
                cusp_int = int(cusp)
            except (TypeError, ValueError):
                raise ValueError(f"Invalid cusp {cusp!r}; must be null or 1-12")
            if not (1 <= cusp_int <= 12):
                raise ValueError(f"Invalid cusp {cusp!r}; must be null or 1-12")
            cusp = cusp_int
        if house is not None:
            try:
                house_int = int(house)
            except (TypeError, ValueError):
                raise ValueError(f"Invalid house {house!r}; must be null or 1-12")
            if not (1 <= house_int <= 12):
                raise ValueError(f"Invalid house {house!r}; must be null or 1-12")
            house = house_int

        karaka_combo, cusp_combo, ws_combo, panel_key = self._dasha_combos(panel)
        errors: list[str] = []

        def _set_combo(combo, value, label):
            if combo is None:
                errors.append(f"{label} combo not available")
                return False
            try:
                idx = combo.findData(value)
            except Exception as e:
                errors.append(f"{label}.findData({value!r}) raised {e!r}")
                return False
            if idx < 0:
                # Value not in combo; fall back to index 0 (None) so the
                # combo is left in a coherent state.
                errors.append(
                    f"{label} value {value!r} not found in combo; resetting to None"
                )
                idx = 0
            try:
                combo.setCurrentIndex(idx)
            except Exception as e:
                errors.append(f"{label}.setCurrentIndex({idx}) raised {e!r}")
                return False
            return True

        _set_combo(karaka_combo, karaka, "karaka")
        _set_combo(cusp_combo, cusp, "cusp")
        _set_combo(ws_combo, house, "house")

        # The combo's currentIndexChanged signal already fires
        # refresh_dasha_lord_highlights, but we call it explicitly in case
        # programmatic setCurrentIndex(same_idx) didn't emit (Qt suppresses
        # the signal when the value is unchanged).
        dm = getattr(self._window, "dasha_manager", None)
        if dm is not None and hasattr(dm, "refresh_dasha_lord_highlights"):
            try:
                dm.refresh_dasha_lord_highlights(panel_key)
            except Exception as e:
                errors.append(f"refresh_dasha_lord_highlights raised {e!r}")

        result = {
            "ok": True,
            "panel": panel,
            "karaka": karaka,
            "cusp": cusp,
            "house": house,
        }
        if errors:
            result["errors"] = errors
        return result

    # ===================================================================
    # 5.14 Command Listing
    # ===================================================================

    @command("list_commands", category="state",
             description="List all available commands with parameters")
    def list_commands(self) -> dict:
        commands = []
        for name, entry in sorted(_REGISTRY.items()):
            param_list = []
            for p in entry.params:
                type_name = getattr(p.type, "__name__", str(p.type))
                param_list.append({"name": p.name, "type": type_name})
            commands.append({
                "name": name,
                "params": param_list,
                "description": entry.description,
                "category": entry.category,
            })
        return {"commands": commands}
