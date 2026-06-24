#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Chart Memory Panel - Multi-chart memory with visual selector (PySide6)
Ported from ui/chart_memory_panel.py (CustomTkinter version)

Allows keeping 50-100 charts in memory with quick switching.
Displays 2 rows × 20 columns of chart buttons with pagination.
"""
import uuid
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QGridLayout, QMenu,
    QDialog, QMessageBox, QFileDialog, QApplication, QToolButton
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont, QIcon

# Import centralized theme - uses get_theme_colors() for theme-adaptive styling
from ui.qt_theme import (
    BG, SURFACE, HOVER, BORDER, TEXT_PRIMARY, TEXT_SECONDARY,
    STATUS, get_theme_colors, scaled_px, scaled_area_px, scaled_area_size
)

# Import calculation logic
# Issue 8c: get_all_planets_data import removed; recalculation now goes through
# core.chart_factory (mode-aware Chart at construction time).
# Panel constants
CHART_MEMORY_PANEL_HEIGHT = 70  # Fixed height in pixels
CHART_BUTTON_WIDTH = 95  # Width of each chart button
CHART_BUTTON_HEIGHT = 28  # Height of each chart button
CHART_BUTTON_FONT_SIZE = 11  # Font size for chart names
CHARTS_PER_ROW = 20  # Number of chart buttons per row
NUM_ROWS = 2  # Number of rows to display
CHARTS_PER_PAGE = CHARTS_PER_ROW * NUM_ROWS  # 40 charts per page

class ChartMemoryPanel:
    """
    Manages multiple charts in memory with a visual selector panel (PySide6).
    Shows chart tabs in 2 rows with pagination for large collections.
    """

    def __init__(self, gui):
        """
        Initialize the chart memory panel.

        Args:
            gui: The parent ChartGUI instance
        """
        self.gui = gui

        # Chart memory storage
        self.charts = []  # List of stored chart dicts
        self.current_index = -1  # Currently selected (-1 = none)
        self.current_page = 0  # Current page for pagination

        # Display settings
        self.charts_per_row = CHARTS_PER_ROW
        self.num_rows = NUM_ROWS

        # UI elements (will be created in _create_panel)
        self.panel = None
        self.buttons_container = None
        self.buttons_grid = None
        self.chart_buttons = []  # Keep references to button widgets

        # Pagination controls
        self.prev_btn = None
        self.next_btn = None
        self.page_label = None
        self.count_label = None
        self.clear_btn = None
        self.sort_btn = None
        self.select_btn = None

        # Sort state: cycles through modes
        self.SORT_MODES = ["az", "date", "added"]
        self.SORT_LABELS = {"az": "A→Z", "date": "Date", "added": "Added"}
        self.current_sort_mode = None  # None = unsorted (load order)
        self._insertion_order = []  # Track original add order for "Added" mode

        # Multi-select mode state
        self._select_mode = False
        self._selected_ids = set()

        # Create the panel
        self._create_panel()

    def _create_panel(self):
        """Create the chart selector panel UI."""
        # Get theme colors (adapts to light/dark theme)
        theme = get_theme_colors()

        # Main container
        self.panel = QWidget()
        self.panel.setFixedHeight(CHART_MEMORY_PANEL_HEIGHT)
        self.panel.setStyleSheet(f"""
            QWidget {{
                background-color: {theme["secondary"]};
                border: 1px solid {theme["secondary_dark"]};
            }}
        """)

        layout = QHBoxLayout(self.panel)
        layout.setContentsMargins(5, 3, 5, 3)
        layout.setSpacing(5)

        # === LEFT SIDE: Chart Buttons Area ===
        self.buttons_container = QWidget()
        self.buttons_grid = QGridLayout(self.buttons_container)
        self.buttons_grid.setContentsMargins(0, 0, 0, 0)
        self.buttons_grid.setSpacing(2)
        self.buttons_grid.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        layout.addWidget(self.buttons_container, stretch=1)

        # === RIGHT SIDE: Pagination Controls ===
        pagination_container = QWidget()
        pagination_layout = QHBoxLayout(pagination_container)
        pagination_layout.setContentsMargins(0, 0, 0, 0)
        pagination_layout.setSpacing(8)

        # Load Folder button (modern rounded style)
        self.load_folder_btn = QPushButton("📁 Load Folder")
        self.load_folder_btn.setFixedSize(110, 32)
        self.load_folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.load_folder_btn.setToolTip("Select a folder to load all CHTK files into memory")
        self.load_folder_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme["secondary"]};
                color: {theme["secondary_text"]};
                border: 1px solid {theme["primary"]};
                border-radius: 16px;
                font-size: {scaled_area_px('buttons')}px;
                font-weight: 600;
                padding: 0px 8px;
            }}
            QPushButton:hover {{
                background-color: {theme["primary"]};
                border-color: {theme["primary_light"]};
                color: {theme["secondary_text"]};
            }}
            QPushButton:pressed {{
                background-color: {theme["primary_light"]};
            }}
        """)
        self.load_folder_btn.clicked.connect(self._load_folder_charts)
        pagination_layout.addWidget(self.load_folder_btn)

        # Spacer between open folder and navigation
        pagination_layout.addSpacing(12)

        # Previous page button (modern rounded)
        self.prev_btn = QPushButton("◀")
        self.prev_btn.setFixedSize(38, 32)
        self.prev_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.prev_btn.setEnabled(False)  # Disabled initially
        self.prev_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme["secondary"]};
                color: {theme["secondary_text"]};
                border: 1px solid {theme["secondary_dark"]};
                border-radius: 16px;
                font-size: {scaled_area_px('buttons')}px;
                font-weight: bold;
            }}
            QPushButton:hover:enabled {{
                background-color: {theme["primary"]};
                border-color: {theme["primary_light"]};
                color: {theme["secondary_text"]};
            }}
            QPushButton:pressed {{
                background-color: {theme["primary_light"]};
            }}
            QPushButton:disabled {{
                color: {theme["secondary_text"]};
                background-color: {theme["secondary_dark"]};
                border-color: {theme["secondary_dark"]};
            }}
        """)
        self.prev_btn.clicked.connect(self.prev_page)
        pagination_layout.addWidget(self.prev_btn)

        # Page indicator label (modern rounded pill)
        self.page_label = QLabel("0/0")
        self.page_label.setFixedSize(60, 28)
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_label.setStyleSheet(f"""
            QLabel {{
                color: {theme["secondary_text"]};
                font-size: {scaled_area_px('status')}px;
                font-weight: 600;
                background-color: {theme["secondary"]};
                border: 1px solid {theme["secondary_dark"]};
                border-radius: 14px;
                padding: 2px 0px;
            }}
        """)
        pagination_layout.addWidget(self.page_label)

        # Next page button (modern rounded)
        self.next_btn = QPushButton("▶")
        self.next_btn.setFixedSize(38, 32)
        self.next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.next_btn.setEnabled(False)  # Disabled initially
        self.next_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme["secondary"]};
                color: {theme["secondary_text"]};
                border: 1px solid {theme["secondary_dark"]};
                border-radius: 16px;
                font-size: {scaled_area_px('buttons')}px;
                font-weight: bold;
            }}
            QPushButton:hover:enabled {{
                background-color: {theme["primary"]};
                border-color: {theme["primary_light"]};
                color: {theme["secondary_text"]};
            }}
            QPushButton:pressed {{
                background-color: {theme["primary_light"]};
            }}
            QPushButton:disabled {{
                color: {theme["secondary_text"]};
                background-color: {theme["secondary_dark"]};
                border-color: {theme["secondary_dark"]};
            }}
        """)
        self.next_btn.clicked.connect(self.next_page)
        pagination_layout.addWidget(self.next_btn)

        # Chart count label (modern pill badge)
        self.count_label = QLabel("(0 charts)")
        self.count_label.setStyleSheet(f"""
            QLabel {{
                color: {theme["secondary_text"]};
                font-size: {scaled_area_px('status')}px;
                font-weight: 500;
                background: transparent;
                padding: 0px 6px;
            }}
        """)
        pagination_layout.addWidget(self.count_label)

        # Spacer
        pagination_layout.addSpacing(8)

        # === ACTION BUTTONS BOX (Sort + Clear All) ===
        self.action_box = action_box = QWidget()
        action_box.setFixedSize(248, 58)
        action_box.setStyleSheet(f"""
            QWidget {{
                background-color: {theme["secondary_dark"]};
                border: 1px solid {theme["secondary_dark"]};
                border-radius: 6px;
            }}
        """)
        action_layout = QHBoxLayout(action_box)
        action_layout.setContentsMargins(4, 4, 4, 4)
        action_layout.setSpacing(4)

        # Search button (left of Sort, matches Sort/Clear aesthetic)
        self.search_btn = QPushButton("🔍\nSearch")
        self.search_btn.setFixedSize(56, 50)
        self.search_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.search_btn.setToolTip("Search for charts in database")
        self.search_btn.clicked.connect(lambda: self.gui.search_btn.click())
        self._update_search_button_style()
        action_layout.addWidget(self.search_btn)

        # Sort button (square, 3D style)
        self.sort_btn = QPushButton("Sort\nA→Z")
        self.sort_btn.setFixedSize(56, 50)
        self.sort_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sort_btn.setToolTip("Cycle sort: A→Z → Birth Date → Load Order")
        self._update_sort_button_style()
        self.sort_btn.clicked.connect(self._cycle_sort_mode)
        action_layout.addWidget(self.sort_btn)

        # Clear All button (square, 3D style)
        self.clear_btn = QPushButton("Clear\nAll")
        self.clear_btn.setFixedSize(56, 50)
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.setToolTip("Clear all charts from memory")
        self._update_clear_button_style()
        self.clear_btn.clicked.connect(self._confirm_clear_all)
        action_layout.addWidget(self.clear_btn)

        # Select button (QToolButton for icon-above-text layout)
        _select_icon_path = str(Path(__file__).resolve().parent.parent.parent / "img" / "icons" / "checkbox_check.svg")
        self._select_icon_path = _select_icon_path
        self.select_btn = QToolButton()
        self.select_btn.setText("Select")
        self.select_btn.setIcon(QIcon(_select_icon_path))
        self.select_btn.setIconSize(QSize(scaled_px(14), scaled_px(14)))
        self.select_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        _select_font = self.select_btn.font()
        _select_font.setPointSize(scaled_area_size('buttons'))
        _select_font.setWeight(QFont.Weight.Bold)
        self.select_btn.setFont(_select_font)
        self.select_btn.setFixedSize(56, 50)
        self.select_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.select_btn.setToolTip("Select multiple charts for batch deletion")
        self._update_select_button_style()
        self.select_btn.clicked.connect(self._toggle_select_mode)
        action_layout.addWidget(self.select_btn)

        pagination_layout.addWidget(action_box)

        layout.addWidget(pagination_container)

        # Initial refresh to show empty state
        self.refresh()

        # Compact mode state
        self._compact = False

    def set_compact(self, compact):
        """Switch between compact (tiled) and full layout.

        In compact mode: hides Load Folder, Sort/Clear, and chart count to
        give more room for chart name pills.
        """
        if compact == self._compact:
            return
        self._compact = compact
        if compact and self._select_mode:
            self._exit_select_mode()
        self.load_folder_btn.setVisible(not compact)
        self.action_box.setVisible(not compact)
        self.count_label.setVisible(not compact)

    def add_chart(self, recipe, *, mode=None, ayanamsa=None,
                  chtk_path=None, is_transit=False, chart_obj=None,
                  defer_refresh=False):
        """Add a chart to memory (SPEC-MEM-002 S5).

        Args:
            recipe:    Complete birth recipe (S2.1). REQUIRED.
            mode:      Zodiac mode. Defaults to current GUI mode.
            ayanamsa:  Ayanamsa ID. Defaults to current GUI setting.
            chtk_path: Source CHTK file path, or None.
            is_transit: True for transit/Now charts.
            chart_obj: Pre-built Chart object (cached as _chart).
            defer_refresh: When True, skip the per-add UI refresh.
                Bulk loaders use this to avoid O(N^2) grid rebuilds; the
                caller is responsible for invoking self.refresh() once at end.

        Returns:
            int: Index of the added or existing chart.
        """
        if mode is None:
            mode = self.gui.state.aditya_mode
        if ayanamsa is None:
            ayanamsa = getattr(self.gui, 'chart_sidereal_ayanamsa_id', 1)

        # All keys must be present: heal-on-match (S5.2) does existing.update(chart_entry)
        chart_entry = {
            'id': str(uuid.uuid4()),
            'recipe': dict(recipe),
            'mode': mode,
            'ayanamsa': ayanamsa,
            'chtk_path': chtk_path,
            'is_transit': is_transit,
            '_chart': chart_obj,
            '_built_mode': mode if chart_obj else None,
            '_built_ayanamsa': ayanamsa if chart_obj else None,
            '_built_hsys': recipe.get('house_system', 'campanus') if chart_obj else None,
        }

        # Backward-compat shim fields (SPEC-MEM-002 S12.2d)
        from core.chart_factory import metadata_from_recipe
        _bd, _bm = metadata_from_recipe(recipe)
        chart_entry['person_name'] = recipe['name']
        chart_entry['city'] = recipe['city']
        chart_entry['country'] = recipe['country']
        chart_entry['birth_data'] = _bd
        chart_entry['birth_metadata'] = _bm
        chart_entry['planets_data'] = {}
        chart_entry['aditya_mode'] = mode
        chart_entry['source_params'] = None

        for i, existing in enumerate(self.charts):
            if self._is_same_chart(existing, chart_entry):
                # S5.2 Heal-on-match: the fresh add is authoritative.
                # Without this, a stale persisted recipe (e.g. utcoffset
                # dropped by an old CHTK offset parser, restored from
                # session.json) survives every re-add and select_chart()
                # rebuilds the wrong chart from it (td-971a).
                # id must be set before update() so _insertion_order stays valid
                chart_entry['id'] = existing['id']
                existing.update(chart_entry)
                self.current_index = i
                if not defer_refresh:
                    self._ensure_page_visible(i)
                    self.refresh()
                return i

        self.charts.append(chart_entry)
        self._insertion_order.append(chart_entry['id'])
        self.current_index = len(self.charts) - 1
        if not defer_refresh:
            self._ensure_page_visible(self.current_index)
            self.refresh()
        return self.current_index

    def _is_same_chart(self, entry1, entry2):
        """Check if two entries represent the same birth event (SPEC-MEM-002 S5.1)."""
        r1 = entry1['recipe']
        r2 = entry2['recipe']
        return (
            r1['name'].lower() == r2['name'].lower() and
            r1['year'] == r2['year'] and
            r1['month'] == r2['month'] and
            r1['day'] == r2['day'] and
            abs(r1['timedec'] - r2['timedec']) < 0.002
        )

    def _reset_dasha_state(self):
        """Reset dasha level and parent chains for new chart."""
        self.gui.vedanga_parent_chain = []
        self.gui.vimshottari_parent_chain = []
        self.gui.dasha_level_vedanga = 1
        self.gui.dasha_level_vimshottari = 1
        self.gui.dasha_level_nisarga = 1
        if hasattr(self.gui, 'vedanga_level_buttons'):
            for i, btn in enumerate(self.gui.vedanga_level_buttons):
                btn.setChecked(i == 0)
        if hasattr(self.gui, 'vimshottari_level_buttons'):
            for i, btn in enumerate(self.gui.vimshottari_level_buttons):
                btn.setChecked(i == 0)
        if hasattr(self.gui, 'vedanga_delegate'):
            self.gui.vedanga_delegate.update_selected_row(None)
        if hasattr(self.gui, 'vimshottari_delegate'):
            self.gui.vimshottari_delegate.update_selected_row(None)

    def select_chart(self, index):
        """Select a chart from memory and load it (SPEC-MEM-002 S6)."""
        if not (0 <= index < len(self.charts)):
            return
        entry = self.charts[index]
        self.current_index = index

        self._reset_dasha_state()

        preserved_varga = self.gui.state.current_varga
        preserved_hd = getattr(self.gui, 'is_human_design', False)
        preserved_mode = self.gui.state.aditya_mode

        from core.chart_factory import get_or_build_chart, make_source_params
        _chart = get_or_build_chart(entry, preserved_mode,
                                    self.gui.chart_sidereal_ayanamsa_id,
                                    current_hsys=self.gui.state.house_system)

        recipe = entry['recipe']
        self.gui.person_name = recipe['name']
        self.gui.current_chart_path = entry.get('chtk_path')
        self.gui.birth_jd = _chart.context.timeJD.jd
        self.gui.birth_lat = _chart.context.location.lat
        self.gui.birth_lon = _chart.context.location.long
        self.gui.birth_country = recipe['country']
        self.gui.current_timezone = recipe['timezone']

        _bd = entry.get('birth_data') or entry.get('birth_metadata') or {}
        self.gui._current_chart_data = None
        self.gui._current_birth_data = None

        from state.events import SetActiveChart
        self.gui.state.dispatch(SetActiveChart(
            chart=_chart,
            source_params=make_source_params(
                chtk_path=entry.get('chtk_path'),
                birth_data=_bd,
                mode=preserved_mode,
                ayanamsa=self.gui.chart_sidereal_ayanamsa_id,
                house_system=self.gui.state.house_system,
                is_human_design=preserved_hd,
            ),
        ))

        from state.events import SetZodiacMode, SetVarga
        self.gui.state.dispatch(SetZodiacMode(mode=preserved_mode))

        _did_recalculate = False
        if preserved_hd and hasattr(self.gui, '_recalculate_chart'):
            self.gui.is_human_design = True
            try:
                _did_recalculate = bool(self.gui._recalculate_chart())
            except Exception:
                self.gui.is_human_design = False
        else:
            self.gui.is_human_design = preserved_hd

        if not _did_recalculate:
            self.gui._finalize_chart_load(
                skip_varga_reset=True, skip_dasha=False)

        self.gui.state.dispatch(SetVarga(varga_number=preserved_varga))
        if preserved_varga != 1:
            try:
                self.gui._switch_varga(preserved_varga)
            except Exception:
                self.gui.state.dispatch(SetVarga(varga_number=1))

        if getattr(self.gui, 'right_dasha_mode', 'vimshottari') == 'nisarga':
            self.gui._configure_right_panel_for_nisarga()
        self.refresh()
        if hasattr(self.gui, 'edit_chart_panel') and self.gui.edit_chart_panel:
            self.gui.edit_chart_panel.load_chart_from_memory(entry)

    def remove_chart(self, index):
        """Remove a chart from memory."""
        if 0 <= index < len(self.charts):
            removed_id = self.charts[index].get('id')
            if removed_id in self._insertion_order:
                self._insertion_order.remove(removed_id)
            self.charts.pop(index)

            # Adjust current index
            if self.current_index >= len(self.charts):
                self.current_index = len(self.charts) - 1
            elif self.current_index > index:
                self.current_index -= 1

            # Adjust page if needed
            self._ensure_page_valid()
            self.refresh()

            # Persist the removal to session file
            if hasattr(self.gui, 'session_manager') and self.gui.session_manager:
                self.gui.session_manager.save_session()

    def clear_all(self):
        """Remove all charts from memory."""
        if self._select_mode:
            self._select_mode = False
            self._selected_ids.clear()
            self._restore_action_buttons()
        self.charts.clear()
        self._insertion_order.clear()
        self.current_sort_mode = None
        if self.sort_btn:
            self.sort_btn.setText("Sort\nA→Z")
            self.sort_btn.setToolTip("Cycle sort: A→Z → Birth Date → Load Order")
        self.current_index = -1
        self.current_page = 0
        self.refresh()

        # Persist the cleared state to session file
        if hasattr(self.gui, 'session_manager') and self.gui.session_manager:
            self.gui.session_manager.save_session()

    def get_all_charts(self):
        """
        Return all charts in memory.

        Returns:
            list: List of chart entry dictionaries, each containing:
                - planets_data: Dictionary with planetary positions
                - person_name: Name of the person
                - city, country: Birth location
                - aditya_mode: Zodiac mode
                - birth_metadata: CHTK metadata
                - chtk_path: Path to source file (if any)
        """
        return self.charts

    def get_current_chart(self):
        """
        Return the currently selected chart.

        Returns:
            dict or None: Current chart entry, or None if no chart selected
        """
        if 0 <= self.current_index < len(self.charts):
            return self.charts[self.current_index]
        return None

    def update_current_chart(self, updates: dict):
        """Update the current chart's recipe with new values (SPEC-MEM-002 S7)."""
        if not (0 <= self.current_index < len(self.charts)):
            return False
        entry = self.charts[self.current_index]
        recipe = entry['recipe']

        _KEY_MAP = {
            'latitude': 'lat', 'longitude': 'lon',
            'local_year': 'year', 'local_month': 'month', 'local_day': 'day',
        }
        _has_time_components = any(
            k in updates for k in ('local_hour', 'local_minute', 'local_second')
        )
        for key, value in updates.items():
            mapped = _KEY_MAP.get(key, key)
            if mapped in recipe:
                recipe[mapped] = value
        if _has_time_components:
            from core.chart_factory import timedec_to_hms
            _dh, _dm, _ds = timedec_to_hms(recipe['timedec'])
            _h = updates.get('local_hour', _dh)
            _m = updates.get('local_minute', _dm)
            _s = updates.get('local_second', _ds)
            if _h is not None and _m is not None:
                recipe['timedec'] = float(_h) + float(_m) / 60.0 + float(_s or 0) / 3600.0

        entry['_chart'] = None

        from core.chart_factory import metadata_from_recipe
        _bd, _bm = metadata_from_recipe(recipe)
        entry['person_name'] = recipe['name']
        entry['city'] = recipe['city']
        entry['country'] = recipe['country']
        entry['birth_data'] = _bd
        entry['birth_metadata'] = _bm

        if hasattr(self.gui, '_current_chart_data'):
            self.gui._current_chart_data = None
        if hasattr(self.gui, '_current_birth_data'):
            self.gui._current_birth_data = None

        self.refresh()
        if hasattr(self.gui, 'session_manager') and self.gui.session_manager:
            self.gui.session_manager.save_session()
        return True

    # validate_chart_against_chtk and validate_all_charts removed —
    # an enhanced validator is available in the proprietary edition.
    def _clear_display_only(self):
        """Clear charts from display WITHOUT saving to session.
        Used during profile switching to avoid overwriting the new profile's session.
        """
        if self._select_mode:
            self._select_mode = False
            self._selected_ids.clear()
            self._restore_action_buttons()
        self.charts.clear()
        self._insertion_order.clear()
        self.current_index = -1
        self.current_page = 0
        self.refresh()

    def refresh_theme(self):
        """
        Refresh panel styling when theme changes.
        Called from core_gui_qt.py when user changes theme.
        """
        theme = get_theme_colors()

        # Update main panel background
        self.panel.setStyleSheet(f"""
            QWidget {{
                background-color: {theme["secondary"]};
                border: 1px solid {theme["secondary_dark"]};
            }}
        """)

        # Update action button styles with new theme colors
        if self._select_mode:
            self._exit_select_mode()
        else:
            self._update_search_button_style()
            self._update_sort_button_style()
            self._update_clear_button_style()
            self._update_select_button_style()

        # Update "Load Folder" button styling
        if hasattr(self, 'load_folder_btn'):
            self.load_folder_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {theme["secondary"]};
                    color: {theme["secondary_text"]};
                    border: 1px solid {theme["primary"]};
                    border-radius: 16px;
                    font-size: {scaled_area_px('buttons')}px;
                    font-weight: 600;
                    padding: 0px 8px;
                }}
                QPushButton:hover {{
                    background-color: {theme["primary"]};
                    border-color: {theme["primary_light"]};
                    color: {theme["secondary_text"]};
                }}
                QPushButton:pressed {{
                    background-color: {theme["primary_light"]};
                }}
            """)

        # Update prev/next navigation buttons
        nav_button_style = f"""
            QPushButton {{
                background-color: {theme["secondary"]};
                color: {theme["secondary_text"]};
                border: 1px solid {theme["secondary_dark"]};
                border-radius: 16px;
                font-size: {scaled_area_px('buttons')}px;
                font-weight: bold;
            }}
            QPushButton:hover:enabled {{
                background-color: {theme["primary"]};
                border-color: {theme["primary_light"]};
                color: {theme["secondary_text"]};
            }}
            QPushButton:pressed {{
                background-color: {theme["primary_light"]};
            }}
            QPushButton:disabled {{
                color: {theme["secondary_text"]};
                background-color: {theme["secondary_dark"]};
                border-color: {theme["secondary_dark"]};
            }}
        """

        if hasattr(self, 'prev_btn'):
            self.prev_btn.setStyleSheet(nav_button_style)
        if hasattr(self, 'next_btn'):
            self.next_btn.setStyleSheet(nav_button_style)

        # Update page label styling
        if hasattr(self, 'page_label'):
            self.page_label.setStyleSheet(f"""
                QLabel {{
                    color: {theme["secondary_text"]};
                    font-size: {scaled_area_px('status')}px;
                    font-weight: 600;
                    background-color: {theme["secondary"]};
                    border: 1px solid {theme["secondary_dark"]};
                    border-radius: 14px;
                    padding: 2px 0px;
                }}
            """)

        # SPEC-THM-001 G08: count_label was missing from refresh_theme().
        if hasattr(self, 'count_label') and self.count_label is not None:
            self.count_label.setStyleSheet(f"""
                QLabel {{
                    color: {theme["secondary_text"]};
                    font-size: {scaled_area_px('status')}px;
                    font-weight: 500;
                    background: transparent;
                    padding: 0px 6px;
                }}
            """)

        # SPEC-THM-001 G09: action_box (Sort/Search/Clear container) was missing.
        if hasattr(self, 'action_box') and self.action_box is not None:
            self.action_box.setStyleSheet(f"""
                QWidget {{
                    background-color: {theme["secondary_dark"]};
                    border: 1px solid {theme["secondary_dark"]};
                    border-radius: 6px;
                }}
            """)

        # Regenerate all chart buttons with new theme colors
        self.refresh()

    def refresh(self):
        """Refresh the chart selector display."""
        theme = get_theme_colors()

        # Clear existing buttons
        for btn in self.chart_buttons:
            btn.deleteLater()
        self.chart_buttons.clear()

        # Show empty message if no charts
        if not self.charts:
            empty_label = QLabel("No charts loaded. Load a chart to begin.")
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_label.setStyleSheet(f"""
                QLabel {{
                    color: {theme["secondary_text"]};
                    font-size: {scaled_area_px('status')}px;
                    font-style: italic;
                    background: transparent;
                }}
            """)
            self.buttons_grid.addWidget(empty_label, 0, 0, 1, self.charts_per_row)
            self.chart_buttons.append(empty_label)
            self._update_pagination()
            return

        # Calculate visible range
        start = self.current_page * CHARTS_PER_PAGE
        end = min(start + CHARTS_PER_PAGE, len(self.charts))
        visible_charts = self.charts[start:end]

        # Create grid of buttons
        for i, chart in enumerate(visible_charts):
            actual_index = start + i
            row = i // self.charts_per_row
            col = i % self.charts_per_row

            # Determine button appearance - selected uses accent color
            is_selected = actual_index == self.current_index

            # Truncate name (shorter in select mode to fit checkbox prefix)
            if self._select_mode:
                is_multi_selected = chart.get('id') in self._selected_ids
                prefix = "☑ " if is_multi_selected else "☐ "
                display_name = prefix + self._truncate_name(chart['person_name'].title(), 17)
            else:
                display_name = self._truncate_name(chart['person_name'].title(), 20)

            btn = QPushButton(display_name)
            btn.setFixedSize(CHART_BUTTON_WIDTH, CHART_BUTTON_HEIGHT)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(chart['person_name'].title())

            if self._select_mode:
                # Select mode styling
                if is_multi_selected:
                    btn.setStyleSheet(f"""
                        QPushButton {{
                            background-color: {theme["secondary"]};
                            color: {theme["secondary_text"]};
                            border: 2px solid #FFA726;
                            border-radius: 4px;
                            font-size: {scaled_area_px('sidebar')}px;
                            font-weight: bold;
                            text-align: left;
                            padding: 0px 2px 0px 3px;
                            text-transform: none;
                        }}
                        QPushButton:hover {{
                            background-color: {theme["secondary_light"]};
                            border-color: #FFB74D;
                        }}
                        QPushButton:pressed {{
                            background-color: {theme["secondary_dark"]};
                        }}
                    """)
                else:
                    btn.setStyleSheet(f"""
                        QPushButton {{
                            background-color: {theme["secondary_dark"]};
                            color: {theme["secondary_text"]};
                            border: 1px dashed {theme["secondary_light"]};
                            border-radius: 4px;
                            font-size: {scaled_area_px('sidebar')}px;
                            text-align: left;
                            padding: 0px 2px 0px 3px;
                            text-transform: none;
                        }}
                        QPushButton:hover {{
                            background-color: {theme["secondary_light"]};
                            border: 1px dashed #FFA726;
                        }}
                        QPushButton:pressed {{
                            background-color: {theme["secondary"]};
                        }}
                    """)
                btn.clicked.connect(lambda checked, idx=actual_index: self._toggle_chart_selection(idx))
            else:
                # Normal mode styling
                if is_selected:
                    btn.setStyleSheet(f"""
                        QPushButton {{
                            background-color: {theme["secondary"]};
                            color: {theme["secondary_text"]};
                            border: 2px solid {theme["primary"]};
                            border-radius: 4px;
                            font-size: {scaled_area_px('sidebar')}px;
                            font-weight: bold;
                            text-align: left;
                            padding: 0px 2px 0px 5px;
                            text-transform: none;
                        }}
                        QPushButton:hover {{
                            background-color: {theme["secondary_light"]};
                            border-color: {theme["primary_light"]};
                        }}
                        QPushButton:pressed {{
                            background-color: {theme["secondary_dark"]};
                        }}
                    """)
                else:
                    btn.setStyleSheet(f"""
                        QPushButton {{
                            background-color: {theme["secondary_dark"]};
                            color: {theme["secondary_text"]};
                            border: 1px solid {theme["secondary_light"]};
                            border-radius: 4px;
                            font-size: {scaled_area_px('sidebar')}px;
                            text-align: left;
                            padding: 0px 2px 0px 5px;
                            text-transform: none;
                        }}
                        QPushButton:hover {{
                            background-color: {theme["secondary_light"]};
                            border-color: {theme["primary"]};
                        }}
                        QPushButton:pressed {{
                            background-color: {theme["secondary"]};
                            border-color: {theme["primary"]};
                        }}
                    """)
                btn.clicked.connect(lambda checked, idx=actual_index: self.select_chart(idx))
                btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                btn.customContextMenuRequested.connect(
                    lambda pos, idx=actual_index, b=btn: self._show_context_menu(b, idx, pos)
                )

            # Add to grid
            self.buttons_grid.addWidget(btn, row, col)
            self.chart_buttons.append(btn)

        self._update_pagination()

    def _truncate_name(self, name, max_length):
        """Truncate name to fit button width."""
        if len(name) <= max_length:
            return name
        return name[:max_length - 2] + ".."

    @staticmethod
    def _darken_color(hex_color, factor=0.8):
        """Darken a hex color by multiplying RGB values by factor."""
        hex_color = hex_color.lstrip('#')
        r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
        r, g, b = int(r * factor), int(g * factor), int(b * factor)
        return f"#{r:02x}{g:02x}{b:02x}"

    @staticmethod
    def _lighten_color(hex_color, factor=1.3):
        """Lighten a hex color by multiplying RGB values by factor (capped at 255)."""
        hex_color = hex_color.lstrip('#')
        r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
        r, g, b = min(255, int(r * factor)), min(255, int(g * factor)), min(255, int(b * factor))
        return f"#{r:02x}{g:02x}{b:02x}"

    def _get_3d_button_style(self, base_color, text_color):
        """Generate 3D beveled square button stylesheet."""
        top_edge = self._lighten_color(base_color, 1.4)
        bottom_edge = self._darken_color(base_color, 0.5)
        hover_base = self._lighten_color(base_color, 1.15)
        pressed_base = self._darken_color(base_color, 0.75)
        return f"""
            QPushButton {{
                background-color: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 {self._lighten_color(base_color, 1.2)},
                    stop:0.5 {base_color},
                    stop:1 {self._darken_color(base_color, 0.8)}
                );
                color: {text_color};
                border: 1px solid {bottom_edge};
                border-top: 2px solid {top_edge};
                border-left: 2px solid {top_edge};
                border-right: 2px solid {bottom_edge};
                border-bottom: 2px solid {bottom_edge};
                border-radius: 5px;
                font-size: {scaled_area_px('buttons')}px;
                font-weight: 700;
                padding: 2px;
            }}
            QPushButton:hover {{
                background-color: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 {self._lighten_color(hover_base, 1.2)},
                    stop:0.5 {hover_base},
                    stop:1 {self._darken_color(hover_base, 0.8)}
                );
            }}
            QPushButton:pressed {{
                background-color: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 {self._darken_color(pressed_base, 0.9)},
                    stop:0.5 {pressed_base},
                    stop:1 {self._lighten_color(pressed_base, 1.1)}
                );
                border-top: 2px solid {bottom_edge};
                border-left: 2px solid {bottom_edge};
                border-right: 2px solid {top_edge};
                border-bottom: 2px solid {top_edge};
            }}
        """

    def _update_search_button_style(self):
        """Update Search button styling with 3D beveled square design."""
        from ui.qt_theme import get_theme_accent
        accent = get_theme_accent()
        # SPEC-THM-001 G07: live theme text color (was frozen TEXT_PRIMARY).
        # qt-material's primary_text is white on dark primary, dark on light primary.
        theme = get_theme_colors()
        self.search_btn.setStyleSheet(self._get_3d_button_style(accent["base"], theme["primary_text"]))

    def _update_clear_button_style(self):
        """Update Clear button styling with 3D beveled square design."""
        from ui.qt_theme import STATUS
        error_base = STATUS["error"]
        # SPEC-THM-001 G07: white on red is correct on both themes; use literal.
        self.clear_btn.setStyleSheet(self._get_3d_button_style(error_base, "#FFFFFF"))

    def _update_sort_button_style(self):
        """Update Sort button styling with 3D beveled square design.
        Uses theme accent color — follows selected qt-material theme."""
        from ui.qt_theme import get_theme_accent
        accent = get_theme_accent()
        # SPEC-THM-001 G07: live theme text color (was frozen TEXT_PRIMARY).
        theme = get_theme_colors()
        self.sort_btn.setStyleSheet(self._get_3d_button_style(accent["base"], theme["primary_text"]))

    def _update_pagination(self):
        """Update pagination controls and labels."""
        total_charts = len(self.charts)
        total_pages = max(1, (total_charts + CHARTS_PER_PAGE - 1) // CHARTS_PER_PAGE)
        current_page_display = self.current_page + 1 if total_charts > 0 else 0

        # Update page label
        self.page_label.setText(f"{current_page_display}/{total_pages}")

        # Update count label
        self.count_label.setText(f"({total_charts} charts)")

        # Enable/disable navigation buttons
        self.prev_btn.setEnabled(self.current_page > 0)
        self.next_btn.setEnabled(self.current_page < total_pages - 1)

    def prev_page(self):
        """Go to previous page."""
        if self.current_page > 0:
            self.current_page -= 1
            self.refresh()

    def next_page(self):
        """Go to next page."""
        total_pages = max(1, (len(self.charts) + CHARTS_PER_PAGE - 1) // CHARTS_PER_PAGE)
        if self.current_page < total_pages - 1:
            self.current_page += 1
            self.refresh()

    def _ensure_page_visible(self, index):
        """Ensure the chart at given index is on the visible page."""
        target_page = index // CHARTS_PER_PAGE
        if target_page != self.current_page:
            self.current_page = target_page

    def _ensure_page_valid(self):
        """Ensure current page is valid after chart removal."""
        total_pages = max(1, (len(self.charts) + CHARTS_PER_PAGE - 1) // CHARTS_PER_PAGE)
        if self.current_page >= total_pages:
            self.current_page = max(0, total_pages - 1)

    def _show_context_menu(self, button, index, pos):
        """Show right-click context menu for chart button."""
        theme = get_theme_colors()
        menu = QMenu(button)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {theme["secondary"]};
                color: {theme["secondary_text"]};
                border: 1px solid {theme["secondary_dark"]};
            }}
            QMenu::item:selected {{
                background-color: {theme["secondary_light"]};
            }}
        """)

        menu.addSeparator()

        remove_action = menu.addAction("Remove from memory")
        remove_action.triggered.connect(lambda: self._remove_and_reselect(index))

        menu.addSeparator()

        clear_action = menu.addAction("Clear all charts")
        clear_action.triggered.connect(self._confirm_clear_all)

        menu.exec(button.mapToGlobal(pos))

    def _remove_and_reselect(self, index):
        """Remove chart and load the chart now at current_index."""
        was_current = (index == self.current_index)
        self.remove_chart(index)
        if was_current and self.charts and 0 <= self.current_index < len(self.charts):
            self.select_chart(self.current_index)

    def _cycle_sort_mode(self):
        """Cycle through sort modes: A→Z → Date → Added (load order)."""
        if not self.charts:
            return

        if self.current_sort_mode is None:
            self.current_sort_mode = "az"
        else:
            idx = self.SORT_MODES.index(self.current_sort_mode)
            self.current_sort_mode = self.SORT_MODES[(idx + 1) % len(self.SORT_MODES)]

        self._apply_sort()
        label = self.SORT_LABELS[self.current_sort_mode]
        self.sort_btn.setText(f"Sort\n{label}")
        self.sort_btn.setToolTip(f"Current: {label} | Click to cycle")

    def _apply_sort(self):
        """Sort self.charts according to current_sort_mode, preserving selection."""
        if not self.charts or self.current_sort_mode is None:
            return

        # Remember which chart is currently selected
        selected_id = None
        if 0 <= self.current_index < len(self.charts):
            selected_id = self.charts[self.current_index].get('id')

        if self.current_sort_mode == "az":
            self.charts.sort(key=lambda c: c.get('recipe', {}).get('name', '').lower())
        elif self.current_sort_mode == "date":
            def birth_sort_key(c):
                r = c.get('recipe', {})
                if r.get('year') is not None:
                    return (r['year'], r['month'], r['day'], float(r['timedec']))
                return (9999, 12, 31, 23.99)
            self.charts.sort(key=birth_sort_key)
        elif self.current_sort_mode == "added":
            # Restore original insertion order using _insertion_order
            order_map = {cid: i for i, cid in enumerate(self._insertion_order)}
            self.charts.sort(key=lambda c: order_map.get(c.get('id'), 9999))

        # Restore selection to the same chart
        if selected_id:
            for i, c in enumerate(self.charts):
                if c.get('id') == selected_id:
                    self.current_index = i
                    break

        self._ensure_page_visible(self.current_index)
        self.refresh()

    # ── Multi-select mode ──────────────────────────────────────────────

    def _toggle_select_mode(self):
        if self._select_mode:
            self._exit_select_mode()
        else:
            self._enter_select_mode()

    def _enter_select_mode(self):
        if not self.charts:
            return
        self._select_mode = True
        self._selected_ids.clear()

        # Swap Search → Select All
        self.search_btn.setText("Select\nAll")
        self.search_btn.setToolTip("Select all charts (toggle)")
        try:
            self.search_btn.clicked.disconnect()
        except RuntimeError:
            pass
        self.search_btn.clicked.connect(self._select_all_charts)

        # Swap Sort → Delete (count)
        self.sort_btn.setText("Delete\n(0)")
        self.sort_btn.setToolTip("Delete selected charts")
        self.sort_btn.setEnabled(False)
        try:
            self.sort_btn.clicked.disconnect()
        except RuntimeError:
            pass
        self.sort_btn.clicked.connect(self._delete_selected_charts)
        self._update_delete_button_style()

        # Swap Clear All → Cancel
        self.clear_btn.setText("Cancel")
        self.clear_btn.setToolTip("Exit selection mode")
        try:
            self.clear_btn.clicked.disconnect()
        except RuntimeError:
            pass
        self.clear_btn.clicked.connect(self._exit_select_mode)
        from ui.qt_theme import get_theme_accent
        accent = get_theme_accent()
        theme = get_theme_colors()
        self.clear_btn.setStyleSheet(
            self._get_3d_button_style(accent["base"], theme["primary_text"]))

        # Repurpose Select button as Invert in select mode
        self.select_btn.setIcon(QIcon())
        self.select_btn.setText("Invert")
        self.select_btn.setToolTip("Invert selection (swap selected/unselected)")
        try:
            self.select_btn.clicked.disconnect()
        except RuntimeError:
            pass
        self.select_btn.clicked.connect(self._invert_selection)
        self._update_select_button_active_style()
        self.refresh()

    def _restore_action_buttons(self):
        """Restore all action buttons to normal-mode text, connections, and styles."""
        # Restore Search
        self.search_btn.setText("\U0001f50d\nSearch")
        self.search_btn.setToolTip("Search for charts in database")
        try:
            self.search_btn.clicked.disconnect()
        except RuntimeError:
            pass
        self.search_btn.clicked.connect(lambda: self.gui.search_btn.click())
        self._update_search_button_style()

        # Restore Sort
        label = self.SORT_LABELS.get(self.current_sort_mode, "A→Z")
        self.sort_btn.setText(f"Sort\n{label}")
        self.sort_btn.setToolTip("Cycle sort: A→Z → Birth Date → Load Order")
        self.sort_btn.setEnabled(True)
        try:
            self.sort_btn.clicked.disconnect()
        except RuntimeError:
            pass
        self.sort_btn.clicked.connect(self._cycle_sort_mode)
        self._update_sort_button_style()

        # Restore Clear All
        self.clear_btn.setText("Clear\nAll")
        self.clear_btn.setToolTip("Clear all charts from memory")
        try:
            self.clear_btn.clicked.disconnect()
        except RuntimeError:
            pass
        self.clear_btn.clicked.connect(self._confirm_clear_all)
        self._update_clear_button_style()

        # Restore Select (with SVG icon, icon-above-text)
        self.select_btn.setIcon(QIcon(self._select_icon_path))
        self.select_btn.setIconSize(QSize(scaled_px(14), scaled_px(14)))
        self.select_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.select_btn.setText("Select")
        self.select_btn.setToolTip("Select multiple charts for batch deletion")
        try:
            self.select_btn.clicked.disconnect()
        except RuntimeError:
            pass
        self.select_btn.clicked.connect(self._toggle_select_mode)
        self._update_select_button_style()

    def _exit_select_mode(self):
        self._select_mode = False
        self._selected_ids.clear()
        self._restore_action_buttons()
        self.refresh()

    def _toggle_chart_selection(self, index):
        if not (0 <= index < len(self.charts)):
            return
        chart_id = self.charts[index].get('id')
        if not chart_id:
            return
        if chart_id in self._selected_ids:
            self._selected_ids.discard(chart_id)
        else:
            self._selected_ids.add(chart_id)
        self._update_delete_count()
        self.refresh()

    def _select_all_charts(self):
        all_ids = {c.get('id') for c in self.charts if c.get('id')}
        if self._selected_ids == all_ids:
            self._selected_ids.clear()
        else:
            self._selected_ids.clear()
            self._selected_ids.update(all_ids)
        self._update_delete_count()
        self.refresh()

    def _invert_selection(self):
        all_ids = {c.get('id') for c in self.charts if c.get('id')}
        inverted = all_ids - self._selected_ids
        self._selected_ids.clear()
        self._selected_ids.update(inverted)
        self._update_delete_count()
        self.refresh()

    def _update_delete_count(self):
        count = len(self._selected_ids)
        self.sort_btn.setText(f"Delete\n({count})")
        self.sort_btn.setToolTip(f"Delete {count} selected chart(s) across all pages")
        self.sort_btn.setEnabled(count > 0)

    def _delete_selected_charts(self):
        self._selected_ids &= {c.get('id') for c in self.charts if c.get('id')}
        count = len(self._selected_ids)
        if count == 0:
            return

        reply = QMessageBox.question(
            self.panel,
            "Delete Selected Charts",
            f"Remove {count} chart(s) from memory?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        selected_chart_id = None
        if 0 <= self.current_index < len(self.charts):
            selected_chart_id = self.charts[self.current_index].get('id')

        surviving = [c for c in self.charts if c.get('id') not in self._selected_ids]
        self.charts[:] = surviving
        self._insertion_order[:] = [
            oid for oid in self._insertion_order if oid not in self._selected_ids]

        if selected_chart_id and selected_chart_id not in self._selected_ids:
            for i, c in enumerate(self.charts):
                if c.get('id') == selected_chart_id:
                    self.current_index = i
                    break
        else:
            self.current_index = max(-1, min(self.current_index, len(self.charts) - 1))

        self._ensure_page_valid()
        self._exit_select_mode()

        if self.charts and 0 <= self.current_index < len(self.charts):
            self.select_chart(self.current_index)

        if hasattr(self.gui, 'session_manager') and self.gui.session_manager:
            self.gui.session_manager.save_session()

    def _get_3d_toolbutton_style(self, base_color, text_color):
        style = self._get_3d_button_style(base_color, text_color).replace(
            "QPushButton", "QToolButton")
        return style.replace(
            "padding: 2px;",
            "padding: 0px;\n                margin: 0px;")

    def _update_select_button_style(self):
        from ui.qt_theme import get_theme_accent
        accent = get_theme_accent()
        theme = get_theme_colors()
        self.select_btn.setStyleSheet(
            self._get_3d_toolbutton_style(accent["base"], theme["primary_text"]))

    def _update_select_button_active_style(self):
        self.select_btn.setStyleSheet(
            self._get_3d_toolbutton_style("#4CAF50", "#FFFFFF"))

    def _update_delete_button_style(self):
        from ui.qt_theme import STATUS
        error_base = STATUS["error"]
        self.sort_btn.setStyleSheet(
            self._get_3d_button_style(error_base, "#FFFFFF"))

    def _confirm_clear_all(self):
        """Show confirmation before clearing all charts."""
        if not self.charts:
            return  # Nothing to clear

        reply = QMessageBox.question(
            self.panel,
            "Clear All Charts",
            f"Clear all {len(self.charts)} charts from memory?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.clear_all()

    def _get_default_folder(self):
        """Get the first configured chart folder via SettingsManager."""
        from managers.settings_manager import get_settings

        try:
            s = get_settings()
            folders = s.get_chart_folders()
            for folder in folders:
                if folder and Path(folder).exists():
                    return folder
        except Exception:
            pass

        return str(Path.home())

    def _load_folder_charts(self):
        """Open folder picker dialog and load all CHTK files from selected folder."""
        default_folder = self._get_default_folder()

        folder_path = QFileDialog.getExistingDirectory(
            self.panel,
            "Select Folder Containing CHTK Files",
            default_folder,
            QFileDialog.Option.ShowDirsOnly
        )

        if not folder_path:
            return

        result = self.load_folder_charts_from_path(folder_path)
        ok = result.get("ok", False)
        loaded = result.get("loaded", 0)
        failed = result.get("failed", 0)
        total = result.get("total_in_folder", 0)
        cancelled = result.get("cancelled", False)

        # ok=False signals a load-level error (e.g., folder does not exist).
        # Show the reason directly instead of falling through to the misleading
        # "No charts found" branch.
        if not ok:
            reason = result.get("reason", "Unknown error")
            QMessageBox.warning(
                self.panel, "Load Folder Failed",
                f"Could not load folder:\n{reason}",
                QMessageBox.StandardButton.Ok
            )
            return

        # User declined the confirmation dialog: no further message needed.
        if cancelled:
            return

        if loaded > 0:
            message = f"Loaded {loaded} chart(s) from folder"
            if failed > 0:
                message += f"\n({failed} file(s) failed to load)"
            QMessageBox.information(
                self.panel, "Charts Loaded", message,
                QMessageBox.StandardButton.Ok
            )
        elif failed > 0:
            QMessageBox.warning(
                self.panel, "Load Failed",
                f"Failed to load any charts from:\n{folder_path}",
                QMessageBox.StandardButton.Ok
            )
        elif total == 0:
            QMessageBox.information(
                self.panel, "No Charts Found",
                f"No .chtk files found in:\n{folder_path}",
                QMessageBox.StandardButton.Ok
            )

    # Soft thresholds for folder loading.
    # WARN_THRESHOLD: surface a "this might take a while" confirmation dialog.
    # SOFT_CAP: surface a stronger warning but still proceed if the user agrees.
    LOAD_FOLDER_WARN_THRESHOLD = 100
    LOAD_FOLDER_SOFT_CAP = 500
    # Drain the Qt event loop every N additions so deleteLater() targets are
    # actually destroyed and the GUI stays responsive. With deferred refresh
    # there are no per-add widgets to destroy, but BirthDataManager still
    # produces small UI events worth flushing.
    LOAD_FOLDER_EVENT_FLUSH_INTERVAL = 20

    def load_folder_charts_from_path(self, folder_path, *, skip_confirmation=False):
        """Batch-load all CHTK files from a folder path.

        Uses BirthDataManager (canonical path) for each file to ensure
        correct coordinates, timezone, and UTC offset.

        Bulk-load optimisation: add_chart is called with defer_refresh=True,
        so the panel grid is rebuilt ONCE at the end instead of once per
        chart (avoids the O(N^2) refresh storm that crashed at ~300 charts).
        QApplication.processEvents() runs every LOAD_FOLDER_EVENT_FLUSH_INTERVAL
        to keep the GUI responsive and let deleteLater queues drain.

        Args:
            folder_path: Absolute path to a folder containing .chtk files.
            skip_confirmation: When True (used by automated callers like the
                remote control), suppress BOTH the >WARN_THRESHOLD and
                >SOFT_CAP confirmation dialogs and load every file found.

        Returns:
            dict: {
                "ok": bool,
                "loaded": int,         # successfully added charts
                "failed": int,         # files that errored during load
                "total_in_folder": int,
                "cancelled": bool,     # True iff user declined a dialog
                "over_cap": bool,      # True iff total > SOFT_CAP
            }
        """
        from managers.birth_data_manager import BirthDataManager
        from core.chart_factory import make_recipe

        folder = Path(folder_path)
        if not folder.exists() or not folder.is_dir():
            return {
                "ok": False,
                "loaded": 0,
                "failed": 0,
                "total_in_folder": 0,
                "cancelled": False,
                "over_cap": False,
                "reason": f"folder does not exist: {folder_path}",
            }

        chtk_files = sorted(folder.glob("*.chtk"))
        total = len(chtk_files)
        if total == 0:
            return {
                "ok": True,
                "loaded": 0,
                "failed": 0,
                "total_in_folder": 0,
                "cancelled": False,
                "over_cap": False,
            }

        over_cap = total > self.LOAD_FOLDER_SOFT_CAP

        if not skip_confirmation:
            if over_cap:
                # Stronger warning above the soft cap. The user explicitly
                # chose "load anyway" semantics, so this still allows it.
                reply = QMessageBox.question(
                    self.panel,
                    "Very large folder",
                    f"This folder contains {total} CHTK files, which exceeds the "
                    f"recommended limit of {self.LOAD_FOLDER_SOFT_CAP}.\n\n"
                    f"Loading this many charts will use significant memory and "
                    f"may make the application slow.\n\nLoad all of them anyway?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return {
                        "ok": True,
                        "loaded": 0,
                        "failed": 0,
                        "total_in_folder": total,
                        "cancelled": True,
                        "over_cap": True,
                    }
            elif total > self.LOAD_FOLDER_WARN_THRESHOLD:
                reply = QMessageBox.question(
                    self.panel,
                    "Large folder",
                    f"This folder contains {total} CHTK files.\n\n"
                    f"Loading this many charts may take a while. Continue?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return {
                        "ok": True,
                        "loaded": 0,
                        "failed": 0,
                        "total_in_folder": total,
                        "cancelled": True,
                        "over_cap": False,
                    }

        # Show the shared loading overlay so a large bulk load reads as
        # "working" instead of a frozen window. start()/finish() are
        # ref-counted and nest safely with the final load_chart() below, so we
        # pair exactly one start() with one finish() (in the finally). All the
        # early returns above happen before this point, so they need no
        # teardown.
        loading_active = (
            hasattr(self, 'gui')
            and hasattr(self.gui, 'loading_manager')
            and self.gui.loading_manager is not None
        )
        if loading_active:
            self.gui.loading_manager.start(f"Loading {total} charts from folder...")
            self.gui.loading_manager.set_progress(0, total)
            # Paint the overlay before the (blocking) load loop begins.
            QApplication.processEvents()

        try:
            loaded_count = 0
            failed_count = 0
            # Track the LAST genuinely-new chart's stable id, not its integer
            # position. Two reasons:
            #   1) add_chart() returns the existing index when it dedups; tracking
            #      that as "last added" would auto-activate an already-loaded
            #      chart at the end of the load.
            #   2) QApplication.processEvents() below lets the user click Remove
            #      or Clear All mid-load. An integer index becomes stale (wrong
            #      chart at best, IndexError at worst). A chart id survives
            #      list-shifting because we resolve it by linear scan at the end.
            last_added_id = None

            for i, chtk_file in enumerate(chtk_files):
                try:
                    bd = BirthDataManager.create_birth_data_from_chtk(str(chtk_file))
                    # SPEC-TZ-001 8a: console only (status bar would spam on bulk load)
                    BirthDataManager.report_tz_warnings(
                        BirthDataManager.validate_birth_data(bd),
                        context=f"Memory:{getattr(chtk_file, 'name', chtk_file)}")
                    local_h = bd.get('local_hour', 0)
                    local_m = bd.get('local_minute', 0)
                    local_s = bd.get('local_second', 0)
                    timedec = local_h + local_m / 60.0 + local_s / 3600.0
                    _recipe = make_recipe(
                        name=bd.get('name', 'Unknown'),
                        year=bd.get('local_year', bd['utc_year']),
                        month=bd.get('local_month', bd['utc_month']),
                        day=bd.get('local_day', bd['utc_day']),
                        timedec=timedec,
                        utcoffset=bd.get('utc_offset_hours', 0.0),
                        timezone=bd.get('iana_timezone', 'UTC'),
                        lat=bd.get('latitude', 0.0),
                        lon=bd.get('longitude', 0.0),
                        city=bd.get('city', ''),
                        country=bd.get('country', ''),
                        gender=bd.get('gender', 'Unknown'),
                        time_change_flag=bd.get('time_change_flag', 0),
                    )
                    pre_len = len(self.charts)
                    idx = self.add_chart(
                        _recipe,
                        chtk_path=str(chtk_file),
                        defer_refresh=True,
                    )
                    # Only treat this as "last added" if a new entry was actually
                    # appended (not a duplicate hit returning an existing index).
                    if len(self.charts) > pre_len:
                        last_added_id = self.charts[idx]['id']
                    loaded_count += 1
                except Exception as e:
                    failed_count += 1
                    print(f"[LOAD FOLDER] Failed: {chtk_file.name}: {e}")

                if loading_active:
                    self.gui.loading_manager.set_progress(i + 1, total)

                # Drain pending Qt events periodically so the GUI stays responsive
                # and queued deleteLater targets actually die.
                if (i + 1) % self.LOAD_FOLDER_EVENT_FLUSH_INTERVAL == 0:
                    QApplication.processEvents()

            # Resolve the tracked id back to a CURRENT index. The list may have
            # shifted during processEvents() (user clicked Remove) or shrunk
            # entirely (user clicked Clear All). If the tracked chart is gone,
            # we safely skip the final auto-activation.
            last_added_idx = -1
            if last_added_id is not None:
                for i, entry in enumerate(self.charts):
                    if entry.get('id') == last_added_id:
                        last_added_idx = i
                        break

            # Rebuild the grid ONCE now that all charts are in.
            if last_added_idx >= 0:
                self._ensure_page_visible(last_added_idx)
            self.refresh()

            if last_added_idx >= 0:
                last_entry = self.charts[last_added_idx]
                chtk_path = last_entry.get('chtk_path')
                if chtk_path:
                    self.gui.load_chart(chtk_path)

            return {
                "ok": True,
                "loaded": loaded_count,
                "failed": failed_count,
                "total_in_folder": total,
                "cancelled": False,
                "over_cap": over_cap,
            }
        finally:
            # Always tear the overlay down. A stuck overlay would be worse
            # than the silent load this fix replaces.
            if loading_active:
                self.gui.loading_manager.finish()

def create_chart_memory_panel(gui):
    """
    Factory function to create chart memory panel.

    Args:
        gui: The parent ChartGUI instance

    Returns:
        QWidget: The panel widget
    """
    panel_instance = ChartMemoryPanel(gui)

    # Store reference to panel instance on gui
    gui.memory_panel_instance = panel_instance

    # Also store chart storage directly on gui for compatibility
    gui.memory_charts = panel_instance.charts
    gui.current_chart_index = panel_instance.current_index
    gui.current_page = panel_instance.current_page

    return panel_instance.panel
