# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Edit Chart Panel - Main container with 3 vertical sub-tabs

This panel provides comprehensive chart editing and creation capabilities:
- Sub-tab 0: Edit Chart Information (form-based)
- Sub-tab 1: New Chart (create charts from scratch)
- Sub-tab 2: Map View (interactive offline map)

The panel connects to the Memory Panel to receive chart selections
and updates the chart data when changes are saved.
"""

import logging

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QMessageBox, QLabel, QApplication
)
from PySide6.QtCore import Signal, Slot, Qt, QSize

# Theme imports - use get_theme_colors() for dynamic light/dark support
from ui.qt_theme import get_theme_colors

logger = logging.getLogger(__name__)


def _writer_for(path):
    """Return the file-format writer instance for ``path`` (SPEC-IMPORT-001 §6.1, B5).

    Pure dispatch on the file extension so the save path NEVER writes UTF-16 CHTK
    binary over a ``.toml`` file (irreversible corruption). ``.toml`` -> a writer
    with ``update_*_birth_data(path, birth_data)``; everything else (``.chtk`` and
    legacy extensionless paths) -> CHTKWriter for backward compatibility.

    Returns a (writer, method_name) tuple. ``method_name`` is the partial-update
    method to call as ``getattr(writer, method_name)(path, birth_data)``.
    """
    from pathlib import Path
    suffix = Path(str(path)).suffix.lower()
    if suffix == ".toml":
        from core.toml_chart import TOMLChartWriter
        return TOMLChartWriter(), "update_toml_birth_data"
    from core.chtk_reader import CHTKWriter
    return CHTKWriter(), "update_chtk_birth_data"


class EditChartPanel(QWidget):
    """
    Main Edit Chart panel with 3 vertical sub-tabs.

    Signals:
        chart_modified(dict): Emitted when chart data is modified
        chart_saved(str): Emitted when changes are saved (with path if saved to file)
    """

    chart_modified = Signal(dict)
    chart_saved = Signal(str)

    def __init__(self, gui):
        """
        Initialize the Edit Chart Panel.

        Args:
            gui: Reference to ChartGUI for data access
        """
        super().__init__()

        self.gui = gui
        self.current_chart_data = None  # Chart entry from memory panel
        self.current_birth_metadata = None  # Birth metadata dict
        self.is_modified = False
        self._map_caller = "info"  # "info" or "new_chart" — who requested the map
        self._previous_tab_index = 0
        # BUG-2 (SPEC-IMPORT-002): pristine _toml_extra snapshot captured at chart
        # load time. Edit-save cycles re-merge unknown TOML keys from THIS snapshot
        # rather than re-reading the file (which reflects the previous save and
        # progressively sheds keys each cycle). Keyed by source path so a stale
        # snapshot can never bleed onto a different chart.
        self._loaded_toml_extra = None
        self._loaded_toml_extra_path = None

        self._create_ui()
        self._connect_signals()

    def _create_ui(self):
        """Create the panel UI with sidebar navigation (horizontal text)"""
        from PySide6.QtWidgets import QListWidget, QListWidgetItem, QStackedWidget, QSplitter

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # === LEFT SIDEBAR (Navigation) ===
        self.sidebar = QListWidget()
        self.sidebar.setFixedWidth(140)
        self.sidebar.setStyleSheet(self._get_sidebar_style())

        # Add navigation items with horizontal text
        nav_items = [
            ("Edit Info", "Edit chart fields"),
            ("New Chart...", "Create from scratch"),
            ("Map View...", "Search or pick location")
        ]

        for title, subtitle in nav_items:
            item = QListWidgetItem(f"{title}\n{subtitle}")
            item.setSizeHint(QSize(130, 50))
            self.sidebar.addItem(item)

        self.sidebar.setCurrentRow(0)

        # === RIGHT CONTENT (Stacked Widget) ===
        theme = get_theme_colors()
        self.stack = QStackedWidget()
        self.stack.setStyleSheet(f"background-color: {theme['secondary_dark']};")

        # === Create Sub-tabs ===
        from apps.panels.new_chart_subtab import NewChartSubTab
        from apps.panels.edit_info_subtab import EditInfoSubTab
        from apps.panels.edit_map_subtab import EditMapSubTab

        self.new_chart_tab = NewChartSubTab(self)
        self.info_tab = EditInfoSubTab(self)
        self.map_tab = EditMapSubTab(self)

        self.stack.addWidget(self.info_tab)        # Index 0 — Edit Info
        self.stack.addWidget(self.new_chart_tab)   # Index 1 — New Chart
        self.stack.addWidget(self.map_tab)         # Index 2 — Map View

        # Connect sidebar to stack
        self.sidebar.currentRowChanged.connect(self.stack.setCurrentIndex)

        layout.addWidget(self.sidebar)
        layout.addWidget(self.stack, 1)  # stretch factor 1

    def _get_sidebar_style(self) -> str:
        """Generate stylesheet for sidebar navigation using dynamic theme colors"""
        theme = get_theme_colors()
        # Use 4 theme colors for proper light/dark support
        primary = theme['primary']              # Accent color
        secondary = theme['secondary']          # Main background
        secondary_dark = theme['secondary_dark'] # Darker background
        secondary_light = theme['secondary_light'] # Hover/lighter
        text_color = theme['secondary_text']    # Text that contrasts with secondary

        return f"""
            QListWidget {{
                background-color: {secondary};
                border: none;
                border-right: 1px solid {secondary_dark};
                outline: none;
            }}

            QListWidget::item {{
                color: {text_color};
                padding: 12px 10px;
                border-left: 3px solid transparent;
            }}

            QListWidget::item:selected {{
                background-color: {secondary_dark};
                color: {text_color};
                border-left: 3px solid {primary};
            }}

            QListWidget::item:hover:!selected {{
                background-color: {secondary_light};
                color: {text_color};
            }}
        """

    def _connect_signals(self):
        """Wire up signal connections"""
        # Sidebar switching - sync data between tabs
        self.sidebar.currentRowChanged.connect(self._on_tab_switched)

        # New Chart tab signals
        self.new_chart_tab.chart_created.connect(self._on_chart_created)

        # Info tab signals
        self.info_tab.data_changed.connect(self._mark_modified)
        self.info_tab.location_changed.connect(self._on_location_changed)
        self.info_tab.save_requested.connect(self.save_changes)
        self.info_tab.cancel_requested.connect(self.cancel_changes)
        self.info_tab.map_view_requested.connect(self._switch_to_map_view)

        # New Chart tab signals (map integration)
        self.new_chart_tab.map_view_requested.connect(self._switch_to_map_from_new_chart)

        # Map tab signals
        self.map_tab.location_selected.connect(self._on_map_location_selected)
        self.map_tab.apply_requested.connect(self._on_map_apply_return)

    # =========================================================================
    # DATA LOADING
    # =========================================================================

    def load_chart_from_memory(self, chart_entry: dict):
        """
        Populate all sub-tabs from a memory panel chart entry.

        Args:
            chart_entry: Dict containing planets_data, birth_metadata, etc.
        """
        if not chart_entry:
            return

        self.current_chart_data = chart_entry
        self.is_modified = False

        # BUG-2 (SPEC-IMPORT-002): snapshot the pristine _toml_extra NOW, before any
        # edit-save cycle can rewrite (and shed keys from) the source file. The
        # save-time re-merge then pulls unknown TOML keys from this snapshot instead
        # of the on-disk file. Recipe-restored charts carry no _toml_extra (the
        # recipe drops it), so without this snapshot _source_birth_data would re-read
        # the possibly-already-degraded file every save.
        self._loaded_toml_extra = None
        self._loaded_toml_extra_path = None
        _src_path = chart_entry.get('chtk_path')
        if _src_path and str(_src_path).lower().endswith('.toml'):
            from pathlib import Path as _Path
            if _Path(str(_src_path)).exists():
                try:
                    from core.toml_chart import TOMLChartReader
                    _pristine = TOMLChartReader().read_toml_file(
                        str(_src_path), canonicalize=False)
                    self._loaded_toml_extra = _pristine.get('_toml_extra')
                    self._loaded_toml_extra_path = str(_src_path)
                except Exception as exc:  # noqa: BLE001 - never block chart load
                    logger.warning(
                        "Could not snapshot _toml_extra at load (%s): %s",
                        _src_path, exc)

        recipe = chart_entry.get('recipe')
        if recipe:
            from core.chart_factory import timedec_to_hms, resolve_recipe_dst_flag
            from core.time_utils import local_to_utc, resolve_total_offset, format_offset
            h, m, s = timedec_to_hms(recipe['timedec'])
            location = {
                'city': recipe.get('city', ''),
                'country': recipe.get('country', ''),
                'timezone': recipe.get('timezone', 'UTC'),
            }
            birth_metadata = chart_entry.get('birth_metadata', {})
            # td-5w3c.1 guard: sessions saved before the CHTK auto-flag fix
            # can carry the Kala -1 AUTO sentinel; resolve it (IANA rules
            # when the recipe holds an IANA name, else 0 + warning) before
            # the flag feeds local_to_utc and birth_data below.
            _tcf, _tcf_warnings = resolve_recipe_dst_flag(recipe)
            for _w in _tcf_warnings:
                logger.warning("%s (recipe %s)", _w, recipe.get('name', ''))
            _tz_display = recipe.get('timezone', '+00:00')

            # Resolve standard offset from timezone string FIRST,
            # needed for both local_to_utc and birth_data construction.
            # recipe['utcoffset'] is TOTAL (standard+DST); we need standard only
            # because birth_data adds _tcf back.
            _std_offset = None
            if '/' in _tz_display:
                try:
                    _std_offset, _computed_flag = resolve_total_offset(
                        _tz_display, recipe['year'], recipe['month'], recipe['day'], h, m,
                        longitude=recipe.get('lon'))
                except Exception:
                    pass
            if _std_offset is None:
                try:
                    from core.time_utils import _parse_offset
                    _std_h, _std_m = _parse_offset(_tz_display)
                    _std_offset = _std_h + _std_m / 60.0
                except Exception:
                    _raw_uo = recipe.get('utcoffset')
                    _tcf_delta = _tcf if _tcf in (1, 2) else 0
                    _std_offset = (float(_raw_uo) if _raw_uo is not None else 0.0) - _tcf_delta

            # Convert IANA to +HH:MM for local_to_utc (it only accepts offset strings)
            _tz_for_utc = _tz_display
            if '/' in _tz_display:
                _tz_for_utc = format_offset(0, int(round(_std_offset * 60)))

            try:
                _utc = local_to_utc(
                    recipe['year'], recipe['month'], recipe['day'],
                    h, m, s, _tz_for_utc, _tcf)
            except Exception:
                _utc = (recipe['year'], recipe['month'], recipe['day'], h, m, s)
            merged_metadata = {
                'name': recipe.get('name', ''),
                'year': recipe['year'],
                'month': recipe['month'],
                'day': recipe['day'],
                'hour': h,
                'minute': m,
                'second': s,
                'gender': recipe.get('gender', birth_metadata.get('gender', '')),
                'latitude': recipe['lat'],
                'longitude': recipe['lon'],
                'dst': _tcf,
                'location': location,
            }
            self.current_birth_metadata = birth_metadata
            planets_data = {}
            birth_data = {
                'name': recipe.get('name', ''),
                'local_year': recipe['year'], 'local_month': recipe['month'],
                'local_day': recipe['day'],
                'local_hour': h, 'local_minute': m, 'local_second': s,
                'utc_year': _utc[0], 'utc_month': _utc[1], 'utc_day': _utc[2],
                'utc_hour': _utc[3], 'utc_minute': _utc[4], 'utc_second': _utc[5],
                # BUG-8 (SPEC-IMPORT-002): recipe['utcoffset'] is the TOTAL offset
                # (standard+DST) by construction (make_recipe stores jd.utcoffset;
                # INVARIANT m14). Read it DIRECTLY rather than re-deriving TOTAL as
                # `_std_offset + _tcf`. That reconstruction is LOSSY for fractional-
                # DST zones (Lord Howe Island, 0.5h DST): on the IANA and fallback
                # paths `_std_offset = TOTAL - INTEGER_flag` because
                # resolve_total_offset subtracts the integer flag, not the float dst
                # (core/time_utils.py contract), so the integer flag — not the 0.5h
                # float — is what must be added back. The old expression only
                # produced the right TOTAL when `_std_offset` was the true float
                # standard (the rarely-taken offset-string path). Keep it solely as a
                # defensive fallback for a malformed recipe missing utcoffset.
                # (Pre-existing, out of scope: line ~251's local_to_utc also takes
                # the integer flag, so the offset-string path's utc_* fields are 0.5h
                # off for fractional DST until switched to local_to_utc_total.)
                'utc_offset_hours': (float(recipe['utcoffset'])
                                     if recipe.get('utcoffset') is not None
                                     else _std_offset + (_tcf or 0)),
                'time_change_flag': _tcf,
                'latitude': recipe['lat'], 'longitude': recipe['lon'],
                'city': recipe.get('city', ''), 'country': recipe.get('country', ''),
                'gender': recipe.get('gender', birth_metadata.get('gender', '')),
                'iana_timezone': birth_metadata.get('iana_timezone', ''),
                # SPEC-IMPORT-001 §6.1: carry the additive metadata the recipe
                # holds (None for CHTK charts) so the edit round-trip does not
                # drop rodden/tags/notes/julian_day/dst_offset_hours. _toml_extra
                # is not in the recipe; it is re-read from the source file at save
                # time (see _source_birth_data).
                'rodden': recipe.get('rodden'),
                'tags': recipe.get('tags'),
                'notes': recipe.get('notes'),
                'julian_day': recipe.get('julian_day'),
                'dst_offset_hours': recipe.get('dst_offset_hours'),
                'source_format': recipe.get('source_format'),
            }
            # td-5w3c.1: surface guard warnings on the SPEC-TZ-001 8a
            # channel. Key added ONLY when the -1 guard fired so normal
            # recipes keep their exact birth_data shape.
            if _tcf_warnings:
                birth_data['tz_warnings'] = _tcf_warnings
        else:
            # Legacy fallback for pre-recipe entries
            planets_data = chart_entry.get('planets_data', {})
            birth_metadata = chart_entry.get('birth_metadata', {})
            self.current_birth_metadata = birth_metadata
            birth_data = chart_entry.get('birth_data') or {}
            sp = chart_entry.get('source_params')
            sp_bd = (sp.get('birth_data') or {}) if sp else {}

            def _pick(*sources, key, default=None):
                for src in sources:
                    v = src.get(key) if isinstance(src, dict) else None
                    if v is not None and v != '':
                        return v
                return default

            sp_bd = dict(sp_bd)
            if sp_bd.get('timedec') is not None and sp_bd.get('hour') is None:
                from core.chart_factory import timedec_to_hms
                _h, _m, _s = timedec_to_hms(float(sp_bd['timedec']))
                sp_bd['hour'] = _h
                sp_bd['minute'] = _m
                sp_bd['second'] = _s

            merged_metadata = {
                'name': chart_entry.get('person_name', '') or birth_metadata.get('name', ''),
                'year': _pick(birth_metadata, birth_data, sp_bd, planets_data, key='year'),
                'month': _pick(birth_metadata, birth_data, sp_bd, planets_data, key='month'),
                'day': _pick(birth_metadata, birth_data, sp_bd, planets_data, key='day'),
                'hour': _pick(birth_metadata, birth_data, sp_bd, planets_data, key='hour'),
                'minute': _pick(birth_metadata, birth_data, sp_bd, planets_data, key='minute'),
                'second': _pick(birth_metadata, birth_data, sp_bd, planets_data, key='second', default=0),
                'gender': birth_metadata.get('gender', ''),
                'latitude': _pick(birth_metadata, birth_data, sp_bd, planets_data, key='latitude',
                                  default=_pick(birth_data, sp_bd, key='lat')),
                'longitude': _pick(birth_metadata, birth_data, sp_bd, planets_data, key='longitude',
                                   default=_pick(birth_data, sp_bd, key='lon')),
                'dst': birth_metadata.get('dst') if birth_metadata.get('dst') is not None
                       else birth_metadata.get('time_change_flag', 0),
                'location': birth_metadata.get('location', {}) or {
                    'city': chart_entry.get('city', ''),
                    'country': chart_entry.get('country', ''),
                    'timezone': (sp_bd.get('iana_timezone') or sp_bd.get('timezone')
                                 or birth_metadata.get('timezone')
                                 or planets_data.get('timezone', '+00:00'))
                }
            }

        self.info_tab.populate_from_chart(planets_data, birth_metadata, chart_entry, birth_data=birth_data)

        # Clear New Chart form so stale data doesn't persist across chart switches
        self.new_chart_tab.clear_form()

        # Load into Map tab
        lat = merged_metadata.get('latitude', 0)
        lon = merged_metadata.get('longitude', 0)
        if lat is not None and lon is not None:
            self.map_tab.set_marker(
                float(lat), float(lon),
                city=merged_metadata.get('city', ''),
                country=merged_metadata.get('country', ''),
            )

    def load_from_gui(self):
        """Load chart data from the current memory panel entry."""
        if not self.gui.state.active_chart:
            return
        mp = getattr(self.gui, 'chart_memory_panel', None) or getattr(self.gui, 'memory_panel', None)
        if mp and 0 <= mp.current_index < len(mp.charts):
            self.load_chart_from_memory(mp.charts[mp.current_index])

    # =========================================================================
    # TAB SYNCHRONIZATION
    # =========================================================================

    @Slot(dict)
    def _on_chart_created(self, chart):
        """
        Handle new chart creation - switch to Edit Info tab to show details.

        Issue 8b-R: payload is now a libaditya Chart (was dict). The handler
        only uses it for tab switching, so the type change is transparent.

        Args:
            chart: The newly built libaditya Chart object
        """
        # Switch to Edit Info tab (index 0) to show the new chart details
        self.sidebar.setCurrentRow(0)

    @Slot(int)
    def _on_tab_switched(self, index: int):
        """
        Handle tab switching - sync data between sub-tabs.

        Args:
            index: New tab index (0=Info, 1=NewChart, 2=Map)
        """
        if index == 2:  # Map tab
            # Auto-detect caller when user clicks Map directly in sidebar
            if self._previous_tab_index == 1:
                self._map_caller = "new_chart"
            elif self._previous_tab_index == 0:
                self._map_caller = "info"
            if self._map_caller == "new_chart":
                form_data = self.new_chart_tab.collect_data()
            else:
                form_data = self.info_tab.collect_data()
            if form_data:
                # SPEC-MAP-002: the basis goes FIRST. set_marker() requests a
                # band scan, so pushing the basis after it would scan the old
                # birth time and then accept that stale result.
                self._push_map_time_basis(form_data)
                lat = form_data.get('latitude')
                lon = form_data.get('longitude')
                if lat is not None and lon is not None:
                    self.map_tab.set_marker(lat, lon)
        self._previous_tab_index = index

    def _push_map_time_basis(self, form_data: dict):
        """Give the map sub-tab the birth civil time, zodiac mode and labels."""
        if not hasattr(self.map_tab, 'set_time_basis'):
            return
        try:
            local_fields = {
                'year': int(form_data['year']), 'month': int(form_data['month']),
                'day': int(form_data['day']), 'hour': int(form_data.get('hour', 0)),
                'minute': int(form_data.get('minute', 0)),
                'second': int(form_data.get('second', 0)),
            }
        except (KeyError, TypeError, ValueError):
            # An incomplete form is not an error here — the picker simply keeps
            # the Ascendant preview switched off (INV-4).
            self.map_tab.set_time_basis(None)
            return

        from core.aditya_mode import displayed_sign_name
        mode = self.gui.state.aditya_mode
        # The label set lives on the GUI (zodiac.use_western_names), NOT on
        # state — and it is orthogonal to the mode (SPEC-ZOD-001). Deriving it
        # from the mode instead is the inversion SPEC-MODE-001 had to fix once
        # already; read the real flag.
        use_western = getattr(self.gui, 'use_western_names', False)
        language = getattr(self.gui, 'sign_language', 'en')
        names = [displayed_sign_name(i, mode, use_western, language)
                 for i in range(12)]

        self.map_tab.set_time_basis(
            local_fields, mode=mode,
            ayanamsa=getattr(self.gui, 'chart_sidereal_ayanamsa_id', 100),
            sign_names=names,
            # A UTC-entered chart has utc_* == local_* by definition; without
            # this the preview subtracted the place's offset and showed an
            # Ascendant a whole UTC offset away from the chart being built.
            utc_input=(form_data.get('time_mode') == 'UTC'))

    # =========================================================================
    # LOCATION UPDATES
    # =========================================================================

    @Slot(float, float)
    def _on_location_changed(self, lat: float, lon: float):
        """Handle location change from Info tab"""
        self.map_tab.set_marker(lat, lon)

    @Slot(float, float, str, str)
    def _on_map_location_selected(self, lat: float, lon: float, city: str, country: str):
        """Route map location to the correct caller tab"""
        target = self.new_chart_tab if self._map_caller == "new_chart" else self.info_tab
        target.set_coordinates(lat, lon)
        if city:
            target.set_city(city)
        if country:
            target.set_country(country)

        # Auto-detect timezone
        tz = self.map_tab.get_detected_timezone()
        if tz:
            target.set_timezone(tz)

        self._mark_modified()

    @Slot()
    def _switch_to_map_view(self):
        """Switch to Map View from Edit Info tab"""
        self._map_caller = "info"
        self.sidebar.setCurrentRow(2)

    @Slot()
    def _switch_to_map_from_new_chart(self):
        """Switch to Map View from New Chart tab"""
        self._map_caller = "new_chart"
        self.sidebar.setCurrentRow(2)

    @Slot()
    def _on_map_apply_return(self):
        """Return to whichever tab requested the map"""
        if self._map_caller == "new_chart":
            self.sidebar.setCurrentRow(1)  # New Chart
        else:
            self.sidebar.setCurrentRow(0)  # Edit Info

    @Slot()
    def _switch_to_edit_info(self):
        """Switch to the Edit Info subtab (index 0)"""
        self.sidebar.setCurrentRow(0)

    # =========================================================================
    # MODIFICATION TRACKING
    # =========================================================================

    @Slot()
    def _mark_modified(self):
        """Mark the chart as having unsaved changes"""
        self.is_modified = True
        self.chart_modified.emit(self.get_modified_data())

    def get_modified_data(self) -> dict:
        """
        Collect current data from the active sub-tab.

        Returns:
            Dict with current chart data
        """
        return self.info_tab.collect_data()

    # =========================================================================
    # SAVE / CANCEL
    # =========================================================================

    @Slot()
    def save_changes(self):
        """
        Save changes back to the chart and optionally to file.

        Implements SPEC-EDIT-001 steps 1-10: collect, validate, UTC convert
        via BirthDataManager, build Chart, update canonical stores, dispatch,
        memory panel, CHTK write-back, finalize, signal.
        """
        try:
            # STEP 1 - Collect
            data = self.info_tab.collect_data()
            if not data:
                QMessageBox.warning(self, "Error", "Could not collect form data")
                return

            # STEP 2 - Validate
            if not self._validate_data(data):
                return

            # STEP 3 - Convert to UTC via BirthDataManager (not inline)
            from managers.birth_data_manager import BirthDataManager

            chtk_path = (
                (self.current_chart_data.get('chtk_path') if self.current_chart_data else None)
                or getattr(self.gui, 'current_chart_path', None)
            )

            # SPEC-IMPORT-001 §6.7 (DST ordering fix): the Edit Info form only
            # exposes the INTEGER dst flag (time_change_flag), never the float
            # dst_offset_hours. For a non-1h-DST source (e.g. Lord Howe Island
            # 0.5h) create_from_form_data would otherwise compute UTC from the
            # integer flag (wrong total offset) and only get the float DST
            # patched back AFTER, leaving utc_* inconsistent with
            # dst_offset_hours. Seed the preserved source float DST into the
            # form dict BEFORE the UTC conversion so the instant is computed
            # with the correct DST from the start (create_from_form_data reads
            # form_data.get('dst_offset_hours'), bead .10). Only seed when the
            # user kept DST ON in the form (flag in (1, 2)): a DST toggle-off or
            # an explicit integer change must win over the stale source float.
            if data.get('dst_offset_hours') is None and data.get('dst') in (1, 2):
                _src_bd = self._source_birth_data(chtk_path)
                _src_dst = _src_bd.get('dst_offset_hours')
                if _src_dst is not None:
                    data['dst_offset_hours'] = float(_src_dst)

            birth_data = BirthDataManager.create_from_form_data(data, chtk_path=chtk_path)

            # SPEC-IMPORT-001 §6.7 (interim metadata preservation): the Edit Info
            # form does NOT expose rodden/tags/notes/julian_day/_toml_extra, so
            # create_from_form_data() returns them as None. Re-merge them from the
            # stored canonical birth_data (the source the chart was loaded from)
            # so a TOML/CHTK round-trip through the editor does not silently drop
            # uneditable fields. Editing civil time/offset legitimately changes
            # the instant, so the stale julian_day is dropped when the civil time
            # or offset moved (recomputed downstream from the new civil fields).
            self._merge_preserved_metadata(birth_data, chtk_path)

            # SPEC-TZ-001 8a: surface timezone warnings, non-blocking
            BirthDataManager.report_tz_warnings(
                BirthDataManager.validate_birth_data(birth_data),
                status_bar=self.gui.statusBar() if self.gui else None,
                context="Edit Chart")

            # STEP 4 - Build Chart (abort on failure)
            _chart = self._recalculate_chart(data, birth_data)
            if _chart is None:
                QMessageBox.critical(self, "Error", "Chart recalculation failed. Changes not saved.")
                return

            # STEP 5 - Update canonical data stores (mirrors chart_manager.load_chart)
            # Honor a carried julian_day (TOML JD-canonical) so gui.birth_jd stays
            # consistent with the Chart built in STEP 4 (SPEC-IMPORT-001 §6.1).
            from core.time_utils import julday
            _stored_jd = birth_data.get('julian_day')
            if _stored_jd is not None:
                birth_jd = float(_stored_jd)
            else:
                hour_decimal = (birth_data['utc_hour']
                                + birth_data['utc_minute'] / 60.0
                                + birth_data['utc_second'] / 3600.0)
                birth_jd = julday(
                    birth_data['utc_year'], birth_data['utc_month'],
                    birth_data['utc_day'], hour_decimal,
                )

            self.gui.birth_jd = birth_jd
            self.gui.birth_lat = birth_data['latitude']
            self.gui.birth_lon = birth_data['longitude']
            self.gui.person_name = birth_data.get('name', '')
            self.gui.current_timezone = birth_data.get('iana_timezone', 'UTC')
            if chtk_path:
                self.gui.current_chart_path = str(chtk_path)
            self.gui._current_chart_data = None
            self.gui._current_birth_data = birth_data

            # Update panel's own copy (used for cancel-reload and signal)
            if self.current_chart_data:
                self.current_chart_data['birth_data'] = birth_data
                self.current_chart_data['person_name'] = birth_data.get('name', '')

            # STEP 7 - Memory panel BEFORE finalize (dasha lazy-rebuild reads recipe)
            if hasattr(self.gui, 'memory_panel'):
                h = birth_data.get('local_hour', 0)
                m = birth_data.get('local_minute', 0)
                s = birth_data.get('local_second', 0)
                self.gui.memory_panel.update_current_chart({
                    'name': birth_data.get('name', ''),
                    'year': birth_data.get('local_year'),
                    'month': birth_data.get('local_month'),
                    'day': birth_data.get('local_day'),
                    'timedec': float(h) + float(m) / 60.0 + float(s) / 3600.0,
                    'utcoffset': birth_data.get('utc_offset_hours', 0.0),
                    'lat': birth_data.get('latitude'),
                    'lon': birth_data.get('longitude'),
                    'city': birth_data.get('city', ''),
                    'country': birth_data.get('country', ''),
                    'timezone': birth_data.get('iana_timezone', '') or data.get('timezone', ''),
                    # SPEC-IMPORT-001 §6.1/§6.7: keep the recipe (serialization
                    # spine) consistent with the merged birth_data. update_
                    # current_chart only writes keys already present in the
                    # recipe, so for TOML charts these update and for CHTK charts
                    # they are no-ops. julian_day was invalidated by _merge_
                    # preserved_metadata when civil/offset changed, so the recipe
                    # never keeps a stale JD after a time edit. (Full recipe-
                    # forwarding across all call sites is bead .6.)
                    'julian_day': birth_data.get('julian_day'),
                    'dst_offset_hours': birth_data.get('dst_offset_hours'),
                    'rodden': birth_data.get('rodden'),
                    'tags': birth_data.get('tags'),
                    'notes': birth_data.get('notes'),
                })

            # STEP 8 - File write-back (if chart was loaded from file)
            # SPEC-IMPORT-001 §6.1 (B5 BLOCKER): gate the writer on the file
            # extension. Calling CHTKWriter unconditionally would write UTF-16
            # CHTK binary over a .toml file (irreversible data loss).
            chtk_write_ok = True
            if chtk_path:
                from pathlib import Path
                p = Path(chtk_path)
                if p.exists():
                    writer, method_name = _writer_for(p)
                    file_label = "TOML" if method_name == "update_toml_birth_data" else "CHTK"
                    try:
                        getattr(writer, method_name)(str(p), birth_data)
                    except Exception as e:
                        chtk_write_ok = False
                        QMessageBox.warning(
                            self, "File Write Error",
                            f"In-memory chart updated, but the {file_label} file "
                            f"could not be saved:\n{e}",
                        )

            # STEP 9 - Refresh UI
            self.gui._finalize_chart_load(skip_varga_reset=True)

            # STEP 10 - Signal and confirm
            self.is_modified = False
            self.chart_saved.emit(str(chtk_path) if chtk_path else '')

            if chtk_write_ok:
                QMessageBox.information(self, "Success", "Chart information updated successfully!")

                # Switch back to the Chart tab after successful save
                if hasattr(self.gui, 'tab_widget') and hasattr(self.gui, 'chart_tab'):
                    chart_idx = self.gui.tab_widget.indexOf(self.gui.chart_tab)
                    if chart_idx >= 0:
                        self.gui.tab_widget.setCurrentIndex(chart_idx)

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save: {e}")

    @Slot()
    def cancel_changes(self):
        """
        Discard changes and reload from original data.
        """
        if self.is_modified:
            reply = QMessageBox.question(
                self, "Discard Changes",
                "Are you sure you want to discard your changes?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        # Reload from original data
        if self.current_chart_data:
            self.load_chart_from_memory(self.current_chart_data)
        else:
            self.load_from_gui()

        self.is_modified = False

    def _validate_data(self, data: dict) -> bool:
        """
        Validate form data before saving.

        Returns:
            True if valid, False otherwise (shows error dialog)
        """
        errors = []

        if not data.get('name', '').strip():
            errors.append("Name is required")

        # Date validation
        month = data.get('month', 0)
        day = data.get('day', 0)
        year = data.get('year', 0)

        if not (1 <= month <= 12):
            errors.append("Month must be 1-12")
        if not (1 <= year <= 9999):
            errors.append("Year must be valid")

        # Month-aware day validation
        if 1 <= month <= 12:
            import calendar
            max_day = calendar.monthrange(year if 1 <= year <= 9999 else 2000, month)[1]
            if not (1 <= day <= max_day):
                errors.append(f"Day must be 1-{max_day} for month {month}")
        elif not (1 <= day <= 31):
            errors.append("Day must be 1-31")

        # Time validation
        hour = data.get('hour', 0)
        minute = data.get('minute', 0)
        second = data.get('second', 0)

        if not (0 <= hour <= 23):
            errors.append("Hour must be 0-23")
        if not (0 <= minute <= 59):
            errors.append("Minute must be 0-59")
        if not (0 <= second <= 59):
            errors.append("Second must be 0-59")

        # Coordinate validation
        lat = data.get('latitude', 0)
        lon = data.get('longitude', 0)

        if not (-90 <= lat <= 90):
            errors.append("Latitude must be -90 to 90")
        if not (-180 <= lon <= 180):
            errors.append("Longitude must be -180 to 180")

        # Timezone validation (only in Local mode; UTC mode needs no offset)
        if data.get('time_mode') != 'UTC':
            tz = data.get('timezone', '')
            if not tz:
                errors.append("Timezone is required")
            elif not tz.startswith(('+', '-')) and '/' not in tz:
                errors.append("Timezone must be in +HH:MM format or an IANA name")

        if errors:
            QMessageBox.warning(self, "Validation Error", "\n".join(errors))
            return False

        return True

    def _source_birth_data(self, chart_path):
        """Recover the canonical birth_data the active chart was loaded from.

        SPEC-IMPORT-001 §6.7 interim preservation needs the as-loaded canonical
        dict to re-supply uneditable metadata (rodden/tags/notes/julian_day/
        dst_offset_hours/_toml_extra) that the Edit Info form never exposes.

        Source priority:
          1. ``current_chart_data['birth_data']`` (set by the legacy load path,
             not yet overwritten at this point in save_changes).
          2. Rebuilt from ``current_chart_data['recipe']`` (the recipe is the
             serialization spine; it carries rodden/tags/notes/julian_day/
             dst_offset_hours but NOT _toml_extra).
          3. For a .toml source, re-read the file so _toml_extra (unknown keys)
             can be preserved — the recipe drops it. update_toml_birth_data also
             re-reads it on write, but seeding it here keeps the in-memory recipe
             and any downstream consumer consistent.

        Returns a dict (possibly empty) — never None.
        """
        src = {}
        cd = self.current_chart_data or {}
        stored_bd = cd.get('birth_data')
        if isinstance(stored_bd, dict) and stored_bd:
            src = dict(stored_bd)
        elif cd.get('recipe'):
            try:
                from core.chart_factory import birth_data_from_recipe
                src = dict(birth_data_from_recipe(cd['recipe']) or {})
            except Exception as exc:  # noqa: BLE001 - degrade, never crash save
                logger.warning("Could not rebuild birth_data from recipe: %s", exc)

        # _toml_extra never travels through the recipe; pull it from the source
        # .toml file so unknown keys round-trip (interim preservation, §6.7).
        from pathlib import Path
        if chart_path and Path(str(chart_path)).suffix.lower() == ".toml":
            # BUG-2 (SPEC-IMPORT-002): prefer the pristine _toml_extra snapshot
            # captured at chart load time over a fresh file read. The file reflects
            # the previous save and progressively sheds unknown TOML keys each
            # edit-save cycle; the snapshot is frozen at load and never degrades.
            if (src.get('_toml_extra') is None
                    and self._loaded_toml_extra is not None
                    and self._loaded_toml_extra_path == str(chart_path)):
                src['_toml_extra'] = self._loaded_toml_extra
            if src.get('_toml_extra') is None:
                # No usable snapshot (chart not opened via the editor, the original
                # had no unknown keys, or the load-time read failed) -> fall back to
                # the file. Also backstops the recipe-carried keys.
                try:
                    from core.toml_chart import TOMLChartReader
                    reread = TOMLChartReader().read_toml_file(
                        str(chart_path), canonicalize=False)
                    for _k in ('_toml_extra', 'rodden', 'tags', 'notes',
                               'julian_day', 'dst_offset_hours'):
                        if src.get(_k) is None and reread.get(_k) is not None:
                            src[_k] = reread[_k]
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Could not re-read .toml source for metadata "
                        "preservation (%s): %s", chart_path, exc)
        return src

    def _merge_preserved_metadata(self, birth_data: dict, chart_path):
        """Re-supply uneditable metadata onto form-derived ``birth_data`` (§6.7).

        The Edit Info form does not expose rodden/tags/notes/julian_day/
        dst_offset_hours/_toml_extra/source_format, so create_from_form_data()
        emits them as None. Merge them back from the as-loaded canonical dict so
        the edit round-trip is non-destructive.

        Hardening:
          - julian_day: dropped (recomputed downstream) when the edit changed the
            local civil time OR the UTC offset, so civil and JD stay consistent.
            An offset-only edit (date/time unchanged but offset moved) therefore
            also triggers recompute.
          - source_format: preserved from the source / inferred from the path so
            the canonical dict's format tag matches the file it will be written to.
          - _toml_extra: when the path is None or the source file is missing, it
            cannot be re-read here (update_toml_birth_data also cannot) — log a
            warning that unknown keys may not be preserved; never crash.
        """
        src = self._source_birth_data(chart_path)

        # Only re-fill keys the form genuinely cannot carry (None == "not edited").
        for key in ('rodden', 'tags', 'notes', 'dst_offset_hours', '_toml_extra'):
            if birth_data.get(key) is None and src.get(key) is not None:
                birth_data[key] = src[key]

        # source_format: trust the actual file extension when we have a path,
        # else keep whatever the source carried (default 'chtk' from the form).
        from pathlib import Path
        if chart_path:
            suffix = Path(str(chart_path)).suffix.lower()
            if suffix == ".toml":
                birth_data['source_format'] = 'toml'
            elif suffix == ".chtk":
                birth_data['source_format'] = 'chtk'
            elif src.get('source_format'):
                birth_data['source_format'] = src['source_format']
        elif src.get('source_format'):
            birth_data['source_format'] = src['source_format']

        # julian_day: keep the source JD ONLY when the instant is unchanged
        # (same local civil fields AND same total offset). Any civil/offset edit
        # invalidates it -> leave it None so the recalc recomputes from civil.
        src_jd = src.get('julian_day')
        if src_jd is not None and self._same_instant(src, birth_data):
            birth_data['julian_day'] = src_jd
        else:
            birth_data['julian_day'] = None

        # _toml_extra guard (Wave-1 Codex): a .toml edit with no usable source
        # path means unknown keys cannot be preserved on write.
        is_toml = bool(chart_path) and \
            Path(str(chart_path)).suffix.lower() == ".toml"
        if is_toml and birth_data.get('_toml_extra') is None:
            if not chart_path or not Path(str(chart_path)).exists():
                logger.warning(
                    "Editing a .toml chart with no readable source file "
                    "(path=%r): unknown TOML keys (_toml_extra) cannot be "
                    "preserved on save.", chart_path)

    @staticmethod
    def _same_instant(src: dict, edited: dict) -> bool:
        """True when ``edited`` has the same local civil time AND total offset.

        Compares the canonical local_* fields and utc_offset_hours (TOTAL offset,
        the convention create_from_form_data uses). A different offset at the same
        wall-clock is a different instant, so a stored JD must not be reused
        (mirrors TOMLChartWriter._same_civil). Source dicts rebuilt from a recipe
        use timedec/year/utcoffset instead of local_*; fall back to those.
        """
        def _local(d):
            if 'local_year' in d:
                return (
                    int(d.get('local_year', 0)), int(d.get('local_month', 0)),
                    int(d.get('local_day', 0)), int(d.get('local_hour', 0)),
                    int(d.get('local_minute', 0)), int(d.get('local_second', 0)),
                )
            # Recipe-shaped source dict (birth_data_from_recipe): year/month/day
            # + timedec (decimal local hours).
            from core.chart_factory import timedec_to_hms
            td = d.get('timedec')
            if td is None:
                return None
            h, m, s = timedec_to_hms(float(td))
            return (
                int(d.get('year', 0)), int(d.get('month', 0)),
                int(d.get('day', 0)), h, m, s,
            )

        def _offset(d):
            o = d.get('utc_offset_hours')
            if o is None:
                o = d.get('utcoffset')
            return None if o is None else round(float(o), 9)

        sl, el = _local(src), _local(edited)
        if sl is None or el is None or sl != el:
            return False
        so, eo = _offset(src), _offset(edited)
        if so is None or eo is None:
            return False
        return so == eo

    def _recalculate_chart(self, data: dict, birth_data: dict = None):
        """
        Build a new Chart from pre-converted birth_data and dispatch it.

        UTC conversion is handled by BirthDataManager.create_from_form_data()
        before this method is called. This method only builds the Chart
        and dispatches the state event.

        Returns:
            The built Chart object, or None on failure.
        """
        try:
            from core.chart_factory import (
                build_chart_from_params, make_source_params,
            )
            from core.time_utils import julday
        except ImportError as e:
            QMessageBox.critical(self, "Import Error", f"Could not import chart_factory: {e}")
            return None

        self.gui.loading_manager.start("Recalculating chart...")
        try:
            if birth_data is None:
                from managers.birth_data_manager import BirthDataManager
                birth_data = BirthDataManager.create_from_form_data(data)
                # SPEC-TZ-001 8a: surface timezone warnings, non-blocking
                BirthDataManager.report_tz_warnings(
                    BirthDataManager.validate_birth_data(birth_data),
                    status_bar=self.gui.statusBar() if self.gui else None,
                    context="Edit Chart")

            # SPEC-IMPORT-001 §6.1/§6.7: honor a carried julian_day (TOML charts
            # are JD-canonical; civil time is advisory). _merge_preserved_metadata
            # has already dropped a stale JD when the civil time or offset changed,
            # so a JD present here is consistent with the (possibly edited) civil
            # fields. When absent (CHTK, or civil/offset edited) recompute from
            # the UTC civil fields as before, preserving sub-second precision only
            # when the file supplied it.
            stored_jd = birth_data.get('julian_day')
            if stored_jd is not None:
                jd = float(stored_jd)
            else:
                hour_decimal = (birth_data['utc_hour']
                                + birth_data['utc_minute'] / 60.0
                                + birth_data['utc_second'] / 3600.0)
                jd = julday(
                    birth_data['utc_year'], birth_data['utc_month'],
                    birth_data['utc_day'], hour_decimal,
                )
            mode = self.gui.state.aditya_mode
            _chart = build_chart_from_params(
                jd=jd,
                lat=birth_data.get('latitude', 0),
                lon=birth_data.get('longitude', 0),
                mode=mode,
                name=birth_data.get('name', ''),
                utcoffset=birth_data.get('utc_offset_hours', 0.0),
                ayanamsa=getattr(self.gui, 'chart_sidereal_ayanamsa_id', 100),
                hsys=self.gui.state.house_system_code,
            )
            QApplication.processEvents()

            # STEP 6 - Dispatch state event
            from state.events import SetActiveChart
            chtk_path = (
                (self.current_chart_data.get('chtk_path') if self.current_chart_data else None)
                or getattr(self.gui, 'current_chart_path', None)
            )
            self.gui.state.dispatch(SetActiveChart(
                chart=_chart,
                source_params=make_source_params(
                    chtk_path=str(chtk_path) if chtk_path else None,
                    birth_data=birth_data,
                    mode=mode,
                    ayanamsa=self.gui.chart_sidereal_ayanamsa_id,
                    house_system=self.gui.state.house_system,
                    is_human_design=getattr(self.gui, 'is_human_design', False),
                )))

            return _chart

        except Exception as e:
            QMessageBox.critical(self, "Calculation Error", f"Error recalculating chart: {e}")
            return None
        finally:
            self.gui.loading_manager.finish()

    # =========================================================================
    # THEME SUPPORT
    # =========================================================================

    def refresh_theme(self):
        """Update colors after theme change"""
        theme = get_theme_colors()
        self.sidebar.setStyleSheet(self._get_sidebar_style())
        self.stack.setStyleSheet(f"background-color: {theme['secondary_dark']};")

        # Refresh sub-tabs
        if hasattr(self.new_chart_tab, 'refresh_theme'):
            self.new_chart_tab.refresh_theme()
        if hasattr(self.info_tab, 'refresh_theme'):
            self.info_tab.refresh_theme()
        if hasattr(self.map_tab, 'refresh_theme'):
            self.map_tab.refresh_theme()
