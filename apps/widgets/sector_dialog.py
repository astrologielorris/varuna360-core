from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QScrollArea, QFrame,
    QPushButton, QHBoxLayout, QSizePolicy,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from ui.qt_theme import (
    get_theme_colors, is_light_theme, scaled_area_font,
    get_primary_button_style,
)
from core.aditya_data import ADITYA_NAMES
from apps.widgets.sector_structure_widget import SectorStructureWidget


ADITYA_TO_WESTERN = dict(zip(
    ADITYA_NAMES,
    ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
     "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"],
))


class SectorInfoDialog(QDialog):

    def __init__(self, sign_name, focus_ring=None, focus_type=None,
                 avastha_summary=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{sign_name} Structure")
        self.setMinimumSize(420, 500)
        self.resize(480, 620)

        theme = get_theme_colors()
        light = is_light_theme()

        bg = theme["secondary_dark"]
        text_color = theme["secondary_text"]
        gold = "#DAA520"
        border_color = theme["secondary_light"]

        if light:
            bg = "#F5F5F5"
            text_color = "#1A1A1A"
            border_color = "#CCCCCC"
            gold = "#B8860B"

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {bg};
            }}
            QLabel {{
                color: {text_color};
            }}
            QScrollArea {{
                background-color: {bg};
                border: none;
            }}
            QScrollArea > QWidget > QWidget {{
                background-color: {bg};
            }}
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(8)

        western = ADITYA_TO_WESTERN.get(sign_name, "")
        header = QLabel(f"{sign_name}")
        header_font = scaled_area_font('panel_titles')
        header_font.setBold(True)
        header.setFont(header_font)
        header.setStyleSheet(f"color: {gold};")
        main_layout.addWidget(header)

        if western:
            sub = QLabel(f"({western})")
            sub.setFont(scaled_area_font('tables'))
            sub.setStyleSheet(f"color: {theme['secondary_text'] if not light else '#666666'};")
            main_layout.addWidget(sub)

        if avastha_summary:
            main_layout.addWidget(
                self._build_expression_bar(avastha_summary, light, text_color))

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet(f"color: {border_color};")
        separator.setFixedHeight(2)
        main_layout.addWidget(separator)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        active_hora = focus_type if focus_ring == "hora" else None
        active_trim = focus_type if focus_ring == "trimsamsa" else None

        widget = SectorStructureWidget(
            sign_name,
            active_hora_key=active_hora,
            active_trimsamsa_key=active_trim,
            parent=None,
        )
        scroll.setWidget(widget)
        main_layout.addWidget(scroll, 1)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(80)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(get_primary_button_style())
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        main_layout.addLayout(btn_layout)

    @staticmethod
    def _build_expression_bar(summary, light, text_color):
        """Render uplifted/afflicted expression totals as a labeled bar."""
        uplifted = summary.get("uplifted", 0)
        afflicted = summary.get("afflicted", 0)
        planet = summary.get("planet", "")
        target = summary.get("target", "")

        green = "#2E7D32" if light else "#A5D6A7"
        red = "#C62828" if light else "#EF9A9A"
        muted = "#666666" if light else "#999999"

        parts = []
        if planet != target:
            parts.append(
                f"<span style='color:{muted}; font-size:11px;'>"
                f"(via lord {target})</span>")
        parts.append(
            f"<span style='color:{green}; font-weight:bold;'>"
            f"Uplifted: +{uplifted:.0f}</span>")
        parts.append(
            f"<span style='color:{red}; font-weight:bold;'>"
            f"Afflicted: {afflicted:.0f}</span>")

        bar = QLabel(f"{planet} &nbsp; " + " &nbsp;&middot;&nbsp; ".join(parts))
        bar.setFont(scaled_area_font('tables'))
        bar.setStyleSheet(f"color: {text_color}; padding: 4px 0px;")
        bar.setTextFormat(Qt.TextFormat.RichText)
        return bar
