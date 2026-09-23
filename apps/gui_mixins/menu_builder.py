"""Application menu-bar builder, extracted from ChartGUI (Stage 1d, move-only
completion of the MENUS & PROFILE cluster split started in Stage 1b W6-A).

`_create_menus` is the retained half of cluster #5. It was blocked from the
W6-A profile extraction because it referenced `VARGA_NAMES`, a dict then defined
in core_gui_qt.py (a core -> mixin -> core import cycle if moved). Stage 1d C1
(td-gl6y) de-duplicated `VARGA_NAMES` to its canonical, GUI-free home in
core.varga_codes; with that blocker gone the 363-line builder moves here
byte-identically (td-6azk).

The builder produces the 5 externally-read QActions (`outer_planets_action`,
`pie_charts_action`, `planet_names_action`, `retinue_rings_action`,
`trimsamsha_degrees_action`) plus ~15 other actions and ~31 handler references,
all assigned to `self` (the ChartGUI instance) exactly as before — a move-only
mixin keeps every `self.*` write unchanged (no `self.gui.*` blackboard write is
introduced; Rule 4b safe). The QActions' STATE ownership is a separate Stage 2
question (bead td-koni), not this move.

Imports are module-top for AST-identity (Stage 1b D1 ruling); each is
cycle-checked: PySide6 is external, core.varga_codes has no GUI deps, and
ui.qt_theme is already imported at module top by a sibling mixin (profile_menu).
"""

from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from core.varga_codes import VARGA_NAMES
from ui.qt_theme import apply_menu_bar_style


class MenuBuilderMixin:
    """Menu-bar construction for ChartGUI (see module docstring)."""

    def _create_menus(self):
        """Create application menu bar with modern dark styling"""
        menubar = self.menuBar()

        # Apply modern dark theme styling + the td-1a24 height pin (the pin must
        # be widget-level, never QSS — see apply_menu_bar_style)
        apply_menu_bar_style(menubar)

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

        # Save As action — writes .chtk OR .toml by the chosen extension
        # (SPEC-IMPORT-001: this is the GUI CHTK<->TOML conversion path).
        save_as_action = QAction("&Save Chart As... (.chtk / .toml)", self)
        save_as_action.setShortcut(QKeySequence.StandardKey.SaveAs)
        save_as_action.setStatusTip("Save/convert the current chart as .chtk or .toml (choose the extension in the dialog)")
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

        # Fullscreen the current chart page (SPEC-FSV-001 WI-3). Plain "F", a
        # WindowShortcut — safe now that WI-1 freed the key from the Cards of
        # Truth family toggle (which moved to "C"). Esc/F also exit from inside
        # the fullscreen container (handled there). Menu label toggles nothing;
        # the manager is idempotent and toggles by state.
        fullscreen_action = QAction("&Fullscreen View", self)
        fullscreen_action.setShortcut(QKeySequence("F"))
        # Holding F would otherwise autorepeat enter->exit->enter (codex M-5).
        fullscreen_action.setAutoRepeat(False)
        fullscreen_action.setStatusTip(
            "Fullscreen the current tab's chart view (F to exit)")
        fullscreen_action.triggered.connect(
            lambda: self.view_float_manager.toggle_fullscreen())
        view_menu.addAction(fullscreen_action)

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
        self.cycle_view_action.setStatusTip("Cycle: South Indian → Wheel → North Indian → Body Graph (F2). Cards of Truth is its own button (Alt+K).")
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
            "Toggle Hora + Trimshamsha on Wheel or vector South Indian chart (F5)")
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

        # Toggle Rashi Aspect Panel action (Shift+F2) — SPEC-BODY-002.
        # Only meaningful on the Body Graph view (chart_stack index 3); the
        # handler is a no-op elsewhere, matching the other view-specific toggles.
        self.aspect_panel_action = QAction("Toggle Rashi &Aspect Panel", self)
        self.aspect_panel_action.setShortcut(QKeySequence("Shift+F2"))
        self.aspect_panel_action.setStatusTip(
            "Show/hide the rashi aspect panel on the Body Graph view (Shift+F2)")
        self.aspect_panel_action.triggered.connect(self._toggle_aspect_panel)
        view_menu.addAction(self.aspect_panel_action)

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

        # License Menu — top-level, sibling of File/View/Help. The desktop has
        # no account: you paste a license key copied from your website account
        # to activate it (like the mobile app). Two entries only: enter the key,
        # and see the plans. Both lazy-load their dialogs.
        license_menu = menubar.addMenu("&License")

        enter_key_action = QAction("Enter &License Key…", self)
        enter_key_action.setStatusTip(
            "Paste the license key from your 360heartsinthesky.com account to "
            "activate the app"
        )
        enter_key_action.triggered.connect(self._show_key_dialog)
        license_menu.addAction(enter_key_action)
        self._enter_key_action = enter_key_action

        # Keep the menu a live status surface (the mobile app's trial tile
        # parity, no new chrome row): each time the menu opens, refresh the
        # separator label to show the trial countdown. aboutToShow fires before
        # the menu paints, so the count is never stale.
        self._trial_status_action = QAction("", self)
        self._trial_status_action.setEnabled(False)
        self._trial_status_action.setVisible(False)
        license_menu.addAction(self._trial_status_action)
        license_menu.aboutToShow.connect(self._refresh_license_menu_status)

        license_menu.addSeparator()

        view_plans_action = QAction("View &Plans…", self)
        view_plans_action.setStatusTip("See the Varuna360 subscription plans")
        view_plans_action.triggered.connect(self._show_tier_dialog)
        license_menu.addAction(view_plans_action)

        # Help Menu
        help_menu = menubar.addMenu("&Help")

        # Manual action
        manual_action = QAction("&Manual...", self)
        manual_action.setShortcut(QKeySequence("F1"))
        manual_action.setStatusTip("Open the Varuna360 help manual (F1)")
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
