#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Vedanga Dasha Panel
Left-side panel showing Vedanga dasha periods with level selection

Extracted from core_gui_qt.py for modularity
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QButtonGroup, QComboBox
)
from PySide6.QtCore import Qt
from ui.qt_theme import scaled_px, scaled_area_px, get_dasha_header_height, get_dasha_level_button_size

# Import centralized theme
from ui.qt_theme import (
    ACCENTS, get_button_style, get_list_style, get_header_style, get_panel_style,
    get_3d_button_style, get_panel_header_3d_style, get_theme_colors
)

# Import delegate for highlighting
from apps.delegates import DashaHighlightDelegate

# Panel width constant (shared between both dasha panels)
DASHA_PANEL_WIDTH = 265  # Increased by 70px for better period visibility


def create_vedanga_panel(gui):
    """
    Create Vedanga Dasha panel (far left) with level buttons and dasha list.

    Args:
        gui: The parent ChartGUI instance (for callbacks and list storage)

    Returns:
        QWidget: The panel widget
    """
    # Get theme colors for dynamic theming
    theme = get_theme_colors()

    panel = QWidget()
    panel.setFixedWidth(DASHA_PANEL_WIDTH)
    panel.setStyleSheet(get_panel_style())

    layout = QVBoxLayout(panel)
    layout.setSpacing(3)
    layout.setContentsMargins(5, 5, 5, 5)

    # === ROW 1: HEADER with title (row 1) and level buttons (row 2) ===
    header = QWidget()
    header.setFixedHeight(get_dasha_header_height())
    gui.vedanga_header = header
    header.setStyleSheet(f"""
        QWidget {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {theme["primary_light"]},
                stop:1 {theme["primary"]});
            border-radius: 6px;
        }}
    """)
    header_vlayout = QVBoxLayout(header)
    header_vlayout.setContentsMargins(8, 4, 8, 4)
    header_vlayout.setSpacing(2)

    # Top row: title button (full width)
    from apps.widgets.ayanamsa_dialog import get_ayanamsa_name
    ayanamsa_name = get_ayanamsa_name(getattr(gui, 'vedanga_ayanamsa', 100))
    gui.vedanga_title_btn = QPushButton(f"{ayanamsa_name}  \u25be")
    gui.vedanga_title_btn.setStyleSheet(f"""
        QPushButton {{ color: {theme["secondary_text"]}; font-size: {scaled_area_px('panel_titles')}px; font-weight: bold;
            background: transparent; border: none; text-transform: none;
            text-align: left; padding: 0px; }}
        QPushButton:hover {{ color: {theme["primary_light"]}; }}
    """)
    gui.vedanga_title_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    gui.vedanga_title_btn.setToolTip("Click to change ayanamsa")
    gui.vedanga_title_btn.clicked.connect(lambda: gui._change_dasha_ayanamsa("vedanga"))
    header_vlayout.addWidget(gui.vedanga_title_btn)

    # Bottom row: level buttons right-aligned
    btn_row = QHBoxLayout()
    btn_row.setContentsMargins(0, 0, 0, 0)
    btn_row.setSpacing(3)
    btn_row.addStretch()

    gui.vedanga_level_buttons = []
    level_btn_style = get_3d_button_style("orange", "small")
    gui.vedanga_level_group = QButtonGroup(gui)
    gui.vedanga_level_group.setExclusive(True)

    for i in range(1, 6):
        btn = QPushButton(str(i))
        btn.setCheckable(True)
        btn.setChecked(i == 1)
        btn.setStyleSheet(level_btn_style)
        btn.setFixedSize(*get_dasha_level_button_size())
        btn.clicked.connect(lambda checked, lvl=i: gui._set_vedanga_level(lvl))
        gui.vedanga_level_group.addButton(btn, i)
        gui.vedanga_level_buttons.append(btn)
        btn_row.addWidget(btn)

    header_vlayout.addLayout(btn_row)
    layout.addWidget(header)

    # === ROW 2: NAVIGATION arrows (horizontal layout) ===
    nav_frame = QWidget()
    nav_frame.setStyleSheet(f"background-color: {theme['secondary']};")
    gui.vedanga_nav_frame = nav_frame  # Store for theme refresh
    nav_layout = QHBoxLayout(nav_frame)
    nav_layout.setContentsMargins(4, 4, 4, 4)
    nav_layout.setSpacing(2)

    # Navigation arrow style — clean text arrows
    arrow_style = f"""
        QPushButton {{
            background-color: {theme["secondary_dark"]};
            color: {theme["secondary_text"]};
            border: 1px solid {theme["secondary_dark"]};
            border-radius: 3px;
            font-size: {scaled_area_px('buttons')}px;
            font-weight: bold;
            min-width: {scaled_px(24)}px;
            max-width: {scaled_px(24)}px;
            min-height: {scaled_px(20)}px;
            padding: 0px;
        }}
        QPushButton:hover {{
            background-color: {theme["secondary_light"]};
            border: 1px solid {theme["primary"]};
            color: {theme["primary"]};
        }}
        QPushButton:pressed {{
            background-color: {theme["primary"]};
            color: {theme["secondary_text"]};
        }}
    """

    gui.vedanga_prev_btn = QPushButton("<")
    gui.vedanga_prev_btn.setToolTip("Previous 120-year cycle (past)")
    gui.vedanga_prev_btn.setStyleSheet(arrow_style)
    gui.vedanga_prev_btn.clicked.connect(gui._navigate_vedanga_previous)
    nav_layout.addWidget(gui.vedanga_prev_btn)

    # Cycle indicator label (year range)
    gui.vedanga_cycle_label = QLabel("0-120y")
    gui.vedanga_cycle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    gui.vedanga_cycle_label.setStyleSheet(f"color: {theme['secondary_text']}; font-size: {scaled_area_px('status')}px; font-weight: bold; background: transparent;")
    nav_layout.addWidget(gui.vedanga_cycle_label, 1)

    gui.vedanga_next_btn = QPushButton(">")
    gui.vedanga_next_btn.setToolTip("Next 120-year cycle (future)")
    gui.vedanga_next_btn.setStyleSheet(arrow_style)
    gui.vedanga_next_btn.clicked.connect(gui._navigate_vedanga_next)
    nav_layout.addWidget(gui.vedanga_next_btn)

    layout.addWidget(nav_frame)
    layout.addSpacing(4)

    # === ROW 3: DASHA LIST ===
    gui.vedanga_list = QListWidget()
    gui.vedanga_list.setStyleSheet(get_list_style("orange"))

    # Apply highlight delegate for current dasha periods
    gui.vedanga_delegate = DashaHighlightDelegate(parent=gui.vedanga_list)
    gui.vedanga_list.setItemDelegate(gui.vedanga_delegate)

    # Single click = select period (move ▶ marker); double click = expand
    gui.vedanga_list.itemClicked.connect(
        lambda item: gui.dasha_manager.on_vedanga_select(item))
    gui.vedanga_list.itemDoubleClicked.connect(gui._on_vedanga_clicked)

    # Enable right-click context menu for "Open in Transit"
    gui.vedanga_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    gui.vedanga_list.customContextMenuRequested.connect(
        lambda pos: gui._on_vedanga_context_menu(pos)
    )

    layout.addWidget(gui.vedanga_list)

    # === ROW 4: HIGHLIGHT COMBOS (Karaka / Cusp Lord / WS Lord) ===
    combo_style = f"""
        QComboBox {{
            background-color: {theme["secondary_dark"]};
            color: {theme["secondary_text"]};
            border: 1px solid {theme["secondary"]};
            border-radius: 3px;
            padding: 2px 6px;
            font-size: {scaled_area_px('buttons')}px;
            min-height: {scaled_px(22)}px;
        }}
        QComboBox:hover {{ border: 1px solid {theme["primary"]}; }}
        QComboBox::drop-down {{ border: none; width: {scaled_px(16)}px; }}
        QComboBox QAbstractItemView {{
            background-color: {theme["secondary_dark"]};
            color: {theme["secondary_text"]};
            selection-background-color: {theme["primary"]};
            selection-color: {theme["primary_text"]};
            border: 1px solid {theme["secondary"]};
            font-size: {scaled_area_px('buttons')}px;
            padding: 2px;
            outline: none;
        }}
        QComboBox QAbstractItemView::item {{
            min-height: {scaled_px(24)}px;
            padding: 4px 8px;
        }}
    """

    # Row 1: Karaka combo
    karaka_row = QHBoxLayout()
    karaka_row.setContentsMargins(2, 0, 2, 0)
    karaka_lbl = QLabel("Karaka")
    karaka_lbl.setStyleSheet(f"color: {ACCENTS['gold']['base']}; font-size: {scaled_area_px('buttons')}px; font-weight: bold;")
    karaka_lbl.setFixedWidth(scaled_px(60))
    gui.vedanga_karaka_combo = QComboBox()
    gui.vedanga_karaka_combo.setStyleSheet(combo_style)
    gui.vedanga_karaka_combo.addItem("None", None)
    for code in ["AK", "AmK", "BK", "MK", "PiK", "GK", "DK"]:
        gui.vedanga_karaka_combo.addItem(code, code)
    gui.vedanga_karaka_combo.currentIndexChanged.connect(
        lambda _: gui.dasha_manager.refresh_dasha_lord_highlights("vedanga"))
    karaka_row.addWidget(karaka_lbl)
    karaka_row.addWidget(gui.vedanga_karaka_combo)
    layout.addLayout(karaka_row)

    # Row 2: Cusp lord combo
    cusp_row = QHBoxLayout()
    cusp_row.setContentsMargins(2, 0, 2, 0)
    cusp_lbl = QLabel("Cusp")
    cusp_lbl.setStyleSheet(f"color: {ACCENTS['cyan']['base']}; font-size: {scaled_area_px('buttons')}px; font-weight: bold;")
    cusp_lbl.setFixedWidth(scaled_px(60))
    gui.vedanga_cusp_combo = QComboBox()
    gui.vedanga_cusp_combo.setStyleSheet(combo_style)
    gui.vedanga_cusp_combo.addItem("None", None)
    for h in range(1, 13):
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(h, "th")
        gui.vedanga_cusp_combo.addItem(f"{h}{suffix}", h)
    gui.vedanga_cusp_combo.currentIndexChanged.connect(
        lambda _: gui.dasha_manager.refresh_dasha_lord_highlights("vedanga"))
    cusp_row.addWidget(cusp_lbl)
    cusp_row.addWidget(gui.vedanga_cusp_combo)
    layout.addLayout(cusp_row)

    # Row 3: Whole-sign lord combo
    ws_row = QHBoxLayout()
    ws_row.setContentsMargins(2, 0, 2, 0)
    ws_lbl = QLabel("House")
    ws_lbl.setStyleSheet(f"color: {ACCENTS['orange']['base']}; font-size: {scaled_area_px('buttons')}px; font-weight: bold;")
    ws_lbl.setFixedWidth(scaled_px(60))
    gui.vedanga_ws_combo = QComboBox()
    gui.vedanga_ws_combo.setStyleSheet(combo_style)
    gui.vedanga_ws_combo.addItem("None", None)
    for h in range(1, 13):
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(h, "th")
        gui.vedanga_ws_combo.addItem(f"{h}{suffix}", h)
    gui.vedanga_ws_combo.currentIndexChanged.connect(
        lambda _: gui.dasha_manager.refresh_dasha_lord_highlights("vedanga"))
    ws_row.addWidget(ws_lbl)
    ws_row.addWidget(gui.vedanga_ws_combo)
    layout.addLayout(ws_row)

    return panel
