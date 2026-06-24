# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Interchange (Parivartana) yoga panel controller.

Displays all exchange yogas classified by Vedic type (Maha/Khala/Dainya),
rendered as HTML in the exchange_display QTextEdit widget.
Click on yoga name to see full explanation.
"""

from PySide6.QtWidgets import QMessageBox
from state import PanelControllerBase


_YOGA_DISPLAY = {
    "MAHA":          ("#2ecc71", "Maha Yoga"),
    "KHALA":         ("#f39c12", "Khala Yoga"),
    "DAINYA_6":      ("#e67e22", "Dainya Yoga (6th)"),
    "DAINYA_8":      ("#e74c3c", "Dainya Yoga (8th)"),
    "DAINYA_12":     ("#c0392b", "Dainya Yoga (12th)"),
    "DAINYA_DOUBLE": ("#8b0000", "Dainya Yoga (double)"),
}

_YOGA_ORDER = ["MAHA", "KHALA", "DAINYA_6", "DAINYA_8", "DAINYA_12", "DAINYA_DOUBLE"]


class InterchangeController(PanelControllerBase):
    """Subscribes to active_chart + aditya_mode events.
    Lazy: only refreshes when the Exchange tab is visible.
    """

    def __init__(self, gui):
        super().__init__(gui=gui, lazy=True)
        self._last_result = None

    def _on_chart_changed(self):
        self._refresh()

    def _on_mode_changed(self):
        self._refresh()

    def show_yoga_detail(self, yoga_key):
        """Show full yoga description in a dialog."""
        from AI_tools.AI_main_function.constants import PARIVARTANA_YOGA_FULL
        color, label = _YOGA_DISPLAY.get(yoga_key, ("#999", yoga_key))
        full_text = PARIVARTANA_YOGA_FULL.get(yoga_key, "")
        if not full_text:
            return

        msg = QMessageBox(self._gui)
        msg.setWindowTitle(f"Parivartana: {label}")
        msg.setText(full_text)
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setStyleSheet("QMessageBox { min-width: 550px; }")
        msg.exec()

    def _refresh(self):
        gui = self._gui
        if not hasattr(gui, "exchange_display"):
            return

        chart = getattr(self._state, 'active_chart', None) if self._state else None
        if not chart:
            gui.exchange_display.setHtml(
                "<p style='color: gray; text-align: center;'>No chart loaded.</p>"
            )
            self._last_result = None
            return

        try:
            from AI_tools.AI_main_function.interchange import get_all_interchanges
            from AI_tools.AI_main_function.constants import PARIVARTANA_YOGA_SHORT
            from ui.qt_theme import get_theme_colors

            theme = get_theme_colors()
            text_color = theme.get("primary_text", "#cccccc")

            result = get_all_interchanges(chart)
            self._last_result = result
            interchanges = result["interchanges"]

            if not interchanges:
                gui.exchange_display.setHtml(
                    f"<div style='padding: 12px;'>"
                    f"<p style='color: #2ecc71; font-weight: bold; text-align: center;'>"
                    f"No Parivartana yogas detected</p>"
                    f"<p style='color: {text_color}; text-align: center; font-size: 11px;'>"
                    f"This chart has no planetary mutual exchange.</p>"
                    f"</div>"
                )
                return

            html = f"<div style='padding: 4px; color: {text_color};'>"

            grouped = {}
            for rec in interchanges:
                cls = rec[6]
                grouped.setdefault(cls, []).append(rec)

            for yoga_key in _YOGA_ORDER:
                if yoga_key not in grouped:
                    continue
                color, label = _YOGA_DISPLAY.get(yoga_key, ("#999", yoga_key))
                short_desc = PARIVARTANA_YOGA_SHORT.get(yoga_key, "")

                html += (
                    f"<p style='margin: 8px 0 1px 0; font-weight: bold; "
                    f"color: {color}; font-size: 12px; cursor: pointer;'>"
                    f"<a href='yoga:{yoga_key}' style='color: {color}; "
                    f"text-decoration: none;'>{label}</a></p>"
                )

                if short_desc:
                    html += (
                        f"<p style='margin: 0 0 4px 0; color: {text_color}; "
                        f"font-size: 10px; font-style: italic;'>{short_desc}</p>"
                    )

                html += (
                    f"<table cellpadding='3' cellspacing='0' "
                    f"style='width: 100%; border-collapse: collapse; font-size: 11px;'>"
                )

                for rec in grouped[yoga_key]:
                    planet_a, sign_a, house_a, planet_b, sign_b, house_b, _ = rec
                    html += (
                        f"<tr>"
                        f"<td style='color: {text_color};'>{planet_a}</td>"
                        f"<td style='color: {color};'>{sign_a}</td>"
                        f"<td style='text-align: center; color: {text_color};'>H{house_a}</td>"
                        f"<td style='text-align: center; color: {text_color};'>&#8596;</td>"
                        f"<td style='color: {text_color};'>{planet_b}</td>"
                        f"<td style='color: {color};'>{sign_b}</td>"
                        f"<td style='text-align: center; color: {text_color};'>H{house_b}</td>"
                        f"</tr>"
                    )

                html += "</table>"

            html += (
                f"<p style='margin: 8px 0 0 0; color: {text_color}; "
                f"font-size: 9px; text-align: center;'>"
                f"Click yoga name for full explanation</p>"
            )
            html += "</div>"
            gui.exchange_display.setHtml(html)

        except Exception as e:
            import html as _html
            gui.exchange_display.setHtml(
                f"<p style='color: red;'>Error: {_html.escape(str(e))}</p>"
            )
            self._last_result = None

    def handle_link_click(self, url):
        """Handle clicks on yoga name links."""
        url_str = url.toString() if hasattr(url, 'toString') else str(url)
        if url_str.startswith("yoga:"):
            yoga_key = url_str[5:]
            self.show_yoga_detail(yoga_key)
