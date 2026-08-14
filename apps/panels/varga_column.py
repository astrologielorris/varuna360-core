#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Varga Selection Column
Slim column with divisional chart selection buttons (D-1 to D-60)

Extracted from core_gui_qt.py for modularity
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QScrollArea, QButtonGroup, QSizePolicy,
    QFrame
)
from PySide6.QtCore import Qt

# Import centralized theme - use theme colors for checked state
from ui.qt_theme import get_theme_colors, scaled_px, scaled_area_px
from core.varga_codes import varga_display_label


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
            # "10R" for 1010, "24R" for 2424 — spelled once, in
            # core.varga_codes, so the column and the center-box label
            # cannot disagree (SPEC-VGC-001).
            label = varga_display_label(varga_num)

            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(varga_num == 1)
            btn.setStyleSheet(button_style)
            btn.setToolTip(f"D-{varga_num} ({get_varga_name(varga_num)})")
            btn.clicked.connect(lambda checked, v=varga_num: gui._switch_varga(v))

            gui.varga_button_group.addButton(btn, varga_num)
            gui.varga_buttons[varga_num] = btn
            layout.addWidget(btn)

    # SPEC-VGC-001: the varga-in-center toggle, below D-60.
    layout.addWidget(_center_separator(theme))
    layout.addWidget(_create_center_toggle(gui, theme))

    # Add stretch at bottom to push buttons up
    layout.addStretch()

    scroll.setWidget(container)
    return scroll


# Nested frames: a chart inside a chart. Picked on screen from five
# candidates (SPEC-VGC-001 D-6). "IN" was rejected — it sits in a column of
# short text labels and reads as another varga code at a glance, which is
# exactly the confusion INV-4 exists to prevent. Renders for the pick:
#   scripts/render_varga_center_button_candidates.py
CENTER_TOGGLE_MARK = "\u29c9"


def _center_separator(theme):
    """A thin rule between D-60 and the toggle. The toggle has to read as
    part of the column AND as not-a-varga; the rule does half that work."""
    rule = QFrame()
    rule.setFrameShape(QFrame.Shape.HLine)
    rule.setFixedHeight(6)
    rule.setStyleSheet(f"color: {theme['secondary_light']};")
    return rule


def center_toggle_style(theme):
    """Same shape as the varga buttons, but the checked state fills with the
    theme primary instead of merely outlining — a varga is *selected*, this
    is *on*, and they must not look alike."""
    return f"""
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
        }}
        QPushButton:checked {{
            background-color: {theme["primary"]};
            color: {theme["secondary_dark"]};
            border: 2px solid {theme["primary_light"]};
        }}
        QPushButton:disabled {{
            color: {theme["secondary_light"]};
            border: 1px solid {theme["secondary_dark"]};
        }}
        /* SPEC-VGC-001 D-1/INV-5: the mode is on but something outranks it
           (transit, time adjust). A lit toggle over a box showing something
           else would tell the user the varga is displayed when it is not. */
        QPushButton[suspended="true"] {{
            background-color: {theme["secondary_dark"]};
            color: {theme["secondary_light"]};
            border: 2px dashed {theme["primary"]};
        }}
        QPushButton:focus {{ outline: none; }}
    """


def _create_center_toggle(gui, theme):
    """Build the toggle and hang it off `gui`.

    INV-4: it must NOT join `gui.varga_button_group`. That group is
    EXCLUSIVE, so joining it would uncheck the selected varga the moment the
    toggle is pressed and the app would believe D-1 is selected. It is kept
    out of `gui.varga_buttons` too, because that dict is indexed by varga
    number and iterated as vargas elsewhere.
    """
    btn = QPushButton(CENTER_TOGGLE_MARK)
    btn.setCheckable(True)
    btn.setChecked(bool(getattr(gui, "varga_in_center", False)))
    btn.setStyleSheet(center_toggle_style(theme))
    # Surface-neutral: _sync_varga_center_button replaces this with wording
    # for whichever view is visible (SPEC-VGO-001 INV-8). This is only the
    # text between construction and the first sync.
    btn.setToolTip(
        "Show the divisional chart beside the main chart,\n"
        "keeping D-1 in the main chart")
    handler = getattr(gui, "_toggle_varga_in_center", None)
    if handler is not None:
        btn.toggled.connect(handler)
    gui.varga_center_button = btn
    return btn


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

    # The center toggle is deliberately outside `varga_buttons` (INV-4), so
    # it needs its own line here or it keeps the previous theme's colours.
    toggle = getattr(gui, 'varga_center_button', None)
    if toggle is not None:
        toggle.setStyleSheet(center_toggle_style(theme))
