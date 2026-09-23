"""managers/hd_manager.py — Human Design BodyGraph view lifecycle (SPEC-HD-001 §8, WI-6).

The HD page (chart-stack index 5) reads its model from here, so the GUI view,
the remote ``read_human_design`` command and the ``show_human_design`` CLI all
consume the ONE producer, ``core.hd_model.build_hd_model``, and cannot diverge
(INV-1, the four-surface parity gate).

Rule 4b: this manager owns the HD model state and NEVER writes ``gui.*`` — it
reads ``gui.state.active_chart`` (whose ``.context`` is the exact birth instant
the CLI also loads) and caches its own model. When a manager owns a piece of
state, the GUI mutates it through this API, not through a new ChartGUI attribute.

Lifecycle:
  * ``model_for_active_chart()`` builds and memoises the model for the loaded
    chart in the resolved frame. Byte-identical to the CLI because both feed the
    same ``chart.context`` / jd into ``build_hd_model``.
  * ``frame()`` derives the frame from the app zodiac mode (``state.aditya_mode``);
    anything absent or unrecognised falls back to Standard, the locked default.
    The HD page has no frame control of its own (C7) — it follows the top-bar
    zodiac buttons and recomputes on ``aditya_mode_changed``.
  * ``refresh_active_view()`` is the one-line delegation target the chart-change
    path calls: it invalidates the cache and, only if the HD page is the current
    view, pushes the fresh model — so a chart swap behind another view costs
    nothing until HD is shown.
  * ``clear()`` / ``on_hide()`` invalidate the cache and stop any per-view timer
    (the mature view owns its own clock; nothing to stop here yet).
"""
from __future__ import annotations

from core.hd_model import build_hd_model, VALID_FRAMES

_DEFAULT_FRAME = "standard"

# The HD gate-1 frame is GATED behind a Human Design experience level
# (Settings, mirroring the Zodiac one; Lorris post-C7):
#   * Beginner (default, locked): the page is PINNED to Standard (Tropical
#     Classic) whatever the top-bar zodiac buttons say. Most people, including
#     astrology specialists, find Standard the better Human Design frame; the
#     other frames are there to test, not the default.
#   * Advanced (unlocked): the top-bar Aditya/Sidereal/Tropical buttons drive
#     the HD frame too, like every other view. aditya -> 193.25,
#     tropical_classic -> the Standard HD anchor, sidereal -> app ayanamsa.
# So clicking Aditya/Sidereal always retargets the MAIN chart, but only
# retargets the HD page when the user has opted into Advanced.
_HD_EXPERIENCE_KEY = "ui.hd_experience_level"
_MODE_TO_FRAME = {
    "aditya": "aditya",
    "tropical_classic": "standard",
    "sidereal": "sidereal",
}
_FRAME_TO_MODE = {v: k for k, v in _MODE_TO_FRAME.items()}   # inverse (C9)


def _hd_is_advanced() -> bool:
    """True when the user unlocked Advanced Human Design (pills drive the frame).

    Defaults to Beginner (False) whenever the setting is absent or the settings
    store cannot be read, so the page stays pinned to Standard by default.
    """
    try:
        from managers.settings_manager import get_settings
        return get_settings().get(_HD_EXPERIENCE_KEY, "beginner") == "advanced"
    except Exception:
        return False


class HDManager:
    """Owns the Human Design model for the active chart (see module docstring)."""

    def __init__(self, gui):
        self._gui = gui
        self._model = None
        self._key = None            # (id(chart), frame) the cached model is for

    # ---- frame resolution (C7: derived from the app zodiac mode) ---------------
    def frame(self) -> str:
        """The gate-1 frame, derived from the app zodiac mode (state.aditya_mode).

        aditya -> "aditya", tropical_classic -> "standard", sidereal -> "sidereal";
        In Beginner mode (default) it is pinned to Standard; in Advanced mode it
        follows the top-bar zodiac buttons, recomputing on ``aditya_mode_changed``.
        An absent/unknown mode falls back to Standard (the locked default). The remote/CLI stay in parity: the
        remote reads this (frame=None -> mode), the CLI keeps an explicit --frame.
        """
        if not _hd_is_advanced():
            # Beginner (default, locked): pinned to Standard regardless of the
            # top-bar zodiac buttons.
            return _DEFAULT_FRAME
        try:
            mode = self._gui.state.aditya_mode
        except Exception:
            return _DEFAULT_FRAME
        return _MODE_TO_FRAME.get(mode, _DEFAULT_FRAME)

    def design_chart_mode(self) -> str:
        """The zodiac MODE the -88 Design astrology chart renders in — the SAME
        gate as frame() (one resolver for both HD views), mapped back to a zodiac
        mode. Beginner -> "tropical_classic" (Standard); Advanced -> the app
        zodiac mode. Never mutates state.aditya_mode (the pills keep controlling
        the MAIN chart), exactly like frame() for the bodygraph."""
        return _FRAME_TO_MODE.get(self.frame(), "tropical_classic")

    # ---- model -----------------------------------------------------------------
    def model_for_active_chart(self, frame: str = None):
        """The HDModel dict for the loaded chart, or None if no chart is loaded.

        ``frame`` overrides the settings frame (used by the remote/CLI which pass
        an explicit ``--frame``); an unknown override falls back to Standard.
        """
        chart = getattr(getattr(self._gui, "state", None), "active_chart", None)
        if chart is None:
            return None
        use_frame = frame if frame is not None else self.frame()
        if use_frame not in VALID_FRAMES:
            use_frame = _DEFAULT_FRAME
        key = (id(chart), use_frame)
        if self._key == key and self._model is not None:
            return self._model
        model = build_hd_model(chart.context, use_frame)
        self._model, self._key = model, key
        return model

    # ---- lifecycle -------------------------------------------------------------
    def push_to_view(self):
        """Build the model for the active chart and push it to the HD view.

        The GUI must NEVER crash on a producer failure (a QShortcut slot or a
        chart-load finalizer would take the exception uncaught) — unlike the
        remote command, which catches and reports it. So build_hd_model is
        wrapped here: on failure the view is fed ``None`` (placeholder / real
        view both render an empty "no chart" state), and the app keeps running.
        Returns True iff a real model was shown.
        """
        view = getattr(self._gui, "human_design_view", None)
        if view is None:
            return False
        try:
            model = self.model_for_active_chart()
        except Exception as e:                       # noqa: BLE001 — GUI must not crash
            print(f"[HDManager] build_hd_model failed: {e!r}")
            model = None
        try:
            view.update_from_chart(model)            # None -> empty view, never a Chart
        except Exception as e:                       # noqa: BLE001
            print(f"[HDManager] HD view update failed: {e!r}")
            return False
        return model is not None

    def refresh_active_view(self):
        """Invalidate the cache and re-push the model IFF the HD page is current.

        One-line delegation target for the chart-change / varga path (Rule 4).
        """
        self.clear()
        gui = self._gui
        if getattr(gui, "human_design_view", None) is None:
            return
        try:
            from state.chart_state import VIEW_STACK_INDEX
            if gui.chart_stack.currentIndex() != VIEW_STACK_INDEX["human_design"]:
                return
        except Exception:
            return
        self.push_to_view()

    def clear(self):
        """Drop the cached model (called when the active chart changes)."""
        self._model = None
        self._key = None

    def on_hide(self):
        """Stop any per-view timer when the HD page is hidden.

        The mature view (WI-4/5) runs its animation clock only while visible via
        its own showEvent/hideEvent, so there is nothing for the manager to stop
        yet; the hook exists so the lifecycle contract is complete and the GUI
        can call it unconditionally.
        """
        return None
