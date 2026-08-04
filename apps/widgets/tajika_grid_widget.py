# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""
Tajika Grid Widget - shared 4-cell Tajika display (SPEC-ECL-002 section 9)

The single implementation of the tajika grid UI population, extracted from
the Solar Return page's inline copy (td-n3h3.5). Canonical output is the SR
grid's rendering: ASCII '--' diagonal, SR pair separator and orb formats, SR
yoga colors/structure, SR empty-state texts. Consumed by:
- Solar Return page (pro/panels/solar_return_page.py)
- Personal Eclipse page (td-n3h3.10)
- Main-window tajika panel controllers (follow-up wave td-n3h3.13, which
  delegates to the module-level fill functions below)

One intended behavior change vs the old SR copy: the matrix body list comes
from the engine's TAJIKA_PLANETS ("Ascendant", not "Lagna"), which fixes the
live SR blank-Lagna row/column bug (research delta B2). Everything else is
byte-identical (gate: test/sr_tajika_parity_capture.py).

Layer rule: this module lives in apps/ (base layer), never imports pro/.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QGridLayout,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QTextEdit, QPushButton
)
from PySide6.QtCore import Qt, Signal

from ui.qt_theme import get_theme_colors, desat_hex
from ui.themed_style import ThemedStyleMixin
from apps.delegates.highlight_delegate import TajikaHighlightDelegate
from AI_tools.AI_main_function.tajika import (
    TAJIKA_PLANETS, TAJIKA_SHORT_NAMES, calculate_all_tajika_aspects,
)
from AI_tools.AI_main_function.tajika_yogas import detect_all_tajika_yogas
from AI_tools.AI_main_function.tajika_cross import cross_chart_tajika


# ---------------------------------------------------------------------------
# Shared constants (single copy; SR page and controllers import from here)
# ---------------------------------------------------------------------------

# Header list derived from the engine's canonical body order/short names,
# so headers and matrix lookups cannot drift apart again.
TAJIKA_HEADERS = [TAJIKA_SHORT_NAMES[body] for body in TAJIKA_PLANETS]

_ASPECT_TO_SHAPE = {
    "Conjunction": "conjunction",
    "Sextile": "sextile",
    "Square": "square",
    "Trine": "trine",
    "Opposition": "opposition",
}

_REL_TO_CATEGORY = {
    "Openly Friendly": "FRIENDLY_OPEN",
    "Secretly Friendly": "FRIENDLY_SECRET",
    "Neutral": "NEUTRAL",
    "Secretly Inimical": "INIMICAL_SECRET",
    "Openly Inimical": "INIMICAL_OPEN",
}

_YOGA_CATEGORY_ORDER = ["SUCCESS", "FAILURE", "DISRUPTION", "VOID", "TRANSFER", "SPECIAL"]

_SPEED_PLANET_ORDER = ["Sun", "Moon", "Mars", "Mercury", "Jupiter",
                       "Venus", "Saturn", "Uranus", "Neptune", "Pluto"]


# ---------------------------------------------------------------------------
# Module-level fill functions (controllers will delegate here, td-n3h3.13)
# ---------------------------------------------------------------------------

def fill_matrix(table, delegate, result):
    """Fill an 11x11 Tajika aspect matrix table from a
    calculate_all_tajika_aspects() result. Bodies come from the engine's
    TAJIKA_PLANETS so the Ascendant row/column resolves (the old SR copy
    looked up "Lagna" and rendered them blank)."""
    matrix = result.get("matrix", {})
    bodies = TAJIKA_PLANETS
    short = TAJIKA_HEADERS

    cell_categories = {}
    cell_shapes = {}

    for row_idx, body1 in enumerate(bodies):
        for col_idx, body2 in enumerate(bodies):
            if row_idx == col_idx:
                item = QTableWidgetItem("--")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(row_idx, col_idx, item)
                cell_shapes[(row_idx, col_idx)] = "diagonal"
                continue

            key = (body1, body2)
            rev_key = (body2, body1)
            record = matrix.get(key) or matrix.get(rev_key)

            if not record:
                item = QTableWidgetItem("")
                table.setItem(row_idx, col_idx, item)
                continue

            symbol = record.get("symbol", "")
            aspect_name = record.get("aspect", "")
            virupas = record.get("virupas", 0)
            rel = record.get("relationship", "")
            dist = record.get("distance_from_exact", 0)

            item = QTableWidgetItem(symbol)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            tip = (f"{short[row_idx]}-{short[col_idx]}: {aspect_name}\n"
                   f"{virupas:.0f} VR | {dist:.1f} from exact\n{rel}")
            item.setToolTip(tip)
            table.setItem(row_idx, col_idx, item)

            shape = _ASPECT_TO_SHAPE.get(aspect_name)
            if shape:
                cell_shapes[(row_idx, col_idx)] = shape

            if virupas >= 45:
                cell_categories[(row_idx, col_idx)] = "STRONG"
            else:
                cat = _REL_TO_CATEGORY.get(rel, "NEUTRAL")
                cell_categories[(row_idx, col_idx)] = cat

    delegate.update_categories(cell_categories)
    delegate.update_shapes(cell_shapes)
    table.viewport().update()


def fill_relations(table, delegate, result):
    """Fill the relations table (grouped by relationship) from a
    calculate_all_tajika_aspects() result."""
    aspects = result.get("aspects_within_orb", [])
    table.clearContents()
    table.setRowCount(0)

    if not aspects:
        table.setRowCount(1)
        item = QTableWidgetItem("No aspects within orb")
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        table.setItem(0, 0, item)
        table.setSpan(0, 0, 1, 5)
        # Drop the previous chart's per-cell maps too, or the empty-state
        # row inherits stale category coloring (codex review F6).
        delegate.update_categories({})
        delegate.update_shapes({})
        table.viewport().update()
        return

    groups = [
        ("Openly Friendly", []), ("Secretly Friendly", []),
        ("Neutral", []), ("Secretly Inimical", []), ("Openly Inimical", []),
    ]
    group_dict = {name: lst for name, lst in groups}
    for asp in aspects:
        rel = asp.get("relationship", "Neutral")
        group_dict.get(rel, group_dict["Neutral"]).append(asp)

    total = sum(1 + len(lst) for _, lst in groups if lst)
    table.setRowCount(total)

    cell_categories = {}
    cell_shapes = {}
    row = 0

    for group_name, group_aspects in groups:
        if not group_aspects:
            continue
        cat = _REL_TO_CATEGORY.get(group_name, "NEUTRAL")
        header_item = QTableWidgetItem(f"{group_name} ({len(group_aspects)})")
        header_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        table.setItem(row, 0, header_item)
        table.setSpan(row, 0, 1, 5)
        for c in range(5):
            cell_categories[(row, c)] = cat
        row += 1

        for asp in group_aspects:
            shape_item = QTableWidgetItem("")
            shape_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(row, 0, shape_item)
            shape_key = _ASPECT_TO_SHAPE.get(asp.get("aspect", ""))
            if shape_key:
                cell_shapes[(row, 0)] = shape_key
            cell_categories[(row, 0)] = cat

            table.setItem(row, 1, QTableWidgetItem(
                f"{asp['body1']}-{asp['body2']}"))
            cell_categories[(row, 1)] = cat

            table.setItem(row, 2, QTableWidgetItem(asp.get("aspect", "")))
            cell_categories[(row, 2)] = cat

            vr_item = QTableWidgetItem(f"{asp.get('virupas', 0):.0f}")
            vr_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(row, 3, vr_item)
            cell_categories[(row, 3)] = cat

            orb_item = QTableWidgetItem(f"{asp.get('distance_from_exact', 0):.1f}")
            orb_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(row, 4, orb_item)
            cell_categories[(row, 4)] = cat

            row += 1

    delegate.update_categories(cell_categories)
    delegate.update_shapes(cell_shapes)
    table.viewport().update()


def fill_yogas(text_edit, yogas):
    """Fill the yogas QTextEdit from a detect_all_tajika_yogas() result
    (pass None when detection failed)."""
    theme = get_theme_colors()
    if yogas is None:
        text_edit.setHtml(
            f'<p style="color:{theme["secondary_text"]}">Yogas unavailable</p>')
        return

    all_yogas = yogas.get("all_yogas", [])
    if not all_yogas:
        text_edit.setHtml(
            f'<p style="color:{theme["secondary_text"]}; text-align:center; padding:20px;">'
            f'No Tajika yogas detected</p>')
        return

    cat_colors = {
        "SUCCESS": desat_hex("#4CAF50"),
        "FAILURE": desat_hex("#F44336"),
        "DISRUPTION": desat_hex("#FF9800"),
        "VOID": theme["secondary_text"],
        "TRANSFER": theme["primary"],
        "SPECIAL": theme["primary"],
    }

    html = f'<div style="padding:4px;">'

    for cat in _YOGA_CATEGORY_ORDER:
        cat_yogas = yogas.get("yogas_by_category", {}).get(cat, [])
        if not cat_yogas:
            continue
        color = cat_colors.get(cat, theme["secondary_text"])
        html += (
            f'<div style="padding:2px 4px; margin-top:4px; '
            f'border-left:3px solid {color}; background-color:{theme["secondary"]};">'
            f'<b style="color:{color}; font-size:11px;">{cat} ({len(cat_yogas)})</b></div>')

        for yoga in cat_yogas:
            yname = yoga.get("yoga_name", "")
            subtype = yoga.get("subtype", "")
            planets_short = yoga.get("planets_short", "")
            description = yoga.get("description", "")
            effect = yoga.get("effect", "")

            label = f'<b style="color:{color};">{yname}</b>'
            if subtype:
                label += f' <span style="color:{theme["secondary_text"]};">({subtype})</span>'

            html += (
                f'<div style="padding:2px 4px 2px 8px; '
                f'border-bottom:1px solid {theme["secondary_light"]};">'
                f'{label} <span style="font-size:10px; color:{theme["secondary_text"]};">'
                f'[{planets_short}]</span><br/>'
                f'<span style="font-size:10px; color:{theme["secondary_text"]};">'
                f'{description}</span><br/>'
                f'<i style="font-size:10px; color:{theme["secondary_text"]};">'
                f'{effect}</i></div>')

    html += '</div>'
    text_edit.setHtml(html)


def fill_speeds(table, chart):
    """Fill the planet speed table with speed and retrograde status."""
    rows = []
    for sign in chart.ecliptic():
        for p in sign.planets():
            n = p.name().replace(" (R)", "")
            if n in _SPEED_PLANET_ORDER:
                rows.append((n, p.speed(), p.retrograde()))

    order_map = {n: i for i, n in enumerate(_SPEED_PLANET_ORDER)}
    rows.sort(key=lambda r: order_map.get(r[0], 99))

    table.setRowCount(len(rows))
    for i, (name, speed, retro) in enumerate(rows):
        name_item = QTableWidgetItem(name)
        name_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        table.setItem(i, 0, name_item)

        speed_item = QTableWidgetItem(f"{speed:+.4f}°/d")
        speed_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        table.setItem(i, 1, speed_item)

        if retro:
            status_item = QTableWidgetItem("R")
            status_item.setForeground(Qt.GlobalColor.red)
        else:
            status_item = QTableWidgetItem("D")
            status_item.setForeground(Qt.GlobalColor.green)
        status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        font = status_item.font()
        font.setBold(True)
        status_item.setFont(font)
        table.setItem(i, 2, status_item)


# ---------------------------------------------------------------------------
# Widget
# ---------------------------------------------------------------------------

class TajikaGridWidget(ThemedStyleMixin, QWidget):
    """4-cell Tajika display: 11x11 aspect matrix, relations table, yogas
    text, planet speeds table. One public entry point: refresh(chart).

    closeRequested fires when the user clicks the grid's own close (✕)
    control. Hosts that dock the grid into a collapsible pane wire this to
    their hide path so there is always a reachable off-switch even when the
    pane holding the header toggle button is collapsed (td-rl77)."""

    closeRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        # Last successful refresh inputs/results, replayed by refresh_theme
        # (the yoga HTML embeds theme colors at fill time, codex review F5).
        self._last_chart = None
        self._last_include_minor = False
        self._last_yogas = None
        self._create_ui()

    def _create_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(4)

        # Close bar: an off-switch that lives ON the grid (which never
        # collapses), so a host whose header toggle button sits in a
        # collapsible pane can still be dismissed when that pane is at zero
        # width (td-rl77). Hidden until a host calls set_close_visible(True).
        self._close_bar = QWidget()
        close_row = QHBoxLayout(self._close_bar)
        close_row.setContentsMargins(2, 0, 2, 0)
        close_row.setSpacing(4)
        self._close_title = QLabel("Tajika Aspects")
        self._register_themed(self._close_title, self._grid_label_style)
        close_row.addWidget(self._close_title)
        close_row.addStretch()
        self.close_btn = QPushButton("✕")
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setFixedWidth(28)
        self.close_btn.setToolTip("Hide the Tajika grid")
        self._register_themed(self.close_btn, self._close_btn_style)
        self.close_btn.clicked.connect(self.closeRequested)
        close_row.addWidget(self.close_btn)
        self._close_bar.setVisible(False)
        outer.addWidget(self._close_bar)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)
        outer.addLayout(grid, 1)

        # All frame/table/label styling flows through the ThemedStyleMixin
        # registry so it replays under the new palette on a theme switch.

        # Cell (0,0): Tajika Aspects Matrix (11x11)
        matrix_frame = QFrame()
        self._register_themed(matrix_frame, self._cell_style)
        matrix_layout = QVBoxLayout(matrix_frame)
        matrix_layout.setContentsMargins(2, 2, 2, 2)
        matrix_layout.setSpacing(0)

        matrix_label = QLabel("Aspects T")
        matrix_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._register_themed(matrix_label, self._grid_label_style)
        matrix_layout.addWidget(matrix_label)

        self.matrix_table = QTableWidget(11, 11)
        self.matrix_table.setHorizontalHeaderLabels(TAJIKA_HEADERS)
        self.matrix_table.setVerticalHeaderLabels(TAJIKA_HEADERS)
        self._register_themed(self.matrix_table, self._table_style)
        self.matrix_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.matrix_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.matrix_table.verticalHeader().setDefaultSectionSize(20)
        self.matrix_table.verticalHeader().setMinimumWidth(25)
        self.matrix_table.horizontalHeader().setDefaultSectionSize(20)
        for col in range(11):
            self.matrix_table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.Stretch)

        self.matrix_delegate = TajikaHighlightDelegate(parent=self.matrix_table)
        self.matrix_table.setItemDelegate(self.matrix_delegate)
        matrix_layout.addWidget(self.matrix_table, 1)
        grid.addWidget(matrix_frame, 0, 0, 1, 2)

        # Cell (0,2): Tajika Relations
        rel_frame = QFrame()
        self._register_themed(rel_frame, self._cell_style)
        rel_layout = QVBoxLayout(rel_frame)
        rel_layout.setContentsMargins(2, 2, 2, 2)
        rel_layout.setSpacing(0)

        rel_label = QLabel("Relations")
        rel_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._register_themed(rel_label, self._grid_label_style)
        rel_layout.addWidget(rel_label)

        self.rel_table = QTableWidget()
        self.rel_table.setColumnCount(5)
        self.rel_table.setHorizontalHeaderLabels(["", "Pair", "Aspect", "VR", "Orb"])
        self.rel_table.verticalHeader().setVisible(False)
        self._register_themed(self.rel_table, self._table_style)
        self.rel_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.rel_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.rel_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.rel_table.setColumnWidth(0, 24)
        for col in range(1, 5):
            self.rel_table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.Stretch)
        self.rel_table.verticalHeader().setDefaultSectionSize(20)

        self.rel_delegate = TajikaHighlightDelegate(parent=self.rel_table)
        self.rel_table.setItemDelegate(self.rel_delegate)
        rel_layout.addWidget(self.rel_table, 1)
        grid.addWidget(rel_frame, 0, 2, 1, 2)

        # Cell (1,0): Tajika Yogas
        yogas_frame = QFrame()
        self._register_themed(yogas_frame, self._cell_style)
        yogas_layout = QVBoxLayout(yogas_frame)
        yogas_layout.setContentsMargins(2, 2, 2, 2)
        yogas_layout.setSpacing(0)

        yogas_label = QLabel("Yogas")
        yogas_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._register_themed(yogas_label, self._grid_label_style)
        yogas_layout.addWidget(yogas_label)

        self.yogas_text = QTextEdit()
        self.yogas_text.setReadOnly(True)
        self._register_themed(self.yogas_text, self._yogas_text_style)
        yogas_layout.addWidget(self.yogas_text, 1)
        grid.addWidget(yogas_frame, 1, 0, 1, 2)

        # Cell (1,2)-(1,3): Planet Speeds & Retrograde
        speed_frame = QFrame()
        self._register_themed(speed_frame, self._cell_style)
        speed_layout = QVBoxLayout(speed_frame)
        speed_layout.setContentsMargins(2, 2, 2, 2)
        speed_layout.setSpacing(0)

        speed_label = QLabel("Planet Speeds")
        speed_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._register_themed(speed_label, self._grid_label_style)
        speed_layout.addWidget(speed_label)

        self.speed_table = QTableWidget()
        self.speed_table.setColumnCount(3)
        self.speed_table.setHorizontalHeaderLabels(["Planet", "Speed", "Status"])
        self.speed_table.verticalHeader().setVisible(False)
        self._register_themed(self.speed_table, self._table_style)
        self.speed_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.speed_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.speed_table.verticalHeader().setDefaultSectionSize(20)
        for col in range(3):
            self.speed_table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.Stretch)
        speed_layout.addWidget(self.speed_table, 1)
        grid.addWidget(speed_frame, 1, 2, 1, 2)

        # Equal row/col stretch
        for r in range(2):
            grid.setRowStretch(r, 1)
        for c in range(4):
            grid.setColumnStretch(c, 1)

    # ── Population ──

    def refresh(self, chart, include_minor=False):
        """Populate all four cells from the chart. Calls the engine ONCE per
        function (aspects, then yogas) and fans out via the module fills.

        chart None renders the empty state; an engine failure renders the
        empty state and RE-RAISES, so the previous chart's data is never
        left on screen either way (codex review F1)."""
        if chart is None:
            self.clear()
            return
        try:
            result = calculate_all_tajika_aspects(chart, include_minor=include_minor)
        except Exception:
            self.clear()
            raise

        fill_matrix(self.matrix_table, self.matrix_delegate, result)
        fill_relations(self.rel_table, self.rel_delegate, result)
        try:
            yogas = detect_all_tajika_yogas(chart, result)
        except Exception:
            yogas = None
        fill_yogas(self.yogas_text, yogas)
        fill_speeds(self.speed_table, chart)

        self._last_chart = chart
        self._last_include_minor = include_minor
        self._last_yogas = yogas

    def clear(self):
        """Render the no-data state: all four cells emptied and the delegate
        category/shape maps dropped, so a swap to a chartless side or a
        failed refresh never shows the previous chart's data (codex review
        F1). Also forgets the stored theme-replay data (F5)."""
        self.matrix_table.clearContents()
        self.matrix_delegate.update_categories({})
        self.matrix_delegate.update_shapes({})
        self.matrix_table.viewport().update()

        self.rel_table.clearContents()
        self.rel_table.setRowCount(0)
        self.rel_delegate.update_categories({})
        self.rel_delegate.update_shapes({})
        self.rel_table.viewport().update()

        self.yogas_text.clear()

        self.speed_table.clearContents()
        self.speed_table.setRowCount(0)

        self._last_chart = None
        self._last_include_minor = False
        self._last_yogas = None

    # ── Themed style sources (registry contract: re-evaluate per call) ──

    def _cell_style(self):
        theme = get_theme_colors()
        return f"""
            QFrame {{
                background-color: {theme["secondary_dark"]};
                border: 1px solid {theme["secondary_light"]};
                border-radius: 4px;
            }}
        """

    def _grid_label_style(self):
        theme = get_theme_colors()
        return f"""
            font-size: 11px; font-weight: bold;
            color: {theme["primary"]}; padding: 2px;
            background-color: {theme["secondary"]};
            border-bottom: 1px solid {theme["secondary_light"]};
        """

    def _table_style(self):
        theme = get_theme_colors()
        return f"""
            QTableWidget {{
                background-color: {theme["secondary_dark"]};
                color: {theme["secondary_text"]};
                gridline-color: {theme["secondary_light"]};
                border: none;
                font-size: 11px;
            }}
            QHeaderView::section {{
                background-color: {theme["secondary"]};
                color: {theme["secondary_text"]};
                font-weight: bold;
                padding: 2px;
                border: 1px solid {theme["secondary_light"]};
                font-size: 10px;
            }}
        """

    def _yogas_text_style(self):
        theme = get_theme_colors()
        return f"""
            QTextEdit {{
                background-color: {theme["secondary_dark"]};
                color: {theme["secondary_text"]};
                border: none;
                font-size: 11px;
            }}
        """

    def _close_btn_style(self):
        theme = get_theme_colors()
        return f"""
            QPushButton {{
                background-color: {theme["secondary"]};
                color: {theme["secondary_text"]};
                border: 1px solid {theme["secondary_light"]};
                border-radius: 4px;
                font-weight: bold;
                font-size: 12px;
                padding: 1px;
            }}
            QPushButton:hover {{
                background-color: {theme["secondary_light"]};
            }}
        """

    def set_close_visible(self, flag):
        """Show/hide the grid's own close bar. Hosts call this when the grid
        is shown/hidden so the always-reachable off-switch (td-rl77) is only
        present while the grid is."""
        self._close_bar.setVisible(bool(flag))

    def refresh_theme(self):
        """Replay every registered themed style under the current palette.
        Hosts must cascade here explicitly: the grid keeps its OWN registry
        (it left the SR page's registry with the extraction).

        The yoga cell embeds theme colors in its HTML at fill time, so it is
        re-rendered from the stored detection result; the tables carry no
        baked-in colors (their delegates read the theme at paint time), so
        the style replay covers them (codex review F5)."""
        self._replay_themed()
        if self._last_chart is not None:
            fill_yogas(self.yogas_text, self._last_yogas)


# ---------------------------------------------------------------------------
# Cross-chart widget (SPEC-TJK-002 section 3.1)
# ---------------------------------------------------------------------------

# Direction view name -> engine result list key. overlay_to_base reads the
# forward (transit_to_natal) list; base_to_overlay reads the reverse
# (natal_to_transit) list. Both are precomputed by the engine in one call, so a
# direction switch NEVER recomputes — it re-renders the already-held result
# (SPEC-TJK-001 5.4; the asymmetric virupa curve makes the two lists differ).
_CROSS_VIEW_ENGINE_KEY = {
    "overlay_to_base": "transit_to_natal",
    "base_to_overlay": "natal_to_transit",
}
_CROSS_VALID_DIRECTIONS = tuple(_CROSS_VIEW_ENGINE_KEY.keys())

# CLI-table columns (mirrors tajika_cross._TEXT_HEADERS): (record_field, header).
# "overlay"/"base" are synthesized from transit_body/natal_body (chart
# membership, never role — SPEC-TJK-001 5.4).
_CROSS_RECORD_COLUMNS = [
    ("overlay", "Overlay"),
    ("base", "Base"),
    ("aspect", "Aspect"),
    ("symbol", "Sym"),
    ("virupas", "VR"),
    ("strength_pct", "Str%"),
    ("distance_from_exact", "Orb"),
    ("applying_status", "App/Sep"),
    ("open_secret", "O/S"),
    ("relationship", "Relationship"),
]

_CROSS_NEUTRAL_MSG = (
    "Select both charts to see cross-chart Tajika aspects."
)


class CrossTajikaGridWidget(ThemedStyleMixin, QWidget):
    """Cross-chart Tajika display (SPEC-TJK-002 3.1).

    Shows the asymmetric aspect matrix between an OVERLAY chart and a BASE
    chart plus a records list, with an in-header direction switch. API mirrors
    the sibling ``TajikaGridWidget`` so the controller can drive either:
    ``refresh(payload_or_none)``, ``clear()``, ``set_close_visible(flag)``,
    ``closeRequested`` signal, ``refresh_theme()``.

    Payload contract (``refresh``): a dict
    ``{base_chart, overlay_chart, base_label, overlay_label,
       default_direction[, symmetric_footnote]}`` — or **None**. None (or either
    chart None) is a NORMAL state: the widget clears and shows a neutral
    "select both charts" message. Both charts are validated present BEFORE the
    service call; payload-construction and service-guard exceptions are caught
    separately and rendered as an in-pane message, never a crash.

    Matrix orientation (SPEC-TJK-001 5.7): rows = ASPECTING bodies, cols =
    RECEIVING bodies, in the active direction.
    - overlay_to_base: overlay aspects base. rows = overlay (10, no Ascendant —
      the transit-side Ascendant never aspects), cols = base (11, incl
      Ascendant). => 10x11.
    - base_to_overlay: base aspects overlay. rows = base (11, incl Ascendant),
      cols = overlay (10, no Ascendant — never a receiving target). => 11x10.
    There is no diagonal: overlay-Sun aspecting base-Sun is a real cross-aspect,
    not a self cell. Cell lookup is direction-specific with NO reverse-key
    fallback (the two direction lists are independent).

    Direction is STICKY across refreshes: ``default_direction`` applies only
    when the widget was empty/cleared; a data refresh re-renders the currently
    selected direction (so 1 s transit ticks never snap the direction). The
    header direction button cycles the two views.

    Data model: immutable Python record data only; no ``QTableWidgetItem``
    references are retained, and the payload's Chart objects are NOT held past
    the compute (only the engine ``result`` dict of plain records is kept, so a
    direction toggle re-renders without recompute and transit ticks never
    accumulate charts). ``clear()`` releases result/label references.
    """

    closeRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        # Last successful engine result + labels, replayed on a direction
        # switch (no recompute). Charts are NEVER retained (transit-tick chart
        # accumulation guard, SPEC-TJK-002 3.1).
        self._result = None
        self._base_label = "Base"
        self._overlay_label = "Overlay"
        self._symmetric_footnote = False
        # Sticky direction: None means "empty/cleared" — the next payload's
        # default_direction is honored; any other value is kept across refreshes.
        self._direction = None
        self._create_ui()
        self._show_message(_CROSS_NEUTRAL_MSG)

    # ── UI ──

    def _create_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(4)

        # Header row: title, direction switch, and the grid-owned close (✕)
        # off-switch (reachable even when the pane holding the host toggle is
        # collapsed, mirroring the sibling grid). Hidden until a host calls
        # set_close_visible(True).
        self._header_bar = QWidget()
        header_row = QHBoxLayout(self._header_bar)
        header_row.setContentsMargins(2, 0, 2, 0)
        header_row.setSpacing(4)
        self._header_title = QLabel("Cross-Chart Tajika")
        self._register_themed(self._header_title, self._grid_label_style)
        header_row.addWidget(self._header_title)
        header_row.addStretch()

        self.direction_btn = QPushButton("")
        self.direction_btn.setCursor(Qt.PointingHandCursor)
        self.direction_btn.setToolTip("Switch aspect direction")
        self._register_themed(self.direction_btn, self._header_btn_style)
        self.direction_btn.clicked.connect(self._on_direction_clicked)
        self.direction_btn.setVisible(False)
        header_row.addWidget(self.direction_btn)

        self.close_btn = QPushButton("✕")
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setFixedWidth(28)
        self.close_btn.setToolTip("Hide the cross-chart Tajika grid")
        self._register_themed(self.close_btn, self._header_btn_style)
        self.close_btn.clicked.connect(self.closeRequested)
        header_row.addWidget(self.close_btn)
        self._header_bar.setVisible(False)
        outer.addWidget(self._header_bar)

        # Neutral/error message (shown instead of the content frames).
        self._message_label = QLabel(_CROSS_NEUTRAL_MSG)
        self._message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._message_label.setWordWrap(True)
        self._register_themed(self._message_label, self._message_style)
        outer.addWidget(self._message_label)

        # Content: matrix frame over records frame.
        self._content = QWidget()
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(4)

        matrix_frame = QFrame()
        self._register_themed(matrix_frame, self._cell_style)
        matrix_layout = QVBoxLayout(matrix_frame)
        matrix_layout.setContentsMargins(2, 2, 2, 2)
        matrix_layout.setSpacing(0)
        matrix_label = QLabel("Cross Aspects")
        matrix_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._register_themed(matrix_label, self._grid_label_style)
        matrix_layout.addWidget(matrix_label)

        self.matrix_table = QTableWidget(0, 0)
        self._register_themed(self.matrix_table, self._table_style)
        self.matrix_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.matrix_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.matrix_table.verticalHeader().setDefaultSectionSize(20)
        self.matrix_table.verticalHeader().setMinimumWidth(25)
        self.matrix_table.horizontalHeader().setDefaultSectionSize(20)
        self.matrix_delegate = TajikaHighlightDelegate(parent=self.matrix_table)
        self.matrix_table.setItemDelegate(self.matrix_delegate)
        matrix_layout.addWidget(self.matrix_table, 1)
        content_layout.addWidget(matrix_frame, 1)

        rec_frame = QFrame()
        self._register_themed(rec_frame, self._cell_style)
        rec_layout = QVBoxLayout(rec_frame)
        rec_layout.setContentsMargins(2, 2, 2, 2)
        rec_layout.setSpacing(0)
        rec_label = QLabel("Records")
        rec_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._register_themed(rec_label, self._grid_label_style)
        rec_layout.addWidget(rec_label)

        self.rec_table = QTableWidget()
        self.rec_table.setColumnCount(len(_CROSS_RECORD_COLUMNS))
        self.rec_table.setHorizontalHeaderLabels(
            [title for _, title in _CROSS_RECORD_COLUMNS])
        self.rec_table.verticalHeader().setVisible(False)
        self._register_themed(self.rec_table, self._table_style)
        self.rec_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.rec_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.rec_table.verticalHeader().setDefaultSectionSize(20)
        for col in range(len(_CROSS_RECORD_COLUMNS)):
            self.rec_table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.Stretch)
        self.rec_delegate = TajikaHighlightDelegate(parent=self.rec_table)
        self.rec_table.setItemDelegate(self.rec_delegate)
        rec_layout.addWidget(self.rec_table, 1)
        content_layout.addWidget(rec_frame, 1)

        outer.addWidget(self._content, 1)
        self._content.setVisible(False)

        # Footnote (SPEC-TJK-001 5.5 rule; extended on the symmetric surface).
        self._footnote_label = QLabel("")
        self._footnote_label.setWordWrap(True)
        self._register_themed(self._footnote_label, self._footnote_style)
        self._footnote_label.setVisible(False)
        outer.addWidget(self._footnote_label)

    # ── Public API ──

    def refresh(self, payload):
        """Populate from a payload dict, or render the neutral/error state.

        payload None, either chart None, a payload-construction error, or a
        service guard/compute error each render an in-pane message and release
        held references — never a crash (SPEC-TJK-002 3.1).

        Two chartless dict forms render a caller-supplied message instead of the
        generic neutral text, WITHOUT resetting the sticky direction (so an
        HD-mode disable/re-enable never snaps the direction, SPEC-TJK-002 3.1):
        - ``{"disabled_message": "<text>"}`` — an explanatory neutral state (W4
          Transit uses this while HD mode disables cross).
        - ``{"error_message": "<text>"}`` — a payload-construction failure raised
          in the controller's refresh path; rendered as a distinct error so a
          real error is never hidden behind the generic neutral message."""
        if payload is None:
            self.clear()
            return
        # Chartless message forms: keep the sticky direction, release data,
        # show the caller's text. Checked before the base/overlay lookup so a
        # KeyError on the missing chart keys does not mask them.
        if isinstance(payload, dict) and "disabled_message" in payload:
            self._release_data()
            self._show_message(str(payload["disabled_message"]))
            return
        if isinstance(payload, dict) and "error_message" in payload:
            self._release_data()
            self._show_message(
                "Cross-chart Tajika unavailable: {}".format(payload["error_message"]))
            return
        try:
            base_chart = payload["base_chart"]
            overlay_chart = payload["overlay_chart"]
            base_label = payload.get("base_label", "Base")
            overlay_label = payload.get("overlay_label", "Overlay")
            default_direction = payload.get("default_direction", "overlay_to_base")
            symmetric_footnote = bool(payload.get("symmetric_footnote", False))
        except Exception as exc:  # malformed payload
            self._release_data()
            self._show_message("Cannot read cross-chart inputs: {}".format(exc))
            return

        if base_chart is None or overlay_chart is None:
            self.clear()
            return

        try:
            result = cross_chart_tajika(base_chart, overlay_chart)
        except Exception as exc:  # context-guard / missing-body / compute error
            self._release_data()
            self._show_message(str(exc))
            return

        # Success: keep the immutable engine result + labels only (no charts).
        self._result = result
        self._base_label = base_label
        self._overlay_label = overlay_label
        self._symmetric_footnote = symmetric_footnote
        if self._direction is None:  # empty/cleared -> honor payload default
            self._direction = (
                default_direction if default_direction in _CROSS_VIEW_ENGINE_KEY
                else "overlay_to_base"
            )
        # else: STICKY — keep the user-selected direction across refreshes.
        self._render()

    def clear(self):
        """Neutral no-data state. Releases result/label references and resets
        the sticky direction so the next payload's default is honored."""
        self._release_data()
        self._direction = None
        self._show_message(_CROSS_NEUTRAL_MSG)

    def set_close_visible(self, flag):
        """Show/hide the header bar (title + direction switch + close)."""
        self._header_bar.setVisible(bool(flag))

    def refresh_theme(self):
        """Replay every registered themed style under the current palette. The
        tables carry no baked-in colors (the delegate reads the theme at paint
        time), so the style replay covers everything; nothing is re-filled."""
        self._replay_themed()

    # ── Internals ──

    def _release_data(self):
        """Drop the engine result, delegate maps, and table contents so no
        chart/record data survives into a message or the next payload."""
        self._result = None
        self._base_label = "Base"
        self._overlay_label = "Overlay"
        self._symmetric_footnote = False
        self.matrix_table.clearContents()
        self.matrix_table.setRowCount(0)
        self.matrix_table.setColumnCount(0)
        self.matrix_delegate.update_categories({})
        self.matrix_delegate.update_shapes({})
        self.matrix_table.viewport().update()
        self.rec_table.clearContents()
        self.rec_table.setRowCount(0)
        self.rec_delegate.update_categories({})
        self.rec_delegate.update_shapes({})
        self.rec_table.viewport().update()

    def _show_message(self, text):
        """Show an in-pane message; hide the content + direction switch."""
        self._message_label.setText(text)
        self._message_label.setVisible(True)
        self._content.setVisible(False)
        self._footnote_label.setVisible(False)
        self.direction_btn.setVisible(False)

    def _direction_bodies(self):
        """(row_bodies, col_bodies) for the active direction: rows aspect cols.

        overlay_to_base -> rows = overlay aspectors (no Ascendant), cols = base
        receivers (all). base_to_overlay -> rows = base aspectors (all), cols =
        overlay receivers (no Ascendant)."""
        no_asc = [b for b in TAJIKA_PLANETS if b != "Ascendant"]
        if self._direction == "overlay_to_base":
            return no_asc, list(TAJIKA_PLANETS)
        return list(TAJIKA_PLANETS), no_asc

    def _build_lookup(self, records):
        """Map (row_body, col_body) -> record for the active direction. rows are
        the aspectors, cols the receivers; overlay is transit_body and base is
        natal_body in EVERY record (chart membership, not role)."""
        lookup = {}
        overlay_first = self._direction == "overlay_to_base"
        for rec in records:
            overlay_body = rec.get("transit_body")
            base_body = rec.get("natal_body")
            if overlay_first:
                lookup[(overlay_body, base_body)] = rec
            else:
                lookup[(base_body, overlay_body)] = rec
        return lookup

    def _render(self):
        """Render the matrix + records + footnote for the active direction from
        the stored engine result (no recompute)."""
        result = self._result
        if result is None:
            self._show_message(_CROSS_NEUTRAL_MSG)
            return

        records = result.get(_CROSS_VIEW_ENGINE_KEY[self._direction], [])
        row_bodies, col_bodies = self._direction_bodies()
        lookup = self._build_lookup(records)

        # Matrix (immutable data only; no QTableWidgetItem retained).
        self.matrix_table.clearContents()
        self.matrix_table.setRowCount(len(row_bodies))
        self.matrix_table.setColumnCount(len(col_bodies))
        self.matrix_table.setHorizontalHeaderLabels(
            [TAJIKA_SHORT_NAMES[b] for b in col_bodies])
        self.matrix_table.setVerticalHeaderLabels(
            [TAJIKA_SHORT_NAMES[b] for b in row_bodies])
        for col in range(len(col_bodies)):
            self.matrix_table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.Stretch)

        cell_categories = {}
        cell_shapes = {}
        for r, row_body in enumerate(row_bodies):
            for c, col_body in enumerate(col_bodies):
                rec = lookup.get((row_body, col_body))
                if not rec:
                    continue
                symbol = rec.get("symbol", "")
                aspect_name = rec.get("aspect", "")
                virupas = rec.get("virupas", 0)
                rel = rec.get("relationship", "")
                dist = rec.get("distance_from_exact", 0)
                item = QTableWidgetItem(symbol)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setToolTip(
                    "{rb}->{cb}: {asp}\n{vr:.0f} VR | {orb:.1f} from exact\n{rel}".format(
                        rb=TAJIKA_SHORT_NAMES[row_body],
                        cb=TAJIKA_SHORT_NAMES[col_body],
                        asp=aspect_name, vr=virupas, orb=dist, rel=rel))
                self.matrix_table.setItem(r, c, item)
                shape = _ASPECT_TO_SHAPE.get(aspect_name)
                if shape:
                    cell_shapes[(r, c)] = shape
                if virupas >= 45:
                    cell_categories[(r, c)] = "STRONG"
                else:
                    cell_categories[(r, c)] = _REL_TO_CATEGORY.get(rel, "NEUTRAL")
        self.matrix_delegate.update_categories(cell_categories)
        self.matrix_delegate.update_shapes(cell_shapes)
        self.matrix_table.viewport().update()

        # Records list (already virupas-descending from the engine).
        self._fill_records(records)

        # Footnote + direction button label.
        self._footnote_label.setText(self._footnote_text())
        self.direction_btn.setText(self._direction_label())

        self._message_label.setVisible(False)
        self._content.setVisible(True)
        self._footnote_label.setVisible(True)
        self.direction_btn.setVisible(True)

    def _fill_records(self, records):
        self.rec_table.clearContents()
        self.rec_table.setRowCount(len(records))
        rec_categories = {}
        for r, rec in enumerate(records):
            virupas = rec.get("virupas", 0)
            rel = rec.get("relationship", "")
            cat = "STRONG" if virupas >= 45 else _REL_TO_CATEGORY.get(rel, "NEUTRAL")
            cells = self._record_cells(rec)
            for c, (field, _title) in enumerate(_CROSS_RECORD_COLUMNS):
                item = QTableWidgetItem(cells[field])
                if field not in ("relationship", "aspect"):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.rec_table.setItem(r, c, item)
                rec_categories[(r, c)] = cat
        self.rec_delegate.update_categories(rec_categories)
        self.rec_delegate.update_shapes({})
        self.rec_table.viewport().update()

    @staticmethod
    def _record_cells(rec):
        open_secret = rec.get("open_secret")
        return {
            "overlay": str(rec.get("transit_body", "")),
            "base": str(rec.get("natal_body", "")),
            "aspect": str(rec.get("aspect", "")),
            "symbol": str(rec.get("symbol", "")),
            "virupas": "{:.1f}".format(rec.get("virupas", 0.0)),
            "strength_pct": "{:.1f}".format(rec.get("strength_pct", 0.0)),
            "distance_from_exact": "{:.1f}".format(rec.get("distance_from_exact", 0.0)),
            "applying_status": str(rec.get("applying_status", "")),
            "open_secret": "-" if open_secret is None else str(open_secret),
            "relationship": str(rec.get("relationship", "")),
        }

    def _direction_label(self):
        if self._direction == "overlay_to_base":
            return "{ov} → {ba}".format(ov=self._overlay_label, ba=self._base_label)
        return "{ba} → {ov}".format(ba=self._base_label, ov=self._overlay_label)

    def _footnote_text(self):
        if self._symmetric_footnote:
            return (
                "Both charts are birth charts. App/Sep reflects the OVERLAY "
                "person's natal planetary motion against the base's frozen "
                "positions; it is not a live-motion statement (SPEC-TJK-001 5.5)."
            )
        return (
            "App/Sep describes the OVERLAY body's motion; the base (natal) "
            "position is held fixed (SPEC-TJK-001 5.5)."
        )

    def _on_direction_clicked(self):
        """Toggle the direction and re-render from the stored result (no
        recompute — both direction lists are already held)."""
        if self._result is None:
            return
        self._direction = (
            "base_to_overlay" if self._direction == "overlay_to_base"
            else "overlay_to_base"
        )
        self._render()

    # ── Themed style sources (registry contract: re-evaluate per call) ──

    def _cell_style(self):
        theme = get_theme_colors()
        return """
            QFrame {{
                background-color: {sd};
                border: 1px solid {sl};
                border-radius: 4px;
            }}
        """.format(sd=theme["secondary_dark"], sl=theme["secondary_light"])

    def _grid_label_style(self):
        theme = get_theme_colors()
        return """
            font-size: 11px; font-weight: bold;
            color: {p}; padding: 2px;
            background-color: {s};
            border-bottom: 1px solid {sl};
        """.format(p=theme["primary"], s=theme["secondary"], sl=theme["secondary_light"])

    def _table_style(self):
        theme = get_theme_colors()
        return """
            QTableWidget {{
                background-color: {sd};
                color: {st};
                gridline-color: {sl};
                border: none;
                font-size: 11px;
            }}
            QHeaderView::section {{
                background-color: {s};
                color: {st};
                font-weight: bold;
                padding: 2px;
                border: 1px solid {sl};
                font-size: 10px;
            }}
        """.format(sd=theme["secondary_dark"], st=theme["secondary_text"],
                   sl=theme["secondary_light"], s=theme["secondary"])

    def _message_style(self):
        theme = get_theme_colors()
        return "color: {st}; font-size: 11px; padding: 16px;".format(
            st=theme["secondary_text"])

    def _footnote_style(self):
        theme = get_theme_colors()
        return "color: {st}; font-size: 10px; padding: 2px 4px;".format(
            st=theme["secondary_text"])

    def _header_btn_style(self):
        theme = get_theme_colors()
        return """
            QPushButton {{
                background-color: {s};
                color: {st};
                border: 1px solid {sl};
                border-radius: 4px;
                font-weight: bold;
                font-size: 11px;
                padding: 1px 6px;
            }}
            QPushButton:hover {{ background-color: {sl}; }}
        """.format(s=theme["secondary"], st=theme["secondary_text"],
                   sl=theme["secondary_light"])


# ---------------------------------------------------------------------------
# Toggle controller
# ---------------------------------------------------------------------------

class TajikaToggleController:
    """Host-agnostic owner of the tajika show/hide + side-swap state
    (SPEC-ECL-002 section 9.2). Owns tajika_mode/tajika_side, wires the two
    buttons, and drives the host's pane swap through callbacks:

    - current_chart(side) -> Chart or None
    - side_label(side) -> str for the side button
    - show_pane(side): give the grid its pane / collapse the chart side
    - hide_pane(saved_geometry): take the pane back, restore geometry
    - capture_geometry() -> opaque saved geometry, optional

    Geometry rule: capture_geometry is called ONLY on the OFF-to-ON
    transition (clean state), never on side swaps, so a collapsed layout is
    never saved as the restore target. Hosts that restore a fixed geometry
    (SR: half/half) may ignore the saved value.

    Cross-chart extension (SPEC-TJK-002 3.2, OPTIONAL, backward compatible)
    ----------------------------------------------------------------------
    Passing ``cross_widget`` + ``cross_states`` adds a state machine:

    - ``cross_widget``: a ``CrossTajikaGridWidget`` driven with payload-or-None.
    - ``cross_states``: an ordered tuple of descriptors
      ``(key, label_callable, payload_callable)``. Eclipse/Transit/Compat pass
      one; SR passes two (``cross_left``, ``cross_right``).
    - ``show_cross_pane(key)``: optional callback; the host restores BOTH chart
      frames (cross is a two-chart view, never a single-side collapse).

    Internal state is ``(kind, key)`` with ``kind in {"internal","cross"}``;
    internal keys are the existing sides. The full swap cycle is the internal
    sides THEN the cross states. The string "cross*" NEVER reaches
    ``current_chart``/``side_label``/``show_pane`` — cross rendering goes solely
    through the descriptors and ``show_cross_pane``. Exactly one of
    {internal grid, cross widget} is visible at any time; every hide path hides
    BOTH. In a cross state, ``refresh_if_showing`` treats ANY side update as
    invalidating and coalesces the rebuild via a 0 ms single-shot timer with a
    generation token, so a stale queued refresh (after teardown, or superseded
    by a newer update) no-ops. ``teardown()`` cancels pending refreshes.

    **When the new kwargs are absent the behavior is bit-identical**: ``_sides``,
    ``swap_side`` (the two-side path), geometry, and ``request_hide`` are
    unchanged. This is proven by running the existing PE/SR regression suites
    unmodified (SPEC-TJK-002 4/G2).
    """

    def __init__(self, *, toggle_btn, side_btn, grid,
                 current_chart, side_label, show_pane, hide_pane,
                 capture_geometry=None, sides=("left", "right"),
                 cross_widget=None, cross_states=None, show_cross_pane=None):
        self.toggle_btn = toggle_btn
        self.side_btn = side_btn
        self.grid = grid
        self._current_chart = current_chart
        self._side_label = side_label
        self._show_pane = show_pane
        self._hide_pane = hide_pane
        self._capture_geometry = capture_geometry
        self._sides = tuple(sides)

        # ── Cross-chart state machine (all inert when cross_states is falsy) ──
        self.cross_widget = cross_widget
        self._cross_states = tuple(cross_states) if cross_states else ()
        self._cross_state_map = {
            d[0]: (d[1], d[2]) for d in self._cross_states
        }
        self._show_cross_pane = show_cross_pane
        # (kind, key): "internal" keys are sides; "cross" keys index cross_states.
        self._state = ("internal", self._sides[0])
        # Coalescing timer + generation token for cross refreshes.
        self._refresh_timer = None
        self._refresh_gen = 0
        self._pending_gen = -1
        # Terminal teardown flag: once set, every refresh/schedule path no-ops
        # (teardown is terminal — a stale refresh_if_showing after teardown must
        # not recreate the timer or pull a payload, SPEC-TJK-002 3.2 finding 1).
        self._torn_down = False

        self.tajika_mode = False
        self.tajika_side = self._sides[0]
        self.saved_geometry = None

        self.side_btn.setVisible(False)
        self.toggle_btn.clicked.connect(self.toggle)
        self.side_btn.clicked.connect(self.swap_side)
        # Grid-owned off-switch (td-rl77): reachable even when the pane
        # holding toggle_btn is collapsed to zero width. setChecked keeps the
        # header toggle in sync before re-running the OFF branch.
        if hasattr(self.grid, 'closeRequested'):
            self.grid.closeRequested.connect(self.request_hide)
        # Cross widget's OWN close (✕) is a hide path too (SPEC-TJK-002 3.2).
        if self.cross_widget is not None and hasattr(self.cross_widget, 'closeRequested'):
            self.cross_widget.closeRequested.connect(self.request_hide)

    # ── Public state hooks for hosts (SPEC-TJK-002 3.2 finding 2) ──

    @property
    def current_state(self):
        """The active ``(kind, key)`` state tuple; ``kind`` in
        {"internal","cross"}. Read-only. Lets a host (W2 Eclipse's overlay-change
        handler) know which state is showing without touching private ``_state``
        or reading the now-stale ``tajika_side`` during a cross state."""
        return self._state

    @property
    def is_cross_active(self):
        """True iff tajika is ON and the active state is a cross state. False
        when off or after teardown-that-left-a-cross-state (tajika_mode gates)."""
        return self.tajika_mode and self._state[0] == "cross"

    def reapply_current_pane(self):
        """Re-dispatch the geometry callback for the CURRENT state so a host can
        restore the correct pane layout after an external geometry change (W2
        Eclipse overlay change) without reaching into privates. internal ->
        ``show_pane(side)``; cross -> ``show_cross_pane(key)``. No-op when tajika
        is off or after teardown."""
        if self._torn_down or not self.tajika_mode:
            return
        kind, key = self._state
        if kind == "internal":
            self._show_pane(key)
        elif self._show_cross_pane is not None:
            self._show_cross_pane(key)

    def request_hide(self):
        """Turn tajika OFF from an external trigger (the grid's close ✕),
        keeping the header toggle button's checked state consistent."""
        if not self.tajika_mode:
            return
        self.toggle_btn.setChecked(False)
        self.toggle()

    def toggle(self):
        self.tajika_mode = self.toggle_btn.isChecked()
        self.side_btn.setVisible(self.tajika_mode)
        if hasattr(self.grid, 'set_close_visible'):
            self.grid.set_close_visible(self.tajika_mode)

        if self.tajika_mode:
            # A queued cross refresh from a PRIOR session must not fire against
            # this fresh ON state (state transition invalidates it, 3.2). No-op
            # when nothing is pending / cross absent.
            self._cancel_pending_refresh()
            # Clean-state capture: only here, never on swap_side.
            if self._capture_geometry is not None:
                self.saved_geometry = self._capture_geometry()
            self.tajika_side = self._sides[0]
            self._state = ("internal", self._sides[0])
            self.update_side_label()
            self._show_pane(self.tajika_side)
            self.grid.setVisible(True)
            # Start on an internal side: the cross widget stays hidden (exactly
            # one of {grid, cross widget} is visible). No-op when cross absent.
            if self.cross_widget is not None:
                self.cross_widget.setVisible(False)
                if hasattr(self.cross_widget, 'set_close_visible'):
                    self.cross_widget.set_close_visible(False)
            chart = self._current_chart(self.tajika_side)
            if chart:
                self.grid.refresh(chart)
            else:
                # No chart on this side: render the empty state instead of
                # whatever the grid showed last (codex review F1).
                self.grid.clear()
        else:
            self.grid.setVisible(False)
            # Every hide path hides BOTH widgets (SPEC-TJK-002 3.2). No-op when
            # cross absent, so the OFF branch stays bit-identical.
            if self.cross_widget is not None:
                self.cross_widget.setVisible(False)
                if hasattr(self.cross_widget, 'set_close_visible'):
                    self.cross_widget.set_close_visible(False)
            self._hide_pane(self.saved_geometry)
            self.saved_geometry = None
            # Cancel any queued cross refresh so it cannot fire after hide.
            self._cancel_pending_refresh()

    def swap_side(self):
        # SPEC-TJK-002 3.2 (round-1 MAJOR): no-op when tajika is off. The side
        # button is hidden while off, so existing hosts never reach this while
        # off — the guard changes no shipped behavior.
        if not self.tajika_mode:
            return
        if not self._cross_states:
            # ── Original two-side path, verbatim (bit-identical). ──
            idx = self._sides.index(self.tajika_side)
            self.tajika_side = self._sides[(idx + 1) % len(self._sides)]
            self.update_side_label()
            self._show_pane(self.tajika_side)
            chart = self._current_chart(self.tajika_side)
            if chart:
                self.grid.refresh(chart)
            else:
                # Swapping to a chartless side must not keep the OTHER side's
                # data rendered (codex review F1).
                self.grid.clear()
            return
        # ── Extended cycle: internal sides THEN cross states. ──
        cycle = self._cycle()
        idx = cycle.index(self._state)
        self._state = cycle[(idx + 1) % len(cycle)]
        self._enter_state()

    def _cycle(self):
        """Full swap order: every internal side, then every cross state."""
        return ([("internal", s) for s in self._sides]
                + [("cross", d[0]) for d in self._cross_states])

    def _enter_state(self):
        """Render the current ``_state`` (cross-enabled hosts only).

        A swap is a state transition: invalidate any queued cross refresh from
        the PREVIOUS state first, so a stale coalesced fire scheduled in state A
        cannot run after we have moved to state B (SPEC-TJK-002 3.2 refresh
        gate). The immediate render below is the single refresh for the new
        state."""
        self._cancel_pending_refresh()
        kind, key = self._state
        if kind == "internal":
            self.tajika_side = key
            self.update_side_label()
            self._show_pane(key)
            self.grid.setVisible(True)
            if hasattr(self.grid, 'set_close_visible'):
                self.grid.set_close_visible(True)
            if self.cross_widget is not None:
                self.cross_widget.setVisible(False)
                if hasattr(self.cross_widget, 'set_close_visible'):
                    self.cross_widget.set_close_visible(False)
            chart = self._current_chart(key)
            if chart:
                self.grid.refresh(chart)
            else:
                self.grid.clear()
        else:  # cross — "cross*" never reaches current_chart/side_label/show_pane
            self.update_side_label()
            self._show_cross(key)

    def _show_cross(self, key):
        """Show the cross widget for a cross state; hide the internal grid."""
        self.grid.setVisible(False)
        if hasattr(self.grid, 'set_close_visible'):
            self.grid.set_close_visible(False)
        self.cross_widget.setVisible(True)
        if hasattr(self.cross_widget, 'set_close_visible'):
            self.cross_widget.set_close_visible(True)
        # Host restores BOTH chart frames (two-chart view; no single-side
        # collapse). show_pane is NEVER called with a cross key.
        if self._show_cross_pane is not None:
            self._show_cross_pane(key)
        self._refresh_cross(key)

    def _refresh_cross(self, key):
        """Pull the payload from the cross state's payload_callable and feed the
        cross widget (payload-or-None; the widget renders neutral on None).

        A payload_callable that RAISES is a real host-side error (a chart lookup
        or context failure), not a normal empty state — feed a distinct error
        payload so the widget shows the exception text instead of collapsing
        into the generic neutral message (SPEC-TJK-002 3.1)."""
        label_cb, payload_cb = self._cross_state_map[key]
        try:
            payload = payload_cb()
        except Exception as exc:
            payload = {"error_message": str(exc)}
        self.cross_widget.refresh(payload)

    def update_side_label(self):
        # In a cross state the label comes from the descriptor's label_callable,
        # never the host side_label (which only understands left/right). When
        # cross is absent this is the original single line (bit-identical).
        if self._cross_states and self._state[0] == "cross":
            label_cb, _payload_cb = self._cross_state_map[self._state[1]]
            self.side_btn.setText(label_cb())
        else:
            self.side_btn.setText(self._side_label(self.tajika_side))

    def refresh_if_showing(self, side, chart):
        """Host hook after a chart update.

        Internal state (and all cross-absent hosts): refresh the grid when the
        updated side is the one being shown (original behavior, verbatim).
        Cross state: ANY side update invalidates the two-chart view, so a
        coalesced recompute is scheduled (SPEC-TJK-002 3.2 refresh-gate
        redefinition)."""
        if self._torn_down:  # teardown is terminal — never refresh again
            return
        # Cross branch first; skipped entirely when cross_states is empty, so
        # the original block below runs verbatim for cross-absent hosts.
        if self._cross_states and self.tajika_mode and self._state[0] == "cross":
            self._schedule_cross_refresh()
            return
        if self.tajika_mode and side == self.tajika_side:
            if chart:
                self.grid.refresh(chart)
            else:
                self.grid.clear()
            self.update_side_label()

    # ── Coalesced cross refresh (0 ms single-shot + generation token) ──

    def _schedule_cross_refresh(self):
        """Batch the host's two-side sequential rebuilds (left then right) into
        ONE payload pull after the event loop settles. A generation token lets a
        stale queued fire (after teardown, or superseded by a newer schedule)
        no-op."""
        if self._torn_down:  # teardown is terminal — never recreate the timer
            return
        self._refresh_gen += 1
        self._pending_gen = self._refresh_gen
        if self._refresh_timer is None:
            from PySide6.QtCore import QTimer
            # Parent to the cross widget so the timer is owned by a QObject and
            # is destroyed with it — it must never outlive teardown as an
            # orphaned, still-connected QTimer (SPEC-TJK-002 3.2 finding 3).
            self._refresh_timer = QTimer(self.cross_widget)
            self._refresh_timer.setSingleShot(True)
            self._refresh_timer.setInterval(0)
            self._refresh_timer.timeout.connect(self._run_scheduled_refresh)
            # If the cross widget (parent) is destroyed FIRST, the child timer's
            # C++ object dies while we still hold the Python wrapper; clear the
            # dangling reference so no later stop()/deleteLater() touches a dead
            # object (SPEC-TJK-002 3.2 finding 1, destruction-order hazard).
            self._refresh_timer.destroyed.connect(self._on_refresh_timer_destroyed)
        self._refresh_timer.start(0)

    def _run_scheduled_refresh(self):
        # Stale/teardown guard: only the most recently scheduled generation may
        # fire, and only while a cross state is actually visible.
        if self._torn_down:  # teardown is terminal — never pull a payload again
            return
        if self._pending_gen != self._refresh_gen:
            return
        if not self.tajika_mode:
            return
        if not (self._cross_states and self._state[0] == "cross"):
            return
        # Re-derive the HOST side-button caption before re-rendering the cross
        # content: a coalesced refresh may have been triggered by a person being
        # replaced or cleared, so the label callable's names may have changed.
        # Without this, the widget's direction button updates (via _refresh_cross)
        # but the host "Cross: A ↔ B" caption goes stale (SPEC-TJK-002 3.2,
        # W5 review finding 2).
        self.update_side_label()
        self._refresh_cross(self._state[1])

    def _cancel_pending_refresh(self):
        """Invalidate any queued cross refresh (bump the generation so a fire
        already in the event queue no-ops) and stop the timer."""
        self._refresh_gen += 1
        timer = getattr(self, '_refresh_timer', None)
        if timer is not None:
            try:
                timer.stop()
            except RuntimeError:
                # The cross widget (parent) was destroyed first; the child
                # timer's C++ object is already gone. Drop the dead wrapper.
                self._refresh_timer = None

    def _on_refresh_timer_destroyed(self, *args):
        """Clear the Python wrapper when the timer's C++ object is destroyed
        (e.g. the cross widget parent was torn down first), so no later path
        stops or deletes a dangling QTimer (SPEC-TJK-002 3.2 finding 1)."""
        self._refresh_timer = None

    def teardown(self):
        """Cancel pending refreshes (SPEC-TJK-002 3.2). Call on host teardown so
        a queued 0 ms refresh cannot fire against a torn-down widget.

        Terminal: sets ``_torn_down`` so every later refresh/schedule path
        no-ops (a stale ``refresh_if_showing`` must not recreate the timer,
        finding 1). Stops the coalescing timer and DROPS the reference so the
        controller retains no live QTimer after teardown (finding 3) — validity
        -guarded so a cross widget destroyed FIRST (its child timer already
        dead) does not raise. Also clears both widgets' data so a torn-down host
        never leaves stale chart/record content on screen (finding 1)."""
        if self._torn_down:
            return
        self._torn_down = True
        self._cancel_pending_refresh()
        timer = getattr(self, '_refresh_timer', None)
        if timer is not None:
            try:
                timer.stop()
                timer.deleteLater()
            except RuntimeError:
                # Parent widget already destroyed the child timer's C++ object.
                pass
            self._refresh_timer = None
        # Drop any data left on either widget (validity-guarded — a widget's
        # C++ object may already be gone if it was destroyed first).
        for w in (self.grid, self.cross_widget):
            if w is None:
                continue
            try:
                clear = getattr(w, 'clear', None)
                if clear is not None:
                    clear()
            except RuntimeError:
                pass
