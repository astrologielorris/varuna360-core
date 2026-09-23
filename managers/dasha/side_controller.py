# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""One controller for a Vimshottari-family dasha side (SPEC-DSH-002, td-t761 w2-2).

`VimshottariSideController` drives ONE dasha side (left = Vedanga, right =
Vimshottari-in-vimshottari-mode). Two instances live on `DashaManager`
(`self._left_ctl`, `self._right_ctl`). It replaces the two byte-identical
renderers and their paired helpers with a single implementation; the pure logic
lives in `managers/dasha/engine.py`, this class executes the Qt side.

Boundary rules the manifest fixes (sol rounds 1-3):
- The controller is part of the manager boundary: it may write `SideState` fields
  (through `self.side`) and set WIDGET state (setChecked, list items, delegate
  rows, cycle-label text, setUpdatesEnabled) — but NEVER a `ChartGUI` attribute
  (`gui.<attr> = ...`); an AST test enforces that.
- SEAM RULE: wherever a retained manager method called ANOTHER retained manager
  method, this controller calls the SAME manager name (`_auto_build_parent_chain`,
  `update_<side>_dasha`, `set_<side>_level`, `scroll_to_<side>_row`,
  `_display_date_at_offset`, `_age_str`, `_update_dasha_title`,
  `refresh_dasha_lord_highlights`, `_select_dasha_entry`) so every `patch.object`
  spy, `MagicMock` and call-count assertion sees the same call sequence as before.
- The right controller does NOT know about modes: the manager's `update_right_panel`
  / `set_right_level` / `on_right_*` keep dispatching by mode and call the right
  controller only in vimshottari mode, exactly as they called
  `update_vimshottari_dasha` today.

Render generation token (sol round 1-2/3): `update()` bumps `self._render_gen`
first; `_pump(gen)` pumps the event loop mid-filter and raises `_StaleRender` if a
newer render (or a Nisarga/ZR reshape via `invalidate()`) superseded this one, so
stale population and stale delayed scrolling are suppressed.
"""

from typing import NamedTuple

from PySide6.QtWidgets import QListWidgetItem, QListWidget, QApplication
from PySide6.QtCore import Qt, QTimer

from managers.dasha import engine

# The flat-view "drill down" notice, verbatim (:1327); NO UserRole data.
_NOTICE_TEXT = "  … drill down by clicking a period above …"


class _StaleRender(Exception):
    """Raised inside `_pump` when a newer render (or a mode reshape) superseded
    this one; `update()` catches it silently BEFORE the generic boundary."""


class SideWidgets(NamedTuple):
    """The per-side GUI collaborators, resolved from the ChartGUI at call time
    (hasattr-guarded — any may be None if the panel is not built). Wave 3 replaces
    this with the DashaPanelWidget."""
    list_widget: object
    delegate: object
    level_buttons: object
    cycle_label: object


# Per-side widget/method NAME table — the ONLY place the two sides differ.
_SIDE_NAMES = {
    "left": {
        "title": "vedanga",                 # _update_dasha_title / _auto_build panel arg
        "title_cap": "Vedanga",             # error-message word
        "scroll": "scroll_to_vedanga_row",
        "update": "update_vedanga_dasha",
        "set_level": "set_vedanga_level",
    },
    "right": {
        "title": "vimshottari",
        "title_cap": "Vimshottari",
        "scroll": "scroll_to_vimshottari_row",
        "update": "update_vimshottari_dasha",
        "set_level": "set_vimshottari_level",
    },
}


class VimshottariSideController:
    """Drives one Vimshottari-family dasha side. Holds the manager (for gui,
    params, chart, title, lord highlights) and the side name; reads/writes its
    SideState through `self.side`."""

    def __init__(self, manager, side_name):
        if side_name not in _SIDE_NAMES:
            raise ValueError(f"side_name must be 'left' or 'right', got {side_name!r}")
        self.manager = manager
        self.side_name = side_name
        self._names = _SIDE_NAMES[side_name]
        self._render_gen = 0

    # ----------------------------------------------------------------------- #
    # State + widget access                                                    #
    # ----------------------------------------------------------------------- #

    @property
    def side(self):
        """This side's SideState."""
        return self.manager.dasha_state.side(self.side_name)

    def widgets(self):
        """Resolve the per-side collaborators from the panel the manager owns
        (w3-2, D-W3-2). Returns the all-None SideWidgets when the panel is not
        built, so every controller path raises at the same statement it did when
        the widgets lived on ChartGUI (hasattr-guarded getattr, same tuple)."""
        panel = self.manager.panel(self.side_name)
        if panel is None:
            return SideWidgets(None, None, None, None)
        return SideWidgets(
            list_widget=panel.list_widget,
            delegate=panel.delegate,
            level_buttons=panel.level_buttons,
            cycle_label=panel.cycle_label,
        )

    def _required_widgets(self):
        """Like widgets() but for the paths that at BASE resolved the collaborators
        with a DEFAULT-LESS getattr (on_clicked, :339/:344): a missing panel raises
        AttributeError at that boundary — never a silent None that would later fail
        with a different error (enumerate(None) TypeError). sol 6."""
        panel = self.manager.panel(self.side_name)
        if panel is None:
            raise AttributeError(
                f"{self._names['title']}_level_buttons: dasha panel for side "
                f"{self.side_name!r} is not built")
        return SideWidgets(
            list_widget=panel.list_widget,
            delegate=panel.delegate,
            level_buttons=panel.level_buttons,
            cycle_label=panel.cycle_label,
        )

    def invalidate(self):
        """Bump the render generation so a suspended render of this side aborts at
        its next `_pump` (sol r1-2). The manager funnels every non-Vimshottari
        right-panel reshape (configure_right_panel, update_nisarga_dasha,
        update_zr_dasha) and reset_for_chart through here."""
        self._render_gen += 1

    def _pump(self, gen):
        """Pump the event loop mid-filter; abort THIS render if a newer one (or a
        mode reshape) moved the generation. Passed into engine.filter_rows as its
        `progress` closure `lambda i: self._pump(gen)` — never QApplication
        .processEvents itself (which would read the row index as its flags)."""
        QApplication.processEvents()
        if self._render_gen != gen:
            raise _StaleRender()

    # ----------------------------------------------------------------------- #
    # The renderer                                                             #
    # ----------------------------------------------------------------------- #

    def update(self):
        """Re-list this side (verbatim order of the two paired renderers).

        First two statements bump + capture the render generation; then title ->
        clear -> chart guard -> params -> compute step (a "reset" step applies
        side.level=1/chain=[] + setChecked BEFORE the fallback compute) ->
        side.rows = rows (before the walk) -> setUpdatesEnabled(False) (before the
        walk) -> filter (pumping) -> populate (no pump) -> setUpdatesEnabled(True)
        at the ORIGINAL success point (verbatim :1360/:1547) -> highlights -> delayed
        scroll (gen-checked) -> lord highlights. The success re-enable matches the two
        paired renderers, so the highlight/scroll/refresh below run with updates
        ENABLED as before; the finally re-enables updates ONLY when a mid-walk failure
        (a _StaleRender or exception raised before that success point) left them
        disabled — so the list is never frozen and a pre-disable failure adds no
        re-enable. _StaleRender is silent.
        """
        self._render_gen += 1
        gen = self._render_gen

        n = self._names
        gui = self.manager.gui
        w = self.widgets()

        # title -> clear -> chart guard (verbatim order, before the try).
        # _update_dasha_title takes the PANEL word ("vedanga"/"vimshottari"), not
        # the side name.
        self.manager._update_dasha_title(n["title"])
        w.list_widget.clear()
        if not gui.current_chart_data:
            return

        updates_disabled = False
        error = None
        try:
            from core.vimshottari_dasha import (
                calculate_dasha_from_birth_data, calculate_sub_dashas_for_period)
            from AI_tools.AI_main_function.dasha import get_dasha_params

            params = get_dasha_params(
                gui.current_chart_data, is_human_design=gui.is_human_design)
            year, month, day = params["year"], params["month"], params["day"]
            hour, minute, second = params["hour"], params["minute"], params["second"]
            tz_offset = params["tz_offset"]
            moon_jd_override = params["moon_jd_override"]
            nak_mode = getattr(gui, "nakshatra_coords", "neither")

            if not all([year, month, day]):
                return

            side = self.side

            # --- compute: the engine decides the step, the controller runs it --- #
            step = engine.decide_compute(side.level, side.parent_chain, side.rows)
            if step.kind == "full":
                formatted = calculate_dasha_from_birth_data(
                    year, month, day, hour, minute, second,
                    dlevels=step.dlevels, ayanamsa=side.ayanamsa,
                    tz_offset_hours=tz_offset, moon_jd_override=moon_jd_override,
                    nak_mode=nak_mode,                    # td-2yqd: full path seeds by nakshatra_coords too
                    year_length=self.manager.year_length)  # SPEC-DSH-003
                used_focused_calc = False
            elif step.kind == "sub":
                formatted = calculate_sub_dashas_for_period(
                    step.parent["jd"], step.parent["end_jd"], step.parent_lord,
                    ayanamsa=side.ayanamsa, tz_offset_hours=tz_offset)
                used_focused_calc = True
            else:                                       # "probe" -> recompute
                fresh = calculate_dasha_from_birth_data(
                    year, month, day, hour, minute, second,
                    dlevels=step.dlevels, ayanamsa=side.ayanamsa,
                    tz_offset_hours=tz_offset, moon_jd_override=moon_jd_override,
                    nak_mode=nak_mode, year_length=self.manager.year_length)
                step2 = engine.decide_after_probe(fresh, step.parent_lord)
                if step2.kind == "sub":
                    formatted = calculate_sub_dashas_for_period(
                        step2.parent["jd"], step2.parent["end_jd"], step2.parent_lord,
                        ayanamsa=side.ayanamsa, tz_offset_hours=tz_offset)
                    used_focused_calc = True
                else:                                   # "reset": absolute fallback
                    # Applied BEFORE the fallback compute (verbatim :1263-1275).
                    side.parent_chain = []
                    side.level = 1
                    if w.level_buttons is not None:
                        for idx, btn in enumerate(w.level_buttons):
                            btn.setChecked(idx == 0)
                    formatted = calculate_dasha_from_birth_data(
                        year, month, day, hour, minute, second,
                        dlevels=step2.dlevels, ayanamsa=side.ayanamsa,
                        tz_offset_hours=tz_offset, moon_jd_override=moon_jd_override,
                        nak_mode=nak_mode, year_length=self.manager.year_length)
                    used_focused_calc = False

            # side.rows cached BEFORE the walk (verbatim :1286).
            side.rows = formatted
            years_to_add = engine.shift_years(side.cycle_offset)

            # --- filter (pumping) then populate (no pump), updates disabled --- #
            w.list_widget.setUpdatesEnabled(False)
            updates_disabled = True

            visible, capped = engine.filter_rows(
                formatted, side.parent_chain, side.level, used_focused_calc,
                progress=lambda i: self._pump(gen))

            for _src_i, entry in visible:
                jd = entry.get("jd")
                date_str = entry["date"]
                # YEAR-only cycle offset through the retained manager helper (per
                # invocation, seam rule); age likewise (both go THROUGH the manager
                # so their spies keep firing).
                if years_to_add != 0 and jd:
                    date_str = self.manager._display_date_at_offset(jd, years_to_add)
                age = self.manager._age_str(jd, years_to_add)
                marked = entry.get("is_current", False) and side.cycle_offset == 0
                item = QListWidgetItem(engine.row_text(entry, date_str, age, marked))
                item.setData(Qt.ItemDataRole.UserRole, entry)
                w.list_widget.addItem(item)
            if capped:
                w.list_widget.addItem(QListWidgetItem(_NOTICE_TEXT))

            # SUCCESS-PATH re-enable at the ORIGINAL point (verbatim :1360 / :1547):
            # the delegate highlights, viewport().update(), delayed-scroll scheduling
            # and lord-highlight refresh below all ran with updates ENABLED in the two
            # paired renderers, so re-enable here — NOT deferred to the finally (sol
            # delta-3 EDIT). Clearing the flag leaves the guarded finally to cover ONLY
            # a mid-walk failure (a _StaleRender or exception raised before this point,
            # i.e. during filter/populate) — the §4.9(b) frozen-list fix, no more.
            w.list_widget.setUpdatesEnabled(True)
            updates_disabled = False

            hl = engine.highlight_rows(visible, side.cycle_offset)

            # delegate highlights
            if w.delegate is not None:
                w.delegate.update_selected_row(None)
                w.delegate.update_highlights(hl)
                w.list_widget.viewport().update()

            # delayed scroll to the deepest current period, gen-checked, THROUGH
            # the retained manager name (a stale render must not scroll, and a
            # vimshottari scroll must never land on a Nisarga list).
            if hl and side.cycle_offset == 0:
                current_row = max(hl)
                delay_ms = 400 if side.level >= 4 else 150
                scroll_name = n["scroll"]
                QTimer.singleShot(
                    delay_ms,
                    lambda g=gen, r=current_row:
                        self._render_gen == g and getattr(self.manager, scroll_name)(r))

            # karaka/lord highlights (stays in the manager, seam); takes the
            # PANEL word ("vedanga"/"vimshottari"), not the side name.
            self.manager.refresh_dasha_lord_highlights(n["title"])
        except _StaleRender:
            pass                                        # silent: newer render owns the list
        except Exception as e:                          # noqa: BLE001 (verbatim boundary)
            error = e
        finally:
            if updates_disabled:
                w.list_widget.setUpdatesEnabled(True)
        if error is not None:
            print(f"Error updating {n['title_cap']} dasha: {error}")

    # ----------------------------------------------------------------------- #
    # Level / navigation / click (verbatim, through the manager seam)          #
    # ----------------------------------------------------------------------- #

    def set_level(self, level):
        """Set this side's display level (1-5): trim the chain, auto-build when it
        empties at level >= 2 (THROUGH manager._auto_build_parent_chain so the
        spy at test_remote_control.py:1633 still intercepts), set level + buttons,
        then re-list THROUGH manager.update_<side>_dasha (seam)."""
        side = self.side
        trimmed = engine.trim_chain_for_level(side.parent_chain, level)
        if not trimmed and level >= 2:
            trimmed = self.manager._auto_build_parent_chain(
                side.rows, level, self._names["title"])
        side.parent_chain = trimmed
        side.level = level
        buttons = self.widgets().level_buttons
        if buttons is not None:
            for idx, btn in enumerate(buttons):
                btn.setChecked(idx + 1 == level)
        getattr(self.manager, self._names["update"])()

    def navigate(self, delta):
        """Move the 120-year cycle by `delta` and re-list (seam)."""
        self.manager.set_cycle_offset(self.side_name, self.side.cycle_offset + delta)
        getattr(self.manager, self._names["update"])()

    def on_clicked(self, item):
        """Click to expand (drill) or, at max depth, toggle-select (verbatim
        :519-566). Expansion sets the chain and re-levels THROUGH
        manager.set_<side>_level (seam)."""
        entry = item.data(Qt.ItemDataRole.UserRole)
        if not entry:
            return
        clicked_lord = entry.get("lord", "")
        new_chain, new_level, expand = engine.click_expansion(clicked_lord, self.side.level)
        if expand:
            self.side.parent_chain = new_chain
            getattr(self.manager, self._names["set_level"])(new_level)
            buttons = self._required_widgets().level_buttons   # sol 6: raise if unbuilt
            for i, btn in enumerate(buttons):
                btn.setChecked((i + 1) == new_level)
        else:
            w = self._required_widgets()                       # sol 6: raise if unbuilt
            list_widget = w.list_widget
            row = list_widget.row(item)
            delegate = w.delegate
            if delegate is not None:
                current_sel = delegate.selected_row
                delegate.update_selected_row(None if current_sel == row else row)
                list_widget.viewport().update()

    def on_select(self, item):
        """Single-click select (move the ▶ marker) via manager._select_dasha_entry
        (the shared, side-parametrised helper stays in the manager, seam).

        Uses _required_widgets() (sol 6, w3-2c finding 2): at BASE this path
        resolved the list with a DEFAULT-LESS getattr, so an unbuilt panel raised
        AttributeError HERE, before _select_dasha_entry ran — not a silent None
        passed into the helper."""
        w = self._required_widgets()
        self.manager._select_dasha_entry(
            self.side, w.list_widget, item, w.delegate)

    def update_cycle_label(self):
        """Set the cycle-range label text (verbatim, engine.cycle_range_text)."""
        label = self.widgets().cycle_label
        if label is not None:
            label.setText(engine.cycle_range_text(self.side.cycle_offset))

    def scroll_to_row(self, row):
        """Scroll this side's list to `row`, centered (verbatim)."""
        lst = self.widgets().list_widget
        if lst is not None and lst.count() > row:
            item = lst.item(row)
            if item:
                lst.scrollToItem(item, QListWidget.ScrollHint.PositionAtCenter)

    def age_str(self, entry_jd, years_offset=0):
        """'Xy Zm' age for a period start, using the chart's birth Y/M/D
        (engine.age_text). Both sides compute identically; the manager keeps ONE
        delegation to the left controller (documented)."""
        chart = self.manager.gui.current_chart_data
        if not chart:
            return ""
        birth_ymd = (chart.get("year"), chart.get("month"), chart.get("day"))
        return engine.age_text(entry_jd, birth_ymd, years_offset)

    def auto_build_chain(self, rows, target_level):
        """Build the parent chain to `target_level` from the current periods
        (engine.auto_chain); on a cache gap recompute a fresh tree at the minimum
        depth and re-extract (verbatim _auto_build_parent_chain body)."""
        needed = target_level - 1
        chain = engine.auto_chain(rows, needed)
        if len(chain) == needed:
            return chain
        ayanamsa = self.side.ayanamsa
        try:
            from core.vimshottari_dasha import calculate_dasha_from_birth_data
            from AI_tools.AI_main_function.dasha import get_dasha_params
            gui = self.manager.gui
            params = get_dasha_params(
                gui.current_chart_data, is_human_design=gui.is_human_design)
            fresh = calculate_dasha_from_birth_data(
                params["year"], params["month"], params["day"],
                params["hour"], params["minute"], params["second"],
                dlevels=needed, ayanamsa=ayanamsa,
                tz_offset_hours=params["tz_offset"],
                moon_jd_override=params["moon_jd_override"],
                nak_mode=getattr(gui, "nakshatra_coords", "neither"),
                year_length=self.manager.year_length)
            chain = engine.auto_chain(fresh, needed)
        except Exception:
            pass
        return chain
