# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Chart B's frame and the frame header chips (SPEC-DUAL-001 §4.2).

``ChartBFrame`` sits in the Chart tab row right after ``chart_stack`` (inserted
once, hidden; shown in two-chart mode with the same stretch). It holds:

- a 32 px header row with a ``ChartHeaderChip`` (B = steel stripe, "B", name,
  "compared", round ✕; empty = hollow stripe, "B", italic "empty");
- the body: one ``ChartSideFrame`` (SI / Wheel / NI, display only), which is
  also the fullscreen companion widget;
- the empty bay over the body area while B is empty: a recessed well with the
  drag glyph, two lines of text and a bar segmented control
  "SKY NOW" | "OPEN .CHTK FILE...";
- drag feedback: a ring + tinted glyph on the empty bay, a veil "Drop to
  replace <B>" over a filled B. Removed on leave, drop, drag end and hide.

The frame owns no chart state: it renders what ChartPairManager hands it and
reports clicks and drops through callbacks (accept-and-refuse, INV-8). Every
colour is read from ``bar_tokens()`` / ``get_theme_colors()`` at paint time.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QHBoxLayout, QPushButton, QSizePolicy,
                               QVBoxLayout, QWidget)

from apps.widgets.action_bar import paint_surfaces
from apps.widgets.action_bar.bar_types import (BTN_TEXT, META_TEXT, NAME_TEXT,
                                               BarMetrics, draw_bar_text,
                                               effective_bar_fs, scaled_font,
                                               text_advance)
from apps.widgets.action_bar.motion import lerp_premul
from apps.widgets.action_bar.title_well import CloseGlyphButton
from apps.widgets.chart_side_frame import ChartSideFrame
from core.i18n import t
from ui.qt_theme import bar_tokens, get_scale_factor, scaled_px

HEADER_BASE = 32
CHIP_BASE = 24
ROLE_TEXT = (9.5, 650, 0.5 / 9.5)
VIEW_INDEX = {"south_indian": 0, "wheel": 1, "north_indian": 2}


def _metrics() -> BarMetrics:
    try:
        return BarMetrics(fs=effective_bar_fs(get_scale_factor()))
    except Exception:
        return BarMetrics(fs=1.0)


def _italic_adv(text: str, style, fs: float) -> float:
    from PySide6.QtGui import QFontMetricsF
    font, k = scaled_font(*style, fs=fs)
    font.setItalic(True)
    return QFontMetricsF(font).horizontalAdvance(text) / k


def _draw_italic(p, rect, text, style, fs):
    font, k = scaled_font(*style, fs=fs)
    font.setItalic(True)
    p.save()
    p.scale(1.0 / k, 1.0 / k)
    p.setFont(font)
    p.drawText(QRectF(rect.x() * k, rect.y() * k, rect.width() * k, rect.height() * k),
               Qt.AlignLeft | Qt.AlignVCenter, text)
    p.restore()


class ChartHeaderChip(QWidget):
    """A 24 px chip in the bar's well style above a chart (§4.2)."""

    close_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._m = _metrics()
        self._role = "a"
        self._name = ""
        self._note = ""
        self._closable = False
        self.close_btn = CloseGlyphButton(self._m, bar_tokens, self)
        self.close_btn.setToolTip(t("chart.pair.close_b_tip", "Back to one chart"))
        self.close_btn.clicked.connect(self.close_clicked)
        self.close_btn.hide()
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._resize()

    # ------------------------------------------------------------------ API
    def set_content(self, role: str, name: str, note: str, closable: bool):
        """``role`` "a" | "b" | "empty"."""
        self._role = role
        self._name = name or ""
        self._note = note or ""
        self._closable = bool(closable)
        self.close_btn.setVisible(self._closable)
        self._resize()
        self.update()

    def content(self) -> tuple:
        return (self._role, self._name, self._note, self._closable)

    def refresh_fonts(self):
        self._m = _metrics()
        self.close_btn.set_metrics(self._m)
        self._resize()
        self.update()

    def refresh_theme(self):
        self.update()

    # --------------------------------------------------------------- layout
    def _letter(self) -> str:
        return (t("chart.pair.label_a", "A") if self._role == "a"
                else t("chart.pair.label_b", "B"))

    def _parts(self):
        fs = self._m.fs
        gap = 7.0 * fs
        x = 7.0 * fs + self._m.stripe_w + gap
        letter_w = text_advance(self._letter(), *ROLE_TEXT, fs=fs)
        parts = [("letter", x, letter_w)]
        x += letter_w + gap
        if self._name:
            w = text_advance(self._name, *NAME_TEXT, fs=fs)
            parts.append(("name", x, w))
            x += w + gap
        if self._note:
            w = (_italic_adv(self._note, META_TEXT, fs) if self._role == "empty"
                 else text_advance(self._note, *META_TEXT, fs=fs))
            parts.append(("note", x, w))
            x += w + 3.0 * fs
        return parts, x

    def _resize(self):
        fs = self._m.fs
        parts, x = self._parts()
        w = x + (self._m.close_d + 4.0 * fs if self._closable else 4.0 * fs)
        h = round(CHIP_BASE * fs)
        self.setFixedSize(math.ceil(w), h)
        if self._closable:
            d = self._m.close_d
            self.close_btn.move(self.width() - round(4 * fs) - d, (h - d) // 2)

    def sizeHint(self):
        return QSize(self.width(), self.height())

    def paintEvent(self, _e):
        tok = bar_tokens()
        fs = self._m.fs
        p = QPainter(self)
        try:
            stripe = {"a": "gold", "b": "steel"}.get(self._role, "hollow")
            paint_surfaces.paint_title_well(p, QRectF(self.rect()), tok, self._m,
                                            self.devicePixelRatioF(), stripe=stripe)
            p.setRenderHint(QPainter.TextAntialiasing, True)
            parts, _x = self._parts()
            h = float(self.height())
            for kind, x, w in parts:
                r = QRectF(x, 0, w + 1, h)
                if kind == "letter":
                    p.setPen(tok["muted"])
                    draw_bar_text(p, r, Qt.AlignLeft | Qt.AlignVCenter, self._letter(),
                                  *ROLE_TEXT, fs=fs)
                elif kind == "name":
                    p.setPen(tok["primary_text"])
                    draw_bar_text(p, r, Qt.AlignLeft | Qt.AlignVCenter, self._name,
                                  *NAME_TEXT, fs=fs)
                elif self._role == "empty":
                    p.setPen(tok["muted"])
                    _draw_italic(p, r, self._note, META_TEXT, fs)
                else:
                    p.setPen(tok["muted"])
                    draw_bar_text(p, r, Qt.AlignLeft | Qt.AlignVCenter, self._note,
                                  *META_TEXT, fs=fs)
            if self._closable and self.close_btn.isVisible():
                btn = self.close_btn
                hot = max(btn._hover_fade.value(), btn._press_fade.value())
                from apps.widgets.action_bar import paint_controls
                paint_controls.close_hover_rim(p, QRectF(btn.geometry()), hot, tok,
                                               self.devicePixelRatioF())
        finally:
            p.end()


class _BayButton(QPushButton):
    """One segment of the bay's bar segmented control (painted)."""

    def __init__(self, text_fn, icon: str = "", parent=None):
        super().__init__(parent)
        self._text_fn = text_fn
        self._icon = icon
        self._hover = False
        self._m = _metrics()
        self.setAttribute(Qt.WA_Hover, True)
        self.setFocusPolicy(Qt.TabFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.refresh_fonts()

    def label(self) -> str:
        return self._text_fn()

    def refresh_fonts(self):
        self._m = _metrics()
        fs = self._m.fs
        w = text_advance(self.label(), *BTN_TEXT, fs=fs) + 2 * 10.0 * fs
        if self._icon:
            w += 13.0 * fs + 5.0 * fs
        self.setFixedSize(math.ceil(w), round(24 * fs))

    def enterEvent(self, e):
        super().enterEvent(e)
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        super().leaveEvent(e)
        self._hover = False
        self.update()

    def paintEvent(self, _e):
        tok = bar_tokens()
        fs = self._m.fs
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.Antialiasing, True)
            r = QRectF(self.rect())
            if self._hover or self.isDown():
                p.fillRect(r, tok["ctl_a"] if self.isDown() else tok["ctl_h"])
            fg = tok["primary_text"] if self._hover else tok["secondary_text"]
            x = 10.0 * fs
            if self._icon:
                from apps.widgets.action_bar import paint_controls
                pm = paint_controls.icon_pixmap(self._icon, 13.0 * fs, fg,
                                                self.devicePixelRatioF())
                if pm is not None:
                    side = 13.0 * fs
                    p.drawPixmap(QRectF(x, (r.height() - side) / 2.0, side, side), pm,
                                 QRectF(pm.rect()))
                x += 13.0 * fs + 5.0 * fs
            p.setPen(fg)
            draw_bar_text(p, QRectF(x, 0, r.width() - x, r.height()),
                          Qt.AlignLeft | Qt.AlignVCenter, self.label(), *BTN_TEXT, fs=fs)
        finally:
            p.end()


class _BaySegment(QWidget):
    """SKY NOW | OPEN .CHTK FILE... : bar cluster chrome + a divider."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.sky_btn = _BayButton(lambda: t("chart.pair.sky_now", "SKY NOW"), "now", self)
        self.file_btn = _BayButton(lambda: t("chart.pair.open_file", "OPEN .CHTK FILE..."),
                                   "", self)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.sky_btn)
        lay.addWidget(self.file_btn)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def refresh_fonts(self):
        self.sky_btn.refresh_fonts()
        self.file_btn.refresh_fonts()
        self.adjustSize()

    def paintEvent(self, _e):
        tok = bar_tokens()
        m = _metrics()
        p = QPainter(self)
        try:
            paint_surfaces.paint_cluster(p, QRectF(self.rect()), tok, m,
                                         self.devicePixelRatioF())
            x = float(self.file_btn.x())
            paint_surfaces.draw_vline(p, x, 5.0 * m.fs, self.height() - 10.0 * m.fs,
                                      tok["hair"], self.devicePixelRatioF(), css_px=0.5)
        finally:
            p.end()


class _EmptyBay(QWidget):
    """The recessed empty chart-B well: glyph, two lines, the segmented control."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._a_name = ""
        self._drag = False
        self.segment = _BaySegment(self)

    def set_a_name(self, name: str):
        self._a_name = name or ""
        self.update()

    def set_drag(self, on: bool):
        if bool(on) != self._drag:
            self._drag = bool(on)
            self.update()

    def drag(self) -> bool:
        return self._drag

    def texts(self) -> tuple[str, str]:
        body = t("chart.pair.bay_body",
                 "It opens as chart B, beside {a}. Drop another one later to replace it.",
                 a=self._a_name)
        return t("chart.pair.bay_title", "Drag a chart from the memory row here"), body

    def _fonts(self):
        f_title = QFont(self.font())
        f_title.setPixelSize(scaled_px(15))
        f_title.setWeight(QFont.Weight(550))
        f_body = QFont(self.font())
        f_body.setPixelSize(scaled_px(12))
        f_bold = QFont(f_body)
        f_bold.setWeight(QFont.Weight.DemiBold)
        return f_title, f_body, f_bold

    def _layout(self):
        """(glyph rect, title y, body y, segment top) centred as one block."""
        gap = scaled_px(14)
        glyph = scaled_px(54)
        f_title, f_body, _ = self._fonts()
        from PySide6.QtGui import QFontMetrics
        th = QFontMetrics(f_title).height()
        bh = QFontMetrics(f_body).height()
        sh = self.segment.height() + scaled_px(4)
        total = glyph + gap + th + gap + bh + gap + sh
        top = (self.height() - total) / 2.0
        g = QRectF((self.width() - glyph) / 2.0, top, glyph, glyph)
        ty = g.bottom() + gap
        by = ty + th + gap
        sy = by + bh + gap + scaled_px(4)
        return g, (ty, th), (by, bh), sy

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.segment.adjustSize()
        _g, _t, _b, sy = self._layout()
        self.segment.move(int((self.width() - self.segment.width()) / 2), int(sy))

    def paintEvent(self, _e):
        tok = bar_tokens()
        theme_dpr = self.devicePixelRatioF()
        m = _metrics()
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.Antialiasing, True)
            r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            path = QPainterPath()
            path.addRoundedRect(r, scaled_px(6), scaled_px(6))
            p.fillPath(path, tok["secondary"])
            p.fillPath(path, tok["well_h"] if self._drag else tok["well"])
            paint_surfaces.draw_inset_hairline(p, r, scaled_px(6), tok["well_line"], theme_dpr)
            if self._drag:
                p.setPen(QPen(tok["ring"], 1.5))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(r.adjusted(0.75, 0.75, -0.75, -0.75),
                                  scaled_px(6), scaled_px(6))
            g, (ty, th), (by, bh), _sy = self._layout()
            ink = QColor(tok["primary"]) if self._drag else QColor(tok["muted"])
            if self._drag:
                ink.setAlphaF(0.75)
            self._paint_glyph(p, g, ink)
            f_title, f_body, f_bold = self._fonts()
            title, body = self.texts()
            p.setFont(f_title)
            p.setPen(tok["secondary_text"])
            p.drawText(QRectF(0, ty, self.width(), th), Qt.AlignHCenter | Qt.AlignVCenter, title)
            self._paint_body(p, QRectF(0, by, self.width(), bh), body, f_body, f_bold, tok)
        finally:
            p.end()

    def _paint_body(self, p, rect, body, f_body, f_bold, tok):
        """The body line with A's name in bold (one run, centred)."""
        from PySide6.QtGui import QFontMetricsF
        name = self._a_name
        i = body.find(name) if name else -1
        runs = [(body, f_body, tok["muted"])] if i < 0 else [
            (body[:i], f_body, tok["muted"]), (name, f_bold, tok["primary_text"]),
            (body[i + len(name):], f_body, tok["muted"])]
        widths = [QFontMetricsF(f).horizontalAdvance(s) for s, f, _c in runs]
        x = rect.center().x() - sum(widths) / 2.0
        for (s, f, c), w in zip(runs, widths):
            p.setFont(f)
            p.setPen(c)
            p.drawText(QRectF(x, rect.y(), w + 1, rect.height()),
                       Qt.AlignLeft | Qt.AlignVCenter, s)
            x += w

    @staticmethod
    def _paint_glyph(p, g: QRectF, ink: QColor):
        """The mockup's 54-unit drag glyph: a memory chip, an arrow, a slot."""
        s = g.width() / 54.0
        p.save()
        p.translate(g.topLeft())
        p.scale(s, s)
        pen = QPen(ink, 1.6)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(6, 8, 30, 13), 3.5, 3.5)
        faint = QColor(ink)
        faint.setAlphaF(ink.alphaF() * 0.55)
        p.setPen(QPen(faint, 1.6, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(12, 14.5), QPointF(30, 14.5))
        p.setPen(QPen(ink, 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawLine(QPointF(21, 25), QPointF(21, 39))
        p.drawPolyline([QPointF(15, 33), QPointF(21, 39), QPointF(27, 33)])
        p.setPen(QPen(faint, 1.4))
        p.drawRoundedRect(QRectF(10, 42, 38, 8), 2, 2)
        p.restore()


class _ReplaceVeil(QWidget):
    """Over a filled B during a drag: a veil, the ring and "Drop to replace <B>"."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._b_name = ""
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.hide()

    def set_b_name(self, name: str):
        self._b_name = name or ""
        self.update()

    def text(self) -> str:
        return t("chart.pair.replace", "Drop to replace {b}", b=self._b_name)

    def paintEvent(self, _e):
        tok = bar_tokens()
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.Antialiasing, True)
            r = QRectF(self.rect()).adjusted(0.75, 0.75, -0.75, -0.75)
            veil = QColor(tok["secondary"])
            veil.setAlphaF(0.78)
            path = QPainterPath()
            path.addRoundedRect(r, scaled_px(6), scaled_px(6))
            p.fillPath(path, veil)
            p.setPen(QPen(tok["ring"], 1.5))
            p.drawPath(path)
            f = QFont(self.font())
            f.setPixelSize(scaled_px(13))
            p.setFont(f)
            from PySide6.QtGui import QFontMetricsF
            fm = QFontMetricsF(f)
            text = self.text()
            w = fm.horizontalAdvance(text) + 2 * scaled_px(12)
            h = fm.height() + 2 * scaled_px(7)
            box = QRectF((self.width() - w) / 2.0, (self.height() - h) / 2.0, w, h)
            lab = QPainterPath()
            lab.addRoundedRect(box, scaled_px(7), scaled_px(7))
            p.fillPath(lab, tok["menu_fill"])
            p.setPen(QPen(tok["hair"], 0.5))
            p.drawPath(lab)
            p.setPen(tok["secondary_text"])
            p.drawText(box, Qt.AlignCenter, text)
        finally:
            p.end()


class _BodyHost(QWidget):
    """Holds the side frame in a plain VBox (the fullscreen companion's owning
    layout) and the bay / veil as overlay children sized to it."""

    def __init__(self, body: ChartSideFrame, parent=None):
        super().__init__(parent)
        self.body_layout = QVBoxLayout(self)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(0)
        self.body_layout.addWidget(body, 1)
        self.bay = _EmptyBay(self)
        self.veil = _ReplaceVeil(self)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.bay.setGeometry(self.rect())
        self.veil.setGeometry(self.rect())


class ChartBFrame(QWidget):
    """Chart B: header chip row + body (or the empty bay); a drop target."""

    def __init__(self, *, on_drop=None, on_sky_now=None, on_open_file=None,
                 on_close=None, on_shown=None, parent=None):
        super().__init__(parent)
        self._on_drop = on_drop
        self._on_shown = on_shown
        self._empty = True
        self._b_name = ""
        self._a_name = ""
        self.setAcceptDrops(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.header_row = QWidget()
        self.header_row.setFixedHeight(scaled_px(HEADER_BASE))
        hl = QHBoxLayout(self.header_row)
        hl.setContentsMargins(0, 0, 0, 0)
        self.chip = ChartHeaderChip()
        hl.addWidget(self.chip, 0, Qt.AlignVCenter)
        hl.addStretch(1)
        outer.addWidget(self.header_row)

        self.body = ChartSideFrame(title="", empty_name="", min_size=0, margins=0)
        self.body.chrome.hide()                  # the header chip carries the identity
        self.body.register_hosts()
        self.body_host = _BodyHost(self.body)
        outer.addWidget(self.body_host, 1)

        bay = self.body_host.bay
        if on_sky_now is not None:
            bay.segment.sky_btn.clicked.connect(on_sky_now)
        if on_open_file is not None:
            bay.segment.file_btn.clicked.connect(on_open_file)
        if on_close is not None:
            self.chip.close_clicked.connect(on_close)
        # The views are new and hold no chart: nothing to clear. Clearing drew
        # three empty charts behind the hidden body at every boot (2.7 s,
        # 2026-10-23 profile); show_chart redraws them before the body shows.
        self.show_empty("", clear_body=False)

    # ------------------------------------------------------------------- API
    @property
    def bay(self):
        return self.body_host.bay

    @property
    def veil(self):
        return self.body_host.veil

    def body_layout(self):
        """The companion's owning layout (SPEC-FSV-001 companion key)."""
        return self.body_host.body_layout

    def is_empty(self) -> bool:
        return self._empty

    def show_chart(self, chart, label, *, varga_code=None, use_western_names=False,
                   aditya_mode=None):
        """Render B (display only), header "B <name> compared". Only the
        on-screen view draws now; the other two are drawn by sync_chart_view
        (set_view_index flushes them) before they show (M3, td-n0o9)."""
        self._empty = False
        self._b_name = label or ""
        self.body.update_visible_only(chart, name=self._b_name, varga_code=varga_code,
                                      use_western_names=use_western_names,
                                      aditya_mode=aditya_mode)
        self.body.show()
        self.bay.hide()
        self.veil.set_b_name(self._b_name)
        self.chip.set_content("b", self._b_name, t("chart.pair.header_b", "compared"), True)

    def show_empty(self, a_name: str | None = None, *, clear_body=True):
        """The empty bay (B none); ``a_name`` names chart A in the bay text."""
        if a_name is not None:
            self._a_name = a_name
        self._empty = True
        self._b_name = ""
        if clear_body:
            self.body.clear()
        self.body.hide()
        self.bay.set_a_name(self._a_name)
        self.bay.show()
        self.bay.raise_()
        self.veil.hide()
        self.chip.set_content("empty", "", t("chart.pair.header_empty", "empty"), False)

    def set_a_name(self, name: str):
        self._a_name = name or ""
        self.bay.set_a_name(self._a_name)

    def b_name(self) -> str:
        return self._b_name

    def supported_chart_views(self):
        return frozenset(VIEW_INDEX)

    def sync_chart_view(self, style):
        """INV-12: only switch the side frame's page (SI / Wheel / NI)."""
        idx = VIEW_INDEX.get(style)
        if idx is not None:
            self.body.set_view_index(idx)

    def current_view(self):
        return self.body.current_view()

    def refresh_theme(self):
        self.body.refresh_theme()
        for w in (self.chip, self.bay, self.bay.segment, self.veil, self):
            w.update()

    def refresh_fonts(self):
        self.header_row.setFixedHeight(scaled_px(HEADER_BASE))
        self.chip.refresh_fonts()
        self.bay.segment.refresh_fonts()
        self.bay.update()

    # ---------------------------------------------------------- drag & drop
    def _kind(self, mime):
        from apps.widgets.chart_drop_common import chart_payload_kind
        return chart_payload_kind(mime)

    def _drag_on(self):
        if self._empty:
            self.bay.set_drag(True)
        else:
            self.veil.setGeometry(self.body_host.rect())
            self.veil.show()
            self.veil.raise_()

    def _drag_off(self):
        self.bay.set_drag(False)
        self.veil.hide()

    def drag_active(self) -> bool:
        return self.bay.drag() or self.veil.isVisible()

    def dragEnterEvent(self, event):
        if self._kind(event.mimeData()) is not None:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.acceptProposedAction()
            self._drag_on()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if self._kind(event.mimeData()) is not None:
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event):
        self._drag_off()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._drag_off()
        mime = event.mimeData()
        if self._kind(mime) is None:
            super().dropEvent(event)
            return
        event.acceptProposedAction()           # INV-8: accept, then refuse inside
        if callable(self._on_drop):
            self._on_drop(mime)

    def hideEvent(self, event):
        self._drag_off()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if callable(self._on_shown):
            self._on_shown()
