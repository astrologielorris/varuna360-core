# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""The Library sheet's small widgets: its buttons and labels in the kit's
colours. Shared by CHECK CHARTS and Sort with AI (moved out of
``sort_with_ai``, which Lite does not ship: SPEC-EDN-002 P4)."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import QLabel, QPushButton

from apps.widgets.action_bar.paint_controls import icon_pixmap
from panels.find_chart import kit
from ui.qt_theme import scaled_area_px


def _px(area: str) -> int:
    return scaled_area_px(area)


def _hexa(c: QColor) -> str:
    return QColor(c).name(QColor.HexArgb)


class _SheetButton(QPushButton):
    """A sheet button in the kit's colours: "solo", "fill", "gold", "green"."""

    def __init__(self, text: str, variant: str = "solo", icon: str = "", parent=None):
        super().__init__(text, parent)
        self._variant = variant
        self._icon_id = icon
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(text)
        self.refresh_theme()

    @property
    def variant(self) -> str:
        return self._variant

    def refresh_theme(self) -> None:
        t = kit.tokens()
        bg, fg, hover = {
            "fill": (t["primary"], t["fg_on_accent"], t["primary_dark"]),
            "gold": (t["tint_gold"], t["tint_gold_fg"], t["tint_gold_h"]),
            "green": (t["tint_green"], t["tint_green_fg"], t["tint_green_h"]),
        }.get(self._variant, (t["ctl"], t["primary_text"], t["ctl_h"]))
        px = _px("buttons")
        self.setStyleSheet(
            f"QPushButton {{ background: {_hexa(bg)}; color: {fg.name()};"
            f" border: 1px solid {_hexa(t['hair_soft'])}; border-radius: 6px;"
            f" padding: 4px 10px; font-size: {px}px; font-weight: 600;"
            " letter-spacing: 0.04em; }"
            f"QPushButton:hover {{ background: {_hexa(hover)}; }}"
            f"QPushButton:disabled {{ color: {t['muted'].name()}; }}"
        )
        if self._icon_id:
            size = round(px * 1.3)
            pix = icon_pixmap(self._icon_id, size, QColor(fg), self.devicePixelRatioF())
            if pix is not None:
                self.setIcon(QIcon(pix))
                self.setIconSize(QSize(size, size))

    refresh_metrics = refresh_theme


class _OneLine(QLabel):
    """A one-line label that never widens the sheet: given less room than
    its text, it shows the text cut with "…" and the full text as a tooltip.
    ``text()`` returns the full text. A plain no-wrap QLabel makes its whole
    text the sheet's minimum width, and a narrow sheet (a large text font
    with a small button font) then scrolls sideways out of reach."""

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(parent)
        self._full = ""
        self._auto_tip = False
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setText(text)

    def setText(self, text) -> None:  # noqa: N802 (Qt name)
        self._full = str(text or "")
        self._elide()
        self.updateGeometry()

    def text(self) -> str:
        return self._full

    def sizeHint(self) -> QSize:
        m = self.contentsMargins()
        w = self.fontMetrics().horizontalAdvance(self._full) + m.left() + m.right() + 2
        return QSize(w, super().sizeHint().height())

    def minimumSizeHint(self) -> QSize:
        least = self.fontMetrics().horizontalAdvance("MMMM…")
        return QSize(min(self.sizeHint().width(), least), super().minimumSizeHint().height())

    def _elide(self) -> None:
        room = self.contentsRect().width() - 2
        shown = self._full
        if room > 0 and self.fontMetrics().horizontalAdvance(shown) > room:
            shown = self.fontMetrics().elidedText(shown, Qt.ElideRight, room)
        QLabel.setText(self, shown)
        if shown != self._full and (self._auto_tip or not self.toolTip()):
            self.setToolTip(self._full)
            self._auto_tip = True
        elif shown == self._full and self._auto_tip:
            self.setToolTip("")
            self._auto_tip = False

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._elide()

    def changeEvent(self, e) -> None:
        super().changeEvent(e)
        if e.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._elide()
            self.updateGeometry()


def _label(text: str = "", *, wrap: bool = True) -> QLabel:
    if not wrap:
        return _OneLine(text)
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setTextFormat(Qt.TextFormat.PlainText)
    return lab


def _style_label(lab: QLabel, role: str, area: str = "info_text", *, bold=False) -> None:
    t = kit.tokens()
    color = {"muted": t["muted"], "secondary": t["secondary_text"],
             "gold": t["gold"], "green": t["green"]}.get(role, t["primary_text"])
    lab.setStyleSheet(
        f"color: {color.name()}; font-size: {_px(area)}px;"
        f" font-weight: {600 if bold else 400}; background: transparent;"
    )
