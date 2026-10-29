# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""A setting changed outside the Settings pages reaches the screen at once
(AI setting redesign, td-bztjj, item 3; SPEC-SET-003 §4.5b).

ONE function, two callers: the in-app request service
(``managers/app_settings_requests.AppSettingsRequests._notify``) and the Pro
remote ``set_setting`` (``pro/remote_control.py``). ``window_tail(gui, key)``
returns what the window runs after the value is saved, in the same live-frame
publication batch as before (W5):

- the shared tail every caller already ran: the Chart Display tail
  (``apply_chart_display_settings``) for the Chart Display family, the zodiac
  settings flush, the dasha reconciliation;
- plus the family's own live apply, the same call its Settings page makes:
  fonts (``set_area_font_size`` then ``_on_font_sizes_changed``), the display
  scale (``set_scale_factor`` then ``_on_scale_changed``), the colour
  saturation (``_on_saturation_changed``), the theme (its stored NAME mapped to
  the theme FILE, as ``remote_control.set_theme``) and the deeper dark
  background, reduce motion, the typed display sections' leaves (planet
  sizes, sign shadows: the views that read the section re-read it and
  redraw, ``_reload_chart_views``), and the GUI-action keys (the
  Trimsamsha degrees through the Chart Display tail, the Tropical rim and the
  divisional chart beside the main chart through their own toggles).

Keys read only at startup (``STARTUP_ONLY``) change nothing on screen now:
``applies_at_next_start`` says so and the service puts it in its reply's
machine field (``applies: next_start``).

No state of its own and no ``ChartGUI`` attribute written (Rule 4b): it
calls the window's existing handlers.
"""
from __future__ import annotations

import logging
import weakref
from typing import Any, Callable, Tuple

_log = logging.getLogger(__name__)

# One font refresh per burst of font-area changes (td-8m3kd). The window's
# font refresh (``_on_font_sizes_changed``) restyles every surface, the same
# pass a Settings > Font Sizes Apply makes once for all its areas. An AI turn
# changes its areas one request at a time ("the menu and the chart names
# smaller": two requests), and a refresh per request made the second request
# queue behind the first refresh, then run a second one: 87-101 s on screen
# at load 29 for a 7-10 s model turn. Each area's size is set at once; the
# refresh waits FONT_REFRESH_QUIET_MS after the latest font change (the next
# request of the same turn arrives within it), never longer than
# FONT_REFRESH_MAX_MS after the first, then runs once for all of them.
FONT_REFRESH_QUIET_MS = 300
FONT_REFRESH_MAX_MS = 1200
_font_refresh = weakref.WeakKeyDictionary()     # window -> (QTimer, first ms)
# The clock alone misses a real AI turn (review 2026-10-13 H6): its tool
# calls are separated by the model's own generation time, often longer than
# the quiet wait, so a two-area turn ran two full refresh passes. While the
# AI setting panel's turn runs it HOLDS the window's font refresh
# (``hold_font_refresh``); the font changes of the turn only mark it due, and
# the turn's end (``release_font_refresh``) runs it once. The timer stays for
# the callers that have no turn (the Pro remote, the endpoint used alone).
_font_hold = weakref.WeakKeyDictionary()        # window -> [holds, refresh due]

# Read once when the app starts (no live reader): the change shows at the
# next start.
STARTUP_ONLY = frozenset((
    "ui.action_bar_v2",             # SPEC-BAR-001 D-15: the bar is built once
    "ui.restore_last_tab",          # read at startup
    "windows.remember_geometry",    # read at startup and exit
    "defaults.auto_restore_session",  # read at startup
    "ai.capture_hotkey",            # the shortcut is bound at startup
))
# Keys the Chart Display tail adopts though its page does not host them.
_CHART_TAIL_EXTRA = frozenset(("chart.show_trimsamsha_degrees",
                               "chart_display.house_number.font_size"))
# Typed sections whose leaves the chart views read at draw time.
_CHART_SECTIONS = ("chart_display", "south_indian_display", "wheel_display",
                   "north_indian_display")


def applies_at_next_start(key: str) -> bool:
    return key in STARTUP_ONLY


def chart_tail_keys() -> frozenset:
    """The keys whose change needs the Chart Display tail
    (``apply_chart_display_settings``): the page's own allowlists (as the
    Pro remote ``set_setting`` builds them, td-iaqm.2.1) and the two
    documented extras."""
    from ui.settings_tab import ChartDisplaySection as _CDS
    return frozenset({f"chart.{k}" for k in _CDS.OWNED_CHART_KEYS}
                     | {f"display.{k}" for k in _CDS.OWNED_DISPLAY_KEYS}
                     | _CHART_TAIL_EXTRA)


def needs_chart_tail(key: str) -> bool:
    try:
        if key in chart_tail_keys():
            return True
    except Exception:                                       # pragma: no cover
        pass
    head = key.split(".", 1)[0]
    return head in _CHART_SECTIONS


def _value(key: str) -> Any:
    from core import settings_registry as registry
    from managers.settings_manager import get_settings
    default = registry.default(key) if registry.has(key) else None
    return get_settings().get(key, default)


def _reload_chart_views(gui, section: str) -> None:
    """The chart views that read ``section`` re-read it and redraw: the
    Chart Display tail repaints them but never reloads a typed section (the
    Wheel and North Indian pages call their view's ``reload_display_settings``;
    no page hosts the South Indian ones)."""
    if section in ("wheel_display", "north_indian_display"):
        names = (("wheel_view", "nakshatra_wheel_view") if section == "wheel_display"
                 else ("north_indian_view",))
        for name in names:
            view = getattr(gui, name, None)
            if view is not None and hasattr(view, "reload_display_settings"):
                view.reload_display_settings()
        return
    # chart_display: the classic South Indian view; south_indian_display: the
    # vector one. Every live South Indian host (main view, dual chart, panels).
    from apps.widgets import south_indian_vector_view as siv
    for host in list(siv._LIVE_HOSTS):
        try:
            if section == "south_indian_display":
                host.vector_view.display_settings = None     # the setter re-reads it
            else:
                host.classic_view.reload_display_settings()
            host.draw_full_chart()
        except RuntimeError:                                # deleted host
            continue


def _family_apply(gui, key: str) -> None:
    """The live apply of ``key``'s family (the call its Settings page makes)."""
    head = key.split(".", 1)[0]
    if head in _CHART_SECTIONS:
        _reload_chart_views(gui, head)
    elif key.startswith("display.fonts."):
        from ui.qt_theme import set_area_font_size
        set_area_font_size(key.rsplit(".", 1)[1], int(_value(key)))
        queue_font_refresh(gui)
    elif key == "display.font_scale":
        from ui.qt_theme import set_scale_factor
        factor = float(_value(key))
        set_scale_factor(factor)
        gui._on_scale_changed(factor)
    elif key == "display.color_saturation":
        gui._on_saturation_changed(int(_value(key)))
    elif key in ("appearance.theme", "appearance.deep_dark"):
        from ui.qt_theme import set_deep_dark
        from ui.themes import THEME_NAME_TO_FILE
        set_deep_dark(bool(_value("appearance.deep_dark")))
        theme_file = THEME_NAME_TO_FILE.get(_value("appearance.theme"))
        if theme_file:              # already saved: re-apply only, write nothing
            gui._on_theme_changed(theme_file, persist=False)
    elif key == "ui.reduce_motion":
        import os
        if "V360_BAR_MOTION" not in os.environ:
            from apps.widgets.action_bar import motion
            motion.set_mode(motion.Mode.REDUCED if _value(key) else motion.Mode.LIVE)
            bar = getattr(gui, "chart_title_widget", None)
            if bar is not None and hasattr(bar, "snap_motion"):
                bar.snap_motion()
    elif key == "chart.show_tropical_rim":
        if bool(getattr(gui, "show_tropical_rim", False)) != bool(_value(key)):
            gui._toggle_dual_rim()
    elif key == "display.varga_in_center":
        wanted = bool(_value(key))
        button = getattr(gui, "varga_center_button", None)
        if button is not None:
            # through the button, so its checked state, the flag and the
            # saved value never disagree (as remote set_varga_in_center)
            if button.isChecked() != wanted:
                button.setChecked(wanted)
        elif bool(getattr(gui, "varga_in_center", False)) != wanted:
            gui._toggle_varga_in_center(wanted)


def queue_font_refresh(gui) -> None:
    """Run the window's font refresh once for this burst of font-area
    changes (see FONT_REFRESH_QUIET_MS): a change made while one is queued
    restarts the quiet wait, up to FONT_REFRESH_MAX_MS after the first."""
    from PySide6.QtCore import QElapsedTimer, QTimer
    hold = _font_hold.get(gui)
    if hold is not None:
        hold[1] = True                  # the turn's end runs it (release)
        return
    entry = _font_refresh.get(gui)
    if entry is None:
        timer = QTimer(gui)
        timer.setSingleShot(True)
        clock = QElapsedTimer()

        def fire(_timer=timer, _gui_ref=weakref.ref(gui)):
            target = _gui_ref()
            if target is None:
                return
            _font_refresh.pop(target, None)
            _timer.deleteLater()
            target._on_font_sizes_changed()
        timer.timeout.connect(fire)
        clock.start()
        entry = _font_refresh[gui] = (timer, clock)
    timer, clock = entry
    wait = min(FONT_REFRESH_QUIET_MS, max(0, FONT_REFRESH_MAX_MS - clock.elapsed()))
    timer.start(wait)


def hold_font_refresh(gui) -> None:
    """An AI turn starts: font changes wait for ``release_font_refresh``. A
    refresh already queued by the clock joins the turn's one."""
    hold = _font_hold.get(gui)
    if hold is None:
        hold = _font_hold[gui] = [0, False]
        entry = _font_refresh.pop(gui, None)
        if entry is not None:
            entry[0].stop()
            entry[0].deleteLater()
            hold[1] = True
    hold[0] += 1


def release_font_refresh(gui) -> None:
    """The AI turn ended (finished, stopped or failed): one font refresh for
    every font change the turn made, none when it made none."""
    hold = _font_hold.get(gui)
    if hold is None:
        return
    hold[0] -= 1
    if hold[0] > 0:
        return
    del _font_hold[gui]
    if hold[1] and _alive(gui):
        gui._on_font_sizes_changed()


def _alive(gui) -> bool:
    """The window still exists and was not closed (window_closed route)."""
    try:
        import shiboken6
        if not shiboken6.isValid(gui):
            return False
    except (ImportError, TypeError):
        return True
    zodiac = getattr(gui, "zodiac_settings", None)
    service = getattr(zodiac, "app_requests", None) if zodiac is not None else None
    return not getattr(service, "closed", False)


def window_tail(gui, key: str) -> Tuple[Callable[[], None], Callable[[str], bool]]:
    """``(adopt, owns)`` of a change of ``key`` in the window ``gui``: the
    callable the window runs after the save (the shared tail plus the
    family's live apply) and the publication batch's ownership test (W5-fix4:
    the written key, and the Chart Display family when its tail runs)."""
    chart_tail = needs_chart_tail(key)

    def adopt():
        if chart_tail and hasattr(gui, "apply_chart_display_settings"):
            gui.apply_chart_display_settings()
        zodiac = getattr(gui, "zodiac_settings", None)
        if zodiac is not None:
            zodiac.apply_settings()
        dasha = getattr(gui, "dasha_manager", None)
        if dasha is not None and hasattr(dasha, "_reconcile_pending_settings"):
            dasha._reconcile_pending_settings()
        try:
            _family_apply(gui, key)
        except Exception:
            _log.exception("live apply of %s failed", key)

    def owns(k):
        if k == key:
            return True
        try:
            return chart_tail and k in chart_tail_keys()
        except Exception:                                   # pragma: no cover
            return False

    return adopt, owns


def readopt(gui, keys) -> None:
    """After a refused AI command was put back (``ai_write_hook.ai_writer``'s
    ``on_undone``): the window shows the restored values again, through the
    same tail a change of each key runs (a font area, a theme already applied
    by the command would otherwise stay on screen). Never raises."""
    if gui is None:
        return
    keys = list(dict.fromkeys(keys))

    def run():
        for key in keys:
            try:
                adopt, _owns = window_tail(gui, key)
                adopt()
            except Exception:
                _log.exception("re-adopting %s after a refused AI command failed", key)
    try:
        from PySide6.QtCore import QObject, QTimer
        if isinstance(gui, QObject):
            # after the refusal reply, as _notify defers its tail
            QTimer.singleShot(0, gui, run)
            return
    except ImportError:                                         # pragma: no cover
        pass
    run()
