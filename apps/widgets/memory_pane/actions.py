# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The 2x2 actions (MC-INTENT "2x2 actions", "CLEAR ALL", "SELECT ON", "⋯").

Twin Rails footprint in the Glass Shelf look: two raised 24 px capsules,
4 px apart, [SEARCH | SORT] over [SELECT | CLEAR ALL], both sharing the same
two column widths so the inner dividers line up. At S3 the block is one 30 px
column, [SEARCH] over [⋯]. States change colour only, never geometry.

Each cell is a real QPushButton (``click()``, ``clicked``, tooltips, focus),
painted here; the panel decides what each cell says and does.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QLabel, QPushButton, QWidget

from apps.widgets.action_bar.paint_surfaces import draw_vline

from .paint import (KeyboardFocusMixin, area_qss, cap_baseline, text_width, design_font, dpr_of, draw_icon, paint_accent,
                    paint_drop, paint_raised, rounded)
from .tokens import pane_tokens

PILL_H = 24
PILL_GAP = 4
PILL_RADIUS = 12.0
MARGIN = 2           # room for the capsules' drop shadow inside this widget
ICON = 11.0

PLAIN, PRIMARY_ICON, DANGER = "plain", "primary_icon", "danger"


class PillCell(KeyboardFocusMixin, QPushButton):
    """One cell of a capsule."""

    def __init__(self, name, parent=None):
        super().__init__("", parent)
        self.setObjectName("memoryPillCell")
        self.cell_name = name
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.icon_name = ""
        self.texts = {"full": "", "short": "", "icons": ""}
        self.kind = PLAIN
        self.active = False          # Select ON (green)
        self.dot = False             # ⋯ while Select is on (S3)
        self.labels = "full"
        self.pill_rect = QRectF()    # the capsule, in this cell's coordinates
        self.first_in_row = True
        self._hover = False
        self.apply_font()

    def apply_font(self):
        # qt-material's QPushButton "height: 32px" beats setGeometry: pin it.
        self.setStyleSheet(
            "QPushButton#memoryPillCell { border: none; background: transparent;"
            " padding: 0px; margin: 0px; min-width: 0px;"
            " height: %dpx; min-height: %dpx; max-height: %dpx; %s }"
            % (PILL_H, PILL_H, PILL_H, area_qss("buttons", 9)))

    def set_content(self, icon, full, short=None, icons="", kind=PLAIN):
        self.icon_name = icon
        self.texts = {"full": full, "short": full if short is None else short,
                      "icons": icons}
        self.kind = kind
        self.setText(full)
        self.update()

    def shown_text(self) -> str:
        key = {"full": "full", "short": "short"}.get(self.labels, "icons")
        return self.texts.get(key, "")

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _e):
        tok = pane_tokens()
        dpr = dpr_of(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect())
        clip = QPainterPath()
        clip.addRect(r)
        clip = clip.intersected(rounded(self.pill_rect, PILL_RADIUS))
        enabled = self.isEnabled()
        hot = enabled and self._hover
        down = enabled and self.isDown()
        danger = self.kind == DANGER

        fg = tok["red_fg"] if danger else tok["secondary_text"]
        icon_col = (tok["red"] if danger else
                    tok["primary"] if self.kind == PRIMARY_ICON else fg)
        if self.active or self.dot:
            p.fillPath(clip, tok["tint_green"])
            fg = tok["tint_green_fg"]
            icon_col = tok["green"] if self.active else fg
        if down:
            p.fillPath(clip, tok["red_press"] if danger else tok["ov_a"])
        elif hot:
            p.fillPath(clip, tok["red"] if danger else tok["ov_h"])
        if danger and (hot or down):
            fg = icon_col = tok["fg_on_accent"]
        elif hot and not (self.active or self.dot):
            fg = tok["primary_text"]
            if self.kind == PLAIN:
                icon_col = fg

        if not self.first_in_row:
            draw_vline(p, 0.0, 5.0, r.height() - 10.0, tok["hair_soft"], dpr, css_px=1.0)

        if not enabled:
            p.setOpacity(0.45)
        text = self.shown_text()
        font = design_font(self, 9, 620, .045, caps=True)
        fm = QFontMetricsF(font)
        icon = self.icon_name
        if self.active and icon == "mp_chk":
            icon = "mp_chk_on"
        iw = ICON if icon else 0.0
        gap = 4.0 if (icon and text) else 0.0
        avail = max(0.0, r.width() - 10.0 - iw - gap)
        text = fm.elidedText(text, Qt.TextElideMode.ElideRight, avail) if text else ""
        tw = text_width(font, text)
        x = (r.width() - (iw + gap + tw)) / 2.0
        if icon:
            draw_icon(p, icon, QRectF(x, (r.height() - ICON) / 2.0, ICON, ICON), icon_col, dpr)
        if text:
            p.setFont(font)
            p.setPen(fg)
            p.drawText(QPointF(x + iw + gap, cap_baseline(font, 0.0, r.height())), text)
        p.setOpacity(1.0)

        if self.active:
            paint_accent(p, 8.0, r.width() - 8.0, r.height() - 2.5,
                         tok["green"], tok["acc_green_glow"], dpr)
        if self.dot:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(tok["green"])
            p.drawEllipse(QRectF(r.width() - 8.0, 4.0, 4.0, 4.0))
        if self.focus_visible():
            p.setPen(QPen(tok["ring"], 2.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(clip.translated(0, 0))
        p.end()


class ActionPills(QWidget):
    """Two capsules of cells; ``apply_step`` sets the columns and labels."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("memoryActionPills")
        self.search_cell = PillCell("search", self)
        self.sort_cell = PillCell("sort", self)
        self.select_cell = PillCell("select", self)
        self.clear_cell = PillCell("clear", self)
        self.more_cell = PillCell("more", self)
        self.more_cell.set_content("more", "")
        self.col1, self.col2 = 70, 90
        self.folded = False
        self._pills = (QRectF(), QRectF())

    def cells(self):
        return (self.search_cell, self.sort_cell, self.select_cell,
                self.clear_cell, self.more_cell)

    def apply_step(self, col1: int, col2: int, labels: str):
        self.col1, self.col2 = int(col1), int(col2)
        self.folded = labels == "fold"
        for c in self.cells():
            c.labels = labels
        width = self.col1 + (0 if self.folded else self.col2)
        self.setFixedSize(width + 2 * MARGIN, 2 * PILL_H + PILL_GAP + 2 * MARGIN)
        self._layout()

    def _layout(self):
        w = self.col1 + (0 if self.folded else self.col2)
        top = QRectF(MARGIN, MARGIN, w, PILL_H)
        bottom = QRectF(MARGIN, MARGIN + PILL_H + PILL_GAP, w, PILL_H)
        self._pills = (top, bottom)
        rows = (((self.search_cell,), (self.more_cell,)) if self.folded else
                ((self.search_cell, self.sort_cell), (self.select_cell, self.clear_cell)))
        placed = set()
        for pill, row in zip(self._pills, rows):
            x = pill.x()
            for i, cell in enumerate(row):
                cw = self.col1 if i == 0 else self.col2
                cell.setGeometry(round(x), round(pill.y()), cw, PILL_H)
                cell.pill_rect = pill.translated(-round(x), -round(pill.y()))
                cell.first_in_row = i == 0
                cell.show()
                cell.update()
                placed.add(cell)
                x += cw
        for cell in self.cells():
            if cell not in placed:
                cell.hide()
        self.update()

    def paintEvent(self, _e):
        tok = pane_tokens()
        dpr = dpr_of(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for pill in self._pills:
            if pill.isEmpty():
                continue
            paint_drop(p, pill, PILL_RADIUS, tok["drop"])
            paint_raised(p, pill, PILL_RADIUS, tok["pill_top"], tok["pill_bottom"],
                         tok["hair"], tok, dpr)
        p.end()


class DangerMenuRow(QLabel):
    """The ⋯ menu's red "Clear all…" row (mockup ``.mi.danger``): red text,
    red fill with white text under the pointer. Emits ``chosen`` on click."""

    chosen = Signal()

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setObjectName("memoryDangerRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        tok = pane_tokens()
        red, white = tok["red"].name(), tok["fg_on_accent"].name()
        self.setStyleSheet(
            f"QLabel#memoryDangerRow {{ color: {red}; background: transparent;"
            f" padding: 4px 12px 4px 22px; border-radius: 5px; }}"
            f"QLabel#memoryDangerRow:hover {{ color: {white}; background: {red}; }}")

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.chosen.emit()
            return
        super().mouseReleaseEvent(e)
