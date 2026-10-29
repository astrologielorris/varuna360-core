# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Planetary Ages (Nisarga) renderer for one dasha side (SPEC-DSH-004).

Body moved verbatim from the retired `DashaManager.update_nisarga_dasha`
(SPEC-DSH-002 era, right panel only); now bound to whichever side shows it.
Nisarga has no drill, no per-period select and no navigation: those verbs are
documented no-ops (today's behaviour).
"""

from PySide6.QtWidgets import QListWidgetItem
from PySide6.QtCore import Qt


class NisargaRenderer:
    """Lists Nisarga periods (level 1: 7 periods + maturation ages; level 2:
    sub-periods) on one side's list."""

    def __init__(self, manager, side_name):
        self.manager = manager
        self.side_name = side_name

    @property
    def state(self):
        return self.manager.dasha_state.side(self.side_name)

    @property
    def side(self):
        return self.manager.sides[self.side_name]

    # -- protocol ----------------------------------------------------------- #

    def invalidate(self):
        pass                    # renders synchronously; nothing to abort

    def enter(self, panel):
        """Per-mode data resets after set_shape (none for Nisarga)."""

    def checked_level(self):
        return self.state.nisarga_level

    def capture_options(self):
        """get_planetary_ages options of what this side lists."""
        return {"level": int(self.state.nisarga_level)}

    def context_cycle_offset(self):
        return 0

    def set_level(self, level):
        """1 = periods + maturation, 2 = sub-periods."""
        self.state.nisarga_level = level
        self.manager.update_side(self.side_name)

    def on_drill(self, item):
        return                  # Nisarga does not drill

    def on_select(self, item):
        return                  # no per-period select

    def nav_prev(self):
        return                  # arrows hidden; a programmatic call is a no-op

    def nav_next(self):
        return

    def on_title_clicked(self):
        return                  # title button is disabled in this mode

    def render(self):
        """Update the side's list with Nisarga dasha data."""
        side = self.side
        # Nisarga replaces the shared list: abort any in-flight Vimshottari
        # render of this side so its stale rows can never land here.
        side.invalidate()
        p = side.panel
        if p is not None:
            p.set_title("Planetary Ages")
        lst = p.list_widget                 # AttributeError pre-build, as before
        lst.clear()
        p.mark_rendered(None)

        if p is not None and p.delegate is not None:
            p.delegate.update_highlights(set())
            p.delegate.update_maturation_highlights(set())

        chart = self.manager.gui.current_chart_data
        if not chart:
            return

        birth_y = chart.get('year')
        birth_m = chart.get('month')
        birth_d = chart.get('day')
        if not all([birth_y, birth_m, birth_d]):
            return

        try:
            from core.nisarga_dasha import format_nisarga_level1, format_nisarga_level2

            level = self.state.nisarga_level

            if level == 2:
                entries = format_nisarga_level2(birth_y, birth_m, birth_d)
            else:
                entries = format_nisarga_level1(birth_y, birth_m, birth_d)

            highlight_rows = set()
            maturation_rows = set()

            for i, entry in enumerate(entries):
                item = QListWidgetItem(entry['text'])
                item.setData(Qt.ItemDataRole.UserRole, entry)
                if entry.get('is_separator'):
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                lst.addItem(item)
                if entry.get('is_current'):
                    highlight_rows.add(i)
                if entry.get('is_maturation'):
                    maturation_rows.add(i)

            if p is not None and p.delegate is not None:
                p.delegate.update_highlights(highlight_rows)
                p.delegate.update_maturation_highlights(maturation_rows)
                lst.viewport().update()

            # Scroll to current period (prefer period highlight over maturation),
            # guarded by the side generation (SPEC-DSH-004 INV-9).
            scroll_rows = highlight_rows if highlight_rows else maturation_rows
            if scroll_rows:
                side.later(100, lambda r=min(scroll_rows):
                           self.manager.scroll_to_row(self.side_name, r))

            self.manager.refresh_dasha_lord_highlights(self.side_name)
            p.mark_rendered(self.manager.gui.state.active_chart)

        except Exception as e:
            import traceback
            print(f"Error updating Nisarga dasha: {e}")
            traceback.print_exc()
