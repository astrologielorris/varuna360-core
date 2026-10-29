#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Info Panels (Karakas + Strength + Aspects)
Right-side stacked panels showing karaka assignments, planetary strengths, and aspects

Extracted from core_gui_qt.py for modularity
"""
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QHeaderView,
    QStackedWidget,
    QPushButton,
    QTextEdit,
    QTextBrowser,
)
from PySide6.QtCore import Qt, QObject, QEvent, QSize

# Import centralized theme
from ui.qt_theme import (
    elevation_color,
    elevation_divider,
    DIVIDER_ALPHA_MATRIX,
    get_panel_style,
    get_frame_style,
    get_theme_colors,
    scaled_px,
    scaled_area_px,
)
from ui.accent_ink import on_accent_ink  # SPEC-THM-001 §13

def avastha_compact_table_style():
    """Avastha-specific table style (SPEC-AVA-001 rev3 display fix).

    Differs from the shared aspects style by ZERO horizontal item padding and
    1px header-section padding: 5-char dignity diagonals ("MK105"/"EX120" =
    36px at the default 11px tables font) sit right at the ~44px stretch
    column's edge and elide with the normal 2px padding.

    Called by BOTH the construction site and core_gui_qt._refresh_panel_styles
    so a live theme/font switch cannot drift from boot (one string, one source).
    """
    theme = get_theme_colors()
    return f"""
        QTableWidget {{
            background-color: {theme["secondary_dark"]};
            border: none;
            font-size: {scaled_area_px('tables')}px;
            gridline-color: {elevation_divider(DIVIDER_ALPHA_MATRIX)};
        }}
        QTableWidget::item {{
            background-color: transparent;
            padding: 2px 0px;
        }}
        QTableWidget::item:selected {{
            background-color: {theme["primary"]};
            color: {on_accent_ink(theme["primary"], theme["primary_text"])};
        }}
        QHeaderView::section {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {elevation_color(2)}, stop:1 {elevation_color(1)});
            color: {theme["secondary_text"]};
            border: 1px solid {theme["secondary_light"]};
            padding: 2px 1px;
            font-size: {scaled_area_px('table_headers')}px;
            font-weight: bold;
        }}
    """ + _THIN_SCROLLBAR_CSS


# One style per info-table family, used by BOTH the construction sites below and
# core_gui_qt._refresh_panel_styles, so a live theme switch repaints exactly what
# a boot paints (the copies had drifted: the refresh flattened every header,
# dropped the elevation gradient and the matrix gridline, and lost the Aspects
# row-header frame).
#   "table"   Karakas, Strength, Elements, Modes, Dignities
#   "retinue" Hora, Trimsamsa: NO ::item rules, so setBackground() still works
#             (Qt hands item painting to the stylesheet once any ::item rule exists)
#   "aspects" Aspects, Tajika matrix and relations (2 px padding)
_INFO_TABLE_PADDING = {"table": ("3px", "4px"), "retinue": (None, "4px"),
                       "aspects": ("2px", "2px")}


def info_table_style(kind="table"):
    """The QSS of one info-table family for the CURRENT theme and fonts."""
    theme = get_theme_colors()
    item_pad, header_pad = _INFO_TABLE_PADDING[kind]
    items = "" if item_pad is None else f"""
        QTableWidget::item {{ background-color: transparent; padding: {item_pad}; }}
        QTableWidget::item:selected {{
            background-color: {theme["primary"]}; color: {on_accent_ink(theme["primary"], theme["primary_text"])};
        }}"""
    return f"""
        QTableWidget {{
            background-color: {theme["secondary_dark"]};
            border: none; font-size: {scaled_area_px('tables')}px;
            gridline-color: {elevation_divider(DIVIDER_ALPHA_MATRIX)};
        }}{items}
        QHeaderView::section {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {elevation_color(2)}, stop:1 {elevation_color(1)}); color: {theme["secondary_text"]};
            border: 1px solid {theme["secondary_light"]};
            padding: {header_pad}; font-size: {scaled_area_px('table_headers')}px; font-weight: bold;
        }}
    """ + _THIN_SCROLLBAR_CSS


# Import highlight delegates
from apps.delegates import KarakaHighlightDelegate, StrengthHighlightDelegate, AspectHighlightDelegate, AvasthaHighlightDelegate, TajikaHighlightDelegate, RetinueColorDelegate

# Import fullscreen popup dialog
from apps.widgets.info_panel_dialog import open_panel_dialog
from apps.panels.strength_style_switch import StrengthTable
from apps.panels.table_metrics import column_header_height, table_row_height
from apps.widgets.panel_header import HeaderSwapButton, HeaderTab, PanelHeader, set_active_tab

# SPEC-SET-002 Phase 5: persist sub-panel tab selections (respects lock)
from managers.settings_manager import get_settings

# Panel width (set dynamically at runtime by create_right_panels)
INFO_PANEL_WIDTH = 380


def info_panel_width(widget=None):
    """Panel width scaled to screen resolution, minimum 380px.

    ``widget``: read the screen that widget is on (SPEC-LAYOUT-001 D1), else
    the primary screen (before the window exists)."""
    screen = widget.screen() if widget is not None else None
    screen = screen or QApplication.primaryScreen()
    if screen is None:
        return 380
    w = screen.availableGeometry().width()
    return max(380, min(480, int(w * 0.15)))

_THIN_SCROLLBAR_CSS = """
    QScrollBar:vertical {
        width: 4px;
        background: transparent;
    }
    QScrollBar::handle:vertical {
        background: rgba(128, 128, 128, 0.4);
        border-radius: 2px;
        min-height: 20px;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0px;
    }
"""


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


def _on_avastha_retinue_click(gui, row, col):
    """Open the retinue being description for a clicked SIGN/HORA/TRIMSAMSA cell.

    SPEC-AVA-001 §12.5 / D10: reuse the existing SectorInfoDialog description
    surface. Only the three retinue rows are actionable; matrix/TOTAL/POS/NEG
    clicks are ignored. All resolution lives in the controller.
    """
    ctrl = getattr(gui, 'avastha_controller', None)
    if ctrl is not None and hasattr(ctrl, 'open_retinue_dialog'):
        ctrl.open_retinue_dialog(row, col)


def _table_row_height(area_id='tables', padding=8, min_h=18):
    """Row height = effective font pixel size + padding, with a floor (table_metrics)."""
    return table_row_height(area_id, padding, min_h, px=scaled_area_px)


def _column_header_height():
    """Height for table column headers, scaled to table_headers font size (table_metrics)."""
    return column_header_height(px=scaled_area_px)


def _fit_column_header(table, height):
    """Column header height. A header that sizes itself from the font (the
    Strength keys, td-esl0r: its keys hold a full Table Headers label) re-fits;
    the others take the shared compact height."""
    header = table.horizontalHeader()
    fit = getattr(header, "fit_to_font", None)
    if callable(fit):
        fit()
    else:
        header.setFixedHeight(height)


def _stack_min_height(visible_rows, area_id='tables', padding=8,
                      min_h=18, header_h=32):
    """Minimum height = header + (visible_rows * row_height)."""
    row_h = _table_row_height(area_id, padding, min_h)
    return header_h + (visible_rows * row_h)


def _body_min_width():
    """Hard minimum width of a panel body (SPEC-LAYOUT-001 D2/D3): a small
    floor, so a narrow info column (INFO_MIN) squeezes the table columns
    instead of clipping the panel. The font-derived width a body needs to read
    well (``info_panel_stack.body_need_width``) decides the magazine layout."""
    return scaled_px(200)


def _avastha_row_height():
    """Row height for the Avastha table, scaled to table font size."""
    return max(18, scaled_area_px('tables') + 8)


def create_center_controllers(gui):
    """SPEC-VAC-001 §4.5: the Vedic and the Tajika center drawing controllers, owned by the
    center drawing registry only (W6 G1). Returns (vedic, tajika); idempotent. The Vedic
    one comes first so the Tajika toggle keeps its place right after the swap button; a
    rebuilt panel releases both and the mode sync first (the registry's stale check)."""
    from managers.settings_manager import get_settings
    from apps.widgets.panel_controllers.center_drawing_registry import ensure_center_controllers
    from apps.widgets.panel_controllers.tajika_center_controller import TajikaCenterController
    from apps.widgets.panel_controllers.vedic_center_controller import VedicCenterController
    return ensure_center_controllers(
        gui, (VedicCenterController, TajikaCenterController), get_settings())


def relayout_info_panels(gui):
    """Recalculate all structural dimensions after font/scale change.

    SPEC-LAYOUT-001 D3: body minimums are set HERE, inside the stack, never
    on the stack: no minimum height (the bodies scroll inside themselves, the
    InfoPanelStack splitter decides the heights) and a small width floor (a
    narrow column squeezes the table columns; the font-derived width that
    decides the magazine layout is info_panel_stack.body_need_width)."""
    tables = [
        (gui.karakas_table, 'tables', 19, 28),
        (gui.hora_table, 'tables', 11, 20),
        (gui.trimsamsa_table, 'tables', 11, 20),
        (gui.strength_table, 'tables', 19, 28),
        (gui.elements_table, 'tables', 44, 50),
        (gui.modality_table, 'tables', 64, 70),
        (gui.dignities_table, 'tables', 13, 22),   # td-m6xyo: inside the VARGA panel, scrolls
        (gui.aspects_table, 'tables', 15, 24),
        (gui.avastha_table, 'tables', 8, 18),
        (gui.tajika_matrix_table, 'tables', 11, 20),
        (gui.tajika_rel_table, 'tables', 13, 22),
    ]

    col_hdr_h = _column_header_height()
    body_w = _body_min_width()
    for table, area, pad, min_h in tables:
        if table is not None:
            row_h = _table_row_height(area, pad, min_h)
            table.verticalHeader().setDefaultSectionSize(row_h)
            _fit_column_header(table, col_hdr_h)
            table.setMinimumSize(body_w, 0)
            table.updateGeometry()

    from apps.widgets.panel_controllers.center_drawing_registry import center_controllers
    for center in center_controllers(gui):
        center.refresh_size()   # SPEC-TJK-003 / SPEC-VAC-001: the virupa rails follow the font

    for widget_name in ['shame_display', 'tajika_placeholder',
                        'exchange_display', 'nabhasa_display', 'house_graph_bars']:
        widget = getattr(gui, widget_name, None)
        if widget is not None:
            widget.setMinimumSize(body_w, 0)

    if hasattr(gui, 'house_graph_bars') and gui.house_graph_bars is not None:
        gui.house_graph_bars.updateGeometry()
        gui.house_graph_bars.update()

    for stack in [gui.karakas_stack, gui.strength_elements_stack,
                  gui.aspects_stack]:
        if stack is not None:
            stack.updateGeometry()

    # SPEC-PANELS-001 §2.6: the painted headers re-measure from the live font.
    from apps.widgets.panel_header import refresh_panel_headers
    refresh_panel_headers(gui)

    # td-m6xyo (R1 review F6): the VARGA panel bakes scaled_area_px into its
    # header / chip / key styles; a font or Display Scale change restyles it
    # with the tables (now when on screen, else just before it is next shown).
    from apps.panels.varga_panel import VargaPanel
    from managers.font_refresh_deferral import refresh_now_or_on_show
    stack = gui.strength_elements_stack
    for varga_panel in (stack.findChildren(VargaPanel) if stack is not None else ()):
        refresh_now_or_on_show(varga_panel, varga_panel.refresh_theme, gui)


def create_right_panels(gui):
    """
    Create right side panels (Karakas + Strength + Aspects stacked vertically).

    Args:
        gui: The parent ChartGUI instance (for list storage)

    Returns:
        QWidget: The combined panel widget
    """
    global INFO_PANEL_WIDTH
    INFO_PANEL_WIDTH = info_panel_width(gui)

    # Get theme colors for dynamic theming
    theme = get_theme_colors()

    from apps.widgets.info_panel_stack import InfoPanelStack
    panel = InfoPanelStack()   # SPEC-LAYOUT-001 frozen API (stream B fills it)
    panel.setFixedWidth(INFO_PANEL_WIDTH)
    panel.setStyleSheet(get_panel_style())


    # === KARAKAS / HORA / TRIMSAMSA PANEL (with inline tabs) ===
    karakas_frame = QWidget()
    karakas_frame.setStyleSheet(get_frame_style())
    gui.karakas_frame = karakas_frame  # Store for theme refresh
    karakas_layout = QVBoxLayout(karakas_frame)
    karakas_layout.setSpacing(2)
    karakas_layout.setContentsMargins(5, 5, 5, 5)

    # Header: SPEC-PANELS-001 §2.6 Inspector Underline (painted, theme-live)
    karakas_header = PanelHeader()
    gui.karakas_header = karakas_header
    karakas_header_layout = QHBoxLayout(karakas_header)
    karakas_header_layout.setContentsMargins(8, 0, 8, 0)

    gui.karakas_tab_btn = HeaderTab("Karakas")
    gui.karakas_tab_btn.set_active(True)
    karakas_header_layout.addWidget(gui.karakas_tab_btn)

    gui.hora_tab_btn = HeaderTab("Hora")
    karakas_header_layout.addWidget(gui.hora_tab_btn)

    gui.trimsamsa_tab_btn = HeaderTab("Trim")
    karakas_header_layout.addWidget(gui.trimsamsa_tab_btn)

    gui.graph_tab_btn = HeaderTab("Houses")
    karakas_header_layout.addWidget(gui.graph_tab_btn)

    # Swap button at the end (same position and widget in all three panels)
    gui.karakas_swap_btn = HeaderSwapButton()
    gui.karakas_swap_btn.setToolTip("Toggle enriched views: Karakas+/Condition")
    karakas_header_layout.addWidget(gui.karakas_swap_btn)

    karakas_header_layout.addStretch()
    karakas_layout.addWidget(karakas_header)

    # === STACKED WIDGET for Karakas/Hora/Trimsamsa ===
    gui.karakas_stack = QStackedWidget()

    # --- Shared table style ---
    _table_style = info_table_style("table")

    # Retinue table style — NO ::item rules so setBackground() works.
    # Qt's stylesheet engine takes total ownership of item painting when
    # ANY QTableWidget::item rule exists, even padding-only. BackgroundRole
    # from setBackground() is ignored. We must avoid ::item entirely.
    _retinue_table_style = info_table_style("retinue")

    # --- Page 0: Karakas Table (existing, unchanged) ---
    gui.karakas_table = QTableWidget()
    gui.karakas_table.setColumnCount(3)
    gui.karakas_table.setRowCount(7)
    gui.karakas_table.setHorizontalHeaderLabels(["Karaka", "Planet", "Cusp Lord"])
    gui.karakas_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    gui.karakas_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    gui.karakas_table.verticalHeader().setVisible(False)
    gui.karakas_table.setShowGrid(True)
    gui.karakas_table.setStyleSheet(_table_style)
    gui.karakas_table.setMinimumSize(_body_min_width(), 0)
    gui.karakas_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    gui.karakas_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
    gui.karakas_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
    gui.karakas_table.verticalHeader().setDefaultSectionSize(_table_row_height('tables', 19, 28))

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
    gui.hora_table.setMinimumSize(_body_min_width(), 0)
    gui.hora_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
    gui.hora_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
    gui.hora_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
    gui.hora_table.verticalHeader().setDefaultSectionSize(_table_row_height('tables', 11, 20))

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
    gui.trimsamsa_table.setMinimumSize(_body_min_width(), 0)
    gui.trimsamsa_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
    gui.trimsamsa_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
    gui.trimsamsa_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
    gui.trimsamsa_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
    gui.trimsamsa_table.verticalHeader().setDefaultSectionSize(_table_row_height('tables', 11, 20))

    gui.trimsamsa_delegate = RetinueColorDelegate(parent=gui.trimsamsa_table)
    gui.trimsamsa_table.setItemDelegate(gui.trimsamsa_delegate)

    _bind_panel_popup(gui.trimsamsa_table, lambda: open_panel_dialog(gui, "karakas"))
    gui.karakas_stack.addWidget(gui.trimsamsa_table)  # Index 2

    # --- Page 3: Houses/Condition nested stack ---
    gui.condition_inner_stack = QStackedWidget()

    # View 0: House Graph (default)
    from apps.widgets.panel_controllers.house_graph_controller import _HouseBarWidget
    gui.house_graph_bars = _HouseBarWidget(gui_ref=gui)
    gui.house_graph_bars.setMinimumSize(_body_min_width(), 0)
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

    def _sync_karakas_visibility(index):
        """td-7932: gate the 3 eager controllers of this stack (index 3 is the
        lazy planetary_condition). Persist-free.

        For index 3 the lazy planetary_condition is turned ON conditionally by
        switch_to_condition (it depends on the inner stack page), so we only
        turn it OFF here when leaving the Condition tab — otherwise it keeps
        recomputing while a sibling karakas page is shown."""
        for _i, _name in ((0, 'karakas_controller'), (1, 'hora_controller'),
                          (2, 'trimsamsa_controller')):
            _c = getattr(gui, _name, None)
            if _c is not None:
                _c.set_visible(_i == index)
        if index != 3:
            _pc = getattr(gui, 'planetary_condition_controller', None)
            if _pc is not None:
                _pc.set_visible(False)

    def _switch_tab(index, active_btn):
        gui.karakas_stack.setCurrentIndex(index)
        _sync_karakas_visibility(index)
        set_active_tab(_all_tab_btns(), active_btn)
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

    # td-7932: initial visibility (non-current eager controllers start hidden).
    _sync_karakas_visibility(gui.karakas_stack.currentIndex())

    # Single swap handler: toggles ALL enriched views at once
    gui._karakas_enriched_mode = False

    def _toggle_enriched():
        gui._karakas_enriched_mode = not gui._karakas_enriched_mode
        enriched = gui._karakas_enriched_mode
        gui.karakas_swap_btn.set_on(enriched)
        new_idx = 1 if enriched else 0
        gui.karakas_inner_stack.setCurrentIndex(new_idx)
        gui.condition_inner_stack.setCurrentIndex(new_idx)
        if enriched:
            if hasattr(gui, 'karakas_controller'):
                gui.karakas_controller._refresh()
            if hasattr(gui, '_ensure_controller'):
                gui._ensure_controller('planetary_condition')
                # td-7932: only VISIBLE when the Condition tab is actually the
                # shown karakas page. Enriched mode can be toggled while a sibling
                # karakas page (0/1/2) is current, and marking planetary_condition
                # visible there re-opens the hidden-recompute leak that
                # _sync_karakas_visibility closes (the two writers must agree).
                if hasattr(gui, 'planetary_condition_controller'):
                    _on_condition = gui.karakas_stack.currentIndex() == 3
                    gui.planetary_condition_controller.set_visible(_on_condition)
        if not enriched:
            if hasattr(gui, 'planetary_condition_controller'):
                gui.planetary_condition_controller.set_visible(False)
            if hasattr(gui, 'house_graph_bars'):
                gui.house_graph_bars.update()

    gui.karakas_swap_btn.clicked.connect(_toggle_enriched)
    gui._toggle_enriched = _toggle_enriched

    # Add small vertical space below
    karakas_layout.addSpacing(2)

    # === STRENGTH / ELEMENTS PANEL (with inline tabs) ===
    strength_frame = QWidget()
    strength_frame.setStyleSheet(get_frame_style())
    gui.strength_frame = strength_frame  # Store for theme refresh
    strength_layout = QVBoxLayout(strength_frame)
    strength_layout.setSpacing(2)
    strength_layout.setContentsMargins(5, 5, 5, 5)

    # Header: SPEC-PANELS-001 §2.6 Inspector Underline (painted, theme-live)
    strength_header = PanelHeader()
    gui.strength_header = strength_header
    strength_header_layout = QHBoxLayout(strength_header)
    strength_header_layout.setContentsMargins(8, 0, 8, 0)

    gui.strength_tab_btn = HeaderTab("Strength")
    gui.strength_tab_btn.set_active(True)
    strength_header_layout.addWidget(gui.strength_tab_btn)

    gui.elements_tab_btn = HeaderTab("Elem")
    strength_header_layout.addWidget(gui.elements_tab_btn)

    gui.modality_tab_btn = HeaderTab("Modes")            # Movable / Fixed / Dual
    strength_header_layout.addWidget(gui.modality_tab_btn)

    gui.dignities_tab_btn = HeaderTab("Varga")   # td-m6xyo: the one-varga VARGA panel
    strength_header_layout.addWidget(gui.dignities_tab_btn)

    # Strength header language toggle (Sanskrit ↔ English)
    gui._strength_english_mode = False  # False = Sanskrit (Digbala/Uccha/Chesta), True = English (Direction/Energy/Confidence)
    gui.strength_lang_btn = HeaderSwapButton()
    gui.strength_lang_btn.setToolTip("Toggle column headers: Sanskrit ↔ English")
    strength_header_layout.addWidget(gui.strength_lang_btn)

    strength_header_layout.addStretch()
    strength_layout.addWidget(strength_header)

    # === STACKED WIDGET for Strength/Elements tables ===
    gui.strength_elements_stack = QStackedWidget()

    # --- Page 0: Strength Table ---
    gui.strength_table = StrengthTable()   # td-9scg9: a QTableWidget with room for the switch
    gui.strength_table.setColumnCount(5)
    gui.strength_table.setRowCount(7)
    gui.strength_table.setHorizontalHeaderLabels(["Planet", "Digbala", "Uccha", "Chesta", "DUC Bala"])
    # Tooltips on column headers explaining the Sanskrit terms
    for col, tip in [(1, "Direction"), (2, "Energy"), (3, "Confidence")]:
        item = gui.strength_table.horizontalHeaderItem(col)
        if item:
            item.setToolTip(tip)
    from apps.widgets.panel_controllers.duc_method import follow_duc_tooltip
    follow_duc_tooltip(gui.strength_table)   # the formula follows strength.duc_method
    gui.strength_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    gui.strength_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    gui.strength_table.verticalHeader().setVisible(False)
    gui.strength_table.setShowGrid(True)
    table_style = info_table_style("table")
    gui.strength_table.setStyleSheet(table_style)
    gui.strength_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    gui.strength_table.verticalHeader().setDefaultSectionSize(_table_row_height('tables', 19, 28))

    # Apply highlight delegate for high-strength planets
    gui.strength_delegate = StrengthHighlightDelegate(parent=gui.strength_table)
    gui.strength_table.setItemDelegate(gui.strength_delegate)
    gui.strength_table.setMinimumSize(_body_min_width(), 0)
    # SPEC-RST-001 D-20: the strength headers are keys choosing the retinue strength
    # source (click on / off / switch; F10 and Settings light the same key); the lit
    # column's values sit on stones in the planet glow colours.
    from apps.panels.strength_source_keys import install_strength_source_keys
    install_strength_source_keys(gui.strength_table, gui)
    # SPEC-RST-001 D-22 (td-9scg9): the V1 | V2 switch below the last planet row.
    from apps.panels.strength_style_switch import install_strength_style_switch
    install_strength_style_switch(gui.strength_table, gui)

    _bind_panel_popup(gui.strength_table, lambda: open_panel_dialog(gui, "strength"))
    gui.strength_elements_stack.addWidget(gui.strength_table)  # Index 0

    # --- Page 1: Elements Table ---
    gui.elements_table = QTableWidget()
    gui.elements_table.setColumnCount(3)
    gui.elements_table.setRowCount(4)  # Fire, Earth, Air, Water
    gui.elements_table.setHorizontalHeaderLabels(["Element", "%", "Planets"])
    gui.elements_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    gui.elements_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    gui.elements_table.verticalHeader().setVisible(False)
    gui.elements_table.setShowGrid(True)
    gui.elements_table.setStyleSheet(table_style)
    gui.elements_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
    gui.elements_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
    gui.elements_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
    gui.elements_table.verticalHeader().setDefaultSectionSize(_table_row_height('tables', 44, 50))
    gui.elements_table.setMinimumSize(_body_min_width(), 0)
    gui.elements_delegate = StrengthHighlightDelegate(parent=gui.elements_table)
    gui.elements_table.setItemDelegate(gui.elements_delegate)

    _bind_panel_popup(gui.elements_table, lambda: open_panel_dialog(gui, "strength"))
    gui.strength_elements_stack.addWidget(gui.elements_table)  # Index 1

    # --- Page 2: Modality Table ---
    gui.modality_table = QTableWidget()
    gui.modality_table.setColumnCount(3)
    gui.modality_table.setRowCount(3)  # Moveable, Fixed, Dual
    gui.modality_table.setHorizontalHeaderLabels(["Modality", "%", "Planets"])
    gui.modality_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    gui.modality_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    gui.modality_table.verticalHeader().setVisible(False)
    gui.modality_table.setShowGrid(True)
    gui.modality_table.setStyleSheet(table_style)
    gui.modality_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
    gui.modality_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
    gui.modality_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
    gui.modality_table.verticalHeader().setDefaultSectionSize(_table_row_height('tables', 64, 70))
    gui.modality_table.setMinimumSize(_body_min_width(), 0)
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
    gui.dignities_table.verticalHeader().setDefaultSectionSize(_table_row_height('tables', 13, 22))
    gui.dignities_table.setMinimumSize(_body_min_width(), 0)
    from apps.widgets.panel_controllers.dignities_controller import DignityColorDelegate
    gui.dignities_table.setItemDelegate(DignityColorDelegate(parent=gui.dignities_table))

    _bind_panel_popup(gui.dignities_table, lambda: open_panel_dialog(gui, "strength"))
    # td-m6xyo (SPEC-DIG-001 §4.4): page 3 is the one-varga VARGA panel; the full
    # table lives inside it (its "All vargas" state) and feeds the expand dialog.
    from apps.panels.varga_panel import VargaPanel
    varga_panel = VargaPanel(gui, table=gui.dignities_table)
    if getattr(gui, "dignities_controller", None) is not None:
        gui.dignities_controller.attach_panel(varga_panel)
    _bind_panel_popup(varga_panel.list, lambda: open_panel_dialog(gui, "strength"))
    gui.strength_elements_stack.addWidget(varga_panel)  # Index 3

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
        _sync_strength_swap_on(index)

    def _sync_strength_swap_on(index=None):
        """The swap button is ON while the shown tab shows its alternate view:
        English headers (Strength), Yoga terms (Modes). On Varga it cycles a
        three-way style that Settings can also change, so it stays a plain
        button there (no ON state to go stale)."""
        if index is None:
            index = gui.strength_elements_stack.currentIndex()
        on = False
        if index == 0:
            on = bool(gui._strength_english_mode)
        elif index == 2:
            ctrl = getattr(gui, "modality_controller", None)
            on = bool(ctrl and ctrl.yoga_mode)
        gui.strength_lang_btn.set_on(on)

    def _sync_strength_visibility(index):
        """td-7932: gate the 4 eager controllers of this stack on visibility —
        only the shown one refreshes on chart changes; the hidden siblings defer
        (PanelControllerBase._is_visible) and drain on their next show. Persist-
        free so it is safe to call for initial visibility without clobbering the
        saved tab."""
        for _i, _name in ((0, 'strength_controller'), (1, 'elements_controller'),
                          (2, 'modality_controller'), (3, 'dignities_controller')):
            _c = getattr(gui, _name, None)
            if _c is not None:
                _c.set_visible(_i == index)

    def _switch_strength_tab(index, active_btn):
        gui.strength_elements_stack.setCurrentIndex(index)
        _sync_strength_visibility(index)
        set_active_tab(_all_strength_tabs(), active_btn)
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
            gui.strength_table.setHorizontalHeaderLabels(["Planet", "Direction", "Energy", "Confidence", "DUC Bala"])
            gui.strength_lang_btn.setToolTip("Switch to Sanskrit terms (Digbala / Uccha / Chesta)")
        else:
            gui.strength_table.setHorizontalHeaderLabels(["Planet", "Digbala", "Uccha", "Chesta", "DUC Bala"])
            gui.strength_lang_btn.setToolTip("Switch to English terms (Direction / Energy / Confidence)")
        for col, (sanskrit, english) in enumerate(
            [("Digbala", "Direction"), ("Uccha Bala", "Energy"), ("Chesta Bala", "Confidence")], start=1
        ):
            item = gui.strength_table.horizontalHeaderItem(col)
            if item:
                item.setToolTip(english if not gui._strength_english_mode else sanskrit)
        # DUC Bala is a proper name (Dig-Uccha-Chesta), same in both languages.
        # setHorizontalHeaderLabels rebuilt the header items, so re-apply its tooltip.
        from apps.widgets.panel_controllers.duc_method import apply_duc_tooltip
        apply_duc_tooltip(gui.strength_table)

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
        _sync_strength_swap_on(active_idx)

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

    # td-7932: initial visibility (non-current eager controllers start hidden).
    # Persist-free; startup restore later calls switch_to_*_tab for the saved
    # index, re-syncing through _switch_strength_tab.
    _sync_strength_visibility(gui.strength_elements_stack.currentIndex())

    # Add small vertical space below
    strength_layout.addSpacing(2)

    # === ASPECTS / AVASTHA / SHAME PANEL (with inline tabs) ===
    aspects_frame = QWidget()
    aspects_frame.setStyleSheet(get_frame_style())
    gui.aspects_frame = aspects_frame  # Store for theme refresh
    aspects_layout = QVBoxLayout(aspects_frame)
    aspects_layout.setSpacing(2)
    aspects_layout.setContentsMargins(5, 5, 5, 5)

    # Header: SPEC-PANELS-001 §2.6 Inspector Underline (painted, theme-live)
    aspects_header = PanelHeader()
    gui.aspects_header = aspects_header
    aspects_header_layout = QHBoxLayout(aspects_header)
    aspects_header_layout.setContentsMargins(8, 0, 8, 0)

    # Vedic/Tajika mode toggle button (ON = Tajika)
    gui._aspects_mode = "vedic"  # default mode
    gui.aspects_mode_btn = HeaderSwapButton()
    gui.aspects_mode_btn.setToolTip("Toggle: Vedic ↔ Tajika aspects")

    gui.aspects_tab_btn = HeaderTab("Aspects V")      # active by default
    gui.aspects_tab_btn.set_active(True)
    aspects_header_layout.addWidget(gui.aspects_tab_btn)

    gui.avastha_tab_btn = HeaderTab("Avastha")
    gui.avastha_tab_btn.setToolTip(
        "Avastha — click again to refine by strength: Duc / Dig / Uccha / Chesta")
    aspects_header_layout.addWidget(gui.avastha_tab_btn)

    gui.shame_tab_btn = HeaderTab("Shame")
    aspects_header_layout.addWidget(gui.shame_tab_btn)

    # Exchange tab button (Vedic-only, hidden in Tajika)
    gui.exchange_tab_btn = HeaderTab("Exch")
    aspects_header_layout.addWidget(gui.exchange_tab_btn)

    # "Nabhasa" tab — the 4th TAJIKA-row tab, to the right of the Tajika "Yogas"
    # (annual) tab, filling the empty space on that row. Hidden in Vedic mode
    # (which keeps its four tabs uncramped). The Nabhasa panel itself is a natal
    # calculation (aspects_stack Index 7); it is placed on the Tajika row only
    # because that row had the spare width. Distinct from the Tajika "Yogas"
    # feature (annual yogas, Index 5) which is untouched.
    gui.nabhasa_tab_btn = HeaderTab("Nabhasa")
    aspects_header_layout.addWidget(gui.nabhasa_tab_btn)
    # Vedic is the default mode -> the Nabhasa tab starts hidden (Tajika-only).
    gui.nabhasa_tab_btn.setVisible(False)

    aspects_header_layout.addWidget(gui.aspects_mode_btn)
    aspects_header_layout.addStretch()
    aspects_layout.addWidget(aspects_header)

    # === STACKED WIDGET for Aspects/Avastha/Shame ===
    gui.aspects_stack = QStackedWidget()

    # Common table style for aspects section
    aspects_table_style = info_table_style("aspects")

    # --- Page 0: Aspects Table (existing 7x9 matrix, unchanged) ---
    gui.aspects_table = QTableWidget()
    gui.aspects_table.setColumnCount(9)
    gui.aspects_table.setRowCount(7)
    gui.aspects_table.setHorizontalHeaderLabels(["Su", "Mo", "Ma", "Me", "Ju", "Ve", "Sa", "Ra", "Ke"])
    gui.aspects_table.setVerticalHeaderLabels(["☉Su", "☽Mo", "♂Ma*", "☿Me", "♃Ju*", "♀Ve", "♄Sa*"])
    gui.aspects_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    gui.aspects_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    gui.aspects_table.verticalHeader().setVisible(True)
    gui.aspects_table.setShowGrid(True)
    gui.aspects_table.setStyleSheet(aspects_table_style)
    for col in range(9):
        gui.aspects_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
    gui.aspects_table.verticalHeader().setDefaultSectionSize(_table_row_height('tables', 15, 24))
    gui.aspects_table.verticalHeader().setMinimumWidth(45)

    gui.aspects_delegate = AspectHighlightDelegate(parent=gui.aspects_table)
    gui.aspects_table.setItemDelegate(gui.aspects_delegate)
    gui.aspects_table.setMinimumSize(_body_min_width(), 0)

    _bind_panel_popup(gui.aspects_table, lambda: open_panel_dialog(gui, "aspects"))
    # SPEC-VAC-001 §4.4: the page holds the matrix and the virupa rail under it; the key
    # headers, the center toggle and their state come with VedicCenterController.
    from apps.panels.vedic_center_keys import VedicVirupaRail
    _vedic_page = QWidget()
    _vedic_page_layout = QVBoxLayout(_vedic_page)
    _vedic_page_layout.setContentsMargins(0, 0, 0, 0)
    _vedic_page_layout.setSpacing(2)
    _vedic_page_layout.addWidget(gui.aspects_table)
    _vedic_page_layout.addWidget(VedicVirupaRail(_vedic_page))
    gui.aspects_stack.addWidget(_vedic_page)  # Index 0

    # --- Page 1: Avastha Table (7x7 + TOTAL/POS/NEG/SIGN/HORA/TRIMSAMSA rows) ---
    # SPEC-AVA-001 §12.2 (rev4): 13 rows — matrix 0-6, TOTAL 7, POS 8, NEG 9,
    # SIGN 10, HORA 11, TRIMSAMSA 12.
    gui.avastha_table = QTableWidget()
    gui.avastha_table.setColumnCount(7)
    gui.avastha_table.setRowCount(13)  # 7 planets + TOTAL/POS/NEG + SIGN/HORA/TRIMSAMSA
    gui.avastha_table.setHorizontalHeaderLabels(["Su", "Mo", "Ma", "Me", "Ju", "Ve", "Sa"])
    gui.avastha_table.setVerticalHeaderLabels(
        ["☉Su", "☽Mo", "♂Ma*", "☿Me", "♃Ju*", "♀Ve", "♄Sa*",
         "TOTAL", "POS", "NEG", "SIGN", "HORA", "TRIM"])
    gui.avastha_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    gui.avastha_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    gui.avastha_table.verticalHeader().setVisible(True)
    gui.avastha_table.setShowGrid(True)
    gui.avastha_table.setStyleSheet(avastha_compact_table_style())
    for col in range(7):
        gui.avastha_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
    _av_rh = _avastha_row_height()
    gui.avastha_table.verticalHeader().setDefaultSectionSize(_av_rh)
    # 40 not 45 (rev3 display fix): "TOTAL" needs 37px + 1px padding; every px
    # saved here widens the 7 stretch columns for the dignity diagonals.
    gui.avastha_table.verticalHeader().setMinimumWidth(40)

    gui.avastha_delegate = AvasthaHighlightDelegate(parent=gui.avastha_table)
    gui.avastha_table.setItemDelegate(gui.avastha_delegate)
    # 13 rows (rev4). SPEC-LAYOUT-001 D3: the panel height comes from the
    # InfoPanelStack splitter (its "fit" snap and AUTO rule show every row);
    # below that the table scrolls inside itself. The room the 5-char dignity
    # diagonals ("MK105") need is in info_panel_stack.body_need_width.
    gui.avastha_table.setMinimumSize(_body_min_width(), 0)

    _bind_panel_popup(gui.avastha_table, lambda: open_panel_dialog(gui, "aspects"))
    # SPEC-AVA-001 §12.5: a single click on a SIGN / HORA / TRIMSAMSA cell opens
    # the being's Theme/Healthy/Afflicted description (the existing SectorInfoDialog
    # surface, SPEC-PLANET-PROFILE-001). Delegated to the controller so no business
    # logic lands here (Rule 4).
    gui.avastha_table.cellClicked.connect(
        lambda r, c: _on_avastha_retinue_click(gui, r, c))
    # Wrap table + legend so the dignity multipliers stay explained on screen
    # (SPEC-AVA-001 rev3: the fixed EX=60/MK=45/OH=30 values are no longer shown).
    # The stack page stays Index 1; switch_to_avastha addresses it by index only.
    _avastha_page = QWidget()
    _avastha_page_layout = QVBoxLayout(_avastha_page)
    _avastha_page_layout.setContentsMargins(0, 0, 0, 0)
    _avastha_page_layout.setSpacing(2)
    _avastha_page_layout.addWidget(gui.avastha_table)
    gui.avastha_legend = QLabel(
        "Diagonal: own strength × dignity (EX ×2, MK ×1.75, OH ×1.5). "
        "Avastha base 60, refined views use the bala.")
    gui.avastha_legend.setAlignment(Qt.AlignmentFlag.AlignCenter)
    gui.avastha_legend.setWordWrap(True)
    _avastha_page_layout.addWidget(gui.avastha_legend)
    gui.aspects_stack.addWidget(_avastha_page)  # Index 1

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
    gui.shame_display.setMinimumSize(_body_min_width(), 0)

    _bind_panel_popup(gui.shame_display, lambda: open_panel_dialog(gui, "aspects"))
    gui.aspects_stack.addWidget(gui.shame_display)  # Index 2

    # --- Page 3: Tajika Matrix (11x11 aspect table) ---
    gui.tajika_matrix_table = QTableWidget()
    gui.tajika_matrix_table.setColumnCount(11)
    gui.tajika_matrix_table.setRowCount(11)
    # Shared header list derived from the engine body order (td-n3h3.13);
    # never keep a local copy that can drift from the matrix lookups.
    from apps.widgets.tajika_grid_widget import TAJIKA_HEADERS
    gui.tajika_matrix_table.setHorizontalHeaderLabels(TAJIKA_HEADERS)
    gui.tajika_matrix_table.setVerticalHeaderLabels(TAJIKA_HEADERS)
    gui.tajika_matrix_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    gui.tajika_matrix_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    gui.tajika_matrix_table.verticalHeader().setVisible(True)
    gui.tajika_matrix_table.setShowGrid(True)
    gui.tajika_matrix_table.setStyleSheet(aspects_table_style)
    for col in range(11):
        gui.tajika_matrix_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
    gui.tajika_matrix_table.verticalHeader().setDefaultSectionSize(_table_row_height('tables', 11, 20))
    gui.tajika_matrix_table.verticalHeader().setMinimumWidth(30)

    gui.tajika_delegate = TajikaHighlightDelegate(parent=gui.tajika_matrix_table)
    gui.tajika_matrix_table.setItemDelegate(gui.tajika_delegate)
    gui.tajika_matrix_table.setMinimumSize(_body_min_width(), 0)

    _bind_panel_popup(gui.tajika_matrix_table, lambda: open_panel_dialog(gui, "aspects"))
    # SPEC-TJK-003 §4.4: the page holds the matrix and the virupa rail under it; the
    # key headers, the center toggle and their state come with TajikaCenterController.
    from apps.panels.tajika_center_keys import VirupaRail
    _tajika_page = QWidget()
    _tajika_page_layout = QVBoxLayout(_tajika_page)
    _tajika_page_layout.setContentsMargins(0, 0, 0, 0)
    _tajika_page_layout.setSpacing(2)
    _tajika_page_layout.addWidget(gui.tajika_matrix_table)
    _tajika_page_layout.addWidget(VirupaRail(_tajika_page))
    gui.aspects_stack.addWidget(_tajika_page)  # Index 3

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
    gui.tajika_rel_table.verticalHeader().setDefaultSectionSize(_table_row_height('tables', 13, 22))

    gui.tajika_rel_delegate = TajikaHighlightDelegate(parent=gui.tajika_rel_table)
    gui.tajika_rel_table.setItemDelegate(gui.tajika_rel_delegate)
    gui.tajika_rel_table.setMinimumSize(_body_min_width(), 0)

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
    gui.tajika_placeholder.setMinimumSize(_body_min_width(), 0)

    # No ZoomableContainer — QTextEdit has native scrolling
    gui.aspects_stack.addWidget(gui.tajika_placeholder)  # Index 5

    # --- Page 6: Exchange (Parivartana) + Final-Dispositor panel (Vedic only) ---
    # Real Qt card-stack widget (Solar-Dawn), replacing the old QTextBrowser. The
    # attr name `exchange_display` and the aspects_stack index 6 are preserved so
    # every existing call site (clear loop, switch_to_exchange, font-scale/theme
    # fan-out) keeps working (hardening H10). The widget self-themes via
    # refresh_theme(); it must NOT receive a QTextBrowser stylesheet (H2).
    from apps.widgets.parivartana_widget import ParivartanaWidget
    gui.exchange_display = ParivartanaWidget()
    gui.exchange_display.setMinimumSize(_body_min_width(), 0)

    # Double-click pop-out: _bind_panel_popup filters the widget AND its
    # viewport() if present; ParivartanaWidget.viewport() returns its inner
    # QScrollArea viewport so the gesture still fires over the cards (H7).
    _bind_panel_popup(gui.exchange_display, lambda: open_panel_dialog(gui, "aspects"))
    gui.aspects_stack.addWidget(gui.exchange_display)  # Index 6

    # --- Page 7: Nabhasa Yogas panel (Vedic only) ---
    # APPEND-ONLY: Index 0-6 above are load-bearing (switch_to_* setCurrentIndex,
    # startup restore, font/theme fan-out). The widget self-themes via
    # refresh_theme() (H2); it must NOT receive a QTextBrowser stylesheet.
    from apps.widgets.nabhasa_widget import NabhasaWidget
    gui.nabhasa_display = NabhasaWidget()
    gui.nabhasa_display.setMinimumSize(_body_min_width(), 0)
    _bind_panel_popup(gui.nabhasa_display, lambda: open_panel_dialog(gui, "aspects"))
    gui.aspects_stack.addWidget(gui.nabhasa_display)  # Index 7

    aspects_layout.addWidget(gui.aspects_stack)

    # === TAB SWITCHING LOGIC (mode-aware: Vedic / Tajika) ===

    # Helper to set tab button active/inactive styling
    def _set_tab_styles(active_idx):
        """Set tab button styles by row position (0-based). The two modes reuse the
        first three physical buttons; the 4th position differs:
          Vedic:  0=Aspects 1=Avastha 2=Shame 3=Exch
          Tajika: 0=Aspects Table 1=Relations 2=Yogas 3=Nabhasa
        """
        fourth = gui.nabhasa_tab_btn if gui._aspects_mode == "tajika" else gui.exchange_tab_btn
        btns = [gui.aspects_tab_btn, gui.avastha_tab_btn, gui.shame_tab_btn, fourth]
        set_active_tab([gui.aspects_tab_btn, gui.avastha_tab_btn, gui.shame_tab_btn,
                        gui.exchange_tab_btn, gui.nabhasa_tab_btn],
                       btns[active_idx] if 0 <= active_idx < len(btns) else None)

    def _sync_aspects_eager(active_idx):
        """td-7932: gate the EAGER members of aspects_stack — aspects (0) and the
        three deferred Tajika controllers (matrix 3 / relationships 4 / yogas 5).
        The lazy members (avastha/shame/interchange/nabhasa) are gated inline in
        each switch handler already; this covers the eager ones the same way.
        getattr-guarded — deferred Tajika controllers may not exist yet."""
        for _idx, _name in ((0, 'aspects_controller'),
                            (3, 'tajika_matrix_controller'),
                            (4, 'tajika_relationships_controller'),
                            (5, 'tajika_yogas_controller')):
            _c = getattr(gui, _name, None)
            if _c is not None:
                _c.set_visible(_idx == active_idx)

    # Vedic tab switches (indices 0-2)
    def switch_to_aspects():
        gui.aspects_stack.setCurrentIndex(0)
        _sync_aspects_eager(0)
        _set_tab_styles(0)
        if hasattr(gui, 'avastha_controller'):
            gui.avastha_controller.set_visible(False)
        if hasattr(gui, 'shame_controller'):
            gui.shame_controller.set_visible(False)
        if hasattr(gui, 'interchange_controller'):
            gui.interchange_controller.set_visible(False)
        if hasattr(gui, 'nabhasa_controller'):
            gui.nabhasa_controller.set_visible(False)

    def switch_to_avastha():
        gui.aspects_stack.setCurrentIndex(1)
        _sync_aspects_eager(1)
        _set_tab_styles(1)
        gui._ensure_controller('avastha')
        if hasattr(gui, 'avastha_controller'):
            gui.avastha_controller.set_visible(True)
        if hasattr(gui, 'shame_controller'):
            gui.shame_controller.set_visible(False)
        if hasattr(gui, 'interchange_controller'):
            gui.interchange_controller.set_visible(False)
        if hasattr(gui, 'nabhasa_controller'):
            gui.nabhasa_controller.set_visible(False)

    def switch_to_shame():
        gui.aspects_stack.setCurrentIndex(2)
        _sync_aspects_eager(2)
        _set_tab_styles(2)
        if hasattr(gui, 'avastha_controller'):
            gui.avastha_controller.set_visible(False)
        gui._ensure_controller('shame')
        if hasattr(gui, 'shame_controller'):
            gui.shame_controller.set_visible(True)
        if hasattr(gui, 'interchange_controller'):
            gui.interchange_controller.set_visible(False)
        if hasattr(gui, 'nabhasa_controller'):
            gui.nabhasa_controller.set_visible(False)

    def switch_to_exchange():
        gui.aspects_stack.setCurrentIndex(6)
        _sync_aspects_eager(6)
        _set_tab_styles(3)
        if hasattr(gui, 'avastha_controller'):
            gui.avastha_controller.set_visible(False)
        if hasattr(gui, 'shame_controller'):
            gui.shame_controller.set_visible(False)
        gui._ensure_controller('interchange')
        if hasattr(gui, 'interchange_controller'):
            gui.interchange_controller.set_visible(True)
        if hasattr(gui, 'nabhasa_controller'):
            gui.nabhasa_controller.set_visible(False)

    def switch_to_nabhasa():
        # 4th tab of the Tajika row (row position 3). Shows the natal Nabhasa panel.
        gui.aspects_stack.setCurrentIndex(7)
        _sync_aspects_eager(7)
        _set_tab_styles(3)
        if hasattr(gui, 'avastha_controller'):
            gui.avastha_controller.set_visible(False)
        if hasattr(gui, 'shame_controller'):
            gui.shame_controller.set_visible(False)
        if hasattr(gui, 'interchange_controller'):
            gui.interchange_controller.set_visible(False)
        gui._ensure_controller('nabhasa')
        if hasattr(gui, 'nabhasa_controller'):
            gui.nabhasa_controller.set_visible(True)

    # Tajika tab switches (indices 3-5)
    def switch_to_tajika_matrix():
        gui.aspects_stack.setCurrentIndex(3)
        _set_tab_styles(0)
        gui._ensure_controller('tajika_matrix')
        _sync_aspects_eager(3)
        if hasattr(gui, 'avastha_controller'):
            gui.avastha_controller.set_visible(False)
        if hasattr(gui, 'shame_controller'):
            gui.shame_controller.set_visible(False)
        if hasattr(gui, 'interchange_controller'):
            gui.interchange_controller.set_visible(False)
        if hasattr(gui, 'nabhasa_controller'):
            gui.nabhasa_controller.set_visible(False)

    def switch_to_tajika_relationships():
        gui.aspects_stack.setCurrentIndex(4)
        _set_tab_styles(1)
        gui._ensure_controller('tajika_relationships')
        _sync_aspects_eager(4)
        if hasattr(gui, 'avastha_controller'):
            gui.avastha_controller.set_visible(False)
        if hasattr(gui, 'shame_controller'):
            gui.shame_controller.set_visible(False)
        if hasattr(gui, 'interchange_controller'):
            gui.interchange_controller.set_visible(False)
        if hasattr(gui, 'nabhasa_controller'):
            gui.nabhasa_controller.set_visible(False)

    def switch_to_tajika_placeholder():
        gui.aspects_stack.setCurrentIndex(5)
        _set_tab_styles(2)
        gui._ensure_controller('tajika_yogas')
        _sync_aspects_eager(5)
        if hasattr(gui, 'avastha_controller'):
            gui.avastha_controller.set_visible(False)
        if hasattr(gui, 'shame_controller'):
            gui.shame_controller.set_visible(False)
        if hasattr(gui, 'interchange_controller'):
            gui.interchange_controller.set_visible(False)
        if hasattr(gui, 'nabhasa_controller'):
            gui.nabhasa_controller.set_visible(False)

    # Mode-aware tab button handlers
    def on_tab1_click():
        if gui._aspects_mode == "vedic":
            switch_to_aspects()
        else:
            switch_to_tajika_matrix()
        get_settings().persist_runtime_change("ui.panel.aspects_tab", 0)

    def on_tab2_click():
        if gui._aspects_mode == "vedic":
            # SPEC-AVA-001: if the Avastha panel is ALREADY showing (stack index
            # 1), clicking the tab cycles the refined views instead of re-selecting
            # it. Otherwise select it at whatever view is active. Tajika branch
            # (Relations) is untouched.
            already_avastha = (gui.aspects_stack.currentIndex() == 1
                               and hasattr(gui, 'avastha_controller'))
            if already_avastha:
                gui.avastha_controller.cycle_view()
                gui.avastha_controller.refresh_view()   # single refresh (pre-mortem #6)
                gui.avastha_tab_btn.setText(gui.avastha_controller.view_label())
            else:
                switch_to_avastha()
                if hasattr(gui, 'avastha_controller'):
                    gui.avastha_tab_btn.setText(gui.avastha_controller.view_label())
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

    def on_tab_nabhasa():
        # Nabhasa is the 4th Tajika-row tab (row position 3); Vedic mode never
        # shows this button.
        if gui._aspects_mode == "tajika":
            switch_to_nabhasa()
            get_settings().persist_runtime_change("ui.panel.aspects_tab", 3)

    gui.aspects_tab_btn.clicked.connect(on_tab1_click)
    gui.avastha_tab_btn.clicked.connect(on_tab2_click)
    gui.shame_tab_btn.clicked.connect(on_tab3_click)
    gui.exchange_tab_btn.clicked.connect(on_tab4_click)
    gui.nabhasa_tab_btn.clicked.connect(on_tab_nabhasa)

    # Toggle between Vedic and Tajika modes
    def toggle_aspects_mode():
        if gui._aspects_mode == "vedic":
            gui._aspects_mode = "tajika"
            gui.aspects_tab_btn.setText("Aspects T")
            gui.avastha_tab_btn.setText("Relations")
            # SPEC-AVA-001: the refine-cycle only exists in Vedic; in Tajika this
            # button just selects Relations, so drop the misleading cycle tooltip.
            gui.avastha_tab_btn.setToolTip("Tajika planetary relationships")
            gui.shame_tab_btn.setText("Yogas")
            gui.exchange_tab_btn.setVisible(False)
            # Tajika row: reveal the 4th "Nabhasa" tab (Vedic hides it).
            gui.nabhasa_tab_btn.setVisible(True)
            gui.aspects_mode_btn.set_on(True)
            switch_to_tajika_matrix()
        else:
            gui._aspects_mode = "vedic"
            gui.aspects_tab_btn.setText("Aspects V")
            # SPEC-AVA-001: restore the avastha button label to the session's
            # active refined view (Duc/Dig/...), not a hardcoded "Avastha".
            if hasattr(gui, 'avastha_controller'):
                gui.avastha_tab_btn.setText(gui.avastha_controller.view_label())
            else:
                gui.avastha_tab_btn.setText("Avastha")
            gui.avastha_tab_btn.setToolTip(
                "Avastha — click again to refine by strength: Duc / Dig / Uccha / Chesta")
            gui.shame_tab_btn.setText("Shame")
            gui.exchange_tab_btn.setVisible(True)
            # Vedic row keeps four tabs; the Nabhasa tab is Tajika-only.
            gui.nabhasa_tab_btn.setVisible(False)
            gui.aspects_mode_btn.set_on(False)
            switch_to_aspects()
        # Toggling mode jumps to the first tab of the new mode.
        get_settings().persist_runtime_change("ui.panel.aspects_mode", gui._aspects_mode)
        get_settings().persist_runtime_change("ui.panel.aspects_tab", 0)

    gui.aspects_mode_btn.clicked.connect(toggle_aspects_mode)
    # SPEC-TJK-003 / SPEC-VAC-001: the center drawings' toggles, keys and rails (needs
    # the main window)
    if callable(getattr(gui, "_ensure_controller", None)):
        create_center_controllers(gui)

    # Store switch functions for external use
    gui.switch_to_aspects_tab = switch_to_aspects
    gui.switch_to_avastha_tab = switch_to_avastha
    gui.switch_to_shame_tab = switch_to_shame
    gui.switch_to_exchange_tab = switch_to_exchange
    gui.switch_to_nabhasa_tab = switch_to_nabhasa
    gui.switch_to_tajika_matrix_tab = switch_to_tajika_matrix
    gui.switch_to_tajika_relationships_tab = switch_to_tajika_relationships
    gui.switch_to_tajika_yogas_tab = switch_to_tajika_placeholder

    # td-7932 boot sync: seed the eager members' _is_visible to match the stack's
    # initial page (persist-free — startup restore fires the real switch handlers
    # later). At boot only aspects_controller (0) exists; the deferred Tajika
    # controllers are created on first switch, so this just hides/shows index 0.
    _sync_aspects_eager(gui.aspects_stack.currentIndex())

    # Add small spacing below
    aspects_layout.addSpacing(2)

    # === COLUMN HEADER HEIGHTS (compact, font-scaled) ===
    col_hdr_h = _column_header_height()
    for tbl in [gui.karakas_table, gui.hora_table, gui.trimsamsa_table,
                gui.strength_table, gui.elements_table, gui.modality_table,
                gui.dignities_table, gui.aspects_table, gui.avastha_table,
                gui.tajika_matrix_table, gui.tajika_rel_table]:
        if tbl is not None:
            _fit_column_header(tbl, col_hdr_h)

    # === DOUBLE-CLICK FULLSCREEN POPUP (also on headers + frame backgrounds) ===
    # No sub-tab argument here on purpose: open_panel_dialog resolves the live
    # sub-tab itself (SPEC-AVA-002 §4.1), so the six call sites cannot drift out
    # of step with each other or with a newly added tab.
    karakas_frame.mouseDoubleClickEvent = lambda e: open_panel_dialog(gui, "karakas")
    karakas_header.mouseDoubleClickEvent = lambda e: open_panel_dialog(gui, "karakas")
    strength_frame.mouseDoubleClickEvent = lambda e: open_panel_dialog(gui, "strength")
    strength_header.mouseDoubleClickEvent = lambda e: open_panel_dialog(gui, "strength")
    aspects_frame.mouseDoubleClickEvent = lambda e: open_panel_dialog(gui, "aspects")
    aspects_header.mouseDoubleClickEvent = lambda e: open_panel_dialog(gui, "aspects")

    # The gesture was undiscoverable — no tooltip, no cursor change, nothing
    # (SPEC-AVA-002 §4.2 / D-1). Headers get a pointing hand so they read as
    # clickable, and say what the expanded view is worth opening for.
    _EXPAND_HINTS = (
        (karakas_header, "Double-click to expand — the full page adds the "
                         "enriched karakas and the planetary condition"),
        (strength_header, "Double-click to expand — the full page shows every "
                          "strength table side by side"),
        (aspects_header, "Double-click to expand — the full Avastha table adds "
                         "each planet's CAST totals (what it sends out) beside "
                         "the received totals it already shows"),
    )
    for _hdr, _tip in _EXPAND_HINTS:
        if _hdr is not None:
            _hdr.setToolTip(_tip)
            _hdr.setCursor(Qt.CursorShape.PointingHandCursor)

    # SPEC-LAYOUT-001 stream B: the stack places the three frames (splitter,
    # folds, magazine layout); their names, stacks and sub-tab indices stay.
    panel.attach_panels(gui, {
        "karakas": (karakas_frame, karakas_header, gui.karakas_stack),
        "strength": (strength_frame, strength_header, gui.strength_elements_stack),
        "bottom": (aspects_frame, aspects_header, gui.aspects_stack),
    })
    return panel
