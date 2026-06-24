# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
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

        try:
            from core.chart_helpers import (
                get_planet_in_sign_longitude, has_planet,
                ADITYA_NAMES as _AD, TROPICAL_NAMES as _TR,
            )

            planet_degrees = []
            for name in _PLANET_NAMES_FOR_RANKING:
                if has_planet(chart, name):
                    deg = get_planet_in_sign_longitude(chart, name)
                    planet_degrees.append({"name": name, "degree": deg})

            planet_degrees.sort(key=lambda x: x["degree"], reverse=True)

            # Cusp lords using Whole Sign Houses from Ascendant
            cusp_lords = {}
            current_aditya_mode = self._state.aditya_mode
            asc_sign_index = -1
            try:
                asc_cusp = chart.rashi().cusps()[1]
                asc_sign_index = (asc_cusp.sign() - 1) % 12
            except (KeyError, IndexError, TypeError):
                pass

            if asc_sign_index >= 0:
                house_nums = {"1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "7th": 7, "9th": 9, "10th": 10}

                for cusp_id, house_num in house_nums.items():
                    sign_index = (asc_sign_index + house_num - 1) % 12
                    if current_aditya_mode == "aditya":
                        sign_name = ADITYA_NAMES[sign_index]
                    else:
                        sign_name = TROPICAL_NAMES[sign_index]
                    cusp_lords[cusp_id] = get_sign_ruler(sign_name)

            highlight_rows = set()

            for i, (karaka_code, karaka_name, meaning, cusp_id) in enumerate(_KARAKA_ROLES):
                if i < len(planet_degrees):
                    p = planet_degrees[i]
                    symbol = _PLANET_SYMBOLS.get(p["name"], "?")

                    karaka_text = f"{karaka_code} - {karaka_name} {meaning}"
                    item0 = QTableWidgetItem(karaka_text)
                    item0.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                    gui.karakas_table.setItem(i, 0, item0)

                    planet_text = f"{symbol} {p['name']}"
                    item1 = QTableWidgetItem(planet_text)
                    item1.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
                    gui.karakas_table.setItem(i, 1, item1)

                    if cusp_id in cusp_lords:
                        lord_planet = cusp_lords[cusp_id]
                        lord_symbol = _PLANET_SYMBOLS.get(lord_planet, "?")
                        if cusp_id == "1st":
                            lord_label = "Asc"
                        elif cusp_id == "7th":
                            lord_label = "Dsc"
                        elif cusp_id == "4th":
                            lord_label = "IC"
                        else:
                            lord_label = cusp_id
                        lord_text = f"{lord_label} Lord: {lord_symbol} {lord_planet}"
                        item2 = QTableWidgetItem(lord_text)
                        item2.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
                        gui.karakas_table.setItem(i, 2, item2)

                    if karaka_code in ("AK", "DK"):
                        highlight_rows.add(i)

            if hasattr(gui, "karakas_delegate"):
                gui.karakas_delegate.update_highlights(highlight_rows)
                gui.karakas_table.viewport().update()

            self._refresh_enriched(chart, planet_degrees)

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
            from AI_tools.AI_main_function.avastha import get_drishti_yuti_data
            from AI_tools.AI_main_function.retinue import get_chart_retinue
            from apps.widgets.info_panel_dialog import split_expression
            from ui.qt_theme import get_theme_colors, is_light_theme, scaled_area_px

            aditya_mode = self._state.aditya_mode
            ayanamsa_offset = 0.0
            if aditya_mode == 'sidereal':
                ayanamsa_offset = getattr(gui, 'chart_ayanamsa_offset', 0.0)

            retinue = get_chart_retinue(
                chart, ayanamsa_offset=ayanamsa_offset,
                tropical_mode=(aditya_mode == 'tropical_classic'))
            retinue_by_name = {r["planet"]: r for r in retinue["planets"]}

            from AI_tools.AI_main_function.retinue import _build_house_tally
            from apps.widgets.info_panel_dialog import InfoPanelDialog
            tally = _build_house_tally(retinue["planets"])
            houses_by_planet = InfoPanelDialog._invert_house_tally(tally)

            from core.aditya_mode import displayed_sign_name
            from core.chart_helpers import get_planet_sign_index
            use_western = getattr(gui, 'use_western_names', False)

            display_chart = chart
            if aditya_mode == 'sidereal':
                from core.chart_factory import rebuild_chart
                display_chart = rebuild_chart(chart, mode="sidereal")

            data = get_drishti_yuti_data(chart)
            matrix = data["matrix"]
            dignity_data = data["dignity_data"]
            shame_pairs = data.get("shame_pairs", set())

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

            _AVASTHA_7 = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]

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

            for i, (code, name, meaning, cusp_id) in enumerate(_KARAKA_ROLES):
                if i >= len(planet_degrees):
                    break
                p = planet_degrees[i]
                pname = p["name"]
                sym = _PLANET_SYMBOLS.get(pname, "?")

                r = retinue_by_name.get(pname)
                trim_type = r.get("trimsamsa", {}).get("being_type") if r else None
                bt_colors = _BEING_TYPE_COLORS.get(trim_type) if trim_type else None
                row_bg = (bt_colors[2] if light else bt_colors[0]) if bt_colors else bg_color
                row_fg = (bt_colors[3] if light else bt_colors[1]) if bt_colors else text_color

                # Sign + degree
                idx = get_planet_sign_index(display_chart, pname, default=-1)
                sign = displayed_sign_name(idx, aditya_mode, use_western) if idx >= 0 else "?"
                deg = f"{r['degrees']}°{r['minutes']:02d}'" if r else ""

                # House connections
                entries = houses_by_planet.get(pname, [])
                if entries:
                    h_parts = []
                    for e in entries:
                        hc = gold if e["ring"] == "H" else cyan
                        h_parts.append(f"<span style='color:{hc}; font-weight:bold;'>"
                                       f"{'H' if e['ring'] == 'H' else 'T'}{e['house']}</span>")
                    houses_str = " ".join(h_parts)
                else:
                    houses_str = "<span style='opacity:0.4;'>-</span>"

                up, aff = split_expression(pname, _AVASTHA_7, matrix, dignity_data, shame_pairs)
                total = up + aff
                tc = green if total > 0 else red if total < 0 else text_color
                sign_char = "+" if total > 0 else ""

                cond_parts = []
                dig = dignity_data.get(pname)
                if dig:
                    dig_names = {"exaltation": "Exalted", "mulatrikona": "Moolatrikona", "own_sign": "Own House"}
                    cond_parts.append(
                        f"<span style='color:{purple}; font-weight:bold;'>"
                        f"{dig_names.get(dig['type'], '?')}</span>")

                if pname in data.get("shamed_planets", set()):
                    cond_parts.append(f"<span style='color:{red}; font-weight:bold;'>Shamed</span>")
                elif not dig and total < 0:
                    cond_parts.append(f"<span style='color:{red};'>Starved</span>")
                elif not dig and total > 0:
                    cond_parts.append(f"<span style='color:{green};'>Supported</span>")

                if trim_type:
                    cond_parts.append(
                        f"<span style='opacity:0.7;'>{_html.escape(trim_type)}</span>")

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
