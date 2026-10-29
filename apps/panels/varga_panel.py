# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The VARGA panel, page 3 of the Strength stack (SPEC-DIG-001 §4.4, td-m6xyo).

One varga at a time, the one selected in the left varga column:

- header: "D1" (accent) + the varga name, the style label at the right;
- a chip row (1 2 3 4 7 9 10 12 16 20 24 27 30 40 45 60, styled labels) that
  selects a varga exactly like the column and always shows the same selection;
- seven planet rows: glyph on a small coloured sphere, name, "Sign deg · lord X"
  (Debilitated: "friend's sign" / "neutral's sign" / "enemy's sign") and a pill
  "EX Exalted" in the app's dignity colours (``ui/dignity_colors``);
- at the bottom the DIGNITY keycap with its lamp (the Strength key family): lit =
  the dignity overlay on the chart (``managers.dignity_overlay``).

The style button is the header's swap button (unchanged); the header label names
the state. Its fourth state, "All vargas" (SPEC-DIG-001 D-9, Lorris 2026-10-13),
shows the full table (``gui.dignities_table``: every varga, each styled variant
right after its classical row) in place of the chips and the planet rows; the
chart and the column keep drawing the style (D-10 amended), and the bottom key is
the style key.
"""
from __future__ import annotations

import math

import shiboken6
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QLinearGradient, QPainter,
                           QPen, QRadialGradient)
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from core import planet_dignity as pd
from core import varga_codes as vc
from core.i18n import t
from ui.dignity_colors import dignity_colors
from ui.qt_theme import desat_hex, get_theme_colors, is_light_theme, scaled_area_px, scaled_px

GLYPHS = {"Sun": "☉", "Moon": "☽", "Mars": "♂", "Mercury": "☿",
          "Jupiter": "♃", "Venus": "♀", "Saturn": "♄"}
# The planet spheres of the panel (Burnish Ledger's planet column, chosen by Lorris)
SPHERES = {"Sun": "#DCD36C", "Moon": "#EFBDE0", "Mars": "#F09A9A", "Mercury": "#DCC0A0",
           "Jupiter": "#CF8FF0", "Venus": "#93B6EE", "Saturn": "#B4B4C2"}
GLYPH_INK = "#2A2A2A"


# ---- the panel's words, through the i18n catalog (SPEC-LOC-002), read at use
def key_label():
    return t("panel.varga.key.dignity", "DIGNITY")


def key_tip():
    return t("panel.varga.key.dignity_tip", "Dignity on the chart (switches the Strength glow off)")


def style_tip():
    return t("panel.varga.key.style_tip",
             "Varga style of the table and the chart (click: Classical, Parivritti, Reversed)")


def dignity_name(code):
    """The pill's name of a dignity code (EX .. DB)."""
    names = {"EX": t("panel.varga.dignity.EX", "Exalted"),
             "MT": t("panel.varga.dignity.MT", "Moolatrikona"),
             "OH": t("panel.varga.dignity.OH", "Own House"),
             "GF": t("panel.varga.dignity.GF", "Great Friend"),
             "F": t("panel.varga.dignity.F", "Friend"),
             "N": t("panel.varga.dignity.N", "Neutral"),
             "E": t("panel.varga.dignity.E", "Enemy"),
             "GE": t("panel.varga.dignity.GE", "Great Enemy"),
             "DB": t("panel.varga.dignity.DB", "Debilitated")}
    return names.get(code, code)


def db_note(kind):
    """The sub line of a Debilitated row: the kind of host of its sign."""
    notes = {pd.FRIEND: t("panel.varga.db.friend", "friend's sign"),
             pd.NEUTRAL: t("panel.varga.db.neutral", "neutral's sign"),
             pd.ENEMY: t("panel.varga.db.enemy", "enemy's sign")}
    return notes.get(kind, "")


def _theme():
    return get_theme_colors()


def _mix(a, b, f):
    ca, cb = QColor(a), QColor(b)
    return QColor(round(ca.red() + (cb.red() - ca.red()) * f),
                  round(ca.green() + (cb.green() - ca.green()) * f),
                  round(ca.blue() + (cb.blue() - ca.blue()) * f)).name()


def _font(px, bold=False):
    f = QFont()
    f.setPixelSize(max(6, int(px)))
    f.setBold(bold)
    return f


def sign_label(sign_index, gui):
    """The sign label the app shows for this ordinal (label set, language)."""
    from core.aditya_mode import displayed_sign_name
    state = getattr(gui, "state", None)
    mode = getattr(state, "aditya_mode", "aditya") or "aditya"
    western = bool(getattr(gui, "use_western_names", False))
    try:
        from core import settings_registry as registry
        from managers.settings_manager import get_settings
        lang = get_settings().get("zodiac.sign_language",
                                  registry.default("zodiac.sign_language")) or "en"
    except Exception:
        lang = "en"
    try:
        return displayed_sign_name(sign_index, mode, western, lang)
    except Exception:
        return str(sign_index + 1)


def planet_rows(chart, gui_varga, gui=None):
    """The seven rows of the panel for the GUI varga code ``gui_varga``."""
    code = None if gui_varga in (None, 1) else vc.to_libaditya_varga_code(gui_varga)
    rows = []
    for d in pd.varga_dignities(chart, code):
        where = f"{sign_label(d.sign_index, gui)} {pd.format_degree(d.degree)}"
        tail = db_note(d.kind) if d.code == "DB" else t("panel.varga.row.lord", "lord {lord}",
                                                        lord=d.lord)
        rows.append({"planet": d.planet, "code": d.code, "kind": d.kind, "step": d.step,
                     "sub": f"{where} · {tail}", "name": dignity_name(d.code)})
    return rows


# ------------------------------------------------------------------ chips
class VargaChips(QWidget):
    """The varga chip row, the column's twin: same labels, same selection."""
    chosen = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(1)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self.buttons = {}
        for base in vc.COLUMN_VARGAS:
            b = QPushButton(str(base))
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(lambda _c=False, v=base: self.chosen.emit(v))
            self._group.addButton(b, base)
            self.buttons[base] = b
            lay.addWidget(b)
        self.refresh_theme()

    def set_state(self, style, shown):
        base = vc.base_gui_varga(shown or 1)
        for b_num, b in self.buttons.items():
            code = vc.styled_gui_varga(b_num, style)
            b.setText(vc.column_label(b_num, style))
            b.setToolTip(f"{vc.gui_varga_code_label(code)} ({vc.get_varga_name(code)})")
        if base in self.buttons:
            self.buttons[base].setChecked(True)
        self._fit_widths()                  # labels only: the QSS stays (R1 review F5)

    def refresh_theme(self):
        """The chips' QSS (theme, font): 16 restyles, so only on a theme or
        font change, never on a varga or style change (``set_state``)."""
        th = _theme()
        px = self._px = max(8, scaled_area_px("sidebar") - 2)
        h = max(px + 4, scaled_px(14))
        style = f"""
            QPushButton {{ background-color: {th["secondary"]}; color: {th["secondary_text"]};
                border: 1px solid {th["secondary_light"]}; border-radius: 3px;
                font-size: {px}px; font-weight: bold; padding: 0px;
                min-height: {h}px; max-height: {h}px; min-width: 0px; }}
            QPushButton:hover {{ border: 1px solid {th["primary"]}; }}
            QPushButton:checked {{ background-color: {th["secondary_dark"]};
                border: 2px solid {th["primary"]}; }}
        """
        for b in self.buttons.values():
            b.setStyleSheet(style)
            b.setFixedHeight(h)                 # qt-material's min-height outvotes the QSS one
        self._fit_widths()

    def _fit_widths(self):
        fm = QFontMetricsF(_font(self._px, True))
        for b in self.buttons.values():
            b.setMinimumWidth(int(math.ceil(fm.horizontalAdvance(b.text() or "10"))) + 2)


# ------------------------------------------------------------------ planet rows
class PlanetDignityList(QWidget):
    """Seven painted rows: sphere + glyph, name, sub line, dignity pill. The rows
    share the height they are given: one line each (name, then the sub line in
    smaller muted text, then the pill) in the panel's own box, two lines when
    there is room; the list asks for the one-line height only, so it scrolls
    only when even that does not fit (large font scales)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def set_rows(self, rows):
        self._rows = list(rows)
        self.updateGeometry()
        self.update()

    @property
    def rows(self):
        return list(self._rows)

    def _metrics(self):
        """(name px, sub px, one-line row height, two-line row height)."""
        name_px = scaled_area_px("tables")
        sub_px = max(8, scaled_area_px("info_text") - 1)
        nh = QFontMetricsF(_font(name_px, True)).height()
        sh = QFontMetricsF(_font(sub_px)).height()
        pill = QFontMetricsF(_font(max(8, name_px - 1), True)).height() + 3
        one = int(math.ceil(max(nh, pill) + 2))
        two = int(math.ceil(nh + sh + scaled_px(5)))
        return name_px, sub_px, one, two

    def _row_height(self):
        _n, _s, one, two = self._metrics()
        share = self.height() / max(len(self._rows), 7)
        return max(float(one), min(share, two * 1.15)), share >= two

    def sizeHint(self):
        return QSize(scaled_px(300), self._metrics()[2] * max(len(self._rows), 7))

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, _event):
        th = _theme()
        light = is_light_theme()
        name_px, sub_px = self._metrics()[:2]
        row_h, two_lines = self._row_height()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        w = self.width()
        pad = scaled_px(6)
        sphere = max(12.0, min(row_h * (0.52 if two_lines else 0.78), scaled_px(22)))
        divider = QColor(th["secondary_light"])
        nf, sf = _font(name_px, True), _font(sub_px)
        nfm, sfm = QFontMetricsF(nf), QFontMetricsF(sf)
        name_col = max(nfm.horizontalAdvance(r["planet"]) for r in self._rows) if self._rows else 0
        muted = QColor(_mix(th["secondary_text"], th["secondary_dark"], 0.38 if light else 0.32))
        for i, row in enumerate(self._rows):
            top = i * row_h
            cy = top + row_h / 2
            if i:
                p.setPen(QPen(divider, 1))
                p.drawLine(QPointF(pad, top + 0.5), QPointF(w - pad, top + 0.5))
            self._sphere(p, QPointF(pad + sphere / 2, cy), sphere / 2, row["planet"])
            # the pill, right aligned
            pill_rect = self._pill(p, row, QRectF(0, top, w - pad, row_h), name_px)
            # name + sub line
            x = pad + sphere + scaled_px(6)
            text_w = max(10.0, pill_rect.left() - x - scaled_px(5))
            if two_lines:
                y0 = cy - (nfm.height() + sfm.height()) / 2
                name_box = QRectF(x, y0, text_w, nfm.height())
                sub_box = QRectF(x, y0 + nfm.height(), text_w, sfm.height())
            else:                               # one line: name column, then the sub line
                name_w = min(name_col, text_w)
                name_box = QRectF(x, top, name_w, row_h)
                sx = x + name_w + scaled_px(6)
                sub_box = QRectF(sx, top, max(0.0, pill_rect.left() - sx - scaled_px(5)), row_h)
            align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            p.setFont(nf)
            p.setPen(QColor(th["secondary_text"]))
            p.drawText(name_box, align,
                       nfm.elidedText(row["planet"], Qt.TextElideMode.ElideRight, name_box.width()))
            p.setFont(sf)
            p.setPen(muted)
            p.drawText(sub_box, align,
                       sfm.elidedText(row["sub"], Qt.TextElideMode.ElideRight, sub_box.width()))
        p.end()

    def _sphere(self, p, centre, r, planet):
        base = QColor(desat_hex(SPHERES.get(planet, "#B4B4C2")))
        g = QRadialGradient(QPointF(centre.x() - r * 0.35, centre.y() - r * 0.4), r * 1.4)
        g.setColorAt(0.0, QColor(_mix(base.name(), "#FFFFFF", 0.55)))
        g.setColorAt(0.55, base)
        g.setColorAt(1.0, QColor(_mix(base.name(), "#000000", 0.22)))
        p.setPen(QPen(QColor(_mix(base.name(), "#000000", 0.35)), 0.8))
        p.setBrush(QBrush(g))
        p.drawEllipse(centre, r, r)
        f = _font(r * 1.25)
        p.setFont(f)
        p.setPen(QColor(GLYPH_INK))
        p.drawText(QRectF(centre.x() - r, centre.y() - r, 2 * r, 2 * r),
                   Qt.AlignmentFlag.AlignCenter, GLYPHS.get(planet, "?"))

    def _pill(self, p, row, area, name_px):
        colours = dignity_colors(row["code"]) or ("#808080", "#FFFFFF")
        bg, fg = QColor(colours[0]), QColor(colours[1])
        px = max(8, name_px - 1)
        cf, nf = _font(px, True), _font(px)
        cfm, nfm = QFontMetricsF(cf), QFontMetricsF(nf)
        gap, hpad = scaled_px(5), scaled_px(7)
        code_w, name_w = cfm.horizontalAdvance(row["code"]), nfm.horizontalAdvance(row["name"])
        width = hpad * 2 + code_w + gap + name_w
        height = min(cfm.height() + 3, area.height() - 2)
        rect = QRectF(area.right() - width, area.center().y() - height / 2, width, height)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(rect, height / 2, height / 2)
        p.setPen(fg)
        p.setFont(cf)
        p.drawText(QRectF(rect.left() + hpad, rect.top(), code_w + 1, rect.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, row["code"])
        p.setFont(nf)
        p.drawText(QRectF(rect.left() + hpad + code_w + gap, rect.top(), name_w + 1, rect.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, row["name"])
        return rect


# ------------------------------------------------------------------ the key
class StripKey(QAbstractButton):
    """The DIGNITY keycap, the Strength panel keys' twin: the same painter
    (``StrengthKeyHeader._paint_key``: geometry, lip, face, lamp, label at the
    Table Headers size, lit / pressed / hover looks) on a cell of the keys' own
    height (``key_header_height``), as wide as the widest Strength key label
    ("DUC BALA") plus a margin, centred by the panel."""

    def __init__(self, label=None, tip=None, parent=None):
        super().__init__(parent)
        self._lit = False
        self._hover = False
        self.header_height = None          # the Strength key header's live height, when known
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tip if tip is not None else key_tip())
        self.setText(label if label is not None else key_label())
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    @property
    def lit(self):
        return self._lit

    def set_lit(self, lit):
        if bool(lit) != self._lit:
            self._lit = bool(lit)
            self.update()

    def sizeHint(self):
        from apps.panels.strength_source_keys import key_header_height, key_width
        width = max(key_width(w, self.font()) for w in ("DUC BALA", key_label(), "PARIVRITTI"))
        return QSize(width + scaled_px(24), self.header_height or key_header_height(self.font()))

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _event):
        from apps.panels.strength_source_keys import StrengthKeyHeader
        p = QPainter(self)
        # the Strength keys' own painter: it reads only ``self.font()``
        StrengthKeyHeader._paint_key(self, p, QRectF(self.rect()), self.text().upper(),
                                     lit=self._lit, pressing=self.isDown(), hover=self._hover)
        p.end()


class KeyStrip(QWidget):
    """The ground the DIGNITY key sits on: the Strength key header's own surface
    (the ``QHeaderView::section`` gradient, elevation 2 to 1, with its
    ``secondary_light`` border), so the keycap reads as on the Strength panel on
    every theme, never on the panel's dark ground."""

    def paintEvent(self, _event):
        from ui.qt_theme import elevation_color
        th = _theme()
        p = QPainter(self)
        r = QRectF(self.rect())
        g = QLinearGradient(r.topLeft(), r.bottomLeft())
        g.setColorAt(0.0, QColor(elevation_color(2)))
        g.setColorAt(1.0, QColor(elevation_color(1)))
        p.fillRect(r, QBrush(g))
        p.setPen(QPen(QColor(th["secondary_light"]), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(r.adjusted(0.5, 0.5, -0.5, -0.5))
        p.end()


# ------------------------------------------------------------------ the panel
class VargaPanel(QWidget):
    """Page 3 of the Strength stack. Reads the app state; owns the varga style
    controller (``managers.varga_style``) and the DIGNITY key's lamp."""

    def __init__(self, gui, table=None, parent=None):
        super().__init__(parent)
        from managers.varga_style import VargaStyleController
        self._gui = gui
        self.style_controller = VargaStyleController(gui, on_change=self._style_changed)
        self.style_controller.subscribe(self)

        outer = QVBoxLayout(self)
        m = 2                                   # scaled_px floors at 5: the box is tight
        outer.setContentsMargins(m, m, m, m)
        outer.setSpacing(m)

        head = QHBoxLayout()
        head.setSpacing(scaled_px(6))
        self.code_label = QLabel(vc.gui_varga_code_label(1))      # refresh() sets them
        self.name_label = QLabel(vc.get_varga_name(1))
        self.style_label = QLabel(vc.varga_style_short("classical"))
        head.addWidget(self.code_label)
        head.addWidget(self.name_label)
        head.addStretch()
        head.addWidget(self.style_label)
        outer.addLayout(head)

        self.chips = VargaChips(self)
        self.chips.chosen.connect(self._chip_chosen)
        outer.addWidget(self.chips)

        # only the planet rows scroll: the header, the chips and the key stay put
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll = scroll
        self.list = PlanetDignityList()
        scroll.setWidget(self.list)
        outer.addWidget(scroll, 1)
        self.table = table                 # "All vargas": every varga, in place of the rows
        if table is not None:
            table.setParent(self)
            table.setMinimumHeight(0)      # the page minimum it had: here it scrolls itself
            outer.addWidget(table, 1)
            table.hide()

        self.key_strip = KeyStrip(self)
        key_row = QHBoxLayout(self.key_strip)
        key_row.setContentsMargins(0, 0, 0, 0)
        key_row.addStretch()
        self.key = StripKey(parent=self.key_strip)
        self.key.clicked.connect(self._key_pressed)
        key_row.addWidget(self.key)
        # the All vargas view's key: the varga style (SPEC-DIG-001 D-10); lit = a
        # style other than Classical, like a Strength key lit away from its rest
        self.style_key = StripKey(vc.varga_style_short("classical").upper(), style_tip(),
                                  parent=self.key_strip)
        self.style_key.clicked.connect(self._style_key_pressed)
        self.style_key.hide()
        key_row.addWidget(self.style_key)
        key_row.addStretch()
        outer.addWidget(self.key_strip)

        self._subscribe_keys()
        self.refresh_theme()
        self._refresh_key()
        # the column and the View menu are built around this panel: label them
        # with the stored style once the window is assembled
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._relabel_once)

    def _relabel_once(self):
        if shiboken6.isValid(self):
            self.style_controller.relabel_column()

    # ---- state
    def _shown(self):
        state = getattr(self._gui, "state", None)
        return getattr(state, "current_varga", 1) or 1

    def refresh(self):
        """Re-read the chart, the varga and the style."""
        style = self.style_controller.style
        table = self.style_controller.table
        shown = self._shown()
        self.chips.set_state(style, shown)
        self.chips.setVisible(not table)
        self._scroll.setVisible(not table)
        if self.table is not None:
            self.table.setVisible(table)
        self.key.setVisible(not table)     # All vargas: the style key takes the DIGNITY key's place
        self.style_key.setVisible(table)
        self.style_key.setText(vc.varga_style_short(style).upper())
        self.style_key.set_lit(style != "classical")
        base = vc.base_gui_varga(shown)
        self.code_label.setText(vc.gui_varga_code_label(shown))
        self.name_label.setText(vc.get_varga_name(shown))
        short = vc.varga_style_short(style)
        touched = shown != base            # the style draws another varga here (accent)
        changes = any(vc.style_touches(base, k) for k in vc.VARGA_STYLE_ORDER)
        # a varga no style changes reads "Classical · unchanged" (muted)
        if table:
            short, touched = vc.varga_style_short(vc.VARGA_TABLE), False
        self.style_label.setText(short if changes or table else t(
            "panel.varga.style.unchanged", "{style} · unchanged", style=short))
        self.style_label.setProperty("touched", bool(touched))
        self._style_label_colour(touched)
        chart = getattr(getattr(self._gui, "state", None), "active_chart", None)
        try:
            rows = planet_rows(chart, shown, self._gui) if chart is not None else []
        except Exception:
            rows = []
        self.list.set_rows(rows)
        self._refresh_key()

    def _style_changed(self, switched=False):
        """The style or the view changed: the table and this panel, ONCE. When
        the style switched the chart's varga, that varga change already
        refreshed both (the table's key holds the style); otherwise the
        controller's coalesced, visibility-gated refresh (a hidden panel waits
        for its show). No controller (a bare panel): refresh here."""
        ctrl = getattr(self._gui, "dignities_controller", None)
        if ctrl is None or not hasattr(ctrl, "request_refresh"):
            self.refresh()
        elif not switched:
            ctrl.request_refresh()

    def _chip_chosen(self, base):
        switch = getattr(self._gui, "_switch_varga", None)
        if callable(switch):
            switch(base)                   # the column's own path; the varga change refreshes
            # a switch that did not land (no chart): the chips show the varga shown
            self.chips.set_state(self.style_controller.style, self._shown())
        else:
            self.refresh()

    # ---- the DIGNITY key
    def _refresh_key(self):
        from managers.settings_manager import get_settings
        self.key.set_lit(pd.dignity_on(get_settings().get))

    def _style_key_pressed(self):
        self.style_controller.cycle_style()   # the style subscription refreshes (once)

    def _key_pressed(self):
        from managers.dignity_overlay import DignitySwitch
        DignitySwitch(self._gui).select(not self.key.lit)
        self._refresh_key()

    def _subscribe_keys(self):
        """The DIGNITY lamp follows every writer. The exclusivity rule itself
        (INV-2) is the window's (``managers.dignity_overlay.install_interlock``)."""
        from core.retinue_strength import KEY_ON
        from managers.dignity_overlay import MODE_KEY
        from managers.settings_manager import get_settings
        s = get_settings()
        me = self

        def _changed(_key, _value):
            if shiboken6.isValid(me):
                me._refresh_key()

        for key in (MODE_KEY, KEY_ON):
            s.on_changed(key, _changed)

        def _drop(*_):
            for key in (MODE_KEY, KEY_ON):
                s.remove_on_changed(key, _changed)
        self.destroyed.connect(_drop)

    # ---- theme and fonts
    def _style_label_colour(self, touched):
        th = _theme()
        colour = th["primary"] if touched else _mix(th["secondary_text"], th["secondary_dark"], 0.35)
        self.style_label.setStyleSheet(
            f"color: {colour}; font-size: {scaled_area_px('info_text')}px; font-weight: bold;"
            " background: transparent;")

    def refresh_theme(self):
        th = _theme()
        self._scroll.setStyleSheet(f"QScrollArea {{ background: {th['secondary_dark']}; border: none; }}")
        self.list.setStyleSheet(f"background-color: {th['secondary_dark']};")
        big = scaled_area_px("tables") + 2
        self.code_label.setStyleSheet(
            f"color: {th['primary']}; font-size: {big}px; font-weight: bold; background: transparent;")
        self.name_label.setStyleSheet(
            f"color: {th['secondary_text']}; font-size: {scaled_area_px('tables')}px;"
            " background: transparent;")
        self._style_label_colour(bool(self.style_label.property("touched")))
        self.chips.refresh_theme()
        self.list.updateGeometry()
        self.list.update()
        self._match_key_font()
        for key in (self.key, self.style_key):
            key.updateGeometry()
            key.update()
        self.key_strip.update()

    def _match_key_font(self):
        """The Strength keys' header font and height, so the DIGNITY key has
        their exact size on screen (the header sizes its keys with its own font)."""
        table = getattr(self._gui, "strength_table", None)
        if table is not None and shiboken6.isValid(table):
            header = table.horizontalHeader()
            for key in (self.key, self.style_key):
                key.setFont(header.font())
                key.header_height = header.height() if header.height() > 0 else None
                key.updateGeometry()

    def showEvent(self, event):
        self._match_key_font()
        super().showEvent(event)

