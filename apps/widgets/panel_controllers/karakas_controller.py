# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Karakas panel controller — Phase 4 W2.4 (first sidereal-aware controller).

Migration source: managers/panel_update_manager.py:127-259.

Subscribes to active_chart + aditya_mode (no varga; karakas use D-1 always).
Sidereal mode handled at Chart level via rebuild_chart(mode="sidereal").

Pulls THREE things from core.sidereal_helpers (extracted in W0.5):
- get_sign_ruler
- ADITYA_NAMES
- TROPICAL_NAMES
"""

from PySide6.QtWidgets import QTableWidgetItem
from PySide6.QtCore import Qt

from state import PanelControllerBase
from ui.item_roles import ITEM_KEY_ROLE
from core.sidereal_helpers import (
    ADITYA_NAMES,
    TROPICAL_NAMES,
    get_sign_ruler,
)

_PLANET_SYMBOLS = {
    "Sun": "☉", "Moon": "☽", "Mars": "♂",
    "Mercury": "☿", "Jupiter": "♃", "Venus": "♀", "Saturn": "♄",
}

_KARAKA_ROLES = [
    ("AK", "Atma", "(Self)", "1st"),
    ("AmK", "Amatya", "(Minister)", "10th"),
    ("BK", "Bhratru", "(Brother)", "3rd"),
    ("MK", "Matru", "(Mother)", "4th"),
    ("PiK", "Pitru", "(Father)", "9th"),
    ("GK", "Gnati", "(Relatives)", "2nd"),
    ("DK", "Dara", "(Spouse)", "7th"),
]

_PLANET_NAMES_FOR_RANKING = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]


class KarakasController(PanelControllerBase):
    """Subscribes to active_chart + aditya_mode events.

    Karakas (Chara Karaka system) rank the 7 grahas by in-sign degree —
    sidereal mode shifts the in-sign degree, so ranking can change. AK + DK
    rows are highlighted via the karakas_delegate.
    """

    def __init__(self, gui):
        super().__init__(gui=gui, lazy=False)
        # The chart the table currently shows (None = not rendered): the AI
        # capture marks the region 'stale' otherwise (SPEC-AIC-001 INV-2).
        self.rendered_chart = None

    def _on_chart_changed(self):
        self._refresh()

    def _on_mode_changed(self):
        self._refresh()

    def _refresh(self):
        gui = self._gui
        if not hasattr(gui, "karakas_table"):
            return

        chart = getattr(self._state, 'active_chart', None) if self._state else None
        if not chart:
            return
        gui.karakas_table.clearContents()
        self.rendered_chart = None

        try:
            # One calculation for panel, CLI and MCP (SPEC-AIC-001 INV-1):
            # core/capabilities/karakas_aspects.karaka_rows is get_karakas.
            from core.capabilities.karakas_aspects import karaka_rows
            rows = karaka_rows(chart, self._state.aditya_mode)
            highlight_rows = set()
            center = Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
            for i, row in enumerate(rows):
                item0 = QTableWidgetItem(row["karaka"])
                item0.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                gui.karakas_table.setItem(i, 0, item0)

                symbol = _PLANET_SYMBOLS.get(row["planet"], "?")
                item1 = QTableWidgetItem(f"{symbol} {row['planet']}")
                item1.setData(ITEM_KEY_ROLE, row["planet"])  # INV-3: the key
                item1.setTextAlignment(center)
                gui.karakas_table.setItem(i, 1, item1)

                if row["lord"]:
                    lord_symbol = _PLANET_SYMBOLS.get(row["lord"], "?")
                    item2 = QTableWidgetItem(
                        f"{row['lord_of']} Lord: {lord_symbol} {row['lord']}")
                    item2.setTextAlignment(center)
                    gui.karakas_table.setItem(i, 2, item2)

                if row["highlight"]:
                    highlight_rows.add(i)
            planet_degrees = [{"name": r["planet"], "degree": r["degree_in_sign"]}
                              for r in rows]

            if hasattr(gui, "karakas_delegate"):
                gui.karakas_delegate.update_highlights(highlight_rows)
                gui.karakas_table.viewport().update()

            self._refresh_enriched(chart, planet_degrees)
            self.rendered_chart = chart

        except Exception as e:
            print(f"Error updating Karakas: {e}")

    def _refresh_enriched(self, chart, planet_degrees):
        """Karakas + Avastha enriched view (Phase 2, SPEC-KARAKAS-LAYOUT-001)."""
        import html as _html
        gui = self._gui
        tb = getattr(gui, 'karakas_enriched_tb', None)
        if not tb or not chart or not planet_degrees:
            return
        inner_stack = getattr(gui, 'karakas_inner_stack', None)
        if inner_stack and inner_stack.currentIndex() != 1:
            return

        try:
            from apps.widgets.panel_controllers.planetary_condition_controller import _BEING_TYPE_COLORS
            from core.capabilities.karakas_aspects import karaka_enriched
            from ui.qt_theme import get_theme_colors, is_light_theme, scaled_area_px

            # One calculation for panel, CLI and MCP (SPEC-AIC-001 INV-1):
            # the rows are get_karakas' "enriched" data; this method only styles.
            aditya_mode = self._state.aditya_mode
            ayanamsa_offset = (getattr(gui, 'chart_ayanamsa_offset', 0.0)
                               if aditya_mode == 'sidereal' else 0.0)
            enriched = karaka_enriched(
                chart, aditya_mode, getattr(gui, 'use_western_names', False),
                ayanamsa_offset=ayanamsa_offset)

            theme = get_theme_colors()
            light = is_light_theme()
            base_px = scaled_area_px('tables')
            sm_px = base_px - 1
            text_color = theme['secondary_text']
            bg_color = theme['secondary_dark']
            bdr = theme['secondary_light']
            green = "#2E7D32" if light else "#A5D6A7"
            red = "#C62828" if light else "#EF9A9A"
            purple = "#7B1FA2" if light else "#CE93D8"
            gold = "#FFD54F" if not light else "#8B5E00"
            cyan = "#80DEEA" if not light else "#0D4D6E"

            td_s = f"padding:5px 4px; border-bottom:1px solid {bdr}; vertical-align:top;"
            th_s = (f"padding:4px; text-align:left; font-weight:bold; "
                    f"border-bottom:2px solid {bdr}; background:{theme['secondary']}; "
                    f"font-size:{sm_px}px;")

            html = (
                f"<table cellpadding='0' cellspacing='0' "
                f"style='width:100%; table-layout:fixed; border-collapse:collapse; "
                f"font-size:{base_px}px; font-family:Inter,sans-serif; "
                f"color:{text_color};'>"
                f"<tr>"
                f"<th style='{th_s} width:30%;'>Karaka</th>"
                f"<th style='{th_s} width:14%;'>Houses</th>"
                f"<th style='{th_s} width:8%; text-align:center;'>Tot</th>"
                f"<th style='{th_s} width:48%;'>Condition</th>"
                f"</tr>"
            )

            role_names = {code: name for code, name, _m, _c in _KARAKA_ROLES}
            dig_names = {"exaltation": "Exalted", "mulatrikona": "Moolatrikona",
                         "own_sign": "Own House"}
            for row in enriched:
                code, pname = row["code"], row["planet"]
                name = role_names[code]
                sym = _PLANET_SYMBOLS.get(pname, "?")

                trim_type = row["trimsamsa_type"]
                bt_colors = _BEING_TYPE_COLORS.get(trim_type) if trim_type else None
                row_bg = (bt_colors[2] if light else bt_colors[0]) if bt_colors else bg_color
                row_fg = (bt_colors[3] if light else bt_colors[1]) if bt_colors else text_color

                sign, deg = row["sign"], row["degree"]

                if row["houses"]:
                    houses_str = " ".join(
                        f"<span style='color:{gold if h['ring'] == 'H' else cyan}; "
                        f"font-weight:bold;'>{h['text']}</span>" for h in row["houses"])
                else:
                    houses_str = "<span style='opacity:0.4;'>-</span>"

                total = row["avastha_total"]
                tc = green if total > 0 else red if total < 0 else text_color
                sign_char = "+" if total > 0 else ""

                # Condition words come from the shared data; only colour here.
                style = {"Shamed": f"color:{red}; font-weight:bold;",
                         "Starved": f"color:{red};", "Supported": f"color:{green};",
                         trim_type: "opacity:0.7;"}
                if row["dignity"]:
                    style[dig_names.get(row["dignity"], "?")] = f"color:{purple}; font-weight:bold;"
                cond_parts = [f"<span style='{style.get(word, '')}'>{_html.escape(word)}</span>"
                              for word in row["condition"]]
                cond_str = " &middot; ".join(cond_parts) if cond_parts else "-"

                is_ak_dk = code in ("AK", "DK")
                bold = "font-weight:bold;" if is_ak_dk else ""
                ak_border = f"border-left:3px solid {theme['primary']};" if is_ak_dk else ""

                html += (
                    f"<tr style='background:{row_bg}; color:{row_fg};'>"
                    f"<td style='{td_s} {bold} {ak_border}'>"
                    f"{sym} {code} {_html.escape(name)}<br>"
                    f"<span style='font-size:{sm_px}px; opacity:0.7; font-weight:normal;'>"
                    f"{_html.escape(sign)} {deg}</span></td>"
                    f"<td style='{td_s} font-size:{sm_px}px;'>{houses_str}</td>"
                    f"<td style='{td_s} text-align:center; color:{tc}; font-weight:bold;'>"
                    f"{sign_char}{total:.0f}</td>"
                    f"<td style='{td_s} font-size:{sm_px}px;'>{cond_str}</td>"
                    f"</tr>"
                )

            html += "</table>"
            tb.setHtml(html)
            tb.document().setDocumentMargin(0)
            tb.setStyleSheet(f"""
                QTextBrowser {{
                    background-color: {bg_color};
                    color: {text_color};
                    border: none;
                    padding: 0px;
                }}
            """)

        except Exception as e:
            print(f"Error updating Karakas enriched: {e}")
