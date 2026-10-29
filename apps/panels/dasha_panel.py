#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""One dasha panel widget (SPEC-DSH-002 wave 3, td-9xlc, w3-2 LIVE).

`DashaPanelWidget` replaces the two byte-near-identical dasha panel factories
(the retired left/right builders): ONE class instantiated twice. Since
SPEC-DSH-004 both instances are built alike (swap button on both) and each shows
any mode of the registry. The sub-widgets are PUBLIC
attributes of the panel, not of ChartGUI (Rule 4b); the widget has NO ChartGUI
dependency and talks to the outside ONLY through its nine signals.

As of w3-2 this widget is LIVE: `DashaManager.build_panel` constructs both
instances (left/Vedanga and right/Vimshottari), wires their nine signals to the
manager's public methods, and the two retired factory files
(`apps/panels/vedanga_panel.py`, `vimshottari_panel.py`) are gone. Every style
string was copied VERBATIM from the former factory copy and routed through
`ThemedStyleMixin._register_themed` (a style_fn that re-reads `get_theme_colors()`
/ `scaled_area_px` per call), so a live theme/font switch replays through one code
path (SPEC-THM-001) and the computed pixels stay byte-identical to the factory
(the w3-2 pixel gate).

Contract details (manifest D-W3-1, rev 1.3): `side` stored for the Rule-4b AST
test and error text; NO `setObjectName` anywhere (the factories set none, a new
object name would change application-QSS selector matching); the caret in
`title_text` is the caller's concern (the LEFT/Vedanga factory uses ▾ U+25BE, the
RIGHT/Vimshottari factory ▼ U+25BC, exactly as `build_panel` passes them; the
manager normalises both to ▾ on the first `_update_dasha_title`).

Header (2026-10-22, SPEC-PANELS-001 §2.6 / SPEC-LAYOUT-001): the info panels'
Inspector Underline strip (`PanelHeader`) holding the title as the one active
`HeaderTab` and the shared `HeaderSwapButton`; the 1-5 levels are the toolbar's
segmented control under it. These widgets paint themselves from the live theme,
so they are NOT in the themed registry; `refresh_header` re-measures them.
"""

import traceback

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QButtonGroup, QComboBox, QSizePolicy
)
from PySide6.QtCore import Qt, QPoint, Signal

from ui.qt_theme import (
    scaled_px, scaled_area_px,
    ACCENTS, get_list_style, get_panel_style, get_theme_colors,
)
from ui.accent_ink import on_accent_ink  # SPEC-THM-001 §13
from ui.themed_style import ThemedStyleMixin
from ui.button_area_style import button_area_font_px
from apps.widgets.panel_header import (
    HeaderSwapButton, HeaderTab, PanelHeader, SegmentButton, SegmentedControl, set_scale_cap,
)


def _display_scale() -> float:
    return scaled_px(100) / 100.0


def cap_header_plates(*widgets) -> None:
    """The dasha column is a fixed 265 px: its title padding and plate buttons
    stop growing at the Display Scale, so a large Panel Titles size enlarges
    the title text (which elides) without pushing the swap out of the strip
    (review 2026-10-22)."""
    for w in widgets:
        set_scale_cap(w, _display_scale)
from apps.delegates import DashaHighlightDelegate
from apps.panels.dasha_presentation import DashaPresentationMixin

# Panel width constant (shared between both dasha panels; moved off the factories).
DASHA_PANEL_WIDTH = 265  # Increased by 70px for better period visibility


class _Keep:
    """Sentinel for `set_shape`: a KEEP field is not written."""
    __slots__ = ()

    def __repr__(self):
        return "KEEP"


KEEP = _Keep()


def _column_label_style(accent):
    """Karaka/Cusp/House column-label QSS (SPEC-FONT-001, 'buttons' area).

    ONE builder shared by construction and live refresh so a per-area font
    change re-resolves the size and a colour edit can never drop it (verbatim
    from the retired factories)."""
    theme = get_theme_colors()
    return (f"color: {accent}; font-size: {scaled_area_px('buttons')}px; "
            f"font-weight: bold; "
            f"background-color: {theme['secondary_dark']}; "
            f"border: 1px solid {theme['secondary']}; border-radius: 3px; "
            f"padding: 0px {scaled_px(8)}px;")


# --- theme-reading style builders (verbatim factory f-strings) -------------- #
# Each reads get_theme_colors() / scaled_* on EVERY call (the _register_themed
# contract), so the produced string is byte-identical to the factory's under the
# same palette.

def _nav_frame_style():
    theme = get_theme_colors()
    return f"background-color: {theme['secondary']};"


def _arrow_style():
    theme = get_theme_colors()
    return f"""
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
            color: {on_accent_ink(theme["primary"], theme["primary_text"])};
        }}
    """


def _cycle_label_style():
    theme = get_theme_colors()
    return (f"color: {theme['secondary_text']}; font-size: {scaled_area_px('status')}px; "
            f"font-weight: bold; background: transparent;")


def _combo_style():
    theme = get_theme_colors()
    return f"""
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
            selection-color: {on_accent_ink(theme["primary"], theme["primary_text"])};
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


class DashaPanelWidget(DashaPresentationMixin, ThemedStyleMixin, QWidget):
    """One dasha column: header (title [+ swap], level buttons), nav row, list,
    three lord combos. Owns its sub-widgets as public attributes; emits nine
    signals; never references a ChartGUI."""

    level_requested = Signal(int)            # 1..5, from the level buttons
    drill_requested = Signal(object)         # QListWidgetItem, from itemDoubleClicked
    select_requested = Signal(object)        # QListWidgetItem, from itemClicked
    prev_requested = Signal()
    next_requested = Signal()
    title_clicked = Signal()
    swap_requested = Signal()
    context_menu_requested = Signal(QPoint)  # from customContextMenuRequested
    lord_filter_changed = Signal()           # any of the three combos
    swap_menu_requested = Signal()           # right-click on the swap button
    # SPEC-LAYOUT-001 (right panel only): presentation buttons.
    fold_requested = Signal()                # fold button: side Full <-> Rail
    dock_requested = Signal()                # Bottom button: dock to the shelf
    return_requested = Signal()              # Return to side (from the shelf)

    def __init__(self, side, *, accent, title_text, swap_tooltip, parent=None):
        super().__init__(parent)
        if side not in ("left", "right"):
            raise ValueError(f"side must be 'left' or 'right', got {side!r}")
        self.side = side
        # The active chart when the list was last filled (None = cleared or
        # never filled); read by the AI capture regions (SPEC-AIC-001).
        self.rendered_chart = None
        self._accent = accent

        self.setFixedWidth(DASHA_PANEL_WIDTH)
        self._register_themed(self, get_panel_style)          # panel

        layout = QVBoxLayout(self)
        layout.setSpacing(3)
        layout.setContentsMargins(5, 5, 5, 5)
        # meta (header + nav [+ shelf extras]) and filters are wrappers so the
        # shelf presentation can lay the panel out left-to-right (SPEC-LAYOUT-001
        # A.1); in the column their spacing equals the former flat layout.
        self.meta = QWidget()
        # Never grow vertically: on the rail the title row turns vertical and its
        # stretch would otherwise make meta share the list's height.
        self.meta.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        meta_layout = QVBoxLayout(self.meta)
        meta_layout.setContentsMargins(0, 0, 0, 0)
        meta_layout.setSpacing(3)
        self.filters = QWidget()
        filters_layout = QVBoxLayout(self.filters)
        filters_layout.setContentsMargins(0, 0, 0, 0)
        filters_layout.setSpacing(3)

        # === HEADER: title strip (title + swap), then the level control ===
        # SPEC-PANELS-001 §2.6 / SPEC-LAYOUT-001: the Inspector Underline strip
        # of the info panel headers. Every header widget PAINTS itself from the
        # live theme and the 'panel_titles' area (no stylesheet, not in the
        # themed registry); refresh_theme / refresh_fonts re-measure them.
        self.header = QWidget()
        header_vlayout = QVBoxLayout(self.header)
        header_vlayout.setContentsMargins(0, 0, 0, 0)
        header_vlayout.setSpacing(scaled_px(4))

        # own_surface: the strip carries the info frames' surface, so it reads
        # the same tone as the info headers on the darker dasha panel.
        self.title_strip = PanelHeader(own_surface=True)
        title_row = QHBoxLayout(self.title_strip)
        title_row.setContentsMargins(scaled_px(4), 0, scaled_px(6), 0)
        title_row.setSpacing(scaled_px(2))

        self.title_btn = HeaderTab(title_text)
        self.title_btn.set_active(True)          # the panel's one "tab": its title
        self.title_btn.set_elide(True)           # long titles end in "…", never clip both ends
        self.title_btn.setToolTip("Click to change ayanamsa")
        self.title_btn.clicked.connect(lambda: self.title_clicked.emit())
        title_row.addWidget(self.title_btn)

        self.swap_btn = HeaderSwapButton()
        self.swap_btn.setToolTip(swap_tooltip)
        self.swap_btn.setAccessibleName(swap_tooltip)
        self.swap_btn.clicked.connect(lambda: self.swap_requested.emit())
        self.swap_btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.swap_btn.customContextMenuRequested.connect(
            lambda _pos: self.swap_menu_requested.emit())
        title_row.addWidget(self.swap_btn)
        title_row.addStretch()
        header_vlayout.addWidget(self.title_strip)
        cap_header_plates(self.title_btn, self.swap_btn)

        # Level control (right-aligned): the toolbar's segmented control.
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(0)
        btn_row.addStretch()
        self.level_segments = SegmentedControl()
        self.level_buttons = []
        self.level_group = QButtonGroup(self)                  # parented to the panel
        self.level_group.setExclusive(True)
        for i in range(1, 6):
            # the digits keep following the 'buttons' font area (td-to202)
            btn = SegmentButton(str(i), font_px=lambda: button_area_font_px("small"))
            btn.setChecked(i == 1)
            btn.clicked.connect(lambda checked=False, lvl=i: self.level_requested.emit(lvl))
            self.level_group.addButton(btn, i)
            self.level_buttons.append(btn)
            self.level_segments.add_segment(btn)
        btn_row.addWidget(self.level_segments)
        header_vlayout.addLayout(btn_row)
        meta_layout.addWidget(self.header)

        # === NAV row: prev, cycle label, next ===
        self.nav_frame = QWidget()
        self._register_themed(self.nav_frame, _nav_frame_style)  # nav_frame
        nav_layout = QHBoxLayout(self.nav_frame)
        nav_layout.setContentsMargins(4, 4, 4, 4)
        nav_layout.setSpacing(2)

        self.prev_btn = QPushButton("<")
        self.prev_btn.setToolTip("Previous 120-year cycle (past)")
        self._register_themed(self.prev_btn, _arrow_style)       # prev arrow
        self.prev_btn.clicked.connect(lambda: self.prev_requested.emit())
        nav_layout.addWidget(self.prev_btn)

        self.cycle_label = QLabel("0-120y")
        self.cycle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._register_themed(self.cycle_label, _cycle_label_style)  # cycle label
        nav_layout.addWidget(self.cycle_label, 1)

        self.next_btn = QPushButton(">")
        self.next_btn.setToolTip("Next 120-year cycle (future)")
        self._register_themed(self.next_btn, _arrow_style)       # next arrow
        self.next_btn.clicked.connect(lambda: self.next_requested.emit())
        nav_layout.addWidget(self.next_btn)

        meta_layout.addWidget(self.nav_frame)
        layout.addWidget(self.meta, 0, Qt.AlignmentFlag.AlignTop)   # shelf: meta box at the top
        layout.addSpacing(4)

        # === LIST ===
        self.list_widget = QListWidget()
        self._register_themed(self.list_widget, lambda a=accent: get_list_style(a))  # list
        # doItemsLayout follows the list restyle (core_gui 5753) — a themed effect.
        self._register_themed_effect(self.list_widget, lambda w: w.doItemsLayout())
        self.delegate = DashaHighlightDelegate(parent=self.list_widget)
        self.list_widget.setItemDelegate(self.delegate)
        self.list_widget.itemClicked.connect(lambda item: self.select_requested.emit(item))
        self.list_widget.itemDoubleClicked.connect(lambda item: self.drill_requested.emit(item))
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(
            lambda pos: self.context_menu_requested.emit(pos))
        layout.addWidget(self.list_widget)

        # === LORD COMBOS (Karaka / Cusp / House) ===
        self.karaka_combo = self._build_combo(
            filters_layout, "Karaka", ACCENTS['gold']['base'],
            [("None", None)] + [(c, c) for c in ["AK", "AmK", "BK", "MK", "PiK", "GK", "DK"]])
        self.cusp_combo = self._build_combo(
            filters_layout, "Cusp", ACCENTS['cyan']['base'],
            [("None", None)] + [(f"{h}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(h, 'th') }", h)
                                for h in range(1, 13)])
        self.ws_combo = self._build_combo(
            filters_layout, "House", ACCENTS['orange']['base'],
            [("None", None)] + [(f"{h}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(h, 'th') }", h)
                                for h in range(1, 13)])
        layout.addWidget(self.filters)
        self._fit_lord_labels()
        self._init_presentation(title_row, meta_layout)
        self.fit_header()

    def mark_rendered(self, chart):
        """Record the chart the list now shows (None when cleared)."""
        self.rendered_chart = chart
        if self.presentation != "full":   # rail/shelf: current tile + scroll follow the data
            self.update_current_summary()
            self.relayout_items()

    def _build_combo(self, layout, label_text, label_accent, items):
        """One (label, combo) row; register the combo themed, the label themed,
        record the (label, accent) pair for the column-label font pass."""
        row = QHBoxLayout()
        row.setContentsMargins(2, 1, 2, 1)
        row.setSpacing(scaled_px(6))
        # Lorris 2026-09-07: the label is a padded chip (same fill, border,
        # radius and height as the combo, text centred, 8px side padding) so
        # the two read as ONE form row; the combo fills the rest of the width.
        lbl = QLabel(label_text)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._register_themed(lbl, lambda a=label_accent: _column_label_style(a))  # column label
        combo = QComboBox()
        self._register_themed(combo, _combo_style)             # combo
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        combo.setMinimumWidth(scaled_px(84))
        combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        for text, data in items:
            combo.addItem(text, data)
        combo.currentIndexChanged.connect(lambda _=None: self.lord_filter_changed.emit())
        row.addWidget(lbl)
        row.addWidget(combo, 1)
        layout.addLayout(row)
        self.__dict__.setdefault("_dasha_column_labels", []).append((lbl, label_accent))
        self.__dict__.setdefault("_dasha_lord_rows", []).append((lbl, combo))
        return combo

    def _fit_lord_labels(self):
        """Give the three lord-filter labels ONE shared width = the widest label
        text at the CURRENT (QSS-resolved) font + a small gap, so the combos line
        up and no label is clipped. Re-run after every column-label style replay
        (refresh_fonts) because the 'buttons' area size can change live."""
        rows = list(getattr(self, "_dasha_lord_rows", ()))
        if not rows:
            return
        widest = 0
        tallest = 0
        for lbl, combo in rows:
            lbl.ensurePolished()                     # QSS font-size applied
            combo.ensurePolished()
            widest = max(widest, lbl.fontMetrics().horizontalAdvance(lbl.text()))
            tallest = max(tallest, combo.sizeHint().height())
        # text + 8px padding each side + 1px border each side (see the chip QSS)
        w = widest + 2 * scaled_px(8) + 2
        for lbl, _combo in rows:
            lbl.setFixedSize(w, tallest)             # chip == combo height

    # ----------------------------------------------------------------------- #
    # Shape / content mutators (each replaces a helper in the manifest matrix) #
    # ----------------------------------------------------------------------- #

    def set_shape(self, *, levels, nav, title=KEEP, title_tooltip=KEEP,
                  title_enabled=KEEP):
        """Structural reshape: title (non-KEEP fields) -> nav -> levels, the
        Nisarga/Vimshottari order (manifest D-W3-1). Never touches the list, the
        delegate, the combos, the swap button or the cycle label."""
        # title
        if title is not KEEP:
            self.title_btn.setText(title)
        if title_tooltip is not KEEP:
            self.title_btn.setToolTip(title_tooltip)
        if title_enabled is not KEEP:
            self.title_btn.setEnabled(title_enabled)
        # nav
        if nav == "cycle":
            shown = True
            self.prev_btn.setText("<")
            self.prev_btn.setToolTip("Previous 120-year cycle (past)")
            self.prev_btn.setVisible(True)
            self.next_btn.setToolTip("Next 120-year cycle (future)")   # set_nav may have changed it
            self.next_btn.setVisible(True)
        elif nav == "strip":
            shown = True
            self.prev_btn.setText("◀")               # ◀ Back one level
            self.prev_btn.setToolTip("Back one level")
            # prev visibility NOT touched (set_strip drives it inside the renderer)
            self.next_btn.setVisible(False)
        elif nav == "chara":
            # Renderer-driven nav shape (SPEC-DSH-004 §3.6, no LTS mode uses it):
            # the renderer writes the arrows and the label per level through
            # set_nav; here only the frame is shown.
            shown = True
        elif nav == "hidden":
            shown = False
            # prev/next restored to the "cycle" texts and visibility
            self.prev_btn.setText("<")
            self.prev_btn.setToolTip("Previous 120-year cycle (past)")
            self.prev_btn.setVisible(True)
            self.next_btn.setToolTip("Next 120-year cycle (future)")   # set_nav may have changed it
            self.next_btn.setVisible(True)
        else:
            raise ValueError(f"nav must be cycle/strip/chara/hidden, got {nav!r}")
        # nav frame + levels: recorded as the mode shape, applied together
        # with the presentation (SPEC-LAYOUT-001 D4)
        self._record_shape(nav=shown, levels=levels)
        self.set_level_checked(1)

    def set_strip(self, *, prev_visible, text):
        """ZR context strip (the two writes of `_update_zr_strip`)."""
        self.prev_btn.setVisible(prev_visible)
        self.cycle_label.setText(text)

    def set_nav(self, *, prev_text, prev_tooltip, prev_visible, next_visible,
                next_tooltip, text):
        """Every nav-row field at once (for a renderer that drives the whole row)."""
        self.prev_btn.setText(prev_text)
        self.prev_btn.setToolTip(prev_tooltip)
        self.prev_btn.setVisible(prev_visible)
        self.next_btn.setToolTip(next_tooltip)
        self.next_btn.setVisible(next_visible)
        self.cycle_label.setText(text)

    def set_cycle_label(self, text):
        self.cycle_label.setText(text)

    def set_title(self, text, tooltip=None, enabled=None):
        self.title_btn.setText(text)
        if tooltip is not None:
            self.title_btn.setToolTip(tooltip)
        if enabled is not None:
            self.title_btn.setEnabled(enabled)

    def set_level_checked(self, level):
        """Verbatim loop (NOT a single setChecked(True) on the target: the
        exclusive group would emit `toggled` in a different order)."""
        for i, b in enumerate(self.level_buttons):
            b.setChecked(i == level - 1)

    def lord_selection(self):
        return (self.karaka_combo.currentData(),
                self.cusp_combo.currentData(),
                self.ws_combo.currentData())

    def set_lord_selection(self, *, karaka=None, cusp=None, ws=None):
        """Index by data (None -> index 0); order karaka -> cusp -> ws (the order
        of the remote setter, so the same three currentIndexChanged emissions
        occur)."""
        for combo, data in ((self.karaka_combo, karaka),
                            (self.cusp_combo, cusp),
                            (self.ws_combo, ws)):
            idx = combo.findData(data)
            combo.setCurrentIndex(idx if idx >= 0 else 0)

    # ----------------------------------------------------------------------- #
    # Theme / font replay                                                      #
    # ----------------------------------------------------------------------- #

    def refresh_header(self):
        """Re-measure and repaint the painted header (strip, title, swap, fold /
        Bottom buttons, level control) under the current theme, 'panel_titles'
        font and Display Scale. Nothing to restyle: they read the theme at paint
        time (SPEC-PANELS-001 §2.6)."""
        self.title_strip.refresh()
        self.title_btn.sync_font()
        self.level_segments.refresh()
        self.fit_header()

    def refresh_theme(self):
        """Replay every registered style_fn under the current palette (the list
        restyle among them, then the themed effects — doItemsLayout after the list
        restyle), then repaint the painted header LAST."""
        self._replay_themed()
        self.refresh_header()

    def refresh_fonts(self):
        """The registry/effect replay + the column-label pass (the folded-in
        retired module-level column-label font refresher) + the header re-measure.

        Full cascade order (w3-2c sol finding 3): the registered style_fns replay
        (the list restyle among them), THEN the themed EFFECTS run
        (list_widget.doItemsLayout after its restyle), THEN the column-label pass
        below re-runs, and the painted header is re-measured LAST. Each column
        label is isolated (per-label try/except) so one dead C++ label cannot
        abort the rest — the same per-entry isolation _replay_themed gives the
        registry. Does NOT call refresh_theme(), so the header is refreshed
        exactly once, after the column labels."""
        self._replay_themed()
        for lbl, accent in getattr(self, "_dasha_column_labels", ()):
            try:
                lbl.setStyleSheet(_column_label_style(accent))
            except Exception:
                traceback.print_exc()
        self._fit_lord_labels()           # widths follow the replayed font
        self.refresh_header()             # LAST, after the column-label pass
        if self.presentation != "full":   # tile/card sizes follow the font
            self.update_current_summary()
            self.relayout_items()
