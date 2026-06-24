# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Shame panel controller — Phase 4 W2.8 (LAZY + sidereal-aware).

Migration source: managers/panel_update_manager.py:835-937.

Writes HTML to a QTextEdit (shame_display), not a QTableWidget.
Same lazy + sidereal pattern as AvasthaController.

Visibility wired by apps/panels/info_panels.py:switch_to_shame.
"""

from state import PanelControllerBase


class ShameController(PanelControllerBase):
    """Subscribes to active_chart + aditya_mode events. Lazy.

    Lajjita (shame) avastha — HTML table with shamed planet, sign, house,
    shamer, and source. Theme-driven colors with semantic accents
    (red for shamed, orange for shamer).
    """

    def __init__(self, gui):
        super().__init__(gui=gui, lazy=True)

    def _on_chart_changed(self):
        self._refresh()

    def _on_mode_changed(self):
        self._refresh()

    def _on_varga_changed(self):
        # Phase 4 W5: same lazy-aware varga handling as avastha
        if self._lazy and not self._is_visible:
            self._pending_chart_refresh = True
            return
        self._refresh()

    def _refresh(self):
        gui = self._gui
        if not hasattr(gui, "shame_display"):
            return

        chart = getattr(self._state, 'active_chart', None) if self._state else None
        if not chart:
            gui.shame_display.setHtml("")
            return

        try:
            from AI_tools.AI_main_function.shame import get_shame_avastha
            from AI_tools.AI_main_function.houses import get_planets_by_house
            from ui.qt_theme import (
                get_theme_colors, STATUS,
                scaled_px, scaled_area_px, is_light_theme,
            )

            theme = get_theme_colors()
            light = is_light_theme()
            clr_error = STATUS["error"]
            clr_warning = STATUS["warning"]
            clr_success = "#2E7D32" if light else STATUS["success"]
            # SPEC-THM-001 G18: live theme colors instead of frozen BORDER / TEXT_TERTIARY.
            border_clr = theme["secondary_light"]
            subtle_clr = theme["secondary_text"]

            if self._state.aditya_mode == "sidereal":
                from core.chart_factory import rebuild_chart
                chart = rebuild_chart(chart, mode="sidereal")

            varga_num = self._state.current_varga if self._state else 1
            planets = chart.varga(varga_num) if varga_num != 1 else chart

            shame_data = get_shame_avastha(planets)
            house_data = get_planets_by_house(planets)

            sign_to_house = {}
            if house_data["houses"]:
                for h_num, h_info in house_data["houses"].items():
                    sign_to_house[h_info["sign"]] = h_num

            if not shame_data["has_shame"]:
                bg_style = "background-color: #FFFFFF;" if light else ""
                html = f"""
                <div style="color: {clr_success}; font-size: {scaled_area_px('info_text')}px; padding: 20px; text-align: center; {bg_style}">
                    <p style="font-size: {scaled_area_px('panel_titles')}px; font-weight: bold;">No shame configurations detected</p>
                    <p style="color: {subtle_clr};">This chart has no Lajjita (shame) avastha.</p>
                """
                if shame_data.get("note"):
                    html += f'<p style="color: {clr_warning}; font-size: {scaled_area_px("status")}px;">{shame_data["note"]}</p>'
                html += "</div>"
                gui.shame_display.setHtml(html)
                return

            rows_html = ""
            for planet, sign, shamer, source in shame_data["all_shamed"]:
                house_str = str(sign_to_house.get(sign, "?"))
                rows_html += f"""
                <tr>
                    <td style="padding: 4px 8px; border: 1px solid {border_clr}; color: {clr_error}; font-weight: bold;">{planet}</td>
                    <td style="padding: 4px 8px; border: 1px solid {border_clr}; color: {theme['secondary_text']};">{sign}</td>
                    <td style="padding: 4px 8px; border: 1px solid {border_clr}; color: {theme['secondary_text']}; text-align: center;">{house_str}</td>
                    <td style="padding: 4px 8px; border: 1px solid {border_clr}; color: {clr_warning}; font-weight: bold;">{shamer}</td>
                    <td style="padding: 4px 8px; border: 1px solid {border_clr}; color: {theme['secondary_text']};">{source}</td>
                </tr>"""

            shamed_set = set(p for p, _, _, _ in shame_data["all_shamed"])
            sources = set(s for _, _, _, s in shame_data["all_shamed"])

            html = f"""
            <div style="padding: 8px;">
                <p style="color: {theme['primary']}; font-size: {scaled_area_px('panel_titles')}px; font-weight: bold; margin-bottom: 8px;">
                    SHAME AVASTHA (Lajjita)
                </p>
                <table style="border-collapse: collapse; width: 100%; background-color: {theme['secondary_dark']};">
                    <tr style="background-color: {theme['secondary']};">
                        <th style="padding: 4px 8px; border: 1px solid {border_clr}; color: {theme['secondary_text']};">Planet</th>
                        <th style="padding: 4px 8px; border: 1px solid {border_clr}; color: {theme['secondary_text']};">Sign</th>
                        <th style="padding: 4px 8px; border: 1px solid {border_clr}; color: {theme['secondary_text']};">House</th>
                        <th style="padding: 4px 8px; border: 1px solid {border_clr}; color: {theme['secondary_text']};">Shamer</th>
                        <th style="padding: 4px 8px; border: 1px solid {border_clr}; color: {theme['secondary_text']};">Source</th>
                    </tr>
                    {rows_html}
                </table>
                <p style="color: {subtle_clr}; font-size: {scaled_area_px('status')}px; margin-top: 8px;">
                    {len(shamed_set)} shamed planets | {len(sources)} sources | {len(shame_data['all_shamed'])} instances
                </p>
            """
            if shame_data.get("note"):
                html += f'<p style="color: {clr_warning}; font-size: {scaled_area_px("status")}px;">{shame_data["note"]}</p>'
            html += "</div>"

            gui.shame_display.setHtml(html)

        except Exception as e:
            import traceback
            print(f"Error updating Shame: {e}")
            traceback.print_exc()

    def refresh_theme(self):
        """Re-render the HTML with current theme colors (SPEC-THM-001 P-006).

        The HTML generated in _refresh() is theme-aware but only re-runs on
        chart/mode/varga change. On a theme switch the existing HTML keeps
        old colors. Trigger a re-render so border/text colors update.
        """
        self._refresh()
