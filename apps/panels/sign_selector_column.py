#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Sign Selector Column (Z6b)

Right-side mirror of the Varga column. Twelve buttons numbered 1..12
(Aditya-order: 1=Dhata, 2=Aryama, ..., 12=Parjanya) with full Aditya
name in the tooltip. Mutually exclusive AND fully deselectable:
clicking the already-active button deselects it.

Selecting a sign drives the South Indian view's center 2x2 box into
"Mode 2" (mini North Indian chart with that sign forced as Ascendant).
Deselecting restores Mode 1 (live hover preview).
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QScrollArea, QSizePolicy
)
from PySide6.QtCore import Qt

from ui.qt_theme import get_theme_colors, scaled_px, scaled_area_px


# Aditya names in 1..12 order (canonical mapping per zodiac spec).
# Imported by callers that need the tooltip mapping; the same list
# already exists at apps/widgets/chart_view.py:182. New duplicates
# of this constant are forbidden by the handoff acceptance checklist;
# this module re-uses it via lazy import to avoid a circular import
# (chart_view imports from apps.widgets.* heavily).
def _get_aditya_names():
    """Lazy fetch of ADITYA_NAMES from the canonical class to avoid
    duplicate declarations and circular imports at module-load time."""
    from apps.widgets.chart_view import SouthIndianView
    return SouthIndianView.ADITYA_NAMES


def create_sign_selector_column(gui):
    """
    Create the right-side Z6b sign-selector column.

    Args:
        gui: The parent ChartGUI instance. The factory
             attaches `gui.sign_selector_buttons` (dict[int, QPushButton])
             and `gui.selected_z6b_sign` (int|None, 1-based) for callers.

    Behaviour:
        - Buttons labelled "1".."12" map to Aditya signs Dhata..Parjanya.
        - Tooltip = full Aditya name.
        - Click an unselected button -> selects it; clears any prior
          selection; calls gui._on_z6b_selection_changed(sign_index).
        - Click the already-selected button -> deselects it; calls
          gui._on_z6b_selection_changed(None).

    Returns:
        QScrollArea: scrollable column widget, ready to add to a layout.
    """
    theme = get_theme_colors()
    aditya_names = _get_aditya_names()

    scroll = QScrollArea()
    scroll.setFixedWidth(45)
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

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

    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setSpacing(2)
    layout.setContentsMargins(2, 5, 2, 5)

    button_style = _build_button_style(theme)

    # NOTE: deliberately NOT using QButtonGroup.setExclusive(True): Qt's
    # exclusive group rejects clicks on the already-active button, which
    # would break the "click-to-deselect" requirement from the handoff.
    # We implement single-selection manually in the click handler below.
    gui.sign_selector_buttons = {}
    gui.selected_z6b_sign = None  # 1-based, or None when nothing selected

    for sign_index in range(1, 13):  # 1..12
        btn = QPushButton(str(sign_index))
        btn.setCheckable(True)
        btn.setChecked(False)
        btn.setStyleSheet(button_style)
        aditya_name = aditya_names[sign_index - 1]
        btn.setToolTip(f"{aditya_name} - sign {sign_index}")
        btn.clicked.connect(
            lambda _checked, s=sign_index: _on_button_clicked(gui, s)
        )
        gui.sign_selector_buttons[sign_index] = btn
        layout.addWidget(btn)

    layout.addStretch()
    scroll.setWidget(container)
    return scroll


def _on_button_clicked(gui, sign_index):
    """Handle Z6b button click. Implements click-to-deselect semantics
    that QButtonGroup.exclusive cannot provide.
    """
    buttons = getattr(gui, "sign_selector_buttons", None) or {}
    clicked_btn = buttons.get(sign_index)

    if gui.selected_z6b_sign == sign_index:
        # Re-clicking the active button -> deselect.
        if clicked_btn is not None:
            clicked_btn.setChecked(False)
        gui.selected_z6b_sign = None
        new_sign = None
    else:
        # Switch selection: uncheck siblings, check this one.
        for idx, b in buttons.items():
            if idx != sign_index and b.isChecked():
                b.setChecked(False)
        if clicked_btn is not None:
            clicked_btn.setChecked(True)
        gui.selected_z6b_sign = sign_index
        new_sign = sign_index

    # Drop keyboard focus from the just-clicked button.
    #
    # Why: the stylesheet's :focus rule paints a 1px pink border in the
    # same color as the :checked rule's 2px pink border — similar enough
    # at button scale that a focused-but-unchecked button visually reads
    # as "still selected". After a deselect, the button is correctly
    # unchecked but Qt leaves it focused, so the :focus rule keeps it
    # highlighted until the user clicks elsewhere. clearFocus() drops
    # the focus immediately so the default (unchecked, unfocused)
    # styling applies right away.
    #
    # On the select branch this is harmless: the button's :checked
    # state still paints its 2px pink border via the :checked rule,
    # which is independent of focus.
    #
    # Future structural option: change :focus to a different border
    # color (not just thickness) so the two states can never visually
    # collide regardless of pixel-thickness tweaks.
    if clicked_btn is not None:
        clicked_btn.clearFocus()

    handler = getattr(gui, "_on_z6b_selection_changed", None)
    if callable(handler):
        handler(new_sign)


def _build_button_style(theme):
    """Theme-driven button stylesheet matching varga_column.py exactly,
    so Z6b is visually flush with Z6.
    """
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


def refresh_sign_selector_theme(gui):
    """Refresh Z6b button styles after a theme change.

    Mirrors refresh_varga_theme() at apps/panels/varga_column.py.
    """
    theme = get_theme_colors()
    style = _build_button_style(theme)
    for btn in getattr(gui, "sign_selector_buttons", {}).values():
        btn.setStyleSheet(style)
