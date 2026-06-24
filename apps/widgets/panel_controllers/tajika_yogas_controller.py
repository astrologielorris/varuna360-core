# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Tajika yogas panel controller — Phase 4 W2.11 (final controller).

Migration source: managers/panel_update_manager.py:1182-1308.
Rich HTML output to tajika_placeholder (QTextEdit), grouped by category
(SUCCESS / FAILURE / DISRUPTION / VOID / TRANSFER / SPECIAL).

NOT sidereal-aware. Subscribes to active_chart only.
"""

from state import PanelControllerBase


class TajikaYogasController(PanelControllerBase):
    """Subscribes to active_chart events. Eager.

    Final controller in the W2 migration — completes the dissolution of
    panel_update_manager into 12 self-updating PanelControllers.
    """

    def __init__(self, gui):
        super().__init__(gui=gui, lazy=False)

    def _on_chart_changed(self):
        self._refresh()

    def _refresh(self):
        gui = self._gui
        if not hasattr(gui, "tajika_placeholder"):
            return

        chart = getattr(self._state, 'active_chart', None) if self._state else None
        if not chart:
            gui.tajika_placeholder.setHtml("")
            return
        base_planets = chart

        try:
            from AI_tools.AI_main_function.tajika_yogas import detect_all_tajika_yogas
            from AI_tools.AI_main_function.tajika import calculate_all_tajika_aspects
            from ui.qt_theme import (
                get_theme_colors, STATUS, scaled_px, scaled_area_px,
            )

            theme = get_theme_colors()
            # SPEC-THM-001 G19: live theme colors instead of frozen BORDER / TEXT_TERTIARY.
            border_clr = theme["secondary_light"]
            subtle_clr = theme["secondary_text"]

            tajika_data = calculate_all_tajika_aspects(base_planets)
            yoga_data = detect_all_tajika_yogas(base_planets, tajika_data)

            yogas_by_cat = yoga_data["yogas_by_category"]
            summary = yoga_data["summary"]

            cat_colors = {
                "SUCCESS":    ("SUCCESS",    STATUS["success"]),
                "FAILURE":    ("FAILURE",    STATUS["error"]),
                "DISRUPTION": ("DISRUPTION", STATUS["warning"]),
                "VOID":       ("VOID",       subtle_clr),
                "TRANSFER":   ("TRANSFER",   theme["primary"]),
                "SPECIAL":    ("SPECIAL",    theme.get("primary_light", theme["primary"])),
            }

            if summary["total_count"] == 0:
                html = f"""
                <div style="color: {subtle_clr}; font-size: {scaled_area_px('info_text')}px; padding: 20px; text-align: center;">
                    <p style="font-size: {scaled_area_px('panel_titles')}px; font-weight: bold;">No Tajika Yogas Detected</p>
                    <p>This chart has no active Tajika yoga configurations.</p>
                </div>"""
                gui.tajika_placeholder.setHtml(html)
                return

            html = '<div style="padding: 8px;">'
            html += (
                f'<p style="color: {theme["primary"]}; font-size: {scaled_area_px("panel_titles")}px; '
                f'font-weight: bold; margin-bottom: 10px;">'
                f'TAJIKA YOGAS ({summary["total_count"]} detected)</p>'
            )

            category_order = ["SUCCESS", "FAILURE", "DISRUPTION", "VOID", "TRANSFER", "SPECIAL"]

            for cat in category_order:
                yogas = yogas_by_cat.get(cat, [])
                if not yogas:
                    continue

                label, color = cat_colors[cat]

                html += (
                    f'<div style="background-color: {theme["secondary"]}; '
                    f'padding: 4px 8px; margin-top: 8px; margin-bottom: 4px; '
                    f'border-left: 3px solid {color};">'
                    f'<span style="color: {color}; font-weight: bold; font-size: {scaled_area_px("table_headers")}px;">'
                    f'{label} ({len(yogas)})</span></div>'
                )

                for yoga in yogas:
                    name = yoga["yoga_name"]
                    subtype = yoga.get("subtype", "")
                    planets_short = yoga["planets_short"]
                    description = yoga["description"]
                    effect = yoga["effect"]

                    is_out_of_orb = subtype == "Bhavishyata"
                    yoga_color = STATUS["warning"] if is_out_of_orb else color

                    name_display = f'<b style="color: {yoga_color};">{name}</b>'
                    if subtype:
                        sub_color = STATUS["warning"] if is_out_of_orb else subtle_clr
                        orb_excess = yoga.get("orb_excess")
                        excess_str = f" — out of orb by {orb_excess}°" if orb_excess is not None else ""
                        name_display += (
                            f' <span style="color: {sub_color};">'
                            f'({subtype}{excess_str})</span>'
                        )

                    html += (
                        f'<div style="padding: 3px 8px 3px 14px; '
                        f'border-bottom: 1px solid {border_clr};">'
                        f'{name_display}'
                        f' &nbsp;<span style="color: {theme["secondary_text"]}; '
                        f'font-size: {scaled_area_px("tables")}px;">[{planets_short}]</span><br/>'
                        f'<span style="color: {theme["secondary_text"]}; '
                        f'font-size: {scaled_area_px("tables")}px;">{description}</span><br/>'
                        f'<i style="color: {subtle_clr}; '
                        f'font-size: {scaled_area_px("tables")}px;">{effect}</i>'
                        f'</div>'
                    )

            parts = []
            for cat in category_order:
                count = summary.get(f"{cat.lower()}_count", 0)
                if count > 0:
                    _, color = cat_colors[cat]
                    parts.append(f'<span style="color: {color};">{cat}: {count}</span>')

            html += (
                f'<p style="color: {subtle_clr}; font-size: {scaled_area_px("status")}px; '
                f'margin-top: 10px;">'
                + " &nbsp;|&nbsp; ".join(parts)
                + '</p>'
            )
            html += '</div>'

            gui.tajika_placeholder.setHtml(html)

        except Exception as e:
            import traceback
            print(f"Error updating Tajika Yogas: {e}")
            traceback.print_exc()

    def refresh_theme(self):
        """Re-render the HTML with current theme colors (SPEC-THM-001 P-006)."""
        self._refresh()
