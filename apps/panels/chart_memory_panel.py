#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Chart Memory Panel - Multi-chart memory with visual selector (PySide6)
Ported from ui/chart_memory_panel.py (CustomTkinter version)

Allows keeping 50-100 charts in memory with quick switching.
Displays the page's 40 charts as chips in one two-row tray, with paging
(SPEC-MEM-004 "Single Tray", widgets in apps/widgets/memory_pane).
"""
import uuid
from pathlib import Path
from PySide6.QtWidgets import (
    QLabel,
    QMenu,
    QWidgetAction,
    QMessageBox,
    QFileDialog,
    QApplication,
)
from PySide6.QtCore import Qt

# Import centralized theme - uses get_theme_colors() for theme-adaptive styling
from ui.qt_theme import (
    get_theme_colors,
    scaled_area_px,
)

# Import calculation logic
# Issue 8c: get_all_planets_data import removed; recalculation now goes through
# core.chart_factory (mode-aware Chart at construction time).
# Panel constants. The strip's geometry lives in apps/widgets/memory_pane
# (SPEC-MEM-004, "Single Tray"); only the paging constants stay here.
NUM_ROWS = 2  # Chip rows in the tray
# Charts per page before the tray has a width. Once shown, a page holds
# exactly what the tray shows (2 rows x visible columns, SPEC-MEM-004 v1.1):
# no chip is ever hidden and the tray never scrolls.
CHARTS_PER_PAGE = 40
CHARTS_PER_ROW = CHARTS_PER_PAGE // NUM_ROWS


def _stamp(entry):
    """Mark this entry as changed NOW (SPEC-SES-002 §4.5).

    Stamped on real mutation only — created, edited, healed — and NEVER on
    save. That distinction is the whole mechanism: if a save stamped every
    entry, no deletion record could ever be newer than the entry it deletes,
    every delete would lose to the other instance's next tick, and the file
    would oscillate forever. The spec calls it the single easiest way to
    build this wrong.

    Two things read it: the cross-instance merge (newer wins) and the
    favorites sync (a star older than a live edit may not revert it). Both
    fail CLOSED on a missing stamp, so an unstamped entry is safe — it just
    cannot win an argument.
    """
    from datetime import datetime, timezone
    entry['updated_at'] = datetime.now(timezone.utc).isoformat()
    return entry


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
        self.page_size = CHARTS_PER_PAGE  # follows the tray's capacity

        # Display settings
        self.charts_per_row = CHARTS_PER_ROW
        self.num_rows = NUM_ROWS

        # UI elements (will be created in _create_panel)
        self.panel = None
        self.buttons_container = None
        self.chart_buttons = []  # Keep references to button widgets

        # Pagination controls
        self.nav_pad = None  # ◀ ▶ pages, ▲ ▼ viewed-chart history
        # Viewed-chart history (back / forward across profiles, this run only)
        from core.chart_view_history import ChartViewHistory
        self.view_history = ChartViewHistory()
        self.count_label = None
        self.clear_btn = None
        self.sort_btn = None
        self.select_btn = None

        # Sort state: cycles through modes
        self.SORT_MODES = ["az", "date", "added"]
        self.SORT_LABELS = {"az": "A→Z", "date": "Date", "added": "Added"}
        self.current_sort_mode = None  # None = unsorted (load order)
        self._insertion_order = []  # Track original add order for "Added" mode
        # SPEC-SES-002 INV-3/INV-4: every removal leaves a record, or the
        # merge resurrects the chart from the other instance's copy. Drained
        # into session.json by save_session and merged from there.
        self.tombstones = []

        # Multi-select mode state
        self._select_mode = False
        self._selected_ids = set()

        # Create the panel
        self._create_panel()

    # Texts of the pill cells: (icon, full label, short label, icon-step label).
    # Labels and tooltips are the approved mockup's (MC-INTENT).
    _LOAD_TIP = "Load folder: load every .chtk chart file of a folder into this profile"

    def _create_panel(self):
        """Create the chart memory pane ("Single Tray", SPEC-MEM-004).

        The widgets (apps/widgets/memory_pane) only draw and report clicks;
        every behaviour stays in this class. The old attribute names point at
        the new controls so callers keep working: ``panel`` is the strip,
        ``buttons_container`` the chip tray (the recorder's privacy target),
        ``load_folder_btn`` the round LOAD key, ``search_btn`` / ``sort_btn`` /
        ``select_btn`` / ``clear_btn`` the four pill cells, ``more_btn`` the ⋯
        cell, ``action_box`` the 2x2 block and ``count_label`` the profile well.
        """
        from apps.widgets.chart_nav_pad import ChartNavPad
        from apps.widgets.memory_pane.strip import MemoryPaneStrip

        # Chart D-pad: LEFT / RIGHT = pages of this list, UP / DOWN = back /
        # forward through the charts viewed this session, across profiles.
        self.nav_pad = ChartNavPad()
        self.nav_pad.pressed_dir.connect(self._on_nav_pad)

        self.strip = MemoryPaneStrip(self.nav_pad)
        self.panel = self.strip
        self.buttons_container = self.strip.tray
        self.well = self.strip.well
        self.count_label = self.strip.well
        self.action_box = self.strip.actions

        self.load_folder_btn = self.strip.well.load_key
        self.load_folder_btn.setToolTip(self._LOAD_TIP)
        self.load_folder_btn.clicked.connect(self._load_folder_charts)

        acts = self.strip.actions
        self.search_btn = acts.search_cell
        self.sort_btn = acts.sort_cell
        self.select_btn = acts.select_cell
        self.clear_btn = acts.clear_cell
        self.more_btn = acts.more_cell
        # One dispatcher per cell: what a cell does depends on Select mode,
        # so nothing is disconnected / reconnected on mode changes.
        self.search_btn.clicked.connect(self._on_search_cell)
        self.sort_btn.clicked.connect(self._on_sort_cell)
        self.select_btn.clicked.connect(self._toggle_select_mode)
        self.clear_btn.clicked.connect(self._on_clear_cell)
        self.more_btn.clicked.connect(self._show_more_menu)
        self.more_btn.setToolTip("More actions")
        self.strip.step_changed.connect(self._on_step_changed)
        self.strip.tray.capacity_changed.connect(self._on_capacity_changed)
        self._refresh_queued = False

        self._compact = False
        self._profile_names = {}
        self._fit_controls()
        self._update_action_cells()

        # Initial refresh to show empty state
        self.refresh()

    def _fit_controls(self):
        """Re-read the font areas: chip, cell and key fonts, and the widths
        that grow with them (td-80vqm: a bigger area must not clip text)."""
        for cell in self.strip.actions.cells():
            cell.apply_font()
        self.load_folder_btn.apply_font()
        self.strip.well.setStyleSheet(
            "#memoryProfileWell { font-size: %dpx; }" % scaled_area_px('buttons'))
        self.strip.apply_step(self.strip.step, force=False)

    def _on_step_changed(self, _step):
        self._update_action_cells()
        self.refresh()

    def _on_capacity_changed(self, capacity):
        """The tray now shows ``capacity`` chips: re-page so the open chart
        (or else the first chart shown) stays on screen, then redraw once."""
        capacity = max(1, int(capacity))
        if capacity == self.page_size:
            return
        start = self.current_page * self.page_size
        if start <= self.current_index < start + self.page_size:
            anchor = self.current_index
        else:
            anchor = start
        self.page_size = capacity
        self.current_page = max(0, anchor) // capacity
        self._ensure_page_valid()
        if not self._refresh_queued:
            # Coalesce: a window drag crosses many widths in one event pass.
            self._refresh_queued = True
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self._queued_refresh)

    def _queued_refresh(self):
        self._refresh_queued = False
        self.refresh()

    def set_compact(self, compact):
        """Kept for the window's responsive pass (core_gui_qt).

        The pane no longer hides anything when the window is narrow: the
        strip picks its width step itself (S0-S3, SPEC-MEM-004) and every
        control stays visible or moves into the ⋯ menu. Lorris's bug was
        exactly this method hiding Load, the count and the actions.
        """
        self._compact = bool(compact)

    # -- action cells -------------------------------------------------------

    def _sort_label(self):
        return self.SORT_LABELS.get(self.current_sort_mode, "A→Z").upper()

    def _update_action_cells(self):
        """Labels, colours and tooltips of the four cells for the mode."""
        from apps.widgets.memory_pane.actions import DANGER, PLAIN, PRIMARY_ICON
        sel = self._select_mode
        if sel:
            n = len(self._selected_ids)
            self.search_btn.set_content("mp_chk", "ALL", "ALL", "")
            self.search_btn.setToolTip("Select all charts (toggle)")
            self.sort_btn.set_content("mp_trash", f"DELETE {n}", f"DEL {n}", f"{n}", DANGER)
            self.sort_btn.setToolTip(f"Delete {n} selected chart(s) across all pages")
            self.sort_btn.setEnabled(n > 0)
            self.clear_btn.set_content("mp_chk", "INVERT", "INVERT", "")
            self.clear_btn.setToolTip("Invert selection (swap selected/unselected)")
            self.select_btn.setToolTip("Select mode is on: click to leave it")
        else:
            label = self._sort_label()
            self.search_btn.set_content("mp_search", "SEARCH", "SEARCH", "", PRIMARY_ICON)
            self.search_btn.setToolTip("Search the chart database")
            self.sort_btn.set_content("mp_sort", f"SORT {label}", label, label, PRIMARY_ICON)
            self.sort_btn.setToolTip(
                f"Sort: {self.SORT_LABELS.get(self.current_sort_mode, 'A→Z')}. "
                "Click to cycle A→Z, Date, Added")
            self.sort_btn.setEnabled(True)
            self.clear_btn.set_content("mp_trash", "CLEAR ALL", "CLEAR", "", DANGER)
            self.clear_btn.setToolTip("Clear all charts from the list (asks to confirm)")
            self.select_btn.setToolTip("Select charts to remove (toggle)")
        self.select_btn.set_content("mp_chk", "SELECT", "SELECT", "", PLAIN)
        self.select_btn.active = sel
        self.select_btn.update()
        self.more_btn.dot = sel and self.strip.step.folded
        self.more_btn.update()

    def _on_search_cell(self):
        if self._select_mode:
            self._select_all_charts()
        else:
            self.gui.search_btn.click()

    def _on_sort_cell(self):
        if self._select_mode:
            self._delete_selected_charts()
        else:
            self._cycle_sort_mode()

    def _on_clear_cell(self):
        if self._select_mode:
            self._invert_selection()
        else:
            self._confirm_clear_all()

    def _build_more_menu(self):
        """The ⋯ menu (S3): Select, the sort order pick list, Clear all…"""
        menu = QMenu(self.panel)
        menu.setStyleSheet(self._menu_style())
        sel = menu.addAction("Select charts to remove")
        sel.setCheckable(True)
        sel.setChecked(self._select_mode)
        sel.triggered.connect(lambda _c=False: self._toggle_select_mode())
        if self._select_mode:
            n = len(self._selected_ids)
            menu.addAction("Select all").triggered.connect(
                lambda _c=False: self._select_all_charts())
            menu.addAction("Invert selection").triggered.connect(
                lambda _c=False: self._invert_selection())
            delete = menu.addAction(f"Delete selected ({n})")
            delete.setEnabled(n > 0)
            delete.triggered.connect(lambda _c=False: self._delete_selected_charts())
        menu.addSeparator()
        head = menu.addAction("SORT ORDER")
        head.setEnabled(False)
        for mode, name in (("az", "Sort A→Z"), ("date", "Sort by date"),
                           ("added", "Sort by added")):
            act = menu.addAction(name)
            act.setCheckable(True)
            act.setChecked(self.current_sort_mode == mode)
            act.triggered.connect(lambda _c=False, m=mode: self._set_sort_mode(m))
        menu.addSeparator()
        # "Clear all…" in red (QSS cannot reach one QAction): a widget row.
        from apps.widgets.memory_pane.actions import DangerMenuRow
        row = DangerMenuRow("Clear all…", menu)
        clear = QWidgetAction(menu)
        clear.setText("Clear all…")
        clear.setDefaultWidget(row)
        row.chosen.connect(clear.trigger)
        row.chosen.connect(menu.close)
        clear.triggered.connect(lambda _c=False: self._confirm_clear_all())
        menu.addAction(clear)
        return menu

    def _show_more_menu(self):
        menu = self._build_more_menu()
        btn = self.more_btn
        menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))
        menu.deleteLater()  # one menu per opening, freed after it closes

    def _menu_style(self):
        from apps.widgets.memory_pane.tokens import pane_tokens
        tok = pane_tokens()

        def rgba(c):
            return f"rgba({c.red()},{c.green()},{c.blue()},{c.alphaF():.3f})"
        return f"""
            QMenu {{ background-color: {rgba(tok["menu_fill"])};
                     color: {tok["primary_text"].name()};
                     border: 1px solid {rgba(tok["hair"])}; border-radius: 8px;
                     padding: 4px; }}
            QMenu::item {{ padding: 4px 12px 4px 22px; border-radius: 5px; }}
            QMenu::item:selected {{ background-color: {tok["primary"].name()};
                                    color: {tok["on_primary"].name()}; }}
            QMenu::item:disabled {{ color: {tok["muted"].name()}; }}
            QMenu::separator {{ height: 1px; margin: 4px 6px;
                                background: {rgba(tok["hair"])}; }}
        """
    def add_chart(self, recipe, *, mode=None, ayanamsa=None,
                  chtk_path=None, is_transit=False, chart_obj=None,
                  defer_refresh=False, kind=None):
        """Add a chart to memory (SPEC-MEM-002 S5).

        Args:
            recipe:    Complete birth recipe (S2.1). REQUIRED.
            mode:      Zodiac mode. Defaults to current GUI mode.
            ayanamsa:  Ayanamsa ID. Defaults to current GUI setting.
            chtk_path: Source CHTK file path, or None.
            is_transit: True for transit/Now charts (legacy spelling of
                kind="transit"; ignored when ``kind`` is given).
            chart_obj: Pre-built Chart object (cached as _chart).
            defer_refresh: When True, skip the per-add UI refresh.
                Bulk loaders use this to avoid O(N^2) grid rebuilds; the
                caller is responsible for invoking self.refresh() once at end.
            kind:      What the chart is (core.chart_kind.KINDS): "birth"
                (default), or an event kind. Sets ``is_transit`` too.

        Returns:
            int: Index of the added or existing chart.
        """
        if mode is None:
            mode = self.gui.state.aditya_mode
        if ayanamsa is None:
            ayanamsa = getattr(self.gui, 'chart_sidereal_ayanamsa_id', 100)

        from core.chart_kind import is_transit_kind, resolve_kind
        kind = resolve_kind(kind, is_transit)

        # All keys must be present: heal-on-match (S5.2) does existing.update(chart_entry)
        chart_entry = {
            'id': str(uuid.uuid4()),
            'recipe': dict(recipe),
            'mode': mode,
            'ayanamsa': ayanamsa,
            'chtk_path': chtk_path,
            'kind': kind,
            'is_transit': is_transit_kind(kind),
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
        # A new chart is a mutation, and so is the heal-on-match below: it
        # replaces the stored recipe wholesale, so the stamp travels with it
        # through existing.update() and the other instance sees a newer entry.
        _stamp(chart_entry)

        for i, existing in enumerate(self.charts):
            if self._is_same_chart(existing, chart_entry):
                # S5.2 Heal-on-match: the fresh add is authoritative.
                # Without this, a stale persisted recipe (e.g. utcoffset
                # dropped by an old CHTK offset parser, restored from
                # session.json) survives every re-add and select_chart()
                # rebuilds the wrong chart from it (td-971a).
                # id must be set before update() so _insertion_order stays valid
                chart_entry['id'] = existing['id']
                # A saved birth chart is never demoted by an incidental match
                # (e.g. Exploration "Load in main" on the base moment of the
                # chart it was opened from): Find Chart would stop finding it.
                if existing.get('kind') == 'birth' and chart_entry['kind'] != 'birth':
                    chart_entry['kind'] = 'birth'
                    chart_entry['is_transit'] = False
                existing.update(chart_entry)
                self.current_index = i
                if not defer_refresh:
                    self._ensure_page_visible(i)
                    self.refresh()
                    self._record_view(existing)
                return i

        self.charts.append(chart_entry)
        self._insertion_order.append(chart_entry['id'])
        self.current_index = len(self.charts) - 1
        if not defer_refresh:
            self._ensure_page_visible(self.current_index)
            self.refresh()
            self._record_view(chart_entry)
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
        """Reset dasha navigation for a new chart (decision 2, SPEC-DSH-002):
        clear ALL navigation through the manager (both sides' levels/chains/
        offsets, Nisarga level, ZR drill) — the wrapper also clears the two list
        delegates' selection highlight. Only the level-button visuals are set
        here."""
        self.gui.dasha_manager.reset_for_chart()
        # w3-2 D-W3-4: reset_for_chart() now resets the level buttons
        # (sync_level_buttons, its last statement) AND clears both list delegates'
        # selection highlight — the two loops and the two update_selected_row(None)
        # writes that used to live here are gone (they duplicated it).

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
                # SPEC-ECL-002 section 6 (td-n3h3.8 7d): the ONLY writer of
                # origin_memory_id. Marks the active chart as dispatched from
                # this memory entry; edit/new-chart paths construct fresh
                # source_params without the key.
                origin_memory_id=entry.get('id'),
            ),
        ))

        from state.events import SetZodiacMode, SetVarga, SetHumanDesignMode
        self.gui.state.dispatch(SetZodiacMode(mode=preserved_mode))

        # Stage 2 td-ltha: is_human_design is owned by AppState — dispatch the
        # restored HD flag instead of writing self.gui.is_human_design directly.
        _did_recalculate = False
        if preserved_hd and hasattr(self.gui, '_recalculate_chart'):
            self.gui.state.dispatch(SetHumanDesignMode(enabled=True))
            try:
                _did_recalculate = bool(self.gui._recalculate_chart())
            except Exception:
                self.gui.state.dispatch(SetHumanDesignMode(enabled=False))
        else:
            self.gui.state.dispatch(SetHumanDesignMode(enabled=bool(preserved_hd)))

        if not _did_recalculate:
            self.gui._finalize_chart_load(
                skip_varga_reset=True, skip_dasha=False)

        self.gui.state.dispatch(SetVarga(varga_number=preserved_varga))
        if preserved_varga != 1:
            try:
                self.gui._switch_varga(preserved_varga)
            except Exception:
                self.gui.state.dispatch(SetVarga(varga_number=1))

        # Right panel keeps its shape; _finalize_chart_load above already
        # re-listed it for the current mode via the dispatcher (SPEC-ZR-001 §3.6).
        self.refresh()
        if hasattr(self.gui, 'edit_chart_panel') and self.gui.edit_chart_panel:
            self.gui.edit_chart_panel.load_chart_from_memory(entry)
        self._record_view(entry)

    # -- viewed-chart history (back / forward) -----------------------------

    def _record_view(self, entry):
        """Add the chart now on screen to the viewed-chart history. Bulk adds
        (defer_refresh) are not views and never reach here."""
        self.view_history.record(self._current_profile_id(), entry.get('id'),
                                 (entry.get('recipe') or {}).get('name'))
        self._update_history_buttons()

    def _current_profile_id(self):
        pm = getattr(self.gui, 'profile_manager', None)
        try:
            return pm.get_current_profile() if pm is not None else ""
        except Exception:
            return ""

    def _history_label(self, entry):
        pm = getattr(self.gui, 'profile_manager', None)
        name = entry.name or "chart"
        if pm is None or not entry.profile_id:
            return name
        return f"{name} ({self._profile_display_name(pm, entry.profile_id)})"

    def _on_nav_pad(self, direction):
        {"left": self.prev_page, "right": self.next_page,
         "up": lambda: self.go_history(-1), "down": lambda: self.go_history(1)}[direction]()

    def _update_history_buttons(self):
        pad = self.nav_pad
        if pad is None:
            return
        hist = self.view_history
        for key, step, verb, none in (("up", -1, "Back to", "No earlier chart this session"),
                                      ("down", 1, "Forward to", "No later chart this session")):
            target = hist.peek(step)
            pad.set_key_enabled(key, target is not None)
            pad.set_key_tooltip(key, none if target is None
                                else f"{verb} {self._history_label(target)}")

    def _index_of_chart_id(self, chart_id):
        for i, entry in enumerate(self.charts):
            if entry.get('id') == chart_id:
                return i
        return -1

    def go_history(self, step):
        """Show the chart viewed before (step -1) or after (+1) the current
        one, switching profile when it lives in another. A chart that has
        since been removed is dropped from the history and skipped."""
        hist = self.view_history
        while True:
            target = hist.peek(step)
            if target is None:
                break
            with hist.suppressed():
                if target.profile_id and target.profile_id != self._current_profile_id():
                    pm = getattr(self.gui, 'profile_manager', None)
                    if pm is not None:
                        pm._on_profile_selected(target.profile_id)
                idx = self._index_of_chart_id(target.chart_id)
                if idx >= 0:
                    hist.move(step)
                    self._ensure_page_visible(idx)
                    self.select_chart(idx)
                    break
            hist.discard(target)
        self._update_history_buttons()

    def _unstar_if_in_favorites_profile(self, entries, checked=False):
        """Unstar charts removed from the Favorites panel (SPEC-PROF-002 §5.1.0).

        Scoped to the Favorites profile ON PURPOSE. A star is global, so
        deleting a chart from the `models` panel must not silently unstar it —
        only deleting it from the star list's own view means "unstar". Without
        this, a starred chart deleted here comes back on the next sync, or
        (once SPEC-SES-002 lands) is dropped by its own tombstone forever while
        the star still points at it.

        Returns a status string: `'n/a'` (not in the Favorites profile),
        `'removed'`, `'absent'`, `'failed'`, or `'locked'`.

        `checked` (single-entry MOVE path, SPEC-PROF-003 finding 5) routes
        through `unstar_checked`, a LOCKED read-modify-write that reports
        whether the write persisted, so the move can abort truthfully when the
        star could not be cleared. Best-effort otherwise (deletion, clear-all):
        `unstar` swallows write failures, which is fine for a deletion the user
        already committed to but not for a move that must stay atomic.
        """
        try:
            pm = getattr(self.gui, 'profile_manager', None)
            if not pm or pm.get_current_profile() != 'favorites':
                return 'n/a'
            from managers import favorites_manager
            if checked:
                entry = entries[0] if entries else None
                if not isinstance(entry, dict):
                    return 'n/a'
                profiles_dir = getattr(pm, 'profiles_dir', None)
                return favorites_manager.unstar_checked(
                    profiles_dir, entry.get('recipe'), entry.get('id'))
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                # Pass the ID, not just the recipe. A recipe match misses
                # after a time edit (the star holds the old snapshot) and
                # overmatches within its 7.2 s tolerance, unstarring a
                # rectification variant's original. See unstar().
                favorites_manager.unstar(entry.get('recipe'), entry.get('id'))
            return 'n/a'
        except Exception as e:
            print(f"[MEMORY] Unstar-on-delete skipped: {e}")
            # In the checked path a swallowed error must NOT read as success —
            # the move relies on this to decide whether to abort.
            return 'failed' if checked else 'n/a'

    def _record_removal(self, entries):
        """Remember that these charts were deleted (SPEC-SES-002 §4.4).

        Union-by-identity without this is worse than the overwrite it
        replaces: a chart deleted here would come straight back from the
        other instance's list on the next merge, and there would be no way
        to delete anything while two windows are open.

        Best-effort — a bookkeeping failure must never block the deletion the
        user asked for. Returns True when every tombstone was recorded.
        """
        try:
            from managers.session_merge import make_tombstone
            for entry in entries:
                if isinstance(entry, dict):
                    self.tombstones.append(make_tombstone(entry))
            return True
        except Exception as e:                          # noqa: BLE001
            print(f"[MEMORY] Could not record the removal: {e}")
            return False

    def remove_chart_reported(self, index, require_unstar=False):
        """Remove a chart and REPORT whether every step persisted.

        The move (SPEC-PROF-003 finding 4) cannot use `remove_chart`: it
        returns nothing and drops `save_session()`'s boolean, so a refused
        source save would still read as a completed move. This returns
        `{'ok', 'unstar', 'tombstone', 'saved', 'reason'}`.

        `require_unstar=True` (set by the move when the source is Favorites)
        uses the checked/locked unstar and ABORTS before mutating anything if
        it reports `'failed'`: the source entry stays, the already-committed
        destination copy stands, and the caller reports a partial move rather
        than a silent copy.
        """
        result = {'ok': False, 'unstar': 'n/a', 'tombstone': False,
                  'saved': False, 'reason': None}
        if not (0 <= index < len(self.charts)):
            result['reason'] = 'index out of range'
            return result
        entry = self.charts[index]

        # Unstar FIRST so an abort leaves the panel untouched. 'locked' (another
        # instance holds the favorites lock) counts as a failure to clear the
        # star: proceeding would leave a still-starred chart that the Favorites
        # sync re-appends — the silent-copy loop this must prevent (SPEC-PROF-003
        # §6). Only a confirmed 'removed'/'absent'/'n/a' may proceed.
        result['unstar'] = self._unstar_if_in_favorites_profile(
            [entry], checked=require_unstar)
        if require_unstar and result['unstar'] in ('failed', 'locked'):
            result['reason'] = 'favorites write failed'
            return result

        removed_id = entry.get('id')
        if removed_id in self._insertion_order:
            self._insertion_order.remove(removed_id)
        result['tombstone'] = self._record_removal([entry])
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
            result['saved'] = bool(self.gui.session_manager.save_session())
        result['ok'] = result['saved']
        return result

    def remove_chart(self, index):
        """Remove a chart from memory (best-effort; existing callers).

        Thin wrapper over `remove_chart_reported` — deletion and clear-all
        never inspected a result, so their behaviour is unchanged.
        """
        self.remove_chart_reported(index)

    def _move_chart_to_profile(self, chart_id, dest_id):
        """Move the chart with uuid `chart_id` into profile `dest_id`.

        Entry-only (SPEC-PROF-003): commit into the destination FIRST, then
        remove from the source, so at every failure the chart is in ≥1 session
        file. uuid-capture (finding 1), destination guards (finding 6), INV-M
        no-self-resurrection, and the INV-T truthful reporting matrix.
        """
        from managers import chart_profile_mover as mover
        pm = getattr(self.gui, 'profile_manager', None)
        if pm is None:
            return self._move_report(False, "Move failed: no profile manager.")
        profiles_dir = getattr(pm, 'profiles_dir', None)
        source_id = pm.get_current_profile()

        # A blank/None id cannot be resolved to exactly one chart (GPT Sol
        # finding 6) — refuse before matching.
        if not (isinstance(chart_id, str) and chart_id):
            return self._move_report(False, "This chart has no id and cannot be moved.")

        # Never move while autosave is paused (a profile switch is mid-flight):
        # save_session() returns True WITHOUT writing then (session_manager.py
        # :1057), so a removal would be reported "Moved" while the source file
        # is untouched (GPT Sol finding 5).
        sm = getattr(self.gui, 'session_manager', None)
        if sm is not None and getattr(sm, '_auto_save_pause_depth', 0) > 0:
            return self._move_report(
                False, "Move unavailable while switching profiles — try again.")

        # 1. Resolve uuid -> index NOW: the menu ran a nested event loop and a
        #    cross-instance push may have reordered or removed entries.
        index = next((i for i, c in enumerate(self.charts)
                      if isinstance(c, dict) and c.get('id') == chart_id), None)
        if index is None:
            return self._move_report(False, "That chart is no longer in this profile.")
        entry = self.charts[index]
        if entry.get('is_transit') or not isinstance(entry.get('recipe'), dict):
            return self._move_report(False, "This chart cannot be moved.")
        if dest_id == source_id:
            return self._move_report(False, "That is already the current profile.")

        dest_name = self._profile_display_name(pm, dest_id)
        source_name = self._profile_display_name(pm, source_id)
        name = (entry.get('person_name')
                or entry.get('recipe', {}).get('name') or "chart")

        # 2. commit-in (locked merged write; stamps updated_at).
        try:
            entry_dict = mover.serialize_entry(entry)
        except Exception as e:
            return self._move_report(False, f"Move failed: {e}. Nothing changed.")
        ok, reason = mover.commit_to_profile(profiles_dir, dest_id, entry_dict)
        if not ok:
            return self._move_report(False, f"Move failed: {reason}. Nothing changed.")

        # 3. destination-deletion race guard (finding 6).
        if not mover.dest_session_present(profiles_dir, dest_id):
            return self._move_report(
                False,
                f"Destination profile disappeared — '{name}' kept in {source_name}.")

        # 4. INV-M reselect-if-selected + structured removal. The destination
        #    copy is already committed; a failure in the widget/selection work
        #    from here must be contained and reported as a partial move (chart
        #    in both), never allowed to escape the Qt slot with the source
        #    silently changed.
        try:
            if (0 <= self.current_index < len(self.charts)
                    and self.charts[self.current_index].get('id') == chart_id):
                self._reselect_neighbor(index)
            # require unstar when moving OUT of Favorites.
            result = self.remove_chart_reported(
                index, require_unstar=(source_id == 'favorites'))
        except Exception as e:
            return self._move_report(
                False,
                f"Partial move: '{name}' copied to {dest_name} but removing it "
                f"from {source_name} failed ({e}) — appears in both.")

        # INV-M postcondition: the moved uuid must be gone from this panel.
        still_present = any(isinstance(c, dict) and c.get('id') == chart_id
                            for c in self.charts)

        # INV-T reporting matrix — "Moved" only when BOTH writes confirmed and
        # the removal actually persisted (with a tombstone, or another instance
        # holding the entry re-adds it on its next merge).
        if result['unstar'] in ('failed', 'locked'):
            return self._move_report(
                False,
                f"Partial move: '{name}' copied to {dest_name} but still starred "
                f"and in {source_name} (favorites busy or write failed).")
        if not result['saved'] or still_present or not result['tombstone']:
            return self._move_report(
                False,
                f"Partial move: '{name}' added to {dest_name}; removal from "
                f"{source_name} not fully saved yet — appears in both.")
        suffix = " and unstarred" if result['unstar'] == 'removed' else ""
        return self._move_report(True, f"Moved '{name}' to {dest_name}{suffix}")

    def _reselect_neighbor(self, index):
        """Select a neighbouring chart before removing the one at `index`.

        INV-M: after this, `current_index` names a different chart, so the
        removal cannot leave the moved uuid as the selected/fenced row. With a
        single chart there is no neighbour — the removal empties the panel and
        `current_index` becomes -1, which also excludes the moved uuid.
        """
        if len(self.charts) <= 1:
            return
        neighbor = index + 1 if index + 1 < len(self.charts) else index - 1
        if 0 <= neighbor < len(self.charts):
            self.select_chart(neighbor)

    def _profile_display_name(self, pm, profile_id):
        """Human-readable profile name for a profile id; the id as fallback."""
        try:
            for prof in pm.list_profiles():
                if prof.get('id') == profile_id:
                    return prof.get('name') or profile_id
        except Exception:
            pass
        return profile_id

    def _move_report(self, ok, msg):
        """Status feedback for a move, and the structured result.

        Success is transient; failure uses the sticky red channel
        (`ui/sticky_status.py`) so a follow-on status message cannot
        immediately erase it (SES-001 INV-1, no modal dialogs). Returns
        `{'ok', 'message', 'moved'}` for the remote-control command and tests;
        the context-menu action ignores it.
        """
        if ok:
            try:
                self.gui.statusBar().showMessage(msg, 6000)
            except Exception:
                print(f"[MEMORY] {msg}")
        else:
            shown = False
            try:
                from ui.sticky_status import sticky_status_for
                # Resolve from self.gui: ChartMemoryPanel is a plain object, not
                # a QWidget, so sticky_status_for(self) could never walk up to a
                # window. self.gui is the QMainWindow that owns the status bar.
                sticky = sticky_status_for(self.gui)
                if sticky is not None:
                    sticky.show_error(msg)
                    shown = True
            except Exception:
                pass
            if not shown:
                try:
                    self.gui.statusBar().showMessage(msg, 12000)
                except Exception:
                    print(f"[MEMORY] {msg}")
        return {'ok': ok, 'message': msg, 'moved': ok}

    def clear_all(self):
        """Remove all charts from memory."""
        if self._select_mode:
            self._select_mode = False
            self._selected_ids.clear()
            self._restore_action_buttons()
        self._unstar_if_in_favorites_profile(list(self.charts))
        # One batch through the same locked write. Bounded by the panel size,
        # which is bounded by what the user can see (§4.4 — the watermark
        # this replaces saved nothing measurable and cost a chain of
        # compensations).
        self._record_removal(list(self.charts))
        self.charts.clear()
        self._insertion_order.clear()
        self.current_sort_mode = None
        if self.sort_btn:
            self._update_action_cells()
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

        from core.chart_factory import RECIPE_INSTANT_FIELDS
        # Snapshot BEFORE mutating. Comparing the resulting values (rather than
        # inspecting `updates` keys) is what makes this robust: callers pass
        # `local_year`, `year` or nothing at all, and a caller that writes the
        # same value back must not be treated as an edit.
        _instant_before = {k: recipe.get(k) for k in RECIPE_INSTANT_FIELDS}
        # td-hba1: the DST pair needs the same before/after comparison, and
        # for the same reason — a caller writing the same flag back is not an
        # edit and must not coarsen an exact half-hour offset.
        _dst_flag_before = recipe.get('time_change_flag')

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

        # td-nbl8: a stored julian_day WINS over civil time in
        # build_chart_from_recipe, so an edit that moves the instant without
        # re-deriving it is silently discarded on the next rebuild — the user's
        # saved time adjustment snapped back on the first mode switch. Only
        # TOML-origin recipes carry a JD; CHTK-origin ones stay untouched.
        if recipe.get('julian_day') is not None and any(
                recipe.get(k) != _instant_before[k] for k in RECIPE_INSTANT_FIELDS):
            from core.chart_factory import jd_from_recipe_civil
            try:
                recipe['julian_day'] = float(jd_from_recipe_civil(recipe))
            except (TypeError, ValueError, KeyError) as e:
                # Never keep a JD we know is stale: falling back to None makes
                # the builder recompute from civil time, which is the whole
                # point. Keeping it would restore the bug.
                print(f"[MEMORY] julian_day re-derive failed, clearing: {e}")
                recipe['julian_day'] = None

        # td-hba1, the same family. A recipe can carry BOTH time_change_flag
        # (an integer: 0 none, 1 DST, 2 War Time) and dst_offset_hours (the
        # exact float, so Lord Howe's half hour survives). Every consumer
        # prefers the float when it is present — toml_chart._recover_offsets,
        # BirthDataManager._compute_chtk_timezone — so editing the flag alone
        # changes nothing at all, and the user's DST correction is silently
        # discarded on the next write.
        #
        # The float wins, so the float has to follow. float(flag) is not a
        # guess: the flag's whole meaning is "this many hours", and the only
        # case where the float says something the flag cannot (a half-hour
        # DST) is the case where the flag did not change and this does not
        # run.
        if (recipe.get('dst_offset_hours') is not None
                and 'time_change_flag' in recipe
                and recipe['time_change_flag'] != _dst_flag_before):
            flag = recipe.get('time_change_flag')
            if flag in (0, 1, 2):
                recipe['dst_offset_hours'] = float(flag)
            else:
                # -1 is Kala's AUTO sentinel and anything else is unknown.
                # Clearing sends every consumer back to the flag, which has
                # resolve_recipe_dst_flag to interpret it; keeping a stale
                # float would override that with the OLD answer.
                print(f"[MEMORY] dst flag {flag!r} is not a fixed amount; "
                      f"clearing dst_offset_hours")
                recipe['dst_offset_hours'] = None

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

        # The single edit funnel (time_adjust_widget and edit_chart_panel both
        # arrive here), so one stamp covers every user edit. Without it the
        # other instance's older copy wins the next merge and the correction
        # is undone by a window the user was not even looking at.
        _stamp(entry)

        self.refresh()
        if hasattr(self.gui, 'session_manager') and self.gui.session_manager:
            self.gui.session_manager.save_session()
        return True

    # validate_chart_against_chtk and validate_all_charts removed —
    # an enhanced validator is available in the paid edition.
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
        Called from core_gui_qt.py when user changes theme (and on font
        changes). Every colour is read from the theme at paint time, so this
        re-reads the font areas and repaints.
        """
        self._fit_controls()
        if self.nav_pad is not None:
            self.nav_pad.refresh_theme()
        for w in (self.strip, self.strip.tray, self.strip.well, self.strip.actions,
                  self.load_folder_btn, *self.strip.actions.cells()):
            w.update()
        self._update_action_cells()
        # Regenerate the chips (fonts and widths follow the areas)
        self.refresh()

    def refresh(self):
        """Refresh the chart chips for the current page."""
        from apps.widgets.memory_pane.chip import MemoryChip
        theme = get_theme_colors()
        tray = self.strip.tray

        # Clear existing chips (Rule 18: Qt owns them, deleteLater)
        for btn in self.chart_buttons:
            btn.hide()
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
                    border: none;
                }}
            """)
            tray.set_empty(empty_label)
            self.chart_buttons.append(empty_label)
            self._update_pagination()
            return

        # Calculate visible range
        start = self.current_page * self.page_size
        end = min(start + self.page_size, len(self.charts))
        visible_charts = self.charts[start:end]

        current_chip = None
        for i, chart in enumerate(visible_charts):
            actual_index = start + i
            is_current = actual_index == self.current_index
            name = chart['person_name'].title()
            # SPEC-TRN-006: the chip is a ChartMemoryButton, so it can also be
            # dragged onto the TRANSIT button to overlay this chart. Drag is
            # suppressed in select-mode (draggable=False) where it would
            # conflict with check box toggling.
            chip = MemoryChip(
                name, chart.get('id'), tray.content,
                draggable=not self._select_mode,
                current=is_current,
                select_mode=self._select_mode,
                checked_box=self._select_mode and chart.get('id') in self._selected_ids)
            chip.setToolTip(name)
            if self._select_mode:
                chip.clicked.connect(
                    lambda checked=False, idx=actual_index: self._toggle_chart_selection(idx))
            else:
                chip.clicked.connect(
                    lambda checked=False, idx=actual_index: self.select_chart(idx))
                chip.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                chip.customContextMenuRequested.connect(
                    lambda pos, idx=actual_index, b=chip: self._show_context_menu(b, idx, pos)
                )
            if is_current:
                current_chip = chip
            self.chart_buttons.append(chip)

        tray.set_chips(self.chart_buttons, current_chip)
        self._update_pagination()

    def _profile_name(self):
        """The active profile's display name (cached per profile id)."""
        pm = getattr(self.gui, 'profile_manager', None)
        if pm is None:
            return ""
        try:
            pid = pm.get_current_profile()
        except Exception:
            return ""
        if pid not in self._profile_names:
            self._profile_names[pid] = self._profile_display_name(pm, pid) or ""
        return self._profile_names[pid]

    def _update_pagination(self):
        """Update the D-pad and the profile well (count, page ticks)."""
        total_charts = len(self.charts)
        total_pages = max(1, (total_charts + self.page_size - 1) // self.page_size)
        current_page_display = self.current_page + 1 if total_charts > 0 else 0

        # Update page indicator (centre of the D-pad)
        self.nav_pad.set_page_text(f"{current_page_display}/{total_pages}")

        # The well: profile name, chart count, one tick per page
        self.strip.well.set_state(self._profile_name(), total_charts,
                                  self.current_page + 1, total_pages)

        # Enable/disable navigation buttons
        self.nav_pad.set_key_enabled("left", self.current_page > 0)
        self.nav_pad.set_key_enabled("right", self.current_page < total_pages - 1)
        self.nav_pad.set_key_tooltip(
            "left", f"Previous page ({current_page_display} of {total_pages})"
            if self.current_page > 0 else "First page")
        self.nav_pad.set_key_tooltip(
            "right", f"Next page ({current_page_display} of {total_pages})"
            if self.current_page < total_pages - 1 else "Last page")

    def prev_page(self):
        """Go to previous page."""
        if self.current_page > 0:
            self.current_page -= 1
            self.refresh()

    def next_page(self):
        """Go to next page."""
        total_pages = max(1, (len(self.charts) + self.page_size - 1) // self.page_size)
        if self.current_page < total_pages - 1:
            self.current_page += 1
            self.refresh()

    def _ensure_page_visible(self, index):
        """Ensure the chart at given index is on the visible page."""
        target_page = index // self.page_size
        if target_page != self.current_page:
            self.current_page = target_page

    def _ensure_page_valid(self):
        """Ensure current page is valid after chart removal."""
        total_pages = max(1, (len(self.charts) + self.page_size - 1) // self.page_size)
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

        chart = self.charts[index] if 0 <= index < len(self.charts) else None

        # Favorite toggle (SPEC-FAV-001 S6). Lazy import + read-on-open
        # keeps the panel's refresh/select paths free of favorites cost.
        if chart and not chart.get('is_transit') and isinstance(chart.get('recipe'), dict):
            from managers import favorites_manager
            if favorites_manager.is_favorite(chart['recipe']):
                fav_action = menu.addAction("★ Remove from Favorites")
            else:
                fav_action = menu.addAction("☆ Add to Favorites")
            fav_action.triggered.connect(
                lambda checked=False, c=chart: favorites_manager.toggle_favorite(
                    c, profiles_dir=getattr(
                        getattr(self.gui, 'profile_manager', None), 'profiles_dir', None))
            )
            menu.addSeparator()

        # Search Astrotheme for this person
        if chart:
            person_name = chart.get('person_name', '')
            if person_name:
                astrotheme_action = menu.addAction(f"Search Astrotheme: \"{person_name}\"")
                astrotheme_action.triggered.connect(
                    lambda: self._search_astrotheme(person_name)
                )

        # SPEC-TRN-006: third entry point for chart overlay (same as dragging this
        # button onto the TRANSIT button). Enabled only when a base chart is loaded.
        # Overlaying a chart onto itself is allowed (a legitimate way to read the
        # medallion), so no identity guard.
        if chart is not None and chart.get('id'):
            menu.addSeparator()
            overlay_action = menu.addAction("⟐ Overlay on current chart")
            has_base = getattr(self.gui.state, 'active_chart', None) is not None
            overlay_action.setEnabled(has_base)
            overlay_action.triggered.connect(
                lambda checked=False, cid=chart.get('id'):
                    self.gui.chart_overlay_manager.overlay_from_memory_id(cid)
            )

        # Move to another profile (SPEC-PROF-003, entry-only). A submenu of
        # every profile EXCEPT the active one; clicking moves this chart's
        # membership out of the current profile into that one. Hidden for
        # transit entries (a moment in time is not a person) and when there is
        # no other profile. uuid-capture in every action (finding 1): the menu
        # runs a nested event loop, so a captured index could name the wrong
        # chart after a cross-instance push.
        if (chart is not None and not chart.get('is_transit')
                and isinstance(chart.get('recipe'), dict)
                # Require a non-empty string id: an id-less entry cannot be
                # matched, deduped, or safely removed, and two None-id entries
                # would resolve to the wrong chart (GPT Sol finding 6).
                and isinstance(chart.get('id'), str) and chart.get('id')):
            pm = getattr(self.gui, 'profile_manager', None)
            if pm is not None:
                try:
                    current_pid = pm.get_current_profile()
                    others = [p for p in pm.list_profiles() if p.get('id') != current_pid]
                except Exception:
                    others = []
                if others:
                    move_menu = menu.addMenu("Move to profile")
                    cid = chart.get('id')
                    for prof in others:
                        act = move_menu.addAction(prof.get('name') or prof.get('id'))
                        act.setData(prof.get('id'))
                    move_menu.triggered.connect(
                        lambda action, chart_id=cid:
                            self._move_chart_to_profile(chart_id, action.data())
                    )
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

    def _search_astrotheme(self, person_name):
        """Search Astrotheme for this person using the default browser."""
        import urllib.parse
        import webbrowser
        query = urllib.parse.quote_plus(f"site:www.astrotheme.com {person_name}")
        webbrowser.open(f"https://www.google.com/search?q={query}")

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
        self._update_action_cells()

    def _set_sort_mode(self, mode):
        """Pick a sort mode directly (the ⋯ menu's sort order list)."""
        if not self.charts or mode not in self.SORT_MODES:
            return
        self.current_sort_mode = mode
        self._apply_sort()
        self._update_action_cells()

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
        """Select mode: chips show a check box and toggle it on click; the
        cells become ALL / DELETE n / SELECT (on) / INVERT."""
        if not self.charts:
            return
        self._select_mode = True
        self._selected_ids.clear()
        self._update_action_cells()
        self.refresh()

    def _restore_action_buttons(self):
        """Restore the cells to their normal-mode labels and actions."""
        self._update_action_cells()

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
        self._update_action_cells()

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

        doomed = [c for c in self.charts if c.get('id') in self._selected_ids]
        self._unstar_if_in_favorites_profile(doomed)
        self._record_removal(doomed)

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

    def _confirm_clear_all(self):
        """Show confirmation before clearing all charts."""
        if not self.charts:
            return  # Nothing to clear

        # In the Favorites profile this also empties the star list, and that
        # list is global — it is not a memory-only operation there, so the
        # confirmation must not describe it as one.
        extra = ""
        try:
            pm = getattr(self.gui, 'profile_manager', None)
            if pm and pm.get_current_profile() == 'favorites':
                extra = ("\n\nThis also removes every star, for all profiles. "
                         "Your saved chart files are not touched.")
        except Exception:
            pass

        name = self._profile_name().upper()
        where = f" from profile {name}" if name else ""
        box = QMessageBox(self.panel)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Clear All Charts")
        box.setText(f"Clear all {len(self.charts):,} charts{where}? "
                    f"The chart files stay on disk.{extra}")
        cancel = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        clear = box.addButton("Clear all", QMessageBox.ButtonRole.DestructiveRole)
        from apps.widgets.memory_pane.tokens import pane_tokens
        tok = pane_tokens()
        clear.setStyleSheet(
            f"QPushButton {{ background-color: {tok['red'].name()};"
            f" color: {tok['fg_on_accent'].name()}; }}")
        box.setDefaultButton(cancel)
        box.exec()

        if box.clickedButton() is clear:
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
            "Select Folder Containing Chart Files",
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
                f"No .chtk or .toml files found in:\n{folder_path}",
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

    def add_chart_files_silently(self, paths, label, *, then=None):
        """Add chart files to memory WITHOUT displaying any of them.

        The one bulk-add path, shared by Load Folder and a multi-file drop on
        the chart tab: each file is parsed through BirthDataManager and added
        with defer_refresh=True, so nothing is drawn per chart; the caller
        decides which single chart to display afterwards. `then(last_added_id)`
        runs while the loading overlay is still up, so the final display does
        not flash the overlay off and on. `last_added_id` is the id of the
        last genuinely-new entry (None if every file was a duplicate or failed).

        Returns (loaded_count, failed_count).
        """
        from managers.birth_data_manager import BirthDataManager
        from core.chart_factory import make_recipe

        paths = list(paths)
        total = len(paths)
        # Show the shared loading overlay so a large bulk load reads as
        # "working" instead of a frozen window. start()/finish() are
        # ref-counted and nest safely with the load_chart() in `then`, so we
        # pair exactly one start() with one finish() (in the finally).
        loading_active = (
            hasattr(self, 'gui')
            and hasattr(self.gui, 'loading_manager')
            and self.gui.loading_manager is not None
        )
        if loading_active:
            self.gui.loading_manager.start(label)
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

            for i, chtk_file in enumerate(paths):
                try:
                    # SPEC-IMPORT-001 §6.1: dispatch by extension (.chtk/.toml).
                    # canonicalize=False: a bulk load is a read path and must NOT
                    # write [moment].jd back into JD-less .toml files (no user consent).
                    bd = BirthDataManager.create_birth_data_from_file(str(chtk_file), canonicalize=False)
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
                        # SPEC-IMPORT-001 §6.3: forward additive metadata (None
                        # for CHTK -> conditionally omitted by make_recipe).
                        rodden=bd.get('rodden'),
                        tags=bd.get('tags'),
                        notes=bd.get('notes'),
                        julian_day=bd.get('julian_day'),
                        dst_offset_hours=bd.get('dst_offset_hours'),
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
                    print(f"[BULK LOAD] Failed: {chtk_file.name}: {e}")

                if loading_active:
                    self.gui.loading_manager.set_progress(i + 1, total)

                # Drain pending Qt events periodically so the GUI stays responsive
                # and queued deleteLater targets actually die.
                if (i + 1) % self.LOAD_FOLDER_EVENT_FLUSH_INTERVAL == 0:
                    QApplication.processEvents()

            if then is not None:
                then(last_added_id)
            return loaded_count, failed_count
        finally:
            # Always tear the overlay down. A stuck overlay would be worse
            # than the silent load this fix replaces.
            if loading_active:
                self.gui.loading_manager.finish()

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

        # SPEC-IMPORT-001 §6.1: load both .chtk and .toml charts from the folder.
        chtk_files = sorted(
            list(folder.glob("*.chtk")) + list(folder.glob("*.toml"))
        )
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

        def _activate_last_new(last_added_id):
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

        loaded_count, failed_count = self.add_chart_files_silently(
            chtk_files, f"Loading {total} charts from folder...",
            then=_activate_last_new)

        return {
            "ok": True,
            "loaded": loaded_count,
            "failed": failed_count,
            "total_in_folder": total,
            "cancelled": False,
            "over_cap": over_cap,
        }

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
