# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The result cards at phone width (SPEC-FIND-005 §3.5, §4.8 T4).

At 640 px and below the table is hidden (still filled: Pro reads it) and
this list shows the same entries in the same order, one card each: name and
birth, the Asc / Sun / Moon pills, "place, country · folder", the source
pills. A ``QListView`` with a painted delegate, so thousands of results cost
no widgets.

API
- ``ResultCards()``
- signals: ``entry_activated(str entry_id)`` (tap: inspect),
  ``entry_opened(str entry_id)`` (double tap: open)
- ``set_entries(entries, labels_fn)``: ``labels_fn(entry)`` returns the
  mapping ``results.row_values`` takes (``ascendant``, ``sun``, ``moon``)
- ``select(entry_id | None)``, ``selected_entry_id()``, ``entry_ids()``
- ``refresh_theme()``, ``refresh_metrics()``

Host wiring: fill it with the table's entries in the same order after every
refresh, ``select(selected_entry_id)`` again, connect ``entry_activated`` to
the row selection + inspector and ``entry_opened`` to ``_open_row``'s logic.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QListView,
    QStyle,
    QStyledItemDelegate,
)

from apps.widgets.action_bar.bar_types import draw_bar_text, text_advance
from core.chart_search.search import ResultEntry
from panels.find_chart import kit
from panels.find_chart.result_columns import source_pills

AREA = "tables"  # the cards are the table's twin (INV-10)
ENTRY_ROLE = Qt.UserRole + 1
LABELS_ROLE = Qt.UserRole + 2


def meta_line(entry: ResultEntry) -> str:
    """"Paris, France · folder" (empty parts left out)."""
    place = ", ".join(p for p in (entry.place, entry.country) if p)
    folder = os.path.basename(os.path.dirname(entry.path)) if entry.path else ""
    return " · ".join(p for p in (place, folder) if p)


class _CardsModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries: list[ResultEntry] = []
        self._labels: list[Mapping[str, str]] = []

    def reset(self, entries: Sequence[ResultEntry], labels: list[Mapping[str, str]]) -> None:
        self.beginResetModel()
        self._entries = list(entries)
        self._labels = labels
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):  # noqa: N802
        return 0 if parent.isValid() else len(self._entries)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        entry = self._entries[index.row()]
        if role == Qt.DisplayRole:
            return entry.name
        if role == ENTRY_ROLE:
            return entry
        if role == LABELS_ROLE:
            return self._labels[index.row()]
        if role == Qt.ToolTipRole:
            return "Click: inspect · Double click: open"
        return None

    def entry(self, row: int) -> ResultEntry:
        return self._entries[row]

    def row_of(self, entry_id) -> int:
        for i, e in enumerate(self._entries):
            if e.entry_id == entry_id:
                return i
        return -1


def elide(text: str, size: float, weight: float, tracking: float, fs: float,
          avail: float) -> str:
    """``text`` cut with an ellipsis to fit ``avail`` px (the painted fonts
    have no elide of their own)."""
    if avail <= 0:
        return ""
    if text_advance(text, size, weight, tracking, fs) <= avail:
        return text
    lo, hi = 0, len(text)
    while lo < hi:  # the longest prefix that fits with the ellipsis
        mid = (lo + hi + 1) // 2
        if text_advance(text[:mid] + "\u2026", size, weight, tracking, fs) <= avail:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + "\u2026" if lo else ""


def _flow(widths: Sequence[float], avail: float, gap: float) -> list[tuple[float, int]]:
    """(x, line) per item, left to right, wrapping when the next does not fit."""
    out: list[tuple[float, int]] = []
    x, line = 0.0, 0
    for w in widths:
        if x > 0 and x + w > avail:
            x, line = 0.0, line + 1
        out.append((x, line))
        x += w + gap
    return out


def card_layout(entry: ResultEntry, labels: Mapping[str, str], width: float, fs: float):
    """Where every text of one card goes at ``width`` (review r10: the pills
    wrap to more lines and every text is cut to its room, so nothing paints
    past the card). Returns ``(height, items)``; an item is ``(kind, rect,
    text)`` with kind one of name, birth, cap, value, meta, src0 (the first
    source pill), src, sign (a sign pill's background)."""
    pad = 12 * fs
    w = max(0.0, width - 2 - 2 * pad)
    x0, y = 1 + pad, 1 + 8 * fs
    line = 18 * fs
    items: list[tuple[str, QRectF, str]] = []
    birth = elide(entry.birth_local[:16], 11, 450, 0, fs, w * 0.45)
    bw = text_advance(birth, 11, 450, 0, fs)
    items.append(("birth", QRectF(x0 + w - bw - 2, y, bw + 2, line), birth))
    name_w = max(0.0, w - bw - 8 * fs)
    items.append(("name", QRectF(x0, y, name_w, line),
                  elide(entry.name, 13, 620, 0, fs, name_w)))
    y += line + 5 * fs
    # Asc / Sun / Moon pills, wrapping
    pill_h, gap = 18 * fs, 6 * fs
    pills = []
    for caption, key in (("ASC", "ascendant"), ("SUN", "sun"), ("MOON", "moon")):
        cw = text_advance(caption, 9.5, 650, 0.06, fs)
        room = w - (7 * fs + cw + 4 * fs + 7 * fs)
        value = elide(labels.get(key, "") or "\u00b7", 11, 500, 0, fs, room)
        vw = text_advance(value, 11, 500, 0, fs)
        pills.append((caption, cw, value, vw, min(w, 7 * fs + cw + 4 * fs + vw + 7 * fs)))
    spots = _flow([pw for *_rest, pw in pills], w, gap)
    for (caption, cw, value, vw, pw), (px, row) in zip(pills, spots):
        top = y + row * (pill_h + 4 * fs)
        items.append(("sign", QRectF(x0 + px, top, pw, pill_h), ""))
        items.append(("cap", QRectF(x0 + px + 7 * fs, top, cw + 2, pill_h), caption))
        items.append(("value", QRectF(x0 + px + 7 * fs + cw + 4 * fs, top, vw + 2, pill_h),
                      value))
    rows = (spots[-1][1] + 1) if spots else 1
    y += rows * pill_h + (rows - 1) * 4 * fs + 5 * fs
    items.append(("meta", QRectF(x0, y, w, 16 * fs),
                  elide(meta_line(entry), 11.5, 450, 0, fs, w)))
    y += 16 * fs + 4 * fs
    # source pills, wrapping
    texts = [elide(t, 10.5, 500, 0, fs, w - 12 * fs) for t in source_pills(entry)]
    widths = [min(w, text_advance(t, 10.5, 500, 0, fs) + 12 * fs) for t in texts]
    spots = _flow(widths, w, 4 * fs)
    for i, (text, pw, (px, row)) in enumerate(zip(texts, widths, spots)):
        items.append(("src" if i else "src0",
                      QRectF(x0 + px, y + row * 20 * fs, pw, 16 * fs), text))
    rows = (spots[-1][1] + 1) if spots else 1
    y += rows * 16 * fs + (rows - 1) * 4 * fs + 6 * fs
    return y + 1, items


class _CardDelegate(QStyledItemDelegate):
    """Paints one card in the kit's tokens (Rule 20), sized from ``tables``
    and laid out by ``card_layout`` (the height follows the wrapped pills)."""

    GAP = 8  # x fs, between cards

    def _width(self, option) -> int:
        # The view's own width: a card never runs past the viewport (W10, 390 px).
        view = self.parent()
        width = view.viewport().width() if view is not None else option.rect.width()
        return max(160, width - 2)

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        fs = kit.area_fs(AREA)
        width = self._width(option)
        entry = index.data(ENTRY_ROLE)
        if entry is None:
            return QSize(width, round((96 + self.GAP) * fs))
        height, _items = card_layout(entry, index.data(LABELS_ROLE) or {}, width, fs)
        return QSize(width, round(height + self.GAP * fs))

    def paint(self, p: QPainter, option, index) -> None:
        t = kit.tokens()
        fs = kit.area_fs(AREA)
        entry: ResultEntry = index.data(ENTRY_ROLE)
        labels = index.data(LABELS_ROLE) or {}
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(option.rect).adjusted(1, 1, -1, -1 - self.GAP * fs)
        selected = bool(option.state & QStyle.State_Selected)
        hover = bool(option.state & QStyle.State_MouseOver)
        p.setPen(Qt.NoPen)
        p.setBrush(t["ctl_h"] if hover and not selected else t["thumb_top"])
        p.drawRoundedRect(r, 10 * fs, 10 * fs)
        if selected:
            p.setPen(QPen(t["primary"], 1.5))
        else:
            p.setPen(QPen(t["hair_soft"], 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 10 * fs, 10 * fs)
        _height, items = card_layout(entry, labels, option.rect.width(), fs)
        dx, dy = option.rect.left(), option.rect.top()
        left = Qt.AlignVCenter | Qt.AlignLeft
        for kind, rect, text in items:
            rect = rect.translated(dx, dy)
            if kind == "sign":
                p.setPen(Qt.NoPen)
                p.setBrush(t["ctl"])
                p.drawRoundedRect(rect, 5 * fs, 5 * fs)
            elif kind in ("src0", "src"):
                p.setPen(Qt.NoPen)
                p.setBrush(t["tint_blue"] if kind == "src" else t["ctl"])
                p.drawRoundedRect(rect, 4 * fs, 4 * fs)
                p.setPen(t["tint_blue_fg"] if kind == "src" else t["secondary_text"])
                draw_bar_text(p, rect, Qt.AlignCenter, text, 10.5, 500, 0, fs)
            elif kind == "birth":
                p.setPen(t["muted"])
                draw_bar_text(p, rect, Qt.AlignVCenter | Qt.AlignRight, text, 11, 450, 0, fs)
            elif kind == "name":
                p.setPen(t["primary_text"])
                draw_bar_text(p, rect, left, text, 13, 620, 0, fs)
            elif kind == "cap":
                p.setPen(t["muted"])
                draw_bar_text(p, rect, left, text, 9.5, 650, 0.06, fs)
            elif kind == "value":
                p.setPen(t["secondary_text"])
                draw_bar_text(p, rect, left, text, 11, 500, 0, fs)
            elif kind == "meta":
                p.setPen(t["secondary_text"])
                draw_bar_text(p, rect, left, text, 11.5, 450, 0, fs)
        p.restore()


class ResultCards(QListView):
    entry_activated = Signal(str)
    entry_opened = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model = _CardsModel(self)
        self.setModel(self._model)
        self._delegate = _CardDelegate(self)
        self.setItemDelegate(self._delegate)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setFrameShape(QFrame.NoFrame)
        # Each card's height follows its wrapped pills (review r10), laid
        # out in batches so thousands of results stay quick.
        self.setUniformItemSizes(False)
        self.setLayoutMode(QListView.Batched)
        self.setMouseTracking(True)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setResizeMode(QListView.Adjust)
        self.setAccessibleName("Results as cards")
        self.clicked.connect(self._on_clicked)
        self.doubleClicked.connect(self._on_double)
        self.refresh_metrics()

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self.doItemsLayout()  # the card heights follow the new width

    # ------------------------------------------------------------- entries
    def set_entries(
        self,
        entries: Sequence[ResultEntry],
        labels_fn: Callable[[ResultEntry], Mapping[str, str]],
    ) -> None:
        keep = self.selected_entry_id()
        self._model.reset(entries, [dict(labels_fn(e)) for e in entries])
        if keep is not None:
            self.select(keep)

    def entry_ids(self) -> tuple[str, ...]:
        return tuple(self._model.entry(i).entry_id for i in range(self._model.rowCount()))

    def select(self, entry_id) -> bool:
        """Select the card of ``entry_id`` (no signal); ``None`` or an
        absent id clears the selection. Returns whether a card is selected."""
        row = self._model.row_of(entry_id) if entry_id is not None else -1
        sel = self.selectionModel()
        sel.blockSignals(True)
        sel.clearSelection()
        if row >= 0:
            index = self._model.index(row)
            sel.select(index, sel.SelectionFlag.ClearAndSelect)
            sel.setCurrentIndex(index, sel.SelectionFlag.NoUpdate)
            self.scrollTo(index)
        sel.blockSignals(False)
        self.viewport().update()
        return row >= 0

    def selected_entry_id(self):
        rows = self.selectionModel().selectedRows() if self.selectionModel() else []
        return self._model.entry(rows[0].row()).entry_id if rows else None

    def _on_clicked(self, index) -> None:
        if index.isValid():
            self.entry_activated.emit(self._model.entry(index.row()).entry_id)

    def _on_double(self, index) -> None:
        if index.isValid():
            self.entry_opened.emit(self._model.entry(index.row()).entry_id)

    # -------------------------------------------------------- theme, fonts
    def refresh_metrics(self) -> None:
        fs = kit.area_fs(AREA)
        self.setSpacing(0)
        self.setViewportMargins(round(12 * fs), round(4 * fs), round(12 * fs), 0)
        self.scheduleDelayedItemsLayout()
        self.refresh_theme()

    def refresh_theme(self) -> None:
        self.setStyleSheet("QListView { background: transparent; border: none; }")
        self.viewport().update()
