#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Info Panel Dialog — Fullscreen popup showing all sub-tables side by side.

Double-click any info panel frame to open this dialog at ~90% screen size.
Tables are cloned (not reparented) so the main window stays intact.
Delegate colors are baked into cloned cells (bg + fg on QTableWidgetItem).
Includes "Copy All as JSON" for AI consumption.
"""
import json

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QHeaderView, QPushButton, QTextEdit,
    QApplication, QSplitter, QWidget, QFrame
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QColor, QBrush

from ui.qt_theme import (
    BG, SURFACE, TEXT_PRIMARY, TEXT_SECONDARY, BORDER, TEXT_TERTIARY,
    get_theme_colors, get_secondary_button_style, is_light_theme,
    scaled_area_px, scaled_area_size, scaled_area_font, FONT_MONO
)


# Section registry: section_key -> list of (gui_attr_name, display_label)
SECTION_DEFS = {
    "karakas": [("karakas_table", "Karakas"), ("karakas_enriched", "Karakas+"), ("hora_table", "Hora"), ("trimsamsa_table", "Trimsamsa"), ("house_graph_bars", "Graph"), ("planet_profiles", "Planetary Condition")],
    "strength": [
        ("strength_table", "Strength"), ("elements_table", "Elements"),
        ("modality_table", "Modality"), ("dignities_table", "Dignities in Vargas"),
    ],
    "aspects": [
        ("aspects_table", "Aspects"), ("avastha_table", "Avastha"), ("shame_display", "Shame"),
        ("tajika_matrix_table", "Tajika Aspects"), ("tajika_rel_table", "Tajika Relations"),
        ("tajika_placeholder", "Tajika Yogas"), ("exchange_display", "Exchange Yogas"),
    ],
}

# Map gui attribute -> delegate attribute for color extraction
DELEGATE_MAP = {
    "karakas_table": "karakas_delegate",
    "strength_table": "strength_delegate",
    "elements_table": "elements_delegate",
    "modality_table": "modality_delegate",
    "aspects_table": "aspects_delegate",
    "avastha_table": "avastha_delegate",
    "tajika_matrix_table": "tajika_delegate",
    "tajika_rel_table": "tajika_rel_delegate",
}


# SPEC-AVA-002 §4.1 — live sub-tab -> the gui attribute it displays.
#
# THE TRAP: these are NOT page indices and must never be used as such. A section's
# live QStackedWidget indices and its SECTION_DEFS page positions line up for
# `aspects` and `strength` by coincidence only; `karakas` does not line up at all,
# because two of its four stack entries are themselves inner stacks that each
# expand into two dialog pages (its Hora tab is stack index 1 but page 2). Resolve
# stack index -> ATTRIBUTE NAME here, then let the dialog look the attribute up in
# SECTION_DEFS. An index->index map would be right for two sections out of three
# and would rot silently the first time a tab is inserted.
#
# A stack index with no dialog page maps to None (aspects index 7 is Nabhasa,
# which has no page today) and the dialog falls back to page 0.
_SUBTAB_ATTRS = {
    "aspects": {
        0: "aspects_table", 1: "avastha_table", 2: "shame_display",
        3: "tajika_matrix_table", 4: "tajika_rel_table",
        5: "tajika_placeholder", 6: "exchange_display", 7: None,
    },
    "strength": {
        0: "strength_table", 1: "elements_table",
        2: "modality_table", 3: "dignities_table",
    },
    # karakas entries 0 and 3 are inner stacks: (inner_stack_attr, {inner index: attr})
    "karakas": {
        0: ("karakas_inner_stack", {0: "karakas_table", 1: "karakas_enriched"}),
        1: "hora_table",
        2: "trimsamsa_table",
        3: ("condition_inner_stack", {0: "house_graph_bars", 1: "planet_profiles"}),
    },
}

# SPEC-THM-002 D-4: tables where the GRID is doing real work — on a 7x7 or an
# 11x11 the gridline is what lets the eye track a row across to its column, so
# these keep a stronger hairline than the list-like tables.
_MATRIX_TABLES = {"avastha_table", "tajika_matrix_table", "tajika_rel_table",
                  "aspects_table"}

_SECTION_STACKS = {
    "aspects": "aspects_stack",
    "karakas": "karakas_stack",
    "strength": "strength_elements_stack",
}


def current_subtab_attr(gui, section_key):
    """The gui attribute name of the sub-tab currently showing in ``section_key``.

    Returns None when it cannot be resolved (missing stack, unknown index, or a
    tab with no dialog page), which the dialog treats as "open on page 0" — the
    pre-SPEC-AVA-002 behaviour, so a new tab can never crash the popup.
    """
    stack = getattr(gui, _SECTION_STACKS.get(section_key, ""), None)
    if stack is None:
        return None
    entry = _SUBTAB_ATTRS.get(section_key, {}).get(stack.currentIndex())
    if isinstance(entry, tuple):
        inner_attr, inner_map = entry
        inner = getattr(gui, inner_attr, None)
        if inner is None:
            return None
        return inner_map.get(inner.currentIndex())
    return entry


def _get_delegate_colors(gui, attr_name, row, col):
    """Read bg/fg colors from the delegate's state for a given cell.

    Returns (bg_hex, fg_hex) or (None, None) if no special coloring.
    """
    delegate_attr = DELEGATE_MAP.get(attr_name)
    if not delegate_attr:
        return None, None

    delegate = getattr(gui, delegate_attr, None)
    if delegate is None:
        return None, None

    theme = get_theme_colors()

    # AvasthaHighlightDelegate: per-cell category coloring
    if hasattr(delegate, 'cell_categories'):
        cat = delegate.cell_categories.get((row, col))
        # The delegate exposes its palette as get_category_colors() (theme-aware),
        # over a CATEGORY_COLORS_MAP class attribute. This branch used to test for
        # a bare `CATEGORY_COLORS`, which exists nowhere in the repo, so it always
        # fell through to (None, None) and cloned avastha tables got no baked
        # colours — invisible only because _attach_avastha_delegate re-attaches a
        # live delegate straight afterwards (SPEC-AVA-002 §4.7).
        if cat and hasattr(delegate, 'get_category_colors'):
            return delegate.get_category_colors().get(cat, (None, None))
        return None, None

    # KarakaHighlightDelegate: highlight_rows (entire row)
    if hasattr(delegate, 'highlight_rows') and not hasattr(delegate, 'highlight_cells'):
        if row in delegate.highlight_rows:
            return theme["secondary_light"], theme["secondary_text"]
        return None, None

    # StrengthHighlightDelegate / AspectHighlightDelegate: highlight_cells
    if hasattr(delegate, 'highlight_cells'):
        if (row, col) in delegate.highlight_cells:
            return theme["secondary_light"], theme["secondary_text"]
        return None, None

    return None, None


# SPEC-AVW-001 T1: the avastha totals math now lives in the pure, GUI-free
# core.avastha_totals module (shared by the desktop GUI, the FastAPI backend, and
# the show_avastha CLI). Re-exported here so existing importers of
# `from apps.widgets.info_panel_dialog import split_expression, _AVASTHA_7` keep working.
from ui.themed_style import ThemedStyleMixin
from ui.qt_theme import (
    elevation_color, elevation_surface_style, elevation_table_style,
    elevation_divider, apply_elevation_shadow, elevation_margin,
)

from core.avastha_totals import (  # noqa: F401
    split_expression, SELF_BASE, dignity_multiplier, AVASTHA_7 as _AVASTHA_7,
)


class InfoPanelDialog(ThemedStyleMixin, QDialog):
    """Near-fullscreen dialog showing all sub-tables of a section side by side."""

    def __init__(self, gui, section_key, parent=None, initial_attr=None):
        super().__init__(parent or gui)
        self.gui = gui
        self.section_key = section_key
        self.section_items = SECTION_DEFS.get(section_key, [])
        # SPEC-AVA-002 §4.1: the gui attribute the user was looking at when they
        # double-clicked, so the dialog opens on THAT page instead of page 0.
        # None (or an attribute with no page, e.g. Nabhasa) falls back to 0.
        self._initial_attr = initial_attr
        self._page_attrs = []

        self._setup_ui()

    def refresh_theme(self):
        """Re-theme a dialog that is open while the theme changes.

        SPEC-THM-002 §6.4. Before this the dialog simply went stale: it is
        non-modal and long-lived, has no refresh path of its own, and was absent
        from core_gui_qt._on_theme_changed's fan-out, so changing theme with a
        popup open left it painted in the old palette until it was closed.

        AS-BUILT DEVIATION from §6.4.2, deliberate. The spec asks for all 28
        setStyleSheet call sites in this file to be converted to
        _register_themed. This rebuilds the UI instead and restores the page.
        The reason is the failure mode: a missed conversion is SILENT, and 28
        sites is 28 chances to miss one now plus one more every time somebody
        adds a widget. A rebuild covers every site by construction and cannot
        rot. Construction here is milliseconds (it clones already-populated
        tables), and a theme switch is a rare, user-initiated event.

        _register_themed / _register_themed_effect are still used for the
        elevation surfaces, because those must also survive the rebuild path
        used by any future partial refresh.
        """
        page = None
        if hasattr(self, "_page_stack") and self._page_stack is not None:
            try:
                idx = self._page_stack.currentIndex()
                if 0 <= idx < len(self._page_attrs):
                    page = self._page_attrs[idx]
            except RuntimeError:
                page = None      # C++ side already gone
        if page is None:
            page = self._initial_attr
        self._initial_attr = page

        # Drop the old tree. Re-parenting the layout onto a throwaway widget is
        # the supported way to destroy a layout AND its children together —
        # deleting widgets one by one here races the pending paint events.
        old = self.layout()
        if old is not None:
            QWidget().setLayout(old)
        self.__dict__["_themed_registry"] = []
        self.__dict__["_themed_effect_registry"] = []
        self._page_attrs = []

        self._setup_ui()

    def _setup_ui(self):
        theme = get_theme_colors()

        # Window setup — 90% of screen
        self.setWindowTitle(self.section_key.upper())
        screen = QApplication.primaryScreen()
        if screen:
            geom = screen.availableGeometry()
            w = int(geom.width() * 0.9)
            h = int(geom.height() * 0.9)
            self.resize(w, h)
            self.move(
                geom.x() + (geom.width() - w) // 2,
                geom.y() + (geom.height() - h) // 2,
            )

        self.setModal(False)
        # SPEC-THM-001 G05: live theme colors (were frozen BG / TEXT_PRIMARY).
        # SPEC-THM-002 W1: the dialog is elevation level 0, the page everything
        # else sits above. Same value as the old secondary_dark by construction
        # (K[0] == 0.0), so this changes nothing on its own — it just puts the
        # page on the ramp so the containers above it have something to rise from.
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {elevation_color(0)};
                color: {theme['secondary_text']};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Title
        title = QLabel(self.section_key.upper())
        title.setFont(scaled_area_font('panel_titles', family="Inter", bold=True))
        title.setStyleSheet(f"color: {theme['primary']};")
        title.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(title)

        # Build the panel widgets first; layout differs by section.
        panels = []  # list of (label, widget)
        self._page_attrs = []  # parallel to `panels`: the gui attr each page shows
        for attr_name, label in self.section_items:
            widget = self._build_section_widget(attr_name)
            if widget is not None:
                panels.append((label, widget))
                self._page_attrs.append(attr_name)

        if self.section_key in ("aspects", "karakas"):
            # Too many panels for side-by-side — show ONE full-width
            # panel at a time with arrow/chip navigation.
            layout.addWidget(self._build_paged_area(panels), stretch=1)
        else:
            # Splitter for side-by-side tables
            splitter = QSplitter(Qt.Orientation.Horizontal)
            # SPEC-THM-001 G05: live theme color for splitter handle.
            splitter.setStyleSheet(f"""
                QSplitter::handle {{
                    background-color: {theme['secondary_light']};
                    width: 3px;
                }}
            """)

            for label, widget in panels:
                # SPEC-THM-002 W1 E1/E3: each side-by-side panel is an elevated
                # container at level 2 ("card"), not a bare transparent QWidget.
                # Level 2 rather than 1 because the T-3 probe measured level 1 at
                # only +4.0 against the page on a LIGHT theme — the whole light
                # ramp spans 12 points across three steps, so one adjacent step
                # can never clear the spec's own 5.0 floor. These containers ARE
                # cards, which is what level 2 is named; it gives +8.0 on light
                # and +12.4 on dark. WA_StyledBackground
                # is required (INV-7) — a plain QWidget subclass ignores a
                # background rule without it and the lift would silently no-op.
                container = QFrame()
                container.setObjectName("elevPanel")
                container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
                self._register_themed(
                    container,
                    lambda: elevation_surface_style("QFrame#elevPanel", 2))
                self._register_themed_effect(
                    container, lambda w: apply_elevation_shadow(w, 2))
                _pad = 4 + elevation_margin(2)
                container_layout = QVBoxLayout(container)
                container_layout.setContentsMargins(_pad, _pad, _pad, _pad)
                container_layout.setSpacing(4)

                sub_label = QLabel(label)
                sub_label.setFont(scaled_area_font('table_headers', family="Inter", bold=True))
                # SPEC-THM-001 G05: live theme color (was frozen TEXT_SECONDARY).
                sub_label.setStyleSheet(f"color: {theme['secondary_text']};")
                container_layout.addWidget(sub_label)
                container_layout.addWidget(widget)
                splitter.addWidget(container)

            if self.section_key == "strength":
                # Dignities matrix (8 cols) needs the most width
                splitter.setSizes([240, 260, 280, 420])

            layout.addWidget(splitter, stretch=1)

        # Being type legend for karakas popup
        if self.section_key == "karakas":
            legend = self._build_being_legend()
            if legend:
                layout.addWidget(legend)

        # Dignity code legend for strength popup
        if self.section_key == "strength":
            legend = self._build_dignity_legend()
            if legend:
                layout.addWidget(legend)

        # Bottom buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.copy_btn = QPushButton("Copy All as JSON")
        self.copy_btn.setStyleSheet(get_secondary_button_style())
        self.copy_btn.setMinimumWidth(160)
        self.copy_btn.clicked.connect(self._copy_json)
        btn_layout.addWidget(self.copy_btn)

        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(get_secondary_button_style())
        close_btn.setMinimumWidth(80)
        close_btn.clicked.connect(self.close)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

    def _build_section_widget(self, attr_name):
        """Build the popup widget for one section item (enhanced or cloned).

        Returns None if the source widget is missing or the builder fails.
        Virtual widgets (no gui attribute) are handled first.
        """
        # Virtual widgets: computed from chart data, no source widget on gui
        if attr_name == "planet_profiles":
            return self._build_popup_planet_profiles()
        if attr_name == "karakas_enriched":
            return self._build_popup_karakas_enriched()

        source_widget = getattr(self.gui, attr_name, None)
        if source_widget is None:
            return None

        # Enhanced builders (recompute or recolor for the popup)
        if self.section_key == "karakas":
            if attr_name == "karakas_table":
                return self._build_popup_karakas_table(source_widget)
            if attr_name == "hora_table":
                return self._build_popup_hora_table()
            if attr_name == "trimsamsa_table":
                return self._build_popup_trimsamsa_table()
            if attr_name == "house_graph_bars":
                return self._build_popup_graph()
        elif self.section_key == "strength":
            if attr_name == "strength_table":
                return self._build_popup_strength_table(source_widget)
            if attr_name == "elements_table":
                return self._build_popup_elements_table(source_widget)
            if attr_name == "modality_table":
                return self._build_popup_modality_table(source_widget)
            if attr_name == "dignities_table":
                return self._build_popup_dignities_table(source_widget)
        elif self.section_key == "aspects":
            if attr_name == "aspects_table":
                return self._build_popup_aspects_table(source_widget)
            if attr_name == "avastha_table":
                # SPEC-AVA-002 §4.5: not a clone of the cramped panel table —
                # a page built for the width, carrying the cast band the panel
                # has no room for.
                from apps.widgets.avastha_fullscreen import AvasthaFullscreenPage
                return AvasthaFullscreenPage(self.gui, parent=self)
            if attr_name == "exchange_display":
                return self._build_popup_exchange_display(source_widget)

        # Generic clones
        if isinstance(source_widget, QTableWidget):
            clone = self._clone_table(source_widget, attr_name)
            # Attach delegates to cloned tables for proper color rendering
            if attr_name in ("tajika_matrix_table", "tajika_rel_table"):
                self._attach_tajika_delegate(clone, attr_name)
            elif attr_name == "avastha_table":
                self._attach_avastha_delegate(clone)
            return clone
        if isinstance(source_widget, QTextEdit):
            return self._clone_textedit(source_widget)
        return None

    # ── Paged layout (aspects section) ─────────────────────────────

    def _build_paged_area(self, panels):
        """One full-width panel per page, with arrows + name chips to switch."""
        from PySide6.QtWidgets import QStackedWidget

        theme = get_theme_colors()
        area = QWidget()
        area_layout = QVBoxLayout(area)
        area_layout.setContentsMargins(0, 0, 0, 0)
        area_layout.setSpacing(8)

        # Navigation bar: ◀  [chip][chip]…  ▶
        nav = QWidget()
        nav_layout = QHBoxLayout(nav)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(6)

        arrow_style = f"""
            QPushButton {{
                background-color: {theme['secondary']};
                color: {theme['secondary_text']};
                border: 1px solid {theme['secondary_light']};
                border-radius: 6px;
                font-size: {scaled_area_px('table_headers')}px;
                font-weight: bold;
                padding: 6px 18px;
            }}
            QPushButton:hover {{
                background-color: {theme['primary']};
                color: {theme['primary_text']};
            }}
        """

        prev_btn = QPushButton("◀")
        prev_btn.setStyleSheet(arrow_style)
        prev_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        nav_layout.addWidget(prev_btn)
        nav_layout.addStretch()

        self._page_chips = []
        for i, (label, _) in enumerate(panels):
            chip = QPushButton(label)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.clicked.connect(lambda _checked=False, idx=i: self._set_page(idx))
            nav_layout.addWidget(chip)
            self._page_chips.append(chip)

        nav_layout.addStretch()
        next_btn = QPushButton("▶")
        next_btn.setStyleSheet(arrow_style)
        next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        nav_layout.addWidget(next_btn)

        area_layout.addWidget(nav)

        self._page_stack = QStackedWidget()
        for _, widget in panels:
            self._page_stack.addWidget(widget)

        # SPEC-THM-002 W1: the stack rides inside an elevated container so the
        # page reads as a card on the dialog rather than as one flat expanse.
        page_frame = QFrame()
        page_frame.setObjectName("elevPage")
        page_frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._register_themed(
            page_frame, lambda: elevation_surface_style("QFrame#elevPage", 2))
        self._register_themed_effect(
            page_frame, lambda w: apply_elevation_shadow(w, 2))
        _pad = 6 + elevation_margin(2)
        frame_layout = QVBoxLayout(page_frame)
        frame_layout.setContentsMargins(_pad, _pad, _pad, _pad)
        frame_layout.addWidget(self._page_stack)
        area_layout.addWidget(page_frame, stretch=1)

        n = len(panels)
        prev_btn.clicked.connect(
            lambda: self._set_page((self._page_stack.currentIndex() - 1) % n))
        next_btn.clicked.connect(
            lambda: self._set_page((self._page_stack.currentIndex() + 1) % n))

        # SPEC-AVA-002 §4.1: open on the page the user was reading. The lookup is
        # by ATTRIBUTE NAME, never by index — the live QStackedWidget indices do
        # not correspond to page positions (karakas has two inner stacks that
        # each expand into two pages, so its Hora tab is stack 1 but page 2).
        start = 0
        if self._initial_attr in self._page_attrs:
            start = self._page_attrs.index(self._initial_attr)
        self._set_page(start)
        return area

    def _set_page(self, idx):
        """Switch the paged stack and restyle the name chips."""
        theme = get_theme_colors()
        self._page_stack.setCurrentIndex(idx)
        for i, chip in enumerate(self._page_chips):
            if i == idx:
                chip.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {theme['primary']};
                        color: {theme['primary_text']};
                        border: 1px solid {theme['primary']};
                        border-radius: 6px;
                        font-size: {scaled_area_px('table_headers')}px;
                        font-weight: bold;
                        padding: 6px 14px;
                    }}
                """)
            else:
                chip.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {theme['secondary']};
                        color: {theme['secondary_text']};
                        border: 1px solid {theme['secondary_light']};
                        border-radius: 6px;
                        font-size: {scaled_area_px('table_headers')}px;
                        padding: 6px 14px;
                    }}
                    QPushButton:hover {{
                        background-color: {theme['secondary_light']};
                    }}
                """)

    def keyPressEvent(self, event):
        """Left/Right arrow keys page through the stacked panels."""
        if hasattr(self, '_page_stack') and self._page_stack.count() > 0:
            n = self._page_stack.count()
            if event.key() == Qt.Key.Key_Left:
                self._set_page((self._page_stack.currentIndex() - 1) % n)
                return
            if event.key() == Qt.Key.Key_Right:
                self._set_page((self._page_stack.currentIndex() + 1) % n)
                return
        super().keyPressEvent(event)

    # ── Clone helpers ──────────────────────────────────────────────

    def _clone_table(self, src: QTableWidget, attr_name: str) -> QTableWidget:
        """Deep-clone a QTableWidget with delegate colors baked into cells."""
        theme = get_theme_colors()
        rows = src.rowCount()
        cols = src.columnCount()

        tbl = QTableWidget(rows, cols)
        tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        # Copy horizontal headers
        h_labels = []
        for c in range(cols):
            item = src.horizontalHeaderItem(c)
            h_labels.append(item.text() if item else "")
        tbl.setHorizontalHeaderLabels(h_labels)

        # Copy vertical headers. Use isHidden() (explicit hide flag), NOT
        # isVisible(): a source table on a hidden stack page reports
        # isVisible()=False and the clone would lose its row-planet column.
        has_v = not src.verticalHeader().isHidden()
        if has_v:
            v_labels = []
            for r in range(rows):
                item = src.verticalHeaderItem(r)
                v_labels.append(item.text() if item else "")
            tbl.setVerticalHeaderLabels(v_labels)
        tbl.verticalHeader().setVisible(has_v)

        # Copy cell data + bake delegate colors
        for r in range(rows):
            for c in range(cols):
                item = src.item(r, c)
                if item:
                    new_item = QTableWidgetItem(item.text())
                    new_item.setTextAlignment(item.textAlignment())

                    # Check delegate for colors
                    bg_hex, fg_hex = _get_delegate_colors(self.gui, attr_name, r, c)
                    if bg_hex:
                        new_item.setBackground(QBrush(QColor(bg_hex)))
                    else:
                        # Copy source item background (for non-delegate tables: Hora, Trimsamsa)
                        src_bg = item.background()
                        if src_bg.color().isValid() and src_bg.color().name() != "#000000":
                            new_item.setBackground(src_bg)
                    if fg_hex:
                        new_item.setForeground(QBrush(QColor(fg_hex)))
                    else:
                        # Preserve original foreground if set
                        fg = item.foreground()
                        if fg.color().isValid() and fg.color().name() != "#000000":
                            new_item.setForeground(fg)

                    tbl.setItem(r, c, new_item)

        # Larger font for fullscreen readability.
        # SPEC-THM-002 W2: was a third hand-rolled copy of the same block, one of
        # the two this wave collapses onto _popup_table_style. The ::item rule
        # here sets PADDING ONLY and is safe to keep — INV-5 is about a
        # BACKGROUND in ::item, which would defeat the delegate's fillRect and
        # erase the semantic colours. Padding does not paint.
        tbl.setStyleSheet(
            self._popup_table_style(matrix=attr_name in _MATRIX_TABLES)
            + """
            QTableWidget::item { padding: 6px; }
        """)

        for c in range(cols):
            tbl.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch)
        tbl.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        return tbl

    def _clone_textedit(self, src: QTextEdit) -> QTextEdit:
        """Clone a QTextEdit's HTML content with 1.5x font scaling."""
        theme = get_theme_colors()
        te = QTextEdit()
        te.setReadOnly(True)

        html = src.toHtml()
        import re
        def _scale_font(m):
            size = float(m.group(1))
            return f"font-size: {size * 1.5:.0f}px"
        html = re.sub(r'font-size:\s*(\d+(?:\.\d+)?)px', _scale_font, html)

        te.setHtml(html)
        # SPEC-THM-001 G05: live theme color (was frozen BORDER).
        te.setStyleSheet(f"""
            QTextEdit {{
                background-color: {theme['secondary_dark']};
                color: {theme['secondary_text']};
                border: 1px solid {theme['secondary_light']};
                font-size: {scaled_area_px('info_text')}px;
            }}
        """)
        return te

    def _attach_tajika_delegate(self, clone_table: QTableWidget,
                               attr_name: str = "tajika_matrix_table"):
        """Attach TajikaHighlightDelegate to a cloned Tajika table.

        Copies shape and category data from the original delegate so the
        fullscreen clone draws the same geometric shapes.
        """
        from apps.delegates import TajikaHighlightDelegate

        delegate_attr = DELEGATE_MAP.get(attr_name)
        if not delegate_attr:
            return
        src_delegate = getattr(self.gui, delegate_attr, None)
        if src_delegate is None:
            return

        delegate = TajikaHighlightDelegate(parent=clone_table)
        delegate.update_categories(src_delegate.cell_categories)
        delegate.update_shapes(src_delegate.cell_shapes)
        clone_table.setItemDelegate(delegate)

    def _attach_avastha_delegate(self, clone_table: QTableWidget):
        """Attach AvasthaHighlightDelegate to cloned Avastha table."""
        from apps.delegates import AvasthaHighlightDelegate

        src_delegate = getattr(self.gui, 'avastha_delegate', None)
        if src_delegate is None:
            return

        delegate = AvasthaHighlightDelegate(parent=clone_table)
        delegate.update_categories(src_delegate.cell_categories)
        clone_table.setItemDelegate(delegate)

    # ── Enhanced popup builders for Karakas section ────────────────

    # Color palettes: (dark_bg, dark_fg, light_bg, light_fg)
    _HORA_COLORS_THEMED = {
        "Aditya": ("#5C3D10", "#FFD54F", "#FFF3D6", "#8B5E00"),
        "Naga":   ("#10354D", "#80DEEA", "#D6F0FA", "#0D4D6E"),
    }
    _BEING_TYPE_COLORS_THEMED = {
        "Gandharva": ("#5C1A1A", "#E57373", "#FDDEDE", "#8B1A1A"),
        "Rakshasa":  ("#4D4D10", "#F0C75E", "#FDF5DC", "#6B5B1A"),
        "Rishi":     ("#3D1A5C", "#CE93D8", "#F3E0FA", "#5C1A8B"),
        "Yaksha":    ("#4D3818", "#D4A76A", "#F0E6D6", "#5C3D10"),
        "Apsara":    ("#102E5C", "#64B5F6", "#D6EAFF", "#0D3B6E"),
    }

    @staticmethod
    def _pick_colors(palette, key):
        """Return (bg, fg) from a themed palette, adapting for light/dark."""
        entry = palette.get(key)
        if not entry:
            t = get_theme_colors()
            return t['secondary'], t['secondary_text']
        if is_light_theme():
            return entry[2], entry[3]
        return entry[0], entry[1]
    _PLANET_SYMBOLS = {
        "Ascendant": "Asc", "Sun": "\u2609", "Moon": "\u263D", "Mars": "\u2642",
        "Mercury": "\u263F", "Jupiter": "\u2643", "Venus": "\u2640", "Saturn": "\u2644",
        "Rahu": "\u260A", "Ketu": "\u260B",
    }

    # Element colors: (dark_bg, dark_fg, light_bg, light_fg)
    _ELEMENT_COLORS = {
        "Fire":  ("#3D1A1A", "#E57373", "#FDDEDE", "#8B1A1A"),
        "Earth": ("#2E2014", "#D4A76A", "#F0E6D6", "#5C3D10"),
        "Air":   ("#2E2B14", "#F0C75E", "#FDF5DC", "#6B5B1A"),
        "Water": ("#0E2440", "#64B5F6", "#D6EAFF", "#0D3B6E"),
    }
    _MODALITY_COLORS = {
        "Fixed":    ("#2E1A00", "#FFB74D", "#FFF0D6", "#8B5E00"),
        "Dual":     ("#1A2E1A", "#81C784", "#DDFADD", "#2E6B2E"),
        "Moveable": ("#1A1A3D", "#9FA8DA", "#E0E4FA", "#3D3D8B"),
    }

    # Planet colors: (dark_bg, dark_fg, light_bg, light_fg)
    # Dark pairs styled like _BEING_TYPE_COLORS_THEMED (the karakas look):
    # saturated mid-dark bg + soft Material-300 text. Light pairs unchanged.
    _PLANET_COLORS_THEMED = {
        "Ascendant": ("#5C4310", "#FFCC80", "#FFEAD6", "#8B4D00"),
        "Sun":       ("#5C4A10", "#FFD54F", "#FFF3D6", "#8B5E00"),
        "Moon":      ("#10454D", "#80DEEA", "#E3F4F6", "#3D6B70"),
        "Mars":      ("#5C1A1A", "#E57373", "#FDDEDE", "#9B2222"),
        "Mercury":   ("#1A5C33", "#A5D6A7", "#DDF5E3", "#1E6B3C"),
        "Jupiter":   ("#5C3310", "#FFB74D", "#FFEAD1", "#8B5E14"),
        "Venus":     ("#5C1A42", "#F48FB1", "#FBE0EC", "#8B2257"),
        "Saturn":    ("#1A2A5C", "#9FA8DA", "#DEE8FB", "#22408B"),
        "Rahu":      ("#37424D", "#B0BEC5", "#E8EAF0", "#455A64"),
        "Ketu":      ("#4D3320", "#D4A76A", "#F0E2D6", "#6B4423"),
    }

    # Dignity codes: (dark_bg, dark_fg, light_bg, light_fg)
    # Dark pairs in the same jewel-tone family as the being-type colors.
    _DIGNITY_COLORS_THEMED = {
        "EX": ("#6B1A1A", "#FF8A80", "#FDDADA", "#B81414"),
        "MT": ("#4A1A6B", "#CE93D8", "#F3DEFA", "#7A1AA8"),
        "OH": ("#14406B", "#64B5F6", "#DCEFFD", "#0D5E9E"),
        "GF": ("#1A5C2A", "#A5D6A7", "#DDF7DD", "#1A7A1A"),
        "F":  ("#2A4D2A", "#C5E1A5", "#E8F5E8", "#3C6B3C"),
        "N":  ("#3A3A42", "#B8B8C0", "#EFEFF2", "#666670"),
        "E":  ("#5C4310", "#FFCC80", "#FDEEDA", "#9E5E0D"),
        "GE": ("#5C2E10", "#FFAB91", "#FDE3D6", "#A8430F"),
        "DB": ("#6B1010", "#FF6E6E", "#FBD9D7", "#C01810"),
    }

    _DIGNITY_FULL_NAMES = {
        "EX": "Exalted", "MT": "Moolatrikona", "OH": "Own House",
        "GF": "Great Friend", "F": "Friend", "N": "Neutral",
        "E": "Enemy", "GE": "Great Enemy", "DB": "Debilitated",
    }

    # Aspect matrix heat colors: (dark_bg, dark_fg, light_bg, light_fg)
    # Dark: rich purple/emerald/amber instead of murky olive/forest tones.
    _ASPECT_COLORS_THEMED = {
        "yuti":     ("#4A1A6B", "#CE93D8", "#F3E0FA", "#5C1A8B"),
        "strong":   ("#1A5C2A", "#A5D6A7", "#DDF7DD", "#1A7A1A"),
        "moderate": ("#5C4A10", "#FFE082", "#FAF5D6", "#6B5E1A"),
        "weak":     ("#2E3440", "#90A4AE", "#EDEEF2", "#5C616E"),
    }

    def _popup_table_style(self, matrix=False):
        """Fullscreen table style — no ::item rule so delegate colors work.

        SPEC-THM-002 W2: the body sits at elevation level 1 (it is inside an
        elevated container), the header gets the E4 gradient, and the gridline
        drops from full-strength `secondary_light` to a low-alpha hairline. That
        gridline was the single loudest thing in these tables and most of the
        "blunt table" complaint — at 0.18 alpha it reads as structure instead of
        noise.

        `matrix=True` keeps a stronger grid (D-4). On the Avastha 7x7 and the
        Tajika 11x11 the grid is doing real work: it is what lets the eye track a
        row across to its column. Quieting those to list-table levels would cost
        legibility to buy calm.

        The "no ::item rule" comment above is load-bearing, not decorative — a
        QSS ::item background DEFEATS a delegate's own fillRect (INV-5), so one
        would silently erase every semantic cell colour in the popup.
        """
        return (elevation_table_style(level=2, header_level=3, matrix=matrix)
                + f"""
            QTableWidget {{ font-size: {scaled_area_px('tables')}px; }}
            QHeaderView::section {{ font-size: {scaled_area_px('table_headers')}px; }}
        """)

    def _build_popup_karakas_enriched(self):
        """Fullscreen Karakas+Avastha enriched view (SPEC-KARAKAS-LAYOUT-001)."""
        from PySide6.QtWidgets import QTextBrowser
        import html as _html

        chart = getattr(self.gui.state, 'active_chart', None)
        if not chart:
            return None

        aditya_mode = self.gui.state.aditya_mode
        try:
            from core.chart_helpers import get_planet_in_sign_longitude, has_planet
            from AI_tools.AI_main_function.avastha import get_drishti_yuti_data
            from AI_tools.AI_main_function.retinue import get_chart_retinue
            from core.sidereal_helpers import ADITYA_NAMES, TROPICAL_NAMES, get_sign_ruler

            planet_names = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]
            planet_degrees = []
            for name in planet_names:
                if has_planet(chart, name):
                    deg = get_planet_in_sign_longitude(chart, name)
                    planet_degrees.append({"name": name, "degree": deg})
            planet_degrees.sort(key=lambda x: x["degree"], reverse=True)

            ayanamsa_offset = 0.0
            if aditya_mode == 'sidereal':
                ayanamsa_offset = getattr(self.gui, 'chart_ayanamsa_offset', 0.0)
            retinue = get_chart_retinue(
                chart, ayanamsa_offset=ayanamsa_offset,
                tropical_mode=(aditya_mode == 'tropical_classic'))
            retinue_by_name = {r["planet"]: r for r in retinue["planets"]}

            data = get_drishti_yuti_data(chart)
            matrix = data["matrix"]
            dignity_data = data["dignity_data"]
            shame_pairs = data.get("shame_pairs", set())
            shamed_planets = data.get("shamed_planets", set())

            lajjitaadi = {}
            try:
                lajj_raw = chart.rashi().lajjitaadi_avasthas()
                if isinstance(lajj_raw, dict):
                    lajjitaadi = lajj_raw
            except Exception:
                pass
        except Exception as e:
            print(f"[karakas_enriched popup] failed: {e}")
            return None

        theme = get_theme_colors()
        light = is_light_theme()
        base_px = scaled_area_px('tables')
        sm_px = base_px - 1
        text_color = theme['secondary_text']
        bg_color = theme['secondary_dark']
        bdr = theme['secondary_light']
        green = "#2E7D32" if light else "#A5D6A7"
        red = "#C62828" if light else "#EF9A9A"
        purple = "#7B1FA2" if light else "#CE93D8"

        _KARAKA_ROLES = [
            ("AK", "Atma Karaka", "Self"), ("AmK", "Amatya Karaka", "Minister"),
            ("BK", "Bhratru Karaka", "Brother"), ("MK", "Matru Karaka", "Mother"),
            ("PiK", "Pitru Karaka", "Father"), ("GK", "Gnati Karaka", "Relatives"),
            ("DK", "Dara Karaka", "Spouse"),
        ]
        _COL_ABBR = [("Sun", "Su"), ("Moon", "Mo"), ("Mars", "Ma"),
                     ("Mercury", "Me"), ("Jupiter", "Ju"), ("Venus", "Ve"),
                     ("Saturn", "Sa")]
        _SYM = self._PLANET_SYMBOLS

        td_s = f"padding:5px 4px; border-bottom:1px solid {bdr}; vertical-align:middle;"
        th_s = (f"padding:5px 4px; text-align:center; font-weight:bold; "
                f"border-bottom:2px solid {bdr}; background:{theme['secondary']}; "
                f"font-size:{sm_px}px;")
        th_l = th_s.replace("text-align:center", "text-align:left")

        def c(key):
            colors = self._AVASTHA_REL_COLORS.get(key, ("#AAA", "#555"))
            return colors[1] if light else colors[0]

        html = (
            f"<table cellpadding='0' cellspacing='0' "
            f"style='width:100%; table-layout:fixed; border-collapse:collapse; "
            f"font-size:{base_px}px; font-family:Inter,sans-serif; "
            f"color:{text_color};'>"
            f"<tr>"
            f"<th style='{th_l} width:16%;'>Karaka</th>"
            f"<th style='{th_l} width:10%;'>Retinue</th>"
        )
        for _, abbr in _COL_ABBR:
            html += f"<th style='{th_s} width:5%;'>{abbr}</th>"
        html += (
            f"<th style='{th_s} width:5%;'>Tot</th>"
            f"<th style='{th_l} width:24%;'>Condition</th>"
            f"</tr>"
        )

        for i, (code, karaka_name, meaning) in enumerate(_KARAKA_ROLES):
            if i >= len(planet_degrees):
                break
            p = planet_degrees[i]
            pname = p["name"]
            sym = _SYM.get(pname, "?")

            r = retinue_by_name.get(pname)
            trim_type = r.get("trimsamsa", {}).get("being_type") if r else None
            bt_colors = self._BEING_TYPE_COLORS.get(trim_type) if trim_type else None
            row_bg = (bt_colors[2] if light else bt_colors[0]) if bt_colors else bg_color
            row_fg = (bt_colors[3] if light else bt_colors[1]) if bt_colors else text_color

            is_shamed = pname in shamed_planets
            is_ak_dk = code in ("AK", "DK")
            lbdr = f"border-left:4px solid {c('SHAME')};" if is_shamed else \
                   (f"border-left:4px solid {theme['primary']};" if is_ak_dk else "")

            # Retinue summary
            ret_parts = []
            if trim_type:
                ret_parts.append(_html.escape(trim_type))
            if r:
                hora_side = r.get("hora", {}).get("side", "")
                if hora_side:
                    ret_parts.append("☉" if hora_side == "Aditya" else "☽")
            ret_str = " ".join(ret_parts) if ret_parts else "-"

            html += (
                f"<tr style='background:{row_bg}; color:{row_fg};'>"
                f"<td style='{td_s} {lbdr} white-space:nowrap;'>"
                f"<b>{sym} {code}</b> {_html.escape(meaning)}<br>"
                f"<span style='font-size:{sm_px}px; opacity:0.7;'>"
                f"{_html.escape(karaka_name)}</span></td>"
                f"<td style='{td_s} font-size:{sm_px}px;'>{ret_str}</td>"
            )

            # Avastha matrix columns
            for col_planet, _ in _COL_ABBR:
                if col_planet == pname:
                    # Diagonal = self base 60 x dignity multiplier (SPEC-AVA-001
                    # rev3): EX=120, MK=105, OH=90, none/debilitated=60.
                    dig = dignity_data.get(pname)
                    diag_val = SELF_BASE * dignity_multiplier(
                        dig["virupas"] if dig else 0)
                    if dig:
                        abbr_map = {"exaltation": "EX", "mulatrikona": "MK", "own_sign": "OH"}
                        html += (
                            f"<td style='{td_s} text-align:center; "
                            f"color:{c('PROUD')}; font-weight:bold;'>"
                            f"{abbr_map.get(dig['type'], '?')}={diag_val:.0f}</td>")
                    else:
                        html += (f"<td style='{td_s} text-align:center;'>"
                                 f"{diag_val:.0f}</td>")
                else:
                    entry = matrix.get((col_planet, pname))
                    if not entry or (not entry.get("is_yuti") and entry["virupas"] <= 0):
                        html += f"<td style='{td_s} text-align:center; opacity:0.4;'>.</td>"
                    else:
                        vr = entry["virupas"]
                        rel = entry["relationship"]
                        if (col_planet, pname) in shame_pairs:
                            color, s = c("SHAME"), "!"
                        elif rel == "FRIEND":
                            color, s = c("FRIEND"), "+"
                        elif rel == "ENEMY":
                            color, s = c("ENEMY"), "-"
                        elif rel == "DUAL":
                            color, s = c("DUAL"), "±"
                        elif rel == "NEUTRAL":
                            color, s = c("NEUTRAL"), "~"
                        else:
                            color, s = text_color, ""
                        html += (
                            f"<td style='{td_s} text-align:center; color:{color}; "
                            f"font-weight:bold;'>{vr:.0f}{s}</td>")

            # Total
            up, aff = split_expression(pname, planet_names, matrix, dignity_data, shame_pairs)
            total = up + aff
            tc = c("FRIEND") if total > 0 else c("ENEMY") if total < 0 else text_color
            html += (
                f"<td style='{td_s} text-align:center; color:{tc}; "
                f"font-weight:bold;'>{total:.0f}</td>")

            # Condition: lajjitaadi states
            cond_parts = []
            states = lajjitaadi.get(pname, {})
            descs = self._get_avastha_descriptions()
            for state_name in ("proud", "delighted", "healthy",
                               "starved", "thirsty", "agitated", "shamed"):
                factors = states.get(state_name)
                if not factors:
                    continue
                desc = descs.get(state_name, {})
                sanskrit = desc.get("sanskrit", state_name.title())
                state_c = c("FRIEND") if state_name in ("proud", "delighted", "healthy") \
                    else c("ENEMY")
                sv = sum(f.get("strength", 0) for f in factors if isinstance(f, dict))
                sign_c = "+" if state_name in ("proud", "delighted", "healthy") else "-"
                cond_parts.append(
                    f"<span style='color:{state_c}; font-size:{sm_px}px;'>"
                    f"{_html.escape(sanskrit)} {sign_c}{sv:.0f}</span>")
            html += (
                f"<td style='{td_s} font-size:{sm_px}px;'>"
                f"{' &middot; '.join(cond_parts) if cond_parts else '-'}</td>")

            html += "</tr>"

        html += "</table>"

        tb = QTextBrowser()
        tb.setReadOnly(True)
        tb.setOpenLinks(False)
        tb.setOpenExternalLinks(False)
        tb.setHtml(html)
        tb.setStyleSheet(f"""
            QTextBrowser {{
                background-color: {bg_color};
                color: {text_color};
                border: none;
            }}
        """)
        return tb

    def _build_popup_hora_table(self):
        """Build enhanced Hora popup table with extended columns."""
        _chart = getattr(self.gui.state, 'active_chart', None)
        if not _chart:
            return None
        try:
            from AI_tools.AI_main_function.retinue import get_chart_retinue
            _aditya_mode = self.gui.state.aditya_mode
            _ayanamsa_offset = 0.0
            if _aditya_mode == 'sidereal':
                _ayanamsa_offset = getattr(self.gui, 'chart_ayanamsa_offset', 0.0)
            _tropical_mode = (_aditya_mode == 'tropical_classic')
            chart_data = get_chart_retinue(_chart,
                                           ayanamsa_offset=_ayanamsa_offset,
                                           tropical_mode=_tropical_mode)
            planets = chart_data["planets"]
            summary = chart_data["summary"]
        except Exception:
            return None

        headers = ["Planet", "Sign", "Deg", "Hora Being", "Side"]
        tbl = QTableWidget(len(planets) + 1, len(headers))
        tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        tbl.setHorizontalHeaderLabels(headers)
        tbl.verticalHeader().setVisible(False)
        tbl.setShowGrid(True)
        tbl.setStyleSheet(self._popup_table_style())

        # Attach delegate so row colors bypass qt-material's global ::item rule
        from apps.delegates import RetinueColorDelegate
        hora_dlg = RetinueColorDelegate(parent=tbl)
        tbl.setItemDelegate(hora_dlg)
        tbl._color_delegate = hora_dlg  # prevent GC

        bold = QFont()
        bold.setBold(True)

        for i, r in enumerate(planets):
            side = r["hora"]["side"]
            bg_hex, fg_hex = self._pick_colors(self._HORA_COLORS_THEMED, side)
            bg = QBrush(QColor(bg_hex))
            fg = QColor(fg_hex)

            # Planet
            sym = self._PLANET_SYMBOLS.get(r["planet"], "")
            item0 = QTableWidgetItem(f"{sym} {r['planet']}")
            item0.setBackground(bg); item0.setForeground(fg)
            item0.setFont(bold)
            tbl.setItem(i, 0, item0)

            # Sign (Aditya/Western)
            sign_text = f"{r['aditya_sign']}/{r['western_equivalent']}"
            item1 = QTableWidgetItem(sign_text)
            item1.setBackground(bg); item1.setForeground(fg)
            tbl.setItem(i, 1, item1)

            # Degree
            deg_text = f"{r['degrees']}\u00B0{r['minutes']:02d}'"
            item2 = QTableWidgetItem(deg_text)
            item2.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item2.setBackground(bg); item2.setForeground(fg)
            tbl.setItem(i, 2, item2)

            # Hora Being
            item3 = QTableWidgetItem(r["hora"]["being_name"])
            item3.setBackground(bg); item3.setForeground(fg)
            item3.setFont(bold)
            tbl.setItem(i, 3, item3)

            # Side
            side_text = f"\u2609 Aditya" if side == "Aditya" else f"\u263D Naga"
            item4 = QTableWidgetItem(side_text)
            item4.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item4.setBackground(bg); item4.setForeground(fg)
            tbl.setItem(i, 4, item4)

        # Summary row
        ha = summary["hora"]["aditya_side"]
        hn = summary["hora"]["naga_side"]
        summary_text = f"\u2609 Aditya: {ha['count']}   |   \u263D Naga: {hn['count']}"
        summary_item = QTableWidgetItem(summary_text)
        summary_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        bold_lg = QFont(); bold_lg.setBold(True); bold_lg.setPointSize(scaled_area_size('tables'))
        summary_item.setFont(bold_lg)
        theme = get_theme_colors()
        summary_item.setBackground(QBrush(QColor(theme['secondary'])))
        summary_item.setForeground(QColor(theme['secondary_text']))
        tbl.setItem(len(planets), 0, summary_item)
        tbl.setSpan(len(planets), 0, 1, len(headers))

        # Column sizing
        tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        tbl.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        tbl.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        tbl.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        tbl.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        return tbl

    def _build_popup_trimsamsa_table(self):
        """Build enhanced Trimsamsa popup table with extended columns."""
        _chart = getattr(self.gui.state, 'active_chart', None)
        if not _chart:
            return None
        try:
            from AI_tools.AI_main_function.retinue import get_chart_retinue
            _aditya_mode = self.gui.state.aditya_mode
            _ayanamsa_offset = 0.0
            if _aditya_mode == 'sidereal':
                _ayanamsa_offset = getattr(self.gui, 'chart_ayanamsa_offset', 0.0)
            _tropical_mode = (_aditya_mode == 'tropical_classic')
            chart_data = get_chart_retinue(_chart,
                                           ayanamsa_offset=_ayanamsa_offset,
                                           tropical_mode=_tropical_mode)
            planets = chart_data["planets"]
            summary = chart_data["summary"]
        except Exception:
            return None

        headers = ["Planet", "Sign", "Deg", "Being", "Type", "Element"]
        tbl = QTableWidget(len(planets) + 1, len(headers))
        tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        tbl.setHorizontalHeaderLabels(headers)
        tbl.verticalHeader().setVisible(False)
        tbl.setShowGrid(True)
        tbl.setStyleSheet(self._popup_table_style())

        # Attach delegate so row colors bypass qt-material's global ::item rule
        from apps.delegates import RetinueColorDelegate
        trim_dlg = RetinueColorDelegate(parent=tbl)
        tbl.setItemDelegate(trim_dlg)
        tbl._color_delegate = trim_dlg  # prevent GC

        bold = QFont()
        bold.setBold(True)

        for i, r in enumerate(planets):
            btype = r["trimsamsa"]["being_type"]
            bg_hex, fg_hex = self._pick_colors(self._BEING_TYPE_COLORS_THEMED, btype)
            bg = QBrush(QColor(bg_hex))
            fg = QColor(fg_hex)

            # Planet
            sym = self._PLANET_SYMBOLS.get(r["planet"], "")
            item0 = QTableWidgetItem(f"{sym} {r['planet']}")
            item0.setBackground(bg); item0.setForeground(fg)
            item0.setFont(bold)
            tbl.setItem(i, 0, item0)

            # Sign
            sign_text = f"{r['aditya_sign']}/{r['western_equivalent']}"
            item1 = QTableWidgetItem(sign_text)
            item1.setBackground(bg); item1.setForeground(fg)
            tbl.setItem(i, 1, item1)

            # Degree
            deg_text = f"{r['degrees']}\u00B0{r['minutes']:02d}'"
            item2 = QTableWidgetItem(deg_text)
            item2.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item2.setBackground(bg); item2.setForeground(fg)
            tbl.setItem(i, 2, item2)

            # Being name
            item3 = QTableWidgetItem(r["trimsamsa"]["being_name"])
            item3.setBackground(bg); item3.setForeground(fg)
            item3.setFont(bold)
            tbl.setItem(i, 3, item3)

            # Type
            item4 = QTableWidgetItem(btype)
            item4.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item4.setBackground(bg); item4.setForeground(fg)
            tbl.setItem(i, 4, item4)

            # Element
            item5 = QTableWidgetItem(r["trimsamsa"]["element"])
            item5.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item5.setBackground(bg); item5.setForeground(fg)
            tbl.setItem(i, 5, item5)

        # Summary row
        ts = summary["trimsamsa"]
        type_order = ["Gandharva", "Rakshasa", "Rishi", "Yaksha", "Apsara"]
        key_order = ["gandharva", "rakshasa", "rishi", "yaksha", "apsara"]
        parts = []
        for label, key in zip(type_order, key_order):
            c = ts[key]["count"]
            parts.append(f"{label}: {c}")
        dominant = summary.get("dominant_force", "")
        summary_text = "   ".join(parts) + f"   \u25B8 Dominant: {dominant}"
        summary_item = QTableWidgetItem(summary_text)
        summary_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        bold_lg = QFont(); bold_lg.setBold(True); bold_lg.setPointSize(scaled_area_size('tables'))
        summary_item.setFont(bold_lg)
        dom_bg, dom_fg = self._pick_colors(self._BEING_TYPE_COLORS_THEMED, dominant)
        summary_item.setBackground(QBrush(QColor(dom_bg)))
        summary_item.setForeground(QColor(dom_fg))
        tbl.setItem(len(planets), 0, summary_item)
        tbl.setSpan(len(planets), 0, 1, len(headers))

        # Column sizing
        tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        tbl.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        tbl.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        tbl.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        tbl.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        tbl.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        return tbl

    def _build_popup_graph(self):
        """Build a larger Graph bar widget for the popup."""
        from apps.widgets.panel_controllers.house_graph_controller import _HouseBarWidget
        graph = _HouseBarWidget(gui_ref=self.gui)
        graph.setMinimumHeight(400)
        return graph

    # ── Planetary Condition (SPEC-PLANET-PROFILE-001) ──────────────────

    _PROFILE_PLANETS = [
        "Ascendant", "Sun", "Moon", "Mars", "Mercury",
        "Jupiter", "Venus", "Saturn", "Rahu", "Ketu",
    ]
    _AVASTHA_PLANETS = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]

    # Trimsamsa being-type row colors: (dark_bg, dark_fg, light_bg, light_fg)
    _BEING_TYPE_COLORS = {
        "Gandharva": ("#5C1A1A", "#E57373", "#FFEBEE", "#B71C1C"),
        "Rakshasa":  ("#4D4D10", "#F0C75E", "#FFFDE7", "#F57F17"),
        "Rishi":     ("#3D1A5C", "#CE93D8", "#F3E5F5", "#6A1B9A"),
        "Yaksha":    ("#4D3818", "#D4A76A", "#FBE9E7", "#4E342E"),
        "Apsara":    ("#102E5C", "#64B5F6", "#E3F2FD", "#1565C0"),
    }

    _AVASTHA_REL_COLORS = {
        "FRIEND":  ("#A5D6A7", "#2E7D32"),
        "ENEMY":   ("#EF9A9A", "#C62828"),
        "NEUTRAL": ("#90CAF9", "#1565C0"),
        "DUAL":    ("#FFE082", "#F57F17"),
        "SHAME":   ("#FF5252", "#B71C1C"),
        "PROUD":   ("#CE93D8", "#7B1FA2"),
    }

    _DIGNITY_LABELS = {
        "exaltation": ("EX", "Exalted", "Proud state"),
        "mulatrikona": ("MK", "Moolatrikona", "Proud state"),
        "own_sign": ("OH", "Own House", "Proud state"),
    }

    @staticmethod
    def _load_avastha_descriptions():
        import json, os
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))),
            "AI_tools", "AI_main_function", "avastha_descriptions.json")
        try:
            with open(path) as f:
                return json.load(f).get("lajjitaadi", {})
        except Exception as e:
            print(f"[PlanetaryCondition] avastha descriptions load failed: {e}")
            return {}

    _AVASTHA_DESCRIPTIONS = None

    @classmethod
    def _get_avastha_descriptions(cls):
        if cls._AVASTHA_DESCRIPTIONS is None:
            cls._AVASTHA_DESCRIPTIONS = cls._load_avastha_descriptions()
        return cls._AVASTHA_DESCRIPTIONS

    @staticmethod
    def _invert_house_tally(tally):
        by_planet = {}
        for house_num, entries in tally.items():
            for e in entries:
                by_planet.setdefault(e["planet"], []).append(
                    {"house": house_num, "ring": e["ring"]}
                )
        for planet in by_planet:
            by_planet[planet].sort(key=lambda x: x["house"])
        return by_planet

    @staticmethod
    def _compute_avastha_total(planet, planet_order, matrix, dignity_data, shame_pairs):
        up, aff = split_expression(planet, planet_order, matrix, dignity_data, shame_pairs)
        return up + aff

    def _build_popup_planet_profiles(self):
        """SPEC-PLANET-PROFILE-001: full-width per-planet table combining
        house connections, retinue identity, and avastha condition.

        Retinue beings are clickable (opens SectorInfoDialog).
        Avastha states come from libaditya + human-readable descriptions.
        Sign display follows the current zodiac mode (SPEC-ZOD-001).
        Asc/Rahu/Ketu show their sign lord's avastha.
        """
        from PySide6.QtWidgets import QTextBrowser
        import html as _html

        theme = get_theme_colors()
        light = is_light_theme()
        chart = getattr(self.gui.state, 'active_chart', None)
        if not chart:
            return None

        aditya_mode = self.gui.state.aditya_mode
        use_western = getattr(self.gui, 'use_western_names', False)

        # In sidereal mode, rebuild chart so sign_for/get_lord use sidereal
        # positions, matching the avastha data (Codex finding #1).
        display_chart = chart
        if aditya_mode == 'sidereal':
            try:
                from core.chart_factory import rebuild_chart
                display_chart = rebuild_chart(chart, mode="sidereal")
            except Exception:
                pass

        retinue_by_name, houses_by_planet = self._load_retinue_data(chart, aditya_mode)
        if retinue_by_name is None:
            return None

        avastha_matrix, dignity_data, shame_pairs, shamed_planets, lajjitaadi = \
            self._load_avastha_data(chart, aditya_mode)

        from core.aditya_mode import displayed_sign_name
        from core.chart_helpers import get_planet_sign_index
        from AI_tools.AI_main_function.avastha import SIGN_RULERS

        def sign_for(planet_name):
            idx = get_planet_sign_index(display_chart, planet_name, default=-1)
            return displayed_sign_name(idx, aditya_mode, use_western) if idx >= 0 else "?"

        def get_lord(planet_name):
            from core.chart_helpers import ADITYA_NAMES, TROPICAL_NAMES
            idx = get_planet_sign_index(display_chart, planet_name, default=-1)
            if idx < 0:
                return None
            for names in (ADITYA_NAMES, TROPICAL_NAMES):
                lord = SIGN_RULERS.get(names[idx])
                if lord:
                    return lord
            return None

        base_px = scaled_area_px('tables')
        sm_px = base_px - 1
        text_color = theme['secondary_text']
        bg_color = theme['secondary_dark']
        bdr = theme['secondary_light']

        def c(key):
            colors = self._AVASTHA_REL_COLORS.get(key, ("#AAA", "#555"))
            return colors[1] if light else colors[0]

        def houses_html(pname):
            entries = houses_by_planet.get(pname, [])
            if not entries:
                return "<span style='color:#666;'>-</span>"
            parts = []
            for e in entries:
                color = ("#FFD54F" if not light else "#8B5E00") if e["ring"] == "H" \
                    else ("#80DEEA" if not light else "#0D4D6E")
                parts.append(f"<span style='color:{color}; font-weight:bold;'>"
                             f"{'Hora' if e['ring'] == 'H' else 'Trim'}{e['house']}</span>")
            return " ".join(parts)

        def retinue_html(r, pname):
            if not r:
                return "<span style='color:#666;'>-</span>"
            hora = r.get("hora", {})
            trim = r.get("trimsamsa", {})
            sign_name = r.get("aditya_sign", "?")
            side = hora.get("side", "?")
            side_c = ("#FFD54F" if side == "Aditya" else "#80DEEA") if not light \
                else ("#8B5E00" if side == "Aditya" else "#0D4D6E")
            side_icon = "☉" if side == "Aditya" else "☽"
            hora_name = _html.escape(hora.get("being_name", "?"))
            trim_name = _html.escape(trim.get("being_name", "?"))
            trim_type_raw = trim.get("being_type", "?")
            trim_type = _html.escape(trim_type_raw)
            safe_sign = _html.escape(sign_name, quote=True)
            safe_planet = _html.escape(pname, quote=True)
            hora_type_key = "aditya" if side == "Aditya" else "naga"
            trim_type_key = trim_type_raw.lower()
            hora_link = (
                f"<a href='sector:{safe_sign}:hora:{hora_type_key}:{safe_planet}' "
                f"style='color:inherit; text-decoration:underline;'>"
                f"<b>{hora_name}</b></a>")
            trim_link = (
                f"<a href='sector:{safe_sign}:trimsamsa:{trim_type_key}:{safe_planet}' "
                f"style='color:inherit; text-decoration:underline;'>"
                f"{trim_name}</a>")
            return (
                f"{hora_link} <span style='color:{side_c};'>{side_icon}</span> "
                f"&middot; {trim_link} ({trim_type})")

        lord_map = {}
        for pname in self._PROFILE_PLANETS:
            if pname not in self._AVASTHA_PLANETS:
                lord = get_lord(pname)
                if lord and lord in self._AVASTHA_PLANETS:
                    lord_map[pname] = lord

        def _avastha_target(pname):
            if pname in self._AVASTHA_PLANETS:
                return pname, ""
            lord = lord_map.get(pname)
            if lord:
                return lord, f"Lord: {self._PLANET_SYMBOLS.get(lord, '')} {lord}"
            return None, ""

        _COL_ABBR = [("Sun", "Su"), ("Moon", "Mo"), ("Mars", "Ma"),
                     ("Mercury", "Me"), ("Jupiter", "Ju"), ("Venus", "Ve"),
                     ("Saturn", "Sa")]

        # Build the HTML table with inline avastha matrix
        th_s = (f"padding:5px 4px; text-align:center; font-weight:bold; "
                f"border-bottom:2px solid {bdr}; background:{theme['secondary']}; "
                f"font-size:{sm_px}px;")
        th_l = th_s.replace("text-align:center", "text-align:left")
        td_s = f"padding:5px 4px; border-bottom:1px solid {bdr}; vertical-align:middle;"

        # Header row: Planet | Houses | Retinue | Su Mo Ma Me Ju Ve Sa | Total | States
        html = (
            f"<table cellpadding='0' cellspacing='0' "
            f"style='width:100%; table-layout:fixed; border-collapse:collapse; "
            f"font-size:{base_px}px; font-family:Inter,sans-serif; "
            f"color:{text_color};'>"
            f"<tr>"
            f"<th style='{th_l} width:10%;'>Planet</th>"
            f"<th style='{th_s} width:6%;'>Houses</th>"
            f"<th style='{th_l} width:16%;'>Retinue</th>"
        )
        for _, abbr in _COL_ABBR:
            html += f"<th style='{th_s} width:5%;'>{abbr}</th>"
        html += (
            f"<th style='{th_s} width:5%;'>Tot</th>"
            f"<th style='{th_l} width:22%;'>Condition</th>"
            f"</tr>"
        )

        for pname in self._PROFILE_PLANETS:
            r = retinue_by_name.get(pname)
            trim_type = r.get("trimsamsa", {}).get("being_type") if r else None
            bt_colors = self._BEING_TYPE_COLORS.get(trim_type) if trim_type else None
            row_bg = (bt_colors[2] if light else bt_colors[0]) if bt_colors else bg_color
            row_fg = (bt_colors[3] if light else bt_colors[1]) if bt_colors else text_color
            is_shamed = pname in shamed_planets
            lbdr = f"border-left:4px solid {c('SHAME')};" if is_shamed else ""

            sym = self._PLANET_SYMBOLS.get(pname, "")
            sign = sign_for(pname)
            deg = f" {r['degrees']}°{r['minutes']:02d}'" if r else ""

            target, lord_label = _avastha_target(pname)

            # Planet + Sign cell
            html += (
                f"<tr style='background:{row_bg}; color:{row_fg};'>"
                f"<td style='{td_s} font-weight:bold; {lbdr} white-space:nowrap;'>"
                f"{sym} {pname}<br>"
                f"<span style='font-size:{sm_px}px; opacity:0.7; font-weight:normal;'>"
                f"{_html.escape(sign)}{deg}</span></td>"
                f"<td style='{td_s} text-align:center;'>{houses_html(pname)}</td>"
                f"<td style='{td_s} font-size:{sm_px}px;'>{retinue_html(r, pname)}</td>"
            )

            # Avastha matrix cells (7 columns: Su Mo Ma Me Ju Ve Sa)
            if target:
                for col_planet, _ in _COL_ABBR:
                    if col_planet == target:
                        # Diagonal = self base 60 x dignity multiplier
                        # (SPEC-AVA-001 rev3).
                        dig = dignity_data.get(target)
                        diag_val = SELF_BASE * dignity_multiplier(
                            dig["virupas"] if dig else 0)
                        if dig:
                            abbr_map = {"exaltation": "EX", "mulatrikona": "MK", "own_sign": "OH"}
                            code = abbr_map.get(dig["type"], "?")
                            html += (
                                f"<td style='{td_s} text-align:center; "
                                f"color:{c('PROUD')}; font-weight:bold;'>"
                                f"{code}={diag_val:.0f}</td>")
                        else:
                            html += (f"<td style='{td_s} text-align:center;'>"
                                     f"{diag_val:.0f}</td>")
                    else:
                        entry = avastha_matrix.get((col_planet, target))
                        if not entry or (not entry.get("is_yuti") and entry["virupas"] <= 0):
                            html += f"<td style='{td_s} text-align:center; opacity:0.4;'>.</td>"
                        else:
                            vr = entry["virupas"]
                            rel = entry["relationship"]
                            if (col_planet, target) in shame_pairs:
                                color, s = c("SHAME"), "!"
                            elif rel == "FRIEND":
                                color, s = c("FRIEND"), "+"
                            elif rel == "ENEMY":
                                color, s = c("ENEMY"), "-"
                            elif rel == "DUAL":
                                color, s = c("DUAL"), "±"
                            elif rel == "NEUTRAL":
                                color, s = c("NEUTRAL"), "~"
                            else:
                                color, s = text_color, ""
                            html += (
                                f"<td style='{td_s} text-align:center; color:{color}; "
                                f"font-weight:bold;'>{vr:.0f}{s}</td>")

                # Total cell
                total = self._compute_avastha_total(
                    target, self._AVASTHA_PLANETS,
                    avastha_matrix, dignity_data, shame_pairs)
                tc = c("FRIEND") if total > 0 else c("ENEMY") if total < 0 else text_color
                html += (
                    f"<td style='{td_s} text-align:center; color:{tc}; "
                    f"font-weight:bold;'>{total:.0f}</td>")

                # Condition cell: lord label + lajjitaadi states with virupas
                cond_parts = []
                if lord_label:
                    cond_parts.append(
                        f"<span style='opacity:0.7; font-size:{sm_px}px;'>"
                        f"{lord_label}</span>")
                states = lajjitaadi.get(target, {})
                for state_name in ("proud", "delighted", "healthy",
                                   "starved", "thirsty", "agitated", "shamed"):
                    factors = states.get(state_name)
                    if not factors:
                        continue
                    desc = self._get_avastha_descriptions().get(state_name, {})
                    sanskrit = desc.get("sanskrit", state_name.title())
                    state_c = c("FRIEND") if state_name in ("proud", "delighted", "healthy") \
                        else c("ENEMY") if state_name in ("starved", "agitated", "shamed") \
                        else c("DUAL")
                    total_str = sum(
                        f.get("strength", 0) for f in factors if isinstance(f, dict))
                    sign_char = "+" if state_name in ("proud", "delighted", "healthy") else "-"
                    cond_parts.append(
                        f"<span style='color:{state_c}; font-size:{sm_px}px;'>"
                        f"{_html.escape(sanskrit)} {sign_char}{total_str:.0f}</span>")
                html += (
                    f"<td style='{td_s} font-size:{sm_px}px;'>"
                    f"{' &middot; '.join(cond_parts) if cond_parts else '-'}</td>")
            else:
                for _ in range(9):
                    html += f"<td style='{td_s} text-align:center; opacity:0.3;'>-</td>"

            html += "</tr>"

        html += "</table>"

        tb = QTextBrowser()
        tb.setReadOnly(True)
        tb.setOpenLinks(False)
        tb.setOpenExternalLinks(False)
        tb.setHtml(html)
        self._pp_avastha_matrix = avastha_matrix
        self._pp_dignity_data = dignity_data
        self._pp_shame_pairs = shame_pairs
        self._pp_lord_map = lord_map

        tb.anchorClicked.connect(self._on_retinue_link_clicked)
        tb.setStyleSheet(f"""
            QTextBrowser {{
                background-color: {bg_color};
                color: {text_color};
                border: none;
            }}
        """)
        return tb

    def _on_retinue_link_clicked(self, url):
        """Handle clicks on retinue being names in the Planetary Condition table.
        URL format: sector:<sign_name>:<ring>:<type_key>:<planet_name>
        Opens SectorInfoDialog with uplifted/afflicted expression totals.
        """
        url_str = url.toString() if hasattr(url, 'toString') else str(url)
        if not url_str.startswith("sector:"):
            return
        parts = url_str.split(":", 4)
        if len(parts) < 4:
            return
        _, sign_name, ring, type_key = parts[0], parts[1], parts[2], parts[3]
        planet_name = parts[4] if len(parts) > 4 else None

        avastha_summary = None
        if planet_name:
            avastha_summary = self._compute_expression_totals(planet_name)

        try:
            from apps.widgets.sector_dialog import SectorInfoDialog
            dlg = SectorInfoDialog(sign_name, focus_ring=ring,
                                   focus_type=type_key,
                                   avastha_summary=avastha_summary,
                                   parent=self)
            dlg.exec()
            dlg.deleteLater()
        except Exception as e:
            print(f"[PlanetaryCondition] sector dialog failed: {e}")

    def _compute_expression_totals(self, planet_name):
        """Compute uplifted/afflicted expression totals using cached build data."""
        matrix = getattr(self, '_pp_avastha_matrix', None)
        if matrix is None:
            return None

        target = planet_name
        if target not in self._AVASTHA_PLANETS:
            target = getattr(self, '_pp_lord_map', {}).get(planet_name)
        if not target:
            return None

        up, aff = split_expression(
            target, self._AVASTHA_PLANETS, matrix,
            getattr(self, '_pp_dignity_data', {}),
            getattr(self, '_pp_shame_pairs', set()))
        return {"planet": planet_name, "target": target,
                "uplifted": up, "afflicted": aff, "total": up + aff}

    def _load_retinue_data(self, chart, aditya_mode):
        """Load retinue + house connection data. Returns (by_name, by_planet) or (None, None)."""
        try:
            from AI_tools.AI_main_function.retinue import get_chart_retinue, _build_house_tally
            ayanamsa_offset = 0.0
            if aditya_mode == 'sidereal':
                ayanamsa_offset = getattr(self.gui, 'chart_ayanamsa_offset', 0.0)
            chart_data = get_chart_retinue(
                chart, ayanamsa_offset=ayanamsa_offset,
                tropical_mode=(aditya_mode == 'tropical_classic'))
            by_name = {r["planet"]: r for r in chart_data["planets"]}
            tally = _build_house_tally(chart_data["planets"])
            return by_name, self._invert_house_tally(tally)
        except Exception as e:
            print(f"[PlanetaryCondition] retinue load failed: {e}")
            return None, None

    def _load_avastha_data(self, chart, aditya_mode):
        """Load avastha matrix + libaditya lajjitaadi states."""
        matrix, dignity, shame_p, shamed_pl, lajjitaadi = {}, {}, set(), set(), {}
        try:
            from AI_tools.AI_main_function.avastha import get_drishti_yuti_data
            if aditya_mode == 'sidereal':
                from core.chart_factory import rebuild_chart
                chart = rebuild_chart(chart, mode="sidereal")
            data = get_drishti_yuti_data(chart)
            matrix = data["matrix"]
            dignity = data["dignity_data"]
            shame_p = data.get("shame_pairs", set())
            shamed_pl = data.get("shamed_planets", set())
        except Exception as e:
            print(f"[PlanetaryCondition] avastha load failed: {e}")
        try:
            rashi = chart.rashi()
            raw = rashi.lajjitaadi_avasthas()
            for pname, avasthas in raw.items():
                lajjitaadi[pname] = avasthas
        except Exception as e:
            print(f"[PlanetaryCondition] lajjitaadi load failed: {e}")
        return matrix, dignity, shame_p, shamed_pl, lajjitaadi

    # ── Enhanced popup builders for Strength section ─────────────────

    def _build_popup_elements_table(self, src: QTableWidget):
        """Clone elements table with element-colored rows."""
        light = is_light_theme()
        clone = self._clone_table(src, "elements_table")

        for r in range(clone.rowCount()):
            item0 = clone.item(r, 0)
            if not item0:
                continue
            cell_text = item0.text()
            for elem, colors in self._ELEMENT_COLORS.items():
                if elem in cell_text:
                    dark_bg, dark_fg, light_bg, light_fg = colors
                    bg = QColor(light_bg if light else dark_bg)
                    fg = QColor(light_fg if light else dark_fg)
                    for c in range(clone.columnCount()):
                        ci = clone.item(r, c)
                        if ci:
                            ci.setBackground(QBrush(bg))
                            ci.setForeground(QBrush(fg))
                    break

        from apps.delegates import RetinueColorDelegate
        dlg = RetinueColorDelegate(parent=clone)
        clone.setItemDelegate(dlg)
        clone._color_delegate = dlg
        return clone

    def _build_popup_modality_table(self, src: QTableWidget):
        """Clone modality table with modality-colored rows."""
        light = is_light_theme()
        clone = self._clone_table(src, "modality_table")

        for r in range(clone.rowCount()):
            item0 = clone.item(r, 0)
            if not item0:
                continue
            cell_text = item0.text()
            for mod, colors in self._MODALITY_COLORS.items():
                if mod in cell_text:
                    dark_bg, dark_fg, light_bg, light_fg = colors
                    bg = QColor(light_bg if light else dark_bg)
                    fg = QColor(light_fg if light else dark_fg)
                    for c in range(clone.columnCount()):
                        ci = clone.item(r, c)
                        if ci:
                            ci.setBackground(QBrush(bg))
                            ci.setForeground(QBrush(fg))
                    break

        from apps.delegates import RetinueColorDelegate
        dlg = RetinueColorDelegate(parent=clone)
        clone.setItemDelegate(dlg)
        clone._color_delegate = dlg
        return clone

    def _apply_planet_row_colors(self, clone: QTableWidget, planet_col: int):
        """Color each row by the planet named in planet_col (theme-aware)."""
        light = is_light_theme()
        for r in range(clone.rowCount()):
            key_item = clone.item(r, planet_col)
            if not key_item:
                continue
            cell_text = key_item.text()
            for planet, colors in self._PLANET_COLORS_THEMED.items():
                if planet in cell_text:
                    dark_bg, dark_fg, light_bg, light_fg = colors
                    bg = QBrush(QColor(light_bg if light else dark_bg))
                    fg = QBrush(QColor(light_fg if light else dark_fg))
                    for c in range(clone.columnCount()):
                        ci = clone.item(r, c)
                        if ci:
                            ci.setBackground(bg)
                            ci.setForeground(fg)
                    break

    def _build_popup_strength_table(self, src: QTableWidget):
        """Clone strength table with planet-colored rows; strong values stand out."""
        theme = get_theme_colors()
        clone = self._clone_table(src, "strength_table")
        self._apply_planet_row_colors(clone, planet_col=0)

        # Re-apply the main view's strength highlights on top of planet colors
        src_delegate = getattr(self.gui, 'strength_delegate', None)
        if src_delegate is not None and hasattr(src_delegate, 'highlight_cells'):
            bold = QFont()
            bold.setBold(True)
            for (r, c) in src_delegate.highlight_cells:
                ci = clone.item(r, c)
                if ci:
                    ci.setFont(bold)
                    ci.setBackground(QBrush(QColor(theme['primary'])))
                    ci.setForeground(QBrush(QColor(theme['primary_text'])))

        from apps.delegates import RetinueColorDelegate
        dlg = RetinueColorDelegate(parent=clone)
        clone.setItemDelegate(dlg)
        clone._color_delegate = dlg
        return clone

    def _build_popup_karakas_table(self, src: QTableWidget):
        """Clone karakas table with planet-colored rows; AK/DK rows in bold."""
        clone = self._clone_table(src, "karakas_table")
        self._apply_planet_row_colors(clone, planet_col=1)

        # AK/DK highlight rows from the main view: bold the whole row
        src_delegate = getattr(self.gui, 'karakas_delegate', None)
        if src_delegate is not None and hasattr(src_delegate, 'highlight_rows'):
            bold = QFont()
            bold.setBold(True)
            for r in src_delegate.highlight_rows:
                for c in range(clone.columnCount()):
                    ci = clone.item(r, c)
                    if ci:
                        ci.setFont(bold)

        from apps.delegates import RetinueColorDelegate
        dlg = RetinueColorDelegate(parent=clone)
        clone.setItemDelegate(dlg)
        clone._color_delegate = dlg
        return clone

    # ── Enhanced popup builders for Aspects section ──────────────────

    def _build_popup_aspects_table(self, src: QTableWidget):
        """Clone aspects matrix as a virupa heat-map (Y / >=45 / >=30 / >0)."""
        light = is_light_theme()
        clone = self._clone_table(src, "aspects_table")

        def _heat_key(text):
            if text == "Y":
                return "yuti"
            try:
                vr = float(text)
            except ValueError:
                return None
            if vr >= 45:
                return "strong"
            if vr >= 30:
                return "moderate"
            if vr > 0:
                return "weak"
            return None

        bold = QFont()
        bold.setBold(True)
        for r in range(clone.rowCount()):
            for c in range(clone.columnCount()):
                ci = clone.item(r, c)
                if not ci:
                    continue
                key = _heat_key(ci.text())
                if not key:
                    continue
                dark_bg, dark_fg, light_bg, light_fg = self._ASPECT_COLORS_THEMED[key]
                ci.setBackground(QBrush(QColor(light_bg if light else dark_bg)))
                ci.setForeground(QBrush(QColor(light_fg if light else dark_fg)))
                if key in ("yuti", "strong"):
                    ci.setFont(bold)

        from apps.delegates import RetinueColorDelegate
        dlg = RetinueColorDelegate(parent=clone)
        clone.setItemDelegate(dlg)
        clone._color_delegate = dlg

        # Wrap table + caption explaining the heat scale
        theme = get_theme_colors()
        wrap = QWidget()
        wrap_layout = QVBoxLayout(wrap)
        wrap_layout.setContentsMargins(0, 0, 0, 0)
        wrap_layout.setSpacing(4)
        wrap_layout.addWidget(clone, stretch=1)

        yuti_fg = self._ASPECT_COLORS_THEMED["yuti"][3 if light else 1]
        strong_fg = self._ASPECT_COLORS_THEMED["strong"][3 if light else 1]
        mod_fg = self._ASPECT_COLORS_THEMED["moderate"][3 if light else 1]
        caption = QLabel(
            f"<span style='color:{yuti_fg}; font-weight:bold;'>Y = Yuti (same sign)</span>"
            f" &nbsp;·&nbsp; values are virupas (max 60)"
            f" &nbsp;·&nbsp; <span style='color:{strong_fg}; font-weight:bold;'>&#8805;45 strong</span>"
            f" &nbsp;·&nbsp; <span style='color:{mod_fg};'>&#8805;30 moderate</span>"
        )
        caption.setStyleSheet(
            f"color: {theme['secondary_text']}; font-size: {scaled_area_px('status')}px;"
            f" background: transparent; border: none;"
        )
        wrap_layout.addWidget(caption)
        return wrap

    def _build_popup_exchange_display(self, src):
        """Exchange (Parivartana) page with FULL yoga explanations inline.

        The main panel shows short blurbs with click-for-detail links; the
        fullscreen page has the space to show everything at once.
        """
        # Fullscreen pop-out reuses the SAME widget as the docked panel, built
        # with wide=True (all cards pre-expanded). This keeps embed and pop-out
        # from ever drifting (they share one renderer). H8: no import of the
        # deleted _YOGA_DISPLAY/_YOGA_ORDER symbols, no src.toHtml() fallback.
        from apps.widgets.parivartana_widget import ParivartanaWidget
        from AI_tools.AI_main_function.interchange import get_all_interchanges
        from AI_tools.AI_main_function.final_dispositor import get_dispositor_themes

        widget = ParivartanaWidget(wide=True)
        try:
            chart = getattr(self.gui.state, 'active_chart', None)
            if chart is not None:
                # Frame sidereal at this seam too (H3) so the pop-out and the
                # docked panel show the SAME yogas in sidereal mode.
                state = getattr(self.gui, 'state', None)
                if state is not None and getattr(state, 'aditya_mode', None) == "sidereal":
                    from core.chart_factory import rebuild_chart
                    chart = rebuild_chart(chart, mode="sidereal")
                interchanges = get_all_interchanges(chart)
                themes = get_dispositor_themes(chart)
                widget.refresh(themes, interchanges)
            else:
                widget.clear()
        except Exception:
            import traceback
            traceback.print_exc()
            widget.clear()
        return widget

    # ── Enhanced popup builders for Dignities ────────────────────────

    def _build_popup_dignities_table(self, src: QTableWidget):
        """Clone dignities-in-vargas table with theme-aware dignity colors."""
        light = is_light_theme()
        theme = get_theme_colors()
        clone = self._clone_table(src, "dignities_table")

        bold = QFont()
        bold.setBold(True)
        for r in range(clone.rowCount()):
            # Column 0 = varga label
            label_item = clone.item(r, 0)
            if label_item:
                label_item.setFont(bold)
                label_item.setForeground(QBrush(QColor(theme['secondary_text'])))
            for c in range(1, clone.columnCount()):
                ci = clone.item(r, c)
                if not ci:
                    continue
                colors = self._DIGNITY_COLORS_THEMED.get(ci.text())
                if not colors:
                    continue
                dark_bg, dark_fg, light_bg, light_fg = colors
                ci.setBackground(QBrush(QColor(light_bg if light else dark_bg)))
                ci.setForeground(QBrush(QColor(light_fg if light else dark_fg)))
                if ci.text() in ("EX", "MT", "OH", "DB"):
                    ci.setFont(bold)

        from apps.delegates import RetinueColorDelegate
        dlg = RetinueColorDelegate(parent=clone)
        clone.setItemDelegate(dlg)
        clone._color_delegate = dlg
        return clone

    def _build_dignity_legend(self):
        """Color-coded legend of dignity codes + current varga style."""
        theme = get_theme_colors()
        light = is_light_theme()

        legend = QWidget()
        legend_layout = QHBoxLayout(legend)
        legend_layout.setContentsMargins(8, 6, 8, 6)
        legend_layout.setSpacing(6)
        legend.setStyleSheet(f"""
            QWidget {{
                background-color: {theme['secondary']};
                border: 1px solid {theme['secondary_light']};
                border-radius: 6px;
            }}
        """)

        ctrl = getattr(self.gui, 'dignities_controller', None)
        style_label = ctrl.varga_style_label if ctrl is not None else "Classical"
        title = QLabel(f"DIGNITIES  —  varga style: {style_label}")
        title.setFont(scaled_area_font('status', family="Inter", bold=True))
        title.setStyleSheet(f"color: {theme['secondary_text']}; border: none; background: transparent;")
        legend_layout.addWidget(title)

        for code in ("EX", "MT", "OH", "GF", "F", "N", "E", "GE", "DB"):
            dark_bg, dark_fg, light_bg, light_fg = self._DIGNITY_COLORS_THEMED[code]
            bg = light_bg if light else dark_bg
            fg = light_fg if light else dark_fg
            chip = QLabel(f"{code} {self._DIGNITY_FULL_NAMES[code]}")
            chip.setStyleSheet(
                f"background-color: {bg}; color: {fg}; font-weight: bold;"
                f" font-size: {scaled_area_px('status')}px;"
                f" padding: 3px 8px; border-radius: 4px; border: none;"
            )
            legend_layout.addWidget(chip)

        legend_layout.addStretch()
        return legend

    def _build_being_legend(self):
        """Build color-coded legend of the five being types for the karakas popup."""
        theme = get_theme_colors()

        legend = QWidget()
        legend_layout = QVBoxLayout(legend)
        legend_layout.setContentsMargins(8, 8, 8, 8)
        legend_layout.setSpacing(4)

        # SPEC-THM-001 G05: live theme color (was frozen SURFACE/BORDER).
        legend.setStyleSheet(f"""
            QWidget {{
                background-color: {theme['secondary']};
                border: 1px solid {theme['secondary_light']};
                border-radius: 6px;
            }}
        """)

        # Title
        title = QLabel("THE FIVE BEING TYPES  \u2014  Srimad Bhagavatam 12.11.33-44")
        title.setFont(scaled_area_font('status', family="Inter", bold=True))
        # SPEC-THM-001 G05: live theme color (was frozen TEXT_PRIMARY).
        title.setStyleSheet(f"color: {theme['secondary_text']}; border: none; background: transparent;")
        legend_layout.addWidget(title)

        # Being descriptions
        beings = [
            ("Gandharva", "Mars / Fire",
             "\u2609 Sun Hora \u2014 Inspires action, warrior serving a greater purpose. \"Takes you to safety.\""),
            ("Rakshasa", "Saturn / Air",
             "\u2609 Sun Hora \u2014 Pushes from behind, \"grow or suffer.\" Destroys threats permanently."),
            ("Rishi", "Jupiter / Ether",
             "\u2609\u263D Bridges BOTH Horas \u2014 Wisdom and truth that serves both solar and lunar forces."),
            ("Yaksha", "Mercury / Earth",
             "\u263D Moon Hora \u2014 Concrete environment that retrains the unconscious. \"Environment > willpower.\""),
            ("Apsara", "Venus / Water",
             "\u263D Moon Hora \u2014 Shifts moods and feelings to release unconscious blocks. Emotional alchemy."),
        ]

        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)

        for name, planet_element, desc in beings:
            bg_hex, fg_hex = self._pick_colors(self._BEING_TYPE_COLORS_THEMED, name)

            item = QWidget()
            item_layout = QVBoxLayout(item)
            item_layout.setContentsMargins(8, 6, 8, 6)
            item_layout.setSpacing(2)
            item.setStyleSheet(f"""
                QWidget {{
                    background-color: {bg_hex};
                    border-radius: 4px;
                    border: none;
                }}
            """)

            name_label = QLabel(f"{name}  ({planet_element})")
            name_label.setFont(scaled_area_font('status', family="Inter", bold=True))
            name_label.setStyleSheet(f"color: {fg_hex}; border: none; background: transparent;")
            item_layout.addWidget(name_label)

            desc_label = QLabel(desc)
            desc_label.setWordWrap(True)
            desc_label.setStyleSheet(f"color: {fg_hex}; font-size: {scaled_area_px('status')}px; border: none; background: transparent;")
            item_layout.addWidget(desc_label)

            row_layout.addWidget(item)

        row_widget.setStyleSheet("border: none; background: transparent;")
        legend_layout.addWidget(row_widget)

        # Hora side summary
        sides_layout = QHBoxLayout()
        sides_layout.setSpacing(20)

        aditya_label = QLabel("\u2609 ADITYA SIDE \u2014 Fire up your engines, actively express love")
        aditya_label.setStyleSheet(f"color: #FFD54F; font-size: {scaled_area_px('status')}px; font-weight: bold; border: none; background: transparent;")
        sides_layout.addWidget(aditya_label)

        naga_label = QLabel("\u263D NAGA SIDE \u2014 Take the brakes off, release what holds you back")
        naga_label.setStyleSheet(f"color: #80DEEA; font-size: {scaled_area_px('status')}px; font-weight: bold; border: none; background: transparent;")
        sides_layout.addWidget(naga_label)

        sides_layout.addStretch()
        legend_layout.addLayout(sides_layout)

        return legend

    # ── JSON export ────────────────────────────────────────────────

    def _copy_json(self):
        """Export all section tables as JSON to clipboard."""
        result = {"section": self.section_key, "tables": {}}

        for attr_name, label in self.section_items:
            source = getattr(self.gui, attr_name, None)
            if source is None:
                continue

            if isinstance(source, QTableWidget):
                result["tables"][label] = self._table_to_dict(source)
            elif isinstance(source, QTextEdit):
                result["tables"][label] = {
                    "type": "html",
                    "text": source.toPlainText(),
                }

        text = json.dumps(result, indent=2, ensure_ascii=False)
        QApplication.clipboard().setText(text)

        self.copy_btn.setText("Copied!")
        QTimer.singleShot(1500, lambda: self.copy_btn.setText("Copy All as JSON"))

    def _table_to_dict(self, tbl: QTableWidget) -> dict:
        """Convert QTableWidget to JSON-friendly dict."""
        cols = tbl.columnCount()
        rows = tbl.rowCount()

        headers = []
        for c in range(cols):
            item = tbl.horizontalHeaderItem(c)
            headers.append(item.text().replace("\n", " ") if item else f"col{c}")

        data_rows = []
        for r in range(rows):
            row_dict = {}
            if tbl.verticalHeader().isVisible():
                v_item = tbl.verticalHeaderItem(r)
                if v_item:
                    row_dict["_row"] = v_item.text()
            for c in range(cols):
                item = tbl.item(r, c)
                row_dict[headers[c]] = item.text() if item else ""
            data_rows.append(row_dict)

        return {"headers": headers, "rows": data_rows}


def open_panel_dialog(gui, section_key, initial_attr=None):
    """Open an InfoPanelDialog for the given section.

    ``initial_attr`` is the gui attribute of the sub-tab the user was reading;
    the dialog opens on that page instead of the section's first one
    (SPEC-AVA-002 §4.1). Omitted, it resolves from the live UI, so a caller that
    does not care still lands on the right page.

    All panels use controllers now (panel_manager is gone).
    The aspects sub-panels are DEFERRED controllers (created on first tab
    visibility), so they may not exist yet — and lazy ones gate refresh on
    visibility. Ensure each one exists, then force a direct _refresh() so
    the cloned widgets are populated.
    """
    if section_key == "aspects":
        for name in ("avastha", "shame", "interchange",
                     "tajika_matrix", "tajika_relationships", "tajika_yogas"):
            if hasattr(gui, '_ensure_controller'):
                ctrl = gui._ensure_controller(name)
            else:
                ctrl = getattr(gui, f'{name}_controller', None)
            if ctrl:
                ctrl._refresh()

    if initial_attr is None:
        initial_attr = current_subtab_attr(gui, section_key)

    dlg = InfoPanelDialog(gui, section_key, parent=gui, initial_attr=initial_attr)

    # SPEC-THM-002 §6.4 / D-7: register the dialog so a theme switch reaches it.
    # WEAKREF, not the dialog itself: a strong reference here would pin every
    # dialog the user ever opened for the life of the app — the same leak
    # SPEC-COT-001 records for its settings closures. Dead refs are pruned on
    # each pass rather than on close, so a dialog destroyed by Qt needs no
    # co-operation from us.
    import weakref
    refs = getattr(gui, "_open_panel_dialogs", None)
    if refs is None:
        refs = []
        gui._open_panel_dialogs = refs
    refs[:] = [r for r in refs if r() is not None]
    refs.append(weakref.ref(dlg))

    dlg.show()
