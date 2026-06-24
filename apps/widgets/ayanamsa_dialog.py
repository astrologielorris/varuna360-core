#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Ayanamsa Selection Dialog

Popup dialog for choosing ayanamsa and chart zodiac type for dasha panels.

Each dasha panel (Vedanga left, Vimshottari right) can independently
select its ayanamsa system. The dialog presents ~50 ayanamsa options
organized by category.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QRadioButton, QButtonGroup, QPushButton, QLabel, QScrollArea,
    QWidget, QFrame, QSizePolicy
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from ui.qt_theme import (
    get_theme_colors, is_light_theme, scaled_px, scaled_area_px,
    get_group_box_style, get_scroll_style,
    get_primary_button_style, get_secondary_button_style,
)

from core.ayanamsa_data import (
    AYANAMSA_OPTIONS, CATEGORY_ORDER,
    get_ayanamsa_name, get_ayanamsa_tooltip,
)


# ============================================================================
# (Data constants and helpers moved to core/ayanamsa_data.py)
# ============================================================================

# DIALOG CLASS
# ============================================================================

class AyanamsaDialog(QDialog):
    """
    Dialog for selecting ayanamsa and chart zodiac type (tropical/sidereal).

    Usage:
        dialog = AyanamsaDialog(parent, current_ayanamsa=98,
                                current_chart_zodiac="tropical")
        if dialog.exec():
            ayanamsa_id, chart_zodiac = dialog.get_selection()
    """

    def __init__(self, parent=None, current_ayanamsa=98,
                 current_chart_zodiac="tropical"):
        super().__init__(parent)
        self.setWindowTitle("Select Ayanamsa")
        self.setMinimumWidth(720)
        self.setMinimumHeight(600)
        self.setModal(True)

        theme = get_theme_colors()
        _light = is_light_theme()

        # Adaptive colors resolved at dialog-open time (not module-import time)
        text_color   = theme["primary_text"] if _light else theme.get("primary_text", "#FFFFFF")
        text_muted   = theme["secondary_text"]
        radio_style  = self._radio_style(theme, _light)
        gbox_style   = get_group_box_style()

        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(14, 14, 14, 14)

        # ── Chart Zodiac Type (Tropical / Sidereal) ──────────────────────────
        zodiac_box = QGroupBox("Chart Zodiac")
        zodiac_box.setStyleSheet(gbox_style)
        zodiac_layout = QHBoxLayout(zodiac_box)
        zodiac_layout.setSpacing(24)
        zodiac_layout.setContentsMargins(12, 16, 12, 10)

        self.chart_zodiac_group = QButtonGroup(self)
        for idx, (value, label, tip) in enumerate([
            ("tropical", "Tropical Chart",
             "Chart displays tropical positions (Western standard). "
             "No ayanamsa correction applied to the chart wheel."),
            ("sidereal", "Sidereal Chart",
             "Chart displays sidereal positions. Subtracts the selected ayanamsa "
             "from all tropical longitudes. Standard Jyotish approach (~23° shift)."),
        ]):
            rb = QRadioButton(label)
            rb.setToolTip(tip)
            rb.setStyleSheet(radio_style)
            self.chart_zodiac_group.addButton(rb, idx)
            if value == current_chart_zodiac:
                rb.setChecked(True)
            zodiac_layout.addWidget(rb)
        zodiac_layout.addStretch()
        main_layout.addWidget(zodiac_box)

        # ── Scrollable area for ayanamsa options ─────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(get_scroll_style())

        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(8)
        scroll_layout.setContentsMargins(4, 4, 8, 4)

        # Radio button group for ayanamsa (mutually exclusive)
        self.ayanamsa_group = QButtonGroup(self)
        self._ayanamsa_buttons = {}  # id -> QRadioButton

        # Group options by category
        categories = {}
        for aid, name, cat, tip in AYANAMSA_OPTIONS:
            categories.setdefault(cat, []).append((aid, name, tip))

        # Build category group boxes
        for cat_name in CATEGORY_ORDER:
            if cat_name not in categories:
                continue
            entries = categories[cat_name]

            group_box = QGroupBox(cat_name)
            group_box.setStyleSheet(gbox_style)

            grid = QGridLayout(group_box)
            grid.setSpacing(4)
            grid.setContentsMargins(12, 16, 12, 10)
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 1)

            for i, (aid, name, tip) in enumerate(entries):
                rb = QRadioButton(name)
                rb.setToolTip(tip)
                rb.setStyleSheet(radio_style)
                self.ayanamsa_group.addButton(rb, aid)
                self._ayanamsa_buttons[aid] = rb
                if aid == current_ayanamsa:
                    rb.setChecked(True)
                row = i // 2
                col = i % 2
                grid.addWidget(rb, row, col)

            scroll_layout.addWidget(group_box)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        main_layout.addWidget(scroll, stretch=1)

        # ── OK / Cancel buttons ───────────────────────────────────────────────
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        ok_btn = QPushButton("OK")
        ok_btn.setFixedSize(scaled_px(88), scaled_px(34))
        ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ok_btn.setStyleSheet(get_primary_button_style())
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedSize(scaled_px(88), scaled_px(34))
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setStyleSheet(get_secondary_button_style())
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        main_layout.addLayout(btn_layout)

    # ─────────────────────────────────────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _radio_style(theme: dict, is_light: bool) -> str:
        """Build theme-aware radio button stylesheet."""
        text  = theme["primary_text"] if is_light else theme.get("primary_text", "#FFFFFF")
        accent = theme["primary"]
        hover  = theme["primary_light"]
        return f"""
            QRadioButton {{
                color: {text};
                font-size: {scaled_area_px('info_text')}px;
                spacing: 6px;
                padding: 2px 4px;
            }}
            QRadioButton::indicator {{
                width: {scaled_px(13)}px;
                height: {scaled_px(13)}px;
                border-radius: {scaled_px(7)}px;
                border: 2px solid {accent};
                background-color: transparent;
            }}
            QRadioButton::indicator:checked {{
                border: 3px solid {accent};
                background-color: {accent};
            }}
            QRadioButton:hover {{
                color: {hover};
            }}
            QRadioButton:hover::indicator {{
                border-color: {hover};
            }}
        """

    # ─────────────────────────────────────────────────────────────────────────
    # RESULT
    # ─────────────────────────────────────────────────────────────────────────

    def get_selection(self):
        """
        Return the user's selection as a tuple.

        Returns:
            (ayanamsa_id, chart_zodiac)
            - ayanamsa_id: int (0-46, 98, 100, 999)
            - chart_zodiac: str ("tropical" or "sidereal")
        """
        ayanamsa_id = self.ayanamsa_group.checkedId()

        chart_zodiac_idx = self.chart_zodiac_group.checkedId()
        chart_zodiac = "sidereal" if chart_zodiac_idx == 1 else "tropical"

        return ayanamsa_id, chart_zodiac
