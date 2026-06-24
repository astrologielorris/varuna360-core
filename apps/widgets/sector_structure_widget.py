from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QSizePolicy,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from ui.qt_theme import (
    get_theme_colors, is_light_theme, scaled_area_font,
)
from core.aditya_data import get_being_description


HORA_SECTIONS = [
    ("hora", "aditya", "Aditya (Sun side)"),
    ("hora", "naga", "Naga (Moon side)"),
]

TRIMSAMSA_SECTIONS = [
    ("trimsamsa", "gandharva", "Gandharva"),
    ("trimsamsa", "rakshasa", "Rakshasa"),
    ("trimsamsa", "rishi", "Rishi"),
    ("trimsamsa", "yaksha", "Yaksha"),
    ("trimsamsa", "apsara", "Apsara"),
]


def _theme_palette():
    """Return a dict of colors for the current theme (light or dark)."""
    theme = get_theme_colors()
    light = is_light_theme()

    if light:
        return {
            "bg": "#F5F5F5",
            "surface": "#EEEEEE",
            "text": "#1A1A1A",
            "text_secondary": "#444444",
            "text_tertiary": "#888888",
            "gold": "#B8860B",
            "gold_bg": "rgba(184, 134, 11, 0.08)",
            "border": "#CCCCCC",
            "section_bg": "#FFFFFF",
            "section_hover": "#F0F0F0",
        }
    else:
        return {
            "bg": theme["secondary_dark"],
            "surface": theme["secondary"],
            "text": theme["primary_text"],
            "text_secondary": theme["secondary_text"],
            "text_tertiary": theme["secondary_light"],
            "gold": "#DAA520",
            "gold_bg": "rgba(255, 215, 0, 0.06)",
            "border": theme["secondary_light"],
            "section_bg": theme["secondary"],
            "section_hover": theme["secondary_light"],
        }


class _CollapsibleSection(QFrame):

    def __init__(self, title, content_text, palette, is_active=False,
                 planet_annotation=None, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)

        p = palette

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(0)

        header = QHBoxLayout()
        header.setContentsMargins(4, 4, 4, 4)

        self._arrow = QLabel("▶")
        self._arrow.setFixedWidth(20)
        self._arrow.setStyleSheet(f"color: {p['text_tertiary']}; font-size: 12px;")
        header.addWidget(self._arrow)

        title_label = QLabel(title)
        font = scaled_area_font('table_headers')
        font.setBold(True)
        title_label.setFont(font)
        title_label.setStyleSheet(f"color: {p['text']};")
        header.addWidget(title_label, 1)

        header_widget = QWidget()
        header_widget.setLayout(header)
        header_widget.setCursor(Qt.CursorShape.PointingHandCursor)
        header_widget.setStyleSheet(
            f"background: {p['section_bg']}; border-radius: 4px;"
        )
        layout.addWidget(header_widget)

        self._content = QFrame()
        self._content.setFrameShape(QFrame.Shape.NoFrame)
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(24, 6, 8, 6)
        content_layout.setSpacing(6)

        if planet_annotation and is_active:
            ann_label = QLabel(planet_annotation)
            ann_label.setWordWrap(True)
            ann_font = scaled_area_font('info_text')
            ann_font.setItalic(True)
            ann_label.setFont(ann_font)
            ann_label.setStyleSheet(f"color: {p['gold']}; padding: 4px 0;")
            content_layout.addWidget(ann_label)

        if content_text:
            for key, label_text in [("theme", "Theme"), ("healthy", "Healthy Expression"),
                                     ("afflicted", "Afflicted Expression")]:
                value = content_text.get(key, "")
                if not value:
                    continue
                section_label = QLabel(f"<b>{label_text}:</b>")
                section_label.setFont(scaled_area_font('info_text'))
                section_label.setStyleSheet(f"color: {p['text_secondary']};")
                content_layout.addWidget(section_label)

                text_label = QLabel(value)
                text_label.setWordWrap(True)
                text_label.setFont(scaled_area_font('info_text'))
                text_label.setStyleSheet(f"color: {p['text']}; padding-left: 8px;")
                content_layout.addWidget(text_label)
        else:
            placeholder = QLabel("Description not available")
            placeholder.setFont(scaled_area_font('info_text'))
            placeholder.setStyleSheet(f"color: {p['text_tertiary']}; font-style: italic;")
            content_layout.addWidget(placeholder)

        self._content.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        layout.addWidget(self._content)

        if is_active:
            self.setObjectName(f"active_section_{id(self)}")
            self.setStyleSheet(
                f"#{self.objectName()} {{ border-left: 3px solid {p['gold']}; "
                f"background: {p['gold_bg']}; padding-left: 4px; }}"
            )
            self._set_expanded(True)
        else:
            self._set_expanded(False)

        header_widget.mousePressEvent = lambda e: self._toggle()

    def _toggle(self):
        self._set_expanded(not self._content.isVisible())

    def _set_expanded(self, expanded):
        self._content.setVisible(expanded)
        self._arrow.setText("▼" if expanded else "▶")
        self.updateGeometry()


class SectorStructureWidget(QWidget):

    def __init__(self, sign_name, active_hora_key=None, active_trimsamsa_key=None,
                 planet_name=None, degree_text=None, parent=None):
        super().__init__(parent)
        self._sign_name = sign_name

        p = _theme_palette()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        if planet_name:
            intro = QLabel(
                "Every being in this sign adds meaning to understanding the Aditya. "
                "A planet does not need to fall directly in a specific zone for that "
                "description to be relevant. However, when a planet does fall in a "
                "specific zone, that description becomes directly activated in the chart."
            )
            intro.setWordWrap(True)
            intro.setFont(scaled_area_font('info_text'))
            intro.setStyleSheet(f"color: {p['text_secondary']}; padding: 4px;")
            layout.addWidget(intro)

        hora_header = QLabel("Hora")
        hora_header.setFont(scaled_area_font('tables'))
        hora_header.setStyleSheet(
            f"color: {p['text']}; font-weight: bold; "
            f"border-bottom: 1px solid {p['border']}; padding: 4px 0 2px 0;"
        )
        layout.addWidget(hora_header)

        for ring, being_type, display_label in HORA_SECTIONS:
            desc = get_being_description(sign_name, ring, being_type)
            is_active = (active_hora_key == being_type)
            annotation = None
            if is_active and planet_name and degree_text:
                annotation = (
                    f"{planet_name} at {degree_text} {sign_name} falls directly "
                    f"in this Hora. This description is especially relevant in your chart."
                )
            name_suffix = ""
            if desc and desc.get("name"):
                name_suffix = f": {desc['name']}"
            section = _CollapsibleSection(
                f"{display_label}{name_suffix}", desc, palette=p,
                is_active=is_active, planet_annotation=annotation, parent=self,
            )
            layout.addWidget(section)

        trim_header = QLabel("Trimsamsa")
        trim_header.setFont(scaled_area_font('tables'))
        trim_header.setStyleSheet(
            f"color: {p['text']}; font-weight: bold; "
            f"border-bottom: 1px solid {p['border']}; padding: 8px 0 2px 0;"
        )
        layout.addWidget(trim_header)

        for ring, being_type, display_label in TRIMSAMSA_SECTIONS:
            desc = get_being_description(sign_name, ring, being_type)
            is_active = (active_trimsamsa_key == being_type)
            annotation = None
            if is_active and planet_name and degree_text:
                annotation = (
                    f"{planet_name} at {degree_text} {sign_name} falls directly "
                    f"in this Trimsamsa. This description is especially relevant in your chart."
                )
            name_suffix = ""
            if desc and desc.get("name"):
                name_suffix = f": {desc['name']}"
            section = _CollapsibleSection(
                f"{display_label}{name_suffix}", desc, palette=p,
                is_active=is_active, planet_annotation=annotation, parent=self,
            )
            layout.addWidget(section)

        layout.addStretch(1)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
