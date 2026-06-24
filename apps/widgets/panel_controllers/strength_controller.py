# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Strength panel controller — Phase 4 W2.5 (sidereal-aware).

Migration source: managers/panel_update_manager.py:265-361.

Sidereal mode is handled inside bala_calculator.get_all_bala_data():
sidereal longitudes are converted to tropical via ayanamsa offset,
and aditya_mode is set to 'classic' (tropical exaltation degrees).

No varga subscription — strength is D-1 only (per upstream comment).
"""

from PySide6.QtWidgets import QTableWidgetItem
from PySide6.QtCore import Qt

from core.bala_calculator import STRENGTH_THRESHOLD
from state import PanelControllerBase

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

        try:
            from core.bala_calculator import get_all_bala_data
            bala_data = get_all_bala_data(chart)

            highlight_cells = set()
            retrograde_rows = set()

            for i, planet_name in enumerate(_PLANET_ORDER):
                if planet_name in bala_data:
                    data = bala_data[planet_name]
                    symbol = _PLANET_SYMBOLS.get(planet_name, "?")
                    digbala = data.get("digbala", 0)
                    uccha = data.get("uccha", 0)
                    chesta = data.get("chesta", 0)

                    planet_text = f"{symbol} {planet_name}"
                    item0 = QTableWidgetItem(planet_text)
                    item0.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                    gui.strength_table.setItem(i, 0, item0)

                    item1 = QTableWidgetItem(f"{digbala:.1f}")
                    item1.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
                    gui.strength_table.setItem(i, 1, item1)
                    if digbala > STRENGTH_THRESHOLD:
                        highlight_cells.add((i, 1))

                    item2 = QTableWidgetItem(f"{uccha:.1f}")
                    item2.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
                    gui.strength_table.setItem(i, 2, item2)
                    if uccha > STRENGTH_THRESHOLD:
                        highlight_cells.add((i, 2))

                    is_retro = False
                    if planet_name in ("Mars", "Mercury", "Jupiter", "Venus", "Saturn"):
                        try:
                            p = chart.rashi().planets()[planet_name]
                            is_retro = p.retrograde()
                        except (KeyError, AttributeError):
                            pass
                    chesta_text = f"{chesta:.1f} R*" if is_retro else f"{chesta:.1f}"
                    item3 = QTableWidgetItem(chesta_text)
                    item3.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
                    if is_retro:
                        retrograde_rows.add(i)
                        item3.setToolTip(f"{planet_name} is retrograde")
                    gui.strength_table.setItem(i, 3, item3)
                    if chesta > STRENGTH_THRESHOLD:
                        highlight_cells.add((i, 3))

            if hasattr(gui, "strength_delegate"):
                gui.strength_delegate.update_highlights(highlight_cells)
                gui.strength_delegate.update_retrogrades(retrograde_rows)
                gui.strength_table.viewport().update()

        except Exception as e:
            print(f"Error updating Strength: {e}")
