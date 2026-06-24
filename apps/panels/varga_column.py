#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Varga Selection Column
Slim column with divisional chart selection buttons (D-1 to D-60)

Extracted from core_gui_qt.py for modularity
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QScrollArea, QButtonGroup, QSizePolicy
)
from PySide6.QtCore import Qt

# Import centralized theme - use theme colors for checked state
from ui.qt_theme import TEXT, get_theme_colors, scaled_px, scaled_area_px


def create_varga_column(gui, is_varga_implemented, get_varga_name):
    """
    Create slim Varga selection column (no header, just number buttons).

    Args:
        gui: The parent ChartGUI instance (for callbacks and button storage)
        is_varga_implemented: Function to check if a varga is implemented
        get_varga_name: Function to get varga name from number

    Returns:
        QScrollArea: The scrollable column widget
    """
    theme = get_theme_colors()

    # Scroll area with fixed width - original size
    scroll = QScrollArea()
    scroll.setFixedWidth(45)
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    # Ensure scroll area doesn't get hidden/overlapped
    scroll.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

    # Minimal styling - inherit from qt-material theme
    scroll.setStyleSheet("""
        QScrollArea {
            border: none;
        }
        QScrollBar:vertical {
            width: 6px;
        }
        QScrollBar::handle:vertical {
            border-radius: 3px;
        }
    """)

    # Container widget
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setSpacing(2)
    layout.setContentsMargins(2, 5, 2, 5)

    # Button group for exclusive selection
    gui.varga_button_group = QButtonGroup(gui)
    gui.varga_button_group.setExclusive(True)

    # Common Vargas to show as buttons (including special variants)
    # 1010 = D-10R (Dasamsa Reverse), 2424 = D-24R (Siddhamsa Reverse)
    varga_numbers = [1, 2, 3, 4, 7, 9, 10, 1010, 12, 16, 20, 24, 2424, 27, 30, 40, 45, 60]

    gui.varga_buttons = {}

    # Button style - ALL colors from get_theme_colors() (adapts to selected theme)
    # NO hardcoded colors - everything uses theme["..."] variables
    button_style = f"""
        QPushButton {{
            background-color: {theme["secondary_dark"]};
            color: {theme["secondary_text"]};
            border: 1px solid {theme["secondary_light"]};
            border-radius: 3px;
            font-size: {scaled_area_px('sidebar')}px;
            font-weight: bold;
            min-height: {scaled_px(22)}px;
            max-height: {scaled_px(22)}px;
            max-width: {scaled_px(35)}px;
            padding: 0px;
            outline: none;
        }}
        QPushButton:hover {{
            background-color: {theme["secondary_light"]};
            border: 1px solid {theme["primary"]};
            outline: none;
        }}
        QPushButton:pressed {{
            background-color: {theme["secondary"]};
            border: 1px solid {theme["primary_light"]};
            outline: none;
        }}
        QPushButton:checked {{
            background-color: {theme["secondary"]};
            color: {theme["secondary_text"]};
            border: 2px solid {theme["primary"]} !important;
            outline: none;
        }}
        QPushButton:focus {{
            outline: none;
            border: 1px solid {theme["primary"]};
        }}
    """

    for varga_num in varga_numbers:
        if is_varga_implemented(varga_num):
            # Display label: use "10R" for 1010, "24R" for 2424
            if varga_num == 1010:
                label = "10R"
            elif varga_num == 2424:
                label = "24R"
            else:
                label = str(varga_num)

            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(varga_num == 1)
            btn.setStyleSheet(button_style)
            btn.setToolTip(f"D-{varga_num} ({get_varga_name(varga_num)})")
            btn.clicked.connect(lambda checked, v=varga_num: gui._switch_varga(v))

            gui.varga_button_group.addButton(btn, varga_num)
            gui.varga_buttons[varga_num] = btn
            layout.addWidget(btn)

    # Add stretch at bottom to push buttons up
    layout.addStretch()

    scroll.setWidget(container)
    return scroll


def refresh_varga_theme(gui):
    """Refresh varga button styles when theme changes."""
    theme = get_theme_colors()
    style = f"""
        QPushButton {{
            background-color: {theme["secondary_dark"]};
            color: {theme["secondary_text"]};
            border: 1px solid {theme["secondary_light"]};
            border-radius: 3px;
            font-size: {scaled_area_px('sidebar')}px; font-weight: bold;
            min-height: {scaled_px(22)}px; max-height: {scaled_px(22)}px; max-width: {scaled_px(35)}px;
            padding: 0px; outline: none;
        }}
        QPushButton:hover {{
            background-color: {theme["secondary_light"]};
            border: 1px solid {theme["primary"]};
        }}
        QPushButton:checked {{
            background-color: {theme["secondary"]};
            color: {theme["secondary_text"]};
            border: 2px solid {theme["primary"]} !important;
        }}
        QPushButton:focus {{ outline: none; border: 1px solid {theme["primary"]}; }}
    """
    for btn in getattr(gui, 'varga_buttons', {}).values():
        btn.setStyleSheet(style)
