# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Planetary Condition compact panel controller (SPEC-KARAKAS-LAYOUT-001 Phase 2).

Width-constrained 4-column distillation of the fullscreen Planetary Condition
page: Planet | Houses | Tot | Condition. Rows colored by trimsamsa being type.
"""
import html as _html

from state import PanelControllerBase
from ui.qt_theme import (
    get_theme_colors, is_light_theme, scaled_area_px,
)


_PROFILE_PLANETS = [
    "Ascendant", "Sun", "Moon", "Mars", "Mercury",
    "Jupiter", "Venus", "Saturn", "Rahu", "Ketu",
]
_AVASTHA_7 = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]

_PLANET_SYMBOLS = {
    "Ascendant": "Asc", "Sun": "☉", "Moon": "☽", "Mars": "♂",
    "Mercury": "☿", "Jupiter": "♃", "Venus": "♀", "Saturn": "♄",
    "Rahu": "☊", "Ketu": "☋",
}

_BEING_TYPE_COLORS = {
    "Gandharva": ("#5C1A1A", "#E57373", "#FFEBEE", "#B71C1C"),
    "Rakshasa":  ("#4D4D10", "#F0C75E", "#FFFDE7", "#F57F17"),
    "Rishi":     ("#3D1A5C", "#CE93D8", "#F3E5F5", "#6A1B9A"),
    "Yaksha":    ("#4D3818", "#D4A76A", "#FBE9E7", "#4E342E"),
    "Apsara":    ("#102E5C", "#64B5F6", "#E3F2FD", "#1565C0"),
}


class PlanetaryConditionController(PanelControllerBase):

    def __init__(self, gui):
        super().__init__(gui=gui, lazy=True)

    def _on_chart_changed(self):
        self._refresh()

    def _on_mode_changed(self):
        self._refresh()

    def _on_theme_changed(self):
        self._refresh()

    def _refresh(self):
        gui = self._gui
        tb = getattr(gui, 'condition_compact_tb', None)
        if not tb:
            return

        chart = getattr(self._state, 'active_chart', None) if self._state else None
        if not chart:
            tb.setHtml("")
            return

        aditya_mode = self._state.aditya_mode
        use_western = getattr(gui, 'use_western_names', False)

        try:
            from AI_tools.AI_main_function.retinue import get_chart_retinue, _build_house_tally
            from AI_tools.AI_main_function.avastha import get_drishti_yuti_data, SIGN_RULERS
            from apps.widgets.info_panel_dialog import split_expression, InfoPanelDialog
            from core.aditya_mode import displayed_sign_name
            from core.chart_helpers import get_planet_sign_index, ADITYA_NAMES, TROPICAL_NAMES

            ayanamsa_offset = 0.0
            if aditya_mode == 'sidereal':
                ayanamsa_offset = getattr(gui, 'chart_ayanamsa_offset', 0.0)

            chart_data = get_chart_retinue(
                chart, ayanamsa_offset=ayanamsa_offset,
                tropical_mode=(aditya_mode == 'tropical_classic'))
            by_name = {r["planet"]: r for r in chart_data["planets"]}

            tally = _build_house_tally(chart_data["planets"])
            houses_by_planet = InfoPanelDialog._invert_house_tally(tally)

            data = get_drishti_yuti_data(chart)
            matrix = data["matrix"]
            dignity_data = data["dignity_data"]
            shame_pairs = data.get("shame_pairs", set())
            shamed_planets = data.get("shamed_planets", set())

            display_chart = chart
            if aditya_mode == 'sidereal':
                from core.chart_factory import rebuild_chart
                display_chart = rebuild_chart(chart, mode="sidereal")

            lajjitaadi = {}
            try:
                lajj_raw = chart.rashi().lajjitaadi_avasthas()
                if isinstance(lajj_raw, dict):
                    lajjitaadi = lajj_raw
            except Exception:
                pass

            lord_map = {}
            for pname in _PROFILE_PLANETS:
                if pname not in _AVASTHA_7:
                    idx = get_planet_sign_index(display_chart, pname, default=-1)
                    if idx >= 0:
                        for names in (ADITYA_NAMES, TROPICAL_NAMES):
                            lord = SIGN_RULERS.get(names[idx])
                            if lord and lord in _AVASTHA_7:
                                lord_map[pname] = lord
                                break

            descs = InfoPanelDialog._get_avastha_descriptions()

        except Exception as e:
            tb.setHtml(f"<p style='color:red;'>Load failed: {e}</p>")
            return

        theme = get_theme_colors()
        light = is_light_theme()
        base_px = scaled_area_px('tables')
        sm_px = base_px - 1
        text_color = theme['secondary_text']
        bg_color = theme['secondary_dark']
        bdr = theme['secondary_light']

        green = "#2E7D32" if light else "#A5D6A7"
        red = "#C62828" if light else "#EF9A9A"

        td_s = f"padding:2px 4px; border-bottom:1px solid {bdr}; vertical-align:middle;"
        th_s = (f"padding:2px 4px; text-align:left; font-weight:bold; "
                f"border-bottom:2px solid {bdr}; background:{theme['secondary']}; "
                f"font-size:{sm_px}px;")

        html = (
            f"<table cellpadding='0' cellspacing='0' "
            f"style='width:100%; table-layout:fixed; border-collapse:collapse; "
            f"font-size:{base_px}px; font-family:Inter,sans-serif; "
            f"color:{text_color};'>"
            f"<tr>"
            f"<th style='{th_s} width:30%;'>Planet</th>"
            f"<th style='{th_s} width:15%;'>Houses</th>"
            f"<th style='{th_s} width:10%; text-align:center;'>Tot</th>"
            f"<th style='{th_s} width:45%;'>Condition</th>"
            f"</tr>"
        )

        for pname in _PROFILE_PLANETS:
            r = by_name.get(pname)
            trim_type = r.get("trimsamsa", {}).get("being_type") if r else None
            bt_colors = _BEING_TYPE_COLORS.get(trim_type) if trim_type else None
            row_bg = (bt_colors[2] if light else bt_colors[0]) if bt_colors else bg_color
            row_fg = (bt_colors[3] if light else bt_colors[1]) if bt_colors else text_color
            is_shamed = pname in shamed_planets
            lbdr = f"border-left:3px solid {red};" if is_shamed else ""

            sym = _PLANET_SYMBOLS.get(pname, "")
            idx = get_planet_sign_index(display_chart, pname, default=-1)
            sign = displayed_sign_name(idx, aditya_mode, use_western) if idx >= 0 else "?"
            deg = f" {r['degrees']}°{r['minutes']:02d}'" if r else ""

            # Houses
            entries = houses_by_planet.get(pname, [])
            if entries:
                h_parts = []
                for e in entries:
                    color = ("#FFD54F" if not light else "#8B5E00") if e["ring"] == "H" \
                        else ("#80DEEA" if not light else "#0D4D6E")
                    h_parts.append(f"<span style='color:{color}; font-weight:bold;'>"
                                   f"{'H' if e['ring'] == 'H' else 'T'}{e['house']}</span>")
                houses_str = " ".join(h_parts)
            else:
                houses_str = "<span style='color:#666;'>-</span>"

            # Avastha total
            target = pname if pname in _AVASTHA_7 else lord_map.get(pname)
            if target:
                up, aff = split_expression(target, _AVASTHA_7, matrix, dignity_data, shame_pairs)
                total = up + aff
                tc = green if total > 0 else red if total < 0 else text_color
                tot_str = f"<span style='color:{tc}; font-weight:bold;'>{total:.0f}</span>"
            else:
                tot_str = "<span style='opacity:0.3;'>-</span>"

            # Condition
            cond_parts = []
            if target and target != pname:
                cond_parts.append(
                    f"<span style='opacity:0.6;'>{_PLANET_SYMBOLS.get(target, '')} {target}</span>")
            if target:
                states = lajjitaadi.get(target, {})
                for state_name in ("proud", "delighted", "healthy",
                                   "starved", "thirsty", "agitated", "shamed"):
                    factors = states.get(state_name)
                    if not factors:
                        continue
                    desc = descs.get(state_name, {})
                    sanskrit = desc.get("sanskrit", state_name.title())
                    sc = green if state_name in ("proud", "delighted", "healthy") else red
                    sv = sum(f.get("strength", 0) for f in factors if isinstance(f, dict))
                    sign_c = "+" if state_name in ("proud", "delighted", "healthy") else "-"
                    cond_parts.append(
                        f"<span style='color:{sc};'>{_html.escape(sanskrit)} {sign_c}{sv:.0f}</span>")
            cond_str = " &middot; ".join(cond_parts) if cond_parts else "-"

            short_name = "Asc" if pname == "Ascendant" else pname
            html += (
                f"<tr style='background:{row_bg}; color:{row_fg};'>"
                f"<td style='{td_s} {lbdr} white-space:nowrap;'>"
                f"<b>{sym} {short_name}</b> "
                f"<span style='font-size:{sm_px}px; opacity:0.6;'>"
                f"{_html.escape(sign)}{deg}</span></td>"
                f"<td style='{td_s}'>{houses_str}</td>"
                f"<td style='{td_s} text-align:center;'>{tot_str}</td>"
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
