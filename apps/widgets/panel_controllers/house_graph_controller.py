# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
House Graph panel controller — retinue house connection density bar chart.
"""

import json
from pathlib import Path

from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtCore import Qt, QRectF, QRect, QSize
from PySide6.QtGui import (
    QPainter, QColor, QFont, QLinearGradient, QPen, QBrush,
    QPixmap, QImage,
)

from state import PanelControllerBase
from state.user_data import get_settings_path as _get_settings_path
from ui.qt_theme import (
    is_light_theme, scaled_area_size, scaled_area_px, desat_image, sat_key, desat_hex,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]

_PLANET_ICON_NAMES = {
    "Sun": "sun", "Moon": "moon", "Mars": "Mars", "Mercury": "Mercury",
    "Jupiter": "Jupiter", "Venus": "Venus", "Saturn": "Saturn",
    "Rahu": "rahu", "Ketu": "ketu",
}

_PLANET_COLORS = {
    "Ascendant": "#FF8C00",
    "Sun": "#FFB300",
    "Moon": "#5CC8C8",
    "Mars": "#FF6B00",
    "Mercury": "#B89A5A",
    "Jupiter": "#7B3FA0",
    "Venus": "#4DD0E1",
    "Saturn": "#3D3D3D",
    "Rahu": "#546E7A",
    "Ketu": "#37474F",
}

_BAR_COLORS = [
    "#E57373", "#F06292", "#BA68C8", "#9575CD", "#7986CB", "#64B5F6",
    "#4FC3F7", "#4DD0E1", "#4DB6AC", "#81C784", "#AED581", "#DCE775",
]


class _HouseBarWidget(QWidget):
    """Custom-painted horizontal bar chart. Reads gui.state directly on every paint."""

    def __init__(self, gui_ref=None, parent=None):
        super().__init__(parent)
        self._gui_ref = gui_ref
        self._icon_cache: dict[str, QPixmap | None] = {}
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def sizeHint(self):
        result = self._get_tally()
        if result is None:
            return QSize(self.width(), 120)
        active, absent = result
        total_rows = len(active) + (1 if absent else 0) + len(absent)
        row_h = max(16, scaled_area_px('tables') + 4)
        chrome_h = 4 + 20 + 4 + 18  # top_margin + subtitle + gap + compact_summary
        ideal_h = (total_rows * row_h) + chrome_h
        return QSize(self.width(), max(120, ideal_h))

    def _load_planet_icon(self, planet_name: str, size: int = 20) -> QPixmap | None:
        """Load planet WebP icon scaled to size, with a colored shadow/glow."""
        cache_key = f"{planet_name}_{size}{sat_key()}"
        if cache_key in self._icon_cache:
            return self._icon_cache[cache_key]

        base = _PLANET_ICON_NAMES.get(planet_name)
        if not base:
            self._icon_cache[cache_key] = None
            return None

        variation = self._get_icon_variation(planet_name)
        if variation > 1:
            path = _PROJECT_ROOT / f"img/planets/{base}{variation}.webp"
            if not path.exists():
                path = _PROJECT_ROOT / f"img/planets/{base}.webp"
        else:
            path = _PROJECT_ROOT / f"img/planets/{base}.webp"

        if not path.exists():
            self._icon_cache[cache_key] = None
            return None

        img = QImage(str(path))
        if img.isNull():
            self._icon_cache[cache_key] = None
            return None

        img = img.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
        img = desat_image(img)
        icon_px = QPixmap.fromImage(img)

        result = QPixmap(icon_px.size())
        result.fill(Qt.GlobalColor.transparent)
        p = QPainter(result)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        glow = QColor("#FFFFFF")
        glow.setAlpha(60)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(1, 1, icon_px.width() - 2, icon_px.height() - 2)

        p.drawPixmap(0, 0, icon_px)
        p.end()

        self._icon_cache[cache_key] = result
        return result

    def _get_icon_variation(self, planet_name: str) -> int:
        try:
            settings_path = _get_settings_path()
            if settings_path.exists():
                with open(settings_path, 'r') as f:
                    return json.load(f).get('planet_icons', {}).get(planet_name, 1)
        except Exception:
            pass
        return 1

    def _get_tally(self):
        """Read chart state and compute tally. Returns (active, absent) or None."""
        gui = self._gui_ref
        if not gui:
            return None
        state = getattr(gui, 'state', None)
        if not state:
            return None
        chart = getattr(state, 'active_chart', None)
        if not chart:
            return None

        try:
            from AI_tools.AI_main_function.retinue import get_chart_retinue, _build_house_tally

            aditya_mode = state.aditya_mode
            ayanamsa_offset = 0.0
            if aditya_mode == "sidereal":
                ayanamsa_offset = getattr(gui, "chart_ayanamsa_offset", 0.0)
            tropical_mode = (aditya_mode == "tropical_classic")

            chart_data = get_chart_retinue(
                chart, ayanamsa_offset=ayanamsa_offset, tropical_mode=tropical_mode,
            )
            tally = _build_house_tally(chart_data["planets"])

            active = []
            absent = []
            for h in range(1, 13):
                entries = tally[h]
                if entries:
                    active.append((h, len(entries),
                                   [(e["planet"], e["ring"]) for e in entries]))
                else:
                    absent.append(h)

            active.sort(key=lambda x: (-x[1], x[0]))
            return active, absent
        except Exception:
            return None

    def paintEvent(self, event):
        result = self._get_tally()
        if result is None:
            return

        active, absent = result
        if not active and not absent:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        max_count = active[0][1] if active else 0

        total_rows = len(active) + (1 if absent else 0) + len(absent)
        subtitle_h = 20
        summary_h = 18
        chrome_h = 4 + subtitle_h + 4 + summary_h  # top_margin + subtitle + gap + compact_summary
        font_row_h = max(16, scaled_area_px('tables') + 4)
        space_row_h = max(12, (h - chrome_h) // max(total_rows, 1))
        row_h = min(font_row_h, space_row_h)

        light = is_light_theme()
        text_color = QColor("#333333") if light else QColor("#E0E0E0")
        label_w = 36
        count_w = 22
        bar_left = label_w + 4
        bar_max_w = int(w * 0.42)
        planet_left = bar_left + bar_max_w + count_w + 6

        font = QFont()
        font.setPixelSize(max(10, scaled_area_px('tables')))

        y = 4

        # --- Subtitle ---
        subtitle_font = QFont()
        subtitle_font.setPointSize(scaled_area_size('table_headers'))
        subtitle_font.setBold(True)
        painter.setFont(subtitle_font)
        painter.setPen(QColor("#666666") if light else QColor("#999999"))
        painter.drawText(QRectF(4, y, w - 8, subtitle_h),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         "House activation from retinue connections")
        y += subtitle_h

        # --- Active houses ---
        for idx, (house_num, count, planet_entries) in enumerate(active):
            bar_color = QColor(desat_hex(_BAR_COLORS[idx % len(_BAR_COLORS)]))  # SPEC-SAT-001

            # House label
            painter.setFont(font)
            painter.setPen(text_color)
            painter.drawText(QRectF(2, y, label_w - 2, row_h),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             f"H{house_num}")

            # Bar
            if max_count > 0 and count > 0:
                bar_w = max(6, int((count / max_count) * bar_max_w))
                bar_rect = QRectF(bar_left, y + 2, bar_w, row_h - 4)
                grad = QLinearGradient(bar_rect.topLeft(), bar_rect.topRight())
                grad.setColorAt(0.0, bar_color.darker(130))
                grad.setColorAt(0.4, bar_color)
                grad.setColorAt(1.0, bar_color.lighter(140))
                painter.setBrush(QBrush(grad))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRoundedRect(bar_rect, 3, 3)

            # Count
            bold_font = QFont()
            bold_font.setPixelSize(max(10, min(scaled_area_px('tables'), row_h - 5)))
            bold_font.setBold(True)
            painter.setFont(bold_font)
            painter.setPen(text_color)
            painter.drawText(QRectF(bar_left + bar_max_w + 2, y, count_w, row_h),
                             Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter,
                             str(count))

            # Planet WebP icons with glow (fallback to colored text for Ascendant)
            icon_size = max(16, row_h - 2)
            gx = planet_left
            for planet_name, _ring in planet_entries:
                px = self._load_planet_icon(planet_name, icon_size)
                if px and not px.isNull():
                    icon_y = int(y + (row_h - px.height()) / 2)
                    painter.drawPixmap(int(gx), icon_y, px)
                    gx += px.width() + 3
                else:
                    fallback_font = QFont()
                    fallback_font.setPixelSize(max(10, min(scaled_area_px('tables'), row_h - 4)))
                    fallback_font.setBold(True)
                    painter.setFont(fallback_font)
                    painter.setPen(QColor(_PLANET_COLORS.get(planet_name, "#AAAAAA")))
                    label = planet_name[:3]
                    tw = painter.fontMetrics().horizontalAdvance(label) + 2
                    painter.drawText(QRectF(gx, y, tw + 2, row_h),
                                     Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                                     label)
                    gx += tw

            y += row_h

        # --- Absent section ---
        if absent:
            painter.setPen(QPen(QColor("#CCCCCC") if light else QColor("#555555"), 1, Qt.PenStyle.DashLine))
            y += 3
            painter.drawLine(8, int(y), int(w - 8), int(y))
            y += 4

            absent_font = QFont()
            absent_font.setPixelSize(max(10, min(scaled_area_px('tables'), row_h - 4)))
            absent_font.setBold(True)
            painter.setFont(absent_font)
            painter.setPen(QColor("#EF5350"))
            painter.drawText(QRectF(0, y, w, row_h),
                             Qt.AlignmentFlag.AlignCenter, "ABSENT")
            y += row_h

            painter.setFont(font)
            for house_num in absent:
                painter.setPen(QPen(QColor("#EF5350"), 1.5, Qt.PenStyle.DashLine))
                painter.setBrush(QBrush(QColor("#FFEBEE") if light else QColor("#3D1111")))
                painter.drawRoundedRect(
                    QRectF(bar_left, y + 2, bar_max_w * 0.25, row_h - 4), 3, 3)

                painter.setPen(text_color)
                painter.drawText(QRectF(2, y, label_w - 2, row_h),
                                 Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                                 f"H{house_num}")

                zero_font = QFont()
                zero_font.setPixelSize(max(10, min(scaled_area_px('tables'), row_h - 5)))
                zero_font.setBold(True)
                painter.setFont(zero_font)
                painter.setPen(QColor("#EF5350"))
                painter.drawText(QRectF(bar_left + bar_max_w + 2, y, count_w, row_h),
                                 Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter,
                                 "0")
                painter.setFont(font)
                y += row_h

        # --- Compact summary footer (1 line) ---
        y = h - summary_h + 2
        sf = QFont()
        sf.setPixelSize(max(9, scaled_area_px('tables') - 1))
        painter.setFont(sf)

        dominant = [hh for hh, c, _ in active if active and c == active[0][1]]
        sparse_houses = [hh for hh, c, _ in active if c == 1]

        parts = []
        dom_str = " ".join(
            f"H{hh}({next(c for h2, c, _ in active if h2 == hh)})"
            for hh in dominant)
        parts.append(("Dom: " + dom_str, QColor("#4CAF50")))

        abs_str = " ".join(f"H{hh}" for hh in absent) if absent else "None"
        parts.append(("Abs: " + abs_str, QColor("#EF5350")))

        if sparse_houses and set(sparse_houses) != set(dominant):
            spr_str = " ".join(f"H{hh}" for hh in sparse_houses)
            parts.append(("Spr: " + spr_str, QColor("#FFA726")))

        painter.setClipRect(QRectF(0, y, w, summary_h))
        x = 8
        fm = painter.fontMetrics()
        for i, (text, color) in enumerate(parts):
            if x > w - 16:
                break
            if i > 0:
                painter.setPen(text_color)
                painter.drawText(
                    QRectF(x, y, 12, summary_h - 2),
                    Qt.AlignmentFlag.AlignCenter, "·")
                x += 12
            painter.setPen(color)
            tw = fm.horizontalAdvance(text)
            painter.drawText(
                QRectF(x, y, tw + 4, summary_h - 2),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                text)
            x += tw + 4
        painter.setClipping(False)

        painter.end()


class HouseGraphController(PanelControllerBase):
    """Marks the graph widget for repaint when chart/mode changes."""

    def __init__(self, gui):
        super().__init__(gui=gui, lazy=False)

    def _on_chart_changed(self):
        bar = getattr(self._gui, "house_graph_bars", None)
        if bar:
            bar._icon_cache.clear()
            bar.update()

    def _on_mode_changed(self):
        self._on_chart_changed()

    def _on_theme_changed(self):
        bar = getattr(self._gui, "house_graph_bars", None)
        if bar:
            bar.update()

    def clear_icon_cache(self):
        """Drop cached planet pixmaps on the bar widget so they re-render at
        the current UI saturation (SPEC-SAT-001 WI-4). Hasattr-guarded."""
        bar = getattr(self._gui, "house_graph_bars", None)
        if bar is not None and hasattr(bar, "_icon_cache"):
            bar._icon_cache.clear()
