# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Avastha panel controller — Phase 4 W2.7 (LAZY + sidereal-aware).

Migration source: managers/panel_update_manager.py:712-829.

LAZY mode (lazy=True): defers refresh until set_visible(True) is called.
Wired by apps/panels/info_panels.py:switch_to_avastha → set_visible(True),
and by switch_to_aspects/switch_to_shame/switch_to_tajika_* → set_visible(False).

Always D1. Does not react to varga changes.

Pre-mortem fixes embedded:
- pm-20260503-003: lazy-deferred chart and mode events (separate pending flags)
- pm-20260503-007: trigger is button-click, not non-existent QWidget.shown signal
"""

from PySide6.QtWidgets import QTableWidgetItem
from PySide6.QtCore import Qt

from state import PanelControllerBase


class AvasthaController(PanelControllerBase):
    """Subscribes to active_chart + aditya_mode events. Lazy.
    Always uses D1 regardless of active varga.

    7x7 drishti/yuti relationship matrix with dignity diagonal, shame pairs,
    DUAL/FRIEND/ENEMY/NEUTRAL classifications, and a TOTALS row.
    """

    def __init__(self, gui):
        super().__init__(gui=gui, lazy=True)

    def _on_chart_changed(self):
        self._refresh()

    def _on_mode_changed(self):
        self._refresh()

    def _refresh(self):
        gui = self._gui
        if not hasattr(gui, "avastha_table"):
            return

        chart = getattr(self._state, 'active_chart', None) if self._state else None
        if not chart:
            return

        gui.avastha_table.clearContents()

        try:
            from AI_tools.AI_main_function.avastha import (
                get_drishti_yuti_data, ASPECTING_PLANETS, REL_SYMBOL,
            )

            if self._state.aditya_mode == "sidereal":
                from core.chart_factory import rebuild_chart
                chart = rebuild_chart(chart, mode="sidereal")

            planets = chart

            data = get_drishti_yuti_data(planets)
            matrix = data["matrix"]
            dignity_data = data["dignity_data"]
            shamed_planets = data["shamed_planets"]
            shame_pairs = data.get("shame_pairs", set())

            cell_categories = {}
            planet_order = list(ASPECTING_PLANETS)

            for row_idx, aspecting in enumerate(planet_order):
                for col_idx, aspected in enumerate(planet_order):
                    if aspecting == aspected:
                        dig = dignity_data.get(aspecting)
                        if dig:
                            abbr = {"exaltation": "EX", "mulatrikona": "MK", "own_sign": "OH"}
                            label = abbr.get(dig["type"], "?")
                            text = f"{label}={dig['virupas']}"
                            cell_categories[(row_idx, col_idx)] = "PROUD"
                        else:
                            text = "-"
                    else:
                        entry = matrix.get((aspecting, aspected))
                        if entry is None or (not entry.get("is_yuti") and entry["virupas"] <= 0):
                            text = "."
                        else:
                            vr = entry["virupas"] if entry.get("is_yuti") else entry["virupas"]
                            rel = entry["relationship"]
                            sym = REL_SYMBOL.get(rel, " ")

                            if (aspecting, aspected) in shame_pairs:
                                if rel in ("NEUTRAL", "N/A"):
                                    sym = "-"
                                text = f"{vr:.0f}{sym}!"
                                cell_categories[(row_idx, col_idx)] = "SHAME"
                            elif rel == "DUAL":
                                text = f"{vr:.0f}±"
                                cell_categories[(row_idx, col_idx)] = "DUAL"
                            else:
                                text = f"{vr:.0f}{sym}"
                                if rel in ("FRIEND", "ENEMY", "NEUTRAL"):
                                    cell_categories[(row_idx, col_idx)] = rel

                    item = QTableWidgetItem(text)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    gui.avastha_table.setItem(row_idx, col_idx, item)

            # TOTALS row (index 7)
            col_totals = []
            for col_idx, aspected in enumerate(planet_order):
                col_total = 0.0
                dig = dignity_data.get(aspected)
                if dig:
                    col_total += dig["virupas"]
                for aspecting in planet_order:
                    if aspecting == aspected:
                        continue
                    entry = matrix.get((aspecting, aspected))
                    if entry and entry["virupas"] > 0:
                        if (aspecting, aspected) in shame_pairs:
                            col_total -= 60
                        elif entry["relationship"] == "DUAL":
                            pass
                        elif entry["relationship"] == "FRIEND":
                            col_total += entry["virupas"]
                        elif entry["relationship"] == "ENEMY":
                            col_total -= entry["virupas"]

                col_totals.append(col_total)
                item = QTableWidgetItem(f"{col_total:.0f}")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                gui.avastha_table.setItem(7, col_idx, item)

            # SIGN row (index 8) — which sign each planet occupies, colored
            # by the planet's TOTAL: boosted (green) / afflicted (red).
            # Mirrors the CLI's show_signs row in avastha.py.
            from core.chart_helpers import (
                get_planet_sign_index, ADITYA_NAMES, TROPICAL_NAMES,
            )
            sign_names = (ADITYA_NAMES if self._state.aditya_mode == "aditya"
                          else TROPICAL_NAMES)
            for col_idx, aspected in enumerate(planet_order):
                sign_idx = get_planet_sign_index(planets, aspected, default=-1)
                sign_text = sign_names[sign_idx] if 0 <= sign_idx < 12 else "?"
                item = QTableWidgetItem(sign_text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                gui.avastha_table.setItem(8, col_idx, item)
                if col_totals[col_idx] > 0:
                    cell_categories[(8, col_idx)] = "FRIEND"
                elif col_totals[col_idx] < 0:
                    cell_categories[(8, col_idx)] = "ENEMY"
                else:
                    cell_categories[(8, col_idx)] = "NEUTRAL"

            if hasattr(gui, "avastha_delegate"):
                gui.avastha_delegate.update_categories(cell_categories)
                gui.avastha_table.viewport().update()

        except Exception as e:
            import traceback
            print(f"Error updating Avastha: {e}")
            traceback.print_exc()
