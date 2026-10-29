# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The Find Chart panel's visual kit (SPEC-FIND-005 §4.1).

The panel speaks the chart action bar's language (SPEC-BAR-001): its toolbar
segments ARE the bar's ``SegmentButton`` / ``SegmentCluster``, and the other
pieces (search well, chips, switch, tick box, progress line, coverage ring,
sheet, collapsible section) are painted the same way. Colours come from
``bar_tokens()`` read at paint time (Rule 20, live theme), bar sizes from
``BarMetrics(effective_bar_fs(get_scale_factor()))`` and the remaining text
from ``scaled_area_px`` font areas (INV-10).

No module of ``pro/`` is imported: ``KitSegment`` is the core twin of Pro's
``BarSegment``.
"""

from __future__ import annotations

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPoint,
    QPointF,
    QRect,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QFrame,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QWidgetItem,
)

from apps.widgets.action_bar.bar_types import (
    BTN_TEXT,
    META_TEXT,
    BarMetrics,
    Role,
    SegPos,
    SegSpec,
    draw_bar_text,
    effective_bar_fs,
    text_advance,
)
from apps.widgets.action_bar.clusters import SegmentCluster
from apps.widgets.action_bar.paint_controls import icon_pixmap
from apps.widgets.action_bar.segment_button import SegmentButton
from ui.qt_theme import bar_tokens, get_scale_factor, scaled_area_px

#: Icon ids are ``fc_<name>``; SegmentButton resolves ``img/icons/bar_<id>.svg``.
ICONS = (
    "fc_search",
    "fc_sparkle",
    "fc_globe",
    "fc_filters",
    "fc_library",
    "fc_folder",
    "fc_rebuild",
    "fc_cpu",
    "fc_columns",
    "fc_expand",
    "fc_sort",
    "fc_add",
    "fc_chevr",
    "fc_easy",
    "fc_advanced",
    "fc_folder_arrow",
    "fc_open",
    "fc_more",
    "fc_back",
    "fc_lock",
)

#: The toolbar's container height around the 40 px bar controls (mockup 44).
TOOLBAR_H = 44
#: The docked inspector's width (x fs).
INSPECTOR_W = 420  # SPEC-FIND-007 §3: the Glance Chart, about 390 px square
#: The SearchWell's minimum width (x fs), §4.8.
SEARCH_MIN_W = 160

# Measured and painted identically; leave enough space around the small badge.
ADV_TEXT = (9.5, 550, 0.025)


def metrics() -> BarMetrics:
    """The live bar metrics: app scale x the action_buttons font area."""
    return BarMetrics(effective_bar_fs(get_scale_factor()))


def area_fs(area: str) -> float:
    """The scale for text painted in the ``area`` font area (INV-10): the app
    scale x that area's ratio to its default, exactly 1.0 at the defaults
    (as ``effective_bar_fs`` does for ``action_buttons``)."""
    from ui.qt_theme import AREA_DEFAULTS, get_area_font_size

    default = AREA_DEFAULTS.get(area) or 12
    return get_scale_factor() * (get_area_font_size(area) / default)


#: How far a raised panel surface (picker columns, result rows, sheets) sits
#: from the theme's panel ground towards its raised colour, in a dark theme.
#: 0.4 keeps the lift the panel had with the bar's frozen neutral grey (same
#: lightness over qt-material's dark ground) while carrying the theme's hue.
RAISE_DARK = 0.4
#: The status bar's darkening of the panel ground (dark theme): the old
#: translucent neutral bar_b over the ground measured ~22 % darker.
STATUS_SINK_DARK = 0.22

_SURFACE_CACHE: tuple | None = None   # (theme signature, surface overrides)


def _blend(a: QColor, b: QColor, t: float) -> QColor:
    return QColor(round(a.red() + (b.red() - a.red()) * t),
                  round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t))


def _surface_overrides() -> dict:
    """The panel's SURFACE colours from the live theme (Rule 20).

    ``bar_tokens()`` freezes its eight pure keys to the chart action bar's
    neutral design palette in a dark theme (``_BAR_PURE_DARK``: secondary_light
    = HOVER, a neutral grey), on purpose for the bar. Painted as a whole
    panel surface that grey reads warm next to the theme's tinted ground
    (Lorris, 2026-10-22: picker columns, result rows), so the panel takes its surfaces from ``get_theme_colors()`` instead. A light theme's
    bar keys already ARE the theme's, so nothing changes there."""
    global _SURFACE_CACHE
    from ui.qt_theme import get_theme_colors, is_light_theme

    theme = get_theme_colors()
    sig = (bool(is_light_theme()), tuple(sorted(theme.items())))
    if _SURFACE_CACHE is not None and _SURFACE_CACHE[0] == sig:
        return _SURFACE_CACHE[1]
    out: dict = {}
    if not sig[0]:
        ground = QColor(theme["secondary"])
        raised = QColor(theme["secondary_light"])
        if ground.isValid() and raised.isValid():
            out["secondary"] = QColor(ground)
            out["secondary_light"] = _blend(ground, raised, RAISE_DARK)
            out["menu_fill"] = _alpha(ground, .88)
            out["bar_b"] = _blend(ground, QColor(0, 0, 0), STATUS_SINK_DARK)
    _SURFACE_CACHE = (sig, out)
    return out


def tokens() -> dict:
    """The bar's token table with the panel's surfaces taken from the theme."""
    t = bar_tokens()
    t.update({k: QColor(v) for k, v in _surface_overrides().items()})
    return t


def _opaque(color: QColor) -> QColor:
    c = QColor(color)
    c.setAlpha(255)
    return c


def menu_style() -> str:
    """The QSS of every Find Chart popup menu, from the live theme.

    Every colour is OPAQUE: a QMenu is a top-level popup with nothing under it
    to blend with, so the bar's translucent tokens (``menu_fill``, ``hair_soft``)
    rendered black on a light theme (Lorris, 2026-10-25, reported many times).
    Translucent tokens are composed over the menu fill first."""
    t = tokens()
    fill = _opaque(t["menu_fill"])

    def over(key: str) -> str:
        c = t[key]
        return _blend(fill, _opaque(c), c.alphaF()).name()

    px = scaled_area_px("buttons")
    return (
        f"QMenu {{ background: {fill.name()}; color: {over('primary_text')};"
        f" border: 1px solid {over('hair')}; font-size: {px}px; padding: 4px 0; }}"
        f"QMenu::item {{ background: transparent; padding: 0 18px;"
        f" min-height: {round(px * 1.9)}px; max-height: {round(px * 1.9)}px; }}"
        f"QMenu::item:selected {{ background: {_opaque(t['primary']).name()};"
        f" color: {t['fg_on_accent'].name()}; }}"
        f"QMenu::item:disabled {{ color: {over('muted')}; }}"
        f"QMenu::separator {{ height: 1px; background: {over('hair_soft')};"
        f" margin: 4px 8px; }}"
    )


def style_menu(menu):
    """Theme ``menu`` now and again each time it opens (a theme switch while
    a long-lived menu exists still reaches it). Returns the menu."""
    menu.setStyleSheet(menu_style())
    if not menu.property("fc_menu_styled"):
        menu.setProperty("fc_menu_styled", True)
        menu.aboutToShow.connect(lambda m=menu: m.setStyleSheet(menu_style()))
    return menu


def dialog_style() -> str:
    """The QSS of every Find Chart dialog (message boxes), from the live theme.

    A dialog parented to the panel inherits its transparent backgrounds, and a
    top-level window with a transparent background renders black (Lorris
    2026-10-25: the "Compute for this search" box was black on Light Blue).
    Every colour is opaque, composed over the menu fill like ``menu_style``."""
    t = tokens()
    fill = _opaque(t["menu_fill"])

    def over(key: str) -> str:
        c = t[key]
        return _blend(fill, _opaque(c), c.alphaF()).name()

    px = scaled_area_px("info_text")
    return (
        f"QDialog, QMessageBox {{ background: {fill.name()}; }}"
        f"QDialog QLabel, QMessageBox QLabel {{ color: {over('primary_text')};"
        f" background: transparent; font-size: {px}px; }}"
        f"QDialog QCheckBox, QMessageBox QCheckBox {{ color: {over('primary_text')};"
        f" background: transparent; font-size: {px}px; }}"
        f"QDialog QPushButton, QMessageBox QPushButton {{ background: {over('ctl')};"
        f" color: {over('primary_text')}; border: 1px solid {over('hair')};"
        f" border-radius: 6px; padding: 5px 16px; min-width: 64px; font-size: {px}px; }}"
        f"QDialog QPushButton:hover, QMessageBox QPushButton:hover {{"
        f" border-color: {_opaque(t['primary']).name()}; }}"
        f"QDialog QPushButton:default, QMessageBox QPushButton:default {{"
        f" background: {_opaque(t['primary']).name()}; color: {t['fg_on_accent'].name()};"
        f" border-color: {_opaque(t['primary']).name()}; }}"
    )


def style_dialog(dialog):
    """Theme ``dialog`` (a QMessageBox or QDialog) now. Returns it."""
    dialog.setStyleSheet(dialog_style())
    return dialog


def message(parent, icon, title: str, text: str) -> None:
    """A themed one-button message box (replaces ``QMessageBox.information``
    / ``.warning``, which inherit the panel's transparent background)."""
    from PySide6.QtWidgets import QMessageBox
    box = style_dialog(QMessageBox(parent))
    box.setIcon(icon)
    box.setWindowTitle(title)
    box.setText(text)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.exec()


def _alpha(color: QColor, a: float) -> QColor:
    c = QColor(color)
    c.setAlphaF(max(0.0, min(1.0, c.alphaF() * a)))
    return c


def _rounded(rect: QRectF, r: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, r, r)
    return path


def _hair(p: QPainter, rect: QRectF, r: float, color: QColor) -> None:
    p.setPen(QPen(color, 1.0))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), r, r)


def draw_icon(p: QPainter, icon_id: str, rect: QRectF, color: QColor) -> None:
    dpr = p.device().devicePixelRatioF() if p.device() else 1.0
    pix = icon_pixmap(icon_id, rect.width(), color, dpr)
    if pix is not None:
        p.drawPixmap(QPointF(round(rect.x()), round(rect.y())), pix)


# ----------------------------------------------------------------- segments


def _selection_tokens() -> dict:
    """Selected modes use the same solid accent/white ink as checked chips."""
    t = dict(bar_tokens())
    t["tint_blue"] = t["primary"]
    t["tint_blue_fg"] = t["fg_on_accent"]
    return t


class KitSegment(SegmentButton):
    """A toolbar segment in the bar's look: ``fc_`` key (never a LADDER row),
    labels swapped by the panel's own tier table (``compact_label``)."""

    def __init__(self, key, label, m: BarMetrics, *, role=Role.PLAIN, icon="",
                 checkable=False, tooltip="", accent_selection=False):
        self.full_label = label
        super().__init__(
            SegSpec("fc_" + key, [label], icon=icon,
                    role=Role.TINT_BLUE if accent_selection else role,
                    checkable=checkable, tooltip=tooltip or label),
            m,
            _selection_tokens if accent_selection else bar_tokens,
        )
        self.set_position(SegPos.SOLO)
        self.setAccessibleName(tooltip or label)

    def compact_label(self, text: str) -> None:
        """Show ``text`` ("" = icon only); the box follows it."""
        if self._spec.labels == [text]:
            return
        self._spec.labels = [text]
        self.set_base_label(text)
        self.set_metrics(self._m)

    def width_for(self, text: str) -> int:
        """This segment's box with ``text`` as its label, without changing it
        (the toolbar's label-fit measurement, §4.8)."""
        return self._m.button_width([text], with_icon=bool(self._spec.icon))


def kit_cluster(buttons: list[KitSegment], m: BarMetrics) -> SegmentCluster:
    return SegmentCluster(buttons, m, bar_tokens)


# ----------------------------------------------------------------- painting


class _Painted(QWidget):
    """Base for painted kit widgets: repaint on palette/style change."""

    def changeEvent(self, event):
        super().changeEvent(event)
        self.update()


# ------------------------------------------------------------------ flow layout


class FlowLayout(QLayout):
    """Left to right, wrapping to the next line when the width runs out."""

    def __init__(self, parent=None, hspace: int = 6, vspace: int = 6):
        super().__init__(parent)
        self._items: list = []
        self._h = hspace
        self._v = vspace
        self.setContentsMargins(0, 0, 0, 0)

    def set_spacing(self, h: int, v: int) -> None:
        self._h, self._v = h, v
        self.invalidate()

    def addItem(self, item):  # noqa: N802
        self._items.append(item)

    def addWidget(self, w):  # noqa: N802
        self.addChildWidget(w)
        self.addItem(QWidgetItem(w))

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, i):  # noqa: N802
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):  # noqa: N802
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._do(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect):  # noqa: N802
        super().setGeometry(rect)
        self._do(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            if item.widget() is None or not item.widget().isHidden():
                size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do(self, rect: QRect, apply: bool) -> int:
        m = self.contentsMargins()
        r = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_h = r.x(), r.y(), 0
        visible = [i for i in self._items if i.widget() is None or not i.widget().isHidden()]
        for item in visible:
            hint = item.sizeHint()
            if hint.width() > r.width() and item.minimumSize().width() < hint.width():
                # A shrinkable item wider than the line: the line's width
                # (it elides), never wider than the layout (round 9: 390 px).
                width = max(item.minimumSize().width(), r.width())
                height = item.heightForWidth(width) if item.hasHeightForWidth() else -1
                hint = QSize(width, height if height > 0 else hint.height())
            if x + hint.width() > r.right() + 1 and line_h > 0:
                x = r.x()
                y += line_h + self._v
                line_h = 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._h
            line_h = max(line_h, hint.height())
        return (y + line_h - rect.y() + m.bottom()) if visible else 0



class SectionHeader(QLabel):
    """Uppercase muted caption (the mockup's column and sheet titles)."""

    def __init__(self, text: str, parent=None):
        super().__init__(text.upper(), parent)
        self.refresh_theme()

    def refresh_theme(self) -> None:
        t = tokens()
        self.setStyleSheet(
            f"color: {t['secondary_text'].name()}; font-size: {round(scaled_area_px('panel_titles') * .75)}px;"
            " font-weight: 600; letter-spacing: 0.06em; background: transparent;"
        )


class Chip(QAbstractButton):
    """A rounded chip (filter, column group, suggestion, token).

    ``dot``: ``""``, ``"amber"`` (not computed) or ``"red"`` (invalid);
    ``closable`` paints an x and emits ``close_clicked``; ``adv`` paints the
    small ADV tag; checkable chips fill with the accent when on. Text and
    geometry follow the ``info_text`` font area (INV-10)."""

    AREA = "info_text"

    close_clicked = Signal()

    def __init__(self, text: str, *, closable=False, checkable=False, adv=False,
                 dot="", tooltip="", active=False, parent=None):
        super().__init__(parent)
        self._text = text
        self._closable = closable
        self._adv = adv
        self._dot = dot
        self._hover = False
        self._active = active
        self._elide = False
        self.setCheckable(checkable)
        self.setToolTip(tooltip)
        self.setAccessibleName(text)
        self.setCursor(Qt.ArrowCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setAttribute(Qt.WA_Hover, True)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    # -- state ------------------------------------------------------------
    def text(self) -> str:  # noqa: D401 - QAbstractButton API
        return self._text

    def setText(self, text: str) -> None:  # noqa: N802
        self._text = text
        self.setAccessibleName(text)
        self.updateGeometry()
        self.update()

    def set_dot(self, dot: str) -> None:
        self._dot = dot
        self.update()

    def set_adv(self, adv: bool) -> None:
        self._adv = adv
        self.updateGeometry()
        self.update()

    # -- geometry ---------------------------------------------------------
    def _fs(self) -> float:
        return area_fs(self.AREA)

    def refresh_metrics(self) -> None:
        """A font change: the size hint follows the area (live replay)."""
        self.updateGeometry()
        self.update()

    def _layout(self):
        fs = self._fs()
        key = (fs, self._text, self._dot, self._adv, self._closable)
        if getattr(self, "_layout_key", None) == key:
            return self._layout_value
        pad = 10 * fs
        x = pad
        dot_w = 7 * fs if self._dot else 0.0
        text_w = text_advance(self._text, *BTN_TEXT, fs=fs)
        adv_w = (text_advance("ADV", *ADV_TEXT, fs=fs) + 8 * fs + 6 * fs) if self._adv else 0.0
        close_w = 14 * fs if self._closable else 0.0
        self._layout_key = key
        self._layout_value = (pad, dot_w, text_w, adv_w, close_w, x)
        return self._layout_value

    def sizeHint(self) -> QSize:  # noqa: N802
        pad, dot_w, text_w, adv_w, close_w, _x = self._layout()
        fs = self._fs()
        return QSize(round(2 * pad + dot_w + text_w + adv_w + close_w), round(24 * fs))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        if self._elide:  # shrinks with an ellipsis (round 9: 390 px)
            hint = self.sizeHint()
            return QSize(min(hint.width(), round(80 * self._fs())), hint.height())
        return self.sizeHint()

    def set_elide(self, on: bool) -> None:
        """Let the chip shrink below its text, the text elided (a long
        preview at phone width or with large fonts)."""
        self._elide = bool(on)
        self.setSizePolicy(QSizePolicy.Preferred if on else QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.updateGeometry()

    def _shown_text(self, avail: float) -> str:
        fs = self._fs()
        text = self._text
        if not self._elide or text_advance(text, *BTN_TEXT, fs=fs) <= avail:
            return text
        while text and text_advance(text + "…", *BTN_TEXT, fs=fs) > avail:
            text = text[:-1]
        return text.rstrip() + "…"

    def _close_rect(self) -> QRectF:
        fs = self._fs()
        return QRectF(self.width() - 10 * fs - 10 * fs, (self.height() - 10 * fs) / 2,
                      10 * fs, 10 * fs)

    # -- events -----------------------------------------------------------
    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._closable and self._close_rect().adjusted(-3, -3, 3, 3).contains(e.position()):
            self.setDown(False)
            self.close_clicked.emit()
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def paintEvent(self, _event):
        t = tokens()
        fs = self._fs()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect())
        on = self.isChecked() or self._active
        if on:
            fill, fg = t["primary"], t["fg_on_accent"]
        else:
            fill = t["ctl_h"] if self._hover else t["ctl"]
            fg = t["primary_text"] if self._hover else t["secondary_text"]
        p.setPen(Qt.NoPen)
        p.setBrush(fill)
        p.drawPath(_rounded(rect, 6 * fs))
        if not on:
            _hair(p, rect, 6 * fs, t["hair_soft"])
        pad, dot_w, text_w, adv_w, close_w, x = self._layout()
        if self._dot:
            color = t["gold"] if self._dot == "amber" else t["red"]
            d = 5 * fs
            p.setPen(Qt.NoPen)
            p.setBrush(color)
            p.drawEllipse(QRectF(x, (rect.height() - d) / 2, d, d))
            x += dot_w
        p.setPen(fg)
        avail = rect.width() - (2 * pad + dot_w + adv_w + close_w)
        shown = self._shown_text(avail)
        text_w = min(text_w, max(0.0, avail)) if shown != self._text else text_w
        draw_bar_text(p, QRectF(x, 0, text_w + 2, rect.height()),
                      Qt.AlignVCenter | Qt.AlignLeft, shown, *BTN_TEXT, fs=fs)
        x += text_w
        if self._adv:
            tag_w = adv_w - 6 * fs
            tag = QRectF(x + 6 * fs, (rect.height() - 17 * fs) / 2, tag_w, 17 * fs)
            p.setPen(Qt.NoPen)
            p.setBrush(_alpha(t["fg_on_accent"], 0.16) if on else t["ctl_h"])
            p.drawPath(_rounded(tag, 3 * fs))
            p.setPen(t["fg_on_accent"] if on else t["secondary_text"])
            draw_bar_text(p, tag, Qt.AlignCenter, "ADV", *ADV_TEXT, fs=fs)
        if self._closable:
            draw_icon(p, "x", self._close_rect(), fg)
        if self.hasFocus():
            _hair(p, rect, 6 * fs, t["ring"])
        p.end()


class Switch(QAbstractButton):
    """An on/off switch (Sort with AI): track in the accent when on."""

    def __init__(self, tooltip="", parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)
        self.setFocusPolicy(Qt.TabFocus)
        self._pos = 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def _get_knob(self) -> float:
        return self._pos

    def _set_knob(self, v: float) -> None:
        self._pos = v
        self.update()

    knob = Property(float, _get_knob, _set_knob)

    def _animate(self, on: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def setChecked(self, on: bool) -> None:  # noqa: N802
        super().setChecked(on)
        self._anim.stop()
        self._pos = 1.0 if on else 0.0
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        fs = metrics().fs
        return QSize(round(30 * fs), round(18 * fs))

    def paintEvent(self, _event):
        t = tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        track = QColor(t["primary"]) if self._pos > 0.5 else QColor(t["recess"])
        if not self.isEnabled():
            track = _alpha(track, 0.45)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 4
        x = r.left() + 2 + self._pos * (r.width() - d - 4)
        p.setBrush(t["fg_on_accent"])
        p.drawEllipse(QRectF(x, r.top() + 2, d, d))
        if self.hasFocus():
            _hair(p, r, r.height() / 2, t["ring"])
        p.end()


class KitCheckBox(QAbstractButton):
    """A tick box with its label, in the bar's tick style."""

    def __init__(self, text: str, tooltip="", parent=None):
        super().__init__(parent)
        self._text = text
        self.setCheckable(True)
        self.setToolTip(tooltip)
        self.setAccessibleName(text)
        self.setFocusPolicy(Qt.TabFocus)

    def text(self) -> str:
        return self._text

    def sizeHint(self) -> QSize:  # noqa: N802
        fs = metrics().fs
        w = 11 * fs + 7 * fs + text_advance(self._text, *META_TEXT, fs=fs * 1.1)
        return QSize(round(w + 4), round(22 * fs))

    def paintEvent(self, _event):
        t = tokens()
        fs = metrics().fs
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        d = 11 * fs
        box = QRectF(1, (self.height() - d) / 2, d, d)
        fg = t["primary_text"] if self.isEnabled() else t["muted"]
        if self.isChecked():
            p.setPen(Qt.NoPen)
            p.setBrush(t["primary"])
            p.drawRoundedRect(box, 2.5 * fs, 2.5 * fs)
            p.setPen(QPen(t["fg_on_accent"], max(1.2, 1.4 * fs)))
            p.drawPolyline([QPointF(box.left() + 2.4 * fs, box.center().y()),
                            QPointF(box.center().x() - 0.5 * fs, box.bottom() - 2.6 * fs),
                            QPointF(box.right() - 2.2 * fs, box.top() + 2.6 * fs)])
        else:
            _hair(p, box, 2.5 * fs, t["secondary_text"])
        p.setPen(fg)
        draw_bar_text(p, QRectF(box.right() + 7 * fs, 0, self.width(), self.height()),
                      Qt.AlignVCenter | Qt.AlignLeft, self._text, *META_TEXT, fs=fs * 1.1)
        p.end()


class ProgressLine(_Painted):
    """A thin rounded progress bar. ``set_progress(done, total)``; total 0 =
    indeterminate (a sweeping segment, animated only while visible)."""

    def __init__(self, height=3, parent=None):
        super().__init__(parent)
        self._done, self._total = 0, 0
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)
        self._base = height
        self.setFixedHeight(round(height * metrics().fs))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def refresh_metrics(self) -> None:
        """Replay the thickness for a new scale (review r5 #9)."""
        self.setFixedHeight(round(self._base * metrics().fs))

    def set_progress(self, done: int, total: int) -> None:
        self._done, self._total = done, total
        self._sync_timer()
        self.update()

    def _sync_timer(self) -> None:
        running = self._total == 0 and self.isVisible()
        if running and not self._timer.isActive():
            self._timer.start()
        elif not running:
            self._timer.stop()

    def showEvent(self, e):
        super().showEvent(e)
        self._sync_timer()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._timer.stop()

    def _tick(self) -> None:
        self._phase = (self._phase + 0.025) % 1.0
        self.update()

    def paintEvent(self, _event):
        t = tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        rad = r.height() / 2
        p.setPen(Qt.NoPen)
        p.setBrush(t["recess"])
        p.drawRoundedRect(r, rad, rad)
        p.setBrush(t["primary"])
        if self._total > 0:
            w = r.width() * max(0.0, min(1.0, self._done / self._total))
            if w > 0:
                p.drawRoundedRect(QRectF(r.left(), r.top(), max(w, r.height()), r.height()), rad, rad)
        else:
            seg = r.width() * 0.3
            x = r.left() - seg + self._phase * (r.width() + seg)
            p.setClipRect(r)
            p.drawRoundedRect(QRectF(x, r.top(), seg, r.height()), rad, rad)
        p.end()


class JobBar(ProgressLine):
    """The status bar's job progress (Lorris, 2026-10-25: the thin 6 px line
    in the corner went unnoticed for minutes). Thick, as wide as the status
    bar allows, the count and percentage written inside, and a light sheen
    sweeping over the filled part so a slow job still visibly moves."""

    def __init__(self, height=18, parent=None):
        super().__init__(height, parent)
        self._sheen = 0.0
        self._sheen_timer = QTimer(self)
        self._sheen_timer.setInterval(40)
        self._sheen_timer.timeout.connect(self._sheen_tick)

    def _sync_timer(self) -> None:
        super()._sync_timer()
        if not hasattr(self, "_sheen_timer"):
            return
        busy = self.isVisible() and self._total > 0 and self._done < self._total
        if busy and not self._sheen_timer.isActive():
            self._sheen_timer.start()
        elif not busy:
            self._sheen_timer.stop()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._sheen_timer.stop()

    def _sheen_tick(self) -> None:
        self._sheen = (self._sheen + 0.012) % 1.0
        self.update()

    def label(self) -> str:
        if self._total <= 0:
            return "Working..."
        pct = 100.0 * max(0, min(self._done, self._total)) / self._total
        return f"{self._done:,} / {self._total:,}  ·  {pct:.0f}%"

    def paintEvent(self, _event):
        from PySide6.QtGui import QFont, QLinearGradient
        t = tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        rad = r.height() / 2
        track, rim = QColor(t["primary"]), QColor(t["primary"])
        track.setAlphaF(0.14)
        rim.setAlphaF(0.45)
        p.setPen(QPen(rim, 1))
        p.setBrush(track)
        p.drawRoundedRect(r, rad, rad)
        p.setPen(Qt.NoPen)
        fill = QRectF(r)
        if self._total > 0:
            frac = max(0.0, min(1.0, self._done / self._total))
            fill.setWidth(max(r.width() * frac, r.height()) if frac > 0 else 0)
        else:  # indeterminate: the moving segment of the line
            seg = r.width() * 0.3
            fill = QRectF(r.left() - seg + self._phase * (r.width() + seg), r.top(),
                          seg, r.height())
        if fill.width() > 0:
            p.save()
            path = QPainterPath()
            path.addRoundedRect(r, rad, rad)
            p.setClipPath(path)
            p.setBrush(t["primary"])
            p.drawRoundedRect(fill, rad, rad)
            if self._total > 0:  # the sheen, inside the filled part only
                p.setClipRect(fill, Qt.IntersectClip)
                band = max(r.height() * 3, 40.0)
                x = fill.left() - band + self._sheen * (fill.width() + 2 * band)
                g = QLinearGradient(x, 0, x + band, 0)
                hi = QColor(255, 255, 255, 0)
                g.setColorAt(0.0, hi)
                hi.setAlpha(70)
                g.setColorAt(0.5, hi)
                hi.setAlpha(0)
                g.setColorAt(1.0, hi)
                p.setBrush(g)
                p.drawRect(QRectF(x, r.top(), band, r.height()))
            p.restore()
        text = self.label()
        f = QFont(self.font())
        f.setPixelSize(max(9, round(r.height() * 0.62)))
        f.setBold(True)
        p.setFont(f)
        # Two passes: on-accent text over the fill, normal text over the rest.
        for clip, color in ((fill, t["fg_on_accent"]), (None, t["primary_text"])):
            p.save()
            if clip is not None:
                if clip.width() <= 0:
                    p.restore()
                    continue
                p.setClipRect(clip)
            else:
                outside = QPainterPath()
                outside.addRect(r)
                inside = QPainterPath()
                inside.addRect(fill)
                p.setClipPath(outside.subtracted(inside) if fill.width() > 0 else outside)
            p.setPen(color)
            p.drawText(r, Qt.AlignCenter, text)
            p.restore()
        p.end()


class CoverageRing(_Painted):
    """One extractor's coverage: a ring filled to ``fraction``. ``state``:
    ``ok`` (green), ``stale`` (gold), ``run`` (accent), ``empty`` (grey)."""

    def __init__(self, size=14, parent=None):
        super().__init__(parent)
        self._fraction = 0.0
        self._state = "empty"
        self._base = size
        CoverageRing.refresh_metrics(self)  # never a subclass override here (r6 #4)

    def refresh_metrics(self) -> None:
        """Replay the diameter for a new scale (review r5 #9)."""
        d = round(self._base * metrics().fs)
        self.setFixedSize(d, d)

    def set_value(self, fraction: float, state: str) -> None:
        self._fraction = max(0.0, min(1.0, fraction))
        self._state = state
        self.update()

    def paintEvent(self, _event):
        t = tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        width = max(2.0, r.width() * 0.22)
        inner = r.adjusted(width / 2, width / 2, -width / 2, -width / 2)
        p.setPen(QPen(t["recess"], width))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(inner)
        color = {"ok": t["green"], "stale": t["gold"], "run": t["primary"]}.get(
            self._state, t["muted"]
        )
        if self._fraction > 0 and self._state != "empty":
            pen = QPen(color, width)
            pen.setCapStyle(Qt.FlatCap)
            p.setPen(pen)
            p.drawArc(inner, 90 * 16, -round(self._fraction * 360 * 16))
        p.end()


# ----------------------------------------------------------------- search well


class SearchWell(_Painted):
    """The rounded well around ``search_entry`` (a real QLineEdit, Pro A.2):
    search icon, token pills, the entry, a clear x, the scope pill, and the
    searching hairline along its bottom edge.

    The token pills sit in a bounded strip that scrolls sideways (at most
    ``TOKENS_SHARE`` of the well), so the entry keeps ``ENTRY_MIN_W`` and the
    well never grows past its minimum because of tokens (review r4); the
    scope pill shortens to its count when the well is narrow."""

    token_removed = Signal(str)
    cleared = Signal()

    TOKENS_SHARE = 0.45
    ENTRY_MIN_W = 56  # x fs
    NARROW_W = 280  # x fs: below it the scope pill shows only its count

    def __init__(self, entry: QLineEdit, parent=None):
        super().__init__(parent)
        self.entry = entry
        self._busy = False
        self._m = metrics()
        self._scope_full = ""
        self._scope_short = ""
        self._tokens_row = QWidget()
        self._tokens_lay = QHBoxLayout(self._tokens_row)
        self._tokens_lay.setContentsMargins(0, 0, 0, 0)
        self._tokens_lay.setSpacing(4)
        self.tokens_strip = QScrollArea(self)
        self.tokens_strip.setFrameShape(QFrame.NoFrame)
        self.tokens_strip.setWidgetResizable(True)
        self.tokens_strip.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.tokens_strip.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tokens_strip.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.tokens_strip.setMinimumWidth(0)
        self.tokens_strip.setStyleSheet("QScrollArea { background: transparent; }")
        self.tokens_strip.setWidget(self._tokens_row)
        self.tokens_strip.hide()
        self.scope_pill = QLabel(self)
        self.scope_pill.setObjectName("fc_scope_pill")
        self.clear_button = _IconButton("x", "Clear the search", self)
        self.clear_button.clicked.connect(self._on_clear)
        self.hairline = ProgressLine(2, self)
        self.hairline.hide()
        lay = QHBoxLayout(self)
        fs = self._m.fs
        lay.setContentsMargins(round(28 * fs), 0, round(8 * fs), 0)
        lay.setSpacing(round(6 * fs))
        lay.addWidget(self.tokens_strip)
        lay.addWidget(entry, 1)
        lay.addWidget(self.clear_button)
        lay.addWidget(self.scope_pill)
        entry.setFrame(False)
        entry.setMinimumWidth(round(self.ENTRY_MIN_W * fs))
        entry.textChanged.connect(self._sync_clear)
        self.setFixedHeight(self._m.ctl_h + round(4 * fs))
        self._sync_clear()
        self.refresh_theme()
        self._update_floor()

    def _sync_clear(self, *_):
        shown = bool(self.entry.text())
        if shown != (not self.clear_button.isHidden()):
            self.clear_button.setVisible(shown)
            if hasattr(self, "_scope_short"):
                self._update_floor()
                self._bound_tokens()

    def _on_clear(self):
        self.entry.clear()
        self.cleared.emit()

    def set_tokens(self, tokens_: list[tuple[str, str, bool, str]]) -> None:
        """``(token, label, ok, tooltip)`` per search-box token."""
        while self._tokens_lay.count():
            item = self._tokens_lay.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()  # no ghost until deleteLater runs
                item.widget().deleteLater()
        for token, label, ok, tip in tokens_:
            chip = Chip(label, closable=True, dot="" if ok else "red", tooltip=tip)
            chip.close_clicked.connect(lambda t=token: self.token_removed.emit(t))
            self._tokens_lay.addWidget(chip)
        self.tokens_strip.setVisible(bool(tokens_))
        self._bound_tokens()

    def token_chips(self) -> list:
        return [
            self._tokens_lay.itemAt(i).widget()
            for i in range(self._tokens_lay.count())
            if self._tokens_lay.itemAt(i).widget() is not None
        ]

    def floor_width(self) -> int:
        """The well's real minimum (review r5 #6): margins, the entry's
        floor, the clear x when shown, the scope pill at its short text and
        the gaps between them. The token strip has no floor: it shrinks to
        zero and scrolls."""
        fs = self._m.fs
        gap = round(6 * fs)
        parts = [round(self.ENTRY_MIN_W * fs)]
        if not self.clear_button.isHidden():
            parts.append(self.clear_button.sizeHint().width())
        short = self._scope_short or self.scope_pill.text()
        if short:
            parts.append(self.scope_pill.fontMetrics().horizontalAdvance(short) + 2)
        return round(28 * fs) + round(8 * fs) + sum(parts) + gap * (len(parts) - 1)

    def _room_for_tokens(self) -> int:
        """What is left for the strip once every other part has its own
        width (the pill at the text it shows now): zero when nothing is."""
        fs = self._m.fs
        gap = round(6 * fs)
        used = round(28 * fs) + round(8 * fs) + round(self.ENTRY_MIN_W * fs) + gap
        if not self.clear_button.isHidden():
            used += self.clear_button.sizeHint().width() + gap
        if self.scope_pill.text():
            used += self.scope_pill.sizeHint().width() + gap
        return max(0, self.width() - used)

    def _update_floor(self) -> None:
        self.setMinimumWidth(self.floor_width())
        self.updateGeometry()

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        """The real floor: the token strip is re-bounded on every resize,
        so its current width is never part of the minimum."""
        return QSize(self.floor_width(), self.height() or self._m.ctl_h)

    def _bound_tokens(self) -> None:
        """The strip: its pills' width, at most TOKENS_SHARE of the well and
        never more than the room the other parts leave (review r5 #6)."""
        fs = self._m.fs
        want = self._tokens_row.sizeHint().width()
        cap = max(0, min(int(self.width() * self.TOKENS_SHARE), self._room_for_tokens()))
        self.tokens_strip.setFixedWidth(min(want, cap))
        bar = self.tokens_strip.horizontalScrollBar().sizeHint().height()
        self.tokens_strip.setFixedHeight(round(24 * area_fs("info_text")) + (bar if want > cap else 0))
        self.tokens_strip.setMaximumHeight(max(self.height() - 2, round(20 * fs)))

    def set_scope(self, text: str, short: str = "") -> None:
        """``text`` ("ALL · 7,659"); ``short`` ("7,659") when the well is narrow."""
        self._scope_full = text
        self._scope_short = short or text
        self._show_scope()
        self._update_floor()
        self._bound_tokens()

    def _show_scope(self) -> None:
        narrow = self.width() < round(self.NARROW_W * self._m.fs)
        self.scope_pill.setText(self._scope_short if narrow else self._scope_full)

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.hairline.set_progress(0, 0)
        self.hairline.setVisible(busy)

    def set_metrics(self, m: BarMetrics) -> None:
        self._m = m
        self.setFixedHeight(m.ctl_h + round(4 * m.fs))
        self.entry.setMinimumWidth(round(self.ENTRY_MIN_W * m.fs))
        lay = self.layout()
        lay.setContentsMargins(round(28 * m.fs), 0, round(8 * m.fs), 0)
        lay.setSpacing(round(6 * m.fs))
        for chip in self.token_chips():
            chip.refresh_metrics()
        self.hairline.refresh_metrics()
        self.refresh_theme()
        self._update_floor()
        self._bound_tokens()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        fs = self._m.fs
        h = self.hairline.height()
        self.hairline.setGeometry(round(8 * fs), self.height() - h - 1, self.width() - round(16 * fs), h)
        self._show_scope()
        self._bound_tokens()

    def refresh_theme(self) -> None:
        t = tokens()
        px = scaled_area_px("info_text")
        self.entry.setStyleSheet(
            f"QLineEdit {{ background: transparent; border: none; color: {t['primary_text'].name()};"
            f" font-size: {px}px; selection-background-color: {t['primary'].name()}; }}"
        )
        self.scope_pill.setStyleSheet(
            f"color: {t['muted'].name()}; font-size: {scaled_area_px('status')}px;"
            " font-weight: 600; background: transparent;"
        )
        self.update()

    def paintEvent(self, _event):
        t = tokens()
        fs = self._m.fs
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0, 1, 0, -1)
        rad = 7 * fs
        p.setPen(Qt.NoPen)
        p.setBrush(t["well_h"] if self.entry.hasFocus() else t["well"])
        p.drawPath(_rounded(r, rad))
        _hair(p, r, rad, t["ring"] if self.entry.hasFocus() else t["well_line"])
        d = 13 * fs
        draw_icon(p, "fc_search", QRectF(10 * fs, (self.height() - d) / 2, d, d), t["muted"])
        p.end()


class _IconButton(QAbstractButton):
    """A small borderless icon button (clear x, sheet close, back)."""

    def __init__(self, icon_id: str, tooltip: str, parent=None, size=16):
        super().__init__(parent)
        self._icon = icon_id
        self._size = size
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)
        self.setCursor(Qt.ArrowCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setFocusPolicy(Qt.TabFocus)

    def sizeHint(self) -> QSize:  # noqa: N802
        d = round(self._size * metrics().fs)
        return QSize(d, d)

    def paintEvent(self, _event):
        t = tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        if self.underMouse():
            p.setPen(Qt.NoPen)
            p.setBrush(t["ctl_h"])
            p.drawEllipse(r)
        d = r.width() * 0.55
        draw_icon(p, self._icon, QRectF((r.width() - d) / 2, (r.height() - d) / 2, d, d),
                  t["primary_text"] if self.underMouse() else t["secondary_text"])
        p.end()


IconButton = _IconButton


# ----------------------------------------------------------------- sections


class CollapsibleSection(QWidget):
    """A titled section whose body folds (the inspector's sections, the
    Library's groups). ``toggled(bool)`` reports the open state; ``dot``
    colours the header's state dot (``""``, ``"amber"``, ``"red"``)."""

    toggled = Signal(bool)

    def __init__(self, title: str, subtitle: str = "", *, open_=False, parent=None):
        super().__init__(parent)
        self._title = title
        self._subtitle = subtitle
        self._open = open_
        self._dot = ""
        self.header = _SectionHeaderButton(self)
        self.header.clicked.connect(self.toggle)
        self.body = QWidget(self)
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(round(10 * metrics().fs), 0, round(10 * metrics().fs),
                                            round(8 * metrics().fs))
        self.body_layout.setSpacing(round(3 * metrics().fs))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.header)
        lay.addWidget(self.body)
        self.body.setVisible(open_)

    @property
    def title(self) -> str:
        return self._title

    def set_subtitle(self, text: str) -> None:
        self._subtitle = text
        self.header.update()

    def set_dot(self, dot: str) -> None:
        self._dot = dot
        self.header.update()

    def is_open(self) -> bool:
        return self._open

    def set_open(self, on: bool) -> None:
        if on == self._open:
            return
        self._open = on
        self.body.setVisible(on)
        self.header.update()
        self.toggled.emit(on)

    def toggle(self) -> None:
        self.set_open(not self._open)

    def refresh_metrics(self) -> None:
        """A font change: the header follows ``panel_titles``, the body
        margins ``info_text``."""
        fs = area_fs("info_text")
        self.body_layout.setContentsMargins(round(10 * fs), 0, round(10 * fs), round(8 * fs))
        self.body_layout.setSpacing(round(3 * fs))
        self.header.updateGeometry()
        self.header.update()


class _SectionHeaderButton(QAbstractButton):
    def __init__(self, section: CollapsibleSection):
        super().__init__(section)
        self._section = section
        self.setFocusPolicy(Qt.TabFocus)
        self.setAttribute(Qt.WA_Hover, True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(100, round(28 * area_fs("panel_titles")))

    def paintEvent(self, _event):
        t = tokens()
        fs = area_fs("panel_titles")  # section titles (INV-10)
        s = self._section
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        if self.underMouse():
            p.fillRect(r, t["ctl_h"])
        p.setPen(QPen(t["hair_soft"], 1))
        p.drawLine(QPointF(0, 0.5), QPointF(r.width(), 0.5))
        d = 10 * fs
        p.save()
        p.translate(10 * fs + d / 2, r.height() / 2)
        if s.is_open():
            p.rotate(90)
        draw_icon(p, "fc_chevr", QRectF(-d / 2, -d / 2, d, d), t["muted"])
        p.restore()
        x = 10 * fs + d + 6 * fs
        p.setPen(t["primary_text"])
        title = s.title if s.property("sentence_case") else s.title.upper()
        title_w = text_advance(title, 11.5, 620, 0, fs=fs)
        draw_bar_text(p, QRectF(x, 0, title_w + 4, r.height()), Qt.AlignVCenter | Qt.AlignLeft,
                      title, 11.5, 620, 0, fs)
        x += title_w + 8 * fs
        if s._dot:
            dd = 5 * fs
            p.setPen(Qt.NoPen)
            p.setBrush(t["gold"] if s._dot == "amber" else t["red"])
            p.drawEllipse(QRectF(x, (r.height() - dd) / 2, dd, dd))
            x += dd + 6 * fs
        if s._subtitle:
            p.setPen(t["muted"])
            draw_bar_text(p, QRectF(x, 0, r.width() - x - 8 * fs, r.height()),
                          Qt.AlignVCenter | Qt.AlignLeft, s._subtitle, *META_TEXT, fs=fs)
        p.end()


# ----------------------------------------------------------------- sheet


def pin_left(scroll: QScrollArea) -> None:
    """Keep a vertical-only scroll area at its left edge. Hiding the
    sideways scrollbar does not stop Qt from scrolling sideways to show a
    focused child of a content wider than the view, and then the left of
    the content is out of reach (Lorris, 2026-10-29). Too wide a content is
    cut on the right instead."""
    bar = scroll.horizontalScrollBar()

    def back(*_a) -> None:
        if bar.value() != bar.minimum():
            bar.setValue(bar.minimum())

    bar.valueChanged.connect(back)
    bar.rangeChanged.connect(back)


class Sheet(QWidget):
    """A panel that slides over ``host`` from the right with a scrim (the
    Library, Sort with AI, Custom system, and the inspector below 1025 px).
    ``full_page`` (phone width) covers the whole host with a back button.
    Esc or the close button closes it; ``closed`` is emitted."""

    closed = Signal()

    def __init__(self, host: QWidget, title: str, *, width=380, chrome=True, text_area=None):
        """``chrome=False``: no title, close or back of its own (a content
        that brings its own, as the inspector does). ``text_area``: the font
        area of the text the sheet holds; the width then follows the larger
        of that scale and the bar's, so a large text font widens the sheet."""
        super().__init__(host)
        self._host = host
        self._width = width
        self._text_area = text_area
        self._full = False
        self._chrome = chrome
        self.scrim = _Scrim(host)
        self.scrim.clicked.connect(self.close_sheet)
        self.panel = QWidget(self)
        self.title_label = SectionHeader(title)
        self.close_button = _IconButton("x", "Close", size=18)
        self.close_button.clicked.connect(self.close_sheet)
        self.back_button = _IconButton("fc_back", "Back", size=18)
        self.back_button.clicked.connect(self.close_sheet)
        self.back_button.hide()
        head = QHBoxLayout()
        fs = metrics().fs
        head.setContentsMargins(round(14 * fs), round(10 * fs), round(10 * fs), round(6 * fs))
        head.addWidget(self.back_button)
        head.addWidget(self.title_label, 1)
        head.addWidget(self.close_button)
        self._head = head
        # The content scrolls vertically, never sideways (review r5 #4): a
        # form taller than the window stays reachable.
        self.scroll = QScrollArea(self.panel)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        pin_left(self.scroll)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; }")
        self.content = QWidget()
        self.content.setObjectName("fc_sheet_content")
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(round(14 * fs), 0, round(14 * fs), round(14 * fs))
        self.content_layout.setSpacing(round(10 * fs))
        self.scroll.setWidget(self.content)
        self.scroll.viewport().setAutoFillBackground(False)
        self.content.setAutoFillBackground(False)
        lay = QVBoxLayout(self.panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addLayout(head)
        lay.addWidget(self.scroll, 1)
        if not chrome:
            for w in (self.title_label, self.close_button, self.back_button):
                w.hide()
            head.setContentsMargins(0, 0, 0, 0)
            self.content_layout.setContentsMargins(0, 0, 0, 0)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.panel)
        self.setFocusPolicy(Qt.StrongFocus)
        self.hide()
        self.scrim.hide()
        host.installEventFilter(self)

    def set_title(self, text: str) -> None:
        self.title_label.setText(text.upper())

    def refresh_metrics(self) -> None:
        """Replay the margins and width for a new scale (review r5 #9)."""
        fs = metrics().fs
        if not self._chrome:
            if self.is_open():
                self._place()
            return
        self._head.setContentsMargins(
            round(14 * fs), round(10 * fs), round(10 * fs), round(6 * fs)
        )
        self.content_layout.setContentsMargins(
            round(14 * fs), 0, round(14 * fs), round(14 * fs)
        )
        self.content_layout.setSpacing(round(10 * fs))
        self.title_label.refresh_theme()
        if self.is_open():
            self._place()

    def set_full_page(self, on: bool) -> None:
        self._full = on
        if self._chrome:
            self.back_button.setVisible(on)
            self.close_button.setVisible(not on)
        if self.is_open():
            self._place()

    def is_open(self) -> bool:
        return not self.isHidden()

    def open_sheet(self) -> None:
        self._place()
        self.scrim.setVisible(not self._full)
        self.scrim.raise_()
        self.show()
        self.raise_()
        self.setFocus()

    def close_sheet(self) -> None:
        if not self.is_open():
            return
        self.hide()
        self.scrim.hide()
        self.closed.emit()

    def _place(self) -> None:
        r = self._host.rect()
        self.scrim.setGeometry(r)
        fs = metrics().fs
        if self._text_area:
            fs = max(fs, area_fs(self._text_area))
        w = r.width() if self._full else min(r.width(), round(self._width * fs))
        self.setGeometry(r.width() - w, 0, w, r.height())

    def eventFilter(self, obj, event):
        if obj is self._host and event.type() == event.Type.Resize and self.is_open():
            self._place()
        return False

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close_sheet()
            e.accept()
            return
        super().keyPressEvent(e)

    def paintEvent(self, _event):
        t = tokens()
        p = QPainter(self)
        p.fillRect(self.rect(), t["secondary_light"])
        p.setPen(QPen(t["hair"], 1))
        p.drawLine(QPointF(0.5, 0), QPointF(0.5, self.height()))
        p.end()


class _Scrim(QAbstractButton):
    def paintEvent(self, _event):
        p = QPainter(self)
        p.fillRect(self.rect(), _alpha(QColor(tokens()["drop"]), 1.0))
        p.end()


# ----------------------------------------------------------------- combos


def restyle_combo(combo: QComboBox) -> None:
    """A ReadableCombo in the kit's look: well fill, hairline, theme text,
    for the closed editor and its popup (Rule 20)."""
    t = tokens()
    px = scaled_area_px("buttons")
    combo.setStyleSheet(
        f"QComboBox {{ background: {t['ctl'].name(QColor.HexArgb)};"
        f" color: {t['primary_text'].name()}; border: 1px solid {t['hair_soft'].name(QColor.HexArgb)};"
        f" border-radius: 6px; padding: 2px 8px; font-size: {px}px; }}"
        f"QComboBox:hover {{ background: {t['ctl_h'].name(QColor.HexArgb)}; }}"
        f"QComboBox QAbstractItemView {{ background: {t['menu_fill'].name(QColor.HexArgb)};"
        f" color: {t['primary_text'].name()}; selection-background-color: {t['primary'].name()};"
        f" selection-color: {t['fg_on_accent'].name()}; font-size: {px}px; }}"
    )
