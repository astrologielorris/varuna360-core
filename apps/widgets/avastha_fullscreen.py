# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
The expanded Avastha page of the fullscreen dialog (SPEC-AVA-002 §4.5).

The small in-panel table is out of room: seven ~45px columns where a six-character
diagonal cell already elides. This is the version with space, and it uses that
space for the half of the matrix that has never been shown.

    THE TWO DIRECTIONS
    A cell (row=ACTOR, col=TARGET) holds what the TARGET receives from the ACTOR.
    Summed DOWN a column you get what a planet RECEIVES -- the bottom TOTAL/POS/NEG
    band, which the panel has always shown. Summed ACROSS a row you get what a
    planet CASTS -- the right-hand band, which is new.

Both bands include the planet's own diagonal (the dignity-amplified self-base),
so the two grand totals agree: the same seven diagonals and the same forty-two
off-diagonal cells, enumerated in a different order. The corner block's diagonal
carries that shared grand trio (SPEC-AVA-002 INV-1b / D-3).

Geometry, 13 rows x 10 columns:
    rows 0-6   the 7x7 matrix          cols 0-6   the seven planets
    row  7     TOTAL   (received)      col  7     CAST TOTAL
    row  8     POS     (received)      col  8     CAST POS
    row  9     NEG     (received)      col  9     CAST NEG
    row  10    SIGN                    corner (7..9, 7..9): grand trio on the
    row  11    HORA                        diagonal, blank elsewhere
    row  12    TRIMSAMSA               rows 10-12 x cols 7-9: blank
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
    QHeaderView, QSizePolicy,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontMetrics

from ui.qt_theme import (
    get_theme_colors, scaled_area_px, scaled_area_font, elevation_table_style,
)
from apps.delegates import AvasthaHighlightDelegate
from apps.delegates.cell_depth import CellDepthMixin

# SPEC-THM-002 W3 / D-6: cell depth is FULLSCREEN ONLY, behind this one flag.
# E5 costs a measured 1.27x per repaint; the in-panel 380px tables repaint on
# every chart change, varga switch and mode toggle, ten of them at a time, so
# they get the free primitives (E4 header gradient, E6 gridline) and not this.
# Flip to False to take the depth off in one line.
CELL_DEPTH_ENABLED = True


class DepthAvasthaDelegate(CellDepthMixin, AvasthaHighlightDelegate):
    """The panel's semantic colouring plus SPEC-THM-002 depth and row hover.

    A SUBCLASS, not a change to AvasthaHighlightDelegate, because that delegate
    is shared with the in-panel table where D-6 says the cost is not worth it.

    Order matters: CellDepthMixin must come first so its paint_depth is found
    before QStyledItemDelegate's MRO entry.

    D-8 row hover is scoped to this delegate rather than the six shared ones.
    On a delegate-painted table it cannot be QSS -- an ``::item:hover``
    background would defeat the semantic fill exactly as INV-5 describes -- so
    it is a State_MouseOver branch here, and only here.
    """

    def paint(self, painter, option, index):
        from PySide6.QtWidgets import QStyle
        from PySide6.QtGui import QBrush, QColor

        super().paint(painter, option, index)
        rect = option.rect.adjusted(0, 0, -1, -1)
        self.paint_depth(painter, rect)
        if option.state & QStyle.StateFlag.State_MouseOver:
            painter.save()
            ink = QColor(get_theme_colors()["secondary_light"])
            ink.setAlphaF(0.10)
            painter.fillRect(rect, QBrush(ink))
            painter.restore()

# Row/column geometry. Mirrors SPEC-AVA-001 §12.2 for the rows and extends it
# with the cast band; the panel controller owns the same row constants.
ROW_TOTAL, ROW_POS, ROW_NEG = 7, 8, 9
ROW_SIGN, ROW_HORA, ROW_TRIM = 10, 11, 12
COL_CAST_TOTAL, COL_CAST_POS, COL_CAST_NEG = 7, 8, 9
N_ROWS, N_COLS = 13, 10

# Planet -> the short glyph+code the panel uses, kept so a reader moving between
# the two surfaces sees the same tokens.
PLANET_ABBR = {
    "Sun": "☉ SU", "Moon": "☽ MO", "Mars": "♂ MA",
    "Mercury": "☿ ME", "Jupiter": "♃ JU", "Venus": "♀ VE",
    "Saturn": "♄ SA",
}

_REL_WORD = {"FRIEND": "friendly", "ENEMY": "hostile",
             "NEUTRAL": "neutral", "DUAL": "dual", "N/A": "no"}


class AvasthaFullscreenPage(QWidget):
    """The Avastha page of the fullscreen InfoPanelDialog.

    Computes from the Qt-free spine (``core.avastha_totals`` /
    ``core.avastha_refined``) rather than scraping the panel's table, so the two
    surfaces cannot disagree and this one can show precision the panel cannot fit.
    """

    def __init__(self, gui, parent=None):
        super().__init__(parent)
        self.gui = gui
        self._cell_info = {}       # (row, col) -> sentence for the reading row
        self._categories = {}
        self._build_ui()
        self.refresh()

    # ── construction ────────────────────────────────────────────────

    def _build_ui(self):
        theme = get_theme_colors()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Compass strip: names the two directions. D-2 chose this over rails --
        # a rail label per band costs a row and a column of the grid and repeats
        # itself; one compass says it once, next to the view name.
        top = QHBoxLayout()
        top.setSpacing(14)
        self._compass = QLabel()
        self._compass.setTextFormat(Qt.TextFormat.RichText)
        self._compass.setStyleSheet(f"color: {theme['secondary_text']};")
        top.addWidget(self._compass)
        top.addStretch()
        self._view_label = QLabel()
        self._view_label.setFont(scaled_area_font('table_headers', family="Inter", bold=True))
        self._view_label.setStyleSheet(f"color: {theme['primary']};")
        top.addWidget(self._view_label)
        layout.addLayout(top)

        self.table = QTableWidget(N_ROWS, N_COLS)
        self.table.setMouseTracking(True)          # for the reading row
        self.table.cellEntered.connect(self._on_cell_entered)
        self.table.verticalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._delegate = DepthAvasthaDelegate(self.table)
        self._delegate.set_depth_enabled(CELL_DEPTH_ENABLED)
        self.table.setItemDelegate(self._delegate)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # E4 header gradient + E6 quiet gridline. matrix=True: on a 7x7 the grid
        # is what lets the eye track a row across to its column (D-4).
        self.table.setStyleSheet(elevation_table_style(level=2, header_level=3,
                                                       matrix=True))
        layout.addWidget(self.table, stretch=1)

        # Reading row: the cheapest and clearest direction cue of the four the
        # mockup tried, and the only one that states the RAW value -- the cells
        # print {v:.0f} but contribute the unrounded float, so an eye-sum of a
        # row drifts (SPEC-AVA-002 INV-7 / D-9).
        self._reading = QLabel(" ")
        self._reading.setFont(scaled_area_font('table_headers', family="Inter"))
        self._reading.setStyleSheet(
            f"color: {theme['primary']}; padding: 4px 8px;")
        self._reading.setMinimumHeight(int(scaled_area_px('table_headers') * 2.2))
        layout.addWidget(self._reading)

        self._legend = QLabel()
        self._legend.setTextFormat(Qt.TextFormat.RichText)
        self._legend.setWordWrap(True)
        self._legend.setStyleSheet(f"color: {theme['secondary_text']};")
        layout.addWidget(self._legend)

        self._apply_static_text()

    def _apply_static_text(self, view=None):
        """Compass + legend. The shame chip is the one VIEW-DEPENDENT part.

        Pure and refined price a shame pair differently (SPEC-AVA-001 §3.1): the
        pure view charges a flat 60, the refined views charge the shamer's
        A-scaled lack. A single wording for both is wrong in one of them, and
        this label is the only place the grid explains what the `!` costs — so
        it takes the current view, defaulting to ``_view()`` for the theme-refresh
        call that has no view in hand.
        """
        if view is None:
            view = self._view()
        theme = get_theme_colors()
        colors = self._delegate.get_category_colors()

        def chip(cat, label):
            bg, fg = colors.get(cat, (theme['secondary'], theme['secondary_text']))
            return (f"<span style='background:{bg};color:{fg};"
                    f"padding:1px 6px;border-radius:3px;'>{label}</span>")

        self._compass.setText(
            "<b>&#8594; across a row:</b> what that planet <b>CASTS</b> at the "
            "other six &nbsp;&nbsp;|&nbsp;&nbsp; "
            "<b>&#8595; down a column:</b> what that planet <b>RECEIVES</b>")

        self._legend.setText(
            chip("FRIEND", "60+ friend") + " &nbsp; " +
            chip("ENEMY", "60- enemy") + " &nbsp; " +
            chip("NEUTRAL", "60~ neutral, counts 0") + " &nbsp; " +
            chip("DUAL", "60&#177; dual") + " &nbsp; " +
            chip("SHAME", "60-! shame, flat 60" if view == "pure"
                 else "60-! shame, takes the lack") + " &nbsp; " +
            chip("PROUD", "EX/MK/OH own base") +
            "<br><span style='opacity:0.75;'>The diagonal is a planet's own "
            "dignity-amplified strength and belongs to both directions, so the "
            "two grand totals agree. Cast totals cover the other six planets "
            "only &mdash; aspects to Rahu and Ketu are not counted.</span>")

    # ── data ────────────────────────────────────────────────────────

    def _active_chart(self):
        state = getattr(self.gui, 'state', None)
        return getattr(state, 'active_chart', None) if state else None

    def _mode(self):
        state = getattr(self.gui, 'state', None)
        return getattr(state, 'aditya_mode', 'aditya') if state else 'aditya'

    def _view(self):
        ctrl = getattr(self.gui, 'avastha_controller', None)
        return ctrl.current_view() if ctrl else "pure"

    def refresh(self):
        """Recompute and repaint. Safe to call with no chart loaded."""
        try:
            self._refresh_inner()
        except Exception as e:
            import traceback
            print(f"[AvasthaFullscreen] refresh failed: {e}")
            traceback.print_exc()

    def _refresh_inner(self):
        from AI_tools.AI_main_function.avastha import (
            get_drishti_yuti_data, ASPECTING_PLANETS, REL_SYMBOL,
        )
        from core.avastha_totals import (
            SELF_BASE, dignity_multiplier, split_expression,
            split_expression_cast, display_split,
        )

        chart = self._active_chart()
        if not chart:
            return
        mode = self._mode()
        view = self._view()

        # Sidereal is a different frame, not a different label: the matrix chart
        # is rebuilt exactly as the panel controller rebuilds it, or the signs
        # and the relationships would come from two different zodiacs.
        matrix_chart = chart
        if mode == "sidereal":
            from core.chart_factory import rebuild_chart
            matrix_chart = rebuild_chart(chart, mode="sidereal")

        data = get_drishti_yuti_data(matrix_chart)
        matrix = data["matrix"]
        dignity = data["dignity_data"]
        shame = data.get("shame_pairs", set())
        order = list(ASPECTING_PLANETS)

        self._cell_info = {}
        self._categories = {}
        self.table.clearContents()
        self._set_headers(order)
        # Re-render the legend for THIS view: the shame chip prices differently
        # in pure vs refined (SPEC-AVA-001 §3.1).
        self._apply_static_text(view)

        if view == "pure":
            decimals = 0
            self._fill_matrix_pure(order, matrix, dignity, shame, REL_SYMBOL,
                                   SELF_BASE, dignity_multiplier)
            recv = {p: split_expression(p, order, matrix, dignity, shame) for p in order}
            cast = {p: split_expression_cast(p, order, matrix, dignity, shame) for p in order}
        else:
            decimals = 1
            from core.avastha_refined import refined_matrix
            from core.bala_calculator import get_all_bala_data
            # Balas follow the Strength panel and take the ACTIVE chart, not the
            # sidereal rebuild -- get_all_bala_data handles sidereal internally
            # (SPEC-AVA-001 §6).
            rm = refined_matrix(order, matrix, dignity, shame,
                                get_all_bala_data(chart), view)
            self._fill_matrix_refined(order, rm)
            recv = {p: (rm["pos"][p], rm["neg"][p]) for p in order}
            cast = {p: (rm["cast_pos"][p], rm["cast_neg"][p]) for p in order}

        self._fill_bands(order, recv, cast, decimals)
        self._fill_retinue(order, matrix_chart, mode, recv)
        self._fill_corner(recv, cast, decimals)

        self._view_label.setText(
            {"pure": "Pure", "duc": "Refined by Duc", "dig": "Refined by Dig",
             "uccha": "Refined by Uccha", "cheshta": "Refined by Chesta"}
            .get(view, view))
        self._delegate.update_categories(self._categories)
        self.table.viewport().update()

    def _set_headers(self, order):
        cast_heads = ["CAST\nTOT", "CAST\nPOS", "CAST\nNEG"]
        cols = [PLANET_ABBR.get(p, p) for p in order] + cast_heads
        rows = [PLANET_ABBR.get(p, p) for p in order] + [
            "TOTAL", "POS", "NEG", "SIGN", "HORA", "TRIMSAMSA"]
        self.table.setHorizontalHeaderLabels(cols)
        self.table.setVerticalHeaderLabels(rows)
        hh, vh = self.table.horizontalHeader(), self.table.verticalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        vh.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        # The cast band sizes to its own content so the 7x7 core keeps the rest
        # of the width. Let QT measure it, do not measure it here: three
        # real-screen runs were spent on hand-computed widths that all clipped
        # ("CASTS/TOTAL" -> "AST/OTA" from a guessed multiple of the base size,
        # then still "AS/O" from QFontMetrics, because header type comes from
        # the app's global stylesheet and its padding is invisible to a bare
        # font measurement). ResizeToContents consults the real style, font and
        # padding, which is the whole reason it exists.
        for c in range(COL_CAST_TOTAL, N_COLS):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)

    # ── the 7x7 core ────────────────────────────────────────────────

    def _put(self, row, col, text, category=None, tooltip=None):
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        if tooltip:
            item.setToolTip(tooltip)
        self.table.setItem(row, col, item)
        if category:
            self._categories[(row, col)] = category

    def _fill_matrix_pure(self, order, matrix, dignity, shame, rel_symbol,
                          self_base, dignity_multiplier):
        abbr = {"exaltation": "EX", "mulatrikona": "MK", "own_sign": "OH"}
        for r, actor in enumerate(order):
            for c, target in enumerate(order):
                if actor == target:
                    dig = dignity.get(actor)
                    val = self_base * dignity_multiplier(dig["virupas"] if dig else 0)
                    if dig:
                        # The fullscreen page has the width the panel lacks, so
                        # the "=" that had to be dropped at ~45px comes back.
                        self._put(r, c, f"{abbr.get(dig['type'], '?')} = {val:.0f}", "PROUD")
                        self._cell_info[(r, c)] = (
                            f"{actor} in {dig['type'].replace('_', ' ')} — own base "
                            f"60 x {dignity_multiplier(dig['virupas']):.2f} = {val:.0f}, "
                            f"counted once in its row and once in its column")
                    else:
                        self._put(r, c, f"{val:.0f}")
                        self._cell_info[(r, c)] = (
                            f"{actor} has no dignity — own base {val:.0f}")
                    continue

                entry = matrix.get((actor, target))
                if entry is None or (not entry.get("is_yuti") and entry["virupas"] <= 0):
                    self._put(r, c, ".")
                    self._cell_info[(r, c)] = f"{actor} does not reach {target}"
                    continue

                vr = entry["virupas"]
                rel = entry["relationship"]
                sym = rel_symbol.get(rel, " ")
                if (actor, target) in shame:
                    if rel in ("NEUTRAL", "N/A"):
                        sym = "-"
                    self._put(r, c, f"{vr:.0f}{sym}!", "SHAME")
                    self._cell_info[(r, c)] = (
                        f"{actor} shames {target} — costs {actor} 60 in its cast "
                        f"total and {target} 60 in its received total (raw {vr:.2f})")
                elif rel == "DUAL":
                    self._put(r, c, f"{vr:.0f}±", "DUAL")
                    self._cell_info[(r, c)] = (
                        f"{actor} casts a dual aspect on {target} — gives and "
                        f"takes {vr:.2f}, so it cancels in the pure view")
                else:
                    self._put(r, c, f"{vr:.0f}{sym}", rel if rel in
                              ("FRIEND", "ENEMY", "NEUTRAL") else None)
                    counts = "counts 0" if rel == "NEUTRAL" else f"raw {vr:.2f}"
                    self._cell_info[(r, c)] = (
                        f"{actor} casts {vr:.0f} {_REL_WORD.get(rel, rel.lower())} "
                        f"onto {target} ({counts})")

    def _fill_matrix_refined(self, order, rm):
        abbr = {"exaltation": "EX", "mulatrikona": "MK", "own_sign": "OH"}
        for r, actor in enumerate(order):
            for c, target in enumerate(order):
                if actor == target:
                    val, dtype = rm["diagonal"][actor]
                    if dtype:
                        self._put(r, c, f"{abbr.get(dtype, '?')} = {val:.1f}", "PROUD")
                    else:
                        self._put(r, c, f"{val:.1f}")
                    self._cell_info[(r, c)] = (
                        f"{actor}'s own bala x its dignity multiplier = {val:.2f}")
                    continue

                cell = rm["cells"].get((actor, target))
                if cell is None:
                    self._put(r, c, ".")
                    self._cell_info[(r, c)] = f"{actor} does not reach {target}"
                    continue

                marker = "!" if cell["is_shame"] else ""
                self._put(r, c, f"{cell['value']:.1f}{cell['symbol']}{marker}",
                          cell["category"])
                if cell["two_sided"]:
                    # Name WHICH side does what. A shame never gives — the
                    # friendship gives and the shame takes, and crediting the
                    # give to the shame reads as if shaming helped. Over a DUAL
                    # base both sides were already on, so the shame adds nothing
                    # on top and must not be credited with the take either.
                    if cell["is_shame"] and cell["relationship"] == "FRIEND":
                        self._cell_info[(r, c)] = (
                            f"{actor} is friendly to {target} and shames it — "
                            f"the friendship gives {cell['give']:.2f}, the "
                            f"shame takes {cell['take']:.2f}, "
                            f"net {cell['signed']:.2f}")
                    elif cell["is_shame"]:
                        self._cell_info[(r, c)] = (
                            f"{actor} casts a dual aspect on {target} and "
                            f"shames it — the dual aspect gives "
                            f"{cell['give']:.2f} and takes {cell['take']:.2f}; "
                            f"the shame costs no more on top, "
                            f"net {cell['signed']:.2f}")
                    else:
                        self._cell_info[(r, c)] = (
                            f"{actor} casts a dual aspect on {target} — gives "
                            f"{cell['give']:.2f}, takes {cell['take']:.2f}, "
                            f"net {cell['signed']:.2f}")
                elif cell["is_shame"]:
                    self._cell_info[(r, c)] = (
                        f"{actor} shames {target} — takes {cell['take']:.2f}, "
                        f"scaled by what {actor} LACKS in this bala")
                else:
                    self._cell_info[(r, c)] = (
                        f"{actor} casts {cell['value']:.2f} "
                        f"{_REL_WORD.get(cell['relationship'], '')} onto {target}"
                        + (", scaled by its own bala" if cell["in_total"]
                           else ", shown but counting 0"))

    # ── the two summary bands ───────────────────────────────────────

    def _fill_bands(self, order, recv, cast, decimals):
        """Bottom band = received (per column); right band = cast (per row)."""
        from core.avastha_totals import display_split

        for i, planet in enumerate(order):
            # Received, under the column.
            pos, neg = recv[planet]
            pos_s, neg_s, tot_s = display_split(pos, neg, decimals)
            self._put(ROW_TOTAL, i, tot_s)
            self._put(ROW_POS, i, pos_s, "FRIEND" if float(pos_s) > 0 else "NEUTRAL")
            self._put(ROW_NEG, i, neg_s, "ENEMY" if float(neg_s) < 0 else "NEUTRAL")
            for row, label in ((ROW_TOTAL, "receives, net"),
                               (ROW_POS, "receives, positive"),
                               (ROW_NEG, "receives, negative")):
                self._cell_info[(row, i)] = f"{planet} {label} (summed down its column)"

            # Cast, beside the row.
            cpos, cneg = cast[planet]
            cpos_s, cneg_s, ctot_s = display_split(cpos, cneg, decimals)
            self._put(i, COL_CAST_TOTAL, ctot_s)
            self._put(i, COL_CAST_POS, cpos_s,
                      "FRIEND" if float(cpos_s) > 0 else "NEUTRAL")
            self._put(i, COL_CAST_NEG, cneg_s,
                      "ENEMY" if float(cneg_s) < 0 else "NEUTRAL")
            for col, label in ((COL_CAST_TOTAL, "casts, net"),
                               (COL_CAST_POS, "casts, positive"),
                               (COL_CAST_NEG, "casts, negative")):
                self._cell_info[(i, col)] = (
                    f"{planet} {label} at the other six (summed across its row; "
                    "Rahu and Ketu are not counted)")

    def _fill_corner(self, recv, cast, decimals):
        """The 3x3 where the bands meet.

        ONE grand trio on the diagonal, not two. Both directions enumerate the
        same cells, so a separate 'cast grand total' would be the same number
        printed twice (INV-1b / D-3). Computed from the raw floats: each band
        absorbs its own display rounding residue, so summing the rendered
        strings would drift.
        """
        from core.avastha_totals import display_split

        gp = sum(p for p, _n in recv.values())
        gn = sum(n for _p, n in recv.values())
        gp_s, gn_s, gt_s = display_split(gp, gn, decimals)

        cells = ((ROW_TOTAL, COL_CAST_TOTAL, gt_s, None, "net"),
                 (ROW_POS, COL_CAST_POS, gp_s, "FRIEND", "positive"),
                 (ROW_NEG, COL_CAST_NEG, gn_s, "ENEMY", "negative"))
        for row, col, text, cat, word in cells:
            self._put(row, col, text, cat,
                      f"Whole chart, {word} — identical read either way")
            self._cell_info[(row, col)] = (
                f"Whole chart, {word}: {text}. The same figure whether you sum "
                "the rows or the columns — the cast direction redistributes the "
                "chart's avastha, it does not add any")

        # Off-diagonal corner cells and the retinue gutter stay empty on purpose:
        # crossing "received POS" with "cast NEG" is not a quantity.
        for row in (ROW_TOTAL, ROW_POS, ROW_NEG):
            for col in (COL_CAST_TOTAL, COL_CAST_POS, COL_CAST_NEG):
                if self.table.item(row, col) is None:
                    self._put(row, col, "")
        for row in (ROW_SIGN, ROW_HORA, ROW_TRIM):
            for col in (COL_CAST_TOTAL, COL_CAST_POS, COL_CAST_NEG):
                self._put(row, col, "")

    def _fill_retinue(self, order, sign_chart, mode, recv):
        from core.chart_helpers import (
            get_planet_sign_index, get_planet_in_sign_longitude,
            ADITYA_NAMES, TROPICAL_NAMES,
        )
        from core.avastha_totals import sign_total_category
        from AI_tools.AI_main_function.retinue import (
            get_hora, get_trimsamsa_being, ADITYA_SIGN_ORDER,
        )

        names = ADITYA_NAMES if mode == "aditya" else TROPICAL_NAMES
        for i, planet in enumerate(order):
            idx = get_planet_sign_index(sign_chart, planet, default=-1)
            ok = 0 <= idx < 12
            sign_text = names[idx] if ok else "?"
            aditya = ADITYA_SIGN_ORDER[idx] if ok else None
            total = recv[planet][0] + recv[planet][1]
            self._put(ROW_SIGN, i, sign_text, sign_total_category(total),
                      f"{aditya} / {TROPICAL_NAMES[idx]}" if aditya else None)
            self._cell_info[(ROW_SIGN, i)] = (
                f"{planet} in {sign_text}" + (f" ({aditya})" if aditya else ""))

            if not aditya:
                self._put(ROW_HORA, i, "?")
                self._put(ROW_TRIM, i, "?")
                continue

            deg = get_planet_in_sign_longitude(sign_chart, planet)
            hora = get_hora(aditya, deg)
            trim = get_trimsamsa_being(aditya, deg)
            side = hora.get("side", "?")
            hora_disp = sign_text if side == "Aditya" else hora.get("being_name", "?")
            self._put(ROW_HORA, i, hora_disp,
                      "HORA_ADITYA" if side == "Aditya" else "HORA_NAGA",
                      f"{hora.get('being_name', '?')} ({side} side, "
                      f"{hora.get('lord', '?')} hora)")
            self._cell_info[(ROW_HORA, i)] = (
                f"{planet}'s hora being: {hora.get('being_name', '?')} "
                f"({side} side)")

            btype = str(trim.get("being_type", ""))
            tname = trim.get("being_name", "?")
            self._put(ROW_TRIM, i, tname, "TRIM_" + btype.upper(),
                      f"{tname} ({btype}, {trim.get('element', '?')})")
            self._cell_info[(ROW_TRIM, i)] = (
                f"{planet}'s trimsamsa being: {tname} ({btype})")

    # ── interaction ─────────────────────────────────────────────────

    def _on_cell_entered(self, row, col):
        self._reading.setText(self._cell_info.get((row, col), " "))

    def refresh_theme(self):
        """Re-apply theme-derived styling after a live theme switch.

        The delegate reads get_category_colors() at paint time so the cells
        follow by themselves, but the compass, legend and reading row hold
        stylesheets set at construction and would otherwise keep the old colours.
        """
        theme = get_theme_colors()
        self._compass.setStyleSheet(f"color: {theme['secondary_text']};")
        self._view_label.setStyleSheet(f"color: {theme['primary']};")
        self._reading.setStyleSheet(f"color: {theme['primary']}; padding: 4px 8px;")
        self._legend.setStyleSheet(f"color: {theme['secondary_text']};")
        self._apply_static_text()   # legend chips are theme-coloured inline
        self.table.setStyleSheet(elevation_table_style(level=2, header_level=3,
                                                       matrix=True))
        # MANDATORY on a theme switch: the depth brush cache is keyed by row
        # HEIGHT, which a theme change does not alter, so nothing else would
        # invalidate it and the cells would keep washing with the old palette's
        # ink (SPEC-THM-002 §6.2).
        self._delegate.clear_depth_cache()
        self.table.viewport().update()
