# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Full / Rail / Shelf presentations of the right dasha panel (SPEC-LAYOUT-001 A.1, D4).

``DashaPresentationMixin`` is mixed into ``DashaPanelWidget``. The panel keeps its
own children in every presentation (same list, same items, same delegate, same
combos), so every renderer, selection, drill, filter and context menu keeps
working; a presentation only re-arranges and hides chrome:

* full  : today's column (header, nav, list, the three lord filters);
* rail  : 64 px; header reduced to the fold and Bottom buttons, list as tiles;
* shelf : the bottom shelf; meta box (title, levels, nav, current, Return to
          side) | list as horizontal cards | the three filters.

The mode SHAPE (levels, nav row) written by ``set_shape`` / ``set_strip`` /
``set_nav`` is stored apart from the presentation, and both are applied by one
``_reconcile_visibility`` (D4), so a mode change while on the rail never reopens
hidden chrome. Width and parent are the ChartLayoutManager's business.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QBoxLayout, QLabel, QListView, QPushButton, QWidget

from apps.widgets.panel_header import HeaderGlyphButton

from core.i18n import t
from ui.qt_theme import get_theme_colors, scaled_area_px, scaled_px

PRESENTATIONS = ("full", "rail", "shelf")
RAIL_WIDTH = 64            # px at scale 1 (plan A.1)
META_WIDTH = 200
FILTERS_WIDTH = 190


def _current_style():
    theme = get_theme_colors()
    return (f"color: {theme['secondary_text']}; font-size: {scaled_area_px('status')}px; "
            f"background: transparent;")


def _return_style():
    theme = get_theme_colors()
    return f"""
        QPushButton {{ background: {theme["secondary"]}; color: {theme["secondary_text"]};
            border: 1px solid {theme["secondary_light"]}; border-radius: {scaled_px(5)}px;
            font-size: {scaled_area_px('status')}px; padding: {scaled_px(4)}px; }}
        QPushButton:hover {{ border-color: {theme["primary"]}; }}
    """


def dock_glyph(kind: str):
    """Glyph painter for a ``HeaderGlyphButton`` (16-unit box, SF-like 1.45 px
    strokes, round caps): a panel outline with a chevron (``fold`` = fold to
    the rail, ``unfold`` = open the full column) or with a bar at its bottom
    and a down chevron (``bottom`` = dock to the shelf)."""
    def paint(p: QPainter, box: QRectF, color: QColor, fs: float) -> None:
        from apps.widgets.panel_header import stroke_pen
        k = box.width() / 16.0
        ox, oy = box.left(), box.top()

        def pt(x, y):
            return QPointF(ox + x * k, oy + y * k)

        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(stroke_pen(color, max(1.1, 1.3 * fs)))
        p.drawRoundedRect(QRectF(pt(1.5, 2.5), pt(14.5, 13.5)), 2.6 * k, 2.6 * k)
        p.setPen(stroke_pen(color, max(1.2, 1.45 * fs)))
        if kind == "bottom":
            p.drawLine(pt(4.5, 10.75), pt(11.5, 10.75))
            p.drawPolyline([pt(5.75, 5.5), pt(8.0, 7.75), pt(10.25, 5.5)])
        else:
            d = 1.9 if kind == "fold" else -1.9
            p.drawPolyline([pt(8.0 - d, 5.0), pt(8.0 + d, 8.0), pt(8.0 - d, 11.0)])
    return paint


class DashaPresentationMixin:
    """Presentation state and chrome of the right dasha panel (see module doc)."""

    # ---------------------------------------------------------- construction
    def _init_presentation(self, title_row, meta_layout):
        """Called by ``DashaPanelWidget.__init__`` once its children exist; the
        three signals (fold/dock/return_requested) are declared on the panel."""
        self.presentation = "full"
        self._shape_nav = True
        self._shape_levels = len(self.level_buttons)
        self._list_defaults = (self.list_widget.flow(), self.list_widget.isWrapping(),
                               self.list_widget.horizontalScrollBarPolicy(),
                               self.list_widget.verticalScrollBarPolicy(),
                               self.list_widget.spacing())
        self._title_row = title_row
        self.fold_btn = self.dock_btn = None
        self._return_allowed = True              # SPEC-DUAL-001 INV-13
        self._title_chip_text = None             # SPEC-DUAL-001 §4.4 "of <A>"
        self.title_chip = None
        if self.side != "right":
            self.current_lbl = self.return_btn = None
            return
        self.title_chip = ShelfTitleChip(self)
        title_row.insertWidget(title_row.indexOf(self.title_btn) + 1, self.title_chip)
        self.title_chip.hide()
        self.fold_btn = HeaderGlyphButton(dock_glyph("fold"))
        self.fold_btn.setToolTip(t("dasha.layout.fold_tip", "Fold to a narrow rail / open the full column (Ctrl+])"))
        self.dock_btn = HeaderGlyphButton(dock_glyph("bottom"))   # the words are in the tooltip
        self.dock_btn.setToolTip(t("dasha.layout.bottom_tip",
                                   "Dock to the bottom, under the whole row (Ctrl+Shift+D)"))
        from apps.panels.dasha_panel import cap_header_plates
        cap_header_plates(self.fold_btn, self.dock_btn)
        for btn, sig in ((self.fold_btn, self.fold_requested), (self.dock_btn, self.dock_requested)):
            btn.setAccessibleName(btn.toolTip())
            btn.clicked.connect(lambda _=False, s=sig: s.emit())
        # Both in the title row, as in the winning mockup: the level row keeps
        # its full width for the 1-5 buttons.
        centre = Qt.AlignmentFlag.AlignHCenter          # centred when the rail stacks them
        title_row.insertWidget(0, self.fold_btn, 0, centre)
        title_row.insertWidget(1, self.dock_btn, 0, centre)
        self.current_lbl = QLabel()
        self.current_lbl.setWordWrap(True)
        self._register_themed(self.current_lbl, _current_style)
        self.return_btn = QPushButton(t("dasha.layout.return", "Return to side"))
        self.return_btn.setToolTip(t("dasha.layout.return_tip",
                                     "Put the dasha back in its side column (Ctrl+Shift+D)"))
        self.return_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._register_themed(self.return_btn, _return_style)
        self.return_btn.clicked.connect(lambda: self.return_requested.emit())
        meta_layout.addWidget(self.current_lbl)
        meta_layout.addWidget(self.return_btn)
        self.current_lbl.hide()
        self.return_btn.hide()
        self.list_widget.viewport().installEventFilter(self)   # shelf cards follow its height
        model = self.list_widget.model()
        for sig in (model.rowsInserted, model.rowsRemoved, model.modelReset, model.dataChanged):
            sig.connect(self.delegate.invalidate_sections)
        self.delegate.on_current_changed = self._on_current_changed
        # One owned, coalescing timer for card relayouts (dies with the panel).
        self._card_timer = QTimer(self)
        self._card_timer.setSingleShot(True)
        self._card_timer.setInterval(60)
        self._card_timer.timeout.connect(self._relayout_cards)

    def _sync_fold_glyph(self):
        """The fold button points at what it does: fold (full) / unfold (rail)."""
        if self.fold_btn is not None:
            self.fold_btn.set_glyph(dock_glyph("unfold" if self.presentation == "rail" else "fold"))

    def eventFilter(self, obj, event):
        if (event.type() == QEvent.Type.Resize and self.presentation == "shelf"
                and obj is self.list_widget.viewport()):
            self._card_timer.start()      # coalesced: once after the height settles
        return super().eventFilter(obj, event)

    def _relayout_cards(self):
        h = max(scaled_px(120), self.list_widget.viewport().height())
        if self.presentation == "shelf" and h != self.delegate.card_height:
            self.delegate.card_height = h
            self.list_widget.doItemsLayout()

    def _on_current_changed(self):
        if self.presentation == "shelf":
            self.update_current_summary()

    # ------------------------------------------------------------ mode shape
    def _record_shape(self, *, nav=None, levels=None):
        if nav is not None:
            self._shape_nav = bool(nav)
        if levels is not None:
            self._shape_levels = int(levels)
        self._reconcile_visibility()

    def _reconcile_visibility(self):
        """Apply mode shape AND presentation together (D4)."""
        p = getattr(self, "presentation", "full")
        rail = p == "rail"
        self.nav_frame.setVisible(self._shape_nav and not rail)
        for i, b in enumerate(self.level_buttons):
            b.setVisible(i < self._shape_levels and not rail)
        self.level_segments.setVisible(self._shape_levels > 0 and not rail)
        self.title_btn.setVisible(not rail)
        self.swap_btn.setVisible(not rail)
        self.filters.setVisible(not rail)
        if self.fold_btn is not None:
            self.fold_btn.setVisible(p != "shelf")
            self.dock_btn.setVisible(p != "shelf")
            self.current_lbl.setVisible(p == "shelf")
            self.return_btn.setVisible(p == "shelf" and self._return_allowed)
        if self.title_chip is not None:
            self.title_chip.set_text(self._title_chip_text or "")
            self.title_chip.setVisible(bool(self._title_chip_text) and not rail)
        self.fit_header()                 # the strip and level row follow what shows

    def set_title_chip(self, text) -> None:
        """SPEC-DUAL-001 §4.4: the "of <active chart>" chip right of the title
        (two-chart mode only); ``None`` removes it."""
        self._title_chip_text = text or None
        self._reconcile_visibility()

    def set_return_allowed(self, allowed: bool) -> None:
        """SPEC-DUAL-001 INV-13: "Return to side" is hidden while paired."""
        self._return_allowed = bool(allowed)
        self._reconcile_visibility()

    def fit_header(self) -> None:
        """Header height: the strip is ``header_height()`` (the info panels'
        strip) or, on the rail, the stacked fold + Bottom buttons; the header
        is the strip plus the level control, both sized from the live
        'panel_titles' font, so a large font never clips the 1-5 digits."""
        from apps.widgets.panel_header import header_height
        rail = getattr(self, "presentation", "full") == "rail"
        strip = self.title_strip
        strip.layout().activate()
        strip.setFixedHeight(max(header_height(), strip.layout().minimumSize().height()) if rail
                             else header_height())
        self.header.layout().activate()
        self.header.setFixedHeight(self.header.layout().minimumSize().height())

    # ---------------------------------------------------------- presentation
    def set_presentation(self, presentation: str) -> None:
        """Re-arrange this panel's own children; never touches list content."""
        if presentation not in PRESENTATIONS:
            raise ValueError(f"presentation must be one of {PRESENTATIONS}, got {presentation!r}")
        if presentation == self.presentation:
            return
        self.presentation = presentation
        root = self.layout()
        lst = self.list_widget
        shelf = presentation == "shelf"
        root.setDirection(QBoxLayout.Direction.LeftToRight if shelf
                          else QBoxLayout.Direction.TopToBottom)
        self._title_row.setDirection(QBoxLayout.Direction.TopToBottom if presentation == "rail"
                                     else QBoxLayout.Direction.LeftToRight)
        for w, width in ((self.meta, META_WIDTH), (self.filters, FILTERS_WIDTH)):
            if shelf:
                w.setFixedWidth(scaled_px(width))
            else:
                self._release(w)
        flow, wrap, hpol, vpol, spacing = self._list_defaults
        if shelf:
            lst.setFlow(QListView.Flow.LeftToRight)
            lst.setWrapping(False)
            lst.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            lst.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            lst.setHorizontalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        else:
            lst.setFlow(flow)
            lst.setWrapping(wrap)
            lst.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff if presentation == "rail" else hpol)
            lst.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff if presentation == "rail" else vpol)
        lst.setSpacing(spacing)
        self.delegate.set_presentation({"full": "row", "rail": "rail", "shelf": "card"}[presentation],
                                       two_line=self.side == "right")
        self._reconcile_visibility()
        self._sync_fold_glyph()
        self.update_current_summary()
        self.relayout_items()

    @staticmethod
    def _release(w: QWidget):
        w.setMinimumWidth(0)
        w.setMaximumWidth(16777215)

    def relayout_items(self):
        """Item geometry follows the delegate (sizes changed) and the current
        period stays in view."""
        lst = self.list_widget
        if self.presentation == "shelf":
            self.delegate.card_height = max(scaled_px(120), lst.viewport().height())
        lst.doItemsLayout()
        rows = sorted(self.delegate.highlight_rows)
        if rows and lst.item(rows[0]) is not None:
            lst.scrollToItem(lst.item(rows[0]), QListView.ScrollHint.PositionAtCenter
                             if self.presentation != "full" else QListView.ScrollHint.EnsureVisible)
        lst.viewport().update()

    def update_current_summary(self):
        """Shelf meta line: 'Current: ♀ Venus' / '12-32y · 2008-2028'."""
        if self.current_lbl is None:
            return
        f = self.current_fields()
        if not f:
            self.current_lbl.setText("")
            return
        from apps.delegates.dasha_presentation_paint import years
        a, b = years(f["dates"])
        tail = " · ".join(x for x in (f["span"], f"{a}–{b}" if a and b else "") if x)
        head = t("dasha.shelf.current", "Current: {glyph} {lord}", glyph=f["glyph"], lord=f["lord"])
        self.current_lbl.setText(f"{head}\n{tail}".rstrip())

    def current_fields(self):
        rows = sorted(self.delegate.highlight_rows)
        if not rows:
            return None
        index = self.list_widget.model().index(rows[0], 0)
        return self.delegate.fields(index) if index.isValid() else None

    # ---------------------------------------------------------------- capture
    def capture_observation(self, window):
        """AI capture of this panel (D7a): the existing header/rows shape; Rail
        and Shelf add a 'Shown' cell with what the item paints. Pro and up:
        only the capture calls it (SPEC-EDN-002 P4)."""
        from core.edition_features import ai_features
        regions = ai_features()
        lst = self.list_widget
        if self.presentation == "full":
            return regions.list_observation(lst, window)
        from PySide6.QtCore import QRect
        as_list = regions.as_list
        from apps.delegates.dasha_presentation_paint import observed_cell
        viewport = lst.viewport()
        view_rect = viewport.visibleRegion().boundingRect()
        rows = []
        for i in range(lst.count()):
            item = lst.item(i)
            if item is None or item.isHidden():
                continue
            rect = lst.visualItemRect(item).intersected(view_rect)
            if rect.isEmpty():
                continue
            top_left = viewport.mapTo(window, rect.topLeft())
            shown = observed_cell(self.delegate.fields(lst.model().index(i, 0)))
            rows.append({"rect": as_list(QRect(top_left, rect.size())),
                         "cells": {"Period": item.data(Qt.ItemDataRole.DisplayRole), "Shown": shown}})
        return {"header": ["Period", "Shown"], "rows": rows}


class ShelfTitleChip(QWidget):
    """The small "of <chart>" chip of the shelf title (SPEC-DUAL-001 §4.4):
    10 px, weight 600, tracking 0.2 px, on a 92 % theme surface with a 0.5 px
    hairline and radius 4. Painted from the theme at paint time (Rule 20)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = ""
        from PySide6.QtWidgets import QSizePolicy
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    def text(self) -> str:
        return self._text

    def set_text(self, text: str) -> None:
        if text != self._text:
            self._text = text
            self.updateGeometry()
            self.update()

    def _font(self):
        from PySide6.QtGui import QFont
        f = QFont(self.font())
        f.setPixelSize(scaled_px(10))
        f.setWeight(QFont.Weight.DemiBold)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.2)
        return f

    def sizeHint(self):
        from PySide6.QtGui import QFontMetrics
        fm = QFontMetrics(self._font())
        return QSize(fm.horizontalAdvance(self._text) + scaled_px(12), fm.height() + scaled_px(2))

    def minimumSizeHint(self):
        return QSize(scaled_px(24), self.sizeHint().height())

    def paintEvent(self, _event):
        from PySide6.QtGui import QFontMetrics
        from ui.qt_theme import bar_tokens
        theme = get_theme_colors()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.25, 0.25, -0.25, -0.25)
        fill = QColor(theme["secondary"])
        fill.setAlphaF(0.92)
        p.setBrush(fill)
        p.setPen(QPen(bar_tokens()["hair"], 0.5))
        p.drawRoundedRect(r, scaled_px(4), scaled_px(4))
        f = self._font()
        p.setFont(f)
        p.setPen(QColor(theme["secondary_text"]))
        fm = QFontMetrics(f)
        text = fm.elidedText(self._text, Qt.TextElideMode.ElideRight,
                             max(0, self.width() - scaled_px(12)))
        p.drawText(r.adjusted(scaled_px(6), 0, -scaled_px(6), 0),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        p.end()
