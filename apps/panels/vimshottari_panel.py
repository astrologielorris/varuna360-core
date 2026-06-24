#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Vimshottari Dasha Panel
Right-side panel showing Vimshottari dasha periods with level selection

Extracted from core_gui_qt.py for modularity
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QButtonGroup, QComboBox
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon
from ui.qt_theme import scaled_px, scaled_area_px, get_dasha_header_height, get_dasha_level_button_size

# Import centralized theme
from ui.qt_theme import (
    ACCENTS, get_list_style, get_header_style, get_panel_style,
    get_3d_button_style, get_panel_header_3d_style, get_theme_colors
)

# Import delegate for highlighting
from apps.delegates import DashaHighlightDelegate

# Panel width constant (shared between both dasha panels)
DASHA_PANEL_WIDTH = 265  # Increased by 70px for better period visibility


def create_vimshottari_panel(gui):
    """
    Create Vimshottari Dasha panel (far right) with level buttons and dasha list.

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
    gui.vimshottari_header = header
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

    # Top row: title button + swap button
    title_row = QHBoxLayout()
    title_row.setContentsMargins(0, 0, 0, 0)
    title_row.setSpacing(4)

    from apps.widgets.ayanamsa_dialog import get_ayanamsa_name
    ayanamsa_name = get_ayanamsa_name(getattr(gui, 'vimshottari_ayanamsa', 98))
    gui.vimshottari_title_btn = QPushButton(f"{ayanamsa_name}  \u25be")
    gui.vimshottari_title_btn.setStyleSheet(f"""
        QPushButton {{ color: {theme["secondary_text"]}; font-size: {scaled_area_px('panel_titles')}px; font-weight: bold;
            background: transparent; border: none; text-transform: none;
            text-align: left; padding: 0px; }}
        QPushButton:hover {{ color: {theme["primary_light"]}; }}
    """)
    gui.vimshottari_title_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    gui.vimshottari_title_btn.setToolTip("Click to change ayanamsa")
    gui.vimshottari_title_btn.clicked.connect(lambda: gui._change_dasha_ayanamsa("vimshottari"))
    title_row.addWidget(gui.vimshottari_title_btn)

    title_row.addStretch()

    gui.vimshottari_swap_btn = QPushButton()
    make_icon = getattr(gui, '_make_swap_icon', None)
    if make_icon:
        gui.vimshottari_swap_btn.setIcon(make_icon())
    else:
        import os
        gui.vimshottari_swap_btn.setIcon(QIcon(
            os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'img', 'icons', 'swap_arrows.svg'))))
    gui.vimshottari_swap_btn.setIconSize(QSize(scaled_px(16), scaled_px(13)))
    gui.vimshottari_swap_btn.setFixedSize(scaled_px(24), scaled_px(20))
    gui.vimshottari_swap_btn.setStyleSheet(f"""
        QPushButton {{ background: {theme["secondary_dark"]}; border: 1px solid {theme["primary"]};
            border-radius: {scaled_px(4)}px; padding: 0px; }}
        QPushButton:hover {{ background: {theme["primary"]}; border-color: {theme["primary_light"]}; }}
    """)
    gui.vimshottari_swap_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    gui.vimshottari_swap_btn.setToolTip("Switch: Vimshottari / Planetary Ages (F7)")
    gui.vimshottari_swap_btn.clicked.connect(gui._cycle_right_dasha)
    title_row.addWidget(gui.vimshottari_swap_btn)

    header_vlayout.addLayout(title_row)

    # Bottom row: level buttons right-aligned
    btn_row = QHBoxLayout()
    btn_row.setContentsMargins(0, 0, 0, 0)
    btn_row.setSpacing(3)
    btn_row.addStretch()

    gui.vimshottari_level_buttons = []
    level_btn_style = get_3d_button_style("cyan", "small")
    gui.vimshottari_level_group = QButtonGroup(gui)
    gui.vimshottari_level_group.setExclusive(True)

    for i in range(1, 6):
        btn = QPushButton(str(i))
        btn.setCheckable(True)
        btn.setChecked(i == 1)
        btn.setStyleSheet(level_btn_style)
        btn.setFixedSize(*get_dasha_level_button_size())
        btn.clicked.connect(lambda checked, lvl=i: gui._set_vimshottari_level(lvl))
        gui.vimshottari_level_group.addButton(btn, i)
        gui.vimshottari_level_buttons.append(btn)
        btn_row.addWidget(btn)

    header_vlayout.addLayout(btn_row)
    layout.addWidget(header)

    # === ROW 2: NAVIGATION arrows (horizontal layout) ===
    nav_frame = QWidget()
    nav_frame.setStyleSheet(f"background-color: {theme['secondary']};")
    gui.vimshottari_nav_frame = nav_frame  # Store for theme refresh
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

    gui.vimshottari_prev_btn = QPushButton("<")
    gui.vimshottari_prev_btn.setToolTip("Previous 120-year cycle (past)")
    gui.vimshottari_prev_btn.setStyleSheet(arrow_style)
    gui.vimshottari_prev_btn.clicked.connect(gui._navigate_vimshottari_previous)
    nav_layout.addWidget(gui.vimshottari_prev_btn)

    # Cycle indicator label (year range)
    gui.vimshottari_cycle_label = QLabel("0-120y")
    gui.vimshottari_cycle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    gui.vimshottari_cycle_label.setStyleSheet(f"color: {theme['secondary_text']}; font-size: {scaled_area_px('status')}px; font-weight: bold; background: transparent;")
    nav_layout.addWidget(gui.vimshottari_cycle_label, 1)

    gui.vimshottari_next_btn = QPushButton(">")
    gui.vimshottari_next_btn.setToolTip("Next 120-year cycle (future)")
    gui.vimshottari_next_btn.setStyleSheet(arrow_style)
    gui.vimshottari_next_btn.clicked.connect(gui._navigate_vimshottari_next)
    nav_layout.addWidget(gui.vimshottari_next_btn)

    layout.addWidget(nav_frame)
    layout.addSpacing(4)

    # === ROW 3: DASHA LIST ===
    gui.vimshottari_list = QListWidget()
    gui.vimshottari_list.setStyleSheet(get_list_style("cyan"))

    # Apply highlight delegate for current dasha periods
    gui.vimshottari_delegate = DashaHighlightDelegate(parent=gui.vimshottari_list)
    gui.vimshottari_list.setItemDelegate(gui.vimshottari_delegate)

    # Single click = select period (move ▶ marker); double click = expand
    gui.vimshottari_list.itemClicked.connect(
        lambda item: gui.dasha_manager.on_vimshottari_select(item))
    gui.vimshottari_list.itemDoubleClicked.connect(gui._on_vimshottari_clicked)

    # Enable right-click context menu for "Open in Transit"
    gui.vimshottari_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    gui.vimshottari_list.customContextMenuRequested.connect(
        lambda pos: gui._on_vimshottari_context_menu(pos)
    )

    layout.addWidget(gui.vimshottari_list)

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

    karaka_row = QHBoxLayout()
    karaka_row.setContentsMargins(2, 0, 2, 0)
    karaka_lbl = QLabel("Karaka")
    karaka_lbl.setStyleSheet(f"color: {ACCENTS['gold']['base']}; font-size: {scaled_area_px('buttons')}px; font-weight: bold;")
    karaka_lbl.setFixedWidth(scaled_px(60))
    gui.vimshottari_karaka_combo = QComboBox()
    gui.vimshottari_karaka_combo.setStyleSheet(combo_style)
    gui.vimshottari_karaka_combo.addItem("None", None)
    for code in ["AK", "AmK", "BK", "MK", "PiK", "GK", "DK"]:
        gui.vimshottari_karaka_combo.addItem(code, code)
    gui.vimshottari_karaka_combo.currentIndexChanged.connect(
        lambda _: gui.dasha_manager.refresh_dasha_lord_highlights("vimshottari"))
    karaka_row.addWidget(karaka_lbl)
    karaka_row.addWidget(gui.vimshottari_karaka_combo)
    layout.addLayout(karaka_row)

    cusp_row = QHBoxLayout()
    cusp_row.setContentsMargins(2, 0, 2, 0)
    cusp_lbl = QLabel("Cusp")
    cusp_lbl.setStyleSheet(f"color: {ACCENTS['cyan']['base']}; font-size: {scaled_area_px('buttons')}px; font-weight: bold;")
    cusp_lbl.setFixedWidth(scaled_px(60))
    gui.vimshottari_cusp_combo = QComboBox()
    gui.vimshottari_cusp_combo.setStyleSheet(combo_style)
    gui.vimshottari_cusp_combo.addItem("None", None)
    for h in range(1, 13):
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(h, "th")
        gui.vimshottari_cusp_combo.addItem(f"{h}{suffix}", h)
    gui.vimshottari_cusp_combo.currentIndexChanged.connect(
        lambda _: gui.dasha_manager.refresh_dasha_lord_highlights("vimshottari"))
    cusp_row.addWidget(cusp_lbl)
    cusp_row.addWidget(gui.vimshottari_cusp_combo)
    layout.addLayout(cusp_row)

    ws_row = QHBoxLayout()
    ws_row.setContentsMargins(2, 0, 2, 0)
    ws_lbl = QLabel("House")
    ws_lbl.setStyleSheet(f"color: {ACCENTS['orange']['base']}; font-size: {scaled_area_px('buttons')}px; font-weight: bold;")
    ws_lbl.setFixedWidth(scaled_px(60))
    gui.vimshottari_ws_combo = QComboBox()
    gui.vimshottari_ws_combo.setStyleSheet(combo_style)
    gui.vimshottari_ws_combo.addItem("None", None)
    for h in range(1, 13):
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(h, "th")
        gui.vimshottari_ws_combo.addItem(f"{h}{suffix}", h)
    gui.vimshottari_ws_combo.currentIndexChanged.connect(
        lambda _: gui.dasha_manager.refresh_dasha_lord_highlights("vimshottari"))
    ws_row.addWidget(ws_lbl)
    ws_row.addWidget(gui.vimshottari_ws_combo)
    layout.addLayout(ws_row)

    return panel
