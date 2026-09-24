#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
ChartGUI - PySide6 Version
Core orchestration layer (Lite foundation). Pro extends via ProChartGUI.
"""
import sys
import faulthandler
faulthandler.enable()  # Print traceback on segfault to stderr
from pathlib import Path

# ====================================================================
# CHECK DEBUG MODE FIRST - before any imports that might consume -d flag
# ====================================================================
# Store ORIGINAL argv before any modifications (needed for restart)
_ORIGINAL_ARGV = sys.argv.copy()

_DEBUG_MODE = '-d' in sys.argv or '--debug' in sys.argv
_LITE_MODE = True  # Hardcoded for Lite distribution

# Licensing is license-KEY only (mobile parity, td-zoc7): the account/sign-in
# model is retired. The desktop holds no account; the user pastes a license key
# copied from their 360heartsinthesky.com account and it is exchanged for a
# signed token (managers/license_key.py, apps/widgets/key_dialog.py). There is
# no email/password or Google sign-in anywhere in the app.


def _is_bundled() -> bool:
    """Whether the license-KEY gate must enforce at launch and mid-run.

    Keyed on state.user_data.is_frozen(), the canonical packaging detector: it
    is True for EVERY packager this app ships with, not just the ones that set
    sys.frozen. PyInstaller and the AppImage set sys.frozen; the macOS build is
    Nuitka --mode=app, which sets NEITHER sys.frozen NOR _MEIPASS and is detected
    via its module-level __compiled__ global instead. Using sys.frozen alone left
    the macOS build ungated. A packaged build ALWAYS enforces and no environment
    change can switch the gate off. VARUNA360_BUNDLED=1 is a source-run opt-in
    that lets a developer test the gate without freezing a binary (opting IN to
    enforcement is harmless). Both main()'s boot gate and the mid-run re-gate
    call this, so the security predicate lives in exactly one place.
    """
    import os
    from state.user_data import is_frozen
    return is_frozen() or \
        os.environ.get("VARUNA360_BUNDLED", "").strip() == "1"

# Remove flags from sys.argv BEFORE importing other modules
if _DEBUG_MODE:
    sys.argv = [arg for arg in sys.argv if arg not in ('-d', '--debug')]
if _LITE_MODE:
    sys.argv = [arg for arg in sys.argv if arg not in ('-l', '--lite')]

import os
import platform

# QtWebEngine (Chromium) flags - MUST be set BEFORE any PySide6/Qt imports
# On Linux + NVIDIA: GBM not supported -> Vulkan loader crashes -> segfault
if platform.system() == "Linux":
    # Disable Vulkan loader (crashes on NVIDIA before GPU process even starts)
    os.environ["VK_ICD_FILENAMES"] = ""
    os.environ["VK_LAYER_PATH"] = ""
    # WebEngine: disable GPU subprocess, run in-process to avoid subprocess crash
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
        "--no-sandbox --disable-gpu --in-process-gpu --disable-gpu-sandbox"
    )
    os.environ["QTWEBENGINE_DISABLE_SANDBOX"] = "1"

from datetime import datetime

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QFileDialog,
    QMessageBox,
    QTabWidget,
    QPushButton,
    QLabel,
    QStackedWidget,
    QSizePolicy,
    QProgressBar,
    QScrollArea,
)
from PySide6.QtCore import (
    QProcess,
    Qt,
    QTimer,
    QSize,
    Signal,
    QPropertyAnimation,
    QEasingCurve,
)
import json
import signal

# qt-material loaded lazily (saves ~58ms at startup, RPI-PERF-B)
_qt_material_apply = None

def _get_apply_stylesheet():
    global _qt_material_apply
    if _qt_material_apply is None:
        try:
            from qt_material import apply_stylesheet
            _qt_material_apply = apply_stylesheet
        except ImportError:
            _qt_material_apply = False
    return _qt_material_apply

from PySide6.QtGui import QAction, QKeySequence, QActionGroup, QColor, QIcon

# Project root for absolute paths
PROJECT_ROOT = Path(__file__).parent.parent

# td-iopy (Wave 5): debounce window for the chart-view persist. A burst of F2
# presses coalesces to one disk write this long after the last switch; a fast
# quit inside the window is caught by the closeEvent flush.
_VIEW_PERSIST_DEBOUNCE_MS = 500

# Add to path for imports
sys.path.insert(0, str(PROJECT_ROOT))

# Import theme functions for styling (must be after sys.path modification)
from ui.qt_theme import get_tab_bar_style, get_theme_colors, scaled_px, scaled_area_px, desat_hex, desat_qss

# Import title formatting from chart_manager
from managers.chart_manager import _format_chart_title

# VARGA_NAMES lives in core.varga_codes (Stage 1d, td-gl6y). This file used to
# carry a second, value-identical copy of the dict; it is imported here instead
# of redefined so `apps.core_gui_qt.VARGA_NAMES` stays a valid re-export and the
# Stage 1d menu-builder mixin can share the one canonical dict without a
# core -> mixin -> core import cycle. core.varga_codes has no GUI deps.
from core.varga_codes import VARGA_NAMES


# Import modular widgets
from apps.widgets.chart_view import SouthIndianView
from apps.widgets.south_indian_vector_view import (
    create_south_indian_view, sync_all_south_indian_hosts)
from apps.widgets.wheel_view import WheelView
from apps.widgets.north_indian_view import NorthIndianView
from apps.widgets.body_aspect_dual_widget import BodyAspectDualWidget
from apps.widgets.cards_of_truth_view import CardsOfTruthView
# SPEC-HD-001 WI-6 import seam: the real Human Design view is built on the
# design branch; until it merges, fall back to the placeholder so page 5 exists
# and the wiring (shortcut/remote/manager/F2-exclusion) is testable now. When
# the real view lands, this seam picks it up with no wiring change.
try:
    # HDPanel is "The Human Design page" (SPEC-HD-001): the graph PLUS its
    # toolbar, the two planet columns and the reading card. It wraps
    # HDBodygraphView (panel.view) and exposes the same update_from_chart(model)
    # + refresh_theme contract, so the manager/activation wiring is unchanged.
    # (The bare HDBodygraphView was the earlier seam target; the :0 harness
    # showed it drops the reading card + columns — mockup 27 is the whole page.)
    from apps.widgets.hd.hd_panel import HDPanel as _HDView
except ImportError:
    # ImportError/ModuleNotFoundError only — the design package is simply not
    # merged yet. A DIFFERENT error inside the real page (once merged) must
    # propagate, not be masked as "still in progress".
    from apps.widgets.hd_view_placeholder import HDViewPlaceholder as _HDView
from apps.widgets.planet_dialog import PlanetInfoDialog
from apps.widgets.sector_dialog import SectorInfoDialog
from core.aditya_data import ADITYA_NAMES
from apps.widgets.debug_console import DebugConsoleWidget
from apps.widgets.planet_placements_dialog import PlanetPlacementsDialog

# Import managers
from managers.chart_manager import ChartManager
from managers.dasha_manager import DashaManager
# Phase 4 W5: panel_update_manager.py moved to trash/. Each of the 12 panels
# now self-updates via state.PanelControllerBase subscriptions. The wrapper
# methods below stay as no-op stubs because chart_memory_panel.py and
# edit_chart_panel.py still call self.gui._update_<panel>() unguarded —
# Phase 5 will migrate them to dispatch SetActiveChart instead.
from managers.loading_manager import LoadingManager
from managers.loading_scope import loading_scope, run_with_loading


# Import panel factory functions
# w3-2 (SPEC-DSH-002): the two dasha panel factories are retired; the panels are
# built by DashaManager.build_panel (one DashaPanelWidget class, two instances).
from apps.panels.info_panels import create_right_panels, relayout_info_panels
from apps.panels.sign_selector_column import (
    create_sign_selector_column,
    refresh_named_lagna,
)
from apps.panels.varga_column import create_varga_column
# NOTE: find_chart_panel import deferred to _create_find_chart_widget() - builds large index
from apps.panels.edit_chart_panel import EditChartPanel

# NOTE: Pro panel imports removed (SPEC-LITE-FOUND-001 s5.1).
# The full version imports them in its own methods.
# NOTE: settings_tab import deferred to _create_settings_widget() - takes 5s+ to create

# SPEC-LITE-001 RPI-A: bridge functions deferred to property bodies (RPI-PERF-B)

# ============================================================================
# MAIN GUI CLASS
# ============================================================================
# Note: DebugConsoleWidget moved to apps/widgets/debug_console.py

# Extracted cluster mixins (god-object decomposition; see
# proprietary_docs/docs/god_object_decomposition/). Move-only, plain-Python.
from apps.gui_mixins.kala_integration import KalaIntegrationMixin
from apps.gui_mixins.keyboard_nav import KeyboardNavMixin
from apps.gui_mixins.side_drawers import SideDrawersMixin
from apps.gui_mixins.app_dialogs import AppDialogsMixin
from apps.gui_mixins.file_ops import FileOpsMixin
from apps.gui_mixins.chart_capture import ChartCaptureMixin
from apps.gui_mixins.profile_menu import ProfileMenuMixin
from apps.gui_mixins.menu_builder import MenuBuilderMixin

import functools
import inspect


def _batched(fn):
    """td-yymp Block 4: run a multi-emit handler inside ONE ChartState batch so
    the panel controllers repaint once at the final state instead of per emit.

    The wrapped handler dispatches several events (e.g. SetZodiacMode then, via
    _recalculate_chart, SetActiveChart); batching buffers the controller refreshes
    across the whole body — the loading-overlay processEvents mid-body has nothing
    batchable scheduled to drain — and replays one coalesced refresh at exit. See
    proprietary_docs/.../BLOCK4_BATCHING_DESIGN.md.

    SIGNATURE-PRESERVING (td-y6kg.12). The wrapper reproduces `fn`'s EXACT
    parameter list via a generated code object, because PySide6/Shiboken decides
    how many arguments to pass a slot by reading the callable's CODE OBJECT — not
    its ``__wrapped__`` or ``__signature__``. A plain ``def wrapper(self, *args,
    **kwargs)`` reads as variadic, so Shiboken passed ZERO positional args and
    silently dropped the ``checked`` bool of ``QAction.triggered`` — the
    Sidereal / Alt+S toggle (``_toggle_sidereal``) raised inside the Qt event
    loop and the mode never switched. ``functools.wraps`` does NOT fix this (it
    copies attributes, not the code object). Verified against a live
    ``QAction.triggered`` probe: the reproduced signature makes PySide6 pass the
    arg through; a no-arg slot still receives none.

    Fidelity/limits (independent review, td-y6kg.12):
    - Positional-only params reproduce their ``/`` marker, so the generated
      parameter list matches ``fn`` exactly, not just in arity.
    - A parameter literally named ``__batched_target__`` would shadow the
      injected wrapped-fn reference; that collision raises, and the fallback
      below fires (never a silent misdispatch).
    - A genuinely variadic wrapped fn (``*args``) CANNOT be made non-variadic;
      it stays variadic and Shiboken would drop signal args. The regression
      guard (test_batched_signature) asserts no *current* @_batched slot is
      variadic — do not decorate a signal-arg slot with a ``*args`` signature.
    - The ``except`` fallback restores the old ``*args`` wrapper for a signature
      the generator cannot handle, but it WARNS (it silently reintroduced the
      exact dropped-arg bug otherwise — the failure this decorator exists to
      prevent)."""
    _TARGET = '__batched_target__'   # closure name for fn inside the generated wrapper
    try:
        sig = inspect.signature(fn)
        params = list(sig.parameters.items())
        first = params[0][0] if params else None
        if first is None:
            raise ValueError("@_batched expects a method (needs `self`)")
        parts, call, saw_star = [], [], False
        pos_only, slash_done = False, False
        for name, p in params:
            if name == _TARGET:
                raise ValueError(
                    "@_batched: slot parameter %r collides with the wrapper's "
                    "closure target" % name)
            k = p.kind
            if k == inspect.Parameter.POSITIONAL_ONLY:
                parts.append(name); call.append(name); pos_only = True
                continue
            if pos_only and not slash_done:   # close the positional-only group
                parts.append('/'); slash_done = True
            if k == inspect.Parameter.VAR_POSITIONAL:
                parts.append('*' + name); call.append('*' + name); saw_star = True
            elif k == inspect.Parameter.VAR_KEYWORD:
                parts.append('**' + name); call.append('**' + name)
            elif k == inspect.Parameter.KEYWORD_ONLY:
                if not saw_star:
                    parts.append('*'); saw_star = True
                parts.append(name); call.append(name + '=' + name)
            else:  # POSITIONAL_OR_KEYWORD
                parts.append(name); call.append(name)
        if pos_only and not slash_done:   # every param was positional-only
            parts.append('/')
        ns = {_TARGET: fn}
        exec("def _batched_wrapper(%s):\n"
             "    with %s.state.batching():\n"
             "        return %s(%s)\n"
             % (', '.join(parts), first, _TARGET, ', '.join(call)), ns)
        wrapper = ns['_batched_wrapper']
        wrapper.__defaults__ = fn.__defaults__
        wrapper.__kwdefaults__ = fn.__kwdefaults__
    except Exception as exc:
        # Fallback: the pre-td-y6kg.12 variadic wrapper. Correct for a slot that
        # needs no signal arg, but for a slot that DOES it silently drops the arg
        # (the exact bug this decorator fixes) — so warn, never fall back mutely.
        import warnings
        warnings.warn(
            "@_batched could not build a signature-preserving wrapper for %r "
            "(%s); falling back to a variadic wrapper, which drops Qt signal "
            "arguments." % (getattr(fn, '__name__', fn), exc),
            RuntimeWarning, stacklevel=2)

        @functools.wraps(fn)
        def wrapper(self, *args, **kwargs):
            with self.state.batching():
                return fn(self, *args, **kwargs)
        wrapper.__batched__ = True
        return wrapper
    functools.wraps(fn)(wrapper)
    wrapper.__batched__ = True   # regression test discovers @_batched slots by this
    return wrapper


class ChartGUI(ProfileMenuMixin, MenuBuilderMixin, ChartCaptureMixin, FileOpsMixin, AppDialogsMixin, SideDrawersMixin, KeyboardNavMixin, KalaIntegrationMixin, QMainWindow):
    """Main window for chart display. Lite foundation; Pro extends via ProChartGUI."""

    _CLEARED = object()

    # Global mode change signal — panels connect to this for bidirectional sync
    aditya_mode_changed = Signal(str)
    # Lightweight "sign label set changed" signal (SPEC-MODE-001). Distinct from
    # aditya_mode_changed: the zodiac system is UNCHANGED, only the displayed labels
    # flip (Aditya <-> Western). Pure relabel-panels (e.g. Find Chart) subscribe so
    # they refresh without triggering the heavy/stateful aditya_mode_changed slots
    # (which recompute charts or reset filters on an actual system change).
    sign_names_changed = Signal(str)

    # ===== CLUSTER: LIFECYCLE / INIT =====
    def __init__(self, debug_mode=False, **kwargs):
        super().__init__()
        self.debug_mode = debug_mode

        # td-iopy (D2): suppress the view PERSIST and the panel BROADCAST for the
        # whole construction phase. Any view activation during __init__ (e.g. an
        # initial display-changed signal) must neither write chart.view_type to
        # disk nor broadcast into half-built panels. showEvent's restore lifts
        # the broadcast (so it can sync the panels to the persisted view) and
        # manages the persist flag itself.
        self._suppress_view_persist = True
        self._suppress_view_broadcast = True

        # Load saved font scale FIRST — before any widgets are constructed
        try:
            from managers.settings_manager import get_settings
            from ui.qt_theme import set_scale_factor
            saved_scale = get_settings().get("display.font_scale", 1.0)
            set_scale_factor(saved_scale)

            # Load per-area font sizes (SPEC-FONT-001)
            from ui.qt_theme import set_area_font_size, AREA_DEFAULTS
            for area_id, default in AREA_DEFAULTS.items():
                saved = get_settings().get(f"display.fonts.{area_id}", default)
                set_area_font_size(area_id, saved)
        except Exception:
            pass

        # Multi-monitor detection state (initialized here, not lazily in moveEvent)
        from PySide6.QtCore import QTimer
        self._move_timer = QTimer()
        self._move_timer.setSingleShot(True)
        self._move_timer.setInterval(500)
        self._move_timer.timeout.connect(self._check_monitor_change)
        self._current_screen_name = None

        self._app_name = self._get_app_name()
        self.setWindowTitle(self._app_name)

        from PySide6.QtGui import QIcon
        from pathlib import Path
        icon_dir = Path(__file__).parent.parent / "icon"
        icon_path = icon_dir / self._get_icon_filename()
        if not icon_path.exists():
            icon_path = icon_dir / "varuna360.ico"

        if icon_path.exists():
            icon = QIcon(str(icon_path))
            self.setWindowIcon(icon)

        # Smart window geometry: restore saved position/size or fit to screen
        self._restore_window_geometry()

        # Allow window tiling (Win+arrows) by overriding Qt's auto-computed minimum
        # Without this, the combined fixed-width panels (2362px) prevent the WM from
        # tiling the window to half-screen. Content scrolls horizontally when tiled.
        self.setMinimumSize(960, 540)

        # Store ORIGINAL argv for restart (includes -d flag if present)
        # Use the global _ORIGINAL_ARGV that was captured at module import time
        self.original_argv = _ORIGINAL_ARGV.copy()

        # Track current loaded chart
        self.current_chart_path = None
        self._current_chart_data = self._CLEARED
        # Phase 5c W5: legacy chart-state + mode-state attributes removed.
        # Consumers read from self.state.{planets_data,active_chart,rashi,
        # current_varga,varga_data,aditya_mode,time_adjust_mode,chart_view_style}.
        self.current_timezone = "UTC"  # IANA timezone for title display
        self._current_birth_data = self._CLEARED

        # Dasha navigation state (the 12 former ChartGUI attributes: right mode,
        # per-side levels/offsets/chains/rows, the two ayanamsa ids, Nisarga
        # level) now lives in DashaManager.dasha_state (SPEC-DSH-002, td-1bpk
        # w1-2), built from settings when the manager is constructed (~:460).
        # Read them via the manager accessors (ayanamsa/side_level/cycle_offset/
        # rows/right_mode), never off self.
        from managers.settings_manager import get_settings
        _sm = get_settings()
        self.nakshatra_coords     = _sm.get("zodiac.nakshatra_coords", "neither")

        # Chart zodiac type: "tropical" (default) or "sidereal"
        self.chart_zodiac = "tropical"
        # Ayanamsa ID for sidereal chart display (tied to dasha ayanamsa selection)
        self.chart_sidereal_ayanamsa_id = 27  # True Citra default (2026-09-24)
        # Cached ayanamsa offset in degrees (computed from birth JD)
        self.chart_ayanamsa_offset = 0.0

        # Dual rim mode: show outer Tropical rim on Aditya wheel (wheel view only)
        self.show_tropical_rim = False

        # Transit overlay managed by TransitOverlayManager (initialized in _init_managers)

        # Sign name display: False = Aditya names (Dhata, Aryama...), True = Western names (Aries, Taurus...)
        # This only affects display labels, not calculations
        self.use_western_names = False

        # Human Design mode (-88° Sun shift) - independent toggle.
        # State now lives on AppState (state.human_design_mode); `is_human_design`
        # is a delegating @property (CHART-DATA PROPERTIES cluster). NOT initialized
        # here: this line ran at __init__ before self.state exists (created ~line
        # 333), so a property setter that dispatches would have no state to reach.
        # AppState's field default (False) supplies the initial value (Stage 2).

        # Sign as Ascendant override (F3 cycle)
        # None = use actual birth Ascendant, 0-11 = use that sign index as Ascendant
        self.current_ascendant_override = None

        # Time adjust overlay widget (created on first toggle; mode lives in self.state)
        self.time_adjust_widget = None

        # Birth parameters for mode switching (set in load_chart)
        self.birth_jd = None
        self.birth_lat = None
        self.birth_lon = None
        self.birth_country = ""
        self.person_name = ""

        # Layer B persistence (Phase 4 W3 — PrefsStore must be created BEFORE
        # ChartState so __init__ can restore aditya_mode + chart_view_style).
        from state import ChartState, PrefsStore
        from state.user_data import get_user_data_dir
        self.user_data_dir = get_user_data_dir() or PROJECT_ROOT
        self.prefs_store = PrefsStore(self.user_data_dir / "settings.json")

        # Layer B state container (single source of truth post-Phase 5c)
        self.state = ChartState(prefs_store=self.prefs_store)

        # Set zodiac mode from SettingsManager (authoritative, SPEC-SET-002 s5.5).
        # Direct assignment: no listeners connected yet, dispatch would be wasted.
        from managers.settings_manager import get_settings
        _sm = get_settings()
        _sm_mode = _sm.get("zodiac.mode", "")
        if _sm_mode:
            from state.chart_state import VALID_ADITYA_MODES
            if _sm_mode in VALID_ADITYA_MODES:
                self.state._aditya_mode = _sm_mode

        _sm_hsys = _sm.get("zodiac.house_system", "")
        if _sm_hsys and _sm_hsys != self.state.house_system:
            from state.events import SetHouseSystem
            try:
                self.state.dispatch(SetHouseSystem(house_system=_sm_hsys))
            except ValueError:
                import warnings
                warnings.warn(
                    f"Unrecognized house_system {_sm_hsys!r} in settings, keeping 'campanus'"
                )

        # SPEC-CAL-001: refresh the title-bar date when the calendar-display
        # convention changes (Settings > Historical dates). DISPLAY-ONLY: the
        # title re-reads display.calendar_convention via display_civil_date; no
        # chart recompute. Subscribed once here so it works in Pro and Lite.
        try:
            _sm.on_changed("display.calendar_convention",
                           lambda _k, _v: self._update_title())
        except Exception:
            pass

        # Sync chart_zodiac with the effective zodiac mode
        if self.state.aditya_mode == "sidereal":
            self.chart_zodiac = "sidereal"

        # Sync remaining zodiac/display attributes from saved settings
        self.use_western_names = _sm.get("zodiac.use_western_names", False)
        # SPEC-MODE-001 (path #5, section 4.7): in Beginner the experience-level
        # gate overrides any persisted/locked use_western_names. Clamp to the
        # native default for the active system and persist it, so an upgrade from
        # Advanced (or a stale value left by the sidereal off-toggle) never boots
        # showing the alternative label set. Per the approved design (section 5.5)
        # an upgrading user defaults to Beginner and re-picks alternative naming
        # once if they switch to Advanced; we do NOT attempt to preserve a stale
        # alt-naming preference, because the only route to Advanced is the Settings
        # combo, which (being collapsed to native entries in Beginner) cannot
        # represent it anyway. The lock resumes governing once in Advanced.
        if _sm.get("ui.experience_level", "beginner") != "advanced":
            _native_western = (self.state.aditya_mode != "aditya")
            if self.use_western_names != _native_western:
                self.use_western_names = _native_western
                _sm.set("zodiac.use_western_names", _native_western)
        # SPEC-MODE-001: clamp use_western_names to native on ANY runtime zodiac
        # mode change in Beginner. Every system switch (toolbar, Alt+S, the dasha
        # and nakshatra ayanamsa dialogs, session restore, remote control) routes
        # through ChartState.dispatch, so a single observer covers them all plus
        # any future path. The callback re-clamps before the caller's re-render.
        self.state.connect(self._clamp_western_names_on_mode_change)
        self.sign_language = _sm.get("zodiac.sign_language", "en")
        _saved_ayan = _sm.get("zodiac.ayanamsa_id", None)
        if _saved_ayan is not None:
            self.chart_sidereal_ayanamsa_id = _saved_ayan
        self.show_tropical_rim = _sm.get("chart.show_tropical_rim", False)
        self._saved_transit_overlay = _sm.get(
            "chart.show_transit_overlay",
            _sm.get("chart.show_transit_rim", False),
        )

        # Initialize chart manager (handles chart file operations)
        self.chart_manager = ChartManager(self)

        # Initialize dasha manager (handles Vedanga/Vimshottari dasha navigation)
        self.dasha_manager = DashaManager(self)
        from managers.zodiac_settings_manager import ZodiacSettingsManager
        self.zodiac_settings = ZodiacSettingsManager(self)

        # Human Design model lifecycle (SPEC-HD-001 §8). Plain object, no timer;
        # must exist before the HD page (index 5) is shown or read remotely.
        from managers.hd_manager import HDManager
        self.hd_manager = HDManager(self)

        from managers.transit_overlay_manager import TransitOverlayManager
        self.transit_overlay_manager = TransitOverlayManager(gui=self, parent=self)
        # SPEC-TRN-006: resolves dropped payloads into overlay charts. Plain
        # object (no timer/signal); must exist before any drop can be handled.
        from managers.chart_overlay_manager import ChartOverlayManager
        self.chart_overlay_manager = ChartOverlayManager(self)
        self.state.connect(self.transit_overlay_manager._on_active_chart_changed)
        self.aditya_mode_changed.connect(
            self.transit_overlay_manager._on_aditya_mode_changed
        )
        # The HD page frame is DERIVED from the zodiac mode (C7): a mode change
        # recomputes the bodygraph in the new frame, but only if HD is the current
        # view (refresh_active_view is a no-op otherwise, so mode changes behind
        # another view cost nothing until HD is shown).
        self.aditya_mode_changed.connect(
            lambda _mode: self.hd_manager.refresh_active_view()
        )
        # C9 item 2: after the bodygraph recomputes, a Beginner who changed the
        # zodiac mode while Human Design is on screen gets the one-time notice
        # that HD stayed on the Standard/tropical frame (no padlock on the main
        # tab — Lorris ruled the popup carries that message instead). The helper
        # self-gates (Beginner + not muted + HD on screen) and never raises, so a
        # notice failure cannot abort the rest of the mode switch. Connected
        # AFTER the refresh so the recompute runs first.
        try:
            from apps.widgets.hd.hd_frame_notice import maybe_warn_frame_locked
            self.aditya_mode_changed.connect(
                lambda _mode: maybe_warn_frame_locked(self))
        except Exception:
            pass
        # Toggling the Human Design experience level (Settings) flips the frame
        # between Standard-locked (Beginner) and mode-following (Advanced), so the
        # bodygraph must recompute live. No-op unless HD is the current view.
        try:
            from managers.settings_manager import get_settings
            get_settings().on_changed(
                "ui.hd_experience_level",
                lambda *_: self.hd_manager.refresh_active_view())
        except Exception:
            pass
        from PySide6.QtCore import Qt as QtCore_Qt
        self.transit_overlay_manager.transit_state_changed.connect(
            self._on_transit_state_changed, QtCore_Qt.ConnectionType.QueuedConnection
        )

        # Phase 4 W5: panel_update_manager dissolved — all 12 panels migrated to
        # PanelController subscribers. info_panels.py + info_panel_dialog.py
        # already guard with `hasattr(gui, 'panel_manager')` so removing this
        # attribute degrades them to no-ops gracefully.

        # Phase 4: self-updating panel controllers (one wave at a time)
        from apps.widgets.panel_controllers import (
            ElementsController, ModalityController, HoraController,
            TrimsamsaController, KarakasController, StrengthController,
            AspectsController, AvasthaController, ShameController,
            TajikaMatrixController, TajikaRelationshipsController,
            TajikaYogasController, DignitiesController,
            InterchangeController, NabhasaController,
        )
        self.elements_controller = ElementsController(self)
        self.elements_controller.connect_to_state(self.state)
        self.modality_controller = ModalityController(self)
        self.modality_controller.connect_to_state(self.state)
        self.dignities_controller = DignitiesController(self)
        self.dignities_controller.connect_to_state(self.state)
        self.hora_controller = HoraController(self)
        self.hora_controller.connect_to_state(self.state)
        self.trimsamsa_controller = TrimsamsaController(self)
        self.trimsamsa_controller.connect_to_state(self.state)
        self.karakas_controller = KarakasController(self)
        self.karakas_controller.connect_to_state(self.state)
        self.strength_controller = StrengthController(self)
        self.strength_controller.connect_to_state(self.state)
        self.aspects_controller = AspectsController(self)
        self.aspects_controller.connect_to_state(self.state)
        # Deferred controllers: created lazily on first panel visibility via
        # _ensure_controller(). info_panels.py switch methods call _ensure_controller()
        # then set_visible(); hasattr() guards elsewhere are safe no-ops until first access.
        from apps.widgets.panel_controllers.planetary_condition_controller import PlanetaryConditionController
        self._deferred_controller_classes = {
            'avastha': AvasthaController,
            'shame': ShameController,
            'interchange': InterchangeController,
            'nabhasa': NabhasaController,
            'tajika_matrix': TajikaMatrixController,
            'tajika_relationships': TajikaRelationshipsController,
            'tajika_yogas': TajikaYogasController,
            'planetary_condition': PlanetaryConditionController,
        }

        # Initialize loading manager (overlay for heavy operations)
        self.loading_manager = LoadingManager(self)



        # Show startup overlay immediately (stays visible through init + session restore)
        self.loading_manager.start("Starting Varuna360...")

        # Create menu bar
        self._create_menus()

        # Register keyboard shortcuts (arrows + Alt+key)
        self._setup_keyboard_shortcuts()

        # === PROFILE BUTTON (top-right corner, circular with avatar) ===
        self.profile_button = QPushButton("👤")
        self.profile_button.setParent(self)
        self.profile_button.setFixedSize(36, 36)
        self._update_profile_button_style()  # Apply theme-aware styling
        self.profile_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.profile_button.clicked.connect(self._show_profile_menu)
        # Position at top-right (will be updated in resizeEvent)
        self.profile_button.move(self.width() - 50, 8)
        self.profile_button.raise_()  # Bring to front

        # Create central widget with tab widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        central_layout = QVBoxLayout(central_widget)
        central_layout.setContentsMargins(0, 0, 0, 0)

        # Tab widget for Chart and Settings tabs
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet(get_tab_bar_style())
        central_layout.addWidget(self.tab_widget)

        # === TAB 1: CHART TAB (vertical layout for memory panel + chart content) ===
        from apps.widgets.chart_drop_tab import ChartDropTab
        self.chart_tab = ChartDropTab(self)
        chart_tab_layout = QVBoxLayout(self.chart_tab)
        chart_tab_layout.setSpacing(0)
        chart_tab_layout.setContentsMargins(0, 0, 0, 0)

        # === CHART MEMORY PANEL (top of chart tab) ===
        from apps.panels.chart_memory_panel import create_chart_memory_panel
        memory_panel_widget = create_chart_memory_panel(self)
        chart_tab_layout.addWidget(memory_panel_widget)
        # Note: ChartMemoryPanel instance stored in self.memory_panel_instance by factory
        self.memory_panel = self.memory_panel_instance  # Alias for convenience
        self.chart_memory_panel = self.memory_panel_instance  # Alias for session manager compatibility

        # === CHART TITLE WIDGET (below memory panel) ===
        from apps.widgets.chart_title_widget import create_chart_title_widget
        self.chart_title_widget = create_chart_title_widget(self)
        chart_tab_layout.addWidget(self.chart_title_widget)

        # === CHART CONTENT (horizontal layout for all panels) ===
        self.chart_content = QWidget()
        chart_content = self.chart_content  # Keep local alias for readability
        chart_layout = QHBoxLayout(chart_content)
        chart_layout.setSpacing(5)
        chart_layout.setContentsMargins(5, 5, 5, 5)

        # Column 1: Vedanga Dasha Panel (far left)
        self.vedanga_panel = self.dasha_manager.build_panel("left", parent=self)
        chart_layout.addWidget(self.vedanga_panel)

        # Column 2: Slim Varga Column (between Vedanga and Chart)
        # SPEC-VGC-001 D-7: restore the persisted center-varga preference
        # BEFORE the column is built, so the toggle is created already
        # checked rather than needing a second sync (an unchecked button
        # over a true flag is the desync INV-4 forbids).
        try:
            from managers.settings_manager import get_settings
            self.varga_in_center = bool(
                get_settings().get("display.varga_in_center", False))
        except Exception:
            self.varga_in_center = False
        _is_implemented = lambda n: n in VARGA_NAMES
        _get_name = lambda n: VARGA_NAMES.get(n, f"D-{n}")
        self.varga_column = create_varga_column(self, _is_implemented, _get_name)
        chart_layout.addWidget(self.varga_column)

        # Column 3: Chart view (center) - takes remaining space
        # Use QStackedWidget to switch between South Indian and Wheel views
        self.chart_stack = QStackedWidget()
        self.chart_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # South Indian View (index 0) — host widget owning BOTH the classic
        # and vector SI themes (SPEC-SIC-002 §4.1); the stack index follows
        # display.south_indian_style via sync_style().
        self.chart_view = create_south_indian_view(
            sector_dialog_handler=self._show_sector_dialog)
        # Connect planet click signal to show dialog
        self.chart_view.planet_click_signal.clicked.connect(self._show_planet_dialog)
        # Sign click opens the sector popup at the Sign layer (SPEC-AVA-003 v1.3)
        self.chart_view.sign_click_signal.clicked.connect(self._show_sign_popup)
        # Theme-locked chart background at boot (td-iqjb.8 Wave H: via the shared
        # helper so boot and switch pick the SAME stone -- was an inline literal).
        from ui.qt_theme import themed_chart_background
        self.chart_view.set_background(themed_chart_background())
        self.chart_stack.addWidget(self.chart_view)

        # Wheel View (index 1)
        self.wheel_view = WheelView()
        self.wheel_view.connect_gui(self)
        self.wheel_view.planet_click_signal.clicked.connect(self._show_planet_dialog)
        self.wheel_view._retinue_click_signal.clicked.connect(self._show_sector_dialog)
        self.wheel_view.sign_click_signal.clicked.connect(self._show_sign_popup)
        self.chart_stack.addWidget(self.wheel_view)

        # North Indian View (index 2)
        self.north_indian_view = NorthIndianView()
        # Connect planet click signal (uses same dialog)
        self.north_indian_view.planet_click_signal.clicked.connect(self._show_planet_dialog)
        self.north_indian_view.sign_click_signal.clicked.connect(self._show_sign_popup)
        self.chart_stack.addWidget(self.north_indian_view)

        # Body Graph View (index 3) — SPEC-BODY-001 body graph wrapped by
        # SPEC-BODY-002's BodyAspectDualWidget: adds a Shift+F2-toggleable rashi
        # aspect South Indian panel with cross-view hover sync. The dual widget is
        # a drop-in proxy for the body view (identical planet-click contract and
        # update_from_chart surface), so `self.body_graph_view` keeps its name and
        # every existing call site works unchanged.
        self.body_graph_view = BodyAspectDualWidget(self)
        self.body_graph_view.planet_click_signal.clicked.connect(self._show_planet_dialog)
        self.chart_stack.addWidget(self.body_graph_view)

        # Cards of Truth View (index 4) — SPEC-COT-001. Always natal (INV-15):
        # the spread binds to chart.rashi(), so _apply_current_varga hands it
        # the unmodified chart and no varga code.
        self.cards_of_truth_view = CardsOfTruthView(self)
        self.cards_of_truth_view.planet_click_signal.clicked.connect(self._show_planet_dialog)
        self.chart_stack.addWidget(self.cards_of_truth_view)

        # Human Design page (index 5) — SPEC-HD-001. HDPanel: graph + toolbar +
        # Design/Personality columns + reading card. Shortcut-only (Ctrl+Shift+H),
        # EXCLUDED from the F2 ring, invisible until mature. Fed the HDModel dict
        # by hd_manager (NOT a Chart object), so its update_from_chart takes the
        # model. Named `human_design_view` for the manager contract; it is the
        # page widget (HDPanel), which contains the graph at `.view`.
        self.human_design_view = _HDView(self)
        self.chart_stack.addWidget(self.human_design_view)

        # Restricted Nakshatra wheel (index 6) — SPEC-NAK-LITE-001. A normal F2
        # view (cycled with Wheel / South Indian), NOT a Pro tab. The panel owns
        # its own planet-click wiring and redraw-on-frame-change; the frame comes
        # from the main-tab zodiac buttons and the ayanamsa from zodiac.ayanamsa_id.
        # Sidereal by default, sector click inert, no teacher content.
        from apps.panels.nakshatra_core_panel import NakshatraCorePanel
        self.nakshatra_core_panel = NakshatraCorePanel(self)
        self.chart_stack.addWidget(self.nakshatra_core_panel)

        self._set_sign_language(self.sign_language)

        # Default to South Indian view (state.chart_view_style is the source of truth)
        self.chart_stack.setCurrentIndex(0)
        # SPEC-BAR-001 D-23(d): the remembered non-Cards view CARDS returns to.
        # Initialised to South Indian (index 0) and kept validated in {0,1,2,3}
        # by _activate_chart_view; a boot/remote restore into Cards (index 4)
        # therefore leaves a valid remembered index instead of looping.
        self._last_chart_view_index = 0

        chart_layout.addWidget(self.chart_stack, stretch=1)

        # Column 3.5: Z6b sign-selector column (mirrors Varga column on the right)
        self.sign_selector_column = create_sign_selector_column(self)
        chart_layout.addWidget(self.sign_selector_column)

        # Column 4: Right panels (Karakas + Strength stacked) in scroll area
        self.right_panels = create_right_panels(self)
        self.right_scroll = QScrollArea()
        self.right_scroll.setWidget(self.right_panels)
        self.right_scroll.setWidgetResizable(True)
        self.right_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.right_scroll.setFixedWidth(self.right_panels.maximumWidth())
        self.right_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        chart_layout.addWidget(self.right_scroll)

        # Column 5: Vimshottari Dasha Panel (far right)
        self.vimshottari_panel = self.dasha_manager.build_panel("right", parent=self)
        chart_layout.addWidget(self.vimshottari_panel)

        # Reshape the right panel for the persisted/boot mode via the one
        # dispatcher (SPEC-ZR-001 §3.6). An unknown persisted mode falls back to
        # the default with a logged warning instead of rendering as Vimshottari.
        # announce=False: boot must not flash the "F7 to switch" status message.
        self.dasha_manager.configure_right_panel(self.dasha_manager.right_mode, announce=False)

        chart_tab_layout.addWidget(chart_content)

        # === RESPONSIVE PANEL SYSTEM (auto-hide + sliding drawers) ===
        self._side_panels_visible = True
        self._side_panels = [
            self.vedanga_panel,
            self.varga_column,
            self.sign_selector_column,
            self.right_scroll,
            self.vimshottari_panel,
        ]

        # Store target widths for animation restore
        self._panel_target_widths = {}
        for p in self._side_panels:
            self._panel_target_widths[p] = p.maximumWidth()

        # Drawer state
        self._left_drawer_open = False
        self._right_drawer_open = False
        self._running_anims = []  # prevent GC of QPropertyAnimation

        # Toggle button style (thin, subtle, theme-compatible)
        _toggle_style = """
            QPushButton {
                background: rgba(255,255,255,0.08);
                border: none; color: #999; font-size: {scaled_px(16)}px;
                border-radius: 3px; padding: 0;
            }
            QPushButton:hover {
                background: rgba(255,255,255,0.18); color: white;
            }
        """

        # Left toggle (slides in Vedanga + Varga)
        self._left_toggle = QPushButton("\u25b6")  # right-pointing triangle
        self._left_toggle.setFixedWidth(22)
        self._left_toggle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self._left_toggle.setToolTip("Toggle Dasha panels")
        self._left_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._left_toggle.setStyleSheet(_toggle_style)
        self._left_toggle.clicked.connect(lambda: self._toggle_side_drawer("left"))
        self._left_toggle.setVisible(False)
        chart_layout.insertWidget(0, self._left_toggle)

        # Right toggle (slides in Info + Vimshottari)
        self._right_toggle = QPushButton("\u25c0")  # left-pointing triangle
        self._right_toggle.setFixedWidth(22)
        self._right_toggle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self._right_toggle.setToolTip("Toggle Info panels")
        self._right_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._right_toggle.setStyleSheet(_toggle_style)
        self._right_toggle.clicked.connect(lambda: self._toggle_side_drawer("right"))
        self._right_toggle.setVisible(False)
        chart_layout.addWidget(self._right_toggle)

        self._setup_tabs()


        # NOTE: Initial chart draw is deferred to showEvent() to ensure proper viewport geometry
        # This fixes the bug where charts don't display correctly on first load
        self._initial_draw_done = False

        # Status bar
        self.statusBar().showMessage("South Indian Chart - Ready (PySide6)")

        # SPEC-FSV-001 WI-2: the position-ORDER control lives here now — one
        # always-visible home on all five chart pages, replacing the four
        # in-canvas copies. Permanent widgets sit right and are immune to
        # transient showMessage() text (ui/sticky_status.py).
        from apps.widgets.status_chrome import (
            StatusFullscreenButton, StatusOrderButton)
        self.status_order_button = StatusOrderButton()
        self.statusBar().addPermanentWidget(self.status_order_button)

        # SPEC-FSV-001 WI-3/WI-4: fullscreen the current chart page. The manager
        # owns the reparent/fit/restore (Rule 4); the status-bar glyph (right of
        # ORDER) and the QAction("F") in the View menu are the two entry points.
        from managers.view_float_manager import ViewFloatManager
        self.view_float_manager = ViewFloatManager(self)
        # Duck-typed resolution attr (like the on_page_shown protocol): the
        # manager walks tab_widget.currentWidget().fullscreen_target(). The Chart
        # tab's descriptor is defined on ChartGUI; bind it onto the tab so tabs
        # WITHOUT a chart surface (Edit/Find/Settings...) simply have no attr and
        # F no-ops there instead of lifting the (hidden) chart stack.
        self.chart_tab.fullscreen_target = self._chart_fullscreen_target
        self.status_fullscreen_button = StatusFullscreenButton(
            self.view_float_manager.toggle_fullscreen)
        self.statusBar().addPermanentWidget(self.status_fullscreen_button)
        # A width-only spacer to the RIGHT of the controls: sized by
        # _align_status_controls() so the ORDER pill + fullscreen glyph line up
        # with the chart view's right edge, not the far window edge (they sit
        # over the chart, not over the side panels). Plain QWidget = transparent,
        # paints nothing. SPEC-FSV-001 alignment refinement.
        from PySide6.QtWidgets import QWidget as _QWidget
        self._status_controls_spacer = _QWidget()
        self.statusBar().addPermanentWidget(self._status_controls_spacer)
        # Fullscreen is session-only and page-scoped: leaving the Chart tab (or
        # quitting) drops back to the windowed layout rather than stranding a
        # detached stack in a top-level window.
        def _on_tab_changed(_i):
            self.view_float_manager.exit_fullscreen()
            # td-sy9e: an F2/view change made while an aux tab was on screen
            # deferred the main-view repaint; settle it now that the stack is
            # visible again (no-op when nothing was deferred).
            if self.chart_stack.isVisible():
                self._repaint_main_views_if_stale()
            # Returning to the Chart tab does not resize the window, so realign
            # the status controls once the stack is visible again.
            from PySide6.QtCore import QTimer as _QTimer
            _QTimer.singleShot(0, self._align_status_controls)
        self.tab_widget.currentChanged.connect(_on_tab_changed)
        from PySide6.QtWidgets import QApplication as _QApp
        _app = _QApp.instance()
        if _app is not None:
            _app.aboutToQuit.connect(self.view_float_manager.exit_fullscreen)
            # td-iopy LOW-5 (Codex): Ctrl+C exits via QApplication.quit()+SystemExit,
            # bypassing closeEvent, which would lose a view change made in the last
            # debounce window (~500ms). Flush on aboutToQuit too — idempotent with
            # the closeEvent flush (the pending flag guards a double write).
            _app.aboutToQuit.connect(self._flush_view_persist)

        # === SESSION MANAGER (Phase 4) ===
        # Phase 4 W4: ProfileStore wraps the file I/O; SessionManager keeps
        # the auto-save QTimer + restore dialog + business logic.
        from managers.session_manager import SessionManager
        from state import ProfileStore
        self.profile_store = ProfileStore(self.user_data_dir / "profiles")
        self.session_manager = SessionManager(self, profile_store=self.profile_store)

        # === PROFILE MANAGER ===
        from managers.profile_manager import ProfileManager
        # SPEC-SES-001 INV-2: use the profiles dir the SessionManager preflight
        # actually settled on, NOT self.user_data_dir. When the configured
        # folder is read-only (macOS TCC denial, a synced folder, a bad
        # permission), the preflight above has already relocated to a writable
        # fallback. Passing the original path here would point ProfileManager
        # at the dead folder and its mkdir would raise during __init__, i.e.
        # the app would crash at startup on exactly the case the relocation
        # exists to survive.
        self.profile_manager = ProfileManager(
            self, profiles_dir=self.session_manager.profiles_dir
        )
        current_profile_id = self.profile_manager.get_current_profile()

        # Sync SessionManager with current profile (CRITICAL for loading correct session)
        self.session_manager.current_profile = current_profile_id

        # FIX: Start auto-save AFTER restore completes to prevent race condition
        # Previously: auto-save started immediately, restore ran 500ms later
        # This caused auto-save to potentially save empty session during startup
        from PySide6.QtCore import QTimer

        def _delayed_startup():
            """Restore session first, THEN start auto-save."""
            self.loading_manager.update("Restoring session...")
            if get_settings().get_auto_restore_session():
                self.session_manager.restore_session_silently()
            # SPEC-MODE-001: re-clamp naming after session restore; the restored
            # mode may have left use_western_names in a non-native state.
            if self._is_beginner_mode():
                _native = (self.state.aditya_mode != "aditya")
                if self.use_western_names != _native:
                    self.use_western_names = _native
                    get_settings().persist_runtime_change(
                        "zodiac.use_western_names", _native)
            # Sync toggle buttons with the mode loaded from PrefsStore
            self._update_toggle_button_styles()
            # Only start auto-save after restore is complete
            self.session_manager.start_auto_save()
            # If no chart was loaded from session, create a "Now" chart
            if not self.state.active_chart:
                QTimer.singleShot(200, self._load_now_chart)
            else:
                # Session restored a chart but dasha panels need explicit population
                QTimer.singleShot(200, self._populate_dasha_after_startup)
            # Dismiss startup overlay now (user sees the chart immediately)
            self.loading_manager.finish()
            # Preload popular tabs silently in the background
            def _finish_startup():
                import shiboken6
                if not shiboken6.isValid(self) or not shiboken6.isValid(self.tab_widget):
                    return
                self._preload_popular_tabs()
                self._startup_phase = False
            QTimer.singleShot(3000, _finish_startup)

        QTimer.singleShot(500, _delayed_startup)

        # Load profile avatar after delay (ensure ProfileManager is ready)
        QTimer.singleShot(800, self._load_profile_avatar)

        # ── License refresh timer (every 12 hours) ──
        self._license_state = getattr(self, '_license_state', None)
        self._license_refresh_timer = QTimer(self)
        self._license_refresh_timer.setInterval(12 * 60 * 60 * 1000)  # 12h in ms
        self._license_refresh_timer.timeout.connect(self._refresh_license)
        self._license_refresh_timer.start()


        self.controller = None
        self._setup_remote_control()
        self.zodiac_settings.start()



    def _ensure_controller(self, name):
        """Lazily create and state-wire a deferred panel controller on first access."""
        attr = f'{name}_controller'
        if hasattr(self, attr):
            return getattr(self, attr)
        cls = self._deferred_controller_classes.get(name)
        if cls:
            ctrl = cls(self)
            ctrl.connect_to_state(self.state)
            setattr(self, attr, ctrl)
            if self.state.active_chart:
                if ctrl._lazy:
                    ctrl._pending_chart_refresh = True
                else:
                    from PySide6.QtCore import QTimer
                    QTimer.singleShot(0, ctrl._on_chart_changed)
            return ctrl
        return None

    def _setup_tabs(self):
        """Add tabs to tab_widget. Override in subclass to add extra tabs."""
        self.tab_widget.addTab(self.chart_tab, "Chart")

        # === EDIT CHART TAB (lazy loading) ===
        self._edit_chart_placeholder = QWidget()
        _ecl = QVBoxLayout(self._edit_chart_placeholder)
        _ecl_label = QLabel("Click to load New & Edit...")
        _ecl_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _ecl_label.setStyleSheet(f"color: #888; font-size: {scaled_px(14)}px;")
        _ecl.addWidget(_ecl_label)
        # "New && Edit": the doubled ampersand renders as a literal "&"; a
        # single "&" is consumed as a Qt tab mnemonic and the following space is
        # drawn underlined, so the tab reads "New_Edit". tabText() returns the
        # "&&" form verbatim, so the _show_new/edit_chart matchers below strip it.
        self.tab_widget.addTab(self._edit_chart_placeholder, "New && Edit")
        self.edit_chart_panel = None

        # === FIND CHART TAB (lazy loading, available in all editions) ===
        self.loading_manager.update("Loading panels...")
        self._find_chart_placeholder = QWidget()
        placeholder_layout = QVBoxLayout(self._find_chart_placeholder)
        placeholder_label = QLabel("Click to load Find Chart...")
        placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder_label.setStyleSheet(f"color: #888; font-size: {scaled_px(14)}px;")
        placeholder_layout.addWidget(placeholder_label)
        self.tab_widget.addTab(self._find_chart_placeholder, "Find Chart")
        self.find_chart_panel = None

        self._add_feature_tabs()

        # === SETTINGS TAB (lazy loading - takes 5s+ to create) ===
        self._settings_placeholder = QWidget()
        placeholder_layout = QVBoxLayout(self._settings_placeholder)
        placeholder_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Loading label
        self._settings_loading_label = QLabel("Click to load Settings...")
        self._settings_loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._settings_loading_label.setStyleSheet(f"color: #888; font-size: {scaled_px(14)}px;")
        placeholder_layout.addWidget(self._settings_loading_label)

        # Progress bar (hidden until loading starts)
        self._settings_progress_bar = QProgressBar()
        self._settings_progress_bar.setFixedWidth(300)
        self._settings_progress_bar.setRange(0, 0)  # Indeterminate mode
        self._settings_progress_bar.setTextVisible(False)
        self._settings_progress_bar.setStyleSheet(desat_qss("""
            QProgressBar {
                border: 1px solid #555;
                border-radius: 5px;
                background-color: #2b2b2b;
                height: 8px;
            }
            QProgressBar::chunk {
                background-color: #D4AF37;
                border-radius: 4px;
            }
        """))
        self._settings_progress_bar.hide()
        placeholder_layout.addWidget(self._settings_progress_bar, alignment=Qt.AlignmentFlag.AlignCenter)

        self.tab_widget.addTab(self._settings_placeholder, "Settings")
        self.settings_tab = None  # Will be set by _create_settings_widget()

        self._add_trailing_tabs()

        if self.debug_mode:
            self.debug_tab = DebugConsoleWidget(restart_callback=self._restart_app)
            self.tab_widget.addTab(self.debug_tab, "Debug")

        from managers.settings_manager import get_settings
        self._tab_usage_counts = get_settings().get("tab_usage_counts", {}) or {}
        self._preloading = False  # Guard: don't count preloading as usage
        self._startup_phase = True  # Guard: suppress heavy work during init

        # Connect tab change handler after usage state exists, then restore the
        # last active tab if configured.
        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        self._restore_last_active_tab()

    # ===== CLUSTER: CHART-DATA PROPERTIES =====
    @property
    def is_human_design(self):
        """Human Design mode flag — delegates to AppState (god-object Stage 2,
        td-ltha). The truth lives in state.human_design_mode; this property keeps
        `gui.is_human_design` working for every reader (managers) and for the
        ~10 internal writes, which now route through the setter -> dispatch.
        Reads are safe because every access happens after self.state exists."""
        return self.state.human_design_mode

    @is_human_design.setter
    def is_human_design(self, value):
        from state.events import SetHumanDesignMode
        self.state.dispatch(SetHumanDesignMode(enabled=bool(value)))

    @property
    def current_chart_data(self):
        stored = self._current_chart_data
        if stored is self._CLEARED:
            return None
        if stored is not None:
            return stored
        state = getattr(self, 'state', None)
        if not state or not state.active_chart:
            return None
        mp = getattr(self, 'chart_memory_panel', None) or getattr(self, 'memory_panel', None)
        if mp and 0 <= mp.current_index < len(mp.charts):
            recipe = mp.charts[mp.current_index].get('recipe')
            if recipe:
                from core.chart_factory import chart_data_from_recipe as _cdata_from_recipe
                result = _cdata_from_recipe(recipe)
                self._current_chart_data = result
                return result
        return None

    @current_chart_data.setter
    def current_chart_data(self, value):
        if value is None:
            self._current_chart_data = self._CLEARED
        else:
            self._current_chart_data = value

    @property
    def current_birth_data(self):
        stored = self._current_birth_data
        if stored is self._CLEARED:
            return None
        if stored is not None:
            return stored
        state = getattr(self, 'state', None)
        if not state or not state.active_chart:
            return None
        mp = getattr(self, 'chart_memory_panel', None) or getattr(self, 'memory_panel', None)
        if mp and 0 <= mp.current_index < len(mp.charts):
            recipe = mp.charts[mp.current_index].get('recipe')
            if recipe:
                from core.chart_factory import birth_data_from_recipe as _bdata_from_recipe
                result = _bdata_from_recipe(recipe)
                self._current_birth_data = result
                return result
        return None

    @current_birth_data.setter
    def current_birth_data(self, value):
        if value is None:
            self._current_birth_data = self._CLEARED
        else:
            self._current_birth_data = value


    # ===== CLUSTER: TAB CONSTRUCTION & LAZY WIDGETS =====
    def _create_settings_tab(self, current_theme):
        """Factory: return a SettingsTab instance. Override in Pro for extended settings."""
        from ui.settings_tab import SettingsTab
        tab = SettingsTab(current_theme=current_theme)
        # SPEC-SES-001 §4.4 — wire the save-health banner. Done here rather
        # than inside SettingsTab because this is where the SessionManager is
        # reachable; the tab itself stays GUI-agnostic.
        from ui.session_health_banner import SessionHealthBanner
        SessionHealthBanner.attach_all(tab, getattr(self, 'session_manager', None))
        return tab

    def has_transit_tab(self):
        """Capability query: does this edition have a Transit tab? Override in Pro."""
        return False

    def ai_image_extractor(self):
        """Return the shared Add Chart image reader callable."""
        from core.chart_image_extraction import extract_charts_from_image
        return extract_charts_from_image

    def _add_feature_tabs(self):
        """Add feature tabs between Find Chart and Settings. Override in Pro."""
        pass

    def _add_trailing_tabs(self):
        """Add tabs after Settings (before Debug). Override in Pro."""
        pass

    def _get_app_name(self):
        """Return the application name. Override in Pro."""
        return "Varuna360 Lite"

    def _get_icon_filename(self):
        """Return the icon filename. Override in Pro."""
        return "varuna360_lite.png"

    def _setup_remote_control(self):
        """Initialize remote control. Override in Pro."""
        pass

    def _create_settings_widget(self):
        """Create Settings tab lazily (direct import, no background thread)."""
        if hasattr(self, '_settings_placeholder') and self._settings_placeholder:
            try:
                # Show loading UI
                if hasattr(self, '_settings_loading_label'):
                    self._settings_loading_label.setText("Loading Settings...")
                if hasattr(self, '_settings_progress_bar'):
                    self._settings_progress_bar.show()
                QApplication.processEvents()  # Update UI immediately

                index = self.tab_widget.indexOf(self._settings_placeholder)
                if index >= 0:
                    current_theme = self._load_theme_preference()
                    self.settings_tab = self._create_settings_tab(current_theme)
                    # Theme change always connected
                    self.settings_tab.theme_changed.connect(self._on_theme_changed)
                    # Font scale change (Core feature — always connected)
                    if hasattr(self.settings_tab, 'scale_changed'):
                        self.settings_tab.scale_changed.connect(self._on_scale_changed)
                    # Global color saturation (SPEC-SAT-001 WI-6)
                    if hasattr(self.settings_tab, 'saturation_changed'):
                        self.settings_tab.saturation_changed.connect(self._on_saturation_changed)
                    if hasattr(self.settings_tab, 'sign_language_changed'):
                        self.settings_tab.sign_language_changed.connect(self._set_sign_language)
                    if hasattr(self.settings_tab, 'chart_display_changed'):
                        # td-iaqm.2.1: route Apply/Reset through the shared tail so
                        # it matches the remote path (chart views + icon views).
                        self.settings_tab.chart_display_changed.connect(self.apply_chart_display_settings)
                    if hasattr(self.settings_tab, 'background_changed'):
                        self.settings_tab.background_changed.connect(self._on_background_changed)
                    if hasattr(self.settings_tab, 'zodiac_changed'):
                        # A zodiac-mode Apply recomputes the whole chart (~750 ms
                        # measured, td-5qkks) — show the loading overlay.
                        self.settings_tab.zodiac_changed.connect(
                            lambda _mode: run_with_loading(
                                self, "Applying zodiac settings...",
                                self.zodiac_settings.apply_settings,
                                ("zodiac.mode", "zodiac.use_western_names")))
                    if hasattr(self.settings_tab, 'dasha_changed'):
                        self.settings_tab.dasha_changed.connect(self._on_dasha_settings_changed)
                    if hasattr(self.settings_tab, 'names_changed'):
                        self.settings_tab.names_changed.connect(
                            lambda _names: self.zodiac_settings.apply_settings(("zodiac.use_western_names",)))
                    if hasattr(self.settings_tab, 'ayanamsa_changed'):
                        self.settings_tab.ayanamsa_changed.connect(
                            lambda _ayan: self.zodiac_settings.apply_settings(("zodiac.ayanamsa_id",)))
                    if hasattr(self.settings_tab, 'house_system_changed'):
                        # A house-system Apply recomputes houses (~440 ms
                        # measured, td-5qkks) — show the loading overlay.
                        self.settings_tab.house_system_changed.connect(
                            lambda _house: run_with_loading(
                                self, "Applying house system...",
                                self.zodiac_settings.apply_settings,
                                ("zodiac.house_system",)))
                    if hasattr(self.settings_tab, 'house_display_mode_changed'):
                        self.settings_tab.house_display_mode_changed.connect(self._on_house_display_mode_changed)
                    if hasattr(self.settings_tab, 'font_sizes_changed'):
                        self.settings_tab.font_sizes_changed.connect(self._on_font_sizes_changed)
                    if hasattr(self.settings_tab, 'chart_display_sync_requested'):
                        self.settings_tab.chart_display_sync_requested.connect(self._update_chart_display_preview)
                    if hasattr(self.settings_tab, 'wheel_display_changed'):
                        self.settings_tab.wheel_display_changed.connect(self._on_wheel_display_changed)
                    if hasattr(self.settings_tab, 'wheel_display_sync_requested'):
                        self.settings_tab.wheel_display_sync_requested.connect(self._update_wheel_display_preview)
                    if hasattr(self.settings_tab, 'north_indian_display_changed'):
                        self.settings_tab.north_indian_display_changed.connect(self._on_north_indian_display_changed)
                    if hasattr(self.settings_tab, 'north_indian_display_sync_requested'):
                        self.settings_tab.north_indian_display_sync_requested.connect(self._update_north_indian_display_preview)
                    self.tab_widget.removeTab(index)
                    self.tab_widget.insertTab(index, self.settings_tab, "Settings")
                    # Only switch to this tab if user clicked it (not during preload)
                    if not self._preloading:
                        self.tab_widget.setCurrentIndex(index)
                    self._settings_placeholder = None
                    # (ai_reading_panel guard removed 2026-08-09: the panel is
                    # deprecated and never instantiated, so the hasattr was
                    # always False — see the _refresh_attr annotation below.)
                    if hasattr(self.settings_tab, 'folders_tab'):
                        self.settings_tab.folders_tab.folders_changed.connect(
                            self._on_chart_folders_changed
                        )
            except Exception as e:
                import traceback
                traceback.print_exc()
                if hasattr(self, '_settings_loading_label'):
                    self._settings_loading_label.setText("Settings failed to load")
                if hasattr(self, '_settings_progress_bar'):
                    self._settings_progress_bar.hide()
                QMessageBox.critical(
                    self,
                    "Settings Error",
                    f"Failed to load Settings tab:\n{e}",
                )

    def _create_edit_chart_widget(self):
        """Create EditChartPanel lazily on first tab click."""
        if hasattr(self, '_edit_chart_placeholder') and self._edit_chart_placeholder:
            index = self.tab_widget.indexOf(self._edit_chart_placeholder)
            if index >= 0:
                self.edit_chart_panel = EditChartPanel(self)
                self.tab_widget.removeTab(index)
                self.tab_widget.insertTab(index, self.edit_chart_panel, "New && Edit")
                if not self._preloading:
                    self.tab_widget.setCurrentIndex(index)
                self._edit_chart_placeholder = None
                if self.state.active_chart:
                    self.edit_chart_panel.load_from_gui()

    def _create_find_chart_widget(self):
        """Create Find Chart panel lazily (direct import, no background thread)."""
        if hasattr(self, '_find_chart_placeholder') and self._find_chart_placeholder:
            from panels.find_chart_panel import FindChartPanel

            index = self.tab_widget.indexOf(self._find_chart_placeholder)
            if index >= 0:
                self.find_chart_panel = FindChartPanel(self)
                self.find_chart_panel.chart_selected.connect(self._on_find_chart_selected)
                self.tab_widget.removeTab(index)
                self.tab_widget.insertTab(index, self.find_chart_panel, "Find Chart")
                # Only switch to this tab if user clicked it (not during preload)
                if not self._preloading:
                    self.tab_widget.setCurrentIndex(index)
                self._find_chart_placeholder = None
                if self._preloading or self._startup_phase:
                    QTimer.singleShot(100, self.find_chart_panel._load_cache_only)
                else:
                    QTimer.singleShot(100, self.find_chart_panel._load_cached_index)

    # ===== CLUSTER: TAB PRELOADING =====
    def _restore_last_active_tab(self):
        """Restore the last active main tab when the setting is enabled."""
        try:
            from managers.settings_manager import get_settings
            settings = get_settings()
            if not settings.get("ui.restore_last_tab", True):
                return
            idx = settings.get("ui.last_active_tab", 0)
            if isinstance(idx, int) and 0 <= idx < self.tab_widget.count():
                self.tab_widget.setCurrentIndex(idx)
        except Exception:
            pass

    def _get_preloadable_tabs(self):
        """Return set of tab names eligible for preloading. Override to extend."""
        return {"Settings", "Find Chart"}

    def _preload_popular_tabs(self):
        """Preload the top 3 most-used tabs that have deferred initialization.

        Reads tab_usage_counts from settings.  Only acts on tabs that are
        currently deferred (showEvent-deferred or placeholder lazy-loaded).
        Already-loaded tabs are skipped since they need no preloading.
        """
        if not self._tab_usage_counts:
            return

        preloadable = self._get_preloadable_tabs()

        # Sort by usage count descending, keep only preloadable tabs
        sorted_tabs = sorted(
            ((name, count) for name, count in self._tab_usage_counts.items()
             if name in preloadable),
            key=lambda x: x[1], reverse=True
        )

        if not sorted_tabs:
            return

        top3 = sorted_tabs[:3]

        # Block signals to prevent _on_tab_changed firing during preload
        self._preloading = True
        current_index = self.tab_widget.currentIndex()
        self.tab_widget.blockSignals(True)

        try:
            for tab_name, count in top3:
                self._preload_tab(tab_name)
        finally:
            # Restore original tab and unblock signals
            self.tab_widget.setCurrentIndex(current_index)
            self.tab_widget.blockSignals(False)
            self._preloading = False

    def _preload_tab(self, tab_name: str):
        """Preload a single deferred tab by name."""
        try:
            if tab_name == "Settings":
                if hasattr(self, '_settings_placeholder') and self._settings_placeholder:
                    self._create_settings_widget()

            elif tab_name == "Find Chart":
                if hasattr(self, '_find_chart_placeholder') and self._find_chart_placeholder:
                    self._create_find_chart_widget()

        except Exception as e:
            print(f"Error preloading {tab_name}: {e}")

    # ===== CLUSTER: WINDOW GEOMETRY & RESPONSIVE =====
    def _restore_window_geometry(self):
        """Restore saved window geometry, or fit to current screen if no saved state.

        Uses SettingsManager to load saved position/size. Validates that the saved
        geometry is actually visible on a connected monitor. Falls back to maximizing
        on the current screen if saved geometry is off-screen or unavailable.
        """
        from managers.settings_manager import get_settings
        settings = get_settings()

        # Try to restore saved geometry
        saved_pos = settings.get_window_position()
        saved_size = settings.get_window_size()
        remember = settings.get_remember_window_size()

        if remember and saved_pos and saved_size:
            saved_x, saved_y = saved_pos
            saved_w, saved_h = saved_size

            # Reject geometry that fills the full width OR full height of the
            # primary screen — saved before the sensible default was in place.
            screen = QApplication.primaryScreen()
            if screen:
                avail = screen.availableGeometry()
                too_wide = saved_w >= avail.width() * 0.95
                too_tall = saved_h >= avail.height() * 0.95
                if too_wide or too_tall:
                    self._fit_to_current_screen()
                    return

            # Validate: is the saved position on any connected screen?
            if self._is_geometry_on_screen(saved_x, saved_y, saved_w, saved_h):
                self.setGeometry(saved_x, saved_y, saved_w, saved_h)
                return

        # No saved geometry or off-screen: use available screen geometry
        self._fit_to_current_screen()

    def _is_geometry_on_screen(self, x, y, w, h):
        """Check if at least 100px of the window title bar is visible on any screen.

        This ensures the window can always be grabbed and moved by the user,
        even if most of it is off-screen.
        """
        from PySide6.QtCore import QRect
        window_top = QRect(x, y, max(w, 100), 50)  # Title bar region

        for screen in QApplication.screens():
            screen_geom = screen.availableGeometry()
            if screen_geom.intersects(window_top):
                return True
        return False

    def _fit_to_current_screen(self):
        """Place the window at 85%/88% of the screen the cursor is on (primary if unknown)."""
        from PySide6.QtGui import QCursor

        cursor_pos = QCursor.pos()
        target_screen = None
        for screen in QApplication.screens():
            if screen.geometry().contains(cursor_pos):
                target_screen = screen
                break

        # Fallback to primary screen
        if target_screen is None:
            target_screen = QApplication.primaryScreen()

        if target_screen:
            avail = target_screen.availableGeometry()
            w = int(avail.width() * 0.85)
            h = int(avail.height() * 0.88)
            x = avail.x() + (avail.width() - w) // 2
            y = avail.y() + (avail.height() - h) // 2
            self.setGeometry(x, y, w, h)
        else:
            # Ultimate fallback
            self.setGeometry(100, 100, 1600, 900)

    def _save_window_geometry(self):
        """Save current window geometry to settings for next launch."""
        from managers.settings_manager import get_settings
        settings = get_settings()

        if settings.get_remember_window_size():
            geom = self.geometry()
            settings.set_window_position(geom.x(), geom.y())
            settings.set_window_size(geom.width(), geom.height())

    def resizeEvent(self, event):
        """Handle window resize - responsive layout + profile button positioning."""
        super().resizeEvent(event)
        if hasattr(self, 'profile_button'):
            self.profile_button.move(self.width() - 50, 8)
            self.profile_button.raise_()

        # Responsive: auto-hide side panels when window is narrow (tiled)
        self._update_responsive_panels()

        # Keep the ORDER/fullscreen status controls at the chart view's right
        # edge as the window (and thus the chart column) resizes. Deferred once
        # so the side-panel show/hide above has settled its geometry first.
        self._align_status_controls()
        from PySide6.QtCore import QTimer as _QTimer
        _QTimer.singleShot(self.DRAWER_ANIM_MS + 40, self._align_status_controls)

    def _align_status_controls(self):
        """Right-align ORDER pill + fullscreen glyph with the chart view edge.

        The status bar spans the whole window, so ``addPermanentWidget`` parks
        the controls at the far right — over the side panels, not the chart. A
        width-only spacer to their right, sized to the gap between the chart
        stack's right edge and the status bar's right edge, slides them left so
        they sit under the chart column. Recomputed on resize because that gap
        (side-panel widths + spacing) changes when responsive panels hide/show.

        Global-coordinate math keeps it agnostic to which side panels are
        currently visible. Skipped while fullscreen (the stack is reparented
        out, its geometry stale) or off the Chart tab (stack hidden).
        """
        spacer = getattr(self, "_status_controls_spacer", None)
        if spacer is None:
            return
        fm = getattr(self, "view_float_manager", None)
        if fm is not None and fm.is_fullscreen:
            return
        stack = getattr(self, "chart_stack", None)
        if stack is None or not stack.isVisible():
            spacer.setFixedWidth(0)
            return
        from PySide6.QtCore import QPoint as _QPoint
        sb = self.statusBar()
        chart_right = stack.mapToGlobal(_QPoint(stack.width(), 0)).x()
        sb_right = sb.mapToGlobal(_QPoint(sb.width(), 0)).x()
        spacer.setFixedWidth(max(0, sb_right - chart_right))

    # -- fullscreen descriptor (SPEC-FSV-001 universal-fullscreen WI-2) ----

    def _chart_fullscreen_views(self):
        """Live QGraphicsViews on the CURRENT chart page, for save/refit.

        Pages 1/2 ARE graphics views; page 0 is a host exposing ``active_view``
        (the classic or vector South Indian child currently shown). Page 3 is a
        BodyAspectDualWidget holding TWO inner views — the body graph (always
        shown) plus the aspect South Indian view (only when its panel is
        toggled on); returning BOTH closes the shipped gap where the aspect view
        never refit in fullscreen. Page 4 (Cards of Truth) is a plain QWidget
        that lays out from its own width -> no graphics view to refit.
        """
        from PySide6.QtWidgets import QGraphicsView
        page = self.chart_stack.currentWidget()
        # Page 3 — the dual body/aspect widget (named body_graph_view for
        # historical reasons; it is a BodyAspectDualWidget).
        dual = getattr(self, "body_graph_view", None)
        if dual is not None and page is dual:
            views = []
            inner_body = getattr(dual, "body_graph_view", None)
            if isinstance(inner_body, QGraphicsView):
                views.append(inner_body)
            aspect = getattr(dual, "aspect_si_view", None)
            if isinstance(aspect, QGraphicsView) and aspect.isVisible():
                views.append(aspect)
            return views
        if isinstance(page, QGraphicsView):
            return [page]
        # Page 5 — the Human Design page (HDPanel) exposes its bodygraph as
        # ``.view`` (an HDBodygraphView / QGraphicsView), NOT ``active_view``.
        # Without this branch HD returned [] and never participated in the
        # save -> refit -> restore contract; it only worked because the graph
        # self-fits on showEvent, which can letterbox on a HiDPI fullscreen exit
        # (C7 fullscreen-exit bug). Return the graph so the manager refits it on
        # enter AND restores its transform on exit like every other page.
        hd = getattr(self, "human_design_view", None)
        if hd is not None and page is hd:
            graph = getattr(hd, "view", None)
            if isinstance(graph, QGraphicsView):
                return [graph]
            return []
        active = getattr(page, "active_view", None)
        if isinstance(active, QGraphicsView):
            return [active]
        return []

    def _chart_fullscreen_target(self):
        """Descriptor for the main chart stack (the Chart tab surface).

        cycle=True: F2 cycles the chart page (the global style broadcast).
        chart_stack.currentChanged is a refit_signal so a page switch (incl. F2)
        refits the newly shown page to the fullscreen viewport.
        """
        return {
            "widget": self.chart_stack,
            "layout": self.chart_content.layout(),
            "views": self._chart_fullscreen_views,
            "refit": True,
            "cycle": True,
            "refit_signals": [self.chart_stack.currentChanged],
            "on_enter": None,
            "on_exit": None,
        }

    # Threshold below which side panels auto-hide (px).
    # 1400 = enough room for chart (~445px) + all side panels (~955px).
    COMPACT_THRESHOLD = 1400
    DRAWER_ANIM_MS = 200

    def _reapply_compact_if_needed(self):
        """Re-apply compact button styles after any method that overwrites them.

        Methods like _update_toggle_button_styles() and _toggle_wheel_view()
        apply full-size styles. This re-applies compact styles if we're in
        compact mode, preventing buttons from reverting to stomped/stretched look.
        """
        if getattr(self, '_title_is_compact', False):
            from apps.widgets.chart_title_widget import set_chart_title_compact
            self._title_is_compact = False  # Force re-application
            set_chart_title_compact(self, True)

    def _update_responsive_panels(self):
        """Show/hide side panels based on window width for responsive tiling."""
        if not hasattr(self, '_side_panels'):
            return

        should_show = self.width() >= self.COMPACT_THRESHOLD

        if should_show == self._side_panels_visible:
            return  # No state change, avoid flicker

        self._side_panels_visible = should_show
        self._stop_all_anims()

        if should_show:
            # Entering full mode: restore all panels at their target widths
            for panel in self._side_panels:
                w = self._panel_target_widths[panel]
                panel.setMinimumWidth(w)
                panel.setMaximumWidth(w)
                panel.setVisible(True)
            self._left_toggle.setVisible(False)
            self._right_toggle.setVisible(False)
            self._left_drawer_open = False
            self._right_drawer_open = False
            # Restore full-size tab bar, memory panel, and title bar
            self.tab_widget.setStyleSheet(get_tab_bar_style(compact=False))
            if hasattr(self, 'memory_panel'):
                self.memory_panel.set_compact(False)
            from apps.widgets.chart_title_widget import set_chart_title_compact
            set_chart_title_compact(self, False)
        else:
            # Entering compact mode: hide all panels, show toggle buttons
            for panel in self._side_panels:
                panel.setVisible(False)
            self._left_toggle.setText("\u25b6")
            self._right_toggle.setText("\u25c0")
            self._left_toggle.setVisible(True)
            self._right_toggle.setVisible(True)
            self._left_drawer_open = False
            self._right_drawer_open = False
            # Switch to compact tab bar, memory panel, and title bar
            self.tab_widget.setStyleSheet(get_tab_bar_style(compact=True))
            if hasattr(self, 'memory_panel'):
                self.memory_panel.set_compact(True)
            from apps.widgets.chart_title_widget import set_chart_title_compact
            set_chart_title_compact(self, True)

    # ===== CLUSTER: LICENSE REFRESH =====
    def _refresh_license(self):
        """Silently refresh the license token in a background thread."""
        if not hasattr(self, '_license_state') or self._license_state is None:
            return

        # Free-trial session: there is no key to re-validate. Re-evaluate the
        # trial window locally (no network, no worker). While it is still open
        # keep granting; once it ends, re-gate exactly like a lapsed license.
        # start_if_absent=False so a consumed trial can never be revived here.
        if getattr(self._license_state, "is_trial", False):
            from managers.license_key import trial_state
            from managers.license_manager import LicenseState
            still = trial_state(start_if_absent=False)
            self._on_license_refresh_done(still if still is not None else LicenseState())
            return

        # Don't start a new refresh if the previous one is still running
        if hasattr(self, '_license_refresh_worker') and self._license_refresh_worker and self._license_refresh_worker.isRunning():
            return

        # Re-validate the stored license KEY (KeyRefreshWorker enforces the
        # grace bound). There is no account/Firebase refresh path any more.
        from managers.license_workers import KeyRefreshWorker
        self._license_refresh_worker = KeyRefreshWorker(self._license_state)
        self._license_refresh_worker.finished.connect(self._on_license_refresh_done)
        self._license_refresh_worker.error.connect(
            lambda msg: print(f"Error: license refresh failed: {msg}")
        )
        self._license_refresh_worker.start()

    def _on_license_refresh_done(self, updated_state):
        """Handle license refresh result (called on main thread via signal)."""
        self._license_state = updated_state
        if updated_state.is_licensed:
            return

        # A bundled session that loses its license mid-run (subscription lapsed,
        # key revoked, grace elapsed) must actually re-gate, not merely warn:
        # re-prompt for a key and exit if declined, mirroring the boot gate.
        # Inert for the anonymous source build. Same predicate as the boot gate
        # (_is_bundled): a frozen build always re-gates and the env alone can
        # neither enable nor disable it.
        _bundled = _is_bundled()
        if _bundled:
            from apps.widgets.key_dialog import KeyDialog
            dialog = KeyDialog(
                parent=self,
                message="Your access has ended. Enter your license key to continue.",
                show_continue_without_account=False,
            )
            if dialog.exec() == KeyDialog.DialogCode.Accepted:
                self._license_state = dialog.get_license_state()
                return
            sys.exit(0)

        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(
            self, "Subscription Expired",
            "Your Varuna360 subscription has expired.\n\n"
            "Please renew at 360heartsinthesky.com to continue.",
            QMessageBox.StandardButton.Ok,
        )

    # ===== CLUSTER: DASHA / VEDANGA / VIMSHOTTARI =====
    # w3-2 (SPEC-DSH-002 D-W3-2): the eleven one-line dasha signal delegators
    # (_set_vedanga_level, _set_vimshottari_level, _navigate_*, _on_vedanga_clicked,
    # _on_vimshottari_clicked, _on_*_context_menu, _on_right_title_clicked) are
    # retired. DashaPanelWidget's signals now connect straight to the manager's
    # public methods in DashaManager.build_panel(). _cycle_right_dasha (F7 menu
    # action + harness) and _change_dasha_ayanamsa (real logic) stay.

    # === NISARGA DASHA (F7 toggle) ===

    def _cycle_right_dasha(self):
        """Cycle the right dasha panel through its modes (F7 / swap button).

        Order lives in DashaManager.VALID_RIGHT_MODES; W5b's "zr" joins the
        cycle automatically. The dispatcher reshapes and sets dasha_state.right_mode.
        """
        order = self.dasha_manager.VALID_RIGHT_MODES
        cur = self.dasha_manager.right_mode
        nxt = order[(order.index(cur) + 1) % len(order)] if cur in order else order[0]
        self.dasha_manager.configure_right_panel(nxt)
        from managers.settings_manager import get_settings
        get_settings().persist_runtime_change("dasha.right.mode", self.dasha_manager.right_mode)

    # w3-2 (SPEC-DSH-002 D-W3-3): the two per-mode right-panel configure helpers
    # (nisarga / vimshottari) are retired. The right-panel reshape for every mode
    # is now DashaManager.configure_right_panel feeding
    # right_panel.set_shape(**_RIGHT_SHAPES[mode]) + the per-mode data resets +
    # the renderer.

    def _on_dasha_settings_changed(self):
        """Live-apply dasha ayanamsha/mode settings from the Settings tab (Apply).

        Sole APPLIER of the dasha.* route (SPEC-DSH-002). Stops and clears the
        manager's deferred reconciliation FIRST — the Settings tab's own set()
        calls filled _pending_settings synchronously through the manager
        subscriber, and this handler applies them once so nothing is handled
        twice. Then compares the OLD runtime mode to the setting exactly as
        before, driving state + relist through the manager API (offset PRESERVED
        on Apply: reset="navigation").
        """
        from managers.settings_manager import get_settings
        s = get_settings()
        dm = self.dasha_manager

        # Cancel the deferred reconciliation for the keys Apply handles itself
        # (through the manager API, not its private fields — Rule 4b).
        dm.cancel_pending_reconciliation()

        self.nakshatra_coords = s.get("zodiac.nakshatra_coords", "neither")

        # SPEC-DSH-003: adopt the year length FIRST, state-only, so every
        # re-list below runs on it (the same ordering rule as the right ayanamsa).
        try:
            dm.set_year_length(s.get("dasha.year_length.nakshatra", "saura"), relist=False)
        except ValueError as exc:      # corrupt stored key: warn, keep the current year
            import logging
            logging.getLogger(__name__).warning("Ignoring dasha year length on Apply: %s", exc)

        # LEFT (Vedanga): always an ayanamsha; keep the 120-year offset.
        dm.set_ayanamsa("left", s.get("dasha.left.ayanamsa_id", 100),
                        persist=False, relist=True, reset="navigation")

        # RIGHT (Vimshottari / Nisarga / ZR): compare OLD runtime mode to setting.
        old_mode = dm.right_mode
        new_mode = s.get("dasha.right.mode", "nisarga")
        right_id = s.get("dasha.right.ayanamsa_id", 98)
        if new_mode != old_mode:
            # State-only adopt the id, then the dispatcher reshapes + resets.
            dm.set_ayanamsa("right", right_id, persist=False, relist=False, reset="none")
            dm.configure_right_panel(new_mode)
        elif new_mode == "vimshottari":
            # Mode unchanged, only the ayanamsha changed: recompute Vimshottari.
            dm.set_ayanamsa("right", right_id, persist=False, relist=True, reset="navigation")
        elif new_mode == "zr":
            # Mode unchanged, ZR options may have changed: adopt id (state-only),
            # reset the ZR drill, and re-list through the dispatcher.
            dm.set_ayanamsa("right", right_id, persist=False, relist=False, reset="none")
            dm.reset_mode_entry("zr")
            dm.update_right_panel()
        else:  # nisarga unchanged: fixed ages, ayanamsha irrelevant.
            dm.set_ayanamsa("right", right_id, persist=False, relist=False, reset="none")

    def _change_dasha_ayanamsa(self, panel):
        """Open ayanamsa selection dialog for a dasha panel and recalculate.
        Also handles the chart zodiac setting (tropical/sidereal).

        NOT @_batched: the body runs dialog.exec() (a nested event loop). A batch
        must never span that — it would suppress every controller and hold queued
        dispatches hostage while the dialog sits open (MED-2). Only the accepted
        post-exec mutation+recalc is batched, below."""
        from apps.widgets.ayanamsa_dialog import AyanamsaDialog
        if panel == "vedanga":
            current_ayanamsa = self.dasha_manager.ayanamsa("left")
        else:
            current_ayanamsa = self.dasha_manager.ayanamsa("right")

        dialog = AyanamsaDialog(self, current_ayanamsa=current_ayanamsa,
                                current_chart_zodiac=self.chart_zodiac, dasha_only=True)
        if dialog.exec():
            ayanamsa_id, chart_zodiac = dialog.get_selection()

            # Dasha half (SPEC-DSH-002): one manager call adopts the id
            # (lock-respecting persist), zeroes navigation incl. the 120-year
            # offset (reset="full"), and re-lists that side through its current
            # mode with title + cycle label refreshed. The level-button visual is
            # the only widget state the caller still sets.
            if panel == "vedanga":
                self.dasha_manager.set_ayanamsa(
                    "left", ayanamsa_id, persist=True, relist=True, reset="full")
                self.dasha_manager.sync_level_buttons("left")
            else:
                self.dasha_manager.set_ayanamsa(
                    "right", ayanamsa_id, persist=True, relist=True, reset="full")
                self.dasha_manager.sync_level_buttons("right")

    # === PANEL UPDATE METHODS ===

    def _populate_dasha_after_startup(self):
        """Populate both dasha panels after session restore."""
        self._update_vedanga_dasha()
        self._update_vimshottari_dasha()

    def _update_vedanga_dasha(self):
        """Update Vedanga dasha list. Delegates to DashaManager."""
        self.dasha_manager.update_vedanga_dasha()

    def _update_vimshottari_dasha(self):
        """Re-list the right dasha panel for the current mode (no reshape).

        Thin alias kept for its many callers (_finalize_chart_load, settings);
        the routing lives in the one dispatcher (SPEC-ZR-001 §3.6).
        """
        self.dasha_manager.update_right_panel()

    def _get_sign_ruler(self, sign):
        """Get sign ruler. Phase 4 W5: now uses core.sidereal_helpers directly
        (was delegating through panel_manager before W5 cleanup)."""
        from core.sidereal_helpers import get_sign_ruler
        return get_sign_ruler(sign)

    def _update_all_panels(self):
        """Phase 4 W5: no-op stub. All 12 info/analysis panels now self-update
        via PanelController subscriptions to ChartState.state_changed.

        Nakshatra and Antikythera are not yet on controllers — explicit calls
        cover their refresh path. To avoid blocking the event loop on every
        chart load (~0.5s each), they are only updated when their tab is
        visible; otherwise they are marked dirty and refreshed on tab switch.
        """
        if not self.state.active_chart:
            return
        chart_id = id(self.state.active_chart)
        current_tab = self.tab_widget.currentWidget()
        for attr in ('nakshatra_panel', 'antikythera_panel'):
            panel = getattr(self, attr, None)
            if panel is None:
                continue
            if current_tab is panel:
                panel.update_from_chart(self.state.active_chart, aditya_mode=self.state.aditya_mode)
                panel._chart_dirty = False
                panel._last_rendered_chart_id = chart_id
            else:
                if getattr(panel, '_last_rendered_chart_id', None) != chart_id:
                    panel._chart_dirty = True

    # === FILE OPERATIONS ===

    # ===== CLUSTER: CHART-ELEMENT DIALOGS (planet / sector / sign) =====
    def _show_planet_placements(self):
        """Show dialog with table of all planetary positions."""
        chart = self.state.active_chart
        if not chart:
            QMessageBox.warning(self, "No Chart", "No chart data loaded. Please open a chart first.")
            return

        # Get person name from various sources
        person_name = "Unknown"
        if self.current_chart_data:
            person_name = self.current_chart_data.get('name', person_name)
        if hasattr(self, 'person_name') and self.person_name:
            person_name = self.person_name

        dasha_chain = []
        try:
            from core.vimshottari_dasha import calculate_dasha_from_birth_data
            from AI_tools.AI_main_function.dasha import get_dasha_params
            params = get_dasha_params(
                self.current_chart_data,
                is_human_design=self.is_human_design,
            )
            if all([params['year'], params['month'], params['day']]):
                entries = calculate_dasha_from_birth_data(
                    params['year'], params['month'], params['day'],
                    params['hour'], params['minute'], params['second'],
                    dlevels=3,
                    ayanamsa=self.dasha_manager.ayanamsa("left"),
                    tz_offset_hours=params['tz_offset'],
                    moon_jd_override=params['moon_jd_override'],
                    nak_mode=getattr(self, 'nakshatra_coords', 'neither'),
                    year_length=self.dasha_manager.year_length,
                )
                for depth in range(3):
                    for e in entries:
                        if e.get('is_current') and e['lord'].count('/') + 1 == depth + 1:
                            dasha_chain.append(e['lord'].split('/')[-1])
                            break
        except Exception:
            pass

        from managers.settings_manager import get_settings
        _sm = get_settings()
        # SPEC-COT-001 D-5: solar_system is the verified order. The old
        # inline "vedic" fallback disagreed with the F2 view and mislabelled
        # three of the seven main cards in this table.
        cot_order = _sm.get("cot.planet_order", "solar_system")

        dialog = PlanetPlacementsDialog(
            parent=self,
            chart=chart,
            aditya_mode=self.state.aditya_mode,
            chart_data=self.current_chart_data,
            person_name=person_name,
            use_western_names=self.use_western_names,
            nakshatra_ayanamsa_id=self.dasha_manager.ayanamsa("left"),
            current_dasha_chain=dasha_chain,
            cot_planet_order=cot_order,
        )
        dialog.show()

    def _set_sign_language(self, language: str):
        """Set the language for Western sign names."""
        if getattr(getattr(self, "zodiac_settings", None), "_ready", False):
            self.zodiac_settings.set_runtime("zodiac.sign_language", language)
            return
        self.sign_language = language
        try:
            from managers.settings_manager import get_settings
            get_settings().set("zodiac.sign_language", language)
        except Exception:
            pass

        if hasattr(self, "_language_actions"):
            for code, action in self._language_actions.items():
                action.setChecked(code == language)

        # Update all chart views
        self.chart_view.sign_language = language
        self.wheel_view.sign_language = language
        self.north_indian_view.sign_language = language

        # Redraw charts if data is loaded
        if self.state.active_chart:
            self.chart_view.draw_full_chart()
            self.chart_view.ensure_visible()
            self.wheel_view.draw_wheel()
            self.wheel_view.ensure_visible()
            self.north_indian_view.draw_chart()
            self.north_indian_view.ensure_visible()

        # Pure relabel signal: language only affects the western label set,
        # so listeners repopulate without recomputing (td-cm8o).
        self.sign_names_changed.emit(self.state.aditya_mode)

    def _dialog_parent(self):
        """Parent for chart-surface popups: the fullscreen container while
        fullscreen, else the main window. A modal parented to the main window
        while fullscreen drops the frameless container to the back (chart
        vanishes, layout scrambles); see ViewFloatManager.dialog_parent."""
        fm = getattr(self, "view_float_manager", None)
        if fm is not None:
            return fm.dialog_parent(self)
        return self

    def _show_planet_dialog(self, planet_name, planet_info):
        """Show popup dialog with planet details when planet is double-clicked"""
        planet_pixmap = self.chart_view.load_planet_image(planet_name, size=64)
        current_variation = self.chart_view.get_planet_variation(planet_name)
        dialog = PlanetInfoDialog(planet_name, planet_info, planet_pixmap,
                                  current_variation=current_variation,
                                  parent=self._dialog_parent())

        # Capture variation BEFORE connecting signal (to avoid applying during deletion)
        pending_variation = None

        def capture_variation(pname, var_num):
            nonlocal pending_variation
            pending_variation = (pname, var_num)

        # Connect to capture function instead of directly applying
        dialog.variation_applied.connect(capture_variation)
        dialog.exec()

        # CRITICAL: Delete dialog BEFORE chart redraw
        dialog.deleteLater()
        dialog = None

        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()

        # Reset drag state on ALL views after dialog closes to prevent "stuck pan mode"
        self._reset_all_views_drag_state()

        # Apply variation after dialog is fully destroyed
        if pending_variation:
            pname, var_num = pending_variation
            self._apply_planet_variation(pname, var_num)

    def _show_sector_dialog(self, sign_name, ring, being_type):
        """Show popup dialog with hora/trimsamsa structure when sector is double-clicked.

        SPEC-AVA-003 §4.2: the avastha numbers come from the ONE spine via the
        (possibly lazy) Avastha controller, and the popup opens at the layer of
        the clicked ring. _ensure_controller may CREATE the deferred controller
        but does NOT refresh the panel (core_gui_qt.py: sets _pending_chart_refresh)."""
        ctrl = self._ensure_controller('avastha')
        summaries = (ctrl.sign_popup_summaries(sign_name, ring, being_type)
                     if ctrl else None)
        dialog = SectorInfoDialog(sign_name, focus_ring=ring, focus_type=being_type,
                                  avastha_summaries=summaries, layer=ring,
                                  view=(ctrl.current_view() if ctrl else None), parent=self._dialog_parent())
        dialog.exec()

        dialog.deleteLater()
        dialog = None

        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()

        self._reset_all_views_drag_state()

    def _apply_planet_variation(self, planet_name, variation_num):
        """Apply the selected planet icon variation to the chart"""
        self.chart_view.set_planet_variation(planet_name, variation_num)
        self.statusBar().showMessage(f"{planet_name} icon changed to variation {variation_num}")

    def _show_sign_popup(self, zodiac_index, _variation=None):
        """A sign icon click opens the sector popup at the Sign layer (SPEC-AVA-003
        v1.3, D-26). zodiac_index is the Aditya number 0..11 (Aries = Dhata = #1
        in every mode, SPEC-ZOD-001), never mode-shifted; the icon-variation arg
        is ignored (the icon browser is parked, D-28)."""
        self._show_sector_dialog(ADITYA_NAMES[zodiac_index], None, None)

    def _reset_all_views_drag_state(self):
        """Reset drag state on all chart views to prevent 'stuck pan mode' after dialogs."""
        from PySide6.QtWidgets import QGraphicsView
        for view_name in ('chart_view', 'wheel_view', 'north_indian_view'):
            view = getattr(self, view_name, None)
            if view and hasattr(view, '_is_dragging'):
                view._is_dragging = False
                view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
                view.viewport().setCursor(Qt.CursorShape.ArrowCursor)

    # ===== CLUSTER: CHART-VIEW STATE MACHINE =====
    def _toggle_wheel_view(self):
        """F2 / view-cycler: advance over the EXPLICIT five-view ring
        0 South → 1 Wheel → 2 North → 3 Body → 6 Nakshatra → 0.

        SPEC-BAR-001 D-23(d) + SPEC-NAK-LITE-001: CARDS (index 4) and Human
        Design (index 5) are NOT cyclers; the Nakshatra wheel (index 6) IS,
        appended at the end. The ring is (0,1,2,3,6); index 4 is never
        indexed by the ring arithmetic. From Cards (current == 4) F2 returns
        to the REMEMBERED non-Cards view, then subsequent F2 continues the
        ring from there. Both bars share this method, so removing Cards from
        the cycle removes it consistently for both.
        """
        # td-iopy: ring derived from INV-14 (VIEW_STACK_INDEX), never a literal
        # (0,1,2,3) — a new view added to the ring must not be silently dropped
        # (SPEC-COT-001 §3.3 four-view-hardcode trap).
        # td-sy9e: when an aux tab is on screen the ring is restricted to what
        # its visible surface can mirror — otherwise North->Body is a press
        # that visibly does NOTHING on the Transit/SR pages (they support only
        # the zodiac trio and skip the body_graph broadcast).
        RING = self._f2_ring()
        current = self.chart_stack.currentIndex()
        if current not in RING:
            # Off the ring (Cards, index 4) — F2 returns to the remembered
            # non-Cards view; never a raw 4→0 (Sol r3 BLOCKER).
            target = getattr(self, "_last_chart_view_index", RING[0])
            if target not in RING:
                # td-sy9e review P1: the remembered view (e.g. Body) may not
                # exist on the restricted surface — landing there would be the
                # dead press again. Clamp to the ring's first view.
                target = RING[0]
        else:
            pos = RING.index(current)
            target = RING[(pos + 1) % len(RING)]
        self._activate_chart_view(target)

    def _f2_ring(self):
        """The F2 ring for the surface the user is LOOKING at (td-sy9e).

        Chart stack on screen (Chart tab, or fullscreen float of the stack):
        the full INV-14 ring. Aux tab on screen: only the views its visible
        surface declares in supported_chart_views(), so no ring step is a
        visible no-op (North->Body on Transit/SR was a dead press). Falls back
        to the full ring when the surface declares nothing recognisable.
        """
        from state.chart_state import F2_RING_INDICES, VIEW_STACK_INDEX
        if self.chart_stack.isVisible():
            return F2_RING_INDICES
        surface = self.tab_widget.currentWidget()
        # The Predictive Tools tab hosts subpages; the user sees the current
        # subpage (Transit / Solar Return / eclipse-internal), not the host.
        stack = getattr(surface, 'content_stack', None)
        if stack is not None:
            page = stack.currentWidget()
            if page is not None and hasattr(page, 'supported_chart_views'):
                surface = page
        supported = getattr(surface, 'supported_chart_views', None)
        if supported is None:
            return F2_RING_INDICES
        # INV-14: consume the ONE style->index map, never re-declare it inline
        # (a stale 4-view literal here silently dropped any newly-added view).
        ring = tuple(i for i in F2_RING_INDICES
                     if i in {VIEW_STACK_INDEX.get(s) for s in supported()})
        return ring or F2_RING_INDICES

    def _activate_chart_view(self, index: int):
        """SPEC-BAR-001 D-23(d): the ONE direct view-activation primitive —
        dispatch + lazy data push + cycler render + persistence, WITHOUT
        walking the ring. Walking (repeated _toggle_wheel_view calls) was the
        startup-restore / remote infinite-loop blocker once Cards (index 4)
        stopped being reachable by ring arithmetic. Every entry point —
        _toggle_wheel_view, _switch_to_chart_index, _toggle_cards_view — lands
        here.

        For a normal view (0..3) it records ``_last_chart_view_index`` so the
        CARDS button can return to it; index 4 (Cards) leaves that memory
        intact so the return target survives.

        td-sy9e: the expensive PAINT work (varga repaint of every main view,
        transit overlay push, body/HD data push) runs only while the chart
        stack is actually on screen. On an aux tab (Transit, Solar Return,
        AI Tools...) those five views are invisible and repainting them per
        F2 press was most of the perceived lag; instead the views are marked
        stale and repainted once, on return to the Chart tab
        (_repaint_main_views_if_stale). Dispatch, cycler chrome, persistence
        and the aux-panel broadcast stay unconditional — they are what the
        visible panel needs.
        """
        from state.events import SetChartViewStyle
        views_on_screen = self.chart_stack.isVisible()
        self.chart_stack.setCurrentIndex(index)
        if index not in (4, 5):
            self._last_chart_view_index = index

        if index == 0:
            # South Indian
            self.state.dispatch(SetChartViewStyle(style="south_indian"))
            self._render_view_cycle_controls()
            if views_on_screen:
                self._push_transit_state(getattr(self, 'chart_view', None))
            else:
                self._main_views_stale = True
            self.statusBar().showMessage("Switched to South Indian view")

        elif index == 1:
            # Wheel
            self.state.dispatch(SetChartViewStyle(style="wheel"))
            self._render_view_cycle_controls()
            # Chart-Everywhere Issue 2c: prefer state.active_chart when available.
            if views_on_screen and self.state.active_chart is not None:
                # td-ijjf: rendered with no varga code, so F2 off a D-10
                # South Indian chart used to land on a D-1 wheel.
                self._apply_current_varga()
                self.wheel_view.ensure_visible()
            elif not views_on_screen:
                self._main_views_stale = True
            if views_on_screen:
                self._push_transit_state(getattr(self, 'wheel_view', None))
            self.statusBar().showMessage("Switched to Wheel view")

        elif index == 2:
            # North Indian
            self.state.dispatch(SetChartViewStyle(style="north_indian"))
            self._render_view_cycle_controls()
            if views_on_screen and self.state.active_chart is not None:
                # td-ijjf: same hole on the second leg of the F2 cycle.
                self._apply_current_varga()
                self.north_indian_view.ensure_visible()
            elif not views_on_screen:
                self._main_views_stale = True
            if views_on_screen:
                self._push_transit_state(getattr(self, 'north_indian_view', None))
            self.statusBar().showMessage("Switched to North Indian view")

        elif index == 3:
            # Body Graph (SPEC-BODY-001). V1 has NO transit overlay, so unlike
            # the wheel/north branches it must NOT call update_transit_overlay.
            self.state.dispatch(SetChartViewStyle(style="body_graph"))
            self._render_view_cycle_controls()
            if not views_on_screen:
                self._main_views_stale = True
            # body_graph_view.update_from_chart absorbs ayanamsa_offset via **_kw.
            elif self.state.active_chart is not None and hasattr(self, 'body_graph_view'):
                ayanamsa_off = self.chart_ayanamsa_offset if self.state.aditya_mode == "sidereal" else 0.0
                self.body_graph_view.update_from_chart(self.state.active_chart,
                                                       use_western_names=getattr(self, 'use_western_names', False),
                                                       ayanamsa_offset=ayanamsa_off,
                                                       aditya_mode=self.state.aditya_mode,
                                                       gender=self._current_body_gender(),
                                                       varga_code=self.body_graph_view._varga_code)
                self.body_graph_view.ensure_visible()
            self.statusBar().showMessage("Switched to Body Graph view")

        elif index == 4:
            # Cards of Truth (SPEC-COT-001). Like the body-graph branch it has
            # NO transit overlay, so it must not call _push_transit_state.
            self.state.dispatch(SetChartViewStyle(style="cards_of_truth"))
            self._render_view_cycle_controls()
            if not views_on_screen:
                self._main_views_stale = True
            # Lazy chart data push through the ONE varga writer, so landing on
            # this view shows the active division rather than silently D-1.
            elif self.state.active_chart is not None and hasattr(self, 'cards_of_truth_view'):
                self._apply_current_varga()
                self.cards_of_truth_view.ensure_visible()
            self.statusBar().showMessage("Switched to Cards of Truth view")

        elif index == 5:
            # Human Design BodyGraph (SPEC-HD-001). Like cards/body it has NO
            # transit overlay. Fed the HDModel dict from hd_manager (the ONE
            # producer, byte-identical to the CLI/remote), never a Chart object.
            self.state.dispatch(SetChartViewStyle(style="human_design"))
            self._render_view_cycle_controls()
            if hasattr(self, 'hd_manager'):
                # push_to_view builds the model and tolerates a producer failure
                # (never crashes this shortcut-driven branch); feeds the MODEL,
                # never a Chart.
                self.hd_manager.push_to_view()
            self.statusBar().showMessage("Switched to Human Design view")

        elif index == 6:
            # Restricted Nakshatra wheel (SPEC-NAK-LITE-001). Sidereal, no varga
            # and no transit overlay in Core, so like body/cards it must NOT call
            # _push_transit_state. The panel ignores varga; a plain chart push.
            self.state.dispatch(SetChartViewStyle(style="nakshatra"))
            self._render_view_cycle_controls()
            if not views_on_screen:
                self._main_views_stale = True
            elif self.state.active_chart is not None and hasattr(self, 'nakshatra_core_panel'):
                self.nakshatra_core_panel.update_from_chart(self.state.active_chart)
                self.nakshatra_core_panel.wheel_view.ensure_visible()
            self.statusBar().showMessage("Switched to Nakshatra view")

        # Persist chart view preference so it survives app restart (respects
        # lock). td-iopy: debounced — a burst of F2 presses coalesces to ONE
        # disk write instead of one synchronous write per keypress; flushed on
        # close (closeEvent) so a fast quit still records the settled view.
        if not getattr(self, '_suppress_view_persist', False):
            self._debounce_view_persist(self.state.chart_view_style)

        # td-iopy SINGLE BROADCAST CHOKE POINT: every entry path (F2 cycle,
        # wheel_btn, Alt+W, startup restore, remote set_chart_view) already lands
        # here, so sync the auxiliary panels to the settled view HERE rather than
        # only in _cycle_chart_view. _suppress_view_broadcast is set only where a
        # broadcast is redundant or premature (see startup restore).
        if not getattr(self, '_suppress_view_broadcast', False):
            self._broadcast_chart_view(self.state.chart_view_style)

        # The pill's nakshatra ayanamsha token is view-aware (td-bu8s BUG4): the
        # Nakshatra view names the zodiac ayanamsha, others the left-dasha one.
        # Refresh it on every view switch so the token is never stale. Every
        # real host defines _update_title (ChartGUI; ProChartGUI subclasses it),
        # so this stays UNCONDITIONAL/fail-loud — a future rename must break a
        # test, not silently stale the pill. Test cycle hosts provide the method.
        self._update_title()

        # Re-apply compact styles if in compact mode (prevents stomped buttons)
        self._reapply_compact_if_needed()

        if self.time_adjust_widget and hasattr(self.time_adjust_widget, 'update_save_button_state'):
            self.time_adjust_widget.update_save_button_state()
            # A transit/view toggle changes whether the readout applies and
            # whether Revert should be live; recompute the whole readout state,
            # not just Save (else a stale readout + wrongly-enabled Revert
            # survive the transition).
            if self.time_adjust_widget.isVisible():
                self.time_adjust_widget.refresh_preview()

        # SPEC-VGC-001 §4.3 + SPEC-VGO-001 INV-8: the toggle greys out only
        # on the body graph now, and its tooltip names the surface of
        # whichever view is visible. The FLAG is untouched — F2 away and back
        # restores the second chart through _apply_current_varga.
        self._sync_varga_center_button()

    def _toggle_cards_view(self):
        """SPEC-BAR-001 D-23(d): the CARDS button / Alt+K. Not on Cards →
        show Cards and light it; on Cards → return to the remembered
        non-Cards view and unlight. Never walks the ring, so it cannot loop."""
        if self.chart_stack.currentIndex() == 4:
            self._activate_chart_view(getattr(self, "_last_chart_view_index", 0))
        else:
            self._activate_chart_view(4)

    def _toggle_hd_bodygraph_view(self):
        """SPEC-HD-001: the Human Design page (index 5), Ctrl+Shift+H only.
        Not on HD -> show it; on HD -> return to the remembered non-HD/non-Cards
        view. Distinct from _toggle_human_design (the astrology -88 recalc mode);
        this only switches the chart-stack page (pre-mortem F4 naming trap)."""
        if self.chart_stack.currentIndex() == 5:
            self._activate_chart_view(getattr(self, "_last_chart_view_index", 0))
        else:
            self._activate_chart_view(5)

    def _set_hd_button_label(self, text):
        """Drive the relocated HUMAN DESIGN button's caption (C7 cycle). The two
        captions live in the 'hd' ladder row; set_base_label swaps the logical
        variant. Guarded — the button/attr may be absent (legacy bar, headless)."""
        btn = getattr(self, "human_design_btn", None)
        if btn is not None and hasattr(btn, "set_base_label"):
            try:
                btn.set_base_label(text)
            except Exception:
                pass

    def _cycle_human_design(self):
        """C7: the ONE HUMAN DESIGN control — a 3-state cycle on the left-group
        button (and Ctrl+Shift+H):

          wheel/normal  --click-->  bodygraph page (index 5), label "HUMAN DESIGN"
          bodygraph     --click-->  -88 Design astrology chart, label "DESIGN CHART"
          Design chart  --click-->  back to the wheel, label "HUMAN DESIGN"

        State is read from (on the bodygraph page?) and (is_human_design, the -88
        recalc flag). The bodygraph page and the -88 chart are two different
        mechanisms (a chart-stack page vs a chart recompute, pre-mortem F4), so the
        cycle drives each independently; the button's lit state (bind_state) tracks
        both."""
        from state.chart_state import VIEW_STACK_INDEX
        hd_page = VIEW_STACK_INDEX["human_design"]
        on_bodygraph = self.chart_stack.currentIndex() == hd_page

        if on_bodygraph:
            # bodygraph -> -88 Design chart: leave the HD page to a normal view,
            # then turn the -88 recalc ON (it renders in-place on that view).
            self._activate_chart_view(getattr(self, "_last_chart_view_index", 0))
            if not self.is_human_design:
                self._toggle_human_design()
            self._set_hd_button_label("DESIGN CHART")
        elif self.is_human_design:
            # -88 Design chart -> wheel: turn the -88 recalc OFF.
            self._toggle_human_design()
            self._set_hd_button_label("HUMAN DESIGN")
        else:
            # wheel/normal -> bodygraph page.
            self._activate_chart_view(hd_page)
            self._set_hd_button_label("HUMAN DESIGN")

    def _render_view_cycle_controls(self):
        """SPEC-BAR-001 M3 W1: view-segment label/lit + dual-capsule
        visibility, called from every cycler branch RIGHT AFTER its dispatch
        — before the branch's data pushes, which can pump the event loop
        (_apply_current_varga), so a later write would paint a frame of
        stale label. v2: one idempotent render via the W4 sync. Legacy: the
        exact old write set — label/style/transit always, dual text+tooltip
        only when entering the wheel view (the old bar's behavior verbatim).
        """
        if hasattr(getattr(self, 'chart_title_widget', None), 'render_state'):
            self._sync_dual_rim_button_text()
            return
        self._legacy_view_cycle_styles()
        if hasattr(self, 'dual_rim_btn'):
            if self.chart_stack.currentIndex() == 1:
                self.dual_rim_btn.setVisible(True)
                self._sync_dual_rim_button_text()
            else:
                self.dual_rim_btn.setVisible(False)

    def _legacy_view_cycle_styles(self):
        """OLD-BAR ONLY (ui.action_bar_v2=False): the view-cycler button's
        label/style writes, consolidated from the five branches they used to
        live in. The label names the NEXT view in the cycle; the button is
        styled active everywhere but South Indian. Deleted with the legacy
        construction at M6 (D-15).
        """
        if not hasattr(self, 'wheel_btn'):
            return
        idx = self.chart_stack.currentIndex()

        # Theme-adaptive button styles — SPEC-THM-001 E5: module-level import.
        _t = get_theme_colors()
        active_style = desat_qss(f"""
            QPushButton {{
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                font-size: {scaled_px(12)}px;
                border: none;
                border-radius: 8px;
                padding: 8px 12px;
            }}
            QPushButton:hover {{
                background-color: #45A049;
            }}
        """)
        inactive_style = f"""
            QPushButton {{
                background-color: {_t["secondary"]};
                color: {_t["secondary_text"]};
                font-size: {scaled_px(12)}px;
                border: 1px solid {_t["primary"]};
                border-radius: 8px;
                padding: 8px 12px;
            }}
            QPushButton:hover {{
                background-color: {_t["primary"]};
                color: {_t["primary_text"]};
            }}
        """

        # SPEC-BAR-001 D-23(d): CARDS left the F2 cycle (five-view ring now:
        # South, Wheel, North, Body, Nakshatra — SPEC-NAK-LITE-001),
        # so this legacy cycler drops "❐ Cards" as a NEXT variant. Two cases,
        # mirroring the v2 bar: on a normal view the label names the NEXT view;
        # while Cards (index 4) is active the label names the REMEMBERED view's
        # OWN name (its own glyph), because F2 returns to that view itself.
        # Ring [0,1,2,3,6]: South→Wheel→North→Body→Nakshatra→South (td-bu8s BUG1;
        # index 6 was missing so Nakshatra fell through to "◎ Wheel").
        if idx == 4:
            last = getattr(self, "_last_chart_view_index", 0)
            next_label = {0: "▣ South", 1: "◎ Wheel", 2: "◇ North",
                          3: "❖ Body", 6: "✴ Nakshatra"}.get(last, "◎ Wheel")
            lit = last != 0
        else:
            next_label = {0: "◎ Wheel", 1: "◇ North", 2: "❖ Body",
                          3: "✴ Nakshatra", 6: "▣ South"}.get(idx, "◎ Wheel")
            lit = idx != 0
        self.wheel_btn.setText(next_label)
        self.wheel_btn.setStyleSheet(active_style if lit else inactive_style)
        # Entering the wheel view reveals the transit button (never re-hidden
        # by the cycle — visible on all views once shown, as before).
        if idx == 1 and hasattr(self, 'transit_btn'):
            self.transit_btn.setVisible(True)

    def _switch_to_chart_index(self, target_index: int):
        """Switch chart view to a specific chart_stack index.

        Indices are defined once in state.chart_state.VIEW_STACK_INDEX
        (SPEC-COT-001 INV-14): 0=South Indian, 1=Wheel, 2=North Indian,
        3=Body Graph, 4=Cards of Truth.
        """
        from state.chart_state import VIEW_STACK_INDEX
        current = self.chart_stack.currentIndex()
        if current == target_index:
            # td-iopy HIGH-1 (Codex): "already on the target index" must NOT skip
            # the panel broadcast. The common case is persisted-SOUTH startup —
            # the restored index equals the constructed default, so a full
            # activation never runs and the boot broadcast (which syncs Transit/
            # Eclipse) would never fire; likewise a remote set_chart_view(current)
            # must be able to repair panel drift + fire the M3 flush. If the state
            # style AGREES with the stack the main view is truly unchanged, so
            # broadcast-only (idempotent panel index assigns; F2/buttons always
            # change index, so this is never a per-keypress double render). If
            # they DISAGREE (drift), fall through to a full activation to
            # reconcile state + panels + persist.
            style_index = VIEW_STACK_INDEX.get(self.state.chart_view_style)
            if style_index == target_index:
                if not getattr(self, '_suppress_view_broadcast', False):
                    self._broadcast_chart_view(self.state.chart_view_style)
                return
        # SPEC-BAR-001 D-23(d) / Sol BLOCKER 2: activate DIRECTLY, never by
        # walking the ring. The old ``while ... _toggle_wheel_view()`` walk
        # could not reach index 4 (Cards) once Cards left the F2 ring —
        # startup restore and remote set_chart_view(cards_of_truth) both pass
        # target 4 through here, and the walk would spin forever.
        self._activate_chart_view(target_index)

    # _save_setting / _load_setting removed (td-7q5s.5 C3): zero callers, static
    # or getattr-string. Single-key settings go through self.prefs_store directly.

    def _cycle_chart_view(self):
        """Cycle the main chart view globally (F2 shortcut).

        td-iopy: the auxiliary-panel broadcast now lives in _activate_chart_view
        (the single choke point every entry path already flows through), so this
        only advances the main ring. wheel_btn / Alt+W / startup-restore / remote
        — which reach _activate_chart_view WITHOUT passing here — now get the same
        panel sync for free, which is the fix for "F2 doesn't switch the wheel".
        The old positional cards/body early-returns are replaced by per-panel
        supported_chart_views() capability inside _broadcast_chart_view.
        """
        self._toggle_wheel_view()

    def _view_sync_panels(self):
        """Yield the live auxiliary panels that mirror the main chart view.
        hasattr/None-guarded: a panel not yet constructed (early boot) is
        skipped and picks up the current view when it is first shown. Order
        matches the legacy broadcast (eclipse first)."""
        for attr in ("eclipse_panel", "transit_panel",
                     "exploration_panel", "solar_return_page"):
            panel = getattr(self, attr, None)
            if panel is not None:
                yield panel

    def _do_broadcast(self, style):
        """Inner panel sync for _broadcast_chart_view: sync every constructed aux
        panel that SUPPORTS `style`. Capability replaces the old positional
        early-returns (Cards -> nobody, Body -> eclipse only, zodiac -> all four)."""
        for panel in self._view_sync_panels():
            if style in panel.supported_chart_views():
                panel.sync_chart_view(style)

    def _broadcast_chart_view(self, style):
        """td-iopy single choke point: broadcast `style` to the aux panels.

        In production sync_chart_view only sets a stack index (+ the M3 flush),
        so a broadcast never re-enters activation. The re-entrancy handling below
        (Codex td-iopy) covers the pathological/drift case WITHOUT dropping a
        legitimate nested request: an earlier version returned-and-dropped, so a
        drift full-activation to view B nested inside an outer broadcast of view
        A left the aux panels split (some A, some B) with main on B — the exact
        desync this wave exists to kill. Instead, a nested request records its
        style in a pending slot (latest-wins) and the OUTER broadcast replays it
        once the panel loop finishes — bounded, and with the guard still held so
        no call-stack recursion. End state: every panel on the FINAL style."""
        if getattr(self, '_broadcasting_view', False):
            # Nested request during an outer broadcast: don't drop it — remember
            # the latest requested style for the outer to replay.
            self._pending_broadcast_style = style
            return
        self._broadcasting_view = True
        try:
            self._pending_broadcast_style = None
            self._do_broadcast(style)
            # Replay nested requests (drift activations that fired during the
            # sync) latest-wins, bounded. Still inside the guard, so each replay's
            # own nested requests land back in the pending slot, not the stack.
            replays = 0
            while (self._pending_broadcast_style is not None
                   and self._pending_broadcast_style != style
                   and replays < 8):
                style = self._pending_broadcast_style
                self._pending_broadcast_style = None
                self._do_broadcast(style)
                replays += 1
        finally:
            self._broadcasting_view = False
            self._pending_broadcast_style = None

    def _repaint_main_views_if_stale(self, force=False):
        """td-sy9e: repaint the main chart views deferred by an off-screen
        F2/view change (see _activate_chart_view). Called on return to the
        Chart tab; a no-op unless something was actually deferred. Repaints
        through _apply_current_varga (the ONE varga writer, so the landed
        view is varga-correct — td-ijjf contract preserved) and re-pushes the
        transit overlay to the now-visible view."""
        if not (force or getattr(self, '_main_views_stale', False)):
            return
        self._main_views_stale = False
        if not self.state.active_chart:
            return
        self._apply_current_varga()
        idx = self.chart_stack.currentIndex()
        view_attr = {0: 'chart_view', 1: 'wheel_view',
                     2: 'north_indian_view'}.get(idx)
        if view_attr:
            self._push_transit_state(getattr(self, view_attr, None))

    def _debounce_view_persist(self, style):
        """Coalesce the per-keypress disk write. Update settings in-memory
        immediately (lock-respected, save=False) and (re)arm a single-shot timer
        so a burst of F2 presses writes the settled view to disk ONCE. Flushed
        eagerly on close (see closeEvent) so a fast quit still persists."""
        from managers.settings_manager import get_settings
        get_settings().persist_runtime_change("chart.view_type", style, save=False)
        self._pending_view_persist = True
        if not hasattr(self, '_view_persist_timer'):
            from PySide6.QtCore import QTimer
            self._view_persist_timer = QTimer(self)
            self._view_persist_timer.setSingleShot(True)
            self._view_persist_timer.timeout.connect(self._flush_view_persist)
        self._view_persist_timer.start(_VIEW_PERSIST_DEBOUNCE_MS)

    def _flush_view_persist(self):
        """Write a pending debounced view change to disk. Idempotent: a no-op
        when nothing is pending (safe to call from both the timer and close)."""
        if getattr(self, '_pending_view_persist', False):
            from managers.settings_manager import get_settings
            get_settings().flush()
            self._pending_view_persist = False

    # ===== CLUSTER: CHART LOAD / RECALC / TITLE / MODE =====
    def _finalize_chart_load(self, *, skip_dasha=False,
                              skip_varga_reset=False, skip_loading=False):
        """Canonical post-dispatch refresh (SPEC-REF-001 v1.1).

        Call AFTER: SetActiveChart dispatch + memory panel updated.
        """
        if not skip_varga_reset:
            from state.events import SetVarga
            self.state.dispatch(SetVarga(varga_number=1))
            if hasattr(self, 'varga_actions') and 1 in self.varga_actions:
                self.varga_actions[1].setChecked(True)
            if hasattr(self, 'varga_buttons') and 1 in self.varga_buttons:
                self.varga_buttons[1].setChecked(True)

        self._update_toggle_button_styles()
        self._update_all_chart_views(skip_loading=skip_loading)

        if not skip_dasha:
            self._update_vedanga_dasha()
            self._update_vimshottari_dasha()

        self._update_title()
        self._update_chart_display_preview()

        # Live birth-time preview: refresh the time-adjust readout on every
        # chart refresh while its popup is open. Covers both a +/- click (this
        # runs via _adjust_time) and a chart switch under the open popup (the
        # widget's entry-id guard recaptures the baseline for the new chart).
        _taw = getattr(self, 'time_adjust_widget', None)
        if _taw is not None and _taw.isVisible():
            _taw.refresh_preview()

    def _update_all_chart_views(self, *, skip_loading=False):
        """Update all chart views from state.active_chart."""
        self._sync_dual_rim_button_text()
        use_western = getattr(self, 'use_western_names', False)
        if not skip_loading:
            self.loading_manager.start("Updating chart...")
        try:
            chart = self.state.active_chart
            if chart is None:
                return

            # td-ijjf: this used to render every view with NO varga code, so a
            # chart reload silently dropped D-10 back to D-1 while the varga
            # column still showed 10 checked. One writer now (SPEC-VGC-001 §4.2).
            self._apply_current_varga()

            if not skip_loading:
                self.loading_manager.update("Updating panels...")
            self._update_all_panels()
        finally:
            # Panel refresh failures must release the loading scope.  Startup
            # intentionally lets individual optional panels fail without
            # leaving an application-modal overlay over the usable chart.
            if not skip_loading:
                self.loading_manager.finish()

        # Force viewport refresh on all views to ensure chart displays
        if hasattr(self, 'chart_view') and self.chart_view:
            self.chart_view.ensure_visible()
        if hasattr(self, 'wheel_view') and self.wheel_view:
            self.wheel_view.ensure_visible()
        if hasattr(self, 'north_indian_view') and self.north_indian_view:
            self.north_indian_view.ensure_visible()
        if hasattr(self, 'body_graph_view') and self.body_graph_view:
            self.body_graph_view.ensure_visible()
        if hasattr(self, 'cards_of_truth_view') and self.cards_of_truth_view:
            self.cards_of_truth_view.ensure_visible()

    def _current_body_gender(self):
        """Resolve the active chart's gender for the Body Graph silhouette.

        Reads from source_params.birth_data (the reliable render-time source).
        Anything other than Female (including a missing value) maps to the male
        body via the view's own default, so this never has to be exact.
        """
        try:
            sp = self.state.source_params or {}
            bd = sp.get('birth_data') or {}
            return bd.get('gender', 'Unknown')
        except Exception:
            return 'Unknown'

    def _close_current_chart(self):
        """Remove current chart from memory. Delegates to ChartManager."""
        self.chart_manager.close_current_chart()

    def _recalculate_chart(self):
        """
        Recalculate chart based on current settings (aditya_mode + is_human_design).
        Called when either setting changes.
        Returns True on success, False on failure.
        """
        _prev = getattr(self.state, 'active_chart', None)
        if _prev is None and self.birth_jd is None:
            print("[WARNING] No chart loaded, cannot recalculate")
            return False

        # Recompute ayanamsa offset if in sidereal mode
        if self.state.aditya_mode == "sidereal" or self.chart_zodiac == "sidereal":
            self._compute_chart_ayanamsa_offset()

        self.loading_manager.start("Recalculating chart...")

        try:
            from core.chart_factory import build_chart_from_params, rebuild_chart, make_source_params
            from state.events import SetActiveChart

            _prev_jd = _prev.context.timeJD.jd if _prev else None
            _prev_was_hd = (self.state.source_params or {}).get('is_human_design', False)
            _is_transit = (self.birth_jd is not None and _prev_jd is not None
                           and abs(_prev_jd - self.birth_jd) > 0.0001
                           and not _prev_was_hd)

            if self.is_human_design:
                if _is_transit:
                    self.statusBar().showMessage("HD mode is not available for transit charts")
                    self.is_human_design = False
                    self._update_toggle_button_styles()
                    return False
                _cbd = getattr(self, 'current_birth_data', None) or {}
                _raw_utc = _cbd.get('utcoffset')
                if _raw_utc is not None:
                    _utc_off = float(_raw_utc)
                elif _prev is not None:
                    _utc_off = _prev.context.timeJD.utcoffset
                else:
                    _utc_off = 0.0
                from core.sun_degree_shift import shift_sun_degrees
                chart_jd, _ = shift_sun_degrees(
                    self.birth_jd, self.birth_lat, self.birth_lon, -88,
                    utcoffset=_utc_off,
                )
                _chart = build_chart_from_params(
                    jd=chart_jd, lat=self.birth_lat, lon=self.birth_lon,
                    mode=self.hd_manager.design_chart_mode(), utcoffset=_utc_off,
                    ayanamsa=self.chart_sidereal_ayanamsa_id,
                    name=getattr(self, 'person_name', ''),
                    hsys=self.state.house_system_code,
                )
            elif _prev is not None:
                if _is_transit:
                    _utc_off = _prev.context.timeJD.utcoffset
                    _chart = build_chart_from_params(
                        jd=_prev_jd, lat=_prev.context.location.lat,
                        lon=_prev.context.location.long,
                        mode=self.state.aditya_mode, utcoffset=_utc_off,
                        ayanamsa=self.chart_sidereal_ayanamsa_id,
                        name=getattr(self, 'person_name', '') or 'Transit',
                        hsys=self.state.house_system_code,
                    )
                elif self.birth_jd is not None:
                    _cbd = getattr(self, 'current_birth_data', None) or {}
                    _raw_utc = _cbd.get('utcoffset')
                    if _raw_utc is not None:
                        _utc_off = float(_raw_utc)
                    elif _prev is not None:
                        _utc_off = _prev.context.timeJD.utcoffset
                    else:
                        _utc_off = 0.0
                    _chart = build_chart_from_params(
                        jd=self.birth_jd, lat=self.birth_lat, lon=self.birth_lon,
                        mode=self.state.aditya_mode, utcoffset=_utc_off,
                        ayanamsa=self.chart_sidereal_ayanamsa_id,
                        name=getattr(self, 'person_name', ''),
                        hsys=self.state.house_system_code,
                    )
                else:
                    _chart = rebuild_chart(
                        _prev,
                        mode=self.state.aditya_mode,
                        ayanamsa=self.chart_sidereal_ayanamsa_id,
                        hsys=self.state.house_system_code,
                    )
            else:
                _cbd = getattr(self, 'current_birth_data', None) or {}
                _raw_utc = _cbd.get('utcoffset')
                if _raw_utc is not None:
                    _utc_off = float(_raw_utc)
                else:
                    _utc_off = 0.0
                _chart = build_chart_from_params(
                    jd=self.birth_jd, lat=self.birth_lat, lon=self.birth_lon,
                    mode=self.state.aditya_mode, utcoffset=_utc_off,
                    ayanamsa=self.chart_sidereal_ayanamsa_id,
                    name=getattr(self, 'person_name', ''),
                    hsys=self.state.house_system_code,
                )

            self.state.dispatch(SetActiveChart(chart=_chart, source_params=make_source_params(
                chtk_path=getattr(self, 'current_chart_path', None) and str(self.current_chart_path),
                birth_data=self.current_birth_data,
                mode=self.state.aditya_mode,
                ayanamsa=self.chart_sidereal_ayanamsa_id,
                house_system=self.state.house_system,
                is_human_design=self.is_human_design,
            )))
            # Invalidate caches so the property fallback re-derives from the
            # new active chart.  Setting the *private* attr to None (not via
            # the property setter, which would set _CLEARED and block fallback).
            self._current_chart_data = None
            self._current_birth_data = None

        except Exception as e:
            print(f"[ERROR] Chart recalculation failed: {e}")
            import traceback; traceback.print_exc()
            self.statusBar().showMessage(f"Recalculation failed: {e}", 5000)
            return False

        finally:
            self.loading_manager.finish()

        # Chart dispatched successfully. UI updates below are non-critical:
        # failures here must NOT revert the toggle state.
        try:
            self._finalize_chart_load(skip_varga_reset=True)
            if self.state.current_varga != 1:
                self._switch_varga(self.state.current_varga)
        except Exception as e:
            print(f"[WARNING] Post-recalculate UI update error: {e}")
            import traceback; traceback.print_exc()

        return True

    def _update_title(self):
        """
        Update title displays:
        - Pill button (center): Just the name
        - Window title bar: Varuna360 | Full birth info

        Uses canonical birth_data (Single Source of Truth) if available.
        """
        # Prefer canonical birth_data if available
        birth_data = getattr(self, 'current_birth_data', None)

        if not self.current_chart_data and not birth_data:
            _bar = getattr(self, 'chart_title_widget', None)
            if hasattr(_bar, 'set_title'):
                _bar.set_title(None)          # SPEC-BAR-001 M3 W2 (Dm3-13)
            elif hasattr(self, 'chart_title_label'):
                self.chart_title_label.setText("No Chart Loaded")
            self.setWindowTitle(self._app_name)
            return

        # Get name - prefer birth_data
        if birth_data:
            name = birth_data.get('name', 'Unknown')
        else:
            name = self.current_chart_data.get('name', 'Unknown')

        # Compute current age — skip for transit charts (age would be "0y 0m")
        age_suffix = ""
        _active = self.state.active_chart
        _active_jd = _active.context.timeJD.jd if _active else None
        _is_transit = (self.birth_jd is not None and _active_jd is not None
                       and abs(_active_jd - self.birth_jd) > 0.0001
                       and not getattr(self, 'is_human_design', False))
        if not _is_transit and self.birth_jd is not None:
            try:
                from datetime import datetime
                if birth_data:
                    b_y = birth_data['local_year'] if 'local_year' in birth_data else birth_data.get('year')
                    b_m = birth_data['local_month'] if 'local_month' in birth_data else birth_data.get('month')
                    b_d = birth_data['local_day'] if 'local_day' in birth_data else birth_data.get('day')
                else:
                    chart = self.current_chart_data or {}
                    b_y, b_m, b_d = chart.get('year'), chart.get('month'), chart.get('day')
                if b_y and b_m and b_d:
                    now = datetime.now()
                    total_months = (now.year - b_y) * 12 + (now.month - b_m)
                    if now.day < b_d:
                        total_months -= 1
                    years = total_months // 12
                    months = total_months % 12
                    if years > 0 or months > 0:
                        age_suffix = f"  {years}y {months}m"
            except Exception:
                pass

        # Pill button (center) - name (title case) + current age
        _bar = getattr(self, 'chart_title_widget', None)
        if hasattr(_bar, 'set_title'):
            # SPEC-BAR-001 M3 W2 (Dm3-13/14): pill = the bare name; the age
            # moves onto the meta line as its leading segment.
            _bar.set_title(name.title(), self._compose_title_meta(age_suffix))
        elif hasattr(self, 'chart_title_label'):
            self.chart_title_label.setText(name.title() + age_suffix)

        # Window title bar - "Varuna360 | Full birth info"
        # Prefer birth_data (canonical) over legacy current_chart_data (SPEC-UI-001 S8.2)
        chart = self.state.active_chart
        if chart:
            _title_data = birth_data if (birth_data and ('hour' in birth_data or 'local_hour' in birth_data)) else getattr(self, 'current_chart_data', None)
            full_title = _format_chart_title(
                chart, aditya_mode=self.state.aditya_mode,
                chart_data=_title_data,
                timezone_str=getattr(self, 'current_timezone', None),
            )
            varga = self.state.current_varga
            if varga and varga != 1:
                varga_name = VARGA_NAMES.get(varga, f"D-{varga}")
                self.setWindowTitle(f"{self._app_name} | {full_title} | D-{varga} {varga_name}")
            else:
                self.setWindowTitle(f"{self._app_name} | {full_title}")
        else:
            self.setWindowTitle(f"{self._app_name} | {name}")

    def _compose_title_meta(self, age_suffix: str = "") -> str:
        """SPEC-BAR-001 D-23(a) (amended v2.3, td-0wh26): the meta line NAMES
        AYANAMSHAS, nothing else. Format `<mode token> · <nakshatra token>[ ·
        <age>]` — age LAST (spec §D-23(a):509), e.g. 'Aditya Circle · Vedanga
        Jyotisha' or 'Aditya Circle · Vedanga Jyotisha · 52y 3m'. td-0wh26: when
        the mode token and the nakshatra token are the SAME ayanamsha name they
        collapse to one (else Sidereal+Nakshatra, and the default zodiac==dasha
        config, read 'X · X'). Bare names only — no 'Sidereal'/'Nakshatras' frame
        words (a frame word can lie; the nakshatra frame can itself be tropical).
        Content-only; hidden wholesale by the D-22f band."""
        from core.ayanamsa_data import get_ayanamsa_name
        # Mode token: sidereal names the ZODIAC ayanamsha's own name (the word
        # "Sidereal" is already lit in the tray, so repeating it is noise).
        if self.state.aditya_mode == "sidereal":
            mode_label = get_ayanamsa_name(self.chart_sidereal_ayanamsa_id)
        elif self.state.aditya_mode == "aditya":
            mode_label = "Aditya Circle"
        else:
            mode_label = "Tropical Classic"
        # Nakshatra token: the Core/Lite Nakshatra F2 view (SPEC-NAK-LITE-001)
        # computes its nakshatras from the ZODIAC ayanamsha (zodiac.ayanamsa_id,
        # mirrored as chart_sidereal_ayanamsa_id) and ignores nakshatra_coords,
        # so on that view the pill must name THAT, not the left-dasha ayanamsha
        # (td-bu8s BUG4). Every other view keeps the app-wide nakshatra token:
        # explicit tropical → "Tropical"; otherwise (incl. the default "neither",
        # ecliptic-sidereal) the left-dasha ayanamsha's bare name (D-23(a)).
        if self.state.chart_view_style == "nakshatra":
            nak = get_ayanamsa_name(self.chart_sidereal_ayanamsa_id)
        elif getattr(self, 'nakshatra_coords', '') == "tropical":
            nak = "Tropical"
        else:
            nak = get_ayanamsa_name(self.dasha_manager.ayanamsa("left"))
        # td-0wh26: collapse a duplicate ayanamsha token. The reported case is the
        # Nakshatra view in Sidereal mode, where both tokens resolve to the SAME
        # ayanamsha (mode names chart_sidereal_ayanamsa_id, and the nakshatra
        # token on that view names it too) -> 'Vedanga Jyotisha · Vedanga
        # Jyotisha'. The collapse is INTENTIONALLY view-agnostic (not gated on
        # view_style): the default config (zodiac==left-dasha ayanamsha) shows the
        # same doubling on the Wheel/South Indian views, and it should collapse
        # there too. Do NOT re-scope this to view_style=="nakshatra" — that would
        # silently reintroduce the default-config duplicate (pinned by
        # test_meta_default_same_id_collapses_on_any_view). age is a duration and
        # never collides, so it always stays last.
        parts = [mode_label]
        if nak != mode_label:
            parts.append(nak)
        if age_suffix.strip():
            parts.append(age_suffix.strip())        # age LAST (D-23(a))
        return " · ".join(parts)

    def _refresh_chart_display(self):
        """
        Refresh chart display without recalculating planetary positions.
        Used when toggling sign name display (Aditya vs Western names).
        Only redraws visuals - no ephemeris calculation needed.
        """
        if not self.state.active_chart:
            print("[WARNING] No chart loaded, cannot refresh display")
            return

        # Relabel the currently selected division.
        self._apply_current_varga()

    def _is_beginner_mode(self):
        """SPEC-MODE-001: True when the experience level gates alternative naming.

        Any value other than the literal "advanced" is treated as Beginner, so a
        missing/None setting fails safe to the simplified experience.
        """
        from managers.settings_manager import get_settings
        return get_settings().get("ui.experience_level", "beginner") != "advanced"

    def _clamp_western_names_on_mode_change(self, reason):
        """ChartState observer: enforce native naming in Beginner (SPEC-MODE-001).

        Fires after every ChartState mutation. On a zodiac-system change while in
        Beginner, re-clamp use_western_names to the native default so a direct
        SetZodiacMode dispatch (Alt+S, ayanamsa dialogs, session restore, remote
        control) can never leave an alternative-naming combo on screen. Must never
        raise: ChartState._emit iterates all listeners, so an exception here would
        break unrelated panels.
        """
        if reason != "aditya_mode":
            return
        try:
            if not self._is_beginner_mode():
                return
            native = (self.state.aditya_mode != "aditya")
            if getattr(self, "use_western_names", None) != native:
                self.use_western_names = native
        except Exception as exc:
            # Never propagate: ChartState._emit iterates all listeners, so raising
            # here would break unrelated panels. But log it, since a silent skip
            # would let Beginner show alt naming with no trace.
            import logging
            logging.getLogger(__name__).warning(
                "Beginner naming clamp skipped: %s", exc)

    def _set_aditya_mode(self, mode):
        """Toolbar entrypoint, including the legacy two-button name toggle."""
        if (mode == "tropical_classic" and self.chart_zodiac == "sidereal"
                and not hasattr(self, "sidereal_btn")):
            mode = "sidereal"
        self.zodiac_settings.set_mode(mode, toggle_names=True)

    def _on_names_changed(self, use_western: bool):
        self.zodiac_settings.set_runtime("zodiac.use_western_names", use_western)

    def _on_ayanamsa_changed(self, ayanamsa_id: int):
        self.zodiac_settings.set_runtime("zodiac.ayanamsa_id", ayanamsa_id)

    def _on_house_system_changed(self, house_system: str):
        self.zodiac_settings.set_runtime("zodiac.house_system", house_system)

    def _on_house_display_mode_changed(self, mode):
        # Target the wheel directly (SPEC-WHD-001 6.5). Applying to
        # currentWidget() drops the change whenever the user is on the
        # south/north-indian tab when they click Apply.
        if hasattr(self, 'wheel_view') and hasattr(self.wheel_view, 'set_house_display_mode'):
            self.wheel_view.set_house_display_mode(mode)

    def _compute_chart_ayanamsa_offset(self):
        """Use the same apparent ecliptic offset as indexed Sidereal search."""
        from core.ayanamsa_offset import birth_ayanamsa_offset
        chart = getattr(getattr(self, "state", None), "active_chart", None)
        jd = self.birth_jd if self.birth_jd is not None else (
            chart.context.timeJD.jd if chart is not None else None)
        self.chart_ayanamsa_offset = (birth_ayanamsa_offset(
            jd, self.chart_sidereal_ayanamsa_id) if jd is not None else 0.0)

    # ===== CLUSTER: VIEW-OPTIONS TOGGLES =====
    @_batched
    def _toggle_human_design(self):
        """
        Toggle Human Design mode (-88° Sun shift).
        Preserves aditya_mode (Aditya vs Tropical naming).
        """
        if self.birth_jd is None:
            print("[WARNING] No chart loaded, cannot toggle Human Design")
            self.statusBar().showMessage("Load a chart first")
            return

        self.is_human_design = not self.is_human_design

        # Chart-context reset (decision 2): HD changes the entire sequence, so
        # clear ALL dasha navigation through the manager (SPEC-DSH-002). The
        # recompute below re-lists; this only resets state + chrome.
        self.dasha_manager.reset_for_chart()
        # w3-2 D-W3-4: level buttons are reset inside reset_for_chart()
        # (sync_level_buttons is its last statement).

        # Recalculate chart (respects aditya_mode)
        success = self._recalculate_chart()
        if not success:
            self.is_human_design = not self.is_human_design
            self._update_toggle_button_styles()
            return

        mode_label = "Aditya Circle" if self.state.aditya_mode == "aditya" else "Tropical Classic"
        if self.is_human_design:
            self.statusBar().showMessage(f"Human Design ON ({mode_label} naming)")
        else:
            self.statusBar().showMessage(f"Human Design OFF - showing birth chart")

    def _toggle_sidereal(self, checked: bool):
        """Alt+S uses the same mode transaction as Settings and the toolbar."""
        self.zodiac_settings.set_mode("sidereal" if checked else "tropical_classic")

    def _toggle_dual_rim(self):
        """
        Toggle dual rim mode - shows outer Tropical rim on Aditya wheel.
        Only affects wheel view. Mutually exclusive with transit rim.
        """
        self.show_tropical_rim = not self.show_tropical_rim

        # Mutually exclusive: if turning on tropical, turn off transit
        if self.show_tropical_rim and hasattr(self, 'transit_overlay_manager') \
                and self.transit_overlay_manager.transit_enabled:
            self.transit_overlay_manager.disable_transit()

        # Update wheel view
        if hasattr(self, 'wheel_view') and self.wheel_view:
            self.wheel_view.set_show_tropical_rim(self.show_tropical_rim)
            # Redraw if data is loaded
            if self.wheel_view._chart:
                self.wheel_view.draw_wheel()
                self.wheel_view.ensure_visible()

        # Update button checked state
        if hasattr(self, 'dual_rim_btn'):
            self.dual_rim_btn.setChecked(self.show_tropical_rim)

        from managers.settings_manager import get_settings
        get_settings().set("chart.show_tropical_rim", self.show_tropical_rim)

        if self.show_tropical_rim:
            self.statusBar().showMessage("Dual rim ON - Aditya + Tropical outer ring")
        else:
            self.statusBar().showMessage("Dual rim OFF - Aditya only")

    def _sync_dual_rim_button_text(self):
        """
        Sync dual rim button text + visibility to match current state.

        Visibility: shown only in wheel view (chart_stack index 1).
        Text: "+ Tropical" in Aditya mode, "+ Aditya" in Tropical/Sidereal mode.

        Called from _cycle_chart_view, _update_all_chart_views, and _set_aditya_mode.
        Each path may flip either dimension — handling both here keeps the button
        consistent regardless of which path triggered the resync.
        """
        if not hasattr(self, 'dual_rim_btn'):
            return

        in_wheel_view = (
            hasattr(self, 'chart_stack')
            and self.chart_stack.currentIndex() == 1
        )

        _bar = getattr(self, 'chart_title_widget', None)
        if hasattr(_bar, 'render_state'):
            # SPEC-BAR-001 M3 W4 (Dm3-23): the v2 bar owns visibility through
            # app-visibility (D-51: capsule shown only in the wheel view) and
            # the label through render_state; the tooltip stays a direct
            # write below (Dm3-4 keeps tooltips outside the routing).
            _ctl = getattr(_bar, 'layout_controller', None)
            if _ctl is not None:
                _ctl.set_app_visible("dual", in_wheel_view)
            _bar.render_state("dual_sync")
        else:
            self.dual_rim_btn.setVisible(in_wheel_view)
            self.dual_rim_btn.setText("+ Tropical"
                                      if self.state.aditya_mode == "aditya"
                                      else "+ Aditya")

        if self.state.aditya_mode == "aditya":
            self.dual_rim_btn.setToolTip("Show outer Tropical rim on Aditya wheel")
        else:
            self.dual_rim_btn.setToolTip("Show outer Aditya rim on Tropical wheel")

    def _toggle_transit_rim(self):
        """Toggle transit overlay via TransitOverlayManager.

        Visible on all chart views. Mutually exclusive with tropical rim.
        """
        mgr = self.transit_overlay_manager
        if mgr.transit_mode == "overlay_chart" and mgr.transit_enabled:
            # SPEC-TRN-006 D-1: clicking TRANSIT while an overlay is active turns
            # the rim off AND drops the overlay. The chip x is the path back to
            # live sky without going through off.
            self.chart_overlay_manager.clear()
        elif mgr.transit_enabled:
            mgr.disable_transit()
        else:
            mgr.enable_transit()
            if mgr.transit_enabled and self.show_tropical_rim:
                self.show_tropical_rim = False
                if hasattr(self, 'dual_rim_btn'):
                    self.dual_rim_btn.setChecked(False)
                from managers.settings_manager import get_settings
                get_settings().set("chart.show_tropical_rim", False)

        # Sync button immediately (enable_transit is a no-op without a chart,
        # so the QPushButton auto-toggle may be out of sync with manager state)
        if hasattr(self, 'transit_btn'):
            self.transit_btn.setChecked(mgr.transit_enabled)
        if hasattr(self, 'transit_action'):
            self.transit_action.setChecked(mgr.transit_enabled)

        # Push state to active view synchronously using chart_stack index
        # as ground truth (state.chart_view_style can lag behind on startup)
        idx = self.chart_stack.currentIndex() if hasattr(self, 'chart_stack') else -1
        if idx == 1 and hasattr(self, 'wheel_view') and self.wheel_view:
            self.wheel_view.update_transit_from_manager(mgr)
        elif idx == 0 and hasattr(self, 'chart_view') and self.chart_view:
            self.chart_view.update_transit_overlay(mgr)
        elif idx == 2 and hasattr(self, 'north_indian_view') and self.north_indian_view:
            self.north_indian_view.update_transit_overlay(mgr)

        # SPEC-VGC-001 D-1: transit outranks the center varga, so turning it
        # on SUSPENDS a selected divisional chart. INV-5 requires that to be
        # visible rather than silent.
        self._sync_varga_center_button()

        from managers.settings_manager import get_settings
        get_settings().set("chart.show_transit_overlay", mgr.transit_enabled)

        if mgr.transit_enabled:
            self.statusBar().showMessage("Transit overlay ON")
        else:
            self.statusBar().showMessage("Transit overlay OFF")

    def _push_transit_state(self, view):
        """Push transit state to `view` whether transit is ON or OFF.

        SPEC-SIC-003 §2.6 / T-10: the mediator only updates the VISIBLE
        view, so a view hidden while transit was switched off never hears
        about it. The switch-back pushes used to be gated on
        `transit_enabled`, which blocked the one message that would have
        corrected it — the hidden view kept redrawing a stale overlay. The
        view decides what to do with the state; the gate belongs there, not
        here.
        """
        mgr = getattr(self, 'transit_overlay_manager', None)
        if mgr is None or view is None:
            return
        if hasattr(view, 'update_transit_from_manager'):
            view.update_transit_from_manager(mgr)   # wheel
        elif hasattr(view, 'update_transit_overlay'):
            view.update_transit_overlay(mgr)        # South / North Indian

    def _on_transit_state_changed(self):
        """Mediator: route TransitOverlayManager state to the active view."""
        mgr = self.transit_overlay_manager
        # SPEC-TRN-006 B-4: transit and tropical rims are mutually exclusive.
        # Centralise the arbitration here so a direct overlay activation (which
        # bypasses _toggle_transit_rim) cannot leave both rims painted.
        if mgr.transit_enabled and getattr(self, 'show_tropical_rim', False):
            self.show_tropical_rim = False
            if hasattr(self, 'dual_rim_btn'):
                self.dual_rim_btn.setChecked(False)
            if hasattr(self, 'wheel_view') and self.wheel_view:
                self.wheel_view.set_show_tropical_rim(False)
            from managers.settings_manager import get_settings
            get_settings().set("chart.show_tropical_rim", False)
        if hasattr(self, 'transit_btn'):
            self.transit_btn.setChecked(mgr.transit_enabled)
        if hasattr(self, 'transit_action'):
            self.transit_action.setChecked(mgr.transit_enabled)
        # SPEC-TRN-006: refresh the overlay chip + button text from manager state.
        if hasattr(self, 'chart_title_widget'):
            try:
                from apps.widgets.chart_title_widget import update_overlay_chip
                update_overlay_chip(self, mgr)
            except Exception as _chip_exc:
                # The chip is one of the two signals distinguishing overlay from
                # live sky (D-2); a silent failure degrades the feature invisibly.
                print(f"[TRANSIT-OVERLAY] update_overlay_chip failed: {_chip_exc}")
        idx = self.chart_stack.currentIndex() if hasattr(self, 'chart_stack') else -1
        if idx == 1 and hasattr(self, 'wheel_view') and self.wheel_view:
            self.wheel_view.update_transit_from_manager(mgr)
        elif idx == 0 and hasattr(self, 'chart_view') and self.chart_view:
            self.chart_view.update_transit_overlay(mgr)
        elif idx == 2 and hasattr(self, 'north_indian_view') and self.north_indian_view:
            self.north_indian_view.update_transit_overlay(mgr)
        if self.time_adjust_widget and hasattr(self.time_adjust_widget, 'update_save_button_state'):
            self.time_adjust_widget.update_save_button_state()
            # A transit/view toggle changes whether the readout applies and
            # whether Revert should be live; recompute the whole readout state,
            # not just Save (else a stale readout + wrongly-enabled Revert
            # survive the transition).
            if self.time_adjust_widget.isVisible():
                self.time_adjust_widget.refresh_preview()

    def _toggle_outer_planets(self):
        """
        Toggle outer planets visibility (Uranus, Neptune, Pluto).
        Affects all chart views: South Indian, North Indian, Wheel, Body Graph.
        Shortcut: F8
        """
        # Get current state from action (it toggles automatically)
        show = self.outer_planets_action.isChecked()

        # Update South Indian view
        if hasattr(self, 'chart_view') and self.chart_view:
            self.chart_view.show_outer_planets = show
            if self.chart_view._chart:
                self.chart_view.draw_full_chart()
                self.chart_view.ensure_visible()

        # Update North Indian view
        if hasattr(self, 'north_indian_view') and self.north_indian_view:
            self.north_indian_view.show_outer_planets = show
            if self.north_indian_view._chart:
                self.north_indian_view.draw_chart()
                self.north_indian_view.ensure_visible()

        # Update Wheel view
        if hasattr(self, 'wheel_view') and self.wheel_view:
            self.wheel_view.show_outer_planets = show
            if self.wheel_view._chart:
                self.wheel_view.draw_wheel()
                self.wheel_view.ensure_visible()

        # Update Body Graph view (SPEC-BODY-001) — re-render so F8 hides/shows
        # Uranus/Neptune/Pluto bars here too.
        if hasattr(self, 'body_graph_view') and self.body_graph_view:
            self.body_graph_view.show_outer_planets = show
            if self.body_graph_view._current_chart is not None:
                self.body_graph_view.update_from_chart(
                    self.body_graph_view._current_chart,
                    use_western_names=self.body_graph_view._use_western,
                    aditya_mode=self.body_graph_view._aditya_mode,
                    varga_code=self.body_graph_view._varga_code)
                self.body_graph_view.ensure_visible()

        # Persist F8 outer planets preference
        from managers.settings_manager import get_settings
        get_settings().persist_runtime_change("chart.show_outer_planets", show)

        # Status message
        if show:
            self.statusBar().showMessage("Outer planets visible (Uranus, Neptune, Pluto)")
        else:
            self.statusBar().showMessage("Outer planets hidden")

    def _toggle_planet_names(self):
        """Toggle planet labels between degrees and localized names (F11)."""
        show = self.planet_names_action.isChecked()

        if hasattr(self, 'chart_view') and self.chart_view:
            self.chart_view.show_planet_names = show
            if self.chart_view._chart:
                self.chart_view.draw_full_chart()
                self.chart_view.ensure_visible()

        if hasattr(self, 'north_indian_view') and self.north_indian_view:
            self.north_indian_view.show_planet_names = show
            if self.north_indian_view._chart:
                self.north_indian_view.draw_chart()
                self.north_indian_view.ensure_visible()

        if hasattr(self, 'wheel_view') and self.wheel_view:
            self.wheel_view.show_planet_names = show
            if self.wheel_view._chart:
                self.wheel_view.draw_wheel()
                self.wheel_view.ensure_visible()

        from managers.settings_manager import get_settings
        get_settings().persist_runtime_change(
            "chart.show_planet_names", show)

        if show:
            self.planet_names_action.setText(
                "Planet Labels: Show &Degrees (F11)")
            self.statusBar().showMessage(
                "Planet labels: Names (F10 to switch back to degrees)",
                3000)
        else:
            self.planet_names_action.setText(
                "Planet Labels: Show &Names (F11)")
            self.statusBar().showMessage(
                "Planet labels: Degrees (F10 to switch to names)", 3000)

    def _toggle_retinue_rings(self, checked: bool):
        """Toggle Hora + Trimsamsa outer rings on the wheel chart (F5)."""
        current = self.chart_stack.currentWidget()
        self.retinue_rings_action.setChecked(bool(checked))
        from apps.widgets.retinue_display import apply_retinue, broadcast_south_indian
        from managers.settings_manager import get_settings
        get_settings().persist_runtime_change('chart.show_retinue_rings', checked)
        apply_retinue(self.wheel_view, rings=checked)
        broadcast_south_indian(rings=checked)
        # Live SI hosts were handled by the broadcast; only inspect their state.
        state = current.retinue_state() if hasattr(current, 'retinue_state') else (
            apply_retinue(current, rings=checked) if current is not self.wheel_view else {})
        self.statusBar().showMessage(state.get('suppression_reason') or
            f"Hora + Trimshamsha: {'ON' if checked else 'OFF'} (F5)", 3000)
        # Propagate to panel wheels (draw if visible, defer if not).
        # td-u53i: per-WHEEL isVisible(), never `active_tab is panel` — the
        # Transit/SR panels are SUBPAGES of the Predictive Tools tab, so they
        # are never the tab widget and the old comparison deferred their
        # wheels forever (rings only appeared when an unrelated render redrew
        # them). A deferred wheel now catches up in WheelView.showEvent.
        for panel_attr in ('transit_panel', 'solar_return_page', 'eclipse_panel'):
            panel = getattr(self, panel_attr, None)
            if panel:
                for wheel in panel.get_all_wheels():
                    wheel.set_show_retinue_rings(checked)
                    if wheel.isVisible():
                        wheel.draw_wheel()
                    else:
                        wheel._retinue_dirty = True

    def _toggle_trimsamsha_degrees(self, checked: bool):
        """Toggle degree labels on Trimsamsha ring sectors (F6)."""
        current = self.chart_stack.currentWidget()
        self.trimsamsha_degrees_action.setChecked(bool(checked))
        from apps.widgets.retinue_display import apply_retinue, broadcast_south_indian
        from managers.settings_manager import get_settings
        get_settings().persist_runtime_change('chart.show_trimsamsha_degrees', checked)
        apply_retinue(self.wheel_view, ruler=checked)
        broadcast_south_indian(ruler=checked)
        self.statusBar().showMessage(
            f"Trimshamsha ruler: {'ON' if checked else 'OFF'} (visible when F5 active)", 3000)
        # td-u53i: per-wheel isVisible() (see _toggle_retinue_rings).
        for panel_attr in ('transit_panel', 'solar_return_page', 'eclipse_panel'):
            panel = getattr(self, panel_attr, None)
            if panel:
                for wheel in panel.get_all_wheels():
                    wheel.show_trimsamsha_degrees = checked
                    if wheel.isVisible():
                        wheel.draw_wheel()
                    else:
                        wheel._retinue_dirty = True

    def _toggle_pie_charts(self, checked: bool):
        """Toggle element pie charts on the wheel chart (Shift+F5)."""
        current = self.chart_stack.currentWidget()
        if hasattr(current, 'show_element_pies'):
            current.show_element_pies = checked
            current.draw_wheel()
            current.ensure_visible()
            state = "ON" if checked else "OFF"
            self.statusBar().showMessage(
                f"Pie charts: {state} (Shift+F5)", 3000)
            from managers.settings_manager import get_settings
            get_settings().persist_runtime_change("chart.show_element_pies", checked)
        else:
            self.statusBar().showMessage(
                "Pie charts only available on Wheel view (F2 to switch)", 3000)
        # td-u53i: NO panel propagation. Element pies are a main-tab feature —
        # the dual/comparison wheels are born with them OFF (dual_chart_widget,
        # dual_chart_comparison) and Shift+F5 must not re-enable them there.

    def _toggle_aspect_panel(self):
        """Toggle the rashi aspect panel on the Body Graph view (Shift+F2).

        No-op unless the Body Graph (chart_stack index 3) is current, mirroring
        the index guard used by the other view-specific shortcuts. The dual
        widget persists its own show/hide state, so nothing else is needed here.
        """
        if self.chart_stack.currentIndex() != 3:
            self.statusBar().showMessage(
                "Rashi aspect panel is only available on the Body Graph view "
                "(F2 to switch)", 3000)
            return
        current = self.chart_stack.currentWidget()
        if hasattr(current, 'toggle_aspect_panel'):
            current.toggle_aspect_panel()
            state = "ON" if getattr(current, '_panel_visible', False) else "OFF"
            self.statusBar().showMessage(
                f"Rashi aspect panel: {state} (Shift+F2)", 3000)

    def _cycle_cusp_glow(self):
        """Cycle cusp glow lines: OFF → Angles → All → OFF (F9)."""
        current = self.chart_stack.currentWidget()
        if hasattr(current, 'cusp_glow_mode'):
            new_mode = (current.cusp_glow_mode + 1) % 3
            current.set_cusp_glow_mode(new_mode)
            current.ensure_visible()
            labels = {0: "OFF", 1: "Angles (ASC/IC/DESC/MC)", 2: "All 12 cusps"}
            self.statusBar().showMessage(
                f"Cusp lines: {labels[new_mode]} (F9)", 3000)
            from managers.settings_manager import get_settings
            get_settings().persist_runtime_change("chart.cusp_glow_mode", new_mode)
            # Propagate to panel wheels (draw if visible, defer if not).
            # td-u53i: per-wheel isVisible() (see _toggle_retinue_rings). The
            # setter redraws internally, so a HIDDEN wheel gets the raw mode
            # attribute + dirty mark instead — the old code repainted every
            # hidden panel wheel on each F9 press. Catches up in showEvent.
            for panel_attr in ('transit_panel', 'solar_return_page', 'eclipse_panel'):
                panel = getattr(self, panel_attr, None)
                if panel:
                    for wheel in panel.get_all_wheels():
                        if not hasattr(wheel, 'set_cusp_glow_mode'):
                            continue
                        if wheel.isVisible():
                            wheel.set_cusp_glow_mode(new_mode)
                        else:
                            wheel.cusp_glow_mode = new_mode % 3
                            wheel._retinue_dirty = True
        else:
            self.statusBar().showMessage(
                "Cusp lines only available on Wheel view (F2 to switch)", 3000)

    def _cycle_sign_ascendant(self):
        """
        Cycle through signs as Ascendant.

        F4 cycles: Dhata(0) → Aryama(1) → ... → Parjanya(11) → Birth Ascendant(None)

        This is a visualization tool that shows how the chart would look
        if any sign were the Ascendant. Useful for:
        - Exploring derived charts (e.g., Sun as Ascendant)
        - Understanding house placements from different perspectives
        - Teaching Whole Sign house concepts

        Shortcut: F4
        """
        from apps.widgets.chart_view import SouthIndianView

        ADITYA_NAMES = ["Dhata", "Aryama", "Mitra", "Varuna", "Indra", "Vivasvan",
                       "Tvasta", "Vishnu", "Amzu", "Bhaga", "Pusha", "Parjanya"]

        # NOTE (SPEC-SIC-003 §4.3): there is deliberately NO "F4 takes over
        # from the column" branch here. The column and F4 are two input
        # surfaces over ONE Ascendant state (INV-10), so a takeover is a
        # contradiction in terms. The branch that used to live here also
        # never cleared `selected_z6b_sign` — only the column module writes
        # it — so it re-fired on every subsequent press and re-zeroed the
        # counter, pinning F4 to Dhata forever after any column click.

        # Cycle logic: None → 0 → 1 → ... → 11 → None
        if self.current_ascendant_override is None:
            self.current_ascendant_override = 0  # Start with Dhata
        elif self.current_ascendant_override < 11:
            self.current_ascendant_override += 1  # Next sign
        else:
            self.current_ascendant_override = None  # Back to birth Ascendant

        override = self.current_ascendant_override

        # Keep the sign column showing where the chart is anchored (INV-10).
        # Uses the column's own setter, which does NOT re-enter
        # _on_z6b_selection_changed — synthesising a click here would
        # rewrite the counter this method is in the middle of advancing.
        from apps.panels.sign_selector_column import set_column_selection
        set_column_selection(
            self, None if override is None else override + 1)

        # Update Wheel view
        if hasattr(self, 'wheel_view') and self.wheel_view:
            self.wheel_view.set_ascendant_override(override)

        # Update South Indian view
        if hasattr(self, 'chart_view') and self.chart_view:
            self.chart_view.set_ascendant_override(override)

        # Update North Indian view
        if hasattr(self, 'north_indian_view') and self.north_indian_view:
            self.north_indian_view.set_ascendant_override(override)

        # Status message
        if override is not None:
            sign_name = ADITYA_NAMES[override]
            self.statusBar().showMessage(f"{sign_name} as Ascendant (F4 to cycle)")
        else:
            self.statusBar().showMessage("Birth Ascendant restored (F4 to cycle)")

    def _toggle_time_adjust(self):
        """
        Toggle Time Adjust mode - shows time adjustment buttons in chart center.
        When active, hides the sign preview (center display).
        """
        if not self.state.active_chart:
            print("[WARNING] No chart loaded, cannot toggle Time Adjust")
            self.statusBar().showMessage("Load a chart first")
            return

        from state.events import SetTimeAdjustMode
        self.state.dispatch(SetTimeAdjustMode(enabled=not self.state.time_adjust_mode))

        # Update button style
        self._update_toggle_button_styles()

        # Tell chart_view to enable/disable center preview
        if hasattr(self, 'chart_view') and self.chart_view:
            self.chart_view.set_time_adjust_mode(self.state.time_adjust_mode)

        # Show/hide time adjust widget overlay
        if self.state.time_adjust_mode:
            self._show_time_adjust_overlay()
            self.statusBar().showMessage("Birth time adjust ON - use buttons to adjust time")
        else:
            self._hide_time_adjust_overlay()
            self.statusBar().showMessage("Birth time adjust OFF")

    def _show_time_adjust_overlay(self):
        """Show the time adjust widget overlay in the chart center.

        NOTE: The widget is overlaid ON TOP of chart_view (as a regular Qt widget),
        NOT embedded in the QGraphicsScene. This avoids destruction when the chart
        is redrawn via update_from_chart().
        """
        from apps.widgets.time_adjust_widget import create_time_adjust_overlay

        if self.time_adjust_widget is None:
            self.time_adjust_widget = create_time_adjust_overlay(self)

        # Position widget on the left side of the chart area (works on any view)
        target = self.chart_stack if hasattr(self, 'chart_stack') else self.chart_view
        if target:
            self.time_adjust_widget.setParent(target)
            # Seed the live preview FIRST so the 3-line readout chip has its real
            # content BEFORE we measure: re-apply the theme-aware shell (rim
            # tracks a light<->dark switch), set Save/Revert state, capture the
            # last-saved baseline, and paint the readout. Sizing an empty label
            # then filling it left the first open clipped.
            self.time_adjust_widget._apply_shell_style()
            self.time_adjust_widget.update_save_button_state()
            self.time_adjust_widget.capture_baseline()
            self.time_adjust_widget.refresh_preview()
            # Now fit to the populated content and position (clamp y so a short
            # chart area never pushes the taller popup off the top).
            self.time_adjust_widget.adjustSize()
            view_rect = target.rect()
            widget_h = self.time_adjust_widget.height()
            margin = 10
            x = margin
            y = max(margin, (view_rect.height() - widget_h) // 2)
            self.time_adjust_widget.move(x, y)
            self.time_adjust_widget.raise_()  # Bring to front
            self.time_adjust_widget.show()

    def _hide_time_adjust_overlay(self):
        """Hide the time adjust widget overlay."""
        if self.time_adjust_widget:
            self.time_adjust_widget.hide()

    # ===== CLUSTER: ADD-CHART / NOW-CHART =====
    def show_add_chart_dialog(self):
        """Show AI-powered Add Chart dialog."""
        from ui.add_chart_dialog_qt import show_add_chart_dialog
        import copy

        def on_chart_loaded(chart, name, location, *, planets_data=None,
                            file_path=None):
            """Callback when chart is successfully generated.

            file_path: the file the pipeline wrote (SPEC-PERSIST-001 INV-7).
            It is recorded on the panel entry so the chart can be recovered
            from disk. The entry key is still called chtk_path — it has held
            the source path of ANY supported format since .toml import
            shipped.
            """
            from core.chart_factory import make_source_params, recipe_from_chart
            from state.events import SetActiveChart
            _chart = chart

            ctx = _chart.context
            lat = ctx.location.lat
            lon = ctx.location.long
            utcoffset = ctx.timeJD.utcoffset if hasattr(ctx.timeJD, 'utcoffset') else 0.0

            _pd = planets_data or {}
            country = _pd.get('country', 'Unknown')
            timezone_str = _pd.get('timezone', 'UTC')

            birth_data = {
                'name': name, 'year': ctx.timeJD.usryear(),
                'month': ctx.timeJD.usrmonth(), 'day': ctx.timeJD.usrday(),
                'timedec': ctx.timeJD.usrhour(), 'lat': lat, 'lon': lon,
                'utcoffset': utcoffset, 'city': location, 'country': country,
            }

            # 1. Dispatch state
            self.state.dispatch(SetActiveChart(
                chart=_chart,
                source_params=make_source_params(
                    chtk_path=file_path,
                    birth_data=birth_data,
                    mode=self.state.aditya_mode,
                    ayanamsa=self.chart_sidereal_ayanamsa_id,
                    house_system=self.state.house_system,
                    is_human_design=False,
                )))

            self.birth_jd = float(ctx.timeJD.jd)
            self.birth_lat = lat
            self.birth_lon = lon
            self.current_timezone = timezone_str
            self.person_name = name
            self.birth_country = country
            self.current_chart_path = file_path
            self.is_human_design = False

            # 2. Add recipe to memory panel (property fallback needs this)
            if hasattr(self, 'chart_memory_panel') and self.chart_memory_panel:
                # metadata N/A: the AI Add-Chart dialog does not collect
                # rodden/tags/notes and produces no julian_day/dst_offset_hours.
                _recipe = recipe_from_chart(
                    _chart, timezone=timezone_str,
                    city=location, country=country,
                )
                self.chart_memory_panel.add_chart(
                    _recipe, chart_obj=self.state.active_chart,
                    chtk_path=file_path,
                )

            # Invalidate property cache so fallback derives from new recipe
            self._current_chart_data = None
            self._current_birth_data = None

            # 3. Finalize
            self._finalize_chart_load()

            if hasattr(self, 'edit_chart_panel') and self.edit_chart_panel:
                mp = self.chart_memory_panel
                if mp and 0 <= mp.current_index < len(mp.charts):
                    self.edit_chart_panel.load_chart_from_memory(
                        mp.charts[mp.current_index]
                    )

        show_add_chart_dialog(self, on_chart_loaded)

    def _load_now_chart(self):
        """Create and display a transit chart for the current moment."""
        from core.transit_utils import calculate_transit_now, get_current_location, get_current_location_name
        from datetime import datetime
        from zoneinfo import ZoneInfo

        _transit_result = calculate_transit_now(
            mode=self.state.aditya_mode,
            ayanamsa=getattr(self, 'chart_sidereal_ayanamsa_id', 100),
            hsys=self.state.house_system_code,
        )
        if not _transit_result:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Transit Error", "Could not calculate transit chart.")
            return
        _transit_chart, iana_tz_str = _transit_result

        # Get location info for metadata
        lat, lon = get_current_location()
        location_name = get_current_location_name()
        city = location_name.split(",")[0].strip() if "," in location_name else location_name
        country = location_name.split(",")[1].strip() if "," in location_name else ""
        try:
            local_tz = ZoneInfo(iana_tz_str)
        except Exception:
            local_tz = ZoneInfo('UTC')
            iana_tz_str = 'UTC'

        # Convert UTC to true local time for display and metadata
        now_utc = datetime.now(ZoneInfo('UTC'))
        now_local = now_utc.astimezone(local_tz)
        name = f"Now {now_local.strftime('%A')}"
        _transit_chart.context.name = name

        _timedec = now_local.hour + now_local.minute / 60.0 + now_local.second / 3600.0
        _utc_off = now_local.utcoffset().total_seconds() / 3600.0 if now_local.utcoffset() else 0.0

        from core.chart_factory import make_recipe
        # metadata N/A: derived chart ("Now" transit, no birth metadata).
        _recipe = make_recipe(
            name=name,
            year=now_local.year, month=now_local.month, day=now_local.day,
            timedec=_timedec,
            utcoffset=_utc_off,
            timezone=iana_tz_str,
            lat=lat, lon=lon,
            city=city, country=country,
        )

        _now_birth_data = {
            'name': name,
            'year': now_local.year, 'month': now_local.month, 'day': now_local.day,
            'timedec': _timedec,
            'hour': now_local.hour, 'minute': now_local.minute, 'second': now_local.second,
            'lat': lat, 'lon': lon,
            'utcoffset': _utc_off,
            'iana_timezone': iana_tz_str, 'timezone': iana_tz_str,
            'city': city, 'country': country,
        }

        from core.chart_factory import make_source_params
        from state.events import SetActiveChart
        self.state.dispatch(SetActiveChart(chart=_transit_chart, source_params=make_source_params(
            chtk_path=None,
            birth_data=_now_birth_data,
            mode=self.state.aditya_mode,
            ayanamsa=self.chart_sidereal_ayanamsa_id,
            house_system=self.state.house_system,
            is_human_design=False,
        )))

        self.is_human_design = False
        self.current_chart_path = None
        self.current_timezone = iana_tz_str
        self.current_birth_data = _now_birth_data
        self._current_chart_data = None

        if hasattr(self, 'chart_memory_panel') and self.chart_memory_panel:
            self.chart_memory_panel.add_chart(
                _recipe,
                is_transit=True,
                chart_obj=self.state.active_chart,
            )

        # Update Edit Chart panel before finalize (matches chart_manager.load_chart ordering)
        chart_entry = {
            'recipe': _recipe,
            'birth_metadata': {},
            'birth_data': _now_birth_data,
            'person_name': name,
            'city': city,
            'country': country,
            'chtk_path': None,
        }
        if hasattr(self, 'edit_chart_panel') and self.edit_chart_panel:
            self.edit_chart_panel.load_chart_from_memory(chart_entry)

        self._finalize_chart_load()

    # ===== CLUSTER: TOGGLE BUTTON STYLES & CAPTURE =====
    def _update_toggle_button_styles(self):
        """
        Update toggle button appearances based on current settings.
        - Human Design: independent toggle (can be ON with either Aditya or Tropical)
        - Aditya/Tropical: mutually exclusive (one active at a time)
        - Aditya button has 3 visual states:
          1. Green (active): Aditya Circle mode with Aditya names
          2. Dark shade: Aditya Circle mode with Western names
          3. Gray (inactive): Tropical Classic mode
        Called when mode changes or theme refreshes.
        """
        if not hasattr(self, 'aditya_btn') or not hasattr(self, 'tropical_btn'):
            return

        # SPEC-MODE-001: in Beginner, force native naming BEFORE rendering so
        # the "*" (alternative names) variant never appears on screen. Order
        # matters for v2: the bar derives the * accent from use_western_names
        # AFTER this clamp has run (Dm3-19).
        if self._is_beginner_mode():
            _native = (self.state.aditya_mode != "aditya")
            if self.use_western_names != _native:
                self.use_western_names = _native

        # Sync sidereal View menu action checked state
        if hasattr(self, 'sidereal_action'):
            self.sidereal_action.setChecked(self.state.aditya_mode == "sidereal")

        # SPEC-BAR-001 M3 W7 (Dm3-12): the state SELECTION stays here; the
        # widget writes belong to the bar. v2 renders every toggle from live
        # state in one pass; the old bar keeps its QSS body below so the
        # ui.action_bar_v2 flag stays a true rollback.
        _bar = getattr(self, 'chart_title_widget', None)
        if hasattr(_bar, 'render_state'):
            _bar.render_state("toggles")
        else:
            self._legacy_toggle_button_styles()

        # Re-apply compact styles if in compact mode (prevents stomped
        # buttons). Inert under v2 (Dm3-43/46).
        self._reapply_compact_if_needed()

    def _legacy_toggle_button_styles(self):
        """OLD-BAR ONLY (ui.action_bar_v2=False): the QSS + setText writes
        _update_toggle_button_styles used to make inline. Deleted with the
        legacy construction at M6 (D-15). The Beginner clamp and the
        sidereal_action sync have ALREADY run in the caller."""
        # Theme-adaptive button styles — SPEC-THM-001 E5: module-level import.
        theme = get_theme_colors()

        # Green active style - Aditya mode with Aditya names
        active_style = f"""
            QPushButton {{
                background-color: {desat_hex('#4CAF50')};
                color: white;
                font-weight: bold;
                font-size: {scaled_area_px('buttons')}px;
                border: none;
                border-radius: 8px;
                padding: 8px 12px;
                min-width: 100px;
            }}
            QPushButton:hover {{
                background-color: {desat_hex('#45A049')};
            }}
        """

        # Dark shade style - Aditya mode with Western names
        western_names_style = f"""
            QPushButton {{
                background-color: {theme["secondary_dark"]};
                color: {theme["secondary_text"]};
                font-weight: bold;
                font-size: {scaled_area_px('buttons')}px;
                border: 1px solid {theme["primary"]};
                border-radius: 8px;
                padding: 8px 12px;
                min-width: 100px;
            }}
            QPushButton:hover {{
                background-color: {theme["secondary_light"]};
                color: {theme["secondary_text"]};
            }}
        """

        # Inactive style (theme-adaptive)
        inactive_style = f"""
            QPushButton {{
                background-color: {theme["secondary"]};
                color: {theme["secondary_text"]};
                font-size: {scaled_area_px('buttons')}px;
                border: 1px solid {theme["primary"]};
                border-radius: 8px;
                padding: 8px 12px;
                min-width: 100px;
            }}
            QPushButton:hover {{
                background-color: {theme["secondary_light"]};
                color: {theme["secondary_text"]};
            }}
        """

        # Time adjust button - independent toggle
        if hasattr(self, 'time_adjust_btn'):
            if self.state.time_adjust_mode:
                self.time_adjust_btn.setStyleSheet(active_style)
            else:
                self.time_adjust_btn.setStyleSheet(inactive_style)

        # Human Design button - independent toggle (can be ON with either Aditya or Tropical)
        if hasattr(self, 'human_design_btn'):
            if self.is_human_design:
                self.human_design_btn.setStyleSheet(active_style)
            else:
                self.human_design_btn.setStyleSheet(inactive_style)

        # Aditya/Tropical/Sidereal buttons - mutually exclusive with * for alternate names
        second_btn_label = "Sidereal" if self.chart_zodiac == "sidereal" else "Tropical Classic"

        if self.state.aditya_mode == "aditya":
            if self.use_western_names:
                self.aditya_btn.setText("Aditya Circle *")
                self.aditya_btn.setStyleSheet(western_names_style)
            else:
                self.aditya_btn.setText("Aditya Circle")
                self.aditya_btn.setStyleSheet(active_style)
            self.tropical_btn.setText(second_btn_label)
            self.tropical_btn.setStyleSheet(inactive_style)
        elif self.state.aditya_mode == "sidereal":
            self.aditya_btn.setText("Aditya Circle")
            self.aditya_btn.setStyleSheet(inactive_style)
            if self.use_western_names:
                self.tropical_btn.setText("Sidereal")
                self.tropical_btn.setStyleSheet(western_names_style)
            else:
                self.tropical_btn.setText("Sidereal *")
                self.tropical_btn.setStyleSheet(active_style)
        else:
            self.aditya_btn.setText("Aditya Circle")
            self.aditya_btn.setStyleSheet(inactive_style)
            if self.use_western_names:
                self.tropical_btn.setText(second_btn_label)
                self.tropical_btn.setStyleSheet(western_names_style)
            else:
                self.tropical_btn.setText(f"{second_btn_label} *")
                self.tropical_btn.setStyleSheet(active_style)

    # ===== CLUSTER: VARGA CENTER =====
    def _on_z6b_selection_changed(self, sign_index_1based):
        """Z6b sign-selector callback.

        Per-view semantics:
          - South Indian view: drives Mode 2 (mini North Indian in center).
          - Wheel view & North Indian view: F4-equivalent forced Ascendant.
        """
        sign_idx_0based = (sign_index_1based - 1) if sign_index_1based else None

        # One shared Ascendant state (SPEC-SIC-003 INV-10 / D-5): the column
        # writes the same counter F4 advances, so the two surfaces cannot
        # drift apart.
        self.current_ascendant_override = sign_idx_0based

        if hasattr(self, "chart_view") and self.chart_view:
            # D-6: the SI host re-anchors like every other view — the fan
            # reaches BOTH children, so a theme flip can never change the
            # effective Ascendant. set_z6b_selection stays because the
            # classic child still draws its mini North Indian chart from it.
            self.chart_view.set_ascendant_override(sign_idx_0based)
            self.chart_view.set_z6b_selection(sign_index_1based)

        if hasattr(self, "wheel_view") and self.wheel_view:
            self.wheel_view.set_ascendant_override(sign_idx_0based)

        if hasattr(self, "north_indian_view") and self.north_indian_view:
            self.north_indian_view.set_ascendant_override(sign_idx_0based)

        if sign_idx_0based is not None:
            from apps.widgets.chart_view import SouthIndianView
            sign_name = SouthIndianView.ADITYA_NAMES[sign_idx_0based]
            self.statusBar().showMessage(f"{sign_name} as Ascendant (F4 to cycle)")
        else:
            self.statusBar().showMessage("Birth Ascendant restored (F4 to cycle)")

    def _toggle_varga_in_center(self, enabled):
        """SPEC-VGC-001 §4.3 — the toggle below D-60.

        Writes the flag, persists it (D-7), and re-runs the current varga
        through the one writer. No routing logic of its own: everything that
        decides where a varga is drawn lives in `_apply_current_varga`.
        """
        self.varga_in_center = bool(enabled)
        try:
            from managers.settings_manager import get_settings
            get_settings().set("display.varga_in_center", self.varga_in_center)
        except Exception as e:      # a preference must never block the view
            print(f"[VARGA] Could not persist varga_in_center: {e}")

        self._apply_current_varga()

        varga = self.state.current_varga
        if not self.varga_in_center:
            self.statusBar().showMessage("Divisional chart back in the main chart")
        elif varga == 1:
            # D-3: nothing to compare yet. The box fills the moment a
            # divisional chart is picked, which explains itself better than
            # a refusal to toggle would.
            self.statusBar().showMessage(
                f"{self._varga_surface_phrase().capitalize()} ready - "
                "pick a divisional chart")
        else:
            name = VARGA_NAMES.get(varga, f"D-{varga}")
            self.statusBar().showMessage(
                f"{name} (D-{varga}) in the {self._varga_surface_phrase()} - "
                "main chart stays D-1")

    def _center_varga_suspended_by(self):
        """What is currently outranking the center varga, or None.

        D-1 chose precedence over mutually-exclusive toggles, on the
        grounds that the transit overlay is shared by every view and
        switching it off from the varga column would reach far outside the
        South Indian chart. The price of that choice is that the center
        varga can be SUSPENDED — and INV-5 says a suspension must be
        visible, or the toggle sits lit over a box showing something else
        and the selected varga is nowhere with no explanation.
        """
        if not getattr(self, 'varga_in_center', False):
            return None
        if self.state.current_varga == 1:
            return None
        # Time adjust belongs to the South Indian center box only; the wheel
        # and North Indian rings (SPEC-VGO-001) have no such mode, so asking
        # the South Indian child about it while the wheel is visible would
        # grey the toggle for a reason the user cannot see on screen.
        if self._varga_second_surface() == "center_box":
            view = getattr(self, 'chart_view', None)
            if view is None:
                return None
            child = getattr(view, 'active_view', view)
            if getattr(child, 'time_adjust_mode', False):
                return "time adjust"
        # The same INV-4 test every surface uses: enabled with no usable
        # chart draws nothing, so it takes nothing from the varga either.
        mgr = getattr(self, 'transit_overlay_manager', None)
        if (mgr is not None and getattr(mgr, "transit_enabled", False)
                and getattr(mgr, "transit_chart", None) is not None):
            return "transit"
        return None

    # Which second surface the VISIBLE view offers the varga, or None.
    # SPEC-VGO-001 INV-8: one toggle, three surfaces, and body graph has
    # none. Indices match _switch_to_chart_index / VALID_VIEWS.
    # 3 = Body Graph, 4 = Cards of Truth: neither has a second surface for the
    # varga (Cards of Truth is natal-only by INV-15), so the centre-varga
    # toggle greys out on both.
    _SECOND_SURFACE_BY_INDEX = {0: "center_box", 1: "outer_ring",
                                2: "outer_ring", 3: None, 4: None}

    def _varga_second_surface(self):
        """Name the second surface of the visible view, or None."""
        stack = getattr(self, 'chart_stack', None)
        if stack is None:
            return "center_box"
        return self._SECOND_SURFACE_BY_INDEX.get(stack.currentIndex())

    def _varga_surface_phrase(self):
        """The second surface, in the words the status bar uses.

        The messages used to say "center box" unconditionally, which became
        wrong the moment the wheel and North Indian charts grew a ring
        (SPEC-VGO-001). Falls back to the ring wording rather than to the
        South Indian one when no view is resolvable, because that is the
        wording that is true for two of the three surfaces.
        """
        return ("center box" if self._varga_second_surface() == "center_box"
                else "outer ring")

    def _sync_varga_center_button(self):
        """Enable the toggle only on a view that has a second surface.

        South Indian draws the varga inside its center box, the wheel and
        North Indian draw it as a ring around the chart (SPEC-VGO-001), and
        the body graph has nowhere to put it — a live-looking button that
        does nothing is worse than a grey one. The FLAG survives the
        disabled period: `_apply_current_varga` runs on the way back, so F2
        away and back restores the second chart.
        """
        btn = getattr(self, 'varga_center_button', None)
        if btn is None:
            return
        surface = self._varga_second_surface()
        btn.setEnabled(surface is not None)
        suspended = self._center_varga_suspended_by() if surface else None
        # A dynamic property so the stylesheet can dim it without a second
        # style path (Rule 20: no hardcoded hex outside the theme).
        btn.setProperty("suspended", bool(suspended))
        btn.style().unpolish(btn)
        btn.style().polish(btn)
        where = ("inside the center box" if surface == "center_box"
                 else "around the chart")
        if surface is None:
            btn.setToolTip(
                "The body graph has no second chart surface.\n"
                "Switch to a South Indian, wheel or North Indian chart.")
        elif suspended:
            btn.setToolTip(
                f"Showing {suspended} instead.\n"
                "The divisional chart returns when that is switched off.")
        else:
            btn.setToolTip(
                f"Show the divisional chart {where},\n"
                "keeping D-1 in the main chart")

    def _apply_current_varga(self):
        """Paint `state.current_varga` onto every surface. THE one writer.

        SPEC-VGC-001 §4.2, closes td-ijjf. `_switch_varga` used to be treated
        as the only route to the chart views, and it is not: three other
        paths re-render with no varga code at all (`_update_all_chart_views`,
        and both branches of `_toggle_wheel_view`). The visible symptom is a
        live bug independent of any feature — show D-10, press F2, and the
        wheel comes up D-1 while the varga column still shows 10 checked.
        Every one of those paths now calls this instead of hand-rolling
        `update_from_chart`.

        Deliberately does NOT dispatch, start the loading manager or refresh
        panels: the paths that call this already own those, and calling back
        into them would recurse (pre-mortem F-6). `_switch_varga` keeps the
        dispatch; this only paints.
        """
        active_chart = self.state.active_chart
        if not active_chart:
            return

        # td-sy9e: a full paint of every surface makes any deferred off-screen
        # F2 repaint moot — clear the stale flag so the Chart-tab return hook
        # does not repaint a second time.
        self._main_views_stale = False

        # Use libaditya Chart.varga(N) directly. Mode is baked into the Chart
        # at construction time (Issue 2), so chart.varga() already returns the
        # mode-correct Varga object — no `chart.tropical()` branch needed (G7).
        # Translate GUI varga numbers into libaditya's classical-formula codes
        # (negative for BPHS deity-based vargas) — without this, D-10/D-24/
        # D-40/D-45/D-60 silently return parivritti results.
        from core.varga_codes import to_libaditya_varga_code
        varga_number = self.state.current_varga
        rcode = (None if varga_number == 1
                 else to_libaditya_varga_code(varga_number))

        ayanamsa_off = (self.chart_ayanamsa_offset
                        if self.state.aditya_mode == "sidereal" else 0.0)
        use_western = getattr(self, 'use_western_names', False)
        render_offset = 0.0 if varga_number != 1 else ayanamsa_off

        # C9 / SPEC-HD gate: the -88 Design chart is BUILT in the HD-gated
        # frame (hd_manager.design_chart_mode()) — Beginner pins it to
        # Standard/tropical, Advanced follows the app mode. Its DISPLAY mode,
        # label set and ayanamsa must AGREE with that build, not with the app's
        # zodiac pills. Outside HD this is a no-op: in Advanced
        # design_chart_mode() == the app mode, and the branch only fires when
        # is_human_design. Never mutates state.aditya_mode (one resolver, both
        # views — same rule as hd_manager.frame()).
        if getattr(self, 'is_human_design', False):
            _disp_mode = self.hd_manager.design_chart_mode()
            _disp_western = (_disp_mode != 'aditya')
            _disp_ayan = ayanamsa_off if _disp_mode == 'sidereal' else 0.0
        else:
            _disp_mode = self.state.aditya_mode
            _disp_western = use_western
            _disp_ayan = ayanamsa_off
        _disp_render_off = 0.0 if varga_number != 1 else _disp_ayan

        # SPEC-VGC-001 + SPEC-VGO-001: with the mode on, the MAIN chart of
        # every view that has a second surface stays on D-1 and the varga is
        # drawn beside it — inside the South Indian center box, around the
        # wheel and the North Indian chart. Body graph has no second surface,
        # so it keeps the varga full-size (SPEC-VGC-001 D-2).
        in_second_surface = (bool(getattr(self, 'varga_in_center', False))
                             and rcode is not None)
        main_varga = None if in_second_surface else rcode
        center_varga = rcode if in_second_surface else None
        ring_varga = rcode if in_second_surface else None
        grid_varga = main_varga

        if hasattr(self, 'chart_view') and self.chart_view:
            self.chart_view.update_from_chart(
                active_chart, varga_code=grid_varga,
                use_western_names=_disp_western,
                ayanamsa_offset=(_disp_ayan if grid_varga is None
                                 else _disp_render_off),
                aditya_mode=_disp_mode)
            setter = getattr(self.chart_view, 'set_center_varga', None)
            if setter is not None:
                setter(center_varga)
        if hasattr(self, 'wheel_view') and self.wheel_view:
            self.wheel_view.update_from_chart(active_chart, varga_code=main_varga,
                                               ring_varga_code=ring_varga,
                                               use_western_names=_disp_western,
                                               ayanamsa_offset=(_disp_ayan if main_varga is None
                                                                else _disp_render_off),
                                               aditya_mode=_disp_mode)
        if hasattr(self, 'north_indian_view') and self.north_indian_view:
            self.north_indian_view.update_from_chart(active_chart, varga_code=main_varga,
                                                      ring_varga_code=ring_varga,
                                                      use_western_names=_disp_western,
                                                      ayanamsa_offset=(_disp_ayan if main_varga is None
                                                                       else _disp_render_off),
                                                      aditya_mode=_disp_mode)
        if hasattr(self, 'body_graph_view') and self.body_graph_view:
            self.body_graph_view.update_from_chart(active_chart, varga_code=rcode,
                                                    use_western_names=_disp_western,
                                                    ayanamsa_offset=_disp_render_off,
                                                    aditya_mode=_disp_mode,
                                                    gender=self._current_body_gender())
        # SPEC-COT-001 INV-15 v2: the spread FOLLOWS the varga. It gets the full
        # rcode, like the body graph, because it has no second surface — the
        # divisional placement IS the main content, not a side panel. The card
        # faces do not move with the varga; only which card each body falls in.
        if hasattr(self, 'cards_of_truth_view') and self.cards_of_truth_view:
            self.cards_of_truth_view.update_from_chart(active_chart, varga_code=rcode)

        # SPEC-NAK-LITE-001: the restricted Nakshatra wheel is always the D-1
        # sidereal nakshatras — it does NOT follow the varga. Push the active
        # chart so a new chart shows while it is the visible view; mode/ayanamsa
        # redraws are owned by the panel's own frame_changed subscription.
        if hasattr(self, 'nakshatra_core_panel') and self.nakshatra_core_panel:
            self.nakshatra_core_panel.update_from_chart(active_chart)

        # SPEC-HD-001 §8: the HD page is F2-excluded and not in the loop above.
        # The manager invalidates its cache and re-pushes ONLY if HD is current,
        # so a varga/chart change behind another view costs nothing (Rule 4).
        if hasattr(self, 'hd_manager'):
            self.hd_manager.refresh_active_view()

        if hasattr(self, 'varga_buttons') and varga_number in self.varga_buttons:
            self.varga_buttons[varga_number].setChecked(True)
        if hasattr(self, 'varga_actions') and varga_number in self.varga_actions:
            self.varga_actions[varga_number].setChecked(True)

        # Surya/Chandra Lagna follows the main chart painted above. Resolve
        # after repaint so chart/frame/varga changes cannot leave it stale.
        refresh_named_lagna(self)

        self._sync_varga_center_button()
        self._update_title()

    def _switch_varga(self, varga_number):
        """Switch to display a different Varga chart"""
        # Chart-Everywhere Issue 3 (G8): guard on active_chart, not the dict.
        if not self.state.active_chart:
            self.statusBar().showMessage("No chart loaded - load a chart first")
            return

        from state.events import SetVarga
        self.state.dispatch(SetVarga(varga_number=varga_number))

        # Panels react to that dispatch on their own (state/panel_mixin.py).
        # Almost all of them are D1-only by design and do not follow the
        # varga at all — `shame_controller` is the single exception.
        self._apply_current_varga()

        # Ensure varga chart displays immediately
        QApplication.processEvents()

        varga_name = VARGA_NAMES.get(varga_number, f"D-{varga_number}")
        suspended = self._center_varga_suspended_by()
        if suspended:
            # INV-5: the varga is selected but nothing on screen shows it.
            self.statusBar().showMessage(
                f"{varga_name} (D-{varga_number}) selected - the "
                f"{self._varga_surface_phrase()} is showing {suspended}")
        elif getattr(self, 'varga_in_center', False) and varga_number != 1:
            # D-4: the main chart IS D-1 here, so say where the varga went
            # rather than claiming the chart is a varga.
            self.statusBar().showMessage(
                f"{varga_name} (D-{varga_number}) in the "
                f"{self._varga_surface_phrase()} - main chart stays D-1")
        else:
            self.statusBar().showMessage(
                f"Showing {varga_name} (D-{varga_number}) chart")

    # ─── Keyboard Shortcuts ───────────────────────────────────────────
    # ===== CLUSTER: CHART LOAD CALLBACKS & REQUEST HANDLERS =====
    def load_chart(self, chtk_path):
        """Load CHTK file and display chart. Delegates to ChartManager."""
        self.chart_manager.load_chart(chtk_path)

    def _on_chart_folders_changed(self):
        """Reload Find Chart paths after Settings saves. SPEC-FIND-003: no auto-rebuild."""
        if hasattr(self, 'find_chart_panel') and self.find_chart_panel:
            self.find_chart_panel._load_folder_paths()
            self.find_chart_panel.index_status.setText(
                "Folders updated. Click REBUILD INDEX to re-index.")

    def _on_find_chart_selected(self, filepath):
        """Handle chart selection from Find Chart tab."""
        # Switch to Chart tab first so loading overlay appears on the correct tab
        # and chart views have correct geometry before rendering.
        self.tab_widget.setCurrentIndex(0)
        self.chart_manager.load_chart(filepath)

    def _on_birth_finder_result_selected(self, result_data):
        """Handle result selection from Birth Finder tab - load as synthetic chart."""
        # Extract birth data
        dt = result_data['datetime']
        lat = result_data['lat']
        lon = result_data['lon']
        # Extract location info from Birth Finder fields
        city = result_data.get('city', '') or f"Lat {lat:.2f}"
        country = result_data.get('country', '') or f"Lon {lon:.2f}"
        # The row's `timezone` offset string is deliberately NOT read here. It
        # was read into a local and then never used: `load_chart_from_datetime`
        # builds with `utcoffset=0.0` (`tools/chtk_loader.py:46`), so the result
        # datetime is treated as the UTC instant it actually is. Reinstating the
        # offset without first defining Birth Finder's local-time contract
        # (SPEC-MAP-004 F-7) would shift every loaded chart by that offset.
        # Create a synthetic name for the chart
        if result_data.get('is_range'):
            name = f"Birth Finder Result (Range: {dt.strftime('%Y-%m-%d')})"
        else:
            name = f"Birth Finder Result ({dt.strftime('%Y-%m-%d %H:%M')})"

        # Load the chart using datetime and location
        from tools.chtk_loader import load_chart_from_datetime
        try:
            if load_chart_from_datetime(self, dt, lat, lon, name=name):
                # Store birth parameters from Chart object
                _chart = self.state.active_chart
                self.birth_jd = float(_chart.context.timeJD.jd)
                self.birth_lat = _chart.context.location.lat
                self.birth_lon = _chart.context.location.long
                self.is_human_design = False
                self.current_chart_path = None

                # IANA timezone for title display and for the memory recipe.
                #
                # SPEC-MAP-004 W2 step 4. The row carries the zone the map
                # resolved when the user picked the place, so prefer it: it is
                # the same answer this code used to recompute, and recomputing
                # it cost a fresh `TimezoneFinder()` -- ~800 ms of shapefile
                # loading on the GUI thread, on every double-click of a result,
                # for a value the panel already had. It was also a second
                # source of truth for a field that ends up in a saved recipe.
                #
                # The fallback stays for rows with no name (a hand-typed
                # location, or a point the finder could not resolve) and now
                # goes through the process-wide singleton rather than building
                # its own (SPEC-MAP-001 INV-7). "Warmed" would overstate it on
                # this road: `start_warmup()` runs when a map surface is built,
                # and a hand-typed location may never have opened one, in which
                # case this still constructs synchronously on the GUI thread.
                # Once per session instead of once per double-click, which is
                # the improvement actually being claimed.
                self.current_timezone = result_data.get('tz_name') or None
                if not self.current_timezone:
                    try:
                        from core.tz_finder import timezone_at
                        self.current_timezone = timezone_at(lat, lon) or 'UTC'
                    except Exception as e:
                        print(f"[WARNING] timezone lookup failed for ({lat}, {lon}): {e}")
                        self.current_timezone = 'UTC'

                from core.chart_factory import make_source_params, recipe_from_chart
                from state.events import SetActiveChart
                self.state.dispatch(SetActiveChart(chart=_chart, source_params=make_source_params(
                    chtk_path=None,
                    birth_data={
                        'name': name,
                        'year': dt.year, 'month': dt.month, 'day': dt.day,
                        'timedec': dt.hour + dt.minute / 60.0 + dt.second / 3600.0,
                        'lat': lat, 'lon': lon,
                    },
                    mode=self.state.aditya_mode,
                    ayanamsa=self.chart_sidereal_ayanamsa_id,
                    house_system=self.state.house_system,
                    is_human_design=False,
                )))

                mp = getattr(self, 'memory_panel', None) or getattr(self, 'chart_memory_panel', None)
                if mp:
                    # metadata N/A: derived chart (birth-time finder result).
                    _bf_recipe = recipe_from_chart(
                        _chart, name=name,
                        timezone=self.current_timezone,
                        city=city, country=country,
                    )
                    mp.add_chart(_bf_recipe, chart_obj=_chart)

                self._current_chart_data = None
                self._current_birth_data = None
                self._finalize_chart_load()

                if hasattr(self, 'edit_chart_panel') and self.edit_chart_panel:
                    if mp and 0 <= mp.current_index < len(mp.charts):
                        self.edit_chart_panel.load_chart_from_memory(
                            mp.charts[mp.current_index]
                        )

                self.tab_widget.setCurrentIndex(0)
        except Exception as e:
            print(f"Error loading Birth Finder result: {e}")
            import traceback
            traceback.print_exc()
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "Load Error",
                f"Could not load chart from Birth Finder result:\n{e}"
            )

    def _on_lunar_chart_requested(self, chart_data: dict):
        """Handle chart request from Lunar New Year panel - load chart for that date.

        IMPORTANT: This follows the same pattern as _on_birth_finder_result_selected.
        When loading a synthetic chart from datetime, you MUST:
        1. Call load_chart_from_datetime() to get planets_data
        2. Store birth_jd, birth_lat, birth_lon, is_human_design
        3. Update chart_view with _update_all_chart_views()
        4. Set current_chart_path = None (no CHTK file)
        5. Set current_chart_data with full birth info (CRITICAL for dasha)
        6. Set current_planets_data and current_varga = 1
        7. Update varga menu action state
        8. Update title, panels, and memory panel
        9. Switch to Chart tab
        """
        # Extract data from the signal
        # dt_local = LOCAL time for display, dt_utc = UTC for calculations
        dt_local = chart_data.get('datetime')  # Local time for display
        dt_utc = chart_data.get('datetime_utc', dt_local)  # UTC for calculations (fallback to local)
        lat = chart_data.get('lat', 0.0)
        lon = chart_data.get('lon', 0.0)
        timezone_str = chart_data.get('timezone', 'UTC')
        name = chart_data.get('name', f"Lunar New Year {dt_local.year if dt_local else 'Unknown'}")

        if not dt_local:
            return

        # Load the chart using UTC datetime for accurate planet positions
        from tools.chtk_loader import load_chart_from_datetime
        try:
            if not load_chart_from_datetime(self, dt_utc, lat, lon, name=name,
                                               preserve_natal=True):
                return
            if True:
                _chart = self.state.active_chart
                self.is_human_design = False
                self.current_chart_path = None
                self.current_timezone = timezone_str

                city = chart_data.get('city', f"Lat {lat:.2f}")
                country = chart_data.get('country', f"Lon {lon:.2f}")

                from core.chart_factory import make_source_params, recipe_from_chart
                from state.events import SetActiveChart
                self.state.dispatch(SetActiveChart(chart=_chart, source_params=make_source_params(
                    chtk_path=None,
                    birth_data={
                        'name': name,
                        'year': dt_local.year, 'month': dt_local.month, 'day': dt_local.day,
                        'timedec': dt_local.hour + dt_local.minute / 60.0 + dt_local.second / 3600.0,
                        'lat': lat, 'lon': lon,
                    },
                    mode=self.state.aditya_mode,
                    ayanamsa=self.chart_sidereal_ayanamsa_id,
                    house_system=self.state.house_system,
                    is_human_design=False,
                )))

                mp = getattr(self, 'memory_panel', None) or getattr(self, 'chart_memory_panel', None)
                if mp:
                    # metadata N/A: derived chart (lunar return).
                    _lunar_recipe = recipe_from_chart(
                        _chart, name=name, timezone=timezone_str,
                        city=city, country=country,
                    )
                    mp.add_chart(_lunar_recipe, chart_obj=_chart)

                self._current_chart_data = None
                self._current_birth_data = None
                self._finalize_chart_load()

                if hasattr(self, 'edit_chart_panel') and self.edit_chart_panel:
                    if mp and 0 <= mp.current_index < len(mp.charts):
                        self.edit_chart_panel.load_chart_from_memory(
                            mp.charts[mp.current_index]
                        )

                self.tab_widget.setCurrentIndex(0)

                if hasattr(self, 'chart_view') and self.chart_view:
                    self.chart_view._is_dragging = False
                    from PySide6.QtWidgets import QGraphicsView
                    self.chart_view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
                    self.chart_view.viewport().setCursor(Qt.CursorShape.ArrowCursor)
                    self.chart_view.setFocus()
        except Exception as e:
            print(f"Error loading Lunar New Year chart: {e}")
            import traceback
            traceback.print_exc()

    def _on_eclipse_chart_requested(self, chart_data: dict):
        """Handle chart request from Eclipse panel - load chart for that date/location.

        This follows the same pattern as _on_lunar_chart_requested.
        See docs/CHART_LOADING_PATTERN.md for the complete pattern.
        """
        # Extract data from the signal
        dt_local = chart_data.get('datetime')  # Local time for display
        dt_utc = chart_data.get('datetime_utc', dt_local)  # UTC for calculations
        lat = chart_data.get('lat', 0.0)
        lon = chart_data.get('lon', 0.0)
        timezone_str = chart_data.get('timezone', 'UTC')
        name = chart_data.get('name', f"Eclipse {dt_local.year if dt_local else 'Unknown'}")

        if not dt_local:
            return

        # Load the chart using UTC datetime for accurate planet positions
        from tools.chtk_loader import load_chart_from_datetime
        try:
            if not load_chart_from_datetime(self, dt_utc, lat, lon, name=name,
                                               preserve_natal=True):
                return
            if True:
                _chart = self.state.active_chart
                self.is_human_design = False
                self.current_chart_path = None
                self.current_timezone = timezone_str

                city = chart_data.get('city', f"Lat {lat:.2f}")
                country = chart_data.get('country', f"Lon {lon:.2f}")

                from core.chart_factory import make_source_params, recipe_from_chart
                from state.events import SetActiveChart
                self.state.dispatch(SetActiveChart(chart=_chart, source_params=make_source_params(
                    chtk_path=None,
                    birth_data={
                        'name': name,
                        'year': dt_local.year, 'month': dt_local.month, 'day': dt_local.day,
                        'timedec': dt_local.hour + dt_local.minute / 60.0 + dt_local.second / 3600.0,
                        'lat': lat, 'lon': lon,
                    },
                    mode=self.state.aditya_mode,
                    ayanamsa=self.chart_sidereal_ayanamsa_id,
                    house_system=self.state.house_system,
                    is_human_design=False,
                )))

                mp = getattr(self, 'memory_panel', None) or getattr(self, 'chart_memory_panel', None)
                if mp:
                    # metadata N/A: derived chart (eclipse).
                    _eclipse_recipe = recipe_from_chart(
                        _chart, name=name, timezone=timezone_str,
                        city=city, country=country,
                    )
                    mp.add_chart(_eclipse_recipe, chart_obj=_chart)

                self._current_chart_data = None
                self._current_birth_data = None
                self._finalize_chart_load()

                if hasattr(self, 'edit_chart_panel') and self.edit_chart_panel:
                    if mp and 0 <= mp.current_index < len(mp.charts):
                        self.edit_chart_panel.load_chart_from_memory(
                            mp.charts[mp.current_index]
                        )

                self.tab_widget.setCurrentIndex(0)

                if hasattr(self, 'chart_view') and self.chart_view:
                    self.chart_view._is_dragging = False
                    from PySide6.QtWidgets import QGraphicsView
                    self.chart_view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
                    self.chart_view.viewport().setCursor(Qt.CursorShape.ArrowCursor)
                    self.chart_view.setFocus()
                    self.chart_view.viewport().setFocus()
        except Exception as e:
            print(f"Error loading Eclipse chart: {e}")
            import traceback
            traceback.print_exc()

    def _on_transit_chart_requested(self, chart_data: dict):
        """Handle chart request from Transit panel.

        This is primarily used when user wants to load a chart into main view
        from the Transit panel (e.g., clicking to load the natal chart).
        """
        # For now, the Transit panel doesn't emit chart requests
        # This handler is a placeholder for future functionality
        # (e.g., loading natal chart from transit dropdown into main view)
        pass

    def _on_exploration_chart_requested(self, chart_data: dict):
        """Handle chart request from Exploration panel — load CHTK file into main view.

        The Exploration panel creates CHTK files on disk. This handler reads
        the CHTK, converts to UTC, and follows the same pattern as eclipse/lunar handlers.
        """
        import os

        chtk_path = chart_data.get('chtk_path')
        name = chart_data.get('name', 'Exploration Chart')

        if not chtk_path or not os.path.exists(chtk_path):
            print(f"[ERROR] CHTK file not found: {chtk_path}")
            return

        try:
            from managers.birth_data_manager import BirthDataManager
            # SPEC-IMPORT-001 §6.1: dispatch by extension so exploration can load
            # both .chtk and .toml companion charts.
            bd = BirthDataManager.create_birth_data_from_file(chtk_path)
            BirthDataManager.report_tz_warnings(
                BirthDataManager.validate_birth_data(bd),
                status_bar=self.statusBar(), context=f"Companion {name}")

            lat = bd['latitude']
            lon = bd['longitude']
            city = bd.get('city', 'Unknown')
            country = bd.get('country', 'Unknown')

            self.loading_manager.start(f"Loading {name}...")
            # Single birth-data -> JD home (td-7q5s.3 C1): byte-identical to the
            # inline it replaces (honor the file's [moment].jd when present for
            # TOML; else compute from civil via the calendar-aware
            # time_utils.julday). Mirrors chart_manager.load_chart (M5, spec §6.2).
            from core.chart_factory import jd_from_birth_data
            birth_jd = jd_from_birth_data(bd)
            _utc_off = bd.get('utc_offset_hours', 0.0)

            from core.chart_factory import build_chart_from_params, make_source_params
            from state.events import SetActiveChart, SetVarga
            try:
                _chart = build_chart_from_params(
                    jd=birth_jd, lat=lat, lon=lon,
                    mode=self.state.aditya_mode, utcoffset=_utc_off,
                    ayanamsa=self.chart_sidereal_ayanamsa_id, name=name,
                    hsys=self.state.house_system_code,
                )
            except Exception as e:
                print(f"[ERROR] Failed to calculate chart for {name}: {e}")
                return

            self.person_name = name
            self.birth_country = country
            self.birth_jd = float(_chart.context.timeJD.jd)
            self.birth_lat = _chart.context.location.lat
            self.birth_lon = _chart.context.location.long
            self.is_human_design = False
            self.current_chart_path = chtk_path
            self.current_timezone = bd.get('iana_timezone', 'UTC')

            self.state.dispatch(SetActiveChart(chart=_chart, source_params=make_source_params(
                chtk_path=str(chtk_path) if chtk_path else None,
                birth_data=bd,
                mode=self.state.aditya_mode,
                ayanamsa=self.chart_sidereal_ayanamsa_id,
                house_system=self.state.house_system,
                is_human_design=False,
            )))

            mp = getattr(self, 'memory_panel', None) or getattr(self, 'chart_memory_panel', None)
            if mp:
                from core.chart_factory import recipe_from_chart
                # SPEC-IMPORT-001 §6.3: forward TOML-native metadata from the
                # loaded birth_data so rodden/tags/notes survive into the recipe
                # (and thus session.json). Absent on CHTK-origin charts -> None.
                _expl_recipe = recipe_from_chart(
                    _chart, name=name, timezone=self.current_timezone,
                    city=city, country=country,
                    gender=bd.get('gender', 'Unknown'),
                    time_change_flag=bd.get('time_change_flag', 0),
                    rodden=bd.get('rodden'), tags=bd.get('tags'),
                    notes=bd.get('notes'), julian_day=bd.get('julian_day'),
                    dst_offset_hours=bd.get('dst_offset_hours'),
                )
                mp.add_chart(
                    _expl_recipe,
                    chtk_path=str(chtk_path) if chtk_path else None,
                    chart_obj=_chart,
                )

            self._current_chart_data = None
            self._current_birth_data = None
            self._finalize_chart_load()

            if hasattr(self, 'edit_chart_panel') and self.edit_chart_panel:
                if mp and 0 <= mp.current_index < len(mp.charts):
                    self.edit_chart_panel.load_chart_from_memory(
                        mp.charts[mp.current_index]
                    )

            self.tab_widget.setCurrentIndex(0)
            self.statusBar().showMessage(f"Loaded: {name}")

            if hasattr(self, 'chart_view') and self.chart_view:
                self.chart_view._is_dragging = False
                from PySide6.QtWidgets import QGraphicsView
                self.chart_view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
                self.chart_view.viewport().setCursor(Qt.CursorShape.ArrowCursor)
                self.chart_view.setFocus()

            self.loading_manager.finish()

        except Exception as e:
            self.loading_manager.force_finish()
            print(f"Error loading Exploration chart: {e}")
            import traceback
            traceback.print_exc()

    # === THEME MANAGEMENT METHODS ===

    # ===== CLUSTER: THEME / FONT / SCALE / SATURATION REFRESH =====
    def _load_theme_preference(self) -> str:
        """Load saved theme preference, SettingsManager first (in-memory), PrefsStore fallback."""
        try:
            from managers.settings_manager import get_settings
            theme_name = get_settings().get("appearance.theme", "")
            if theme_name:
                from ui.themes import THEME_NAME_TO_FILE
                filename = THEME_NAME_TO_FILE.get(theme_name)
                if filename:
                    return filename
            return self.prefs_store.get("theme", "dark_blue.xml")
        except Exception as e:
            print(f"Error loading theme preference: {e}")
        return "dark_blue.xml"

    def _save_theme_preference(self, theme_file: str):
        """Save theme preference to both PrefsStore and SettingsManager."""
        try:
            self.prefs_store.update("theme", theme_file)
            from ui.themes import THEME_FILE_TO_NAME
            display_name = THEME_FILE_TO_NAME.get(theme_file)
            if display_name:
                from managers.settings_manager import get_settings
                get_settings().persist_runtime_change("appearance.theme", display_name)
        except Exception as e:
            print(f"Error saving theme preference: {e}")

    def _on_tab_changed(self, index: int):
        """Handle tab switch events - triggers lazy loading for placeholder tabs."""
        # Track tab usage (but not during preloading or before init completes)
        if not getattr(self, '_preloading', True):
            tab_name = self.tab_widget.tabText(index)
            self._tab_usage_counts[tab_name] = self._tab_usage_counts.get(tab_name, 0) + 1
            try:
                from managers.settings_manager import get_settings
                get_settings().set("ui.last_active_tab", index)
            except Exception:
                pass

        tab_widget = self.tab_widget.widget(index)

        # === LAZY LOADING: Check if a placeholder tab was clicked ===
        # Settings tab
        if hasattr(self, '_settings_placeholder') and tab_widget == self._settings_placeholder:
            self._create_settings_widget()
            return

        # Find Chart tab
        if hasattr(self, '_find_chart_placeholder') and tab_widget == self._find_chart_placeholder:
            self._create_find_chart_widget()
            return

        if hasattr(self, 'find_chart_panel') and tab_widget == self.find_chart_panel:
            if self.find_chart_panel.cache and len(self.find_chart_panel.cache.index) == 0:
                QTimer.singleShot(100, self.find_chart_panel._load_cached_index)
            return

        # Edit Chart tab (lazy placeholder)
        if hasattr(self, '_edit_chart_placeholder') and tab_widget == self._edit_chart_placeholder:
            self._create_edit_chart_widget()
            return

        # === EXISTING LOGIC ===
        # Check if Edit Chart tab was selected
        if hasattr(self, 'edit_chart_panel') and tab_widget == self.edit_chart_panel:
            # Only load from GUI if edit panel doesn't already have data
            # (prevents overwriting data just loaded from memory panel)
            if not self.edit_chart_panel.current_chart_data:
                if self.state.active_chart:
                    self.edit_chart_panel.load_from_gui()

        # Deferred panel chart-refresh for Nakshatra/Antikythera (perf: ~0.5s each)
        for attr in ('nakshatra_panel', 'antikythera_panel'):
            panel = getattr(self, attr, None)
            if panel and tab_widget is panel and getattr(panel, '_chart_dirty', False):
                panel._chart_dirty = False
                if self.state.active_chart:
                    panel.update_from_chart(self.state.active_chart, aditya_mode=self.state.aditya_mode)
                    panel._last_rendered_chart_id = id(self.state.active_chart)

        # td-u53i: the deferred retinue-ring catch-up moved into
        # WheelView.showEvent. The loop that lived here compared
        # `tab_widget is panel`, which is never true for the Transit/SR
        # SUBPAGES of the Predictive Tools tab — their dirty flags were never
        # consumed, so F5/F6/F9 changes only appeared when an unrelated
        # render happened to redraw a wheel. showEvent covers every reveal
        # path (tab switch, subpage nav, dual-stack index switch) per wheel.

    def _on_theme_changed(self, theme_file: str, loading_message: str = None):
        """Handle theme change from settings tab - apply immediately.

        loading_message overrides the "Applying <Theme>..." caption — the
        saturation fan-out reuses this method but is not a theme change, so it
        passes its own label (SPEC-SAT-001) instead of the current theme name.
        """
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QCursor

        apply_fn = _get_apply_stylesheet()
        if apply_fn:
            theme_name = theme_file.replace('.xml', '').replace('_', ' ').title()
            self.loading_manager.start(loading_message or f"Applying {theme_name}...")
            QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))

            try:
                # SPEC-SAT-001 WI-2: apply a DESATURATED copy of the theme XML
                # when the saturation slider is below 100 (no-op at 100 — the
                # built-in name passes straight through). This is the SINGLE
                # application point for all qt-material chrome; get_theme_colors()
                # inherits the muted QTMATERIAL_* env vars for free. theme_file
                # stays the logical name so _save_theme_preference is unaffected.
                from ui.qt_theme import desaturated_theme_path
                apply_fn(QApplication.instance(), theme=desaturated_theme_path(theme_file), style=None)
                # G9d: qt-material reset the app sheet, so re-append the global
                # input-font rule (else combos/inputs snap back to the frozen 13px).
                from ui.input_font_qss import apply_global_input_font_qss
                apply_global_input_font_qss(QApplication.instance())
                self._save_theme_preference(theme_file)
                # Refresh tab bar and menu bar styles (reads from qt-material env vars)
                from ui.qt_theme import apply_menu_bar_style
                self.tab_widget.setStyleSheet(get_tab_bar_style())
                apply_menu_bar_style(self.menuBar())
                # Refresh dasha list styles to pick up new theme colors
                self._refresh_panel_styles()
                # SPEC-THM-001 E1: REMOVED redundant dasha recalculation.
                # _update_vedanga_dasha() and _update_vimshottari_dasha() rebuilt
                # the entire dasha tree on every theme switch with no chart change.
                # The list stylesheets are already refreshed by _refresh_panel_styles
                # (via get_list_style), and DashaHighlightDelegate.paint() reads
                # get_theme_colors() at paint time. No recalculation needed.
                # Refresh info panels
                self._update_all_panels()
                # SPEC-THM-001 (td-iqjb Wave A): refresh every themed surface in
                # ISOLATION. Previously a single raising refresh_theme() aborted the
                # entire fan-out below it, leaving those surfaces unstyled ("white
                # patches in dark theme"). _safe_theme() mirrors the per-surface
                # pattern already used by _on_font_sizes_changed()/_refresh_scaled_surfaces.
                # WIRING ONLY - no per-surface logic changed; same attrs/methods/guards.
                import traceback as _tb_theme
                _theme_failures = []

                def _safe_theme(label, fn):
                    try:
                        fn()
                    except Exception:
                        _theme_failures.append(label)
                        _tb_theme.print_exc()

                def _refresh_attr(attr, method='refresh_theme', *args):
                    obj = getattr(self, attr, None)
                    fn = getattr(obj, method, None) if obj is not None else None
                    if callable(fn):
                        _safe_theme(attr, lambda: fn(*args))

                # Core panels/widgets with module-level refresh helpers
                _refresh_attr('memory_panel')
                # Birth Time +/- popup: re-skin dark HUD <-> light panel. Lazily
                # created (may be None); _refresh_attr no-ops if absent.
                _refresh_attr('time_adjust_widget')
                if hasattr(self, 'chart_title_widget'):
                    from apps.widgets.chart_title_widget import refresh_chart_title_theme
                    _safe_theme('chart_title_widget', lambda: refresh_chart_title_theme(self))
                if hasattr(self, 'varga_buttons'):
                    from apps.panels.varga_column import refresh_varga_theme
                    _safe_theme('varga_buttons', lambda: refresh_varga_theme(self))
                if hasattr(self, 'sign_selector_buttons'):
                    from apps.panels.sign_selector_column import refresh_sign_selector_theme
                    _safe_theme('sign_selector_buttons', lambda: refresh_sign_selector_theme(self))
                if hasattr(self, 'profile_button'):
                    _safe_theme('profile_button', self._update_profile_button_style)
                # SPEC-THM-002 §6.4 / D-7: fullscreen InfoPanelDialogs are
                # non-modal top-levels that outlive the click that opened them.
                # They were absent from this fan-out entirely, so a theme switch
                # with one open left it painted in the old palette. Weak refs —
                # a strong list here would pin every dialog ever opened.
                for _dlg_ref in list(getattr(self, '_open_panel_dialogs', ()) or ()):
                    _dlg = _dlg_ref()
                    if _dlg is not None:
                        _safe_theme('info_panel_dialog', _dlg.refresh_theme)
                if getattr(self, '_open_panel_dialogs', None) is not None:
                    self._open_panel_dialogs[:] = [
                        r for r in self._open_panel_dialogs if r() is not None]
                # Pro panels (ProChartGUI subclass creates these as self.<attr>;
                # _refresh_attr no-ops cleanly when an attr/method is absent).
                _refresh_attr('ai_reading_panel')       # deprecated; never instantiated
                _refresh_attr('find_chart_panel')
                _refresh_attr('birth_finder_panel')
                _refresh_attr('lunar_new_year_panel')
                _refresh_attr('eclipse_panel')
                _refresh_attr('transit_panel')
                _refresh_attr('solar_return_page')       # td-iqjb Wave A: previously orphaned
                _refresh_attr('edit_chart_panel')
                _refresh_attr('settings_tab')
                _refresh_attr('exploration_panel')
                _refresh_attr('cliwoc_map_panel')        # not instantiated in Pro
                _refresh_attr('nakshatra_core_panel')    # Core/F2 scene + viewport canvas
                _refresh_attr('nakshatra_panel')         # td-iqjb Wave D: now has refresh_theme
                _refresh_attr('antikythera_panel')       # td-iqjb Wave D: now has refresh_theme
                # SPEC-THM-001 W1: four chart views re-read get_theme_colors() and redraw
                # to apply colors to existing scene items (pre-mortem P-002/P-003).
                _refresh_attr('chart_view')
                _refresh_attr('wheel_view')
                _refresh_attr('north_indian_view')
                # SPEC-BODY-001: body graph swaps its background pixmap between the
                # dark/light silhouette variants on theme change.
                _refresh_attr('body_graph_view')
                # SPEC-COT-001 §4.5: the card table has tuned dark/light palettes
                # (a literal #000 "black" suit is invisible on the dark table),
                # read live in paintEvent — refresh_theme just repaints.
                _refresh_attr('cards_of_truth_view')
                # SPEC-HD-001: the HD page (HDPanel) reads hd_palette() at paint
                # time and swaps its whole light/dark token table on a theme
                # switch. Without this it only re-themed on FONT changes (it is in
                # _refresh_scaled_surfaces), so a live Dark<->Light switch left the
                # page on the old palette — caught by the :0 dark/light harness.
                _refresh_attr('human_design_view')
                # SPEC-FSV-001: status-bar chart chrome (ORDER pill + fullscreen
                # button) — painted widgets that read the palette live, so their
                # refresh_theme is a bare repaint.
                _refresh_attr('status_order_button')
                _refresh_attr('status_fullscreen_button')
                # SPEC-THM-001 W3 G13: loading overlay (wrapped by LoadingManager).
                _refresh_attr('loading_manager')
                # SPEC-THM-001 W3 G18/G19: HTML controllers re-render content with live
                # theme colors (their HTML is only rebuilt on chart/mode/varga change).
                _refresh_attr('shame_controller')
                _refresh_attr('tajika_yogas_controller')
                # Exchange/Final-Dispositor panel is a real Qt widget now; it no
                # longer restyles via a QTextBrowser stylesheet, so it MUST be told
                # to re-render its cards on theme change (hardening H2).
                _refresh_attr('interchange_controller', 'refresh_theme')
                # Nabhasa Yogas panel: same H2 contract, self-themes via refresh_theme().
                _refresh_attr('nabhasa_controller', 'refresh_theme')
                # Retinue tables (Hora/Trimsamsa) + house graph + planetary condition use
                # is_light_theme(); re-render cell bg/fg via their _on_theme_changed().
                _refresh_attr('dignities_controller', '_on_theme_changed')
                _refresh_attr('hora_controller', '_on_theme_changed')
                _refresh_attr('trimsamsa_controller', '_on_theme_changed')
                _refresh_attr('house_graph_controller', '_on_theme_changed')
                _refresh_attr('planetary_condition_controller', '_on_theme_changed')
                _refresh_attr('karakas_controller', '_refresh')

                # Auto-select the theme-locked chart background (td-iqjb.8 Wave H:
                # via the shared helper -- same stone the boot path and every
                # embedded chart-view host now use, so they cannot drift). The
                # stylesheet was applied above (:5193) so is_light_theme() reads
                # the NEW theme here.
                from ui.qt_theme import themed_chart_background
                self._on_background_changed(themed_chart_background())

                # SPEC-THM-001 E3: REMOVED redundant self.update() + self.repaint().
                # Each setStyleSheet() above already queues a Qt repaint via the
                # dirty-region system. ChartGUI has no paintEvent override,
                # so the explicit full-window repaint was duplicating work.
                theme_name = theme_file.replace('.xml', '').replace('_', ' ').title()
                if _theme_failures:
                    # SPEC-THM-001 (td-iqjb Wave A): surface which surfaces failed to
                    # refresh instead of silently aborting the rest of the fan-out.
                    self.statusBar().showMessage(
                        f"Theme applied: {theme_name} "
                        f"({len(_theme_failures)} surface(s) failed - see console)", 6000)
                else:
                    self.statusBar().showMessage(f"Theme applied: {theme_name}")
            except Exception as e:
                self.statusBar().showMessage(f"Theme error: {e}")
                print(f"Error applying theme: {e}")
            finally:
                QApplication.restoreOverrideCursor()
                self.loading_manager.finish()
        else:
            self.statusBar().showMessage("qt-material not installed - theme change unavailable")

    def _on_font_sizes_changed(self):
        """Refresh all panels after a per-area font size change (SPEC-FONT-001).

        Per-area font sizes feed the same stylesheets that the global scale
        refresh regenerates (get_list_style, table styles, dasha buttons, etc.),
        so we reuse that refresh path to apply the new sizes live rather than
        adding per-panel refresh hooks.
        """
        from PySide6.QtCore import QTimer
        from ui.qt_theme import get_scale_factor
        import traceback

        def _run_font_refresh():
            # SPEC-FONT-001: a per-area font-size change must re-render every
            # persistent surface whose HTML/painted output embeds a scaled_area_*
            # value read at render time. This mirrors the surface set that
            # _on_theme_changed() refreshes. Each surface is refreshed in
            # isolation (via _safe) so one failure cannot abort the rest — the
            # controllers and house graph must still update even if an earlier
            # view raises.
            failures = []

            def _safe(label, fn):
                try:
                    fn()
                except Exception:
                    failures.append(label)
                    traceback.print_exc()

            # Tab/menu bars, panel stylesheets (incl. dasha lists and info-panel
            # styles) and the sidebar memory list.
            _safe("scale_refresh",
                  lambda: self._apply_scale_refresh(get_scale_factor()))
            _safe("relayout", lambda: relayout_info_panels(self))

            # All surfaces whose painted or HTML output embeds a scaled_area_*
            # value: sidebar columns, chart title, chart views, side panels, HTML
            # controllers and the house graph. Shared with _on_scale_changed so a
            # global Display-Scale change redraws them too (SPEC-FONT-001 M1).
            self._refresh_scaled_surfaces(_safe)

            if failures:
                self.statusBar().showMessage(
                    f"Font sizes updated ({len(failures)} surface(s) failed - "
                    f"see console)", 5000)
            else:
                self.statusBar().showMessage("Font sizes updated", 3000)

        # Defer to next event loop tick to avoid re-entrant layout. Wrap the
        # deferred body (not the handler, which only schedules) in the loading
        # overlay — the surface refresh blocks ~8.8 s on a loaded chart
        # (td-5qkks measurement).
        def _run_font_refresh_scoped():
            with loading_scope(self, "Applying font sizes..."):
                _run_font_refresh()
        QTimer.singleShot(0, _run_font_refresh_scoped)

    def _refresh_scaled_surfaces(self, _safe):
        """Re-render every persistent surface whose painted/HTML output embeds a
        scaled_area_* value read at render time (SPEC-FONT-001).

        Shared by _on_font_sizes_changed (a per-area base size changed) and
        _on_scale_changed (the global Display Scale changed). Both change the
        effective size returned by scaled_area_px/size/font, so both must redraw
        these surfaces; otherwise chart-view labels, HTML controllers and the
        house graph go stale. The Display-Scale slider regressed in exactly this
        way once Wave 1 made the chart labels scaled_area_* (they used to be
        hardcoded, and so were scale-independent).

        Each surface is refreshed in isolation via the caller's _safe() so one
        failure cannot abort the rest. Mirrors the set _on_theme_changed() covers.
        """
        # Sidebar button columns embed scaled_area_px('sidebar'/'buttons') and are
        # not covered by _refresh_panel_styles(); refresh them explicitly.
        if hasattr(self, 'varga_buttons'):
            def _varga():
                from apps.panels.varga_column import refresh_varga_theme
                refresh_varga_theme(self)
            _safe("varga", _varga)
        if hasattr(self, 'sign_selector_buttons'):
            def _sign_selector():
                from apps.panels.sign_selector_column import refresh_sign_selector_theme
                refresh_sign_selector_theme(self)
            _safe("sign_selector", _sign_selector)

        # Chart title bar. refresh_chart_title_theme() re-applies the full-size
        # styles and stomps compact mode, so re-assert compact afterwards via the
        # force-reapply idiom (set_chart_title_compact early-returns when the flag
        # already matches).
        if hasattr(self, 'chart_title_widget'):
            def _title():
                from apps.widgets.chart_title_widget import refresh_chart_title_theme
                refresh_chart_title_theme(self)
                if getattr(self, '_title_is_compact', False):
                    from apps.widgets.chart_title_widget import set_chart_title_compact
                    self._title_is_compact = False  # force past early-return
                    set_chart_title_compact(self, True)
            _safe("chart_title", _title)

        # Action bar v2 (chart_title_widget when ui.action_bar_v2): its text and
        # every metric derive from BarMetrics(fs), and fs now folds in the
        # action_buttons font-area ratio (td-l0jfa). The scale path reboxes it via
        # _apply_scale_refresh; the font-size path reaches only here, so rebox it
        # too. refresh_scale rebuilds from the CURRENT scale AND the new area
        # ratio and early-returns when nothing changed, so this is a no-op unless
        # the action_buttons size actually moved.
        bar = getattr(self, 'chart_title_widget', None)
        if bar is not None and hasattr(bar, 'refresh_scale'):
            from ui.qt_theme import get_scale_factor as _gsf
            _safe("action_bar_scale", lambda: bar.refresh_scale(_gsf()))

        # Chart views: refresh_theme() fully redraws the scene (wheel and
        # north-indian via draw_*, body graph via update_from_chart), so label
        # items are recreated with the new scaled_area_font/size. Each view
        # self-guards on whether a chart is loaded.
        for _view_name in ('chart_view', 'wheel_view',
                           'north_indian_view', 'body_graph_view',
                           'cards_of_truth_view', 'human_design_view'):
            view = getattr(self, _view_name, None)
            if view is not None and hasattr(view, 'refresh_theme'):
                _safe(_view_name, view.refresh_theme)

        # Side panels, the settings tab, and the loading overlay each own a
        # refresh_theme() that regenerates scaled_area_* styling.
        for _panel_name in ('find_chart_panel', 'birth_finder_panel',
                           'edit_chart_panel', 'lunar_new_year_panel',
                           'eclipse_panel', 'transit_panel',
                           'exploration_panel', 'ai_reading_panel',
                           'cliwoc_map_panel', 'settings_tab',
                           # B5 (SPEC-FONT-001 WIRE): these three own scaled_area_*
                           # chrome (and painted wheel/scene labels) but were absent
                           # from the font-size fan-out, so a per-area change left
                           # them stale until the next theme switch. refresh_theme()
                           # re-reads scaled_area_* / redraws the scene. getattr-guarded.
                           'nakshatra_panel', 'antikythera_panel',
                           'solar_return_page',
                           # B7-a WIRE: time_adjust_widget owns scaled_area_* chrome
                           # (buttons + panel_titles readout) and a conforming
                           # refresh_theme, but sat only in the THEME fan-out — a
                           # per-area font change did not reach it. None-until-opened,
                           # getattr-guarded here.
                           'time_adjust_widget',
                           'loading_manager'):
            panel = getattr(self, _panel_name, None)
            if panel is not None and hasattr(panel, 'refresh_theme'):
                _safe(_panel_name, panel.refresh_theme)

        # Font-size-dependent HTML controllers. _refresh() rebuilds each
        # controller's HTML so it re-reads scaled_area_px/size. Deferred
        # controllers (shame/tajika_yogas/planetary_condition/interchange) may not
        # exist until their panel is first shown, hence the getattr guard. The
        # eight controllers that use no scaled_area_* helper (avastha, strength,
        # elements, modality, aspects, dignities, tajika_matrix,
        # tajika_relationships) are intentionally omitted; their text is styled by
        # the widget stylesheets already regenerated by _apply_scale_refresh().
        for _ctrl_name in ('shame_controller', 'tajika_yogas_controller',
                          'hora_controller', 'trimsamsa_controller',
                          'planetary_condition_controller',
                          'karakas_controller', 'interchange_controller',
                          'nabhasa_controller'):
            ctrl = getattr(self, _ctrl_name, None)
            if ctrl is not None and hasattr(ctrl, '_refresh'):
                _safe(_ctrl_name, ctrl._refresh)

        # The house graph has no controller instance; it is painted by
        # _HouseBarWidget (gui.house_graph_bars). Repaint it so its paint path
        # re-reads scaled_area_px/size (matches the info_panels path).
        bars = getattr(self, 'house_graph_bars', None)
        if bars is not None:
            def _repaint_bars():
                bars.updateGeometry()
                bars.update()
            _safe("house_graph_bars", _repaint_bars)

        # Non-modal transient dialogs that embed scaled_area_* chrome and can sit
        # open across a font change (SPEC-FONT-001 B6c). They hold NO ChartGUI
        # attribute (Rule 4b: no new blackboard state) — the QObject parent-child
        # tree IS the registry. Enumerate live instances, refresh only the VISIBLE
        # ones (a closed-but-undeleted dialog is skipped), each isolated via _safe.
        from apps.widgets.planet_placements_dialog import PlanetPlacementsDialog
        for _ppd in self.findChildren(PlanetPlacementsDialog):
            if _ppd.isVisible():
                _safe("planet_placements_dialog", _ppd._refresh_fonts)
        # B7-a WIRE: info_panel_dialog is the same class of parented non-modal
        # transient (parent=gui, no ChartGUI handle). Its refresh_theme rebuilds the
        # UI (re-reads every scaled_area_* site), so enumerate + refresh visible ones.
        from apps.widgets.info_panel_dialog import InfoPanelDialog
        for _ipd in self.findChildren(InfoPanelDialog):
            if _ipd.isVisible():
                _safe("info_panel_dialog", _ipd.refresh_theme)
        # Every other non-modal pop-up registers its font styles with
        # ui.popup_fonts.live_style (SPEC-FONT-001 §3.2); re-apply the visible ones.
        from ui.popup_fonts import refresh_live_popups
        _safe("live_popups", refresh_live_popups)

        # B7-a4 WIRE: the status-bar ORDER pill paints its text with the
        # 'status' font area (scaled_tier_size). It was already refreshed by the
        # THEME fan-out but not this one, so a per-area font change left it
        # frozen. refresh_theme() repaints AND updateGeometry()s so it grows to
        # fit. (The fullscreen glyph beside it is a symbol icon, not text — it
        # keeps its scale-only font and is intentionally NOT wired: SKIP, same
        # principle as the profile 👤 button.)
        _order_pill = getattr(self, 'status_order_button', None)
        if _order_pill is not None and hasattr(_order_pill, 'refresh_theme'):
            _safe("status_order_button", _order_pill.refresh_theme)

    def _on_saturation_changed(self, pct: int):
        """Handle a global Color-Saturation change from settings (SPEC-SAT-001 WI-6).

        Thin per Rule 4 — the real work is: (1) set the module saturation so
        desat_hex/desat_image/desaturated_theme_path all pick it up; (2) clear
        every Layer-3/4 icon cache so stale pixmaps are not served (the theme
        fan-out's refresh_theme() redraws but reads caches first, so clearing is
        mandatory); (3) re-run the existing theme fan-out which re-applies the
        now-desaturated qt-material stylesheet AND refreshes every themed surface.

        Persistence is already done by the settings tab's Apply handler; we set
        it again here defensively (idempotent) so a programmatic caller is safe.
        Cache surfaces are enumerated from CODE (findChildren) not a static list —
        the font-refresh migration proved plan-time enumeration goes stale.
        """
        from ui import qt_theme
        qt_theme.set_ui_saturation(pct)
        try:
            from managers.settings_manager import get_settings
            get_settings().set("display.color_saturation", int(pct))
        except Exception:
            pass

        # Clear every icon/image cache in the live widget tree.
        from PySide6.QtWidgets import QWidget
        for w in self.findChildren(QWidget):
            fn = getattr(w, 'clear_icon_cache', None)
            if callable(fn):
                try:
                    fn()
                except Exception:
                    pass
            # House-graph bars keep their _icon_cache on the widget while the
            # clear method lives on the controller — catch the raw dict too.
            cache = getattr(w, '_icon_cache', None)
            if isinstance(cache, dict):
                cache.clear()

        # Re-apply the (now desaturated) stylesheet + fan out to every surface.
        # The fan-out already reaches every SouthIndianVectorView: the MAIN chart
        # is self.chart_view (a create_south_indian_view() host that fans
        # refresh_theme into its SIV), covered by _refresh_attr('chart_view'); the
        # panel-hosted SIVs (eclipse/transit/solar/nakshatra mini-charts) are
        # covered by their parent panels' refresh. An extra findChildren(SIV)
        # sweep here just re-refreshed every one a second (and third) time — a
        # multi-second freeze on Apply. Caches were cleared above, so the single
        # fan-out redraws each surface at the new saturation exactly once.
        try:
            current_theme = self._load_theme_preference()
        except Exception:
            current_theme = "dark_blue.xml"
        self._on_theme_changed(current_theme, loading_message=f"Applying saturation {int(pct)}%...")

    def _on_scale_changed(self, factor: float):
        """Handle a global Display-Scale change from settings (SPEC-FONT-001 M1).

        The scale factor multiplies every scaled_area_* value, so this must redraw
        the same surface set as _on_font_sizes_changed, not just the stylesheet
        zones in _apply_scale_refresh(). Chart-view labels, HTML controllers and
        the house graph became scale-dependent when Wave 1 replaced their
        hardcoded fonts with scaled_area_*; without this fan-out they would stay
        at the old size until the next unrelated redraw.
        """
        from PySide6.QtCore import QTimer
        import traceback

        def _run_scale_refresh():
            failures = []

            def _safe(label, fn):
                try:
                    fn()
                except Exception:
                    failures.append(label)
                    traceback.print_exc()

            # _apply_scale_refresh() regenerates the scaled_px/size stylesheet
            # zones (tab/menu bars, panel styles, memory panel) and shows the
            # "Font scale: N%" status message on success.
            _safe("scale_refresh", lambda: self._apply_scale_refresh(factor))
            _safe("relayout", lambda: relayout_info_panels(self))

            # Plus every scaled_area_* surface — the M1 regression fix.
            self._refresh_scaled_surfaces(_safe)

            if failures:
                self.statusBar().showMessage(
                    f"Font scale updated ({len(failures)} surface(s) failed - "
                    f"see console)", 5000)

        # Defer refresh to next event loop tick to avoid re-entrant layout. Wrap
        # the deferred body (not the handler, which only schedules) in the loading
        # overlay — the surface refresh blocks ~8.4 s on a loaded chart
        # (td-5qkks measurement).
        def _run_scale_refresh_scoped():
            with loading_scope(self, "Applying display scale..."):
                _run_scale_refresh()
        QTimer.singleShot(0, _run_scale_refresh_scoped)

    def _apply_scale_refresh(self, factor: float):
        """Apply font scale refresh to ALL UI elements.

        Re-generates all stylesheets that use scaled_px()/scaled_size().
        Called by Apply button click and monitor switch.
        """
        from ui.qt_theme import get_tab_bar_style, apply_menu_bar_style
        from ui.input_font_qss import apply_global_input_font_qss
        pct = int(factor * 100)
        # Zone 1: Tab bar + menu bar
        self.tab_widget.setStyleSheet(get_tab_bar_style())
        apply_menu_bar_style(self.menuBar())
        # G9d: the effective px of the combo/input font just changed — re-append
        # the global input-font rule so the new size takes effect live.
        apply_global_input_font_qss(QApplication.instance())
        # Zones 2-9: All panel styles (dasha buttons, info lists, tables, etc.)
        self._refresh_panel_styles()
        bar = getattr(self, 'chart_title_widget', None)
        if hasattr(bar, 'refresh_scale'):
            bar.refresh_scale(factor)
        # Zone 2: Memory panel
        if hasattr(self, 'memory_panel') and hasattr(self.memory_panel, 'refresh_theme'):
            self.memory_panel.refresh_theme()
        self.statusBar().showMessage(f"Font scale: {pct}%", 3000)

    # ===== CLUSTER: MONITOR / BACKGROUND / DISPLAY =====
    def moveEvent(self, event):
        """Detect when window moves to a different monitor — debounced."""
        super().moveEvent(event)
        self._move_timer.start()

    def _check_monitor_change(self):
        """Check if the window moved to a different monitor and suggest scale."""
        try:
            # Use the center of the window frame to detect which screen it's on
            center = self.frameGeometry().center()
            screen = QApplication.screenAt(center)
            if screen is None:
                # Fallback: use the screen the window is mostly on
                screen = self.screen()
            if screen is None:
                return
            screen_name = screen.name()
            if self._current_screen_name is None:
                # First check — just store, don't trigger
                self._current_screen_name = screen_name
                return
            if screen_name != self._current_screen_name:
                self._current_screen_name = screen_name
                from ui.qt_theme import detect_optimal_scale, get_scale_factor
                optimal = detect_optimal_scale(screen)
                current = get_scale_factor()
                dpi = screen.logicalDotsPerInch()
                size = screen.size()
                # Only suggest if meaningfully different (>5% difference)
                if abs(optimal - current) > 0.05:
                    self.statusBar().showMessage(
                        f"Monitor: {size.width()}x{size.height()} ({dpi:.0f} DPI) — "
                        f"suggested scale: {int(optimal * 100)}% (current: {int(current * 100)}%)",
                        5000
                    )
                else:
                    self.statusBar().showMessage(
                        f"Monitor: {size.width()}x{size.height()} ({dpi:.0f} DPI)", 3000
                    )
                # Update DisplayScaleTab DPI info if settings tab exists. Core
                # names it display_scale_tab; Pro reuses the same Core widget as
                # display_scale_section.
                if hasattr(self, 'settings_tab'):
                    scale_tab = (
                        getattr(self.settings_tab, 'display_scale_tab', None)
                        or getattr(self.settings_tab, 'display_scale_section', None)
                    )
                    if scale_tab is not None and hasattr(scale_tab, '_update_dpi_info'):
                        scale_tab._update_dpi_info()
        except Exception:
            pass

    def _on_background_changed(self, bg_identifier: str):
        """Handle background change from settings tab - update chart view immediately"""
        self.chart_view.set_background(bg_identifier)
        self.chart_view.draw_full_chart()
        # Extract category and number for status message
        parts = bg_identifier.split('_')
        if len(parts) >= 2:
            category = parts[0].capitalize()
            number = parts[1]
            display_name = f"{category} {number}"
        else:
            display_name = bg_identifier
        self.statusBar().showMessage(f"✅ Background changed: {display_name}")

    def _on_chart_display_changed(self):
        """Handle chart display settings change from settings panel Apply button."""
        from managers.settings_manager import get_settings
        s = get_settings()

        # 1. Chart view type — SPEC-COT-001 INV-14: one shared mapping.
        view_type = s.get("chart.view_type", "south_indian")
        from state.chart_state import VIEW_STACK_INDEX
        target_index = VIEW_STACK_INDEX.get(view_type, 0)
        if self.chart_stack.currentIndex() != target_index:
            self._switch_to_chart_index(target_index)

        # 1b. South Indian theme (classic/vector) — SPEC-SIC-002 D-13:
        # explicit activation on EVERY live host (main view, dual-chart,
        # Pro panels) via the live-host registry — a style-only change
        # triggers no panel retheme path (Phase-3 review finding 1).
        sync_all_south_indian_hosts()

        # 1c. Embedded Wheel / North-Indian hosts in composed panels (dual chart,
        # Compatibility comparison, Exploration) read display.sign_display at draw
        # but otherwise only redraw on showEvent — broadcast a reload so a live
        # flip flips them too (td-iaqm.5 CP7d). The main-stack wheel/NI are
        # covered by _refresh_chart_display below.
        from apps.widgets.chart_host_registry import sync_all_chart_hosts
        sync_all_chart_hosts()

        # 2. Outer planets
        show_outer = s.get("chart.show_outer_planets", True)
        if hasattr(self, 'outer_planets_action'):
            if self.outer_planets_action.isChecked() != show_outer:
                self.outer_planets_action.setChecked(show_outer)
                self._toggle_outer_planets()

        # 2b. Planet names
        show_names = s.get("chart.show_planet_names", False)
        if hasattr(self, 'planet_names_action'):
            if self.planet_names_action.isChecked() != show_names:
                self.planet_names_action.setChecked(show_names)
                self._toggle_planet_names()

        # 3. Cusp glow
        cusp_mode = s.get("chart.cusp_glow_mode", 0)
        current_widget = self.chart_stack.currentWidget()
        if hasattr(current_widget, 'set_cusp_glow_mode'):
            current_widget.set_cusp_glow_mode(cusp_mode)
            current_widget.ensure_visible()

        # 3b. Wheel house display (SPEC-WHD-001). Apply to the wheel directly
        # (per spec 6.5): currentWidget() at startup is the south-indian view,
        # which has no set_house_display_mode, so the setting would be dropped.
        whd = s.get("chart.wheel_house_display", "sign_based")
        if hasattr(self, 'wheel_view') and hasattr(self.wheel_view, 'set_house_display_mode'):
            self.wheel_view.set_house_display_mode(whd)

        # Shared intent is applied to Wheel and all full-size vector hosts.
        from apps.widgets.retinue_display import apply_retinue, broadcast_south_indian
        flags = dict(rings=s.get('chart.show_retinue_rings', False),
                     ruler=s.get('chart.show_trimsamsha_degrees', False))
        apply_retinue(self.wheel_view, **flags)
        broadcast_south_indian(**flags)
        self.retinue_rings_action.setChecked(flags['rings'])
        self.trimsamsha_degrees_action.setChecked(flags['ruler'])

        # 6. Element pies
        show_pies = s.get("chart.show_element_pies", True)
        if hasattr(current_widget, 'show_element_pies'):
            current_widget.show_element_pies = show_pies

        # 7. Panel default sub-tabs (Karakas / Strength / Aspects) applied live.
        # Reuse the startup applier so Settings Apply and boot use identical logic
        # (handles the Aspects mode relabel and the Yogas idx 5 raw switch, pm-004).
        from managers.startup_state_manager import _apply_panel_tabs
        _apply_panel_tabs(self, s)

        # Antikythera FT map rasterises planet icons into its scene, so a display
        # Apply that changes display.planet_icon_set (or the SVG family / colours /
        # variations) needs an explicit icon rebuild — a plain repaint keeps the
        # stale pixmaps (td-jxxp DeepSeek review; parity with the saturation path).
        ak = getattr(self, 'antikythera_panel', None)
        mv = getattr(ak, 'map_view', None) if ak is not None else None
        if mv is not None and hasattr(mv, 'refresh_icons'):
            mv.refresh_icons()

        self._refresh_chart_display()
        self.statusBar().showMessage("Chart display settings applied")

    def apply_chart_display_settings(self):
        """The single post-write tail for a Chart Display settings change, whether
        it came from the Settings Apply/Reset buttons (via chart_display_changed)
        or the Pro remote/CLI path (set_setting / set_rashi_aspect_system). Both
        call THIS method, so the two are indistinguishable and cannot drift
        (td-iaqm.2.1): refresh the chart views, then the icon views (repaints every
        QGraphicsView and reloads any open PlanetInfoDialog image — the popup half
        _on_chart_display_changed does not cover on its own).

        Wrapped in the loading overlay (~1.2 s measured, td-5qkks); nested with the
        remote/CLI path which also enters here (the ref-counted manager keeps a
        single overlay)."""
        with loading_scope(self, "Applying chart display..."):
            self._on_chart_display_changed()
            from apps.widgets.planet_icon_style import refresh_icon_views
            refresh_icon_views()

    def _on_wheel_display_changed(self):
        """Handle Wheel chart display settings change - reload wheel view with new settings"""
        if hasattr(self, 'wheel_view') and self.wheel_view:
            self.wheel_view.reload_display_settings()
            self.statusBar().showMessage("✅ Wheel display settings updated")

    def _on_north_indian_display_changed(self):
        """Handle North Indian chart display settings change - reload view with new settings"""
        if hasattr(self, 'north_indian_view') and self.north_indian_view:
            self.north_indian_view.reload_display_settings()
            self.statusBar().showMessage("✅ North Indian display settings updated")

    def _update_chart_display_preview(self):
        """Update Chart Display tab preview with current chart data and background."""
        if hasattr(self, 'settings_tab') and hasattr(self.settings_tab, 'chart_display_tab'):
            chart = self.state.active_chart
            tab = self.settings_tab.chart_display_tab
            if chart and hasattr(tab, 'set_chart'):
                current_bg = None
                if hasattr(self, 'chart_view'):
                    current_bg = self.chart_view.get_background()
                tab.set_chart(chart, background=current_bg)

    def _update_wheel_display_preview(self):
        """Update Wheel Display tab preview with current chart data."""
        if hasattr(self, 'settings_tab') and hasattr(self.settings_tab, 'wheel_display_tab'):
            chart = self.state.active_chart
            if chart:
                self.settings_tab.wheel_display_tab.set_chart(chart)

    def _update_north_indian_display_preview(self):
        """Update North Indian Display tab preview with current chart data."""
        if hasattr(self, 'settings_tab') and hasattr(self.settings_tab, 'north_indian_display_tab'):
            chart = self.state.active_chart
            if chart:
                self.settings_tab.north_indian_display_tab.set_chart(chart)

    # ===== CLUSTER: PANEL STYLES REFRESH =====
    def _refresh_panel_styles(self):
        """Refresh panel header styles to match new theme colors and scaled font sizes."""
        # Guard: skip if core panels not yet initialized (called during startup before layout is built)
        if not hasattr(self, 'vedanga_panel') and not hasattr(self, 'karakas_list'):
            return
        # w3-2 (SPEC-DSH-002 D-W3-1): the two dasha panels self-restyle through the
        # ThemedStyleMixin replay. This ONE call replaces the former dasha block of
        # this method (lists, level buttons, panel bg, nav/arrows/cycle label,
        # combos, column labels, swap icon). It runs as a unit here, under whatever
        # _safe wrapper the caller already provides (per-widget try/except inside).
        self.dasha_manager.refresh_panel_styles()
        # SPEC-THM-001 E5: get_theme_colors is module-level.
        theme = get_theme_colors()

        # Header style with new theme colors
        header_style = f"""
            QWidget {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {theme["primary_light"]},
                    stop:1 {theme["primary"]});
                border-radius: 6px;
            }}
        """

        # Apply directly to each header widget (widget-level styles override app-level)
        header_names = ['karakas_header', 'strength_header', 'aspects_header']  # dasha headers self-restyle (w3-2)
        for header_name in header_names:
            if hasattr(self, header_name):
                header = getattr(self, header_name)
                header.setStyleSheet(header_style)

        # (dasha list styles handled by dasha_manager.refresh_panel_styles above)

        # Refresh info panel list styles
        from ui.qt_theme import FONT_MONO
        info_list_style = f"""
            QListWidget {{
                background-color: {theme["secondary_dark"]};
                border: none;
                font-size: {scaled_area_px('tables')}px;
            }}
            QListWidget::item {{
                padding: 3px;
                border-bottom: 1px solid {theme["secondary_light"]};
            }}
            QListWidget::item:selected {{
                background-color: {theme["primary"]};
                color: {theme["primary_text"]};
            }}
        """
        if hasattr(self, 'karakas_list'):
            self.karakas_list.setStyleSheet(info_list_style)
            self.karakas_list.doItemsLayout()
        if hasattr(self, 'strength_list'):
            strength_list_style = info_list_style + f"""
                QListWidget {{
                    font-family: "{FONT_MONO}", monospace;
                }}
                QScrollBar:vertical {{
                    width: 0px;
                }}
            """
            self.strength_list.setStyleSheet(strength_list_style)
            self.strength_list.doItemsLayout()

        # (dasha level-button styles handled by dasha_manager.refresh_panel_styles above)

        # Refresh panel CONTAINER backgrounds (critical for theme switching)
        # Without this, containers keep old theme colors when switching dark<->light
        from ui.qt_theme import get_panel_style, get_frame_style
        panel_bg = get_panel_style()
        frame_bg = get_frame_style()

        # dasha panels self-style their container (w3-2); right_panels stays here.
        for attr in ('right_panels',):
            panel = getattr(self, attr, None)
            if panel:
                panel.setStyleSheet(panel_bg)

        # Refresh info panel FRAMES (karakas, strength, aspects sections)
        for attr in ('karakas_frame', 'strength_frame', 'aspects_frame'):
            frame = getattr(self, attr, None)
            if frame:
                frame.setStyleSheet(frame_bg)

        # w3-2 (SPEC-DSH-002): the dasha nav bar backgrounds, arrows, cycle
        # labels, lord combos and the Karaka/Cusp/House column-label fonts are
        # all replayed by dasha_manager.refresh_panel_styles() at the top of this
        # method (each panel's ThemedStyleMixin re-reads the live theme + fonts).

        # Refresh table backgrounds (Karakas, Strength, Elements, etc.)
        table_style = f"""
            QTableWidget {{
                background-color: {theme["secondary_dark"]};
                gridline-color: {theme["secondary_light"]};
                color: {theme["secondary_text"]};
                border: none;
                font-size: {scaled_area_px('tables')}px;
            }}
            QTableWidget::item {{
                background-color: transparent;
            }}
            QTableWidget::item:selected {{
                background-color: {theme["primary"]};
                color: {theme["primary_text"]};
            }}
            QHeaderView::section {{
                background-color: {theme["secondary"]};
                color: {theme["secondary_text"]};
                border: none;
                padding: 4px;
                font-size: {scaled_area_px('table_headers')}px;
                font-weight: bold;
            }}
        """
        for attr in ('karakas_table', 'strength_table', 'elements_table',
                      'modality_table', 'aspects_table', 'avastha_table',
                      'tajika_matrix_table', 'tajika_rel_table',
                      'hora_table', 'trimsamsa_table'):
            tbl = getattr(self, attr, None)
            if tbl:
                tbl.setStyleSheet(table_style)
        # Avastha table: its own compact style (SPEC-AVA-001 rev3) — the SAME
        # helper the construction site uses, so live refresh cannot drift.
        if getattr(self, 'avastha_table', None):
            from apps.panels.info_panels import avastha_compact_table_style
            self.avastha_table.setStyleSheet(avastha_compact_table_style())
                # NO resizeRowsToContents() here (td-v21r): it set EXPLICIT
                # content-based row heights that override the construction
                # setDefaultSectionSize AND survive relayout_info_panels, so a
                # live THEME switch inflated every info-table row (boot-parity
                # break caught by test/theme_audit.py). It predates (2026-04)
                # the proper re-layout chain relayout_info_panels (SPEC-RESP-001,
                # 2026-06), which both font/scale paths already call right
                # after this method.

        # Swap/lang icon buttons on the Karakas + Strength headers (td-v21r):
        # construction-styled with secondary_dark bg / primary border and never
        # replayed, so they kept the previous theme's colors after a live
        # switch. Same expression as their construction sites; the icon is
        # re-tinted with the LIVE primary_text (the stored _make_swap_icon
        # closure's default color froze the construction theme, so pass it).
        _swap_btn_style = f"""
            QPushButton {{ background: {theme["secondary_dark"]}; border: 1px solid {theme["primary"]};
                border-radius: {scaled_px(4)}px; padding: 0px; }}
            QPushButton:hover {{ background: {theme["primary"]}; border-color: {theme["primary_light"]}; }}
        """
        _make_swap_icon = getattr(self, '_make_swap_icon', None)
        for attr in ('karakas_swap_btn', 'strength_lang_btn'):
            btn = getattr(self, attr, None)
            if btn:
                btn.setStyleSheet(_swap_btn_style)
                if _make_swap_icon:
                    try:
                        btn.setIcon(_make_swap_icon(theme["primary_text"]))
                    except Exception:
                        pass

        # Dignities table: omit `color` from QTableWidget so DignityColorDelegate
        # can set per-cell text colors via ForegroundRole (SPEC-THM-001 compliant)
        dignities_tbl = getattr(self, 'dignities_table', None)
        if dignities_tbl:
            dignities_style = f"""
                QTableWidget {{
                    background-color: {theme["secondary_dark"]};
                    gridline-color: {theme["secondary_light"]};
                    border: none;
                    font-size: {scaled_area_px('tables')}px;
                }}
                QTableWidget::item {{
                    background-color: transparent;
                }}
                QTableWidget::item:selected {{
                    background-color: {theme["primary"]};
                }}
                QHeaderView::section {{
                    background-color: {theme["secondary"]};
                    color: {theme["secondary_text"]};
                    border: none;
                    padding: 4px;
                    font-size: {scaled_area_px('table_headers')}px;
                    font-weight: bold;
                }}
            """
            dignities_tbl.setStyleSheet(dignities_style)

        # w3-2 (SPEC-DSH-002): the dasha title buttons and the right-panel swap
        # button restyle through dasha_manager.refresh_panel_styles() above.

        # SPEC-THM-001 E2: REMOVED duplicate varga button styling here.
        # `refresh_varga_theme(self)` (called from _on_theme_changed at the same
        # ceremony) is the single owner. Two divergent styles caused subtle
        # visual mismatches on the checked state; the dedicated function uses
        # a secondary-bg + thick primary-border highlight, which is the design.

        # Refresh info panel header tab buttons (KARAKAS|HORA|TRIMSAMSA, etc.)
        header_tab_style = f"""
            QPushButton {{
                color: {theme['primary_text']}; font-size: {scaled_area_px('panel_titles')}px; font-weight: bold;
                background: transparent; border: none; padding: 4px 8px;
            }}
            QPushButton:hover {{ text-decoration: underline; }}
        """
        header_tab_normal = f"""
            QPushButton {{
                color: {theme['primary_text']}; font-size: {scaled_area_px('panel_titles')}px; font-weight: normal;
                background: transparent; border: none; padding: 4px 8px;
            }}
            QPushButton:hover {{ text-decoration: underline; }}
        """
        for attr in ('karakas_tab_btn', 'hora_tab_btn', 'trimsamsa_tab_btn',
                     'strength_tab_btn', 'elements_tab_btn', 'modality_tab_btn',
                     'aspects_tab_btn', 'avastha_tab_btn', 'shame_tab_btn'):
            btn = getattr(self, attr, None)
            if btn:
                # Keep the bold state for currently active tab
                if btn.font().bold():
                    btn.setStyleSheet(header_tab_style)
                else:
                    btn.setStyleSheet(header_tab_normal)

        # SPEC-BAR-001 M3 W8 (Dm3-1): the bar-button restyle block that lived
        # here is deleted whole. Two of its three attribute names (south_btn,
        # open_kala_btn) were dead, and the surviving chart_info_btn write was
        # a sizeHint corruption under the v2 custom paint (INV-4).

        # SPEC-THM-001 W2 G06: rebuild stored tab style strings on theme change.
        # info_panels.py caches `gui._tab_active_style`, `gui._karakas_tab_active_style`,
        # etc. at construction time. Click handlers re-apply these stale strings,
        # reverting the buttons after a refresh. Rebuild them here using live theme,
        # then re-apply to the currently active tabs (pre-mortem P-007).
        strength_tab_active = f"""
            QPushButton {{
                color: {theme['primary_text']}; font-size: {scaled_area_px('panel_titles')}px; font-weight: bold;
                background: transparent; border: none;
                border-bottom: 2px solid {theme['primary_text']}; padding: 2px 8px;
            }}
        """
        strength_tab_inactive = f"""
            QPushButton {{
                color: {theme['primary_text']}; font-size: {scaled_area_px('panel_titles')}px; font-weight: normal;
                background: transparent; border: none;
                border-bottom: 2px solid transparent; padding: 2px 8px; opacity: 0.7;
            }}
            QPushButton:hover {{ border-bottom: 2px solid rgba(255,255,255,0.5); }}
        """
        self._tab_active_style = strength_tab_active
        self._tab_inactive_style = strength_tab_inactive
        self._karakas_tab_active_style = strength_tab_active
        self._karakas_tab_inactive_style = strength_tab_inactive
        # Re-apply to the currently-active tab in each group so the visible state
        # picks up the new colors immediately.
        strength_names = ('strength_tab_btn', 'elements_tab_btn', 'modality_tab_btn', 'dignities_tab_btn')
        karakas_names = ('karakas_tab_btn', 'hora_tab_btn', 'trimsamsa_tab_btn', 'graph_tab_btn')
        aspects_index = getattr(self.aspects_stack, 'currentIndex', lambda: 0)()
        aspects_active = {0: 0, 1: 1, 2: 2, 6: 3, 7: 4}.get(aspects_index, -1)
        aspects_names = ('aspects_tab_btn', 'avastha_tab_btn', 'shame_tab_btn',
                         'exchange_tab_btn', 'nabhasa_tab_btn')
        groups = (
            (getattr(self.strength_elements_stack, 'currentIndex', lambda: 0)(), strength_names),
            (getattr(self.karakas_stack, 'currentIndex', lambda: 0)(), karakas_names),
            (aspects_active, aspects_names),
        )
        for active_index, group in groups:
            group_btns = [getattr(self, n, None) for n in group]
            group_btns = [b for b in group_btns if b is not None]
            for index, button in enumerate(group_btns):
                button.setStyleSheet(strength_tab_active if index == active_index
                                     else strength_tab_inactive)

        # SPEC-THM-001 W2 G21/G22: strength_lang_btn + aspects_mode_btn small toggle buttons.
        toggle_btn_style = f"""
            QPushButton {{
                background-color: {theme["secondary_dark"]};
                color: {theme["secondary_text"]};
                border-radius: 12px;
                font-size: {scaled_area_px('status')}px;
                font-weight: bold;
                border: 2px solid {theme["secondary_text"]};
            }}
            QPushButton:hover {{
                background-color: {theme["secondary"]};
            }}
        """
        for attr in ('strength_lang_btn', 'aspects_mode_btn'):
            btn = getattr(self, attr, None)
            if btn:
                btn.setStyleSheet(toggle_btn_style)

        # Refresh swap icon color for light/dark theme (info-panel buttons).
        # w3-2: the right dasha panel's swap icon is re-tinted by the panel's own
        # refresh_theme (through its swap_icon_getter), no longer here.
        make_icon = getattr(self, '_make_swap_icon', None)
        if make_icon:
            themed_icon = make_icon(theme["primary_text"])
            for attr in ('strength_lang_btn', 'aspects_mode_btn'):
                btn = getattr(self, attr, None)
                if btn:
                    btn.setIcon(themed_icon)

        # SPEC-THM-001 W2 G23: graph_tab_btn uses the karakas tab style group.
        # Already handled by the karakas group loop above; nothing extra needed.

        # SPEC-THM-001 W2 G16/G17: shame_display + tajika_placeholder QTextEdits
        # need explicit refresh because inline stylesheets override qt-material's
        # global stylesheet (spec §5.3).
        textedit_style = f"""
            QTextEdit {{
                background-color: {theme["secondary_dark"]};
                color: {theme["secondary_text"]};
                border: 1px solid {theme["secondary_light"]};
                font-size: {scaled_area_px('info_text')}px;
                padding: 4px;
            }}
        """
        for attr in ('shame_display', 'tajika_placeholder'):
            te = getattr(self, attr, None)
            if te is not None:
                te.setStyleSheet(textedit_style)
        # exchange_display is now a ParivartanaWidget (real Qt cards), NOT a
        # QTextBrowser: it self-themes via interchange_controller.refresh_theme()
        # in the theme fan-out. Applying a QTextBrowser stylesheet here would
        # clobber the card widget on every theme change (hardening H2).

    # ===== CLUSTER: LIFECYCLE EVENTS =====
    def showEvent(self, event):
        """
        Handle window show event - perform initial chart draw after window is visible.

        This fixes the bug where charts don't display correctly on first load because
        the viewport geometry wasn't established when draw was called during __init__.
        """
        super().showEvent(event)

        # Only do initial draw once, after window is first shown
        if not getattr(self, '_initial_draw_done', False):
            self._initial_draw_done = True

            # td-iopy MED-2 (Codex): lift the construction-phase suppress flags
            # HERE, before the fallible initial-draw calls below. If a draw
            # raised while the lift sat after it, BOTH flags would stay True for
            # the whole runtime — no persist, no broadcast, silently. Lifting
            # first is safe: construction is already over, so a view activation
            # triggered by the draw should broadcast. (Restore re-suppresses
            # persist around its own apply — see startup_state_manager — so it
            # never rewrites what it just read.)
            self._suppress_view_broadcast = False
            self._suppress_view_persist = False

            # Only draw the active chart view (others draw on first switch)
            active_view = self.chart_stack.currentWidget()
            if active_view:
                if hasattr(active_view, 'draw_chart_with_icons'):
                    active_view.draw_chart_with_icons()
                if hasattr(active_view, 'ensure_visible'):
                    active_view.ensure_visible()

            # SPEC-SET-002 Phase 2: single startup-apply pass for persisted UI
            # state (chart view + wheel-only settings + outer planets).
            from managers.startup_state_manager import apply_persisted_ui_state
            from managers.settings_manager import get_settings
            apply_persisted_ui_state(self, get_settings())

    def closeEvent(self, event):
        """
        Handle window close event - save session and geometry before closing.

        This is called automatically when the user closes the window.
        """
        # Save window geometry for next launch
        self._save_window_geometry()

        # td-iopy: flush any debounced chart-view change so a quit inside the
        # debounce window still records the settled view (crash-safety half of
        # the debounce; idempotent no-op when nothing is pending).
        self._flush_view_persist()

        # Persist tab usage counts
        if self._tab_usage_counts:
            from managers.settings_manager import get_settings
            get_settings().set("tab_usage_counts", self._tab_usage_counts)
        if hasattr(self, 'session_manager'):
            self.session_manager.save_session(mark_closed=True)
        # Defensive: join the license-refresh QThread before the window (its
        # parent) is torn down. KeyRefreshWorker overrides run() with a bounded
        # network call and has no event loop, so quit() is a no-op — wait()
        # blocks until run() returns. If the 12h refresh timer happened to fire
        # and a refresh is in flight when the user closes the app, this stops the
        # thread outliving its C++ object ("QThread: Destroyed while thread is
        # still running"). NOTE: this is NOT the SPEC-BAR-001 MAJOR 4 test-suite
        # crash — that leaked thread was pro.ui.settings_tab._SnapshotWorker
        # (the 12h license timer never fires within a test run), joined in
        # test_bar_zodiac_routes.py's fixture teardown.
        _lw = getattr(self, "_license_refresh_worker", None)
        if _lw is not None and _lw.isRunning():
            _lw.wait(5000)
        event.accept()

# Deprecated alias, scheduled for removal in v2.0
SouthIndianChartGUI = ChartGUI

def main():
    """Launch GUI"""
    # Use the debug mode that was detected at module import time
    # (BEFORE utils/debug.py could consume the flag)
    debug_mode = _DEBUG_MODE

    app = QApplication(sys.argv)
    app.setDesktopFileName("varuna360-core")

    # Register the bundled Inter family so QFont("Inter") resolves in dev and in
    # frozen builds instead of silently substituting (SPEC-FONT, WI-7). Silent
    # and safe when the font is not bundled.
    try:
        from ui.font_bootstrap import register_bundled_fonts
        register_bundled_fonts(PROJECT_ROOT)
    except Exception:
        pass

    # Headless boot smoke for the build gate (WI-8). When VARUNA360_BOOT_CHECK_MS
    # is set, the app skips every interactive gate that would block a scripted
    # launch (sign-in, first-run, welcome) and quits itself after that many ms,
    # once the main window has been fully constructed and shown. Exit 0 with no
    # startup_crash.txt then proves the whole import + widget-construction path.
    _boot_check_ms = 0
    try:
        _boot_check_ms = int(os.environ.get("VARUNA360_BOOT_CHECK_MS", "0"))
    except ValueError:
        _boot_check_ms = 0
    # Clamp to a sane ceiling. This value only ever arms the auto-quit timer and
    # skips the NON-auth onboarding gates (see _boot_check_active below); it can
    # NEVER skip the license gate, which runs unconditionally when IS_BUNDLED.
    # The clamp is a second belt: even a source test build quits within 30 s.
    _boot_check_ms = min(max(_boot_check_ms, 0), 30_000)

    # Enable Ctrl+C to quit immediately (no waiting)
    # Qt applications normally ignore SIGINT, so we need to handle it explicitly
    def handle_sigint(signum, frame):
        """Handle Ctrl+C (SIGINT) for immediate exit."""
        print("\n[QUIT] Ctrl+C pressed - exiting immediately...")
        QApplication.quit()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_sigint)

    # Set a timer to process signals periodically (every 100ms)
    # This ensures SIGINT is handled even during the Qt event loop
    timer = QTimer()
    timer.timeout.connect(lambda: None)  # Dummy function to keep event loop alive
    timer.start(100)

    # Apply qt-material theme on startup
    apply_fn = _get_apply_stylesheet()
    if apply_fn:
        from state.user_data import get_user_data_dir
        data_dir = get_user_data_dir() or PROJECT_ROOT
        theme = "dark_blue.xml"
        # SPEC-SAT-001 WI-2: boot saturation. SettingsManager does NOT exist yet
        # at this point, so read display.color_saturation with the SAME raw
        # json.load pattern the theme read uses (never get_settings()). Covering
        # boot here is what stops the app starting saturated until the first
        # manual theme switch (boot-asymmetry pre-mortem #8).
        boot_saturation = 100
        try:
            # Check app_settings.json first (post-migration canonical source)
            app_settings_path = data_dir / "app_settings.json"
            if app_settings_path.exists():
                with open(app_settings_path, "r") as f:
                    app_cfg = json.load(f)
                    display_name = app_cfg.get("appearance", {}).get("theme", "")
                    if display_name:
                        from ui.themes import AVAILABLE_THEMES
                        for t in AVAILABLE_THEMES:
                            if t[1] == display_name:
                                theme = t[0]
                                break
                    boot_saturation = app_cfg.get("display", {}).get("color_saturation", 100)
            else:
                # Fallback to legacy settings.json
                theme_settings_path = data_dir / "settings.json"
                if theme_settings_path.exists():
                    with open(theme_settings_path, "r") as f:
                        settings = json.load(f)
                        theme = settings.get("theme", "dark_blue.xml")
                        boot_saturation = settings.get("display", {}).get(
                            "color_saturation", 100)
        except Exception:
            pass
        from ui.qt_theme import set_ui_saturation, desaturated_theme_path
        set_ui_saturation(boot_saturation)
        apply_fn(app, theme=desaturated_theme_path(theme))
        # G9d (td-q43fm): scale combobox / spin box / text-input fonts app-wide
        # (qt-material froze them at the universal 13px).
        from ui.input_font_qss import apply_global_input_font_qss
        apply_global_input_font_qss(app)
    else:
        app.setStyle("Fusion")

    # Install global "Search Google" right-click on any selected text
    from managers.context_menu_manager import install_search_context_menu
    install_search_context_menu(app)

    # ── License gate ────────────────────────────────────────────
    # Varuna360 Core is AGPL-3.0 and runs anonymously from source. The
    # license-KEY gate (paste an Explorateur key, verify it offline) is
    # mandatory in any PACKAGED build and optional from source.
    #
    # Enforcement is keyed on sys.frozen, NOT on an environment variable.
    # Every shipped edition is a frozen (PyInstaller/Nuitka) binary, so a
    # frozen build always enforces: clearing the process environment or
    # running an inner ELF cannot switch the gate off. VARUNA360_BUNDLED=1
    # survives only as a source-run opt-in that lets a developer TEST the
    # gate without freezing a binary. Opting IN to more enforcement is
    # harmless; there is no env value that opts OUT of a frozen build.
    # (History: this was env-only, and nothing in the shipped path ever set
    # the var, so the gate was dead in every packaged build. Keying on
    # sys.frozen fixes that and, because a shipped build is always frozen,
    # also removes the VARUNA360_BOOT_CHECK_MS auth-bypass in one move.)
    #
    # The IS_BUNDLED split keeps commercial enforcement and software
    # features decoupled: _LITE_MODE forces ChartGUI (skips Pro import),
    # while IS_BUNDLED is "which commercial model applies".
    #
    # STRUCTURAL FREEDOM 0 PROTECTION: the anonymous (non-frozen, no-env)
    # path does not import managers.license_manager or managers.license_key
    # at all. license_state stays None on anonymous boot, and the refresh
    # flow handles None as "no license to refresh".
    IS_BUNDLED = _is_bundled()

    # The build-time headless boot check (VARUNA360_BOOT_CHECK_MS) skips only the
    # NON-auth onboarding gates (first-run, welcome) and arms an auto-quit timer
    # so a scripted launch cannot hang. It must NEVER skip the license gate:
    # letting a user-settable env var reach the full app would be an auth bypass.
    # So the auth gate below always runs. A frozen build boots past it either
    # with a valid key or, on a fresh install, via the no-key free trial (which
    # is also what lets build_lite.py step_boot_check pass in an empty scratch
    # home) never by an env flag.
    _boot_check_active = _boot_check_ms > 0

    if IS_BUNDLED:
        # License-KEY gate: the user pastes a license key copied from their
        # 360heartsinthesky.com account; it is exchanged for a signed token and
        # verified offline (managers/license_key.py). No account, no sign-in.
        # Declining means exiting, so the "Continue without a key" button is
        # hidden here.
        from managers.license_key import (
            attempt_key_login, trial_state, ensure_install_anchor,
            has_been_licensed,
        )
        # Stamp the trial anchor at install time (idempotent) BEFORE the key
        # check, so the 7-day window is measured from first launch even for a
        # user who licenses immediately. Without this, a revoked payer whose
        # caches are later cleared would be handed a fresh trial.
        ensure_install_anchor()
        license_state = attempt_key_login()
        if not license_state.is_licensed:
            # No valid key: fall back to the no-key free trial, UNLESS this
            # machine was ever licensed (a former payer re-keys, never re-trials;
            # this guard holds even if the install anchor failed to persist).
            # First launch starts the trial (app opens immediately, no dialog);
            # within the window it keeps granting. Once ended, require a key.
            trial = None if has_been_licensed() else trial_state()
            if trial is not None:
                license_state = trial
            else:
                from apps.widgets.key_dialog import KeyDialog
                key_dialog = KeyDialog(
                    show_continue_without_account=False,
                    message=(
                        "Your 7-day free trial has ended. Enter your license "
                        "key to continue."
                    ),
                )
                if key_dialog.exec() == KeyDialog.DialogCode.Accepted:
                    license_state = key_dialog.get_license_state()
                else:
                    sys.exit(0)
    else:
        # Anonymous source/self-host path. NO import of license_manager,
        # NO server call, NO dialog. license_state stays None; downstream
        # refresh code is None-safe.
        license_state = None

    # Arm the boot-check auto-quit ONLY after the auth gate has resolved. A
    # key-gated (frozen) build reaches this line only if it got past the gate
    # with a valid token, so the timer can never be used to escape a blocked
    # gate and produce a vacuous "pass" (fail-closed: no token, no pass).
    if _boot_check_active:
        QTimer.singleShot(_boot_check_ms, app.quit)

    # ────────────────────────────────────────────────────────────

    # First-run data directory setup (AppImage/frozen only).
    # On a fresh install there is no bootstrap config yet, so we ask the
    # user where to store profiles, settings, and session files.
    from state.user_data import needs_first_run_setup
    if needs_first_run_setup() and not _boot_check_active:
        from apps.widgets.first_run_dialog import FirstRunDialog
        first_run = FirstRunDialog()
        if first_run.exec() != FirstRunDialog.DialogCode.Accepted:
            sys.exit(0)

    # First-launch welcome popup — shown exactly once per install before
    # the main window appears. The flag file at
    # ~/.config/Varuna360/.welcome_shown is written on close so the
    # popup never shows again. Intrusive by design: the user wanted
    # the welcome message to register before the main UI distracts them.
    from apps.widgets.welcome_dialog import WelcomeDialog, should_show_welcome
    if should_show_welcome() and not _boot_check_active:
        welcome = WelcomeDialog()
        welcome.exec()

    gui_class = ChartGUI
    if not _LITE_MODE:
        try:
            pass  # Pro import stripped for Lite distribution
            gui_class = ProChartGUI
        except ImportError:
            pass
    window = gui_class(debug_mode=debug_mode)
    window._license_state = license_state  # Store for periodic refresh
    window.show()

    # Open a chart file if passed as command-line argument (e.g. double-click
    # from file manager). SPEC-IMPORT-001 §6.1: accept .toml as well as .chtk;
    # chart_manager.load_chart dispatches by extension (create_birth_data_from_file).
    chtk_arg = None
    for arg in sys.argv[1:]:
        if arg.endswith(('.chtk', '.toml')) and os.path.isfile(arg):
            chtk_arg = arg
            break
    if chtk_arg:
        QTimer.singleShot(1500, lambda path=chtk_arg: window.chart_manager.load_chart(path))

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
