# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Sector info popup — SPEC-AVA-003 (v1.2, §12 amendment).

Double-clicking a wheel retinue ring, an Avastha panel SIGN/HORA/TRIMSAMSA cell,
or a Planetary Condition retinue link opens this dialog. The MAIN EVENT is the
sign's structure and the beings' descriptions (``SectorStructureWidget``, the
clicked hora/trimsamsa section expanded and gold-marked): they fill most of the
popup and are visible at once (D-22, reverses D-19). The avastha numbers are
the optional helper: one quiet line ("simplest form", D-23) shows the clicked
block's POS/NEG/TOTAL and the whole-sign trio in the panel's current view, and a
small ``Details`` toggle (closed by default) reveals the two segmented switches —
View (Avastha/Duc/Dig/Uccha/Chesta) and Depth (Sign/Hora/Trimsamsa) — plus the
Planet/POS/NEG/TOTAL table whose rows ARE the panel's own cells (INV-11). The
view is switchable but LOCAL to the popup (opens at the panel's current view,
never written back — D-16); the depth zooms Sign -> two Hora halves -> five
Trimsamsa bands over the same occupants (a partition, never a filter).

Every number comes from the ``avastha_summaries`` dict (one summary per view,
built once at open by ``AvasthaController.sign_popup_summaries`` -> Half B
``sign_summaries_all_views``, D-20); switching a view or a layer re-renders ONLY
the line and the table from the dict in hand — no engine call, no rebuild of
the switches or the structure widget. The dialog computes no avastha math and
imports no engine: it only paints ``core.avastha_sign_summary.layer_display``
(INV-7, INV-8).
"""

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QFrame,
    QPushButton,
    QToolButton,
    QButtonGroup,
    QSizePolicy,
)
from PySide6.QtCore import Qt

from ui.qt_theme import (
    get_theme_colors, is_light_theme, scaled_area_font, get_primary_button_style,
)
from core.aditya_data import ADITYA_NAMES
from core.avastha_sign_summary import (
    LAYERS, LAYER_LABEL, VIEW_POPUP_LABEL, layer_display,
)
from apps.widgets.sector_structure_widget import SectorStructureWidget, _theme_palette


# View keys in switch order (== AvasthaController.VIEW_ORDER; T-8 pins the tie).
VIEW_ORDER = tuple(VIEW_POPUP_LABEL)

ADITYA_TO_WESTERN = dict(zip(
    ADITYA_NAMES,
    ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
     "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"],
))


class SectorInfoDialog(QDialog):

    def __init__(self, sign_name, focus_ring=None, focus_type=None,
                 avastha_summaries=None, layer=None, view=None, parent=None):
        super().__init__(parent)

        # D-9 (extended): reject the v1.0 single-summary shape and any half-built
        # dict loudly. ``avastha_summaries`` is either None or a dict keyed by
        # EVERY view whose values carry the summary shape ("planets" + "sectors").
        if avastha_summaries is not None:
            if (not isinstance(avastha_summaries, dict)
                    or set(avastha_summaries) != set(VIEW_ORDER)
                    or any(not isinstance(s, dict) or "planets" not in s
                           or "sectors" not in s
                           for s in avastha_summaries.values())):
                raise TypeError(
                    "SectorInfoDialog: avastha_summaries must be {view: summary} "
                    "keyed by every view; see SPEC-AVA-003 §11.2")

        self._summaries = avastha_summaries

        # Opening layer: explicit ``layer``, else the clicked ring, else sign.
        if layer is None:
            layer = "sign" if focus_ring is None else focus_ring
        if layer not in LAYERS:
            raise ValueError(f"unknown layer {layer!r}; expected one of {LAYERS}")
        self._layer = layer

        # Opening view: the panel's current view (popup-local, D-16), else pure.
        if view is None:
            view = "pure"
        if avastha_summaries is not None and view not in VIEW_ORDER:
            raise ValueError(f"unknown view {view!r}; expected one of {VIEW_ORDER}")
        self._view = view

        western = ADITYA_TO_WESTERN.get(sign_name, "")
        title = f"{sign_name} · {western}" if western else sign_name
        self.setWindowTitle(f"{sign_name} Structure")

        theme = get_theme_colors()
        light = is_light_theme()
        palette = _theme_palette()

        bg = "#F5F5F5" if light else theme["secondary_dark"]
        text_color = "#1A1A1A" if light else theme["secondary_text"]
        border_color = "#CCCCCC" if light else theme["secondary_light"]
        gold = "#B8860B" if light else "#DAA520"
        muted = theme["secondary_text"]
        primary = theme["primary"]
        primary_text = theme["primary_text"]

        self._c = {
            "green": "#2E7D32" if light else "#A5D6A7",
            "red": "#C62828" if light else "#EF9A9A",
            "muted": muted,
            "text": text_color,
            "gold": palette["gold"],
            "gold_bg": palette["gold_bg"],
            "border": border_color,
        }

        self.setStyleSheet(f"""
            QDialog {{ background-color: {bg}; }}
            QLabel {{ color: {text_color}; background: transparent; }}
            QScrollArea {{ background-color: {bg}; border: none; }}
            QScrollArea > QWidget > QWidget {{ background-color: {bg}; }}
        """)

        seg_style = f"""
            QPushButton {{
                background: transparent;
                color: {text_color};
                border: 1px solid {border_color};
                padding: 3px 9px;
                margin: 0px;
            }}
            QPushButton:checked {{
                background: {primary};
                color: {primary_text};
                border: 1px solid {primary};
                font-weight: bold;
            }}
        """

        main = QVBoxLayout(self)
        main.setContentsMargins(12, 8, 12, 8)
        main.setSpacing(5)

        # ---- title (sign · western, one line) ------------------------------ #
        header = QLabel(title)
        hfont = scaled_area_font('panel_titles')
        hfont.setBold(True)
        header.setFont(hfont)
        header.setStyleSheet(f"color: {gold};")
        main.addWidget(header)

        self._view_group = None
        self._depth_group = None
        self._status = None
        self._table = None
        self._line = None
        self._details = None
        self._details_btn = None

        if avastha_summaries is not None:
            # ---- the simplest form: ONE quiet line + a small Details toggle -- #
            # (D-23) clicked block trio + whole-sign trio in the panel's view;
            # the switches and the table stay behind the toggle (D-22).
            line_row = QHBoxLayout()
            line_row.setSpacing(6)
            self._line = QLabel()
            self._line.setFont(scaled_area_font('tables'))
            self._line.setTextFormat(Qt.TextFormat.RichText)
            self._line.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
            self._line.setWordWrap(True)
            line_row.addWidget(self._line, 1)

            self._details_btn = QToolButton()
            self._details_btn.setText("Details")
            self._details_btn.setCheckable(True)
            self._details_btn.setChecked(False)
            self._details_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            self._details_btn.setArrowType(Qt.ArrowType.RightArrow)
            self._details_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._details_btn.setFont(scaled_area_font('status'))
            self._details_btn.setStyleSheet(
                f"QToolButton {{ border: none; background: transparent; "
                f"color: {muted}; padding: 1px 4px; }} "
                f"QToolButton:hover {{ color: {text_color}; }}")
            self._details_btn.setFixedHeight(max(22, self._details_btn.sizeHint().height()))
            self._details_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self._details_btn.toggled.connect(self._on_details_toggled)
            line_row.addWidget(self._details_btn, 0, Qt.AlignmentFlag.AlignTop)
            main.addLayout(line_row)

            # ---- details (hidden by default): switches, status, table ------ #
            self._details = QFrame()
            self._details.setFrameShape(QFrame.Shape.NoFrame)
            det = QVBoxLayout(self._details)
            det.setContentsMargins(0, 2, 0, 2)
            det.setSpacing(5)

            switch_row = QHBoxLayout()
            switch_row.setSpacing(0)
            self._view_group = self._build_segment(
                switch_row, seg_style,
                [(v, VIEW_POPUP_LABEL[v]) for v in VIEW_ORDER],
                self._view, self._on_view_clicked)

            switch_row.addSpacing(18)   # visible gap between the View and Depth groups

            self._depth_group = self._build_segment(
                switch_row, seg_style,
                [(lyr, LAYER_LABEL[lyr]) for lyr in LAYERS],
                self._layer, self._on_depth_clicked)
            switch_row.addStretch(1)
            det.addLayout(switch_row)

            self._status = QLabel()
            sfont = scaled_area_font('tables')
            sfont.setBold(True)
            self._status.setFont(sfont)
            det.addWidget(self._status)

            self._table = QLabel()
            self._table.setFont(scaled_area_font('tables'))
            self._table.setTextFormat(Qt.TextFormat.RichText)
            self._table.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
            self._table.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            det.addWidget(self._table)

            self._details.setVisible(False)
            main.addWidget(self._details)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet(f"color: {border_color};")
        separator.setFixedHeight(2)
        main.addWidget(separator)

        # ---- the main event: sign structure + beings' descriptions (D-22) --- #
        active_hora = focus_type if focus_ring == "hora" else None
        active_trim = focus_type if focus_ring == "trimsamsa" else None
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setWidget(SectorStructureWidget(
            sign_name, active_hora_key=active_hora,
            active_trimsamsa_key=active_trim,
            active_sign=(focus_ring is None), parent=None))
        main.addWidget(self._scroll, 1)

        # ---- Close --------------------------------------------------------- #
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(80)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(get_primary_button_style())
        close_btn.clicked.connect(self.accept)
        close_btn.setDefault(True)          # Enter = Close, never a switch
        btn_row.addWidget(close_btn)
        main.addLayout(btn_row)

        if self._summaries is not None:
            self._render()

        # The descriptions own the height (the pre-v1.0 shape, 480x620); the
        # width never jitters on a view/layer switch (rows only change height).
        self.setMinimumSize(420, 500)
        self.resize(480, 620)
        self.setMinimumWidth(max(420, self.sizeHint().width()))

    # ---- segmented control -------------------------------------------------- #

    def _build_segment(self, row, style, items, checked_key, on_click):
        group = QButtonGroup(self)
        group.setExclusive(True)
        for key, label in items:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(key == checked_key)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(style)
            btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            btn._key = key
            btn.clicked.connect(lambda _checked, k=key: on_click(k))
            group.addButton(btn)
            row.addWidget(btn)
        return group

    def _on_view_clicked(self, view):
        self.set_view(view)

    def _on_depth_clicked(self, layer):
        self.set_layer(layer)

    def _sync_group(self, group, key):
        if group is None:
            return
        for btn in group.buttons():
            btn.blockSignals(True)
            btn.setChecked(btn._key == key)
            btn.blockSignals(False)

    def _on_details_toggled(self, on):
        self._details_btn.setArrowType(
            Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)
        self._details.setVisible(on)

    def details_open(self):
        return bool(self._details is not None and self._details_btn.isChecked())

    def set_details_open(self, on):
        if self._details_btn is not None:
            self._details_btn.setChecked(bool(on))

    # ---- public switch API (used by the buttons, the keys, the harness) ----- #

    def current_layer(self):
        return self._layer

    def current_view(self):
        return self._view

    def set_layer(self, layer):
        if layer not in LAYERS or self._summaries is None:
            return
        if layer != self._layer:
            self._layer = layer
            self._render()
        self._sync_group(self._depth_group, layer)

    def set_view(self, view):
        if self._summaries is None or view not in VIEW_ORDER:
            return
        if view != self._view:
            self._view = view
            self._render()
        self._sync_group(self._view_group, view)

    # ---- rendering ---------------------------------------------------------- #

    @staticmethod
    def _esc(text):
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _render(self):
        model = layer_display(self._summaries[self._view], self._layer)
        self._status.setText(self._esc(model["status"]))
        self._sync_group(self._view_group, self._view)
        self._sync_group(self._depth_group, self._layer)
        self._table.setText(self._table_html(model))
        self._line.setText(self._line_html(model))

    def _tint(self, value, color):
        try:
            return color if float(value) != 0.0 else self._c["muted"]
        except ValueError:
            return color

    def _trio_html(self, pos, neg, total, bold=False):
        c = self._c
        b0, b1 = ("<b>", "</b>") if bold else ("", "")
        return (f"<span style='color:{self._tint(pos, c['green'])};'>{b0}{self._esc(pos)}{b1}</span>"
                f"&nbsp;<span style='color:{self._tint(neg, c['red'])};'>{b0}{self._esc(neg)}{b1}</span>"
                f"&nbsp;{b0}{self._esc(total)}{b1}")

    def _line_html(self, model):
        """The simplest form (D-23): ``<View> · <focused block>: trio · Sign: trio``.

        The focused block is the run of ``focused`` items at the current layer
        (its sum row when it has one, else its single row, else its empty note);
        at the Sign layer, or with no focus, only the whole-sign trio prints.
        Same strings as the table (INV-11/INV-12): the line is a projection of
        ``layer_display``, never a second computation."""
        c = self._c
        items = model["items"]
        view_label = self._summaries[self._view]["view_label"]
        parts = [f"<span style='color:{c['muted']};'>{self._esc(view_label)} ·</span>"]

        focused = [it for it in items if it.get("focused")]
        header = next((it for it in focused if it["kind"] == "section_header"), None)
        if focused:
            if header is not None:
                label = f"{header['label']} {header['span']}"
                subsum = next((it for it in focused if it["kind"] == "subsum"), None)
                rows = [it for it in focused if it["kind"] == "row"]
                if subsum is not None:
                    parts.append(f"{self._esc(label)}: "
                                 + self._trio_html(subsum["pos"], subsum["neg"], subsum["total"]))
                elif len(rows) == 1:
                    parts.append(f"{self._esc(label)} ({self._esc(rows[0]['planet'])}): "
                                 + self._trio_html(rows[0]["pos"], rows[0]["neg"], rows[0]["total"]))
            else:
                note = next((it for it in focused
                             if it["kind"] in ("empty_half", "empty_bands", "empty")), None)
                if note is not None:
                    parts.append(f"<span style='color:{c['muted']};'>"
                                 f"{self._esc(note['text'])}</span>")
            parts.append("<span style='color:%s;'>·</span>" % c["muted"])

        sign = next((it for it in items if it["kind"] in ("sum", "sign_sum")), None)
        if sign is not None:
            parts.append(f"{self._esc(sign['label'])}: "
                         + self._trio_html(sign["pos"], sign["neg"], sign["total"], bold=True))
        else:
            empty = next((it for it in items if it["kind"] == "empty"), None)
            if empty is not None:
                parts.append(f"<span style='color:{c['muted']};'>{self._esc(empty['text'])}</span>")
        return " ".join(parts)

    def _num(self, value, color, bold=False):
        """A right-aligned numeric cell; tinted only when non-zero (a rendered
        0 is never tinted, matching the panel). Sum rows pass ``bold=True`` and
        follow the same zero rule (review minor #2, 2026-08-18)."""
        try:
            tint = color if float(value) != 0.0 else self._c["muted"]
        except ValueError:
            tint = color
        b0, b1 = ("<b>", "</b>") if bold else ("", "")
        return (f"<td align='right' style='padding-left:14px;color:{tint};'>"
                f"{b0}{self._esc(value)}{b1}</td>")

    def _table_html(self, model):
        c = self._c
        rows_html = []
        for it in model["items"]:
            kind = it["kind"]
            if kind == "status":
                continue
            if kind == "row":
                focused = it.get("focused")
                cell0 = (f"<td style='border-left:3px solid {c['gold']};"
                         f"padding-left:6px;'>{self._esc(it['planet'])}</td>"
                         if focused else
                         f"<td style='padding-left:6px;'>{self._esc(it['planet'])}</td>")
                tr_style = f" style='background:{c['gold_bg']};'" if focused else ""
                rows_html.append(
                    f"<tr{tr_style}>{cell0}"
                    f"{self._num(it['pos'], c['green'])}"
                    f"{self._num(it['neg'], c['red'])}"
                    f"{self._num(it['total'], c['text'])}</tr>")
            elif kind in ("sum", "subsum", "sign_sum"):
                focused = it.get("focused")
                tr_style = f" style='background:{c['gold_bg']};'" if focused else ""
                bar = (f"border-left:3px solid {c['gold']};padding-left:6px;"
                       if focused else "padding-left:6px;")
                rows_html.append(
                    f"<tr{tr_style}><td style='{bar}'><b>{self._esc(it['label'])}</b></td>"
                    f"{self._num(it['pos'], c['green'], bold=True)}"
                    f"{self._num(it['neg'], c['red'], bold=True)}"
                    f"{self._num(it['total'], c['text'], bold=True)}</tr>")
            elif kind == "section_header":
                focused = it.get("focused")
                prefix = "▸ " if focused else ""
                text = f"{prefix}{it['label']} · {it['span']}"
                if focused:
                    cell = (f"<td colspan='4' style='border-left:3px solid {c['gold']};"
                            f"padding-left:6px;background:{c['gold_bg']};'>"
                            f"<b>{self._esc(text)}</b></td>")
                else:
                    cell = (f"<td colspan='4' style='padding-left:6px;color:{c['muted']};'>"
                            f"<b>{self._esc(text)}</b></td>")
                rows_html.append(f"<tr>{cell}</tr>")
            else:  # empty / empty_half / empty_bands / other
                focused = it.get("focused")
                prefix = "▸ " if focused else ""
                bar = (f"border-left:3px solid {c['gold']};padding-left:6px;"
                       f"background:{c['gold_bg']};"
                       if focused else "padding-left:6px;")
                rows_html.append(
                    f"<tr><td colspan='4' style='{bar}color:{c['muted']};'>"
                    f"{prefix}{self._esc(it['text'])}</td></tr>")

        return ("<table cellspacing='0' cellpadding='1' width='100%'>"
                + "".join(rows_html) + "</table>")

    # ---- keyboard (§3.6 / §11.1) ------------------------------------------- #

    def keyPressEvent(self, event):
        if self._summaries is not None:
            key = event.key()
            li = LAYERS.index(self._layer)
            if key in (Qt.Key.Key_Down, Qt.Key.Key_PageDown):
                if li < len(LAYERS) - 1:
                    self.set_layer(LAYERS[li + 1])
                event.accept()
                return
            if key in (Qt.Key.Key_Up, Qt.Key.Key_PageUp):
                if li > 0:
                    self.set_layer(LAYERS[li - 1])
                event.accept()
                return
            if key == Qt.Key.Key_Home:
                self.set_layer("sign")
                event.accept()
                return
            if key == Qt.Key.Key_End:
                self.set_layer("trimsamsa")
                event.accept()
                return
            if key in (Qt.Key.Key_1, Qt.Key.Key_2, Qt.Key.Key_3):
                self.set_layer(LAYERS[key - Qt.Key.Key_1])
                event.accept()
                return
            vi = VIEW_ORDER.index(self._view)
            if key == Qt.Key.Key_Right:
                if vi < len(VIEW_ORDER) - 1:
                    self.set_view(VIEW_ORDER[vi + 1])
                event.accept()
                return
            if key == Qt.Key.Key_Left:
                if vi > 0:
                    self.set_view(VIEW_ORDER[vi - 1])
                event.accept()
                return
        super().keyPressEvent(event)
