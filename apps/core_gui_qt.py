#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
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
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QWidget,
    QFileDialog, QMessageBox, QTabWidget, QListWidget, QListWidgetItem,
    QTextEdit, QPushButton, QLabel, QStackedWidget, QSizePolicy, QProgressBar,
    QScrollArea
)
from PySide6.QtCore import (
    QProcess, Qt, QTimer, QSize, QRunnable, QThreadPool, QObject, Signal, Slot,
    QPropertyAnimation, QEasingCurve,
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

from PySide6.QtGui import QAction, QKeySequence, QActionGroup, QColor, QBrush, QIcon

# Project root for absolute paths
PROJECT_ROOT = Path(__file__).parent.parent

# Add to path for imports
sys.path.insert(0, str(PROJECT_ROOT))

# Import theme functions for styling (must be after sys.path modification)
from ui.qt_theme import get_tab_bar_style, get_theme_colors, get_menu_bar_style, scaled_px, scaled_area_px

from core.chtk_reader import CHTKReader

# Import title formatting from chart_manager
from managers.chart_manager import _format_chart_title

VARGA_NAMES = {
    1: "Rasi", 2: "Hora", 3: "Drekkana", 4: "Chaturthamsa",
    7: "Saptamsa", 9: "Navamsa", 10: "Dasamsa", 1010: "Dasamsa-R",
    12: "Dwadasamsa", 16: "Shodasamsa", 20: "Vimshamsa",
    24: "Chaturvimshamsa", 2424: "Siddhamsa-R", 27: "Bhamsha",
    30: "Trimshamsa", 40: "Khavedamsa", 45: "Akshavedamsa", 60: "Shashtiamsa",
}


# Import modular widgets
from apps.widgets.chart_view import SouthIndianView, PlanetClickSignal, SignClickSignal
from apps.widgets.wheel_view import WheelView
from apps.widgets.north_indian_view import NorthIndianView
from apps.widgets.planet_dialog import PlanetInfoDialog
from apps.widgets.sector_dialog import SectorInfoDialog
from apps.widgets.sign_variation_dialog import SignVariationDialog
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


# Import panel factory functions
from apps.panels.vedanga_panel import create_vedanga_panel
from apps.panels.vimshottari_panel import create_vimshottari_panel
from apps.panels.info_panels import create_right_panels
from apps.panels.sign_selector_column import create_sign_selector_column
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

class ChartGUI(QMainWindow):
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

    def __init__(self, debug_mode=False, **kwargs):
        super().__init__()
        self.debug_mode = debug_mode

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

        # Dasha state. Source the two dasha ayanamsha configs from app_settings.json
        # (the authoritative store) instead of hard-coded literals, so a saved or
        # locked config is honoured at boot, BEFORE the first dasha compute (~:487).
        # Use get(key, default), never `value or default` (ayanamsa id 0 is valid).
        from managers.settings_manager import get_settings
        _sm = get_settings()
        self.right_dasha_mode = _sm.get("dasha.right.mode", "nisarga")  # "vimshottari" or "nisarga"
        self.dasha_level_vedanga = 1
        self.dasha_level_vimshottari = 1
        self.dasha_level_nisarga = 1  # 1=periods, 2=maturation
        self.dasha_cycle_offset_vedanga = 0  # Track 120-year cycle offset
        self.dasha_cycle_offset_vimshottari = 0  # Track 120-year cycle offset
        self.vedanga_dasha_data = None
        self.vimshottari_dasha_data = None
        # Track parent hierarchy for filtered sub-dasha view
        self.vimshottari_parent_chain = []  # List of parent lord names at each level
        self.vedanga_parent_chain = []  # List of parent lord names at each level

        # Ayanamsa settings for each dasha panel (configurable via title click),
        # sourced from app_settings.json (defaults: LEFT/Vedanga 100, RIGHT/Vimshottari 98).
        self.vedanga_ayanamsa     = _sm.get("dasha.left.ayanamsa_id", 100)
        self.vimshottari_ayanamsa = _sm.get("dasha.right.ayanamsa_id", 98)
        self.nakshatra_coords     = _sm.get("zodiac.nakshatra_coords", "neither")

        # Chart zodiac type: "tropical" (default) or "sidereal"
        self.chart_zodiac = "tropical"
        # Ayanamsa ID for sidereal chart display (tied to dasha ayanamsa selection)
        self.chart_sidereal_ayanamsa_id = 1  # Lahiri default
        # Cached ayanamsa offset in degrees (computed from birth JD)
        self.chart_ayanamsa_offset = 0.0

        # Dual rim mode: show outer Tropical rim on Aditya wheel (wheel view only)
        self.show_tropical_rim = False

        # Transit overlay managed by TransitOverlayManager (initialized in _init_managers)

        # Sign name display: False = Aditya names (Dhata, Aryama...), True = Western names (Aries, Taurus...)
        # This only affects display labels, not calculations
        self.use_western_names = False

        # Human Design mode (-88° Sun shift) - independent toggle
        self.is_human_design = False

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

        from managers.transit_overlay_manager import TransitOverlayManager
        self.transit_overlay_manager = TransitOverlayManager(gui=self, parent=self)
        self.state.connect(self.transit_overlay_manager._on_active_chart_changed)
        self.aditya_mode_changed.connect(
            self.transit_overlay_manager._on_aditya_mode_changed
        )
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
            InterchangeController,
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
        self.vedanga_panel = create_vedanga_panel(self)
        chart_layout.addWidget(self.vedanga_panel)

        # Column 2: Slim Varga Column (between Vedanga and Chart)
        _is_implemented = lambda n: n in VARGA_NAMES
        _get_name = lambda n: VARGA_NAMES.get(n, f"D-{n}")
        self.varga_column = create_varga_column(self, _is_implemented, _get_name)
        chart_layout.addWidget(self.varga_column)

        # Column 3: Chart view (center) - takes remaining space
        # Use QStackedWidget to switch between South Indian and Wheel views
        self.chart_stack = QStackedWidget()
        self.chart_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # South Indian View (index 0)
        self.chart_view = SouthIndianView()
        # Connect planet click signal to show dialog
        self.chart_view.planet_click_signal.clicked.connect(self._show_planet_dialog)
        # Connect sign click signal to show variation dialog
        self.chart_view.sign_click_signal.clicked.connect(self._show_sign_variation_dialog)
        # Load initial background from settings
        from managers.settings_manager import get_settings
        settings = get_settings()
        current_theme = self._load_theme_preference()
        initial_bg = "stone_01" if current_theme.startswith('light_') else "stone_06"
        self.chart_view.set_background(initial_bg)
        self.chart_stack.addWidget(self.chart_view)

        # Wheel View (index 1)
        self.wheel_view = WheelView()
        self.wheel_view.connect_gui(self)
        self.wheel_view.planet_click_signal.clicked.connect(self._show_planet_dialog)
        self.wheel_view._retinue_click_signal.clicked.connect(self._show_sector_dialog)
        self.wheel_view.sign_click_signal.clicked.connect(self._show_sign_variation_dialog)
        self.chart_stack.addWidget(self.wheel_view)

        # North Indian View (index 2)
        self.north_indian_view = NorthIndianView()
        # Connect planet click signal (uses same dialog)
        self.north_indian_view.planet_click_signal.clicked.connect(self._show_planet_dialog)
        self.north_indian_view.sign_click_signal.clicked.connect(self._show_sign_variation_dialog)
        self.chart_stack.addWidget(self.north_indian_view)
        self._set_sign_language(self.sign_language)

        # Default to South Indian view (state.chart_view_style is the source of truth)
        self.chart_stack.setCurrentIndex(0)

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
        self.vimshottari_panel = create_vimshottari_panel(self)
        chart_layout.addWidget(self.vimshottari_panel)

        # Apply default Nisarga mode to right panel UI
        if self.right_dasha_mode == "nisarga":
            self._configure_right_panel_for_nisarga()

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

        # === SESSION MANAGER (Phase 4) ===
        # Phase 4 W4: ProfileStore wraps the file I/O; SessionManager keeps
        # the auto-save QTimer + restore dialog + business logic.
        from managers.session_manager import SessionManager
        from state import ProfileStore
        self.profile_store = ProfileStore(self.user_data_dir / "profiles")
        self.session_manager = SessionManager(self, profile_store=self.profile_store)

        # === PROFILE MANAGER ===
        from managers.profile_manager import ProfileManager
        self.profile_manager = ProfileManager(self, profiles_dir=self.user_data_dir / "profiles")
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
        _ecl_label = QLabel("Click to load Edit Chart...")
        _ecl_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _ecl_label.setStyleSheet(f"color: #888; font-size: {scaled_px(14)}px;")
        _ecl.addWidget(_ecl_label)
        self.tab_widget.addTab(self._edit_chart_placeholder, "Edit Chart")
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
        self._settings_progress_bar.setStyleSheet("""
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
        """)
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

    # =========================================================================
    # SPEC-LITE-001 RPI-A: Property shim for dict elimination
    # =========================================================================

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

    # =========================================================================
    # TRUE LAZY LOADING - Tabs only load when clicked
    # =========================================================================


    def _create_settings_tab(self, current_theme):
        """Factory: return a SettingsTab instance. Override in Pro for extended settings."""
        from ui.settings_tab import SettingsTab
        return SettingsTab(current_theme=current_theme)

    def has_transit_tab(self):
        """Capability query: does this edition have a Transit tab? Override in Pro."""
        return False

    def _add_feature_tabs(self):
        """Add feature tabs between Find Chart and Settings. Override in Pro."""
        pass

    def _add_trailing_tabs(self):
        """Add tabs after Settings (before Debug). Override in Pro."""
        pass

    def _on_chart_recalculated(self):
        """Hook called after chart recalculation. Override in Pro for extra updates."""
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
                    if hasattr(self.settings_tab, 'sign_language_changed'):
                        self.settings_tab.sign_language_changed.connect(self._set_sign_language)
                    if hasattr(self.settings_tab, 'chart_display_changed'):
                        self.settings_tab.chart_display_changed.connect(self._on_chart_display_changed)
                    if hasattr(self.settings_tab, 'background_changed'):
                        self.settings_tab.background_changed.connect(self._on_background_changed)
                    if hasattr(self.settings_tab, 'zodiac_changed'):
                        self.settings_tab.zodiac_changed.connect(self._set_aditya_mode)
                    if hasattr(self.settings_tab, 'dasha_changed'):
                        self.settings_tab.dasha_changed.connect(self._on_dasha_settings_changed)
                    if hasattr(self.settings_tab, 'names_changed'):
                        self.settings_tab.names_changed.connect(self._on_names_changed)
                    if hasattr(self.settings_tab, 'ayanamsa_changed'):
                        self.settings_tab.ayanamsa_changed.connect(self._on_ayanamsa_changed)
                    if hasattr(self.settings_tab, 'house_system_changed'):
                        self.settings_tab.house_system_changed.connect(self._on_house_system_changed)
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
                    if hasattr(self.settings_tab, 'ai_settings_tab') and hasattr(self, 'ai_reading_panel'):
                        self.settings_tab.ai_settings_tab.settings_changed.connect(
                            self.ai_reading_panel.refresh_provider_button
                        )
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
                self.tab_widget.insertTab(index, self.edit_chart_panel, "Edit Chart")
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

    # =========================================================================
    # ADAPTIVE TAB PRELOADING — preload top 3 most-used deferred tabs
    # =========================================================================

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

    def _create_menus(self):
        """Create application menu bar with modern dark styling"""
        menubar = self.menuBar()

        # Apply modern dark theme styling
        menubar.setStyleSheet(get_menu_bar_style())

        # File Menu
        file_menu = menubar.addMenu("&File")

        # Open action
        open_action = QAction("&Open CHTK...", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.setStatusTip("Open a CHTK chart file")
        open_action.triggered.connect(self._open_file_dialog)
        file_menu.addAction(open_action)

        file_menu.addSeparator()

        # New Chart action
        new_chart_action = QAction("&New Chart...", self)
        new_chart_action.setShortcut(QKeySequence("Ctrl+N"))
        new_chart_action.setStatusTip("Create a new chart from scratch")
        new_chart_action.triggered.connect(self._show_new_chart)
        file_menu.addAction(new_chart_action)

        # Edit Chart action
        edit_chart_action = QAction("&Edit Chart...", self)
        edit_chart_action.setShortcut(QKeySequence("Ctrl+E"))
        edit_chart_action.setStatusTip("Edit current chart information")
        edit_chart_action.triggered.connect(self._show_edit_chart)
        file_menu.addAction(edit_chart_action)

        file_menu.addSeparator()

        # Save As CHTK action
        save_as_action = QAction("&Save As CHTK...", self)
        save_as_action.setShortcut(QKeySequence.StandardKey.SaveAs)
        save_as_action.setStatusTip("Save current chart as CHTK file")
        save_as_action.triggered.connect(self._save_as_chtk)
        file_menu.addAction(save_as_action)

        file_menu.addSeparator()

        # Reload action
        reload_action = QAction("&Reload Current", self)
        reload_action.setShortcut(QKeySequence("Ctrl+R"))
        reload_action.setStatusTip("Reload the current chart file")
        reload_action.triggered.connect(self._reload_current)
        file_menu.addAction(reload_action)

        file_menu.addSeparator()

        # Screenshot action (debug - to screenshot_debug/)
        screenshot_action = QAction("&Screenshot", self)
        screenshot_action.setShortcut(QKeySequence("F12"))
        screenshot_action.setStatusTip("Save chart screenshot to screenshot_debug/")
        screenshot_action.triggered.connect(self._take_screenshot)
        file_menu.addAction(screenshot_action)

        # Save Chart as PNG (high quality, file dialog)
        save_chart_png_action = QAction("Save &Chart as PNG...", self)
        save_chart_png_action.setShortcut(QKeySequence("Ctrl+Shift+S"))
        save_chart_png_action.setStatusTip("Export current chart as high-quality PNG")
        save_chart_png_action.triggered.connect(self._save_chart_as_png)
        file_menu.addAction(save_chart_png_action)

        # Save Full View as PNG (entire window)
        save_full_png_action = QAction("Save &Full View as PNG...", self)
        save_full_png_action.setStatusTip("Export entire application view as PNG")
        save_full_png_action.triggered.connect(self._save_full_view_as_png)
        file_menu.addAction(save_full_png_action)

        file_menu.addSeparator()

        # Exit action
        exit_action = QAction("E&xit", self)
        exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        exit_action.setStatusTip("Exit the application")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # View Menu
        view_menu = menubar.addMenu("&View")

        # Varga submenu
        varga_menu = view_menu.addMenu("&Varga Charts")

        # Create action group for mutually exclusive selection
        varga_group = QActionGroup(self)
        varga_group.setExclusive(True)

        # Define common vargas in display order
        varga_order = [1, 2, 3, 4, 7, 9, 10, 12, 16, 20, 24, 27, 30, 40, 45, 60]

        self.varga_actions = {}
        for varga_num in varga_order:
            if varga_num in VARGA_NAMES:
                varga_name = VARGA_NAMES[varga_num]
                action = QAction(f"D-{varga_num} ({varga_name})", self)
                action.setCheckable(True)
                action.setChecked(varga_num == 1)
                action.setStatusTip(f"Show {varga_name} (D-{varga_num}) chart")
                action.triggered.connect(lambda checked, v=varga_num: self._switch_varga(v))
                varga_group.addAction(action)
                varga_menu.addAction(action)
                self.varga_actions[varga_num] = action

        view_menu.addSeparator()

        # Planet Placements action
        placements_action = QAction("&Planet Placements...", self)
        placements_action.setShortcut(QKeySequence("Ctrl+P"))
        placements_action.setStatusTip("Show table of all planetary positions")
        placements_action.triggered.connect(self._show_planet_placements)
        view_menu.addAction(placements_action)

        # Outer Planets toggle action
        self.outer_planets_action = QAction("Show &Outer Planets", self)
        self.outer_planets_action.setShortcut(QKeySequence("F8"))
        self.outer_planets_action.setCheckable(True)
        self.outer_planets_action.setChecked(True)  # Default ON - outer planets visible
        self.outer_planets_action.setStatusTip("Toggle Uranus, Neptune, Pluto visibility (F8)")
        self.outer_planets_action.triggered.connect(self._toggle_outer_planets)
        view_menu.addAction(self.outer_planets_action)

        # Planet Labels toggle action (F11)
        self.planet_names_action = QAction(
            "Planet Labels: Show &Names (F11)", self)
        self.planet_names_action.setShortcut(QKeySequence("F11"))
        self.planet_names_action.setCheckable(True)
        self.planet_names_action.setChecked(False)
        self.planet_names_action.setStatusTip(
            "Switch planet labels between degrees and names (F11)")
        self.planet_names_action.triggered.connect(self._toggle_planet_names)
        view_menu.addAction(self.planet_names_action)

        # Cycle Sign as Ascendant action (F4)
        self.cycle_ascendant_action = QAction("Cycle &Sign as Ascendant", self)
        self.cycle_ascendant_action.setShortcut(QKeySequence("F4"))
        self.cycle_ascendant_action.setStatusTip("Cycle through signs as Ascendant: Dhata → Aryama → ... → Birth (F4)")
        self.cycle_ascendant_action.triggered.connect(self._cycle_sign_ascendant)
        view_menu.addAction(self.cycle_ascendant_action)

        # Cycle Chart View action (F2)
        self.cycle_view_action = QAction("Cycle Chart &View", self)
        self.cycle_view_action.setShortcut(QKeySequence("F2"))
        self.cycle_view_action.setStatusTip("Cycle: South Indian → Wheel → North Indian (F2)")
        self.cycle_view_action.triggered.connect(self._cycle_chart_view)
        view_menu.addAction(self.cycle_view_action)

        # Cycle Right Dasha action (F7)
        self.cycle_right_dasha_action = QAction("Cycle Right &Dasha", self)
        self.cycle_right_dasha_action.setShortcut(QKeySequence("F7"))
        self.cycle_right_dasha_action.setStatusTip("Cycle right panel: Vimshottari / Planetary Ages (F7)")
        self.cycle_right_dasha_action.triggered.connect(self._cycle_right_dasha)
        view_menu.addAction(self.cycle_right_dasha_action)

        # Toggle Transit Overlay (F3)
        self.transit_action = QAction("Toggle &Transit Overlay", self)
        self.transit_action.setShortcut(QKeySequence("F3"))
        self.transit_action.setCheckable(True)
        self.transit_action.setChecked(False)
        self.transit_action.setStatusTip(
            "Toggle transit overlay on current chart view (F3)")
        self.transit_action.triggered.connect(self._toggle_transit_rim)
        view_menu.addAction(self.transit_action)

        # Toggle Retinue Rings action (F5)
        self.retinue_rings_action = QAction("Toggle &Retinue Rings", self)
        self.retinue_rings_action.setShortcut(QKeySequence("F5"))
        self.retinue_rings_action.setCheckable(True)
        self.retinue_rings_action.setChecked(False)
        self.retinue_rings_action.setStatusTip(
            "Toggle Hora + Trimsamsa outer rings on wheel chart (F5)")
        self.retinue_rings_action.triggered.connect(self._toggle_retinue_rings)
        view_menu.addAction(self.retinue_rings_action)

        # Toggle Trimsamsha Degree Ruler (F6)
        self.trimsamsha_degrees_action = QAction("Toggle Trimsamsha &Degrees", self)
        self.trimsamsha_degrees_action.setShortcut(QKeySequence("F6"))
        self.trimsamsha_degrees_action.setCheckable(True)
        self.trimsamsha_degrees_action.setChecked(False)
        self.trimsamsha_degrees_action.setStatusTip(
            "Toggle degree labels on Trimsamsha ring (F6)")
        self.trimsamsha_degrees_action.triggered.connect(
            self._toggle_trimsamsha_degrees)
        view_menu.addAction(self.trimsamsha_degrees_action)

        # Toggle Pie Charts action (Shift+F5)
        self.pie_charts_action = QAction("Toggle &Pie Charts", self)
        self.pie_charts_action.setShortcut(QKeySequence("Shift+F5"))
        self.pie_charts_action.setCheckable(True)
        self.pie_charts_action.setChecked(True)
        self.pie_charts_action.setStatusTip(
            "Show/hide element pie charts on wheel (Shift+F5)")
        self.pie_charts_action.triggered.connect(self._toggle_pie_charts)
        view_menu.addAction(self.pie_charts_action)

        # Cycle Cusp Glow Lines action (F9)
        self.cusp_glow_action = QAction("Cycle Cusp &Lines", self)
        self.cusp_glow_action.setShortcut(QKeySequence("F9"))
        self.cusp_glow_action.setStatusTip(
            "Cycle cusp glow lines: OFF / Angles / All (F9)")
        self.cusp_glow_action.triggered.connect(self._cycle_cusp_glow)
        view_menu.addAction(self.cusp_glow_action)

        view_menu.addSeparator()

        # ── Chart Mode toggles (Alt+Z / Alt+C / Alt+S / Alt+H) ──

        # Aditya Circle mode (Alt+Z)
        self.aditya_circle_action = QAction("&Aditya Circle Mode", self)
        self.aditya_circle_action.setShortcut(QKeySequence("Alt+Z"))
        self.aditya_circle_action.setStatusTip(
            "Switch to Aditya Circle naming (Alt+Z)")
        self.aditya_circle_action.triggered.connect(
            lambda: self._set_aditya_mode("aditya"))
        view_menu.addAction(self.aditya_circle_action)

        # Tropical Classic mode (Alt+C)
        self.tropical_classic_action = QAction("&Tropical Classic Mode", self)
        self.tropical_classic_action.setShortcut(QKeySequence("Alt+C"))
        self.tropical_classic_action.setStatusTip(
            "Switch to Tropical Classic naming (Alt+C)")
        self.tropical_classic_action.triggered.connect(
            lambda: self._set_aditya_mode("tropical_classic"))
        view_menu.addAction(self.tropical_classic_action)

        # Toggle Sidereal Chart (Alt+S)
        self.sidereal_action = QAction("Toggle &Sidereal Chart", self)
        self.sidereal_action.setShortcut(QKeySequence("Alt+S"))
        self.sidereal_action.setCheckable(True)
        self.sidereal_action.setChecked(False)
        self.sidereal_action.setStatusTip(
            "Toggle sidereal chart mode — subtracts ayanamsa from all positions (Alt+S)")
        self.sidereal_action.triggered.connect(self._toggle_sidereal)
        view_menu.addAction(self.sidereal_action)

        # Human Design mode (Alt+H)
        self.human_design_action = QAction("Toggle &Human Design", self)
        self.human_design_action.setShortcut(QKeySequence("Alt+H"))
        self.human_design_action.setStatusTip(
            "Toggle Human Design mode — shifts Sun by -88° (Alt+H)")
        self.human_design_action.triggered.connect(self._toggle_human_design)
        view_menu.addAction(self.human_design_action)

        view_menu.addSeparator()

        # Language submenu for Western sign names
        language_menu = view_menu.addMenu("&Language")
        self._language_group = QActionGroup(self)
        self._language_group.setExclusive(True)
        self._language_actions = {}

        _LANGUAGES = [
            ("en", "&English"),
            ("fr", "&Français"),
            ("es", "&Español"),
            ("pt", "Português &BR"),
            ("pt-PT", "Português &PT"),
            ("de", "&Deutsch"),
            ("it", "&Italiano"),
            ("ru", "&Русский"),
            ("zh", "&中文"),
        ]

        for code, label in _LANGUAGES:
            action = QAction(label, self)
            action.setCheckable(True)
            action.setData(code)
            action.triggered.connect(lambda checked, c=code: self._set_sign_language(c))
            self._language_group.addAction(action)
            language_menu.addAction(action)
            self._language_actions[code] = action

        self._language_actions.get(self.sign_language, self._language_actions["en"]).setChecked(True)

        # Account Menu — top-level, sibling of File/View/Help (NOT under Help).
        # The desktop app runs anonymously by default; this menu is where users
        # who want to attach a website account tier (free or paid) sign in or
        # create an account. All three entries lazy-load their dialogs so an
        # anonymous user never pays the import cost.
        account_menu = menubar.addMenu("&Account")

        sign_in_action = QAction("&Sign In…", self)
        sign_in_action.setStatusTip(
            "Sign in to a Varuna360 account (optional — the desktop works "
            "fully without an account)"
        )
        sign_in_action.triggered.connect(self._show_sign_in_dialog)
        account_menu.addAction(sign_in_action)

        create_account_action = QAction("&Create Account…", self)
        create_account_action.setStatusTip(
            "Open the subscription page to create an account or start a subscription"
        )
        create_account_action.triggered.connect(self._open_subscribe_page)
        account_menu.addAction(create_account_action)

        account_menu.addSeparator()

        view_tiers_action = QAction("&View Tiers…", self)
        view_tiers_action.setStatusTip("Compare the three Varuna360 account tiers")
        view_tiers_action.triggered.connect(self._show_tier_dialog)
        account_menu.addAction(view_tiers_action)

        # Help Menu
        help_menu = menubar.addMenu("&Help")

        # Manual action
        manual_action = QAction("&Manual...", self)
        manual_action.setShortcut(QKeySequence("F1"))
        manual_action.setStatusTip("Open the Varuna 360 help manual (F1)")
        manual_action.triggered.connect(self._show_manual)
        help_menu.addAction(manual_action)

        help_menu.addSeparator()

        # About action
        about_action = QAction("&About", self)
        about_action.setStatusTip("About this application")
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

        # About Varuna360 Pro — static marketing dialog. Always shown.
        # Reads constants from core/pro_marketing.py — no runtime detection
        # of whether Pro is installed, just a link to the upgrade page.
        about_pro_action = QAction("About Varuna360 &Pro...", self)
        about_pro_action.setStatusTip(
            "Learn about the Pro edition and its additional research tools"
        )
        about_pro_action.triggered.connect(self._show_about_pro)
        help_menu.addAction(about_pro_action)

    def _restart_app(self):
        """Restart the application with the same command-line arguments."""
        # Close the window
        self.close()

        # Use QProcess to restart the app with original arguments (includes -d flag)
        QProcess.startDetached(
            sys.executable,
            self.original_argv,
            Path.cwd().as_posix()
        )

    def _show_profile_menu(self):
        """Show profile dropdown menu from profile button."""
        if hasattr(self, 'profile_manager'):
            # Get button global position
            button_pos = self.profile_button.mapToGlobal(self.profile_button.rect().bottomLeft())
            self.profile_manager.show_profile_menu(self, button_pos)
        else:
            pass

    def _update_profile_button_style(self):
        """Update profile button styling with current theme colors."""
        # SPEC-THM-001 E5: get_theme_colors imported at module level.
        theme = get_theme_colors()

        self.profile_button.setStyleSheet(f"""
            QPushButton {{
                border-radius: 18px;
                background-color: {theme["secondary"]};
                color: {theme["secondary_text"]};
                font-size: {scaled_px(16)}px;
                border: 1px solid {theme["primary"]};
            }}
            QPushButton:hover {{
                background-color: {theme["primary"]};
                color: {theme["primary_text"]};
            }}
        """)

    def _load_profile_avatar(self):
        """Load avatar image for profile button from ProfileManager."""
        if not hasattr(self, 'profile_manager'):
            self.profile_button.setText("👤")
            return

        try:
            profile_data = self.profile_manager.get_profile_data()
            if not profile_data:
                self.profile_button.setText("👤")
                return

            avatar_path = profile_data.get("avatar", "img/planets/sun.webp")

            # Load avatar at full button size for visibility
            pixmap = self.profile_manager.get_avatar_pixmap(avatar_path, size=(36, 36))

            if pixmap and not pixmap.isNull():
                icon = QIcon(pixmap)

                # Set icon and remove text
                self.profile_button.setIcon(icon)
                self.profile_button.setIconSize(QSize(36, 36))  # Full button size
                self.profile_button.setText("")  # Clear text to show icon

                # Force visibility and bring to front
                self.profile_button.show()
                self.profile_button.raise_()
                self.profile_button.update()
                self.profile_button.repaint()
            else:
                # Ensure emoji is visible if avatar fails
                self.profile_button.setText("👤")
                self.profile_button.setIcon(QIcon())  # Clear any null icon
                self.profile_button.show()
                self.profile_button.raise_()
        except Exception as e:
            print(f"Error loading profile avatar: {e}")
            # Ensure emoji is visible on error
            self.profile_button.setText("👤")
            self.profile_button.setIcon(QIcon())  # Clear any null icon
            self.profile_button.show()
            self.profile_button.raise_()
            import traceback
            traceback.print_exc()

    # =========================================================================
    # WINDOW GEOMETRY MANAGEMENT
    # =========================================================================

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

    # -------------------------------------------------------------------------
    # License refresh (called by 12h QTimer)
    # -------------------------------------------------------------------------

    def _refresh_license(self):
        """Silently refresh the license token in a background thread."""
        if not hasattr(self, '_license_state') or self._license_state is None:
            return
        # Don't start a new refresh if the previous one is still running
        if hasattr(self, '_license_refresh_worker') and self._license_refresh_worker and self._license_refresh_worker.isRunning():
            return

        from managers.license_workers import LicenseRefreshWorker
        self._license_refresh_worker = LicenseRefreshWorker(self._license_state)
        self._license_refresh_worker.finished.connect(self._on_license_refresh_done)
        self._license_refresh_worker.error.connect(
            lambda msg: print(f"Error: license refresh failed: {msg}")
        )
        self._license_refresh_worker.start()

    def _on_license_refresh_done(self, updated_state):
        """Handle license refresh result (called on main thread via signal)."""
        self._license_state = updated_state
        if updated_state.is_licensed:
            pass
        else:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "Subscription Expired",
                "Your Varuna360 subscription has expired.\n\n"
                "Please renew at 360heartsinthesky.com to continue.",
                QMessageBox.StandardButton.Ok,
            )

    # -------------------------------------------------------------------------
    # Sliding drawer toggles (compact mode only)
    # -------------------------------------------------------------------------

    def _toggle_side_drawer(self, side):
        """Toggle a group of side panels with slide animation."""
        if side == "left":
            panels = [self.vedanga_panel, self.varga_column]
            is_open = self._left_drawer_open
            # Close the other side first
            if self._right_drawer_open:
                self._close_drawer("right")
        else:
            panels = [self.right_scroll, self.vimshottari_panel]
            is_open = self._right_drawer_open
            if self._left_drawer_open:
                self._close_drawer("left")

        if is_open:
            self._close_drawer(side)
        else:
            self._open_drawer(side, panels)

    def _open_drawer(self, side, panels):
        """Slide panels in from the edge."""
        self._stop_all_anims()

        for panel in panels:
            target_w = self._panel_target_widths[panel]
            panel.setMinimumWidth(0)
            panel.setMaximumWidth(0)
            panel.setVisible(True)

            anim = QPropertyAnimation(panel, b"maximumWidth")
            anim.setStartValue(0)
            anim.setEndValue(target_w)
            anim.setDuration(self.DRAWER_ANIM_MS)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            # Restore fixed width when animation finishes
            anim.finished.connect(lambda p=panel, w=target_w: (
                p.setMinimumWidth(w), p.setMaximumWidth(w)
            ))
            anim.start()
            self._running_anims.append(anim)

        if side == "left":
            self._left_drawer_open = True
            self._left_toggle.setText("\u25c0")  # arrow points left = "close"
        else:
            self._right_drawer_open = True
            self._right_toggle.setText("\u25b6")  # arrow points right = "close"

    def _close_drawer(self, side):
        """Slide panels out toward the edge."""
        self._stop_all_anims()

        if side == "left":
            panels = [self.vedanga_panel, self.varga_column]
        else:
            panels = [self.right_scroll, self.vimshottari_panel]

        for panel in panels:
            current_w = self._panel_target_widths[panel]
            panel.setMinimumWidth(0)

            anim = QPropertyAnimation(panel, b"maximumWidth")
            anim.setStartValue(current_w)
            anim.setEndValue(0)
            anim.setDuration(self.DRAWER_ANIM_MS)
            anim.setEasingCurve(QEasingCurve.Type.InCubic)
            anim.finished.connect(lambda p=panel: p.setVisible(False))
            anim.start()
            self._running_anims.append(anim)

        if side == "left":
            self._left_drawer_open = False
            self._left_toggle.setText("\u25b6")
        else:
            self._right_drawer_open = False
            self._right_toggle.setText("\u25c0")

    def _stop_all_anims(self):
        """Stop all running drawer animations."""
        for anim in self._running_anims:
            anim.stop()
        self._running_anims.clear()

    # === DASHA NAVIGATION METHODS ===

    def _set_vedanga_level(self, level):
        """Set Vedanga dasha display level (1-5). Delegates to DashaManager."""
        self.dasha_manager.set_vedanga_level(level)

    def _set_vimshottari_level(self, level):
        """Set right panel dasha level. Routes to correct mode."""
        if getattr(self, 'right_dasha_mode', 'vimshottari') == 'nisarga':
            self.dasha_manager.set_nisarga_level(level)
        else:
            self.dasha_manager.set_vimshottari_level(level)

    def _navigate_vedanga_previous(self):
        """Navigate to previous 120-year Vedanga cycle. Delegates to DashaManager."""
        self.dasha_manager.navigate_vedanga_previous()

    def _navigate_vedanga_next(self):
        """Navigate to next 120-year Vedanga cycle. Delegates to DashaManager."""
        self.dasha_manager.navigate_vedanga_next()

    def _navigate_vimshottari_previous(self):
        """Navigate to previous 120-year Vimshottari cycle. Delegates to DashaManager."""
        self.dasha_manager.navigate_vimshottari_previous()

    def _navigate_vimshottari_next(self):
        """Navigate to next 120-year Vimshottari cycle. Delegates to DashaManager."""
        self.dasha_manager.navigate_vimshottari_next()

    def _on_vimshottari_clicked(self, item):
        """Handle click on Vimshottari dasha item. Delegates to DashaManager."""
        if getattr(self, 'right_dasha_mode', 'vimshottari') == 'nisarga':
            return
        self.dasha_manager.on_vimshottari_clicked(item)

    def _on_vedanga_clicked(self, item):
        """Handle click on Vedanga dasha item. Delegates to DashaManager."""
        self.dasha_manager.on_vedanga_clicked(item)

    def _on_vedanga_context_menu(self, pos):
        """Handle right-click on Vedanga dasha item. Delegates to DashaManager."""
        self.dasha_manager.show_dasha_context_menu(self.vedanga_list, pos, "vedanga")

    def _on_vimshottari_context_menu(self, pos):
        """Handle right-click on Vimshottari dasha item. Delegates to DashaManager."""
        self.dasha_manager.show_dasha_context_menu(self.vimshottari_list, pos, "vimshottari")

    def _extract_parent_chain_from_entry(self, entry, all_entries, entry_index):
        """Extract parent chain for dasha entry. Delegates to DashaManager."""
        return self.dasha_manager.extract_parent_chain_from_entry(entry, all_entries, entry_index)

    def _scroll_to_vedanga_row(self, row):
        """Scroll Vedanga list to row. Delegates to DashaManager."""
        self.dasha_manager.scroll_to_vedanga_row(row)

    def _scroll_to_vimshottari_row(self, row):
        """Scroll Vimshottari list to row. Delegates to DashaManager."""
        self.dasha_manager.scroll_to_vimshottari_row(row)

    def _update_cycle_label_vedanga(self):
        """Update Vedanga cycle label. Delegates to DashaManager."""
        self.dasha_manager.update_cycle_label_vedanga()

    def _update_cycle_label_vimshottari(self):
        """Update Vimshottari cycle label. Delegates to DashaManager."""
        self.dasha_manager.update_cycle_label_vimshottari()

    # === NISARGA DASHA (F7 toggle) ===

    def _cycle_right_dasha(self):
        """Cycle the right dasha panel between Vimshottari and Nisarga modes (F7)."""
        if self.right_dasha_mode == "vimshottari":
            self.right_dasha_mode = "nisarga"
            self._configure_right_panel_for_nisarga()
        else:
            self.right_dasha_mode = "vimshottari"
            self._configure_right_panel_for_vimshottari()
        from managers.settings_manager import get_settings
        get_settings().persist_runtime_change("dasha.right.mode", self.right_dasha_mode)

    def _configure_right_panel_for_nisarga(self):
        """Switch right panel UI to Nisarga mode."""
        # SPEC-THM-001 E5: get_theme_colors imported at module level.
        theme = get_theme_colors()

        # Title: show "Nisarga" instead of ayanamsa name
        self.vimshottari_title_btn.setText("Planetary Ages")
        self.vimshottari_title_btn.setToolTip("Natural Planetary Ages (F7 to switch back)")
        self.vimshottari_title_btn.setEnabled(False)  # No ayanamsa click in Planetary Ages

        # Hide nav arrows (no 120y cycling for fixed periods)
        self.vimshottari_nav_frame.setVisible(False)

        # Show all 5 level buttons (only 1-2 implemented for now)
        for btn in self.vimshottari_level_buttons:
            btn.setVisible(True)
        self.vimshottari_level_buttons[0].setChecked(True)

        # Reset Nisarga level and update
        self.dasha_level_nisarga = 1
        self.dasha_manager.update_nisarga_dasha()

        self.statusBar().showMessage("Right panel: Planetary Ages - F7 to switch back", 3000)

    def _configure_right_panel_for_vimshottari(self):
        """Restore right panel UI to Vimshottari mode."""
        # Restore title button
        self.dasha_manager._update_dasha_title("vimshottari")
        self.vimshottari_title_btn.setToolTip("Click to change ayanamsa")
        self.vimshottari_title_btn.setEnabled(True)

        # Show nav arrows
        self.vimshottari_nav_frame.setVisible(True)

        # Show all 5 level buttons
        for btn in self.vimshottari_level_buttons:
            btn.setVisible(True)
        # Reset to level 1
        self.vimshottari_level_buttons[0].setChecked(True)
        self.dasha_level_vimshottari = 1
        self.vimshottari_parent_chain = []

        # Clear maturation highlights (leftover from Nisarga)
        if hasattr(self, 'vimshottari_delegate'):
            self.vimshottari_delegate.update_maturation_highlights(set())

        # Update
        self.dasha_manager.update_vimshottari_dasha()

        self.statusBar().showMessage("Right panel: Vimshottari Dasha - F7 to switch", 3000)

    def _on_dasha_settings_changed(self):
        """Live-apply dasha ayanamsha settings changed in the Settings tab (td-qxbk.3).

        Copies the persisted dasha.* values into the runtime attrs and recomputes
        both dasha panels. Thin handler: delegates the recompute to dasha_manager
        and the existing right-panel configure helpers.
        """
        from managers.settings_manager import get_settings
        s = get_settings()

        # LEFT (Vedanga): always an ayanamsha
        self.vedanga_ayanamsa = s.get("dasha.left.ayanamsa_id", 100)
        self.nakshatra_coords = s.get("zodiac.nakshatra_coords", "neither")
        self.vedanga_dasha_data = None
        self.vedanga_parent_chain = []
        self.dasha_level_vedanga = 1
        self.dasha_manager._update_dasha_title("vedanga")
        self.dasha_manager.update_vedanga_dasha()

        # RIGHT (Vimshottari / Nisarga)
        new_mode = s.get("dasha.right.mode", "nisarga")
        self.vimshottari_ayanamsa = s.get("dasha.right.ayanamsa_id", 98)
        mode_changed = (new_mode != self.right_dasha_mode)
        self.right_dasha_mode = new_mode
        if mode_changed:
            # The configure helpers recompute the right panel for the new mode.
            if new_mode == "nisarga":
                self._configure_right_panel_for_nisarga()
            else:
                self._configure_right_panel_for_vimshottari()
        elif new_mode == "vimshottari":
            # Mode unchanged, only the ayanamsha changed: recompute Vimshottari.
            self.vimshottari_dasha_data = None
            self.vimshottari_parent_chain = []
            self.dasha_level_vimshottari = 1
            self.dasha_manager._update_dasha_title("vimshottari")
            self.dasha_manager.update_vimshottari_dasha()
        # Nisarga with unchanged mode: the ayanamsha is irrelevant (fixed ages),
        # so there is nothing to recompute.

    def _change_dasha_ayanamsa(self, panel):
        """Open ayanamsa selection dialog for a dasha panel and recalculate.
        Also handles the chart zodiac setting (tropical/sidereal)."""
        from apps.widgets.ayanamsa_dialog import AyanamsaDialog
        if panel == "vedanga":
            current_ayanamsa = self.vedanga_ayanamsa
        else:
            current_ayanamsa = self.vimshottari_ayanamsa

        dialog = AyanamsaDialog(self, current_ayanamsa=current_ayanamsa,
                                current_chart_zodiac=self.chart_zodiac)
        if dialog.exec():
            ayanamsa_id, chart_zodiac = dialog.get_selection()

            # Track whether chart zodiac changed
            chart_zodiac_changed = (chart_zodiac != self.chart_zodiac)
            ayanamsa_changed_for_chart = (
                chart_zodiac == "sidereal" and ayanamsa_id != self.chart_sidereal_ayanamsa_id
            )
            # pm-008: do NOT bypass a locked zodiac.mode via this dasha dialog.
            # If zodiac.mode is locked AND the dialog tried to change chart_zodiac,
            # skip the chart-zodiac mutation entirely (dasha persist below still runs).
            from managers.settings_manager import get_settings
            if not (chart_zodiac_changed and get_settings().is_locked("zodiac.mode")):
                self.chart_zodiac = chart_zodiac
                if chart_zodiac == "sidereal":
                    self.chart_sidereal_ayanamsa_id = ayanamsa_id
                    self._compute_chart_ayanamsa_offset()
                    get_settings().persist_runtime_change("zodiac.ayanamsa_id", ayanamsa_id)

            if panel == "vedanga":
                self.vedanga_ayanamsa = ayanamsa_id
                # pm-003: persist dasha LEFT group under the single LEFT lock key.
                if not get_settings().is_locked("dasha.left.ayanamsa_id"):
                    s = get_settings()
                    s.set("dasha.left.ayanamsa_id", ayanamsa_id)
                self.vedanga_dasha_data = None
                self.vedanga_parent_chain = []
                self.dasha_level_vedanga = 1
                self.dasha_cycle_offset_vedanga = 0
                self.dasha_manager.update_cycle_label_vedanga()
                for i, btn in enumerate(self.vedanga_level_buttons):
                    btn.setChecked(i == 0)
                self.dasha_manager._update_dasha_title("vedanga")
                self.dasha_manager.update_vedanga_dasha()
            else:
                self.vimshottari_ayanamsa = ayanamsa_id
                # pm-003: persist dasha RIGHT group under the single RIGHT lock key.
                if not get_settings().is_locked("dasha.right.ayanamsa_id"):
                    s = get_settings()
                    s.set("dasha.right.ayanamsa_id", ayanamsa_id)
                self.vimshottari_dasha_data = None
                self.vimshottari_parent_chain = []
                self.dasha_level_vimshottari = 1
                self.dasha_cycle_offset_vimshottari = 0
                self.dasha_manager.update_cycle_label_vimshottari()
                for i, btn in enumerate(self.vimshottari_level_buttons):
                    btn.setChecked(i == 0)
                self.dasha_manager._update_dasha_title("vimshottari")
                self.dasha_manager.update_vimshottari_dasha()

            # CRITICAL: When chart zodiac changes, ALWAYS switch aditya_mode
            # This fixes the 30° bug: previously only handled classic→sidereal,
            # missing the zodiac→sidereal case (default mode!)
            if chart_zodiac_changed or ayanamsa_changed_for_chart:
                from state.events import SetZodiacMode
                if chart_zodiac == "sidereal":
                    self.state.dispatch(SetZodiacMode(mode="sidereal"))
                elif chart_zodiac == "tropical" and self.state.aditya_mode == "sidereal":
                    self.state.dispatch(SetZodiacMode(mode="tropical_classic"))
                self._update_toggle_button_styles()
                self._recalculate_chart()
                from core.ayanamsa_data import get_ayanamsa_name
                if chart_zodiac == "sidereal":
                    ayan_name = get_ayanamsa_name(self.chart_sidereal_ayanamsa_id)
                    self.statusBar().showMessage(
                        f"Chart: Sidereal ({ayan_name}, offset {self.chart_ayanamsa_offset:.2f}°)")
                else:
                    self.statusBar().showMessage("Chart: Tropical")

    # === PANEL UPDATE METHODS ===

    def _populate_dasha_after_startup(self):
        """Populate both dasha panels after session restore."""
        self._update_vedanga_dasha()
        self._update_vimshottari_dasha()

    def _update_vedanga_dasha(self):
        """Update Vedanga dasha list. Delegates to DashaManager."""
        self.dasha_manager.update_vedanga_dasha()

    def _update_vimshottari_dasha(self):
        """Update right dasha panel. Routes to correct mode (Vimshottari or Nisarga)."""
        mode = getattr(self, 'right_dasha_mode', 'vimshottari')
        if mode == 'nisarga':
            self.dasha_manager.update_nisarga_dasha()
        else:
            self.dasha_manager.update_vimshottari_dasha()

    def _get_sign_ruler(self, sign):
        """Get sign ruler. Phase 4 W5: now uses core.sidereal_helpers directly
        (was delegating through panel_manager before W5 cleanup)."""
        from core.sidereal_helpers import get_sign_ruler
        return get_sign_ruler(sign)

    def _update_nakshatra(self):
        """Update Nakshatra wheel panel with current chart data."""
        if hasattr(self, 'nakshatra_panel') and self.state.active_chart:
            self.nakshatra_panel.update_from_chart(self.state.active_chart, aditya_mode=self.state.aditya_mode)

    def _update_antikythera(self):
        """Update Antikythera map panel with current chart data."""
        if hasattr(self, 'antikythera_panel') and self.state.active_chart:
            self.antikythera_panel.update_from_chart(self.state.active_chart, aditya_mode=self.state.aditya_mode)

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
        current_tab = self.tab_widget.currentWidget()
        for attr in ('nakshatra_panel', 'antikythera_panel'):
            panel = getattr(self, attr, None)
            if panel is None:
                continue
            if current_tab is panel:
                panel.update_from_chart(self.state.active_chart, aditya_mode=self.state.aditya_mode)
                panel._chart_dirty = False
            else:
                panel._chart_dirty = True

    # === FILE OPERATIONS ===

    def _open_file_dialog(self):
        """Show file dialog to open CHTK file. Delegates to ChartManager."""
        self.chart_manager.open_file_dialog()

    def _show_new_chart(self):
        """Switch to Edit Chart tab and select New Chart sub-tab."""
        # Find the Edit Chart tab
        for i in range(self.tab_widget.count()):
            tab_text = self.tab_widget.tabText(i)
            if "Edit Chart" in tab_text:
                self.tab_widget.setCurrentIndex(i)
                break

        # Select New Chart sub-tab (index 1)
        if hasattr(self, 'edit_chart_panel') and self.edit_chart_panel:
            self.edit_chart_panel.sidebar.setCurrentRow(1)

    def _show_edit_chart(self):
        """Switch to Edit Chart tab and select Edit Info sub-tab."""
        # Find the Edit Chart tab
        for i in range(self.tab_widget.count()):
            tab_text = self.tab_widget.tabText(i)
            if "Edit Chart" in tab_text:
                self.tab_widget.setCurrentIndex(i)
                break

        # Select Edit Info sub-tab (index 0)
        if hasattr(self, 'edit_chart_panel') and self.edit_chart_panel:
            self.edit_chart_panel.sidebar.setCurrentRow(0)

    def _reload_current(self):
        """Reload the currently loaded chart. Delegates to ChartManager."""
        self.chart_manager.reload_current()

    def _save_as_chtk(self):
        """Save current chart as CHTK file. Delegates to CHTKWriter.

        Uses recipe as primary source when available, with fallback to
        current_chart_data and current_birth_data for legacy entries.
        """
        if not self.current_chart_data:
            QMessageBox.warning(self, "No Chart", "No chart loaded to save.")
            return

        _active = self.state.active_chart
        _active_jd = _active.context.timeJD.jd if _active else None
        if (self.birth_jd is not None and _active_jd is not None
                and abs(_active_jd - self.birth_jd) > 0.0001
                and not getattr(self, 'is_human_design', False)):
            QMessageBox.warning(self, "Transit Chart",
                                "Cannot save a transit/Now chart as CHTK.\n"
                                "Load a natal chart first.")
            return

        _recipe = None
        if hasattr(self, 'memory_panel') and self.memory_panel:
            _idx = self.memory_panel.current_index
            if 0 <= _idx < len(self.memory_panel.charts):
                _recipe = self.memory_panel.charts[_idx].get('recipe')

        chart = self.current_chart_data
        bm = {}
        bd = getattr(self, 'current_birth_data', None) or {}

        # Helper: first non-empty/non-zero value from multiple sources
        def pick(keys_sources, default=''):
            """Try (key, source) pairs, return first truthy value."""
            for key, src in keys_sources:
                val = src.get(key) if isinstance(src, dict) else None
                if val is not None and val != '' and val != 0 and val != 'Unknown':
                    return val
            return default

        name = (_recipe.get('name') if _recipe else None) or chart.get('name') or bd.get('name') or 'chart'
        safe_name = "".join(c for c in name if c.isalnum() or c in " -_").strip()
        suggested = f"{safe_name}.chtk" if safe_name else "chart.chtk"

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save As CHTK", suggested,
            "CHTK Files (*.chtk);;All Files (*)"
        )
        if not file_path:
            return

        try:
            from core.chtk_reader import CHTKWriter

            if _recipe:
                lat = _recipe.get('lat', 0)
                lon = _recipe.get('lon', 0)
                country = _recipe.get('country', 'Unknown')
                city = _recipe.get('city', 'Unknown')
                gender = _recipe.get('gender', 'Unknown')
                tz = _recipe.get('timezone', 'UTC')
                tcf = _recipe.get('time_change_flag', 0)
            else:
                chart_coords = chart.get('coordinates', {})
                chart_location = chart.get('location', {})
                bm_coords = bm.get('coordinates', {})

                lat = pick([
                    ('latitude', chart), ('latitude', chart_coords),
                    ('latitude', chart_location),
                    ('latitude', bm), ('latitude', bm_coords), ('latitude', bd),
                ], default=0)
                lon = pick([
                    ('longitude', chart), ('longitude', chart_coords),
                    ('longitude', chart_location),
                    ('longitude', bm), ('longitude', bm_coords), ('longitude', bd),
                ], default=0)

                country = pick([
                    ('country', chart), ('country', chart_location),
                    ('country', bm), ('country', bd),
                ], default='Unknown')
                city = pick([
                    ('city', chart), ('city', chart_location),
                    ('city', bm), ('city', bd),
                ], default='Unknown')

                gender = pick([
                    ('gender', chart), ('gender', bm), ('gender', bd),
                ], default='Unknown')

                tz = getattr(self, 'current_timezone', None)
                if not tz or tz == 'UTC':
                    tz = pick([
                        ('timezone', chart), ('timezone', bm),
                        ('iana_timezone', bd), ('chtk_timezone', bd),
                    ], default='UTC')

                tcf = chart.get('time_change_flag', bm.get('time_change_flag',
                        bd.get('time_change_flag', 0)))

            if _recipe:
                from core.chart_factory import timedec_to_hms
                _h, _m, _s = timedec_to_hms(_recipe['timedec'])
                metadata = {
                    'name': name,
                    'year': _recipe['year'],
                    'month': _recipe['month'],
                    'day': _recipe['day'],
                    'hour': _h,
                    'minute': _m,
                    'second': _s,
                    'gender': gender,
                    'country': country,
                    'city': city,
                    'timezone': _recipe.get('timezone', 'UTC'),
                    'time_change_flag': tcf,
                    'coordinates': {
                        'latitude': lat,
                        'longitude': lon,
                    },
                }
            else:
                metadata = {
                    'name': name,
                    'year': chart['year'] if 'year' in chart else (bm['year'] if 'year' in bm else bd.get('local_year', 1900)),
                    'month': chart['month'] if 'month' in chart else (bm['month'] if 'month' in bm else bd.get('local_month', 1)),
                    'day': chart['day'] if 'day' in chart else (bm['day'] if 'day' in bm else bd.get('local_day', 1)),
                    'hour': chart.get('hour', bm.get('hour', bd.get('local_hour', 0))),
                    'minute': chart.get('minute', bm.get('minute', bd.get('local_minute', 0))),
                    'second': chart.get('second', bm.get('second', bd.get('local_second', 0))),
                    'gender': gender,
                    'country': country,
                    'city': city,
                    'timezone': tz,
                    'time_change_flag': tcf,
                    'coordinates': {
                        'latitude': lat,
                        'longitude': lon,
                    },
                }

            writer = CHTKWriter()
            writer.save_chtk_file(metadata, name=name, output_path=file_path)

            self.statusBar().showMessage(f"Saved: {file_path}")

        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save CHTK:\n{e}")
            import traceback
            traceback.print_exc()

    def _show_manual(self):
        """Open the help manual dialog (singleton — only one instance at a time)."""
        if hasattr(self, '_help_dialog') and self._help_dialog is not None:
            self._help_dialog.raise_()
            self._help_dialog.activateWindow()
            return
        from apps.widgets.help_dialog import HelpDialog
        self._help_dialog = HelpDialog(parent=self)
        self._help_dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._help_dialog.destroyed.connect(lambda: setattr(self, '_help_dialog', None))
        self._help_dialog.show()

    def _show_about(self):
        """Show about dialog."""
        QMessageBox.about(
            self,
            "About Varuna 360",
            "<h2>Varuna 360</h2>"
            "<p><b>Tropical Vedic Astrology</b></p>"
            "<p>Version: 1.0</p>"
            "<p>A professional astrology chart calculator combining the "
            "Aditya Circle system with Tropical Western astrology, "
            "powered by Swiss Ephemeris calculations.</p>"
            "<p>Default settings follow Ernst Wilhelm's Tropical Vedic approach. "
            "Classic Western options are also available.</p>"
            "<p><i>&copy; 2024-2026 Lorris Turpin / 360 Hearts in the Sky</i></p>"
            "<p>License: AGPL-3.0</p>"
        )

    def _show_about_pro(self):
        """Show the About-Varuna360-Pro static marketing dialog.

        This is the SINGLE point of Pro awareness in the Core GUI. All
        content is read from core/pro_marketing.py — pure constants, no
        runtime detection of whether Pro is installed. The dialog renders
        the same content regardless of whether the user has Pro or not.
        """
        from core.pro_marketing import (
            PRO_UPGRADE_URL,
            PRO_TAGLINE,
            PRO_DESCRIPTION,
            PRO_FEATURES,
            PRO_PRICE_DISPLAY,
        )

        feature_list_html = "".join(
            f"<li>{feature}</li>" for feature in PRO_FEATURES
        )

        # Use QMessageBox.about() so the dialog gets the standard "info"
        # styling, supports rich-text rendering of HTML, and exposes the
        # URL as a clickable link via Qt's automatic <a href> handling.
        QMessageBox.about(
            self,
            "About Varuna 360 Pro",
            f"<h2>Varuna 360 Pro</h2>"
            f"<p><b>{PRO_TAGLINE}</b></p>"
            f"<p>{PRO_DESCRIPTION}</p>"
            f"<h3>Pro features</h3>"
            f"<ul>{feature_list_html}</ul>"
            f"<p><b>Pricing:</b> {PRO_PRICE_DISPLAY}</p>"
            f'<p><a href="{PRO_UPGRADE_URL}">{PRO_UPGRADE_URL}</a></p>'
            f"<p><i>Varuna 360 Core is and remains open-source under AGPL-3.0. "
            f"Pro is an optional proprietary upgrade for users who want the "
            f"additional research tooling.</i></p>"
        )

    # ──────────────────────────────────────────────────────────────────
    # Account menu handlers (top-level Account menu — sibling of Help)
    # ──────────────────────────────────────────────────────────────────

    def _show_sign_in_dialog(self):
        """Open the login dialog on user request from the Account menu.

        Varuna360 Core runs anonymously by default — main() skips the
        login flow unless VARUNA360_BUNDLED=1 is set. This handler lets
        anonymous users explicitly sign in at any time from the menu
        (to attach a website tier that matches their subscription).

        If sign-in succeeds, the resulting LicenseState is stashed on
        the window so the periodic refresh worker picks it up. If the
        user closes the dialog (reject / continue without account),
        nothing changes and the anonymous state persists.
        """
        from apps.widgets.login_dialog import LoginDialog
        dialog = LoginDialog(parent=self)
        if dialog.exec() == LoginDialog.DialogCode.Accepted:
            self._license_state = dialog.get_license_state()

    def _open_subscribe_page(self):
        """Open the subscription page in the default browser."""
        import webbrowser
        from core.pro_marketing import PRO_UPGRADE_URL
        webbrowser.open(PRO_UPGRADE_URL)

    def _show_tier_dialog(self):
        """Open the three-tier comparison dialog (singleton, non-modal)."""
        if hasattr(self, '_tier_dialog') and self._tier_dialog is not None:
            self._tier_dialog.raise_()
            self._tier_dialog.activateWindow()
            return
        from apps.widgets.tier_dialog import TierDialog
        self._tier_dialog = TierDialog(parent=self)
        self._tier_dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._tier_dialog.destroyed.connect(
            lambda: setattr(self, '_tier_dialog', None)
        )
        self._tier_dialog.show()

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
                    ayanamsa=getattr(self, 'vedanga_ayanamsa', 100),
                    tz_offset_hours=params['tz_offset'],
                    moon_jd_override=params['moon_jd_override'],
                    nak_mode=getattr(self, 'nakshatra_coords', 'neither'),
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
        cot_order = _sm.get("cot.planet_order", "vedic")

        dialog = PlanetPlacementsDialog(
            parent=self,
            chart=chart,
            aditya_mode=self.state.aditya_mode,
            chart_data=self.current_chart_data,
            person_name=person_name,
            use_western_names=self.use_western_names,
            nakshatra_ayanamsa_id=getattr(self, 'vedanga_ayanamsa', 100),
            current_dasha_chain=dasha_chain,
            cot_planet_order=cot_order,
        )
        dialog.show()

    def _set_sign_language(self, language: str):
        """Set the language for Western sign names."""
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

    def _show_planet_dialog(self, planet_name, planet_info):
        """Show popup dialog with planet details when planet is double-clicked"""
        planet_pixmap = self.chart_view.load_planet_image(planet_name, size=64)
        current_variation = self.chart_view.get_planet_variation(planet_name)
        dialog = PlanetInfoDialog(planet_name, planet_info, planet_pixmap,
                                  current_variation=current_variation, parent=self)

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
        """Show popup dialog with hora/trimsamsa structure when sector is double-clicked"""
        avastha_summary = self._compute_sector_avastha(sign_name, ring, being_type)
        dialog = SectorInfoDialog(sign_name, focus_ring=ring, focus_type=being_type,
                                  avastha_summary=avastha_summary, parent=self)
        dialog.exec()

        dialog.deleteLater()
        dialog = None

        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()

        self._reset_all_views_drag_state()

    def _compute_sector_avastha(self, sign_name, ring, being_type):
        """Compute uplifted/afflicted totals for planets in a specific sector.
        Only planets whose retinue data matches both the sign AND the clicked
        sector (hora side or trimsamsa being type) are included."""
        chart = getattr(self.state, 'active_chart', None)
        if not chart:
            return None
        try:
            from AI_tools.AI_main_function.retinue import get_chart_retinue
            from AI_tools.AI_main_function.avastha import get_drishti_yuti_data
            from apps.widgets.info_panel_dialog import split_expression, _AVASTHA_7

            aditya_mode = self.state.aditya_mode
            ayanamsa_offset = 0.0
            if aditya_mode == 'sidereal':
                ayanamsa_offset = getattr(self, 'chart_ayanamsa_offset', 0.0)
            retinue = get_chart_retinue(
                chart, ayanamsa_offset=ayanamsa_offset,
                tropical_mode=(aditya_mode == 'tropical_classic'))

            targets = []
            for p in retinue["planets"]:
                if p["aditya_sign"] != sign_name:
                    continue
                pname = p["planet"]
                if pname not in _AVASTHA_7:
                    continue
                if ring == "hora":
                    side = p.get("hora", {}).get("side", "")
                    if side == "Aditya":
                        key = "aditya"
                    elif side == "Naga":
                        key = "naga"
                    else:
                        continue
                    if key != being_type.lower():
                        continue
                elif ring == "trimsamsa":
                    ttype = p.get("trimsamsa", {}).get("being_type", "")
                    if ttype.lower() != being_type.lower():
                        continue
                targets.append(pname)

            if not targets:
                return None

            data = get_drishti_yuti_data(chart)
            up_total = 0.0
            aff_total = 0.0
            for t in targets:
                u, a = split_expression(
                    t, _AVASTHA_7, data["matrix"],
                    data["dignity_data"], data.get("shame_pairs", set()))
                up_total += u
                aff_total += a

            label = ", ".join(targets)
            return {"planet": label, "target": label,
                    "uplifted": up_total, "afflicted": aff_total,
                    "total": up_total + aff_total}
        except Exception:
            import traceback
            traceback.print_exc()
            return None

    def _apply_planet_variation(self, planet_name, variation_num):
        """Apply the selected planet icon variation to the chart"""
        self.chart_view.set_planet_variation(planet_name, variation_num)
        self.statusBar().showMessage(f"{planet_name} icon changed to variation {variation_num}")

    def _show_sign_variation_dialog(self, zodiac_index, current_variation):
        """Show popup dialog for selecting zodiac sign icon variation"""
        dialog = SignVariationDialog(zodiac_index, current_variation, parent=self)

        # Don't connect signal - we'll check for pending variation after dialog closes
        # This prevents race condition: dialog closing + chart redrawing simultaneously

        result = dialog.exec()

        # Check if user applied a variation (stored instead of emitted)
        pending_variation = None
        if hasattr(dialog, '_pending_variation') and dialog._pending_variation:
            pending_variation = dialog._pending_variation

        # CRITICAL: Delete dialog BEFORE chart redraw to ensure complete cleanup
        dialog.deleteLater()
        dialog = None

        # Process deletion event (use global singleton, not local import)
        QApplication.instance().processEvents()

        # Reset drag state on ALL views after dialog closes to prevent "stuck pan mode"
        self._reset_all_views_drag_state()

        # NOW apply variation (dialog is fully destroyed)
        if pending_variation:
            zodiac_idx, var_num = pending_variation
            self._apply_sign_variation(zodiac_idx, var_num)

    def _apply_sign_variation(self, zodiac_index, variation_num):
        """Apply the selected variation to the chart"""
        self.chart_view.set_selected_variation(zodiac_index, variation_num)
        western_name = self.chart_view.WESTERN_NAMES[zodiac_index]
        self.statusBar().showMessage(f"{western_name} icon changed to variation {variation_num}")
        QApplication.instance().processEvents()

    def _reset_all_views_drag_state(self):
        """Reset drag state on all chart views to prevent 'stuck pan mode' after dialogs."""
        from PySide6.QtWidgets import QGraphicsView
        for view_name in ('chart_view', 'wheel_view', 'north_indian_view'):
            view = getattr(self, view_name, None)
            if view and hasattr(view, '_is_dragging'):
                view._is_dragging = False
                view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
                view.viewport().setCursor(Qt.CursorShape.ArrowCursor)

    def _toggle_wheel_view(self):
        """
        Cycle between South Indian, Wheel, and North Indian views.

        Connected to the view toggle button in the chart title bar.
        Cycles: South Indian (0) → Wheel (1) → North Indian (2) → South Indian (0)
        """
        current_index = self.chart_stack.currentIndex()

        # Theme-adaptive button styles — SPEC-THM-001 E5: use module-level import.
        _t = get_theme_colors()
        active_style = """
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                font-size: {scaled_px(12)}px;
                border: none;
                border-radius: 8px;
                padding: 8px 12px;
            }
            QPushButton:hover {
                background-color: #45A049;
            }
        """
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

        if current_index == 0:
            # South Indian → Wheel
            self.chart_stack.setCurrentIndex(1)
            from state.events import SetChartViewStyle
            self.state.dispatch(SetChartViewStyle(style="wheel"))

            if hasattr(self, 'wheel_btn'):
                self.wheel_btn.setText("◇ North")
                self.wheel_btn.setStyleSheet(active_style)

            # Show wheel-only buttons and sync their text
            if hasattr(self, 'dual_rim_btn'):
                self.dual_rim_btn.setVisible(True)
                self._sync_dual_rim_button_text()
            if hasattr(self, 'transit_btn'):
                self.transit_btn.setVisible(True)

            # Update wheel view with current data
            # Chart-Everywhere Issue 2c: prefer state.active_chart when available.
            if self.state.active_chart is not None:
                ayanamsa_off = self.chart_ayanamsa_offset if self.state.aditya_mode == "sidereal" else 0.0
                self.wheel_view.update_from_chart(self.state.active_chart,
                                                   use_western_names=getattr(self, 'use_western_names', False),
                                                   ayanamsa_offset=ayanamsa_off,
                                                   aditya_mode=self.state.aditya_mode)
                self.wheel_view.ensure_visible()

            if hasattr(self, 'transit_overlay_manager') \
                    and self.transit_overlay_manager.transit_enabled:
                self.wheel_view.update_transit_from_manager(
                    self.transit_overlay_manager)

            self.statusBar().showMessage("Switched to Wheel view")

        elif current_index == 1:
            # Wheel → North Indian
            self.chart_stack.setCurrentIndex(2)
            from state.events import SetChartViewStyle
            self.state.dispatch(SetChartViewStyle(style="north_indian"))

            if hasattr(self, 'wheel_btn'):
                self.wheel_btn.setText("▣ South")
                self.wheel_btn.setStyleSheet(active_style)

            # Hide wheel-only buttons (transit stays visible on all views)
            if hasattr(self, 'dual_rim_btn'):
                self.dual_rim_btn.setVisible(False)

            # Update north indian view with current data
            # Chart-Everywhere Issue 2c: prefer state.active_chart when available.
            if self.state.active_chart is not None:
                ayanamsa_off = self.chart_ayanamsa_offset if self.state.aditya_mode == "sidereal" else 0.0
                self.north_indian_view.update_from_chart(self.state.active_chart,
                                                          use_western_names=getattr(self, 'use_western_names', False),
                                                          ayanamsa_offset=ayanamsa_off,
                                                          aditya_mode=self.state.aditya_mode)
                self.north_indian_view.ensure_visible()

            if hasattr(self, 'transit_overlay_manager') \
                    and self.transit_overlay_manager.transit_enabled:
                self.north_indian_view.update_transit_overlay(
                    self.transit_overlay_manager)

            self.statusBar().showMessage("Switched to North Indian view")

        else:
            # North Indian → South Indian
            self.chart_stack.setCurrentIndex(0)
            from state.events import SetChartViewStyle
            self.state.dispatch(SetChartViewStyle(style="south_indian"))

            if hasattr(self, 'wheel_btn'):
                self.wheel_btn.setText("◎ Wheel")
                self.wheel_btn.setStyleSheet(inactive_style)

            # Hide wheel-only buttons (transit stays visible on all views)
            if hasattr(self, 'dual_rim_btn'):
                self.dual_rim_btn.setVisible(False)

            if hasattr(self, 'transit_overlay_manager') \
                    and self.transit_overlay_manager.transit_enabled \
                    and hasattr(self, 'chart_view') and self.chart_view:
                self.chart_view.update_transit_overlay(
                    self.transit_overlay_manager)

            self.statusBar().showMessage("Switched to South Indian view")

        # Persist chart view preference so it survives app restart (respects lock)
        if not getattr(self, '_suppress_view_persist', False):
            from managers.settings_manager import get_settings
            get_settings().persist_runtime_change("chart.view_type", self.state.chart_view_style)

        # Re-apply compact styles if in compact mode (prevents stomped buttons)
        self._reapply_compact_if_needed()

        if self.time_adjust_widget and hasattr(self.time_adjust_widget, 'update_save_button_state'):
            self.time_adjust_widget.update_save_button_state()

    def _switch_to_chart_index(self, target_index: int):
        """Switch chart view to a specific index: 0=South Indian, 1=Wheel, 2=North Indian."""
        current = self.chart_stack.currentIndex()
        if current == target_index:
            return
        self._suppress_view_persist = True
        try:
            while self.chart_stack.currentIndex() != target_index:
                self._toggle_wheel_view()
        finally:
            self._suppress_view_persist = False
        from managers.settings_manager import get_settings
        get_settings().persist_runtime_change("chart.view_type", self.state.chart_view_style)

    def _save_setting(self, key: str, value):
        """Save a single key to settings.json via PrefsStore (atomic write)."""
        if hasattr(self, "prefs_store"):
            self.prefs_store.update(key, value)

    def _load_setting(self, key: str, default=None):
        """Load a single key from settings.json via PrefsStore."""
        if hasattr(self, "prefs_store"):
            return self.prefs_store.get(key, default)
        return default

    def _cycle_chart_view(self):
        """
        Cycle chart view globally (F2 shortcut).

        Delegates to _toggle_wheel_view() for main chart cycling,
        then syncs the Eclipse panel's Personal Eclipse views.
        """
        # Cycle the main chart view
        self._toggle_wheel_view()

        # Sync Eclipse panel if it exists
        if hasattr(self, 'eclipse_panel') and self.eclipse_panel:
            self.eclipse_panel.sync_chart_view(self.state.chart_view_style)

        # Sync Transit panel if it exists
        if hasattr(self, 'transit_panel') and self.transit_panel:
            self.transit_panel.sync_chart_view(self.state.chart_view_style)

        # Sync Exploration panel if it exists
        if hasattr(self, 'exploration_panel') and self.exploration_panel:
            self.exploration_panel.sync_chart_view(self.state.chart_view_style)

        # Sync Solar Return page if it exists
        if hasattr(self, 'solar_return_page') and self.solar_return_page:
            self.solar_return_page.sync_chart_view(self.state.chart_view_style)

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

    def _update_all_chart_views(self, *, skip_loading=False):
        """Update all chart views from state.active_chart."""
        self._sync_dual_rim_button_text()
        use_western = getattr(self, 'use_western_names', False)
        if not skip_loading:
            self.loading_manager.start("Updating chart...")

        chart = self.state.active_chart
        if chart is None:
            if not skip_loading:
                self.loading_manager.finish()
            return

        if hasattr(self, 'chart_view') and self.chart_view:
            self.chart_view.update_from_chart(chart, use_western_names=use_western, aditya_mode=self.state.aditya_mode)
        if hasattr(self, 'wheel_view') and self.wheel_view:
            self.wheel_view.update_from_chart(chart, use_western_names=use_western, aditya_mode=self.state.aditya_mode)
        if hasattr(self, 'north_indian_view') and self.north_indian_view:
            self.north_indian_view.update_from_chart(chart, use_western_names=use_western, aditya_mode=self.state.aditya_mode)

        if not skip_loading:
            self.loading_manager.update("Updating panels...")
        self._update_all_panels()

        if not skip_loading:
            self.loading_manager.finish()

        # Force viewport refresh on all views to ensure chart displays
        if hasattr(self, 'chart_view') and self.chart_view:
            self.chart_view.ensure_visible()
        if hasattr(self, 'wheel_view') and self.wheel_view:
            self.wheel_view.ensure_visible()
        if hasattr(self, 'north_indian_view') and self.north_indian_view:
            self.north_indian_view.ensure_visible()

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
                    mode=self.state.aditya_mode, utcoffset=_utc_off,
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
            if hasattr(self, 'chart_title_label'):
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
        if hasattr(self, 'chart_title_label'):
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

    def _refresh_chart_display(self):
        """
        Refresh chart display without recalculating planetary positions.
        Used when toggling sign name display (Aditya vs Western names).
        Only redraws visuals - no ephemeris calculation needed.
        """
        if not self.state.active_chart:
            print("[WARNING] No chart loaded, cannot refresh display")
            return

        # Refresh all chart views with current data
        self._update_all_chart_views()

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
        """
        Switch between Aditya Circle, Tropical Classic, and Sidereal modes.
        When already in current mode, toggles between Aditya and Western sign names.

        Args:
            mode: "aditya" for Aditya Circle, "tropical_classic" for Tropical Classic,
                  "sidereal" for Sidereal
        """
        # When chart_zodiac is "sidereal", the classic button triggers sidereal instead
        if mode == "tropical_classic" and self.chart_zodiac == "sidereal":
            mode = "sidereal"

        if self.state.aditya_mode == mode:
            # Already in this mode. SPEC-MODE-001: in Beginner the alternative
            # name set is unreachable, so clicking the active button is a no-op
            # (no toggle, no aditya_mode_changed signal, status bar unchanged).
            if self._is_beginner_mode():
                return
            # Advanced: toggle alternate names (existing behavior).
            self.use_western_names = not self.use_western_names
            # Route the runtime flip through persist_runtime_change so a locked
            # zodiac.use_western_names is honored (SPEC-SET-002 section 5.4).
            from managers.settings_manager import get_settings
            get_settings().persist_runtime_change("zodiac.use_western_names", self.use_western_names)
            if self.use_western_names:
                name_type = "Western"
            elif mode == "tropical_classic":
                name_type = "Aditya Classic"
            else:
                name_type = "Aditya"
            self._update_toggle_button_styles()
            self._refresh_chart_display()
            self.aditya_mode_changed.emit(self.state.aditya_mode)

            hd_label = " (Human Design)" if self.is_human_design else ""
            if mode == "sidereal":
                mode_label = "Sidereal"
            elif mode == "aditya":
                mode_label = "Aditya Circle"
            else:
                mode_label = "Tropical Classic"
            self.statusBar().showMessage(f"{mode_label} - {name_type} names{hd_label}")
            return

        from state.events import SetZodiacMode
        self.state.dispatch(SetZodiacMode(mode=mode))

        # Keep chart_zodiac in sync with mode
        if mode == "sidereal":
            self.chart_zodiac = "sidereal"
            self._compute_chart_ayanamsa_offset()
        elif self.chart_zodiac == "sidereal":
            self.chart_zodiac = "tropical"
            if hasattr(self, 'sidereal_action'):
                self.sidereal_action.setChecked(False)

        # Update dual rim button text to reflect complementary system
        self._sync_dual_rim_button_text()

        # Default: Aditya names for Aditya mode, Western names for TC/Sidereal
        self.use_western_names = (mode != "aditya")

        # Recalculate chart (respects is_human_design)
        self._recalculate_chart()

        # Notify all panels of mode change
        self.aditya_mode_changed.emit(mode)

        if mode == "sidereal":
            mode_label = "Sidereal"
        elif mode == "aditya":
            mode_label = "Aditya Circle"
        else:
            mode_label = "Tropical Classic"
        hd_label = " (Human Design)" if self.is_human_design else ""
        self.statusBar().showMessage(f"Switched to {mode_label}{hd_label} mode")

        # Persist zodiac mode and name preference (respects lock)
        from managers.settings_manager import get_settings
        get_settings().persist_runtime_change("zodiac.mode", mode)
        get_settings().persist_runtime_change("zodiac.use_western_names", self.use_western_names)

    def _on_names_changed(self, use_western: bool):
        """Handle sign name toggle from settings panel."""
        # SPEC-MODE-001 (path #2): Beginner cannot show the alternative label set.
        # Force the native default for the active system, whatever was emitted.
        if self._is_beginner_mode():
            use_western = (self.state.aditya_mode != "aditya")
        if self.use_western_names == use_western:
            return
        self.use_western_names = use_western
        from managers.settings_manager import get_settings
        get_settings().persist_runtime_change("zodiac.use_western_names", use_western)
        self._refresh_chart_display()
        # Notify pure relabel-panels (e.g. Find Chart) so their dropdowns and
        # results re-render with the new naming. Use the lightweight
        # sign_names_changed signal, NOT aditya_mode_changed: the zodiac system did
        # not change, so we must not trigger the heavy aditya_mode_changed slots
        # that recompute charts (solar_return_page) or reset filters (birth_finder).
        self.sign_names_changed.emit(self.state.aditya_mode)
        name_type = "Western" if use_western else "Aditya"
        self.statusBar().showMessage(f"Sign names: {name_type}")

    def _on_ayanamsa_changed(self, ayanamsa_id: int):
        """Handle ayanamsa change from settings panel. Same logic as the ayanamsa dialog."""
        self.chart_sidereal_ayanamsa_id = ayanamsa_id
        if self.chart_zodiac == "sidereal" or self.state.aditya_mode == "sidereal":
            self._compute_chart_ayanamsa_offset()
            self._recalculate_chart()
            from core.ayanamsa_data import get_ayanamsa_name
            ayan_name = get_ayanamsa_name(ayanamsa_id)
            self.statusBar().showMessage(
                f"Ayanamsa changed: {ayan_name} (offset {self.chart_ayanamsa_offset:.2f})")
        else:
            from core.ayanamsa_data import get_ayanamsa_name
            ayan_name = get_ayanamsa_name(ayanamsa_id)
            self.statusBar().showMessage(
                f"Ayanamsa set to {ayan_name} (applies when switching to Sidereal)")

    def _on_house_system_changed(self, house_system: str):
        """Live-apply a house system change from the settings panel (SPEC-HSY-001).

        Mirrors _on_ayanamsa_changed: update ChartState, then rebuild the active
        chart so cusps, wheel labels, and Digbala follow the new system at once.
        Persistence already happened in the settings card's s.set() call.
        """
        from state.events import SetHouseSystem
        try:
            self.state.dispatch(SetHouseSystem(house_system=house_system))
        except ValueError:
            return  # unrecognized key — ignore
        # Guard on active_chart, NOT birth_jd: a "Now"/synthetic chart has an
        # active_chart but leaves birth_jd None, and must still rebuild.
        if self.state.active_chart is not None:
            self._recalculate_chart()
        label = house_system.replace("_", " ").title()
        self.statusBar().showMessage(f"House system: {label}")

    def _on_house_display_mode_changed(self, mode):
        # Target the wheel directly (SPEC-WHD-001 6.5). Applying to
        # currentWidget() drops the change whenever the user is on the
        # south/north-indian tab when they click Apply.
        if hasattr(self, 'wheel_view') and hasattr(self.wheel_view, 'set_house_display_mode'):
            self.wheel_view.set_house_display_mode(mode)

    def _compute_chart_ayanamsa_offset(self):
        """Compute the ayanamsa offset in degrees for sidereal chart rendering."""
        if self.birth_jd is None:
            self.chart_ayanamsa_offset = 0.0
            return
        ayanamsa_id = self.chart_sidereal_ayanamsa_id
        if ayanamsa_id == 999:
            self.chart_ayanamsa_offset = 0.0
            return
        try:
            from libaditya import swe
            if ayanamsa_id in (98, 99, 100):
                # Custom ayanamsas — use Lahiri as ecliptic fallback for chart display
                swe.set_sid_mode(1)
            else:
                swe.set_sid_mode(ayanamsa_id)
            self.chart_ayanamsa_offset = swe.get_ayanamsa_ut(self.birth_jd)
        except Exception as e:
            print(f"[WARNING] Failed to compute ayanamsa offset: {e}")
            self.chart_ayanamsa_offset = 0.0

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

        # Clear dasha parent chains and reset levels — HD changes entire sequence,
        # so stale parent chains would cause empty/wrong sub-dasha displays
        self.vedanga_parent_chain = []
        self.vimshottari_parent_chain = []
        self.dasha_level_vedanga = 1
        self.dasha_level_vimshottari = 1
        # Reset level button states
        if hasattr(self, 'vedanga_level_buttons'):
            for i, btn in enumerate(self.vedanga_level_buttons):
                btn.setChecked(i == 0)
        if hasattr(self, 'vimshottari_level_buttons'):
            for i, btn in enumerate(self.vimshottari_level_buttons):
                btn.setChecked(i == 0)

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
        """Toggle sidereal chart mode on/off via Alt+S shortcut."""
        from state.events import SetZodiacMode
        if checked:
            self.chart_zodiac = "sidereal"
            self.state.dispatch(SetZodiacMode(mode="sidereal"))
            self._compute_chart_ayanamsa_offset()
            self._recalculate_chart()
            from core.ayanamsa_data import get_ayanamsa_name
            ayan_name = get_ayanamsa_name(self.chart_sidereal_ayanamsa_id)
            self.statusBar().showMessage(
                f"Chart: Sidereal ({ayan_name}, {self.chart_ayanamsa_offset:.2f}°)", 3000)
        else:
            self.chart_zodiac = "tropical"
            self.state.dispatch(SetZodiacMode(mode="tropical_classic"))
            self._update_toggle_button_styles()
            self._recalculate_chart()
            self.statusBar().showMessage("Chart: Tropical", 3000)

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
        self.dual_rim_btn.setVisible(in_wheel_view)

        if self.state.aditya_mode == "aditya":
            self.dual_rim_btn.setText("+ Tropical")
            self.dual_rim_btn.setToolTip("Show outer Tropical rim on Aditya wheel")
        else:
            self.dual_rim_btn.setText("+ Aditya")
            self.dual_rim_btn.setToolTip("Show outer Aditya rim on Tropical wheel")

    def _toggle_transit_rim(self):
        """Toggle transit overlay via TransitOverlayManager.

        Visible on all chart views. Mutually exclusive with tropical rim.
        """
        mgr = self.transit_overlay_manager
        if mgr.transit_enabled:
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

        from managers.settings_manager import get_settings
        get_settings().set("chart.show_transit_overlay", mgr.transit_enabled)

        if mgr.transit_enabled:
            self.statusBar().showMessage("Transit overlay ON")
        else:
            self.statusBar().showMessage("Transit overlay OFF")

    def _on_transit_state_changed(self):
        """Mediator: route TransitOverlayManager state to the active view."""
        mgr = self.transit_overlay_manager
        if hasattr(self, 'transit_btn'):
            self.transit_btn.setChecked(mgr.transit_enabled)
        if hasattr(self, 'transit_action'):
            self.transit_action.setChecked(mgr.transit_enabled)
        idx = self.chart_stack.currentIndex() if hasattr(self, 'chart_stack') else -1
        if idx == 1 and hasattr(self, 'wheel_view') and self.wheel_view:
            self.wheel_view.update_transit_from_manager(mgr)
        elif idx == 0 and hasattr(self, 'chart_view') and self.chart_view:
            self.chart_view.update_transit_overlay(mgr)
        elif idx == 2 and hasattr(self, 'north_indian_view') and self.north_indian_view:
            self.north_indian_view.update_transit_overlay(mgr)
        if self.time_adjust_widget and hasattr(self.time_adjust_widget, 'update_save_button_state'):
            self.time_adjust_widget.update_save_button_state()

    def _toggle_outer_planets(self):
        """
        Toggle outer planets visibility (Uranus, Neptune, Pluto).
        Affects all chart views: South Indian, North Indian, and Wheel.
        Shortcut: F2
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
        if hasattr(current, 'set_show_retinue_rings'):
            current.set_show_retinue_rings(checked)
            current.draw_wheel()
            current.ensure_visible()
            state = "ON" if checked else "OFF"
            self.statusBar().showMessage(
                f"Hora + Trimsamsa rings: {state} (F5)", 3000)
            # Persist F5 retinue rings preference
            from managers.settings_manager import get_settings
            get_settings().persist_runtime_change("chart.show_retinue_rings", checked)
        else:
            self.statusBar().showMessage(
                "Retinue rings only available on Wheel view (F2 to switch)", 3000)
        # Propagate to panel wheels (draw if visible, defer if not)
        active_tab = self.tab_widget.widget(self.tab_widget.currentIndex())
        for panel_attr in ('transit_panel', 'solar_return_page'):
            panel = getattr(self, panel_attr, None)
            if panel:
                for wheel in panel.get_all_wheels():
                    wheel.set_show_retinue_rings(checked)
                    if active_tab is panel:
                        wheel.draw_wheel()
                    else:
                        wheel._retinue_dirty = True

    def _toggle_trimsamsha_degrees(self, checked: bool):
        """Toggle degree labels on Trimsamsha ring sectors (F6)."""
        current = self.chart_stack.currentWidget()
        if hasattr(current, 'show_trimsamsha_degrees'):
            current.show_trimsamsha_degrees = checked
            if current.show_retinue_rings:
                current.draw_wheel()
                current.ensure_visible()
            state = "ON" if checked else "OFF"
            qualifier = "" if current.show_retinue_rings else " (visible when F5 active)"
            self.statusBar().showMessage(
                f"Trimsamsha degree ruler: {state}{qualifier} (F6)", 3000)
            from managers.settings_manager import get_settings
            get_settings().persist_runtime_change(
                "chart.show_trimsamsha_degrees", checked)
        else:
            self.statusBar().showMessage(
                "Trimsamsha degrees only available on Wheel view (F2)", 3000)
        active_tab = self.tab_widget.widget(self.tab_widget.currentIndex())
        for panel_attr in ('transit_panel', 'solar_return_page'):
            panel = getattr(self, panel_attr, None)
            if panel:
                for wheel in panel.get_all_wheels():
                    wheel.show_trimsamsha_degrees = checked
                    if active_tab is panel:
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
            self.retinue_rings_action.setChecked(False)
        # Propagate to panel wheels (draw if visible, defer if not)
        active_tab = self.tab_widget.widget(self.tab_widget.currentIndex())
        for panel_attr in ('transit_panel', 'solar_return_page'):
            panel = getattr(self, panel_attr, None)
            if panel:
                for wheel in panel.get_all_wheels():
                    wheel.show_element_pies = checked
                    if active_tab is panel:
                        wheel.draw_wheel()
                    else:
                        wheel._retinue_dirty = True

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
            # Propagate to panel wheels (draw if visible, defer if not)
            active_tab = self.tab_widget.widget(self.tab_widget.currentIndex())
            for panel_attr in ('transit_panel', 'solar_return_page'):
                panel = getattr(self, panel_attr, None)
                if panel:
                    for wheel in panel.get_all_wheels():
                        if hasattr(wheel, 'set_cusp_glow_mode'):
                            wheel.set_cusp_glow_mode(new_mode)
                        if active_tab is not panel:
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

        # If a Z6b button is currently driving the override, F4 takes over
        # cleanly: deselect the Z6b column and reset the cycle so it starts
        # from None (Birth Ascendant) → Dhata.
        if getattr(self, "selected_z6b_sign", None) is not None:
            for btn in getattr(self, "sign_selector_buttons", {}).values():
                btn.setChecked(False)
            self.current_ascendant_override = None
            self._on_z6b_selection_changed(None)

        # Cycle logic: None → 0 → 1 → ... → 11 → None
        if self.current_ascendant_override is None:
            self.current_ascendant_override = 0  # Start with Dhata
        elif self.current_ascendant_override < 11:
            self.current_ascendant_override += 1  # Next sign
        else:
            self.current_ascendant_override = None  # Back to birth Ascendant

        override = self.current_ascendant_override

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
            view_rect = target.rect()
            widget_h = self.time_adjust_widget.height()
            margin = 10
            x = margin
            y = (view_rect.height() - widget_h) // 2
            self.time_adjust_widget.setParent(target)
            self.time_adjust_widget.move(x, y)
            self.time_adjust_widget.raise_()  # Bring to front
            self.time_adjust_widget.show()

    def _hide_time_adjust_overlay(self):
        """Hide the time adjust widget overlay."""
        if self.time_adjust_widget:
            self.time_adjust_widget.hide()

    def _open_in_kala(self):
        """
        Open the current chart in Kala astrology software.

        Priority (memory panel is authoritative for current chart):
        1. Use memory panel's current chart chtk_path (if exists)
        2. Create temp CHTK from memory panel's birth_metadata
        3. Launch Kala without a file

        Cross-platform:
        - Windows: launches Kala.exe directly
        - Linux/macOS: launches through Wine
        """
        import os
        import sys
        import subprocess
        import tempfile
        import json
        from PySide6.QtWidgets import QMessageBox

        # Load Kala exe path: SettingsManager first, legacy PrefsStore fallback
        from managers.settings_manager import get_settings
        kala_exe_path = get_settings().get("paths.kala_path", "")
        if not kala_exe_path:
            try:
                all_prefs = self.prefs_store.load()
                kala_exe_path = all_prefs.get("kala", {}).get("exe_path", "")
            except Exception as e:
                print(f"Error reading Kala settings: {e}")

        # Platform-specific defaults if no setting configured
        if not kala_exe_path:
            if sys.platform == 'win32':
                kala_exe_path = r"C:\Kala\Kala.exe"
            else:
                kala_exe_path = os.path.expanduser("~/Kala/Kala.exe")

        use_wine = sys.platform != 'win32'

        # Check if Kala exists
        if not use_wine and not os.path.exists(kala_exe_path):
            QMessageBox.warning(
                self, "Kala Not Found",
                f"Kala.exe not found at:\n{kala_exe_path}\n\n"
                "Please set the Kala path in Settings > Default Folders."
            )
            return
        if use_wine and not os.path.exists(kala_exe_path):
            QMessageBox.warning(
                self, "Kala Not Found",
                f"Kala.exe not found at:\n{kala_exe_path}\n\n"
                "Please set the Kala path in Settings > Default Folders.\n"
                "Kala will be launched through Wine."
            )
            return

        chtk_path = None
        chart_name = "chart"
        metadata = None

        # Get current chart from memory panel (authoritative source)
        if hasattr(self, 'memory_panel') and self.memory_panel:
            current_idx = self.memory_panel.current_index
            if 0 <= current_idx < len(self.memory_panel.charts):
                current_chart = self.memory_panel.charts[current_idx]
                chart_name = current_chart.get('recipe', {}).get('name') or current_chart.get('person_name', 'chart')

                # Option 1: Use this chart's chtk_path if it has one
                memory_chtk_path = current_chart.get('chtk_path')
                if memory_chtk_path and os.path.exists(str(memory_chtk_path)):
                    chtk_path = str(memory_chtk_path)
                else:
                    # Option 2: Build metadata from recipe for temp CHTK
                    recipe = current_chart.get('recipe')
                    if recipe:
                        from core.chart_factory import timedec_to_hms
                        _h, _m, _s = timedec_to_hms(recipe['timedec'])
                        metadata = {
                            'name': recipe.get('name', chart_name),
                            'year': recipe['year'],
                            'month': recipe['month'],
                            'day': recipe['day'],
                            'hour': _h,
                            'minute': _m,
                            'second': _s,
                            'latitude': recipe['lat'],
                            'longitude': recipe['lon'],
                            'timezone': recipe.get('timezone', 'UTC'),
                            'time_change_flag': recipe.get('time_change_flag', 0),
                            'gender': recipe.get('gender', 'Unknown'),
                            'city': recipe.get('city', ''),
                            'country': recipe.get('country', ''),
                            'coordinates': {
                                'latitude': recipe['lat'],
                                'longitude': recipe['lon'],
                            },
                        }
                    else:
                        # Legacy fallback for pre-recipe entries
                        metadata = current_chart.get('birth_metadata', {})
                        if not metadata:
                            bd = current_chart.get('birth_data') or {}
                            if not bd:
                                sp = current_chart.get('source_params')
                                bd = (sp.get('birth_data') or {}) if sp else {}
                            if not bd:
                                bd = current_chart.get('planets_data', {})
                            metadata = {
                                'name': chart_name,
                                'year': bd['year'] if 'year' in bd else bd.get('local_year'),
                                'month': bd['month'] if 'month' in bd else bd.get('local_month'),
                                'day': bd['day'] if 'day' in bd else bd.get('local_day'),
                                'hour': bd['hour'] if 'hour' in bd else bd.get('local_hour'),
                                'minute': bd['minute'] if 'minute' in bd else bd.get('local_minute'),
                                'second': bd.get('second', 0),
                                'latitude': bd['latitude'] if 'latitude' in bd else bd.get('lat'),
                                'longitude': bd['longitude'] if 'longitude' in bd else bd.get('lon'),
                                'timezone': bd.get('timezone') or bd.get('iana_timezone', 'UTC'),
                            }
            else:
                pass
        else:
            pass

        # Create temp CHTK if we have metadata but no chtk_path
        if not chtk_path and metadata:
            try:
                from core.chtk_reader import CHTKWriter

                temp_dir = tempfile.gettempdir()
                safe_name = chart_name.replace(' ', '_').replace('/', '_')
                temp_path = os.path.join(temp_dir, f"{safe_name}_kala.chtk")

                writer = CHTKWriter()
                saved_path = writer.save_chtk_file(metadata, name=chart_name, output_path=temp_path)
                chtk_path = str(saved_path)

            except Exception as e:
                print(f"Error creating Kala temp file: {e}")
                import traceback
                traceback.print_exc()
                QMessageBox.critical(self, "Save Error", f"Could not save chart for Kala:\n{str(e)}")
                return

        # Convert Linux path to Wine/Windows path (Z:\...)
        def _to_wine_path(linux_path):
            try:
                result = subprocess.run(
                    ["winepath", "-w", linux_path],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.strip()
            except Exception:
                pass
            # Fallback: manual Z: drive mapping
            return "Z:" + linux_path.replace("/", "\\")

        # Build launch command based on platform
        def _build_kala_cmd(exe_path, chart_path=None):
            if use_wine:
                cmd = ["wine", exe_path]
                if chart_path:
                    cmd.append(_to_wine_path(chart_path))
            else:
                cmd = [exe_path]
                if chart_path:
                    cmd.append(chart_path)
            return cmd

        # Option 3: No chart data - just launch Kala
        if not chtk_path:
            try:
                cmd = _build_kala_cmd(kala_exe_path)
                subprocess.Popen(cmd, shell=False)
                self.statusBar().showMessage("Launched Kala (no chart)")
                return
            except Exception as e:
                QMessageBox.critical(self, "Launch Error", f"Could not launch Kala:\n{str(e)}")
                return

        # Launch Kala with the CHTK file
        try:
            cmd = _build_kala_cmd(kala_exe_path, chtk_path)
            subprocess.Popen(cmd, shell=False)
            self.statusBar().showMessage(f"Opened '{chart_name}' in Kala")
        except Exception as e:
            QMessageBox.critical(self, "Launch Error", f"Could not launch Kala:\n{str(e)}")

    def show_add_chart_dialog(self):
        """Show AI-powered Add Chart dialog."""
        from ui.add_chart_dialog_qt import show_add_chart_dialog
        import copy

        def on_chart_loaded(chart, name, location, *, planets_data=None):
            """Callback when chart is successfully generated."""
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
                    chtk_path=None,
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
            self.current_chart_path = None
            self.is_human_design = False

            # 2. Add recipe to memory panel (property fallback needs this)
            if hasattr(self, 'chart_memory_panel') and self.chart_memory_panel:
                _recipe = recipe_from_chart(
                    _chart, timezone=timezone_str,
                    city=location, country=country,
                )
                self.chart_memory_panel.add_chart(
                    _recipe, chart_obj=self.state.active_chart,
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
            ayanamsa=getattr(self, 'chart_sidereal_ayanamsa_id', 1),
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

        # Theme-adaptive button styles — SPEC-THM-001 E5: module-level import.
        theme = get_theme_colors()

        # Green active style - Aditya mode with Aditya names
        active_style = f"""
            QPushButton {{
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                font-size: {scaled_area_px('buttons')}px;
                border: none;
                border-radius: 8px;
                padding: 8px 12px;
                min-width: 100px;
            }}
            QPushButton:hover {{
                background-color: #45A049;
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

        # SPEC-MODE-001: in Beginner, force native naming before rendering buttons
        # so the "*" (alternative names) variant never appears on screen.
        if self._is_beginner_mode():
            _native = (self.state.aditya_mode != "aditya")
            if self.use_western_names != _native:
                self.use_western_names = _native

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

        # Sync sidereal View menu action checked state
        if hasattr(self, 'sidereal_action'):
            self.sidereal_action.setChecked(self.state.aditya_mode == "sidereal")

        # Re-apply compact styles if in compact mode (prevents stomped buttons)
        self._reapply_compact_if_needed()

    def _take_screenshot(self):
        """Capture chart view and save as PNG. Delegates to ChartManager."""
        self.chart_manager.take_screenshot()

    def _save_chart_as_png(self):
        """Export current chart view as high-quality PNG with file dialog."""
        from PySide6.QtWidgets import QFileDialog
        from PySide6.QtGui import QImage, QPainter
        from PySide6.QtCore import Qt

        # Get current chart widget (South Indian, Wheel, or North Indian)
        current = self.chart_stack.currentWidget()
        if not current or not hasattr(current, 'scene'):
            self.statusBar().showMessage("No chart to save", 3000)
            return

        # Build default filename from chart name
        chart_name = "chart"
        if self.current_chart_data:
            chart_name = self.current_chart_data.get('name', 'chart')
            chart_name = "".join(c for c in chart_name if c.isalnum() or c in " _-").strip()
            chart_name = chart_name.replace(" ", "_")

        default_path = str(Path.home() / f"{chart_name}.png")

        filepath, _ = QFileDialog.getSaveFileName(
            self, "Save Chart as PNG", default_path,
            "PNG Images (*.png);;All Files (*)"
        )
        if not filepath:
            return

        # Render scene at native resolution (scene is already 2048px — high quality)
        scene = current.scene
        scene_rect = scene.sceneRect()
        width = int(scene_rect.width())
        height = int(scene_rect.height())

        from PySide6.QtCore import QRectF
        image = QImage(width, height, QImage.Format.Format_ARGB32)
        image.fill(QColor("#1a1a1e"))  # Dark background

        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        # Explicit target (full image) ← source (full scene) mapping
        target = QRectF(0, 0, width, height)
        scene.render(painter, target, scene_rect)
        painter.end()

        # PNG compression: 0 = max compression (smaller file), 100 = no compression
        image.save(filepath, "PNG", 50)
        self.statusBar().showMessage(f"Chart saved: {filepath}", 5000)

    def _save_full_view_as_png(self):
        """Export chart content area as PNG (dasha panels + chart + info panels)."""
        from PySide6.QtWidgets import QFileDialog

        chart_name = "chart"
        if self.current_chart_data:
            chart_name = self.current_chart_data.get('name', 'chart')
            chart_name = "".join(c for c in chart_name if c.isalnum() or c in " _-").strip()
            chart_name = chart_name.replace(" ", "_")

        default_path = str(Path.home() / f"{chart_name}_full.png")

        filepath, _ = QFileDialog.getSaveFileName(
            self, "Save Full View as PNG", default_path,
            "PNG Images (*.png);;All Files (*)"
        )
        if not filepath:
            return

        # Grab just the chart content area (Vedanga → Chart → Info → Vimshottari)
        # Excludes toolbar, memory panel, tab bar
        pixmap = self.chart_content.grab()
        pixmap.save(filepath, "PNG", 50)
        self.statusBar().showMessage(f"Full view saved: {filepath}", 5000)

    def _on_z6b_selection_changed(self, sign_index_1based):
        """Z6b sign-selector callback.

        Per-view semantics:
          - South Indian view: drives Mode 2 (mini North Indian in center).
          - Wheel view & North Indian view: F4-equivalent forced Ascendant.
        """
        sign_idx_0based = (sign_index_1based - 1) if sign_index_1based else None

        if hasattr(self, "chart_view") and self.chart_view:
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

    def _switch_varga(self, varga_number):
        """Switch to display a different Varga chart"""
        # Chart-Everywhere Issue 3 (G8): guard on active_chart, not the dict.
        if not self.state.active_chart:
            self.statusBar().showMessage("No chart loaded - load a chart first")
            return

        from state.events import SetVarga
        self.state.dispatch(SetVarga(varga_number=varga_number))

        # Use libaditya Chart.varga(N) directly. Mode is baked into the Chart at
        # construction time (Issue 2), so chart.varga() already returns the
        # mode-correct Varga object — no `chart.tropical()` branch needed (G7).
        # Translate GUI varga numbers into libaditya's classical-formula codes
        # (negative for BPHS deity-based vargas) — without this, D-10/D-24/D-40
        # /D-45/D-60 silently return parivritti results.
        active_chart = self.state.active_chart
        if not active_chart:
            return

        from core.varga_codes import to_libaditya_varga_code
        rcode = None if varga_number == 1 else to_libaditya_varga_code(varga_number)

        ayanamsa_off = self.chart_ayanamsa_offset if self.state.aditya_mode == "sidereal" else 0.0
        use_western = getattr(self, 'use_western_names', False)
        render_offset = 0.0 if varga_number != 1 else ayanamsa_off

        if hasattr(self, 'chart_view') and self.chart_view:
            self.chart_view.update_from_chart(active_chart, varga_code=rcode,
                                               use_western_names=use_western,
                                               ayanamsa_offset=render_offset,
                                               aditya_mode=self.state.aditya_mode)
        if hasattr(self, 'wheel_view') and self.wheel_view:
            self.wheel_view.update_from_chart(active_chart, varga_code=rcode,
                                               use_western_names=use_western,
                                               ayanamsa_offset=render_offset,
                                               aditya_mode=self.state.aditya_mode)
        if hasattr(self, 'north_indian_view') and self.north_indian_view:
            self.north_indian_view.update_from_chart(active_chart, varga_code=rcode,
                                                      use_western_names=use_western,
                                                      ayanamsa_offset=render_offset,
                                                      aditya_mode=self.state.aditya_mode)

        # Phase 4 W5: all 12 panels migrated to controllers — varga changes
        # propagate via the SetVarga dispatch above. Lazy controllers (avastha,
        # shame) handle varga via _on_varga_changed with their own lazy guard.
        # Aspects and strength stay D1-only (mode-invariant across vargas).

        # Ensure varga chart displays immediately
        QApplication.processEvents()

        if hasattr(self, 'varga_buttons') and varga_number in self.varga_buttons:
            self.varga_buttons[varga_number].setChecked(True)

        if hasattr(self, 'varga_actions') and varga_number in self.varga_actions:
            self.varga_actions[varga_number].setChecked(True)

        varga_name = VARGA_NAMES.get(varga_number, f"D-{varga_number}")

        # Use centralized title update (includes varga suffix when D2+)
        self._update_title()

        self.statusBar().showMessage(f"Showing {varga_name} (D-{varga_number}) chart")

    # ─── Keyboard Shortcuts ───────────────────────────────────────────
    def _setup_keyboard_shortcuts(self):
        """Register all keyboard shortcuts using QShortcut.

        Uses QShortcut instead of keyPressEvent so shortcuts work regardless
        of which child widget has focus (QGraphicsView, buttons, etc.).

        Arrow keys: chart/tab navigation
        Alt+key: toolbar button shortcuts
        """
        from PySide6.QtGui import QShortcut, QKeySequence

        # ── Alt+Arrow: chart/tab navigation ──
        QShortcut(QKeySequence("Alt+Left"), self, self._prev_chart)
        QShortcut(QKeySequence("Alt+Right"), self, self._next_chart)
        QShortcut(QKeySequence("Alt+Up"), self, self._prev_tab)
        QShortcut(QKeySequence("Alt+Down"), self, self._next_tab)

        # ── Alt+PageUp/PageDown: memory panel page navigation ──
        QShortcut(QKeySequence("Alt+PgUp"), self, self._prev_memory_page)
        QShortcut(QKeySequence("Alt+PgDown"), self, self._next_memory_page)

        # ── Alt+key: toolbar buttons ──
        QShortcut(QKeySequence("Alt+K"), self, self._open_in_kala)
        QShortcut(QKeySequence("Alt+W"), self, self._toggle_wheel_view)
        QShortcut(QKeySequence("Alt+N"), self, self._load_now_chart)
        QShortcut(QKeySequence("Alt+A"), self, self.show_add_chart_dialog)
        QShortcut(QKeySequence("Alt+T"), self, self._toggle_time_adjust)

    def _prev_chart(self):
        """Navigate to previous chart in memory panel."""
        if hasattr(self, 'memory_panel') and self.memory_panel.current_index > 0:
            self.memory_panel.select_chart(self.memory_panel.current_index - 1)

    def _next_chart(self):
        """Navigate to next chart in memory panel."""
        if hasattr(self, 'memory_panel') and self.memory_panel.current_index < len(self.memory_panel.charts) - 1:
            self.memory_panel.select_chart(self.memory_panel.current_index + 1)

    def _prev_tab(self):
        """Navigate to previous tab."""
        idx = self.tab_widget.currentIndex()
        if idx > 0:
            self.tab_widget.setCurrentIndex(idx - 1)

    def _next_tab(self):
        """Navigate to next tab."""
        idx = self.tab_widget.currentIndex()
        if idx < self.tab_widget.count() - 1:
            self.tab_widget.setCurrentIndex(idx + 1)

    def _prev_memory_page(self):
        """Navigate to previous page in memory panel."""
        if hasattr(self, 'memory_panel'):
            self.memory_panel.prev_page()

    def _next_memory_page(self):
        """Navigate to next page in memory panel."""
        if hasattr(self, 'memory_panel'):
            self.memory_panel.next_page()

    def load_chart(self, chtk_path):
        """Load CHTK file and display chart. Delegates to ChartManager."""
        self.chart_manager.load_chart(chtk_path)

    def _on_chart_folders_changed(self):
        """Reload Find Chart paths and rebuild index after Settings saves."""
        if hasattr(self, 'find_chart_panel') and self.find_chart_panel:
            self.find_chart_panel._load_folder_paths()
            self.find_chart_panel._build_index_async()

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
        timezone_str = result_data.get('timezone', '+00:00:00') or '+00:00:00'
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

                # Detect IANA timezone from coordinates for title display
                try:
                    from timezonefinder import TimezoneFinder
                    tf = TimezoneFinder()
                    self.current_timezone = tf.timezone_at(lat=lat, lng=lon) or 'UTC'
                except Exception as e:
                    print(f"[WARNING] TimezoneFinder failed for ({lat}, {lon}): {e}")
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
            bd = BirthDataManager.create_birth_data_from_chtk(chtk_path)
            BirthDataManager.report_tz_warnings(
                BirthDataManager.validate_birth_data(bd),
                status_bar=self.statusBar(), context=f"Companion {name}")

            lat = bd['latitude']
            lon = bd['longitude']
            city = bd.get('city', 'Unknown')
            country = bd.get('country', 'Unknown')

            self.loading_manager.start(f"Loading {name}...")
            from core.time_utils import julday
            hour_decimal = bd['utc_hour'] + bd['utc_minute'] / 60.0 + bd['utc_second'] / 3600.0
            birth_jd = julday(bd['utc_year'], bd['utc_month'], bd['utc_day'], hour_decimal)
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
                _expl_recipe = recipe_from_chart(
                    _chart, name=name, timezone=self.current_timezone,
                    city=city, country=country,
                    gender=bd.get('gender', 'Unknown'),
                    time_change_flag=bd.get('time_change_flag', 0),
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

        # Deferred retinue ring redraw for non-visible panel wheels (B5 perf fix)
        for panel_attr in ('transit_panel', 'solar_return_page'):
            panel = getattr(self, panel_attr, None)
            if panel and tab_widget is panel:
                for wheel in panel.get_all_wheels():
                    if getattr(wheel, '_retinue_dirty', False):
                        wheel.draw_wheel()
                        wheel._retinue_dirty = False

    def _on_theme_changed(self, theme_file: str):
        """Handle theme change from settings tab - apply immediately"""
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QCursor

        apply_fn = _get_apply_stylesheet()
        if apply_fn:
            theme_name = theme_file.replace('.xml', '').replace('_', ' ').title()
            self.loading_manager.start(f"Applying {theme_name}...")
            QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))

            try:
                apply_fn(QApplication.instance(), theme=theme_file)
                self._save_theme_preference(theme_file)
                # Refresh tab bar and menu bar styles (reads from qt-material env vars)
                self.tab_widget.setStyleSheet(get_tab_bar_style())
                self.menuBar().setStyleSheet(get_menu_bar_style())
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
                # Refresh memory panel with new theme colors
                if hasattr(self, 'memory_panel') and hasattr(self.memory_panel, 'refresh_theme'):
                    self.memory_panel.refresh_theme()
                # Refresh chart title widget
                if hasattr(self, 'chart_title_widget'):
                    from apps.widgets.chart_title_widget import refresh_chart_title_theme
                    refresh_chart_title_theme(self)
                # Refresh varga column buttons
                if hasattr(self, 'varga_buttons'):
                    from apps.panels.varga_column import refresh_varga_theme
                    refresh_varga_theme(self)
                # Refresh Z6b sign-selector buttons
                if hasattr(self, 'sign_selector_buttons'):
                    from apps.panels.sign_selector_column import refresh_sign_selector_theme
                    refresh_sign_selector_theme(self)
                # Refresh profile button styling
                if hasattr(self, 'profile_button'):
                    self._update_profile_button_style()
                # Refresh AI Reading panel
                if hasattr(self, 'ai_reading_panel') and hasattr(self.ai_reading_panel, 'refresh_theme'):
                    self.ai_reading_panel.refresh_theme()
                # Refresh Find Chart panel
                if hasattr(self, 'find_chart_panel') and hasattr(self.find_chart_panel, 'refresh_theme'):
                    self.find_chart_panel.refresh_theme()
                # Refresh Birth Finder panel
                if hasattr(self, 'birth_finder_panel') and hasattr(self.birth_finder_panel, 'refresh_theme'):
                    self.birth_finder_panel.refresh_theme()
                # Refresh Lunar New Year panel
                if hasattr(self, 'lunar_new_year_panel') and hasattr(self.lunar_new_year_panel, 'refresh_theme'):
                    self.lunar_new_year_panel.refresh_theme()
                # Refresh Eclipse panel
                if hasattr(self, 'eclipse_panel') and hasattr(self.eclipse_panel, 'refresh_theme'):
                    self.eclipse_panel.refresh_theme()
                # Refresh Transit panel
                if hasattr(self, 'transit_panel') and hasattr(self.transit_panel, 'refresh_theme'):
                    self.transit_panel.refresh_theme()
                # Refresh Edit Chart panel (sidebar + all subtabs)
                if hasattr(self, 'edit_chart_panel') and hasattr(self.edit_chart_panel, 'refresh_theme'):
                    self.edit_chart_panel.refresh_theme()
                # Refresh Settings tab (needs style update even though it triggered the change)
                if hasattr(self, 'settings_tab') and hasattr(self.settings_tab, 'refresh_theme'):
                    self.settings_tab.refresh_theme()
                # Refresh Exploration panel
                if hasattr(self, 'exploration_panel') and hasattr(self.exploration_panel, 'refresh_theme'):
                    self.exploration_panel.refresh_theme()
                # Refresh Cliwoc Map panel
                if hasattr(self, 'cliwoc_map_panel') and hasattr(self.cliwoc_map_panel, 'refresh_theme'):
                    self.cliwoc_map_panel.refresh_theme()
                # SPEC-THM-001 W1: refresh the three chart views so backgrounds
                # and text pick up the new theme colors. Each view re-reads
                # get_theme_colors() and redraws to apply colors to existing
                # scene items (pre-mortem P-002/P-003).
                if hasattr(self, 'chart_view') and hasattr(self.chart_view, 'refresh_theme'):
                    self.chart_view.refresh_theme()
                if hasattr(self, 'wheel_view') and hasattr(self.wheel_view, 'refresh_theme'):
                    self.wheel_view.refresh_theme()
                if hasattr(self, 'north_indian_view') and hasattr(self.north_indian_view, 'refresh_theme'):
                    self.north_indian_view.refresh_theme()
                # SPEC-THM-001 W3 G13: loading overlay (wrapped by LoadingManager).
                if hasattr(self, 'loading_manager') and hasattr(self.loading_manager, 'refresh_theme'):
                    self.loading_manager.refresh_theme()
                # SPEC-THM-001 W3 G18/G19: HTML controllers re-render content with
                # live theme colors (pre-mortem P-006). The controller HTML is only
                # rebuilt on chart/mode/varga change; theme switch must explicitly
                # trigger a re-render.
                if hasattr(self, 'shame_controller') and hasattr(self.shame_controller, 'refresh_theme'):
                    self.shame_controller.refresh_theme()
                if hasattr(self, 'tajika_yogas_controller') and hasattr(self.tajika_yogas_controller, 'refresh_theme'):
                    self.tajika_yogas_controller.refresh_theme()
                # Retinue tables (Hora/Trimsamsa) use is_light_theme() to pick
                # color palettes; re-render so cell bg/fg match the new theme.
                if hasattr(self, 'hora_controller') and hasattr(self.hora_controller, '_on_theme_changed'):
                    self.hora_controller._on_theme_changed()
                if hasattr(self, 'trimsamsa_controller') and hasattr(self.trimsamsa_controller, '_on_theme_changed'):
                    self.trimsamsa_controller._on_theme_changed()
                if hasattr(self, 'house_graph_controller') and hasattr(self.house_graph_controller, '_on_theme_changed'):
                    self.house_graph_controller._on_theme_changed()
                if hasattr(self, 'planetary_condition_controller') and hasattr(self.planetary_condition_controller, '_on_theme_changed'):
                    self.planetary_condition_controller._on_theme_changed()
                if hasattr(self, 'karakas_controller'):
                    self.karakas_controller._refresh()

                # Auto-select background based on theme brightness
                if theme_file.startswith('light_'):
                    self._on_background_changed("stone_01")
                else:
                    self._on_background_changed("stone_06")

                # SPEC-THM-001 E3: REMOVED redundant self.update() + self.repaint().
                # Each setStyleSheet() above already queues a Qt repaint via the
                # dirty-region system. ChartGUI has no paintEvent override,
                # so the explicit full-window repaint was duplicating work.
                theme_name = theme_file.replace('.xml', '').replace('_', ' ').title()
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
            try:
                self._apply_scale_refresh(get_scale_factor())
                self.statusBar().showMessage("Font sizes updated", 3000)
            except Exception:
                traceback.print_exc()
                self.statusBar().showMessage("Font size refresh failed - see console", 5000)

        # Defer to next event loop tick to avoid re-entrant layout
        QTimer.singleShot(0, _run_font_refresh)

    def _on_scale_changed(self, factor: float):
        """Handle font scale change from settings tab — refresh UI stylesheets."""
        from PySide6.QtCore import QTimer
        import traceback

        def _run_scale_refresh():
            try:
                self._apply_scale_refresh(factor)
            except Exception:
                traceback.print_exc()
                self.statusBar().showMessage("Font scale refresh failed - see console", 5000)

        # Defer refresh to next event loop tick to avoid re-entrant layout
        QTimer.singleShot(0, _run_scale_refresh)

    def _apply_scale_refresh(self, factor: float):
        """Apply font scale refresh to ALL UI elements.

        Re-generates all stylesheets that use scaled_px()/scaled_size().
        Called by Apply button click and monitor switch.
        """
        from ui.qt_theme import get_tab_bar_style, get_menu_bar_style
        pct = int(factor * 100)
        # Zone 1: Tab bar + menu bar
        self.tab_widget.setStyleSheet(get_tab_bar_style())
        self.menuBar().setStyleSheet(get_menu_bar_style())
        # Zones 2-9: All panel styles (dasha buttons, info lists, tables, etc.)
        self._refresh_panel_styles()
        # Zone 2: Memory panel
        if hasattr(self, 'memory_panel') and hasattr(self.memory_panel, 'refresh_theme'):
            self.memory_panel.refresh_theme()
        self.statusBar().showMessage(f"Font scale: {pct}%", 3000)

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

        # 1. Chart view type
        view_type = s.get("chart.view_type", "south_indian")
        view_map = {"south_indian": 0, "wheel": 1, "north_indian": 2}
        target_index = view_map.get(view_type, 0)
        if self.chart_stack.currentIndex() != target_index:
            self._switch_to_chart_index(target_index)

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

        # 4. Retinue rings
        show_retinue = s.get("chart.show_retinue_rings", False)
        if hasattr(current_widget, 'set_show_retinue_rings'):
            current_widget.set_show_retinue_rings(show_retinue)

        # 6. Element pies
        show_pies = s.get("chart.show_element_pies", True)
        if hasattr(current_widget, 'show_element_pies'):
            current_widget.show_element_pies = show_pies

        # 7. Panel default sub-tabs (Karakas / Strength / Aspects) applied live.
        # Reuse the startup applier so Settings Apply and boot use identical logic
        # (handles the Aspects mode relabel and the Yogas idx 5 raw switch, pm-004).
        from managers.startup_state_manager import _apply_panel_tabs
        _apply_panel_tabs(self, s)

        self._refresh_chart_display()
        self.statusBar().showMessage("Chart display settings applied")

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

    def _refresh_panel_styles(self):
        """Refresh panel header styles to match new theme colors and scaled font sizes."""
        # Guard: skip if core panels not yet initialized (called during startup before layout is built)
        if not hasattr(self, 'vedanga_list') and not hasattr(self, 'karakas_list'):
            return
        # SPEC-THM-001 E5: get_theme_colors is module-level. Other helpers are
        # local-only here so keep their imports inline.
        from ui.qt_theme import get_list_style, get_3d_button_style
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
        header_names = ['vedanga_header', 'vimshottari_header', 'karakas_header', 'strength_header', 'aspects_header']
        for header_name in header_names:
            if hasattr(self, header_name):
                header = getattr(self, header_name)
                header.setStyleSheet(header_style)

        # Refresh dasha list styles
        vedanga_list = getattr(self, 'vedanga_list', None)
        if vedanga_list:
            vedanga_list.setStyleSheet(get_list_style("orange"))
            # Force Qt to re-layout list items (row heights don't auto-update on stylesheet change)
            vedanga_list.doItemsLayout()
        vimshottari_list = getattr(self, 'vimshottari_list', None)
        if vimshottari_list:
            vimshottari_list.setStyleSheet(get_list_style("cyan"))
            vimshottari_list.doItemsLayout()

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

        # Update level button styles for both panels (using "small" size now)
        vedanga_btn_style = get_3d_button_style("orange", "small")
        vimshottari_btn_style = get_3d_button_style("cyan", "small")

        for btn in getattr(self, 'vedanga_level_buttons', []):
            btn.setStyleSheet(vedanga_btn_style)
        for btn in getattr(self, 'vimshottari_level_buttons', []):
            btn.setStyleSheet(vimshottari_btn_style)

        # Refresh panel CONTAINER backgrounds (critical for theme switching)
        # Without this, containers keep old theme colors when switching dark<->light
        from ui.qt_theme import get_panel_style, get_frame_style
        panel_bg = get_panel_style()
        frame_bg = get_frame_style()

        for attr in ('vedanga_panel', 'vimshottari_panel', 'right_panels'):
            panel = getattr(self, attr, None)
            if panel:
                panel.setStyleSheet(panel_bg)

        # Refresh info panel FRAMES (karakas, strength, aspects sections)
        for attr in ('karakas_frame', 'strength_frame', 'aspects_frame'):
            frame = getattr(self, attr, None)
            if frame:
                frame.setStyleSheet(frame_bg)

        # Refresh dasha nav bar backgrounds, arrows, and cycle labels
        nav_bg = f"background-color: {theme['secondary']};"
        for attr in ('vedanga_nav_frame', 'vimshottari_nav_frame'):
            nav = getattr(self, attr, None)
            if nav:
                nav.setStyleSheet(nav_bg)
        arrow_style = f"""
            QPushButton {{
                background-color: {theme["secondary_dark"]};
                color: {theme["secondary_text"]};
                border: 1px solid {theme["secondary_dark"]};
                border-radius: 3px;
                font-size: {scaled_area_px('buttons')}px; font-weight: bold;
                min-width: {scaled_px(24)}px; max-width: {scaled_px(24)}px; min-height: {scaled_px(20)}px;
                padding: 0px;
            }}
            QPushButton:hover {{
                background-color: {theme["secondary_light"]};
                border: 1px solid {theme["primary"]};
                color: {theme["primary"]};
            }}
            QPushButton:pressed {{
                background-color: {theme["primary"]};
                color: {theme["secondary_text"]};
            }}
        """
        for attr in ('vedanga_prev_btn', 'vedanga_next_btn',
                      'vimshottari_prev_btn', 'vimshottari_next_btn'):
            btn = getattr(self, attr, None)
            if btn:
                btn.setStyleSheet(arrow_style)
        label_style = f"color: {theme['secondary_text']}; font-size: {scaled_area_px('status')}px; font-weight: bold; background: transparent;"
        for attr in ('vedanga_cycle_label', 'vimshottari_cycle_label'):
            lbl = getattr(self, attr, None)
            if lbl:
                lbl.setStyleSheet(label_style)

        # Refresh dasha highlight combo styles (Karaka / Cusp / WS lord)
        from ui.qt_theme import ACCENTS
        combo_style = f"""
            QComboBox {{
                background-color: {theme["secondary_dark"]};
                color: {theme["secondary_text"]};
                border: 1px solid {theme["secondary"]};
                border-radius: 3px;
                padding: 2px 6px;
                font-size: {scaled_area_px('buttons')}px;
                min-height: {scaled_px(22)}px;
            }}
            QComboBox:hover {{ border: 1px solid {theme["primary"]}; }}
            QComboBox::drop-down {{ border: none; width: {scaled_px(16)}px; }}
            QComboBox QAbstractItemView {{
                background-color: {theme["secondary_dark"]};
                color: {theme["secondary_text"]};
                selection-background-color: {theme["primary"]};
                selection-color: {theme["primary_text"]};
                border: 1px solid {theme["secondary"]};
                font-size: {scaled_area_px('buttons')}px;
                padding: 2px;
                outline: none;
            }}
            QComboBox QAbstractItemView::item {{
                min-height: {scaled_px(24)}px;
                padding: 4px 8px;
            }}
        """
        for attr in ('vedanga_karaka_combo', 'vedanga_cusp_combo', 'vedanga_ws_combo',
                      'vimshottari_karaka_combo', 'vimshottari_cusp_combo', 'vimshottari_ws_combo'):
            combo = getattr(self, attr, None)
            if combo:
                combo.setStyleSheet(combo_style)
        # Refresh combo label colors (accent-colored)
        combo_label_pairs = [
            ('vedanga_karaka_combo', ACCENTS['gold']['base']),
            ('vedanga_cusp_combo', ACCENTS['cyan']['base']),
            ('vedanga_ws_combo', ACCENTS['orange']['base']),
            ('vimshottari_karaka_combo', ACCENTS['gold']['base']),
            ('vimshottari_cusp_combo', ACCENTS['cyan']['base']),
            ('vimshottari_ws_combo', ACCENTS['orange']['base']),
        ]

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
                tbl.resizeRowsToContents()

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
                    font-weight: bold;
                }}
            """
            dignities_tbl.setStyleSheet(dignities_style)

        # Refresh dasha title buttons (font-size scaled)
        title_btn_style = f"""
            QPushButton {{ color: {theme["secondary_text"]}; font-size: {scaled_area_px('panel_titles')}px; font-weight: bold;
                background: transparent; border: none; text-transform: none;
                text-align: left; padding: 0px; }}
            QPushButton:hover {{ color: {theme["primary_light"]}; }}
        """
        for attr in ('vedanga_title_btn', 'vimshottari_title_btn'):
            btn = getattr(self, attr, None)
            if btn:
                btn.setStyleSheet(title_btn_style)

        swap_btn = getattr(self, 'vimshottari_swap_btn', None)
        if swap_btn:
            swap_btn.setStyleSheet(f"""
                QPushButton {{ background: {theme["secondary_dark"]}; border: 1px solid {theme["primary"]};
                    border-radius: {scaled_px(4)}px; padding: 0px; }}
                QPushButton:hover {{ background: {theme["primary"]}; border-color: {theme["primary_light"]}; }}
            """)

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

        # Refresh action bar buttons (SOUTH, OPEN IN KALA, etc.) — they use
        # get_3d_button_style which already uses scaled_px internally
        action_bar_style = get_3d_button_style("blue", "text")
        for attr in ('south_btn', 'open_kala_btn', 'wikibio_btn'):
            btn = getattr(self, attr, None)
            if btn:
                btn.setStyleSheet(action_bar_style)

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
        for active_attr, group in (
            ('strength_tab_btn', ('strength_tab_btn', 'elements_tab_btn', 'modality_tab_btn')),
            ('karakas_tab_btn', ('karakas_tab_btn', 'hora_tab_btn', 'trimsamsa_tab_btn', 'graph_tab_btn')),
        ):
            group_btns = [getattr(self, n, None) for n in group]
            group_btns = [b for b in group_btns if b is not None]
            for b in group_btns:
                if b.font().bold():
                    b.setStyleSheet(strength_tab_active)
                else:
                    b.setStyleSheet(strength_tab_inactive)

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

        # Refresh swap icon color for light/dark theme (all panels)
        make_icon = getattr(self, '_make_swap_icon', None)
        if make_icon:
            themed_icon = make_icon(theme["primary_text"])
            for attr in ('strength_lang_btn', 'aspects_mode_btn', 'vimshottari_swap_btn'):
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
        te = getattr(self, 'exchange_display', None)
        if te is not None:
            te.setStyleSheet(textedit_style.replace("QTextEdit", "QTextBrowser"))

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


        # Persist tab usage counts
        if self._tab_usage_counts:
            from managers.settings_manager import get_settings
            get_settings().set("tab_usage_counts", self._tab_usage_counts)
        if hasattr(self, 'session_manager'):
            self.session_manager.save_session(mark_closed=True)
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
            else:
                # Fallback to legacy settings.json
                theme_settings_path = data_dir / "settings.json"
                if theme_settings_path.exists():
                    with open(theme_settings_path, "r") as f:
                        settings = json.load(f)
                        theme = settings.get("theme", "dark_blue.xml")
        except Exception:
            pass
        apply_fn(app, theme=theme)
    else:
        app.setStyle("Fusion")

    # Install global "Search Google" right-click on any selected text
    from managers.context_menu_manager import install_search_context_menu
    install_search_context_menu(app)

    # ── License Validation ──────────────────────────────────────
    # Varuna360 Core is AGPL-3.0 and runs anonymously from source. The
    # forced-login flow only activates when VARUNA360_BUNDLED=1 is set
    # in the environment — that env var is injected by the PyInstaller
    # wrapper used for the future paid installer distribution. Source
    # builds (git clone), the AppImage self-host, and anyone running
    # python apps/core_gui_qt.py directly get the anonymous path and
    # never see a login dialog at launch.
    #
    # .strip() defends against trailing whitespace on the env var value.
    # Without it, a .env file entry like "VARUNA360_BUNDLED=1\n" would
    # silently disable enforcement in the future bundled installer, which
    # is exactly the kind of hidden regression that's worth one extra
    # character to prevent.
    #
    # The IS_BUNDLED split keeps commercial enforcement and software
    # features decoupled: _LITE_MODE forces ChartGUI (skips Pro import),
    # while IS_BUNDLED is "which commercial model applies".
    #
    # STRUCTURAL FREEDOM 0 PROTECTION: the anonymous source path does
    # not import managers.license_manager at all. license_state stays
    # None on anonymous boot, and the 12h refresh flow (_refresh_license
    # around line 1272) handles None as "no license to refresh". Even
    # if a future license_manager edit accidentally introduced a module-
    # level network call or thread start, the anonymous path would be
    # unaffected because Python never executes license_manager.py on
    # this branch.
    IS_BUNDLED = os.environ.get("VARUNA360_BUNDLED", "").strip() == "1"

    if IS_BUNDLED:
        from managers.license_manager import attempt_cached_login
        license_state = attempt_cached_login()
        if not license_state.is_licensed:
            # Bundled installer — sign-in is required. The "Continue
            # without account" button is explicitly disabled in this
            # context: bundled users paid for access, and declining
            # sign-in means exiting. The LoginDialog hides the button
            # entirely rather than showing a misleading "Continue"
            # label that would actually trigger sys.exit(0).
            from apps.widgets.login_dialog import LoginDialog
            login_dialog = LoginDialog(show_continue_without_account=False)
            result = login_dialog.exec()
            if result == LoginDialog.DialogCode.Accepted:
                license_state = login_dialog.get_license_state()
            else:
                sys.exit(0)
    else:
        # Anonymous source/self-host path. NO import of license_manager,
        # NO server call, NO dialog. license_state stays None; downstream
        # refresh code is None-safe (see line 1272).
        license_state = None

    # ────────────────────────────────────────────────────────────

    # First-run data directory setup (AppImage/frozen only).
    # On a fresh install there is no bootstrap config yet, so we ask the
    # user where to store profiles, settings, and session files.
    from state.user_data import needs_first_run_setup
    if needs_first_run_setup():
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
    if should_show_welcome():
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

    # Open .chtk file if passed as command-line argument (e.g. double-click from file manager)
    chtk_arg = None
    for arg in sys.argv[1:]:
        if arg.endswith('.chtk') and os.path.isfile(arg):
            chtk_arg = arg
            break
    if chtk_arg:
        QTimer.singleShot(1500, lambda path=chtk_arg: window.chart_manager.load_chart(path))

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
