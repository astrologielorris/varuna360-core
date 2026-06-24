# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Dasha Manager - Handles Vedanga and Vimshottari dasha navigation and display

This module manages:
- Dasha level navigation (1-5)
- 120-year cycle navigation
- Click-to-expand functionality
- Dasha list updates and formatting
- Parent chain tracking for sub-dasha display

Extracted from core_gui_qt.py to reduce complexity and improve maintainability.
"""

from PySide6.QtWidgets import QListWidgetItem, QListWidget, QMenu, QApplication
from PySide6.QtCore import Qt, QTimer

class DashaManager:
    """
    Manages Vedanga and Vimshottari dasha navigation and display.

    This class handles:
    - Level selection (1-5 sub-dasha levels)
    - 120-year cycle navigation (past/current/future)
    - Click-to-expand parent chain tracking
    - List widget population and highlighting

    Heavy GUI operations are delegated back to the main window via self.gui reference.
    """

    def __init__(self, gui):
        """
        Initialize the dasha manager.

        Args:
            gui: The main ChartGUI instance (QMainWindow)
        """
        self.gui = gui
        self.state = gui.state

    # =========================================================================
    # LEVEL MANAGEMENT
    # =========================================================================

    def _auto_build_parent_chain(self, dasha_data, target_level, panel="vimshottari"):
        """Build a parent chain from the current (is_current) dasha entries.

        When the user clicks a level button without having drilled into a
        specific period, this finds the current periods at each depth and
        builds the chain so the focused calc shows the right sub-periods.

        If the cached data doesn't have entries at all needed depths
        (e.g., after a focused calc that only kept 9 sub-period entries),
        recompute a fresh tree at the minimum required depth.
        """
        needed = target_level - 1
        chain = self._extract_current_chain(dasha_data, needed)
        if len(chain) == needed:
            return chain
        if panel == "vedanga":
            ayanamsa = self.gui.vedanga_ayanamsa
        else:
            ayanamsa = self.gui.vimshottari_ayanamsa
        try:
            from core.vimshottari_dasha import calculate_dasha_from_birth_data
            from AI_tools.AI_main_function.dasha import get_dasha_params
            params = get_dasha_params(
                self.gui.current_chart_data,
                is_human_design=self.gui.is_human_design,
            )
            fresh = calculate_dasha_from_birth_data(
                params['year'], params['month'], params['day'],
                params['hour'], params['minute'], params['second'],
                dlevels=needed,
                ayanamsa=ayanamsa,
                tz_offset_hours=params['tz_offset'],
                moon_jd_override=params['moon_jd_override'],
                nak_mode=getattr(self.gui, 'nakshatra_coords', 'neither'),
            )
            chain = self._extract_current_chain(fresh, needed)
        except Exception:
            pass
        return chain

    def _extract_current_chain(self, dasha_data, needed_depth):
        """Extract current lords at each depth from dasha data."""
        if not dasha_data:
            return []
        chain = []
        for depth in range(needed_depth):
            for entry in dasha_data:
                if not entry.get('is_current'):
                    continue
                lord = entry.get('lord', '')
                if lord.count('/') + 1 == depth + 1:
                    chain.append(lord)
                    break
            else:
                break
        return chain

    def set_vedanga_level(self, level):
        """Set Vedanga dasha display level (1-5)"""
        if level == 1:
            self.gui.vedanga_parent_chain = []
        else:
            trimmed = self.gui.vedanga_parent_chain[:level-1]
            if trimmed:
                last_depth = trimmed[-1].count('/') + 1
                if last_depth < level - 1:
                    trimmed = []
            if not trimmed and level >= 2:
                trimmed = self._auto_build_parent_chain(
                    getattr(self.gui, 'vedanga_dasha_data', None), level, panel="vedanga")
            self.gui.vedanga_parent_chain = trimmed
        self.gui.dasha_level_vedanga = level
        if hasattr(self.gui, 'vedanga_level_buttons'):
            for idx, btn in enumerate(self.gui.vedanga_level_buttons):
                btn.setChecked(idx + 1 == level)
        self.update_vedanga_dasha()

    def set_vimshottari_level(self, level):
        """Set Vimshottari dasha display level (1-5)"""
        if level == 1:
            self.gui.vimshottari_parent_chain = []
        else:
            trimmed = self.gui.vimshottari_parent_chain[:level-1]
            if trimmed:
                last_depth = trimmed[-1].count('/') + 1
                if last_depth < level - 1:
                    trimmed = []
            if not trimmed and level >= 2:
                trimmed = self._auto_build_parent_chain(
                    getattr(self.gui, 'vimshottari_dasha_data', None), level)
            self.gui.vimshottari_parent_chain = trimmed
        self.gui.dasha_level_vimshottari = level
        if hasattr(self.gui, 'vimshottari_level_buttons'):
            for idx, btn in enumerate(self.gui.vimshottari_level_buttons):
                btn.setChecked(idx + 1 == level)
        self.update_vimshottari_dasha()

    # =========================================================================
    # CYCLE NAVIGATION
    # =========================================================================

    def navigate_vedanga_previous(self):
        """Navigate to previous 120-year Vedanga cycle"""
        self.gui.dasha_cycle_offset_vedanga -= 1
        self.update_cycle_label_vedanga()
        self.update_vedanga_dasha()

    def navigate_vedanga_next(self):
        """Navigate to next 120-year Vedanga cycle"""
        self.gui.dasha_cycle_offset_vedanga += 1
        self.update_cycle_label_vedanga()
        self.update_vedanga_dasha()

    def navigate_vimshottari_previous(self):
        """Navigate to previous 120-year Vimshottari cycle"""
        self.gui.dasha_cycle_offset_vimshottari -= 1
        self.update_cycle_label_vimshottari()
        self.update_vimshottari_dasha()

    def navigate_vimshottari_next(self):
        """Navigate to next 120-year Vimshottari cycle"""
        self.gui.dasha_cycle_offset_vimshottari += 1
        self.update_cycle_label_vimshottari()
        self.update_vimshottari_dasha()

    # =========================================================================
    # CLICK HANDLERS
    # =========================================================================

    def on_vimshottari_clicked(self, item):
        """Handle click on Vimshottari dasha item to expand or select"""
        entry = item.data(Qt.ItemDataRole.UserRole)
        if not entry:
            return

        clicked_lord = entry.get('lord', '')
        lord_parts = clicked_lord.split('/')
        new_chain = ['/'.join(lord_parts[:i + 1]) for i in range(len(lord_parts))]
        new_level = min(len(new_chain) + 1, 5)

        if new_level > self.gui.dasha_level_vimshottari or self.gui.dasha_level_vimshottari < 5:
            # Can drill deeper — expand
            self.gui.vimshottari_parent_chain = new_chain
            self.set_vimshottari_level(new_level)
            for i, btn in enumerate(self.gui.vimshottari_level_buttons):
                btn.setChecked((i + 1) == new_level)
        else:
            # At max depth — click-select this row instead of expanding
            row = self.gui.vimshottari_list.row(item)
            if hasattr(self.gui, 'vimshottari_delegate'):
                current_sel = self.gui.vimshottari_delegate.selected_row
                # Toggle: click same row again to deselect
                self.gui.vimshottari_delegate.update_selected_row(
                    None if current_sel == row else row
                )
                self.gui.vimshottari_list.viewport().update()

    def on_vedanga_clicked(self, item):
        """Handle click on Vedanga dasha item to expand or select"""
        entry = item.data(Qt.ItemDataRole.UserRole)
        if not entry:
            return

        clicked_lord = entry.get('lord', '')
        lord_parts = clicked_lord.split('/')
        new_chain = ['/'.join(lord_parts[:i + 1]) for i in range(len(lord_parts))]
        new_level = min(len(new_chain) + 1, 5)

        if new_level > self.gui.dasha_level_vedanga or self.gui.dasha_level_vedanga < 5:
            # Can drill deeper — expand
            self.gui.vedanga_parent_chain = new_chain
            self.set_vedanga_level(new_level)
            for i, btn in enumerate(self.gui.vedanga_level_buttons):
                btn.setChecked((i + 1) == new_level)
        else:
            # At max depth — click-select this row instead of expanding
            row = self.gui.vedanga_list.row(item)
            if hasattr(self.gui, 'vedanga_delegate'):
                current_sel = self.gui.vedanga_delegate.selected_row
                self.gui.vedanga_delegate.update_selected_row(
                    None if current_sel == row else row
                )
                self.gui.vedanga_list.viewport().update()

    # =========================================================================
    # SINGLE-CLICK SELECT (move ▶ marker without expanding)
    # =========================================================================

    _PREFIX_CURRENT = '▶ '
    _PREFIX_NORMAL = '  '

    def _select_dasha_entry(self, list_widget, item, delegate_attr,
                            cycle_offset_attr, dasha_data_attr):
        """Move ▶ highlight to the clicked entry (single-click selection).

        Updates is_current in both the list widget entries AND the cached
        dasha_data, so the pill context menu picks up the new selection.
        """
        entry = item.data(Qt.ItemDataRole.UserRole)
        if not entry or not entry.get('jd'):
            return

        cycle_offset = getattr(self.gui, cycle_offset_attr, 0)
        if cycle_offset != 0:
            return

        clicked_level = entry.get('level', 0)
        clicked_jd = entry.get('jd')
        clicked_lord = entry.get('lord')
        highlight_rows = set()

        for row_idx in range(list_widget.count()):
            row_item = list_widget.item(row_idx)
            row_entry = row_item.data(Qt.ItemDataRole.UserRole)
            if not row_entry:
                continue

            row_level = row_entry.get('level', 0)
            text = row_item.text()

            if row_level == clicked_level:
                is_this = (row_item is item)
                row_entry['is_current'] = is_this

                if text.startswith(self._PREFIX_CURRENT) or text.startswith(self._PREFIX_NORMAL):
                    body = text[2:]
                    row_item.setText(
                        (self._PREFIX_CURRENT if is_this else self._PREFIX_NORMAL) + body)
                if is_this:
                    highlight_rows.add(row_idx)
            else:
                if row_entry.get('is_current', False):
                    highlight_rows.add(row_idx)

        delegate = getattr(self.gui, delegate_attr, None)
        if delegate:
            delegate.update_highlights(highlight_rows)
            list_widget.viewport().update()

        dasha_data = getattr(self.gui, dasha_data_attr, None)
        if dasha_data:
            for e in dasha_data:
                if e.get('level', 0) == clicked_level:
                    e['is_current'] = (e.get('jd') == clicked_jd
                                       and e.get('lord') == clicked_lord)

    def on_vimshottari_select(self, item):
        """Single click on Vimshottari: select this period, move ▶ marker."""
        if getattr(self.gui, 'right_dasha_mode', 'nisarga') == 'nisarga':
            return
        self._select_dasha_entry(
            self.gui.vimshottari_list, item,
            'vimshottari_delegate', 'dasha_cycle_offset_vimshottari',
            'vimshottari_dasha_data')

    def on_vedanga_select(self, item):
        """Single click on Vedanga: select this period, move ▶ marker."""
        self._select_dasha_entry(
            self.gui.vedanga_list, item,
            'vedanga_delegate', 'dasha_cycle_offset_vedanga',
            'vedanga_dasha_data')

    # =========================================================================
    # CONTEXT MENU HANDLERS
    # =========================================================================

    def show_dasha_context_menu(self, list_widget, pos, dasha_type):
        """Show right-click context menu for a dasha list item.

        Args:
            list_widget: The QListWidget (vedanga_list or vimshottari_list)
            pos: Position of the right-click
            dasha_type: "vedanga" or "vimshottari" (used for cycle offset)
        """
        item = list_widget.itemAt(pos)
        if not item:
            return

        entry = item.data(Qt.ItemDataRole.UserRole)
        if not entry:
            return

        from ui.qt_theme import get_theme_colors

        theme = get_theme_colors()
        menu = QMenu(list_widget)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {theme["secondary"]};
                color: {theme["secondary_text"]};
                border: 1px solid {theme["secondary_dark"]};
            }}
            QMenu::item:selected {{
                background-color: {theme["secondary_light"]};
            }}
            QMenu::item:disabled {{
                color: {theme["secondary_dark"]};
            }}
        """)

        jd = entry.get('jd')
        if jd is not None:
            if dasha_type == "vedanga":
                cycle_offset = self.gui.dasha_cycle_offset_vedanga
            else:
                cycle_offset = self.gui.dasha_cycle_offset_vimshottari
            if cycle_offset != 0:
                jd = jd + (cycle_offset * 120 * 365.25)

        if not self.gui.has_transit_tab():
            action = menu.addAction("\U0001f512 Open in Transit")
            action.setEnabled(False)
            action.setToolTip("Available in full version")
        else:
            action = menu.addAction("Open in Transit")
            if jd is not None:
                action.triggered.connect(
                    lambda checked, j=jd: self._open_in_transit(j)
                )
            else:
                action.setEnabled(False)

        menu.addSeparator()

        act_chart = menu.addAction("Create chart")
        if jd is not None:
            lord = entry.get('lord', 'Dasha')
            act_chart.triggered.connect(
                lambda checked, j=jd, l=lord: self._create_chart_for_dasha(j, l)
            )
        else:
            act_chart.setEnabled(False)

        act_overlay = menu.addAction("Show as transit overlay")
        if jd is not None and hasattr(self.gui, 'transit_overlay_manager'):
            act_overlay.triggered.connect(
                lambda checked, j=jd: self._show_dasha_as_transit_overlay(j)
            )
        else:
            act_overlay.setEnabled(False)

        menu.exec(list_widget.mapToGlobal(pos))

    def _open_in_transit(self, jd):
        """Open the Transit tab with the chart for a specific Julian Day.

        Args:
            jd: Julian Day number (UTC) for the transit date
        """
        gui = self.gui
        gui.loading_manager.start("Opening in Transit...")

        # Switch to Transit tab
        if hasattr(gui, 'tab_widget'):
            for i in range(gui.tab_widget.count()):
                if gui.tab_widget.tabText(i) == "Transit":
                    gui.tab_widget.setCurrentIndex(i)
                    break
        QApplication.processEvents()

        # Ensure natal chart is loaded and set the transit date
        if hasattr(gui, 'transit_panel') and gui.transit_panel:
            tp = gui.transit_panel

            # Populate dropdown and select the current memory chart
            tp._populate_natal_dropdown()
            if hasattr(gui, 'memory_panel') and gui.memory_panel:
                active_idx = gui.memory_panel.current_index
                for i in range(tp.natal_combo.count()):
                    if tp.natal_combo.itemData(i) == active_idx:
                        tp.natal_combo.setCurrentIndex(i)
                        break

            # Set the transit date (this triggers get_all_planets_data inside transit_panel)
            tp.set_transit_for_date(jd)

        gui.loading_manager.finish()

    def _create_chart_for_dasha(self, jd, lord_name):
        """Create a standalone chart for a dasha period's start date.

        Uses the natal chart's birth location (not current geolocation)
        because the dasha is tied to the natal chart's context.
        """
        gui = self.gui
        natal = gui.state.active_chart
        if not natal:
            return

        from libaditya import swe
        from core.chart_factory import build_chart_from_params, make_recipe, make_source_params
        from state.events import SetActiveChart

        ctx = natal.context
        lat = ctx.location.lat
        lon = ctx.location.long
        natal_bd = getattr(gui, 'current_birth_data', {}) or {}
        city = natal_bd.get('city', '') or ''
        country = natal_bd.get('country', '') or ''
        iana_tz = natal_bd.get('iana_timezone', natal_bd.get('timezone', 'UTC')) or 'UTC'

        local_off = ctx.timeJD.utcoffset if ctx.timeJD else 0.0

        local_jd = jd + local_off / 24.0
        ut_tuple = swe.revjul(local_jd)
        year, month, day = int(ut_tuple[0]), int(ut_tuple[1]), int(ut_tuple[2])
        hour_dec = ut_tuple[3]
        hour = int(hour_dec)
        minute = int((hour_dec - hour) * 60)
        second = int(((hour_dec - hour) * 60 - minute) * 60)

        mode = gui.state.aditya_mode
        ayanamsa = getattr(gui, 'chart_sidereal_ayanamsa_id', 1)
        hsys = getattr(gui, '_house_system_code', 'C')

        chart = build_chart_from_params(
            jd=jd, lat=lat, lon=lon,
            mode=mode, ayanamsa=ayanamsa,
            hsys=hsys, utcoffset=local_off,
        )

        name = f"Dasha {lord_name} {year}-{month:02d}-{day:02d}"
        chart.context.name = name

        recipe = make_recipe(
            name=name,
            year=year, month=month, day=day,
            timedec=hour_dec,
            utcoffset=local_off,
            timezone=iana_tz,
            lat=lat, lon=lon,
            city=city, country=country,
        )

        birth_data = {
            'name': name,
            'year': year, 'month': month, 'day': day,
            'timedec': hour_dec,
            'hour': hour, 'minute': minute, 'second': second,
            'lat': lat, 'lon': lon,
            'utcoffset': local_off,
            'iana_timezone': iana_tz, 'timezone': iana_tz,
            'city': city, 'country': country,
        }

        gui.state.dispatch(SetActiveChart(
            chart=chart,
            source_params=make_source_params(
                chtk_path=None,
                birth_data=birth_data,
                mode=mode,
                ayanamsa=ayanamsa,
                house_system=gui.state.house_system,
                is_human_design=False,
            ),
        ))

        gui.is_human_design = False
        gui.current_chart_path = None
        gui.current_birth_data = birth_data
        gui._current_chart_data = None

        if hasattr(gui, 'chart_memory_panel') and gui.chart_memory_panel:
            gui.chart_memory_panel.add_chart(
                recipe,
                is_transit=True,
                chart_obj=gui.state.active_chart,
            )

        chart_entry = {
            'recipe': recipe,
            'birth_metadata': {},
            'birth_data': birth_data,
            'person_name': name,
            'city': city,
            'country': country,
            'chtk_path': None,
        }
        if hasattr(gui, 'edit_chart_panel') and gui.edit_chart_panel:
            gui.edit_chart_panel.load_chart_from_memory(chart_entry)

        gui._finalize_chart_load()

    def _show_dasha_as_transit_overlay(self, jd):
        """Load a dasha period's start date into the transit overlay."""
        mgr = getattr(self.gui, 'transit_overlay_manager', None)
        if not mgr:
            return
        if not mgr.transit_enabled:
            mgr.enable_transit()
        if not mgr.transit_enabled:
            return
        mgr.lock_to_jd(jd)

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def extract_parent_chain_from_entry(self, entry, all_entries, entry_index):
        """Extract the parent chain for a dasha entry by tracing back through hierarchy"""
        parents = []
        current_indent = len(entry.get('indent', ''))

        # Walk backwards from current entry to find parents
        for i in range(entry_index - 1, -1, -1):
            prev_entry = all_entries[i]
            prev_indent = len(prev_entry.get('indent', ''))

            # Found a parent (less indented)
            if prev_indent < current_indent:
                parents.insert(0, prev_entry.get('lord', ''))
                current_indent = prev_indent

                # Stop when we've found all parents (reached top level)
                if current_indent == 0:
                    break

        return parents

    # =========================================================================
    # KARAKA / LORD HIGHLIGHT HELPERS
    # =========================================================================

    # Map full planet names to dasha abbreviations
    # Also build reverse map for Nisarga entries which store full names
    PLANET_TO_ABBREV = {
        "Sun": "Su", "Moon": "Mo", "Mars": "Ma", "Mercury": "Me",
        "Jupiter": "Ju", "Venus": "Ve", "Saturn": "Sa",
        "Rahu": "Ra", "Ketu": "Ke",
    }

    def get_karaka_planet_abbrev(self, karaka_code):
        """Return the 2-letter dasha abbreviation for the planet holding a karaka role.

        Args:
            karaka_code: 'AK', 'AmK', 'BK', 'MK', 'PiK', 'GK', 'DK'
        Returns:
            Abbreviation like 'Ma' or None if unavailable.
        """
        chart = getattr(self.gui.state, 'active_chart', None)
        if not chart:
            return None

        planet_names = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]
        planet_degrees = []
        planets = chart.rashi().planets()
        for name in planet_names:
            try:
                p = planets[name]
                planet_degrees.append({"name": name, "degree": p.real_in_sign_longitude()})
            except (KeyError, AttributeError):
                continue

        planet_degrees.sort(key=lambda x: x["degree"], reverse=True)
        karaka_order = ["AK", "AmK", "BK", "MK", "PiK", "GK", "DK"]
        try:
            idx = karaka_order.index(karaka_code)
        except ValueError:
            return None
        if idx >= len(planet_degrees):
            return None
        return self.PLANET_TO_ABBREV.get(planet_degrees[idx]["name"])

    def get_house_lord_abbrev(self, house_num, whole_sign=True):
        """Return the 2-letter dasha abbreviation for the lord of a house.

        Args:
            house_num: 1-12
            whole_sign: if True use whole-sign houses, else cusp-based (both use same calc for now)
        Returns:
            Abbreviation like 'Ve' or None.
        """
        chart = getattr(self.gui.state, 'active_chart', None)
        if not chart:
            return None

        asc = chart.rashi().cusps()[1]
        asc_sign_idx = asc.sign() - 1

        if self.gui.state.aditya_mode == "aditya":
            asc_sign = asc_sign_idx
            names = ['Dhata', 'Aryama', 'Mitra', 'Varuna', 'Indra', 'Vivasvan',
                     'Tvasta', 'Vishnu', 'Amzu', 'Bhaga', 'Pusha', 'Parjanya']
        else:
            asc_sign = asc_sign_idx
            names = ['Aries', 'Taurus', 'Gemini', 'Cancer', 'Leo', 'Virgo',
                     'Libra', 'Scorpio', 'Sagittarius', 'Capricorn', 'Aquarius', 'Pisces']

        sign_index = (asc_sign + house_num - 1) % 12
        sign_name = names[sign_index]

        rulers = {
            "Dhata": "Mars", "Aryama": "Venus", "Mitra": "Mercury",
            "Varuna": "Moon", "Indra": "Sun", "Vivasvan": "Mercury",
            "Tvasta": "Venus", "Vishnu": "Mars", "Amzu": "Jupiter",
            "Bhaga": "Saturn", "Pusha": "Saturn", "Parjanya": "Jupiter",
            "Aries": "Mars", "Taurus": "Venus", "Gemini": "Mercury",
            "Cancer": "Moon", "Leo": "Sun", "Virgo": "Mercury",
            "Libra": "Venus", "Scorpio": "Mars", "Sagittarius": "Jupiter",
            "Capricorn": "Saturn", "Aquarius": "Saturn", "Pisces": "Jupiter",
        }
        planet_full = rulers.get(sign_name)
        if not planet_full:
            return None
        return self.PLANET_TO_ABBREV.get(planet_full)

    def compute_lord_highlight_rows(self, list_widget, target_abbrev):
        """Scan displayed list items, return set of row indices whose lord chain
        contains the target planet abbreviation at ANY level.

        Handles both Vimshottari entries (lord='Ma/Ve') and Nisarga entries
        (lord='Mars' full name or None for separators).

        Args:
            list_widget: QListWidget (vedanga_list or vimshottari_list)
            target_abbrev: 2-letter abbreviation like 'Ma'
        Returns:
            set of row indices
        """
        if not target_abbrev:
            return set()
        # Build reverse lookup: full name → abbreviation for Nisarga entries
        full_name_for_abbrev = {v: k for k, v in self.PLANET_TO_ABBREV.items()}
        target_full = full_name_for_abbrev.get(target_abbrev, '')
        rows = set()
        for row_idx in range(list_widget.count()):
            item = list_widget.item(row_idx)
            entry = item.data(Qt.ItemDataRole.UserRole) if item else None
            if not entry:
                continue
            lord = entry.get('lord')
            if not lord:
                continue
            # Check abbreviated form (Vimshottari: 'Ma/Ve/Su')
            parts = lord.split('/')
            if target_abbrev in parts:
                rows.add(row_idx)
            # Check full name form (Nisarga: 'Mars', 'Venus')
            elif target_full and lord == target_full:
                rows.add(row_idx)
        return rows

    def refresh_dasha_lord_highlights(self, panel="vedanga"):
        """Recompute karaka/cusp/WS lord highlights from combo selections and
        push updated row sets to the delegate."""
        if panel == "vedanga":
            list_widget = self.gui.vedanga_list
            delegate = getattr(self.gui, 'vedanga_delegate', None)
            karaka_combo = getattr(self.gui, 'vedanga_karaka_combo', None)
            cusp_combo = getattr(self.gui, 'vedanga_cusp_combo', None)
            ws_combo = getattr(self.gui, 'vedanga_ws_combo', None)
        else:
            list_widget = self.gui.vimshottari_list
            delegate = getattr(self.gui, 'vimshottari_delegate', None)
            karaka_combo = getattr(self.gui, 'vimshottari_karaka_combo', None)
            cusp_combo = getattr(self.gui, 'vimshottari_cusp_combo', None)
            ws_combo = getattr(self.gui, 'vimshottari_ws_combo', None)

        if not delegate:
            return

        # Karaka highlight
        if karaka_combo and karaka_combo.currentIndex() > 0:
            karaka_code = karaka_combo.currentData()
            abbrev = self.get_karaka_planet_abbrev(karaka_code)
            delegate.update_karaka_highlights(self.compute_lord_highlight_rows(list_widget, abbrev))
        else:
            delegate.update_karaka_highlights(set())

        # Cusp lord highlight
        if cusp_combo and cusp_combo.currentIndex() > 0:
            house_num = cusp_combo.currentData()
            abbrev = self.get_house_lord_abbrev(house_num, whole_sign=False)
            delegate.update_cusp_lord_highlights(self.compute_lord_highlight_rows(list_widget, abbrev))
        else:
            delegate.update_cusp_lord_highlights(set())

        # Whole-sign lord highlight
        if ws_combo and ws_combo.currentIndex() > 0:
            house_num = ws_combo.currentData()
            abbrev = self.get_house_lord_abbrev(house_num, whole_sign=True)
            delegate.update_whole_sign_highlights(self.compute_lord_highlight_rows(list_widget, abbrev))
        else:
            delegate.update_whole_sign_highlights(set())

        list_widget.viewport().update()

    def scroll_to_vedanga_row(self, row):
        """Helper to scroll Vedanga list to specific row"""
        if hasattr(self.gui, 'vedanga_list') and self.gui.vedanga_list.count() > row:
            item = self.gui.vedanga_list.item(row)
            if item:
                self.gui.vedanga_list.scrollToItem(item, QListWidget.ScrollHint.PositionAtCenter)

    def scroll_to_vimshottari_row(self, row):
        """Helper to scroll Vimshottari list to specific row"""
        if hasattr(self.gui, 'vimshottari_list') and self.gui.vimshottari_list.count() > row:
            item = self.gui.vimshottari_list.item(row)
            if item:
                self.gui.vimshottari_list.scrollToItem(item, QListWidget.ScrollHint.PositionAtCenter)

    def _age_str(self, date_str, years_to_add=0):
        """Compute 'Xy Zm' age string from birth date to dasha start date.

        Args:
            date_str: Date in 'DD/MM/YYYY' format
            years_to_add: Additional years for 120-year cycle offset
        Returns:
            String like '16y 11m' or '-5y -1m' for pre-birth periods
        """
        try:
            chart = self.gui.current_chart_data
            if not chart:
                return ""
            birth_y = chart.get('year')
            birth_m = chart.get('month')
            birth_d = chart.get('day')
            if not all([birth_y, birth_m, birth_d]):
                return ""

            parts = date_str.split('/')
            if len(parts) != 3:
                return ""
            d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
            y += years_to_add

            # Calculate age in months then convert
            total_months = (y - birth_y) * 12 + (m - birth_m)
            if d < birth_d:
                total_months -= 1

            years = total_months // 12
            months = total_months % 12
            # For negative: keep sign consistent
            if total_months < 0:
                years = -((-total_months) // 12)
                months = -((-total_months) % 12)

            return f"{years}y {months}m"
        except Exception:
            return ""

    def _cycle_range_text(self, offset):
        """Return year-range label for a 120-year dasha cycle offset."""
        start = offset * 120
        end = start + 120
        return f"{start}-{end}y"

    def update_cycle_label_vedanga(self):
        """Update Vedanga cycle indicator label"""
        if hasattr(self.gui, 'vedanga_cycle_label'):
            offset = self.gui.dasha_cycle_offset_vedanga
            self.gui.vedanga_cycle_label.setText(self._cycle_range_text(offset))

    def update_cycle_label_vimshottari(self):
        """Update Vimshottari cycle indicator label"""
        if hasattr(self.gui, 'vimshottari_cycle_label'):
            offset = self.gui.dasha_cycle_offset_vimshottari
            self.gui.vimshottari_cycle_label.setText(self._cycle_range_text(offset))

    # =========================================================================
    # TITLE UPDATE
    # =========================================================================

    def _update_dasha_title(self, panel):
        """Update the dasha panel title button text to reflect the current ayanamsa."""
        from apps.widgets.ayanamsa_dialog import get_ayanamsa_name
        if panel == "vedanga":
            name = get_ayanamsa_name(self.gui.vedanga_ayanamsa)
            if hasattr(self.gui, 'vedanga_title_btn'):
                self.gui.vedanga_title_btn.setText(f"{name}  \u25be")
        else:
            name = get_ayanamsa_name(self.gui.vimshottari_ayanamsa)
            if hasattr(self.gui, 'vimshottari_title_btn'):
                self.gui.vimshottari_title_btn.setText(f"{name}  \u25be")

    # =========================================================================
    # MAIN UPDATE METHODS
    # =========================================================================

    def clear_dasha_panels(self):
        """Clear dasha lists and reset state. Titles are restored by the
        subsequent update_vedanga/vimshottari_dasha calls."""
        if hasattr(self.gui, 'vedanga_list'):
            self.gui.vedanga_list.clear()
        if hasattr(self.gui, 'vimshottari_list'):
            self.gui.vimshottari_list.clear()
        for attr in ('vedanga_cycle_label', 'vimshottari_cycle_label'):
            if hasattr(self.gui, attr):
                getattr(self.gui, attr).setText("")
        self.gui.vedanga_parent_chain = []
        self.gui.vimshottari_parent_chain = []
        self.gui.dasha_level_vedanga = 1
        self.gui.dasha_level_vimshottari = 1
        if hasattr(self.gui, 'dasha_level_nisarga'):
            self.gui.dasha_level_nisarga = 1

    def update_vedanga_dasha(self):
        """Update Vedanga dasha list based on current chart, level, and cycle offset"""
        self._update_dasha_title("vedanga")
        self.gui.vedanga_list.clear()
        if not self.gui.current_chart_data:
            return

        try:
            from core.vimshottari_dasha import calculate_dasha_from_birth_data
            from datetime import datetime, timedelta
            from AI_tools.AI_main_function.dasha import get_dasha_params

            # Get dasha params (handles HD design date computation)
            params = get_dasha_params(
                self.gui.current_chart_data,
                is_human_design=self.gui.is_human_design,
            )
            year, month, day = params['year'], params['month'], params['day']
            hour, minute, second = params['hour'], params['minute'], params['second']
            tz_offset = params['tz_offset']
            moon_jd_override = params['moon_jd_override']
            nak_mode = getattr(self.gui, 'nakshatra_coords', 'neither')

            if not all([year, month, day]):
                return

            # OPTIMIZATION: For levels 3+, use focused calculation if we have parent chain.
            # Focused calc: only use if the last parent is at the right depth.
            # Same logic as Vimshottari (see comment there).
            used_focused_calc = False
            use_focused = False
            if self.gui.dasha_level_vedanga >= 3 and self.gui.vedanga_parent_chain:
                parent_lord = self.gui.vedanga_parent_chain[-1]
                parent_depth = parent_lord.count('/') + 1
                use_focused = (parent_depth >= self.gui.dasha_level_vedanga - 1)
            if use_focused:

                # Try cached data first (fast: 9 entries from previous focused calc)
                parent_entry = None
                if hasattr(self.gui, 'vedanga_dasha_data'):
                    for entry in self.gui.vedanga_dasha_data:
                        if entry.get('lord') == parent_lord:
                            parent_entry = entry
                            break

                if not (parent_entry and 'jd' in parent_entry and 'end_jd' in parent_entry):
                    # Cache miss (e.g., user pressed a level button directly and the
                    # cached data is from a different level). Recompute at just enough
                    # depth to locate the parent entry, NOT at full dlevels which
                    # would generate 50k entries and trigger O(n²) filtering.
                    parent_depth = len(self.gui.vedanga_parent_chain)
                    fresh = calculate_dasha_from_birth_data(
                        year, month, day, hour, minute, second,
                        dlevels=parent_depth,
                        ayanamsa=self.gui.vedanga_ayanamsa,
                        tz_offset_hours=tz_offset,
                        moon_jd_override=moon_jd_override,
                        nak_mode=nak_mode,
                    )
                    for entry in fresh:
                        if entry.get('lord') == parent_lord:
                            parent_entry = entry
                            break

                if parent_entry and 'jd' in parent_entry and 'end_jd' in parent_entry:
                    from core.vimshottari_dasha import calculate_sub_dashas_for_period
                    formatted_dasha = calculate_sub_dashas_for_period(
                        parent_entry['jd'],
                        parent_entry['end_jd'],
                        parent_lord,
                        ayanamsa=self.gui.vedanga_ayanamsa,
                        tz_offset_hours=tz_offset,
                    )
                    used_focused_calc = True
                else:
                    # Absolute fallback: parent chain is invalid, reset to level 1
                    self.gui.vedanga_parent_chain = []
                    self.gui.dasha_level_vedanga = 1
                    if hasattr(self.gui, 'vedanga_level_buttons'):
                        for idx, btn in enumerate(self.gui.vedanga_level_buttons):
                            btn.setChecked(idx == 0)
                    formatted_dasha = calculate_dasha_from_birth_data(
                        year, month, day, hour, minute, second,
                        dlevels=1,
                        ayanamsa=self.gui.vedanga_ayanamsa,
                        tz_offset_hours=tz_offset,
                        moon_jd_override=moon_jd_override,
                        nak_mode=nak_mode,
                    )
            else:
                # Levels 1-2 or no parent chain: use full calculation (already fast)
                formatted_dasha = calculate_dasha_from_birth_data(
                    year, month, day, hour, minute, second,
                    dlevels=self.gui.dasha_level_vedanga,
                    ayanamsa=self.gui.vedanga_ayanamsa,
                    tz_offset_hours=tz_offset,
                    moon_jd_override=moon_jd_override,
                )

            self.gui.vedanga_dasha_data = formatted_dasha

            # Calculate years to shift based on cycle offset
            years_to_add = self.gui.dasha_cycle_offset_vedanga * 120

            # Track which rows should be highlighted (current periods)
            highlight_rows = set()
            display_row = 0  # Counter for displayed rows (after filtering)

            # Disable repaints while populating — prevents scrollbar from growing
            # incrementally as each item is added (causes visual lag at level 4/5).
            # processEvents() is still called periodically so the UI doesn't freeze
            # on large datasets (level 5 = up to 50k entries), but with updates
            # disabled the list won't trigger layout/repaint on each flush.
            self.gui.vedanga_list.setUpdatesEnabled(False)

            # Flat-view cap: showing ALL levels with no parent chain at level 3+
            # generates thousands→tens-of-thousands of items and freezes the UI.
            # Cap the flat display at 500 visible rows; user must drill down for deeper.
            flat_view_cap = 500 if (not self.gui.vedanga_parent_chain and
                                    self.gui.dasha_level_vedanga >= 3) else None

            for i, entry in enumerate(formatted_dasha):
                if i % 100 == 0 and i > 0:
                    QApplication.processEvents()

                entry_indent_level = len(entry.get('indent', '')) // 2

                if len(self.gui.vedanga_parent_chain) > 0:
                    if entry_indent_level != len(self.gui.vedanga_parent_chain):
                        continue
                    if used_focused_calc:
                        entry_parents = self.gui.vedanga_parent_chain
                    else:
                        entry_parents = self.extract_parent_chain_from_entry(entry, formatted_dasha, i)
                    if entry_parents != self.gui.vedanga_parent_chain:
                        continue
                else:
                    if entry_indent_level >= self.gui.dasha_level_vedanga:
                        continue
                    if flat_view_cap is not None and display_row >= flat_view_cap:
                        notice = QListWidgetItem("  … drill down by clicking a period above …")
                        self.gui.vedanga_list.addItem(notice)
                        break

                lord = entry['lord']
                date_str = entry['date']
                time_str = entry['time']
                indent = entry['indent']
                is_current = entry.get('is_current', False)

                # Apply 120-year offset to dates if needed
                if years_to_add != 0 and date_str:
                    try:
                        parts = date_str.split('/')
                        if len(parts) == 3:
                            d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
                            new_year = y + years_to_add
                            date_str = f"{d:02d}/{m:02d}/{new_year}"
                    except (ValueError, IndexError):
                        pass

                age = self._age_str(date_str, years_to_add)

                if is_current and self.gui.dasha_cycle_offset_vedanga == 0:
                    text = f"▶ {indent}{lord:8}  {date_str} {time_str}        {age}"
                    highlight_rows.add(display_row)
                else:
                    text = f"  {indent}{lord:8}  {date_str} {time_str}        {age}"

                item = QListWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, entry)
                self.gui.vedanga_list.addItem(item)
                display_row += 1

            # Re-enable updates and do a single repaint pass
            self.gui.vedanga_list.setUpdatesEnabled(True)

            # Update delegate with rows to highlight
            if hasattr(self.gui, 'vedanga_delegate'):
                self.gui.vedanga_delegate.update_selected_row(None)
                self.gui.vedanga_delegate.update_highlights(highlight_rows)
                self.gui.vedanga_list.viewport().update()

            # Scroll to the DEEPEST current period (most precise match for today).
            if highlight_rows and self.gui.dasha_cycle_offset_vedanga == 0:
                current_row = max(highlight_rows)
                delay_ms = 400 if self.gui.dasha_level_vedanga >= 4 else 150
                QTimer.singleShot(delay_ms, lambda: self.scroll_to_vedanga_row(current_row))

            # Refresh karaka/lord highlights after list is repopulated
            self.refresh_dasha_lord_highlights("vedanga")

        except Exception as e:
            print(f"Error updating Vedanga dasha: {e}")

    def update_vimshottari_dasha(self):
        """Update Vimshottari dasha list based on current chart, level, and cycle offset"""
        self._update_dasha_title("vimshottari")
        self.gui.vimshottari_list.clear()
        if not self.gui.current_chart_data:
            return

        try:
            from core.vimshottari_dasha import calculate_dasha_from_birth_data
            from AI_tools.AI_main_function.dasha import get_dasha_params

            # Get dasha params (handles HD design date computation)
            params = get_dasha_params(
                self.gui.current_chart_data,
                is_human_design=self.gui.is_human_design,
            )
            year, month, day = params['year'], params['month'], params['day']
            hour, minute, second = params['hour'], params['minute'], params['second']
            tz_offset = params['tz_offset']
            moon_jd_override = params['moon_jd_override']
            nak_mode = getattr(self.gui, 'nakshatra_coords', 'neither')

            if not all([year, month, day]):
                return

            # OPTIMIZATION: For levels 3+, use focused calculation if the last
            # parent in the chain is at the right depth. The focused calc computes
            # sub-periods ONE level deeper than the parent. So for level 3, the
            # parent must be at depth 2 (e.g. 'Mo/Ra' = 1 slash = depth 2).
            # If the chain is too shallow (e.g. ['Mo'] at level 3), fall through
            # to the full tree calculation instead of showing wrong-depth data.
            used_focused_calc = False
            use_focused = False
            if self.gui.dasha_level_vimshottari >= 3 and self.gui.vimshottari_parent_chain:
                parent_lord = self.gui.vimshottari_parent_chain[-1]
                parent_depth = parent_lord.count('/') + 1
                use_focused = (parent_depth >= self.gui.dasha_level_vimshottari - 1)
            if use_focused:

                parent_entry = None
                if hasattr(self.gui, 'vimshottari_dasha_data'):
                    for entry in self.gui.vimshottari_dasha_data:
                        if entry.get('lord') == parent_lord:
                            parent_entry = entry
                            break

                if not (parent_entry and 'jd' in parent_entry and 'end_jd' in parent_entry):
                    # Cache miss — recompute at minimal depth to find parent entry
                    parent_depth = len(self.gui.vimshottari_parent_chain)
                    fresh = calculate_dasha_from_birth_data(
                        year, month, day, hour, minute, second,
                        dlevels=parent_depth,
                        ayanamsa=self.gui.vimshottari_ayanamsa,
                        tz_offset_hours=tz_offset,
                        moon_jd_override=moon_jd_override,
                        nak_mode=nak_mode,
                    )
                    for entry in fresh:
                        if entry.get('lord') == parent_lord:
                            parent_entry = entry
                            break

                if parent_entry and 'jd' in parent_entry and 'end_jd' in parent_entry:
                    from core.vimshottari_dasha import calculate_sub_dashas_for_period
                    formatted_dasha = calculate_sub_dashas_for_period(
                        parent_entry['jd'],
                        parent_entry['end_jd'],
                        parent_lord,
                        ayanamsa=self.gui.vimshottari_ayanamsa,
                        tz_offset_hours=tz_offset,
                    )
                    used_focused_calc = True
                else:
                    # Absolute fallback: parent chain invalid, reset to level 1
                    self.gui.vimshottari_parent_chain = []
                    self.gui.dasha_level_vimshottari = 1
                    if hasattr(self.gui, 'vimshottari_level_buttons'):
                        for idx, btn in enumerate(self.gui.vimshottari_level_buttons):
                            btn.setChecked(idx == 0)
                    formatted_dasha = calculate_dasha_from_birth_data(
                        year, month, day, hour, minute, second,
                        dlevels=1,
                        ayanamsa=self.gui.vimshottari_ayanamsa,
                        tz_offset_hours=tz_offset,
                        moon_jd_override=moon_jd_override,
                        nak_mode=nak_mode,
                    )
            else:
                formatted_dasha = calculate_dasha_from_birth_data(
                    year, month, day, hour, minute, second,
                    dlevels=self.gui.dasha_level_vimshottari,
                    ayanamsa=self.gui.vimshottari_ayanamsa,
                    tz_offset_hours=tz_offset,
                    moon_jd_override=moon_jd_override,
                )

            self.gui.vimshottari_dasha_data = formatted_dasha

            # Calculate years to shift based on cycle offset
            years_to_add = self.gui.dasha_cycle_offset_vimshottari * 120

            # Track which rows should be highlighted (current periods)
            highlight_rows = set()
            display_row = 0  # Counter for displayed rows (after filtering)

            # Disable repaints while populating — prevents scrollbar from growing
            # incrementally as each item is added (causes visual lag at level 4/5).
            # processEvents() is still called periodically so the UI doesn't freeze
            # on large datasets (level 5 = up to 50k entries), but with updates
            # disabled the list won't trigger layout/repaint on each flush.
            self.gui.vimshottari_list.setUpdatesEnabled(False)

            flat_view_cap = 500 if (not self.gui.vimshottari_parent_chain and
                                    self.gui.dasha_level_vimshottari >= 3) else None

            for i, entry in enumerate(formatted_dasha):
                if i % 100 == 0 and i > 0:
                    QApplication.processEvents()

                entry_indent_level = len(entry.get('indent', '')) // 2

                if len(self.gui.vimshottari_parent_chain) > 0:
                    if entry_indent_level != len(self.gui.vimshottari_parent_chain):
                        continue
                    if used_focused_calc:
                        entry_parents = self.gui.vimshottari_parent_chain
                    else:
                        entry_parents = self.extract_parent_chain_from_entry(entry, formatted_dasha, i)
                    if entry_parents != self.gui.vimshottari_parent_chain:
                        continue
                else:
                    if entry_indent_level >= self.gui.dasha_level_vimshottari:
                        continue
                    if flat_view_cap is not None and display_row >= flat_view_cap:
                        notice = QListWidgetItem("  … drill down by clicking a period above …")
                        self.gui.vimshottari_list.addItem(notice)
                        break

                lord = entry['lord']
                date_str = entry['date']
                time_str = entry['time']
                indent = entry['indent']
                is_current = entry.get('is_current', False)

                # Apply 120-year offset to dates if needed
                if years_to_add != 0 and date_str:
                    try:
                        parts = date_str.split('/')
                        if len(parts) == 3:
                            d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
                            new_year = y + years_to_add
                            date_str = f"{d:02d}/{m:02d}/{new_year}"
                    except (ValueError, IndexError):
                        pass

                age = self._age_str(date_str, years_to_add)

                if is_current and self.gui.dasha_cycle_offset_vimshottari == 0:
                    text = f"▶ {indent}{lord:8}  {date_str} {time_str}        {age}"
                    highlight_rows.add(display_row)
                else:
                    text = f"  {indent}{lord:8}  {date_str} {time_str}        {age}"

                item = QListWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, entry)
                self.gui.vimshottari_list.addItem(item)
                display_row += 1

            # Re-enable updates and do a single repaint pass
            self.gui.vimshottari_list.setUpdatesEnabled(True)

            # Update delegate with rows to highlight
            if hasattr(self.gui, 'vimshottari_delegate'):
                self.gui.vimshottari_delegate.update_selected_row(None)
                self.gui.vimshottari_delegate.update_highlights(highlight_rows)
                self.gui.vimshottari_list.viewport().update()

            # Scroll to the DEEPEST current period (most precise match for today).
            # max() picks the sub-sub-period, not the L1 header.
            if highlight_rows and self.gui.dasha_cycle_offset_vimshottari == 0:
                current_row = max(highlight_rows)
                delay_ms = 400 if self.gui.dasha_level_vimshottari >= 4 else 150
                QTimer.singleShot(delay_ms, lambda: self.scroll_to_vimshottari_row(current_row))

            # Refresh karaka/lord highlights after list is repopulated
            self.refresh_dasha_lord_highlights("vimshottari")

        except Exception as e:
            print(f"Error updating Vimshottari dasha: {e}")

    # =========================================================================
    # NISARGA DASHA (Natural Planetary Ages)
    # =========================================================================

    def set_nisarga_level(self, level):
        """Set Nisarga dasha display level (1=periods+maturation, 2=sub-periods)."""
        self.gui.dasha_level_nisarga = level
        self.update_nisarga_dasha()

    def update_nisarga_dasha(self):
        """Update the right panel with Nisarga dasha data.

        Level 1: 7 natural periods + separator + 9 maturation ages at bottom
        Level 2: Sub-periods (each main period divided into 12)

        Reuses the Vimshottari list widget (gui.vimshottari_list).
        """
        if hasattr(self.gui, 'vimshottari_title_btn'):
            self.gui.vimshottari_title_btn.setText("Planetary Ages")
        self.gui.vimshottari_list.clear()

        # Clear any leftover highlights
        if hasattr(self.gui, 'vimshottari_delegate'):
            self.gui.vimshottari_delegate.update_highlights(set())
            self.gui.vimshottari_delegate.update_maturation_highlights(set())

        chart = self.gui.current_chart_data
        if not chart:
            return

        birth_y = chart.get('year')
        birth_m = chart.get('month')
        birth_d = chart.get('day')
        if not all([birth_y, birth_m, birth_d]):
            return

        try:
            from core.nisarga_dasha import format_nisarga_level1, format_nisarga_level2

            level = getattr(self.gui, 'dasha_level_nisarga', 1)

            if level == 2:
                entries = format_nisarga_level2(birth_y, birth_m, birth_d)
            else:
                entries = format_nisarga_level1(birth_y, birth_m, birth_d)

            highlight_rows = set()
            maturation_rows = set()

            for i, entry in enumerate(entries):
                item = QListWidgetItem(entry['text'])
                item.setData(Qt.ItemDataRole.UserRole, entry)

                # Make separator rows non-selectable
                if entry.get('is_separator'):
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)

                self.gui.vimshottari_list.addItem(item)

                # Track highlights: primary for current period, gold for maturation
                if entry.get('is_current'):
                    highlight_rows.add(i)
                if entry.get('is_maturation'):
                    maturation_rows.add(i)

            # Update delegate highlights
            if hasattr(self.gui, 'vimshottari_delegate'):
                self.gui.vimshottari_delegate.update_highlights(highlight_rows)
                self.gui.vimshottari_delegate.update_maturation_highlights(maturation_rows)
                self.gui.vimshottari_list.viewport().update()

            # Scroll to current period (prefer period highlight over maturation)
            scroll_rows = highlight_rows if highlight_rows else maturation_rows
            if scroll_rows:
                current_row = min(scroll_rows)
                QTimer.singleShot(100, lambda: self.scroll_to_vimshottari_row(current_row))

            # Refresh karaka/lord highlights after Nisarga list is populated
            self.refresh_dasha_lord_highlights("vimshottari")

        except Exception as e:
            import traceback
            print(f"Error updating Nisarga dasha: {e}")
            traceback.print_exc()

    # =========================================================================
    # SPEC-REM-002 Wave 3 — READ ACCESSORS (read-only snapshots)
    # =========================================================================
    #
    # These getters expose what the dasha panels currently show, so that
    # AppController.read_dasha can return a normalized snapshot to an AI
    # agent without re-running the dasha calculation. They are intentionally
    # defensive: every accessor returns a safe default rather than raising
    # when the GUI is not fully constructed (e.g. unit-test environments,
    # before a chart is loaded).

    def _list_widget_for(self, panel):
        """Resolve the QListWidget for a "left"/"right" panel descriptor."""
        if panel == "left":
            return getattr(self.gui, "vedanga_list", None)
        if panel == "right":
            return getattr(self.gui, "vimshottari_list", None)
        raise ValueError(
            f"Invalid panel {panel!r}; must be 'left' or 'right'"
        )

    def get_current_system(self, panel):
        """Return the active dasha system for a panel.

        - "left" → always "vedanga"
        - "right" → "vimshottari" or "nisarga" depending on
          ``self.gui.right_dasha_mode``
        """
        if panel == "left":
            return "vedanga"
        if panel == "right":
            return getattr(self.gui, "right_dasha_mode", "vimshottari") or "vimshottari"
        raise ValueError(
            f"Invalid panel {panel!r}; must be 'left' or 'right'"
        )

    def get_current_level(self, panel):
        """Return the current depth level for a panel (1-5)."""
        if panel == "left":
            return int(getattr(self.gui, "dasha_level_vedanga", 1) or 1)
        if panel == "right":
            system = self.get_current_system("right")
            if system == "nisarga":
                return int(getattr(self.gui, "dasha_level_nisarga", 1) or 1)
            return int(getattr(self.gui, "dasha_level_vimshottari", 1) or 1)
        raise ValueError(
            f"Invalid panel {panel!r}; must be 'left' or 'right'"
        )

    def get_displayed_rows(self, panel):
        """Snapshot every visible QListWidget entry for a panel.

        Each returned dict contains the row's UserRole data merged with
        a "row_index" and the literal "display_text" the user sees. If
        UserRole is missing (notice rows, separators), only display_text
        and row_index are present.
        """
        list_widget = self._list_widget_for(panel)
        if list_widget is None:
            return []
        rows = []
        try:
            count = list_widget.count()
        except Exception:
            return []
        for i in range(count):
            try:
                item = list_widget.item(i)
            except Exception:
                item = None
            if item is None:
                continue
            try:
                text = item.text()
            except Exception:
                text = ""
            try:
                data = item.data(Qt.ItemDataRole.UserRole)
            except Exception:
                data = None
            snapshot = {"row_index": i, "display_text": text}
            if isinstance(data, dict):
                # Shallow copy so callers cannot mutate the live entry
                snapshot.update(data)
            elif data is not None:
                snapshot["raw"] = repr(data)
            rows.append(snapshot)
        return rows
