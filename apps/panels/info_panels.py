#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Info Panels (Karakas + Strength + Aspects)
Right-side stacked panels showing karaka assignments, planetary strengths, and aspects

Extracted from core_gui_qt.py for modularity
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QStackedWidget, QPushButton, QTextEdit,
    QTextBrowser
)
from PySide6.QtCore import Qt, QObject, QEvent, QSize
from PySide6.QtGui import QIcon

# Import centralized theme
from ui.qt_theme import (
    BG, SURFACE, TEXT_PRIMARY, FONT_MONO,
    ACCENTS, get_header_style, get_panel_style, get_frame_style,
    get_theme_colors, scaled_px, scaled_area_px
)

# Import highlight delegates
from apps.delegates import KarakaHighlightDelegate, StrengthHighlightDelegate, AspectHighlightDelegate, AvasthaHighlightDelegate, TajikaHighlightDelegate, RetinueColorDelegate

# Import fullscreen popup dialog
from apps.widgets.info_panel_dialog import open_panel_dialog

# SPEC-SET-002 Phase 5: persist sub-panel tab selections (respects lock)
from managers.settings_manager import get_settings

# Panel width constant
INFO_PANEL_WIDTH = 380  # Increased for table format with 3 columns


class _PanelDoubleClickFilter(QObject):
    """Open the enlarged popup when the user double-clicks a panel widget."""

    def __init__(self, callback, parent=None):
        super().__init__(parent)
        self._callback = callback

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseButtonDblClick:
            self._callback()
            return True
        return super().eventFilter(watched, event)


def _bind_panel_popup(widget, callback):
    """Preserve the documented double-click popup without using QGraphicsProxyWidget."""
    event_filter = _PanelDoubleClickFilter(callback, widget)
    widget.installEventFilter(event_filter)
    if hasattr(widget, "viewport"):
        viewport = widget.viewport()
        if viewport is not None:
            viewport.installEventFilter(event_filter)
    widget._panel_popup_filter = event_filter


def _avastha_row_height():
    """Row height for the Avastha table, scaled to table font size."""
    return max(18, scaled_area_px('tables') + 8)


def create_right_panels(gui):
    """
    Create right side panels (Karakas + Strength + Aspects stacked vertically).

    Args:
        gui: The parent ChartGUI instance (for list storage)

    Returns:
        QWidget: The combined panel widget
    """
    # Get theme colors for dynamic theming
    theme = get_theme_colors()

    panel = QWidget()
    panel.setFixedWidth(INFO_PANEL_WIDTH)
    panel.setStyleSheet(get_panel_style())

    layout = QVBoxLayout(panel)
    layout.setSpacing(5)
    layout.setContentsMargins(5, 5, 5, 5)

    # === KARAKAS / HORA / TRIMSAMSA PANEL (with inline tabs) ===
    karakas_frame = QWidget()
    karakas_frame.setStyleSheet(get_frame_style())
    gui.karakas_frame = karakas_frame  # Store for theme refresh
    karakas_layout = QVBoxLayout(karakas_frame)
    karakas_layout.setSpacing(2)
    karakas_layout.setContentsMargins(5, 5, 5, 5)

    # Header with inline tab buttons (theme-aware colors)
    karakas_header = QWidget()
    karakas_header.setFixedHeight(32)
    gui.karakas_header = karakas_header
    karakas_header.setStyleSheet(f"""
        QWidget {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {theme["primary_light"]},
                stop:1 {theme["primary"]});
            border-radius: 6px;
        }}
    """)
    karakas_header_layout = QHBoxLayout(karakas_header)
    karakas_header_layout.setContentsMargins(8, 2, 8, 2)

    # Tab button styles (will be stored on gui by Strength panel below)
    _k_tab_active = f"""
        QPushButton {{
            color: {theme['primary_text']}; font-size: {scaled_area_px('panel_titles')}px; font-weight: bold;
            background: transparent; border: none;
            border-bottom: 2px solid {theme['primary_text']}; padding: 2px 8px;
        }}
    """
    _k_tab_inactive = f"""
        QPushButton {{
            color: {theme['primary_text']}; font-size: {scaled_area_px('panel_titles')}px; font-weight: normal;
            background: transparent; border: none;
            border-bottom: 2px solid transparent; padding: 2px 8px; opacity: 0.7;
        }}
        QPushButton:hover {{ border-bottom: 2px solid rgba(255,255,255,0.5); }}
    """

    _sep_style = f"QLabel {{ color: {theme['primary_text']}; font-size: {scaled_area_px('panel_titles')}px; background: transparent; opacity: 0.5; }}"

    # Build swap icon inline (same SVG as strength panel, defined here for reuse)
    import os
    _swap_icon_path = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'img', 'icons', 'swap_arrows.svg'))
    _karakas_swap_icon_style = f"""
        QPushButton {{ background: {theme["secondary_dark"]}; border: 1px solid {theme["primary"]};
            border-radius: {scaled_px(4)}px; padding: 0px; }}
        QPushButton:hover {{ background: {theme["primary"]}; border-color: {theme["primary_light"]}; }}
    """

    def _make_karakas_swap_icon(color=None):
        if color is None:
            color = theme["primary_text"]
        try:
            with open(_swap_icon_path, "r") as f:
                svg = f.read()
            svg = svg.replace('stroke="white"', f'stroke="{color}"')
            from PySide6.QtSvg import QSvgRenderer
            from PySide6.QtGui import QPixmap, QPainter
            renderer = QSvgRenderer(svg.encode())
            pm = QPixmap(scaled_px(16), scaled_px(13))
            pm.fill(Qt.GlobalColor.transparent)
            p = QPainter(pm)
            renderer.render(p)
            p.end()
            return QIcon(pm)
        except Exception:
            return QIcon()

    gui.karakas_tab_btn = QPushButton("Karakas")
    gui.karakas_tab_btn.setStyleSheet(_k_tab_active)
    gui.karakas_tab_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    karakas_header_layout.addWidget(gui.karakas_tab_btn)

    sep1 = QLabel("|")
    sep1.setStyleSheet(_sep_style)
    karakas_header_layout.addWidget(sep1)

    gui.hora_tab_btn = QPushButton("Hora")
    gui.hora_tab_btn.setStyleSheet(_k_tab_inactive)
    gui.hora_tab_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    karakas_header_layout.addWidget(gui.hora_tab_btn)

    sep2 = QLabel("|")
    sep2.setStyleSheet(_sep_style)
    karakas_header_layout.addWidget(sep2)

    gui.trimsamsa_tab_btn = QPushButton("Trim")
    gui.trimsamsa_tab_btn.setStyleSheet(_k_tab_inactive)
    gui.trimsamsa_tab_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    karakas_header_layout.addWidget(gui.trimsamsa_tab_btn)

    sep3 = QLabel("|")
    sep3.setStyleSheet(_sep_style)
    karakas_header_layout.addWidget(sep3)

    gui.graph_tab_btn = QPushButton("Houses")
    gui.graph_tab_btn.setStyleSheet(_k_tab_inactive)
    gui.graph_tab_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    karakas_header_layout.addWidget(gui.graph_tab_btn)

    # Swap button at the end (same position as strength panel)
    gui.karakas_swap_btn = QPushButton()
    gui.karakas_swap_btn.setIcon(_make_karakas_swap_icon())
    gui.karakas_swap_btn.setIconSize(QSize(scaled_px(16), scaled_px(13)))
    gui.karakas_swap_btn.setFixedSize(scaled_px(24), scaled_px(20))
    gui.karakas_swap_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    gui.karakas_swap_btn.setToolTip("Toggle enriched views: Karakas+/Condition")
    gui.karakas_swap_btn.setStyleSheet(_karakas_swap_icon_style)
    karakas_header_layout.addWidget(gui.karakas_swap_btn)

    karakas_header_layout.addStretch()
    karakas_layout.addWidget(karakas_header)

    # Store tab styles for karakas panel switching
    gui._karakas_tab_active_style = _k_tab_active
    gui._karakas_tab_inactive_style = _k_tab_inactive

    # === STACKED WIDGET for Karakas/Hora/Trimsamsa ===
    gui.karakas_stack = QStackedWidget()
    gui.karakas_stack.setMinimumHeight(220)

    # --- Shared table style ---
    _table_style = f"""
        QTableWidget {{
            background-color: {theme["secondary_dark"]};
            border: none; font-size: {scaled_area_px('tables')}px;
            gridline-color: {theme["secondary_light"]};
        }}
        QTableWidget::item {{ background-color: transparent; padding: 3px; }}
        QTableWidget::item:selected {{
            background-color: {theme["primary"]}; color: {theme["primary_text"]};
        }}
        QHeaderView::section {{
            background-color: {theme["secondary"]}; color: {theme["secondary_text"]};
            border: 1px solid {theme["secondary_light"]};
            padding: 4px; font-size: {scaled_area_px('table_headers')}px; font-weight: bold;
        }}
    """

    # Retinue table style — NO ::item rules so setBackground() works.
    # Qt's stylesheet engine takes total ownership of item painting when
    # ANY QTableWidget::item rule exists, even padding-only. BackgroundRole
    # from setBackground() is ignored. We must avoid ::item entirely.
    _retinue_table_style = f"""
        QTableWidget {{
            background-color: {theme["secondary_dark"]};
            border: none; font-size: {scaled_area_px('tables')}px;
            gridline-color: {theme["secondary_light"]};
        }}
        QHeaderView::section {{
            background-color: {theme["secondary"]}; color: {theme["secondary_text"]};
            border: 1px solid {theme["secondary_light"]};
            padding: 4px; font-size: {scaled_area_px('table_headers')}px; font-weight: bold;
        }}
    """

    # --- Page 0: Karakas Table (existing, unchanged) ---
    gui.karakas_table = QTableWidget()
    gui.karakas_table.setColumnCount(3)
    gui.karakas_table.setRowCount(7)
    gui.karakas_table.setHorizontalHeaderLabels(["Karaka", "Planet", "Cusp Lord"])
    gui.karakas_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    gui.karakas_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    gui.karakas_table.verticalHeader().setVisible(False)
    gui.karakas_table.setShowGrid(True)
    gui.karakas_table.setStyleSheet(_table_style)
    gui.karakas_table.setMinimumSize(INFO_PANEL_WIDTH - 20, 240)
    gui.karakas_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    gui.karakas_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
    gui.karakas_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
    gui.karakas_table.verticalHeader().setDefaultSectionSize(30)

    gui.karakas_delegate = KarakaHighlightDelegate(parent=gui.karakas_table)
    gui.karakas_table.setItemDelegate(gui.karakas_delegate)

    _bind_panel_popup(gui.karakas_table, lambda: open_panel_dialog(gui, "karakas"))

    # Nested stack for Karakas sub-tab: View 0 = basic, View 1 = enriched
    gui.karakas_inner_stack = QStackedWidget()
    gui.karakas_inner_stack.addWidget(gui.karakas_table)  # View 0: basic

    from PySide6.QtWidgets import QTextBrowser, QSizePolicy
    gui.karakas_enriched_tb = QTextBrowser()
    gui.karakas_enriched_tb.setReadOnly(True)
    gui.karakas_enriched_tb.setOpenLinks(False)
    gui.karakas_enriched_tb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    _bind_panel_popup(gui.karakas_enriched_tb, lambda: open_panel_dialog(gui, "karakas"))
    gui.karakas_inner_stack.addWidget(gui.karakas_enriched_tb)  # View 1: enriched

    gui.karakas_stack.addWidget(gui.karakas_inner_stack)  # Index 0

    # --- Page 1: Hora Table (compact: no sign/deg, those are on the chart) ---
    gui.hora_table = QTableWidget()
    gui.hora_table.setColumnCount(3)
    gui.hora_table.setRowCount(11)
    gui.hora_table.setHorizontalHeaderLabels(["Planet", "Hora Being", "Ruler"])
    gui.hora_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    gui.hora_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    gui.hora_table.verticalHeader().setVisible(False)
    gui.hora_table.setShowGrid(True)
    gui.hora_table.setStyleSheet(_retinue_table_style)
    gui.hora_table.setMinimumSize(INFO_PANEL_WIDTH - 20, 240)
    gui.hora_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
    gui.hora_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
    gui.hora_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
    gui.hora_table.verticalHeader().setDefaultSectionSize(22)

    gui.hora_delegate = RetinueColorDelegate(parent=gui.hora_table)
    gui.hora_table.setItemDelegate(gui.hora_delegate)

    _bind_panel_popup(gui.hora_table, lambda: open_panel_dialog(gui, "karakas"))
    gui.karakas_stack.addWidget(gui.hora_table)  # Index 1

    # --- Page 2: Trimsamsa Table (compact + Element column) ---
    gui.trimsamsa_table = QTableWidget()
    gui.trimsamsa_table.setColumnCount(4)
    gui.trimsamsa_table.setRowCount(11)
    gui.trimsamsa_table.setHorizontalHeaderLabels(["Planet", "Being", "Type", "Element"])
    gui.trimsamsa_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    gui.trimsamsa_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    gui.trimsamsa_table.verticalHeader().setVisible(False)
    gui.trimsamsa_table.setShowGrid(True)
    gui.trimsamsa_table.setStyleSheet(_retinue_table_style)
    gui.trimsamsa_table.setMinimumSize(INFO_PANEL_WIDTH - 20, 240)
    gui.trimsamsa_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
    gui.trimsamsa_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
    gui.trimsamsa_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
    gui.trimsamsa_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
    gui.trimsamsa_table.verticalHeader().setDefaultSectionSize(22)

    gui.trimsamsa_delegate = RetinueColorDelegate(parent=gui.trimsamsa_table)
    gui.trimsamsa_table.setItemDelegate(gui.trimsamsa_delegate)

    _bind_panel_popup(gui.trimsamsa_table, lambda: open_panel_dialog(gui, "karakas"))
    gui.karakas_stack.addWidget(gui.trimsamsa_table)  # Index 2

    # --- Page 3: Houses/Condition nested stack ---
    gui.condition_inner_stack = QStackedWidget()

    # View 0: House Graph (default)
    from apps.widgets.panel_controllers.house_graph_controller import _HouseBarWidget
    gui.house_graph_bars = _HouseBarWidget(gui_ref=gui)
    gui.house_graph_bars.setMinimumSize(INFO_PANEL_WIDTH - 20, 240)
    gui.condition_inner_stack.addWidget(gui.house_graph_bars)  # View 0

    # View 1: Planetary Condition compact (behind arrow)
    gui.condition_compact_tb = QTextBrowser()
    gui.condition_compact_tb.setReadOnly(True)
    gui.condition_compact_tb.setOpenLinks(False)
    gui.condition_compact_tb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    _bind_panel_popup(gui.condition_compact_tb, lambda: open_panel_dialog(gui, "karakas"))
    gui.condition_inner_stack.addWidget(gui.condition_compact_tb)  # View 1

    gui.karakas_stack.addWidget(gui.condition_inner_stack)  # Index 3

    karakas_layout.addWidget(gui.karakas_stack)

    # Tab switching logic (4 tabs: Karakas, Hora, Trimsamsa, Condition)
    _all_tab_btns = lambda: [gui.karakas_tab_btn, gui.hora_tab_btn,
                             gui.trimsamsa_tab_btn, gui.graph_tab_btn]

    def _switch_tab(index, active_btn):
        gui.karakas_stack.setCurrentIndex(index)
        for btn in _all_tab_btns():
            btn.setStyleSheet(gui._karakas_tab_active_style if btn is active_btn
                              else gui._karakas_tab_inactive_style)
        get_settings().persist_runtime_change("ui.panel.karakas_tab", index)

    def switch_to_karakas():
        _switch_tab(0, gui.karakas_tab_btn)

    def switch_to_hora():
        _switch_tab(1, gui.hora_tab_btn)

    def switch_to_trimsamsa():
        _switch_tab(2, gui.trimsamsa_tab_btn)

    def switch_to_condition():
        _switch_tab(3, gui.graph_tab_btn)
        if gui.condition_inner_stack.currentIndex() == 0 and hasattr(gui, 'house_graph_bars'):
            gui.house_graph_bars.update()
        elif gui.condition_inner_stack.currentIndex() == 1:
            if hasattr(gui, '_ensure_controller'):
                gui._ensure_controller('planetary_condition')
                if hasattr(gui, 'planetary_condition_controller'):
                    gui.planetary_condition_controller.set_visible(True)

    gui.karakas_tab_btn.clicked.connect(switch_to_karakas)
    gui.hora_tab_btn.clicked.connect(switch_to_hora)
    gui.trimsamsa_tab_btn.clicked.connect(switch_to_trimsamsa)
    gui.graph_tab_btn.clicked.connect(switch_to_condition)

    gui.switch_to_karakas_tab = switch_to_karakas
    gui.switch_to_hora_tab = switch_to_hora
    gui.switch_to_trimsamsa_tab = switch_to_trimsamsa
    gui.switch_to_graph_tab = switch_to_condition

    # Single swap handler: toggles ALL enriched views at once
    gui._karakas_enriched_mode = False

    def _toggle_enriched():
        gui._karakas_enriched_mode = not gui._karakas_enriched_mode
        enriched = gui._karakas_enriched_mode
        new_idx = 1 if enriched else 0
        gui.karakas_inner_stack.setCurrentIndex(new_idx)
        gui.condition_inner_stack.setCurrentIndex(new_idx)
        if enriched:
            if hasattr(gui, 'karakas_controller'):
                gui.karakas_controller._refresh()
            if hasattr(gui, '_ensure_controller'):
                gui._ensure_controller('planetary_condition')
                if hasattr(gui, 'planetary_condition_controller'):
                    gui.planetary_condition_controller.set_visible(True)
        if not enriched:
            if hasattr(gui, 'planetary_condition_controller'):
                gui.planetary_condition_controller.set_visible(False)
            if hasattr(gui, 'house_graph_bars'):
                gui.house_graph_bars.update()

    gui.karakas_swap_btn.clicked.connect(_toggle_enriched)
    gui._toggle_enriched = _toggle_enriched

    # Add small vertical space below
    karakas_layout.addSpacing(5)
    layout.addWidget(karakas_frame, stretch=3)

    # === STRENGTH / ELEMENTS PANEL (with inline tabs) ===
    strength_frame = QWidget()
    strength_frame.setStyleSheet(get_frame_style())
    gui.strength_frame = strength_frame  # Store for theme refresh
    strength_layout = QVBoxLayout(strength_frame)
    strength_layout.setSpacing(2)
    strength_layout.setContentsMargins(5, 5, 5, 5)

    # Header with inline tab buttons (theme-aware colors)
    strength_header = QWidget()
    strength_header.setFixedHeight(32)
    gui.strength_header = strength_header
    strength_header.setStyleSheet(f"""
        QWidget {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {theme["primary_light"]},
                stop:1 {theme["primary"]});
            border-radius: 6px;
        }}
    """)
    strength_header_layout = QHBoxLayout(strength_header)
    strength_header_layout.setContentsMargins(8, 2, 8, 2)

    # Tab button style (active vs inactive)
    tab_active_style = f"""
        QPushButton {{
            color: {theme['primary_text']};
            font-size: {scaled_area_px('panel_titles')}px;
            font-weight: bold;
            background: transparent;
            border: none;
            border-bottom: 2px solid {theme['primary_text']};
            padding: 2px 8px;
        }}
    """
    tab_inactive_style = f"""
        QPushButton {{
            color: {theme['primary_text']};
            font-size: {scaled_area_px('panel_titles')}px;
            font-weight: normal;
            background: transparent;
            border: none;
            border-bottom: 2px solid transparent;
            padding: 2px 8px;
            opacity: 0.7;
        }}
        QPushButton:hover {{
            border-bottom: 2px solid rgba(255,255,255,0.5);
        }}
    """

    # Strength tab button
    gui.strength_tab_btn = QPushButton("Strength")
    gui.strength_tab_btn.setStyleSheet(tab_active_style)
    gui.strength_tab_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    strength_header_layout.addWidget(gui.strength_tab_btn)

    # Separator
    sep_label = QLabel("|")
    sep_label.setStyleSheet(f"QLabel {{ color: {theme['primary_text']}; font-size: {scaled_area_px('panel_titles')}px; background: transparent; opacity: 0.5; }}")
    strength_header_layout.addWidget(sep_label)

    # Elements tab button
    gui.elements_tab_btn = QPushButton("Elem")
    gui.elements_tab_btn.setStyleSheet(tab_inactive_style)
    gui.elements_tab_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    strength_header_layout.addWidget(gui.elements_tab_btn)

    # Separator 2
    sep_label2 = QLabel("|")
    sep_label2.setStyleSheet(f"QLabel {{ color: {theme['primary_text']}; font-size: {scaled_area_px('panel_titles')}px; background: transparent; opacity: 0.5; }}")
    strength_header_layout.addWidget(sep_label2)

    # Modes tab button (Movable/Fixed/Dual)
    gui.modality_tab_btn = QPushButton("Modes")
    gui.modality_tab_btn.setStyleSheet(tab_inactive_style)
    gui.modality_tab_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    strength_header_layout.addWidget(gui.modality_tab_btn)

    # Separator 3
    sep_label3 = QLabel("|")
    sep_label3.setStyleSheet(f"QLabel {{ color: {theme['primary_text']}; font-size: {scaled_area_px('panel_titles')}px; background: transparent; opacity: 0.5; }}")
    strength_header_layout.addWidget(sep_label3)

    # Dignities tab button
    gui.dignities_tab_btn = QPushButton("Dignities")
    gui.dignities_tab_btn.setStyleSheet(tab_inactive_style)
    gui.dignities_tab_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    strength_header_layout.addWidget(gui.dignities_tab_btn)

    # Strength header language toggle (Sanskrit ↔ English)
    gui._strength_english_mode = False  # False = Sanskrit (Digbala/Uccha/Chesta), True = English (Direction/Energy/Confidence)
    import os
    _swap_icon_path = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'img', 'icons', 'swap_arrows.svg'))

    def _make_swap_icon(color=None):
        """Build a QIcon from the swap_arrows SVG with the given stroke color."""
        if color is None:
            color = theme["primary_text"]
        with open(_swap_icon_path, "r") as f:
            svg = f.read()
        svg = svg.replace('stroke="white"', f'stroke="{color}"')
        from PySide6.QtSvg import QSvgRenderer
        from PySide6.QtGui import QPixmap, QPainter
        renderer = QSvgRenderer(svg.encode())
        pm = QPixmap(scaled_px(16), scaled_px(13))
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        renderer.render(p)
        p.end()
        return QIcon(pm)

    gui._make_swap_icon = _make_swap_icon
    gui._swap_icon_path = _swap_icon_path
    gui.strength_lang_btn = QPushButton()
    gui.strength_lang_btn.setIcon(_make_swap_icon())
    gui.strength_lang_btn.setIconSize(QSize(scaled_px(16), scaled_px(13)))
    gui.strength_lang_btn.setFixedSize(scaled_px(24), scaled_px(20))
    gui.strength_lang_btn.setToolTip("Toggle column headers: Sanskrit ↔ English")
    gui.strength_lang_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    gui.strength_lang_btn.setStyleSheet(f"""
        QPushButton {{ background: {theme["secondary_dark"]}; border: 1px solid {theme["primary"]};
            border-radius: {scaled_px(4)}px; padding: 0px; }}
        QPushButton:hover {{ background: {theme["primary"]}; border-color: {theme["primary_light"]}; }}
    """)
    strength_header_layout.addWidget(gui.strength_lang_btn)

    strength_header_layout.addStretch()
    strength_layout.addWidget(strength_header)

    # Store tab styles for switching
    gui._tab_active_style = tab_active_style
    gui._tab_inactive_style = tab_inactive_style

    # === STACKED WIDGET for Strength/Elements tables ===
    gui.strength_elements_stack = QStackedWidget()
    gui.strength_elements_stack.setMinimumHeight(200)

    # --- Page 0: Strength Table ---
    gui.strength_table = QTableWidget()
    gui.strength_table.setColumnCount(4)
    gui.strength_table.setRowCount(7)
    gui.strength_table.setHorizontalHeaderLabels(["Planet", "Digbala", "Uccha", "Chesta"])
    # Tooltips on column headers explaining the Sanskrit terms
    for col, tip in [(1, "Direction"), (2, "Energy"), (3, "Confidence")]:
        item = gui.strength_table.horizontalHeaderItem(col)
        if item:
            item.setToolTip(tip)
    gui.strength_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    gui.strength_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    gui.strength_table.verticalHeader().setVisible(False)
    gui.strength_table.setShowGrid(True)
    table_style = f"""
        QTableWidget {{
            background-color: {theme["secondary_dark"]};
            border: none;
            font-size: {scaled_area_px('tables')}px;
            gridline-color: {theme["secondary_light"]};
        }}
        QTableWidget::item {{
            background-color: transparent;
            padding: 3px;
        }}
        QTableWidget::item:selected {{
            background-color: {theme["primary"]};
            color: {theme["primary_text"]};
        }}
        QHeaderView::section {{
            background-color: {theme["secondary"]};
            color: {theme["secondary_text"]};
            border: 1px solid {theme["secondary_light"]};
            padding: 4px;
            font-size: {scaled_area_px('table_headers')}px;
            font-weight: bold;
        }}
    """
    gui.strength_table.setStyleSheet(table_style)
    gui.strength_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    gui.strength_table.verticalHeader().setDefaultSectionSize(30)

    # Apply highlight delegate for high-strength planets
    gui.strength_delegate = StrengthHighlightDelegate(parent=gui.strength_table)
    gui.strength_table.setItemDelegate(gui.strength_delegate)
    gui.strength_table.setMinimumSize(INFO_PANEL_WIDTH - 20, 220)

    _bind_panel_popup(gui.strength_table, lambda: open_panel_dialog(gui, "strength"))
    gui.strength_elements_stack.addWidget(gui.strength_table)  # Index 0

    # --- Page 1: Elements Table ---
    gui.elements_table = QTableWidget()
    gui.elements_table.setColumnCount(3)
    gui.elements_table.setRowCount(4)  # Fire, Earth, Air, Water
    gui.elements_table.setHorizontalHeaderLabels(["Element", "%", "Planets"])
    gui.elements_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    gui.elements_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    gui.elements_table.verticalHeader().setVisible(False)
    gui.elements_table.setShowGrid(True)
    gui.elements_table.setStyleSheet(table_style)
    gui.elements_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
    gui.elements_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
    gui.elements_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
    gui.elements_table.verticalHeader().setDefaultSectionSize(55)  # Taller rows for planet lists
    gui.elements_table.setMinimumSize(INFO_PANEL_WIDTH - 20, 220)
    gui.elements_delegate = StrengthHighlightDelegate(parent=gui.elements_table)
    gui.elements_table.setItemDelegate(gui.elements_delegate)

    _bind_panel_popup(gui.elements_table, lambda: open_panel_dialog(gui, "strength"))
    gui.strength_elements_stack.addWidget(gui.elements_table)  # Index 1

    # --- Page 2: Modality Table ---
    gui.modality_table = QTableWidget()
    gui.modality_table.setColumnCount(3)
    gui.modality_table.setRowCount(3)  # Moveable, Fixed, Dual
    gui.modality_table.setHorizontalHeaderLabels(["Modality", "%", "Planets"])
    gui.modality_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    gui.modality_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    gui.modality_table.verticalHeader().setVisible(False)
    gui.modality_table.setShowGrid(True)
    gui.modality_table.setStyleSheet(table_style)
    gui.modality_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
    gui.modality_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
    gui.modality_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
    gui.modality_table.verticalHeader().setDefaultSectionSize(75)  # Taller rows for planet lists + descriptions
    gui.modality_table.setMinimumSize(INFO_PANEL_WIDTH - 20, 220)
    gui.modality_delegate = StrengthHighlightDelegate(parent=gui.modality_table)
    gui.modality_table.setItemDelegate(gui.modality_delegate)

    _bind_panel_popup(gui.modality_table, lambda: open_panel_dialog(gui, "strength"))
    gui.strength_elements_stack.addWidget(gui.modality_table)  # Index 2

    # --- Page 3: Dignities in Vargas Table ---
    gui.dignities_table = QTableWidget()
    gui.dignities_table.setColumnCount(8)
    gui.dignities_table.setRowCount(16)
    gui.dignities_table.setHorizontalHeaderLabels(["", "Su", "Mo", "Ma", "Me", "Ju", "Ve", "Sa"])
    gui.dignities_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    gui.dignities_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    gui.dignities_table.verticalHeader().setVisible(False)
    gui.dignities_table.setShowGrid(True)
    gui.dignities_table.setStyleSheet(table_style)
    gui.dignities_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    gui.dignities_table.verticalHeader().setDefaultSectionSize(24)
    gui.dignities_table.setMinimumSize(INFO_PANEL_WIDTH - 20, 220)
    from apps.widgets.panel_controllers.dignities_controller import DignityColorDelegate
    gui.dignities_table.setItemDelegate(DignityColorDelegate(parent=gui.dignities_table))

    _bind_panel_popup(gui.dignities_table, lambda: open_panel_dialog(gui, "strength"))
    gui.strength_elements_stack.addWidget(gui.dignities_table)  # Index 3

    strength_layout.addWidget(gui.strength_elements_stack)

    # Tab switching logic (for 4 tabs: Strength, Elem, Modes, Dignities)
    _all_strength_tabs = lambda: [
        gui.strength_tab_btn, gui.elements_tab_btn,
        gui.modality_tab_btn, gui.dignities_tab_btn,
    ]

    def _update_lang_btn_tooltip(index):
        if index == 0:
            tip = "Toggle column headers: Sanskrit / English"
        elif index == 2:
            ctrl = getattr(gui, "modality_controller", None)
            if ctrl and ctrl.yoga_mode:
                tip = "Switch to standard terms (Movable / Fixed / Dual)"
            else:
                tip = "Switch to Yoga terms (Rajju / Musala / Nala)"
        elif index == 3:
            ctrl = getattr(gui, "dignities_controller", None)
            label = ctrl.varga_style_label if ctrl else "Classical"
            tip = f"Varga style: {label} (click to cycle)"
        else:
            tip = ""
        gui.strength_lang_btn.setToolTip(tip)
        gui.strength_lang_btn.setVisible(index in (0, 2, 3))

    def _switch_strength_tab(index, active_btn):
        gui.strength_elements_stack.setCurrentIndex(index)
        for btn in _all_strength_tabs():
            btn.setStyleSheet(gui._tab_active_style if btn is active_btn else gui._tab_inactive_style)
        _update_lang_btn_tooltip(index)
        get_settings().persist_runtime_change("ui.panel.strength_tab", index)

    def switch_to_strength():
        _switch_strength_tab(0, gui.strength_tab_btn)

    def switch_to_elements():
        _switch_strength_tab(1, gui.elements_tab_btn)

    def switch_to_modality():
        _switch_strength_tab(2, gui.modality_tab_btn)

    def switch_to_dignities():
        _switch_strength_tab(3, gui.dignities_tab_btn)

    def _toggle_strength_language():
        gui._strength_english_mode = not gui._strength_english_mode
        if gui._strength_english_mode:
            gui.strength_table.setHorizontalHeaderLabels(["Planet", "Direction", "Energy", "Confidence"])
            gui.strength_lang_btn.setToolTip("Switch to Sanskrit terms (Digbala / Uccha / Chesta)")
        else:
            gui.strength_table.setHorizontalHeaderLabels(["Planet", "Digbala", "Uccha", "Chesta"])
            gui.strength_lang_btn.setToolTip("Switch to English terms (Direction / Energy / Confidence)")
        for col, (sanskrit, english) in enumerate(
            [("Digbala", "Direction"), ("Uccha Bala", "Energy"), ("Chesta Bala", "Confidence")], start=1
        ):
            item = gui.strength_table.horizontalHeaderItem(col)
            if item:
                item.setToolTip(english if not gui._strength_english_mode else sanskrit)

    def _toggle_modality_yoga():
        ctrl = getattr(gui, "modality_controller", None)
        if ctrl:
            ctrl.toggle_yoga_mode()
            if ctrl.yoga_mode:
                gui.strength_lang_btn.setToolTip("Switch to standard terms (Movable / Fixed / Dual)")
            else:
                gui.strength_lang_btn.setToolTip("Switch to Yoga terms (Rajju / Musala / Nala)")

    def _toggle_dignities_style():
        ctrl = getattr(gui, "dignities_controller", None)
        if ctrl:
            ctrl.toggle_varga_style()
            gui.strength_lang_btn.setToolTip(
                f"Varga style: {ctrl.varga_style_label} (click to cycle)"
            )

    def toggle_language():
        active_idx = gui.strength_elements_stack.currentIndex()
        if active_idx == 0:
            _toggle_strength_language()
        elif active_idx == 2:
            _toggle_modality_yoga()
        elif active_idx == 3:
            _toggle_dignities_style()

    def _on_modality_row_clicked(row, _col):
        ctrl = getattr(gui, "modality_controller", None)
        if ctrl and ctrl.yoga_mode:
            from apps.widgets.panel_controllers.modality_controller import ModalityController
            ModalityController.show_yoga_detail(gui, row)

    gui.modality_table.cellClicked.connect(_on_modality_row_clicked)

    gui.strength_tab_btn.clicked.connect(switch_to_strength)
    gui.elements_tab_btn.clicked.connect(switch_to_elements)
    gui.modality_tab_btn.clicked.connect(switch_to_modality)
    gui.dignities_tab_btn.clicked.connect(switch_to_dignities)
    gui.strength_lang_btn.clicked.connect(toggle_language)

    # Store switch functions for external use
    gui.switch_to_strength_tab = switch_to_strength
    gui.switch_to_elements_tab = switch_to_elements
    gui.switch_to_modality_tab = switch_to_modality
    gui.switch_to_dignities_tab = switch_to_dignities

    # Add small vertical space below
    strength_layout.addSpacing(5)
    layout.addWidget(strength_frame, stretch=2)

    # === ASPECTS / AVASTHA / SHAME PANEL (with inline tabs) ===
    aspects_frame = QWidget()
    aspects_frame.setStyleSheet(get_frame_style())
    gui.aspects_frame = aspects_frame  # Store for theme refresh
    aspects_layout = QVBoxLayout(aspects_frame)
    aspects_layout.setSpacing(2)
    aspects_layout.setContentsMargins(5, 5, 5, 5)

    # Header with inline tab buttons (same pattern as Strength panel)
    aspects_header = QWidget()
    aspects_header.setFixedHeight(32)
    gui.aspects_header = aspects_header
    aspects_header.setStyleSheet(f"""
        QWidget {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {theme["primary_light"]},
                stop:1 {theme["primary"]});
            border-radius: 6px;
        }}
    """)
    aspects_header_layout = QHBoxLayout(aspects_header)
    aspects_header_layout.setContentsMargins(8, 2, 8, 2)

    # Vedic/Tajika mode toggle button
    gui._aspects_mode = "vedic"  # default mode
    gui.aspects_mode_btn = QPushButton()
    gui.aspects_mode_btn.setIcon(_make_swap_icon())
    gui.aspects_mode_btn.setIconSize(QSize(scaled_px(16), scaled_px(13)))
    gui.aspects_mode_btn.setFixedSize(scaled_px(24), scaled_px(20))
    gui.aspects_mode_btn.setToolTip("Toggle: Vedic ↔ Tajika aspects")
    gui.aspects_mode_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    gui.aspects_mode_btn.setStyleSheet(f"""
        QPushButton {{ background: {theme["secondary_dark"]}; border: 1px solid {theme["primary"]};
            border-radius: {scaled_px(4)}px; padding: 0px; }}
        QPushButton:hover {{ background: {theme["primary"]}; border-color: {theme["primary_light"]}; }}
    """)

    # Aspects tab button (active by default)
    gui.aspects_tab_btn = QPushButton("Aspects V")
    gui.aspects_tab_btn.setStyleSheet(tab_active_style)
    gui.aspects_tab_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    aspects_header_layout.addWidget(gui.aspects_tab_btn)

    # Separator
    asp_sep1 = QLabel("|")
    asp_sep1.setStyleSheet(f"QLabel {{ color: {theme['primary_text']}; font-size: {scaled_area_px('panel_titles')}px; background: transparent; opacity: 0.5; }}")
    aspects_header_layout.addWidget(asp_sep1)

    # Avastha tab button
    gui.avastha_tab_btn = QPushButton("Avastha")
    gui.avastha_tab_btn.setStyleSheet(tab_inactive_style)
    gui.avastha_tab_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    aspects_header_layout.addWidget(gui.avastha_tab_btn)

    # Separator
    asp_sep2 = QLabel("|")
    asp_sep2.setStyleSheet(f"QLabel {{ color: {theme['primary_text']}; font-size: {scaled_area_px('panel_titles')}px; background: transparent; opacity: 0.5; }}")
    aspects_header_layout.addWidget(asp_sep2)

    # Shame tab button
    gui.shame_tab_btn = QPushButton("Shame")
    gui.shame_tab_btn.setStyleSheet(tab_inactive_style)
    gui.shame_tab_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    aspects_header_layout.addWidget(gui.shame_tab_btn)

    # Separator (Vedic-only, hidden in Tajika)
    gui._asp_sep3 = QLabel("|")
    gui._asp_sep3.setStyleSheet(f"QLabel {{ color: {theme['primary_text']}; font-size: {scaled_area_px('panel_titles')}px; background: transparent; opacity: 0.5; }}")
    aspects_header_layout.addWidget(gui._asp_sep3)

    # Exchange tab button (Vedic-only, hidden in Tajika)
    gui.exchange_tab_btn = QPushButton("Exch")
    gui.exchange_tab_btn.setStyleSheet(tab_inactive_style)
    gui.exchange_tab_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    aspects_header_layout.addWidget(gui.exchange_tab_btn)

    aspects_header_layout.addWidget(gui.aspects_mode_btn)
    aspects_header_layout.addStretch()
    aspects_layout.addWidget(aspects_header)

    # === STACKED WIDGET for Aspects/Avastha/Shame ===
    gui.aspects_stack = QStackedWidget()
    gui.aspects_stack.setMinimumHeight(200)

    # Common table style for aspects section
    aspects_table_style = f"""
        QTableWidget {{
            background-color: {theme["secondary_dark"]};
            border: none;
            font-size: {scaled_area_px('tables')}px;
            gridline-color: {theme["secondary_light"]};
        }}
        QTableWidget::item {{
            background-color: transparent;
            padding: 2px;
        }}
        QTableWidget::item:selected {{
            background-color: {theme["primary"]};
            color: {theme["primary_text"]};
        }}
        QHeaderView::section {{
            background-color: {theme["secondary"]};
            color: {theme["secondary_text"]};
            border: 1px solid {theme["secondary_light"]};
            padding: 2px;
            font-size: {scaled_area_px('table_headers')}px;
            font-weight: bold;
        }}
    """

    # --- Page 0: Aspects Table (existing 7x9 matrix, unchanged) ---
    gui.aspects_table = QTableWidget()
    gui.aspects_table.setColumnCount(9)
    gui.aspects_table.setRowCount(7)
    gui.aspects_table.setHorizontalHeaderLabels(["Su", "Mo", "Ma", "Me", "Ju", "Ve", "Sa", "Ra", "Ke"])
    gui.aspects_table.setVerticalHeaderLabels(["☉Su", "☽Mo", "♂Ma*", "☿Me", "♃Ju*", "♀Ve", "♄Sa*"])
    gui.aspects_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    gui.aspects_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    gui.aspects_table.verticalHeader().setVisible(True)
    gui.aspects_table.setShowGrid(True)
    gui.aspects_table.setStyleSheet(aspects_table_style)
    for col in range(9):
        gui.aspects_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
    gui.aspects_table.verticalHeader().setDefaultSectionSize(26)
    gui.aspects_table.verticalHeader().setMinimumWidth(45)

    gui.aspects_delegate = AspectHighlightDelegate(parent=gui.aspects_table)
    gui.aspects_table.setItemDelegate(gui.aspects_delegate)
    gui.aspects_table.setMinimumSize(INFO_PANEL_WIDTH - 20, 200)

    _bind_panel_popup(gui.aspects_table, lambda: open_panel_dialog(gui, "aspects"))
    gui.aspects_stack.addWidget(gui.aspects_table)  # Index 0

    # --- Page 1: Avastha Table (7x7 + TOTALS row + SIGN row) ---
    gui.avastha_table = QTableWidget()
    gui.avastha_table.setColumnCount(7)
    gui.avastha_table.setRowCount(9)  # 7 planets + TOTALS + SIGN
    gui.avastha_table.setHorizontalHeaderLabels(["Su", "Mo", "Ma", "Me", "Ju", "Ve", "Sa"])
    gui.avastha_table.setVerticalHeaderLabels(["☉Su", "☽Mo", "♂Ma*", "☿Me", "♃Ju*", "♀Ve", "♄Sa*", "TOTAL", "SIGN"])
    gui.avastha_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    gui.avastha_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    gui.avastha_table.verticalHeader().setVisible(True)
    gui.avastha_table.setShowGrid(True)
    gui.avastha_table.setStyleSheet(aspects_table_style)
    for col in range(7):
        gui.avastha_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
    _av_rh = _avastha_row_height()
    gui.avastha_table.verticalHeader().setDefaultSectionSize(_av_rh)
    gui.avastha_table.verticalHeader().setMinimumWidth(45)

    gui.avastha_delegate = AvasthaHighlightDelegate(parent=gui.avastha_table)
    gui.avastha_table.setItemDelegate(gui.avastha_delegate)
    gui.avastha_table.setMinimumSize(INFO_PANEL_WIDTH - 20, 9 * _av_rh + _av_rh + 10)

    _bind_panel_popup(gui.avastha_table, lambda: open_panel_dialog(gui, "aspects"))
    gui.aspects_stack.addWidget(gui.avastha_table)  # Index 1

    # --- Page 2: Shame Display (rich HTML) ---
    gui.shame_display = QTextEdit()
    gui.shame_display.setReadOnly(True)
    gui.shame_display.setStyleSheet(f"""
        QTextEdit {{
            background-color: {theme["secondary_dark"]};
            color: {theme["secondary_text"]};
            border: none;
            font-size: {scaled_area_px('tables')}px;
            font-family: monospace;
        }}
    """)
    gui.shame_display.setMinimumSize(INFO_PANEL_WIDTH - 20, 200)

    _bind_panel_popup(gui.shame_display, lambda: open_panel_dialog(gui, "aspects"))
    gui.aspects_stack.addWidget(gui.shame_display)  # Index 2

    # --- Page 3: Tajika Matrix (11x11 aspect table) ---
    gui.tajika_matrix_table = QTableWidget()
    gui.tajika_matrix_table.setColumnCount(11)
    gui.tajika_matrix_table.setRowCount(11)
    tajika_headers = ["Lg", "Su", "Mo", "Ma", "Me", "Ju", "Ve", "Sa", "Ur", "Ne", "Pl"]
    gui.tajika_matrix_table.setHorizontalHeaderLabels(tajika_headers)
    gui.tajika_matrix_table.setVerticalHeaderLabels(tajika_headers)
    gui.tajika_matrix_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    gui.tajika_matrix_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    gui.tajika_matrix_table.verticalHeader().setVisible(True)
    gui.tajika_matrix_table.setShowGrid(True)
    gui.tajika_matrix_table.setStyleSheet(aspects_table_style)
    for col in range(11):
        gui.tajika_matrix_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
    gui.tajika_matrix_table.verticalHeader().setDefaultSectionSize(22)
    gui.tajika_matrix_table.verticalHeader().setMinimumWidth(30)

    gui.tajika_delegate = TajikaHighlightDelegate(parent=gui.tajika_matrix_table)
    gui.tajika_matrix_table.setItemDelegate(gui.tajika_delegate)
    gui.tajika_matrix_table.setMinimumSize(INFO_PANEL_WIDTH - 20, 200)

    _bind_panel_popup(gui.tajika_matrix_table, lambda: open_panel_dialog(gui, "aspects"))
    gui.aspects_stack.addWidget(gui.tajika_matrix_table)  # Index 3

    # --- Page 4: Tajika Relationships (table with shape icons) ---
    gui.tajika_rel_table = QTableWidget()
    gui.tajika_rel_table.setColumnCount(5)
    gui.tajika_rel_table.setHorizontalHeaderLabels(["", "Pair", "Aspect", "VR", "Orb"])
    gui.tajika_rel_table.verticalHeader().setVisible(False)
    gui.tajika_rel_table.setShowGrid(True)
    gui.tajika_rel_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    gui.tajika_rel_table.setStyleSheet(aspects_table_style)
    # Column 0 (shape icon) narrow, rest stretch
    gui.tajika_rel_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
    gui.tajika_rel_table.setColumnWidth(0, 28)
    for col in range(1, 5):
        gui.tajika_rel_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
    gui.tajika_rel_table.verticalHeader().setDefaultSectionSize(24)

    gui.tajika_rel_delegate = TajikaHighlightDelegate(parent=gui.tajika_rel_table)
    gui.tajika_rel_table.setItemDelegate(gui.tajika_rel_delegate)
    gui.tajika_rel_table.setMinimumSize(INFO_PANEL_WIDTH - 20, 200)

    # No ZoomableContainer — this table needs native scrolling
    gui.aspects_stack.addWidget(gui.tajika_rel_table)  # Index 4

    # --- Page 5: Tajika Yogas Placeholder ---
    gui.tajika_placeholder = QTextEdit()
    gui.tajika_placeholder.setReadOnly(True)
    gui.tajika_placeholder.setStyleSheet(f"""
        QTextEdit {{
            background-color: {theme["secondary_dark"]};
            color: {theme["secondary_text"]};
            border: none;
            font-size: {scaled_area_px('tables')}px;
        }}
    """)
    gui.tajika_placeholder.setHtml(f"""
        <div style="text-align:center; padding:40px;">
            <h3 style="color:{theme['primary']}">Tajika Yogas</h3>
            <p style="color:{theme['secondary_text']}">Coming Soon</p>
            <p style="color:{theme['secondary_text']}; font-size: {scaled_area_px('status')}px; margin-top: 20px;">
                Ishta Kashta Phala, Ithasala, Easarapha, Nakta, Yamaya, etc.
            </p>
        </div>
    """)
    gui.tajika_placeholder.setMinimumSize(INFO_PANEL_WIDTH - 20, 200)

    # No ZoomableContainer — QTextEdit has native scrolling
    gui.aspects_stack.addWidget(gui.tajika_placeholder)  # Index 5

    # --- Page 6: Exchange (Parivartana) yoga display (Vedic only) ---
    gui.exchange_display = QTextBrowser()
    gui.exchange_display.setStyleSheet(f"""
        QTextBrowser {{
            background-color: {theme["secondary_dark"]};
            color: {theme["secondary_text"]};
            border: none;
            font-size: {scaled_area_px('tables')}px;
            font-family: monospace;
        }}
    """)
    gui.exchange_display.setMinimumSize(INFO_PANEL_WIDTH - 20, 200)
    gui.exchange_display.setOpenLinks(False)  # anchorClicked still fires for our yoga: scheme

    def _on_exchange_link(url):
        ctrl = getattr(gui, "interchange_controller", None)
        if ctrl:
            ctrl.handle_link_click(url)

    gui.exchange_display.anchorClicked.connect(_on_exchange_link)

    _bind_panel_popup(gui.exchange_display, lambda: open_panel_dialog(gui, "aspects"))
    gui.aspects_stack.addWidget(gui.exchange_display)  # Index 6

    aspects_layout.addWidget(gui.aspects_stack)

    # === TAB SWITCHING LOGIC (mode-aware: Vedic / Tajika) ===

    # Helper to set tab button active/inactive styling
    def _set_tab_styles(active_idx):
        """Set tab button styles: active_idx 0=first, 1=second, 2=third, 3=fourth."""
        btns = [gui.aspects_tab_btn, gui.avastha_tab_btn, gui.shame_tab_btn, gui.exchange_tab_btn]
        for i, btn in enumerate(btns):
            btn.setStyleSheet(gui._tab_active_style if i == active_idx else gui._tab_inactive_style)

    # Vedic tab switches (indices 0-2)
    def switch_to_aspects():
        gui.aspects_stack.setCurrentIndex(0)
        _set_tab_styles(0)
        if hasattr(gui, 'avastha_controller'):
            gui.avastha_controller.set_visible(False)
        if hasattr(gui, 'shame_controller'):
            gui.shame_controller.set_visible(False)
        if hasattr(gui, 'interchange_controller'):
            gui.interchange_controller.set_visible(False)

    def switch_to_avastha():
        gui.aspects_stack.setCurrentIndex(1)
        _set_tab_styles(1)
        gui._ensure_controller('avastha')
        if hasattr(gui, 'avastha_controller'):
            gui.avastha_controller.set_visible(True)
        if hasattr(gui, 'shame_controller'):
            gui.shame_controller.set_visible(False)
        if hasattr(gui, 'interchange_controller'):
            gui.interchange_controller.set_visible(False)

    def switch_to_shame():
        gui.aspects_stack.setCurrentIndex(2)
        _set_tab_styles(2)
        if hasattr(gui, 'avastha_controller'):
            gui.avastha_controller.set_visible(False)
        gui._ensure_controller('shame')
        if hasattr(gui, 'shame_controller'):
            gui.shame_controller.set_visible(True)
        if hasattr(gui, 'interchange_controller'):
            gui.interchange_controller.set_visible(False)

    def switch_to_exchange():
        gui.aspects_stack.setCurrentIndex(6)
        _set_tab_styles(3)
        if hasattr(gui, 'avastha_controller'):
            gui.avastha_controller.set_visible(False)
        if hasattr(gui, 'shame_controller'):
            gui.shame_controller.set_visible(False)
        gui._ensure_controller('interchange')
        if hasattr(gui, 'interchange_controller'):
            gui.interchange_controller.set_visible(True)

    # Tajika tab switches (indices 3-5)
    def switch_to_tajika_matrix():
        gui.aspects_stack.setCurrentIndex(3)
        _set_tab_styles(0)
        gui._ensure_controller('tajika_matrix')
        if hasattr(gui, 'avastha_controller'):
            gui.avastha_controller.set_visible(False)
        if hasattr(gui, 'shame_controller'):
            gui.shame_controller.set_visible(False)
        if hasattr(gui, 'interchange_controller'):
            gui.interchange_controller.set_visible(False)

    def switch_to_tajika_relationships():
        gui.aspects_stack.setCurrentIndex(4)
        _set_tab_styles(1)
        gui._ensure_controller('tajika_relationships')
        if hasattr(gui, 'avastha_controller'):
            gui.avastha_controller.set_visible(False)
        if hasattr(gui, 'shame_controller'):
            gui.shame_controller.set_visible(False)
        if hasattr(gui, 'interchange_controller'):
            gui.interchange_controller.set_visible(False)

    def switch_to_tajika_placeholder():
        gui.aspects_stack.setCurrentIndex(5)
        _set_tab_styles(2)
        gui._ensure_controller('tajika_yogas')
        if hasattr(gui, 'avastha_controller'):
            gui.avastha_controller.set_visible(False)
        if hasattr(gui, 'shame_controller'):
            gui.shame_controller.set_visible(False)
        if hasattr(gui, 'interchange_controller'):
            gui.interchange_controller.set_visible(False)

    # Mode-aware tab button handlers
    def on_tab1_click():
        if gui._aspects_mode == "vedic":
            switch_to_aspects()
        else:
            switch_to_tajika_matrix()
        get_settings().persist_runtime_change("ui.panel.aspects_tab", 0)

    def on_tab2_click():
        if gui._aspects_mode == "vedic":
            switch_to_avastha()
        else:
            switch_to_tajika_relationships()
        get_settings().persist_runtime_change("ui.panel.aspects_tab", 1)

    def on_tab3_click():
        if gui._aspects_mode == "vedic":
            switch_to_shame()
        else:
            switch_to_tajika_placeholder()
        get_settings().persist_runtime_change("ui.panel.aspects_tab", 2)

    def on_tab4_click():
        if gui._aspects_mode == "vedic":
            switch_to_exchange()
            get_settings().persist_runtime_change("ui.panel.aspects_tab", 3)

    gui.aspects_tab_btn.clicked.connect(on_tab1_click)
    gui.avastha_tab_btn.clicked.connect(on_tab2_click)
    gui.shame_tab_btn.clicked.connect(on_tab3_click)
    gui.exchange_tab_btn.clicked.connect(on_tab4_click)

    # Toggle between Vedic and Tajika modes
    def toggle_aspects_mode():
        if gui._aspects_mode == "vedic":
            gui._aspects_mode = "tajika"
            gui.aspects_tab_btn.setText("Aspects T")
            gui.avastha_tab_btn.setText("Relations")
            gui.shame_tab_btn.setText("Yogas")
            gui.exchange_tab_btn.setVisible(False)
            gui._asp_sep3.setVisible(False)
            switch_to_tajika_matrix()
        else:
            gui._aspects_mode = "vedic"
            gui.aspects_tab_btn.setText("Aspects V")
            gui.avastha_tab_btn.setText("Avastha")
            gui.shame_tab_btn.setText("Shame")
            gui.exchange_tab_btn.setVisible(True)
            gui._asp_sep3.setVisible(True)
            switch_to_aspects()
        # Toggling mode jumps to the first tab of the new mode.
        get_settings().persist_runtime_change("ui.panel.aspects_mode", gui._aspects_mode)
        get_settings().persist_runtime_change("ui.panel.aspects_tab", 0)

    gui.aspects_mode_btn.clicked.connect(toggle_aspects_mode)

    # Store switch functions for external use
    gui.switch_to_aspects_tab = switch_to_aspects
    gui.switch_to_avastha_tab = switch_to_avastha
    gui.switch_to_shame_tab = switch_to_shame
    gui.switch_to_exchange_tab = switch_to_exchange
    gui.switch_to_tajika_matrix_tab = switch_to_tajika_matrix
    gui.switch_to_tajika_relationships_tab = switch_to_tajika_relationships
    gui.switch_to_tajika_yogas_tab = switch_to_tajika_placeholder

    # Add small spacing below
    aspects_layout.addSpacing(5)
    layout.addWidget(aspects_frame, stretch=2)

    # === DOUBLE-CLICK FULLSCREEN POPUP (also on headers + frame backgrounds) ===
    karakas_frame.mouseDoubleClickEvent = lambda e: open_panel_dialog(gui, "karakas")
    karakas_header.mouseDoubleClickEvent = lambda e: open_panel_dialog(gui, "karakas")
    strength_frame.mouseDoubleClickEvent = lambda e: open_panel_dialog(gui, "strength")
    strength_header.mouseDoubleClickEvent = lambda e: open_panel_dialog(gui, "strength")
    aspects_frame.mouseDoubleClickEvent = lambda e: open_panel_dialog(gui, "aspects")
    aspects_header.mouseDoubleClickEvent = lambda e: open_panel_dialog(gui, "aspects")

    return panel
