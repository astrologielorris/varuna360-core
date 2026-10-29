# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Strength panel controller — Phase 4 W2.5 (sidereal-aware).

Migration source: managers/panel_update_manager.py:265-361.

Sidereal mode is handled inside bala_calculator.get_all_bala_data():
sidereal longitudes are converted to tropical via ayanamsa offset,
and aditya_mode is set to 'classic' (tropical exaltation degrees).

No varga subscription — strength is D-1 only (per upstream comment).

The DUC Bala column follows the ``strength.duc_method`` setting (SPEC-STR-001
§7.5): read at each refresh, and a change of it refreshes the table like a
chart change (gated on visibility, coalesced).
"""

from PySide6.QtWidgets import QTableWidgetItem
from PySide6.QtCore import Qt

from apps.widgets.panel_controllers.duc_method import (current_duc_method, subscribe_chart_redraw,
                                                       subscribe_duc_method)
from state import PanelControllerBase
from ui.item_roles import ITEM_KEY_ROLE

_PLANET_SYMBOLS = {
    "Sun": "☉", "Moon": "☽", "Mars": "♂",
    "Mercury": "☿", "Jupiter": "♃", "Venus": "♀", "Saturn": "♄",
}
_PLANET_ORDER = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]


class StrengthController(PanelControllerBase):
    """Subscribes to active_chart + aditya_mode events.

    Strength is D-1 only (aspects/strength stay D-1 per project conventions
    in core_gui_qt.py:3819 — "strength same across vargas").
    """

    def __init__(self, gui):
        super().__init__(gui=gui, lazy=False)
        # The chart the table currently shows (None = not rendered): the AI
        # capture marks the Strength region 'stale' when it is not the active
        # chart (SPEC-AIC-001 INV-2).
        self.rendered_chart = None
        subscribe_duc_method(self, gui)
        # The chart views colour by DUC too (retinue strength, Jewel Lamp, glow):
        # one window-wide redraw on a method change, installed once with the
        # always-built Strength controller.
        subscribe_chart_redraw(gui)

    def _on_chart_changed(self):
        self._refresh()

    def _on_mode_changed(self):
        self._refresh()

    def _refresh(self):
        gui = self._gui
        if not hasattr(gui, "strength_table"):
            return

        chart = getattr(self._state, 'active_chart', None) if self._state else None
        if not chart:
            return

        gui.strength_table.clearContents()
        self.rendered_chart = None

        try:
            # One calculation for panel, CLI and MCP (SPEC-AIC-001 INV-1):
            # core/capabilities/strength.strength_rows is get_strength's data.
            from core.capabilities.strength import strength_rows
            by_planet = {r["planet"]: r for r in strength_rows(chart, current_duc_method())}

            highlight_cells = set()
            retrograde_rows = set()
            center = Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter

            for i, planet_name in enumerate(_PLANET_ORDER):
                row = by_planet.get(planet_name)
                if row is None:
                    continue
                symbol = _PLANET_SYMBOLS.get(planet_name, "?")
                item0 = QTableWidgetItem(f"{symbol} {planet_name}")
                item0.setData(ITEM_KEY_ROLE, planet_name)  # INV-3: the key
                item0.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                gui.strength_table.setItem(i, 0, item0)

                # Cols 1-4: Dig, Uccha, Chesta (" R*" when retrograde), DUC
                # (mean of the three; the R* marker belongs on Chesta only).
                for col, key in enumerate(("digbala", "uccha", "chesta", "duc_bala"), 1):
                    item = QTableWidgetItem(row["text"][key])
                    item.setTextAlignment(center)
                    if key == "chesta" and row["retrograde"]:
                        retrograde_rows.add(i)
                        item.setToolTip(f"{planet_name} is retrograde")
                    gui.strength_table.setItem(i, col, item)
                    if row["strong"][key]:
                        highlight_cells.add((i, col))

            if hasattr(gui, "strength_delegate"):
                gui.strength_delegate.update_highlights(highlight_cells)
                gui.strength_delegate.update_retrogrades(retrograde_rows)
                gui.strength_table.viewport().update()
            self.rendered_chart = chart

        except Exception as e:
            print(f"Error updating Strength: {e}")
