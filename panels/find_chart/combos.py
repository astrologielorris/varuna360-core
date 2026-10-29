# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The Find Chart combos (filter-redesign.md §6).

``ReadableCombo`` gives the popup an explicit ``QListView`` with item padding
(the default view reserves a check column and indents the text) and a minimum
width from the content, so long labels are not cut off at the combo's width
(pattern: ``apps/widgets/planet_icon_colors.readable_combo``).

``SectionedCombo`` groups its items under bold, disabled section headers.
Items carry the stored value as item data (SPEC-LOC-002 INV-3) and are
indented under their header; a section titled ``None`` has no header and
its items sit at the margin. ``findData`` and ``currentData`` work on them
as on a plain combo. Mouse, wheel and keyboard skip the headers: Qt never
makes a disabled row current.

``MenuCombo`` is a combo whose rarer items sit in a submenu (a tool button
and a ``QMenu``; ``QComboBox`` has no submenus). It answers the combo calls
a caller uses (``addItem``, ``findData``, ``currentData``,
``setCurrentIndex``, ``currentIndexChanged``), so it stands in for one.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QSize, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QComboBox,
    QListView,
    QMenu,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolButton,
    QWidget,
)

from panels.find_chart.choices import Item
from panels.find_chart import kit

#: Popup item padding, vertical and horizontal (px).
PAD_V, PAD_H = 4, 10
#: How far a sectioned item sits right of its header (px).
INDENT = 14
#: The item-data role marking a section header.
HEADER_ROLE = Qt.ItemDataRole.UserRole + 1
#: The item-data role marking an item outside any section (not indented).
FLAT_ROLE = Qt.ItemDataRole.UserRole + 2


class ReadableCombo(QComboBox):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        view = QListView(self)
        view.setStyleSheet(f"QListView::item {{ padding: {PAD_V}px {PAD_H}px; }}")
        self.setView(view)

    def showPopup(self) -> None:
        view = self.view()
        view.setFont(self.font())
        # Items added before the padded item style was polished keep their
        # unpadded positions (rows overlap): lay them out again.
        view.doItemsLayout()
        content = view.sizeHintForColumn(0) + 2 * PAD_H + view.frameWidth() * 2
        scrollbar = view.verticalScrollBar().sizeHint().width()
        view.setMinimumWidth(max(self.width(), content + scrollbar))
        super().showPopup()


def _indented(index: QModelIndex | QPersistentModelIndex) -> bool:
    return not (index.data(HEADER_ROLE) or index.data(FLAT_ROLE))


class _SectionDelegate(QStyledItemDelegate):
    """Indents the items under a header; the header itself, and the items
    outside any section, sit at the margin."""

    def initStyleOption(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> None:
        super().initStyleOption(option, index)
        if _indented(index):
            option.rect = option.rect.adjusted(INDENT, 0, 0, 0)

    def sizeHint(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        hint = super().sizeHint(option, index)
        if _indented(index):
            hint.setWidth(hint.width() + INDENT)
        return hint


class SectionedCombo(ReadableCombo):
    """``set_sections`` fills it; a section with no items gets no header."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = QStandardItemModel(self)
        self.setModel(self._model)
        self.view().setItemDelegate(_SectionDelegate(self.view()))

    def set_sections(
        self,
        sections: Sequence[tuple[str | None, Sequence[Item]]],
        blank: str | None,
    ) -> None:
        """Replace every row. ``blank``: the label of an unsectioned first item
        carrying None (the cascade's "pick one"), or no such item."""
        self._model.clear()
        if blank is not None:
            first = QStandardItem(blank)
            first.setData(True, FLAT_ROLE)
            self._model.appendRow(first)
        for title, items in sections:
            if not items:
                continue
            if title is not None:
                header = QStandardItem(title)
                header.setFlags(Qt.ItemFlag.NoItemFlags)
                header.setData(True, HEADER_ROLE)
                font = header.font()
                font.setBold(True)
                header.setFont(font)
                self._model.appendRow(header)
            for item in items:
                row = QStandardItem(item.label)
                row.setData(item.value, Qt.ItemDataRole.UserRole)
                row.setData(title is None, FLAT_ROLE)
                if item.tooltip is not None:
                    row.setToolTip(item.tooltip)
                self._model.appendRow(row)

    def is_header(self, index: int) -> bool:
        return bool(self.itemData(index, HEADER_ROLE))


class MenuCombo(QToolButton):
    """The items whose value is in ``common`` on the menu, in order, then a
    ``more`` submenu with the rest; the button shows the current item's label,
    wherever it sits. Each ``addItem`` places one item."""

    currentIndexChanged = Signal(int)

    def __init__(
        self, common: Sequence[object], more: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._common = common
        self._items: list[tuple[str, object]] = []
        self._actions: list[QAction] = []
        self._index = -1
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._menu = kit.style_menu(QMenu(self))
        self._more = kit.style_menu(QMenu(more, self._menu))
        self._group = QActionGroup(self)
        self._menu.addMenu(self._more)
        self._menu.aboutToShow.connect(self._match_font)
        self.setMenu(self._menu)

    def addItem(self, label: str, value: object) -> None:
        if value in self._common:
            action = QAction(label, self._menu)
            self._menu.insertAction(self._common_after(value), action)
        else:
            action = self._more.addAction(label)
        action.setCheckable(True)
        self._group.addAction(action)
        index = len(self._items)
        action.triggered.connect(lambda _checked, i=index: self.setCurrentIndex(i))
        self._items.append((label, value))
        self._actions.append(action)
        if self._index < 0:
            self.setCurrentIndex(index)

    def _common_after(self, value: object) -> QAction:
        """The menu entry a common item goes before: the first placed common
        item later in ``common``, else the submenu."""
        rank = self._common.index(value)
        later = [
            (self._common.index(v), action)
            for (_label, v), action in zip(self._items, self._actions, strict=True)
            if v in self._common and self._common.index(v) > rank
        ]
        return (
            min(later, key=lambda pair: pair[0])[1]
            if later
            else self._more.menuAction()
        )

    def count(self) -> int:
        return len(self._items)

    def itemText(self, index: int) -> str:
        return self._items[index][0]

    def itemData(self, index: int) -> object:
        return self._items[index][1]

    def findData(self, value: object) -> int:
        return next((i for i, (_l, v) in enumerate(self._items) if v == value), -1)

    def currentIndex(self) -> int:
        return self._index

    def currentData(self) -> object:
        return self._items[self._index][1] if self._index >= 0 else None

    def currentText(self) -> str:
        return self._items[self._index][0] if self._index >= 0 else ""

    def setCurrentIndex(self, index: int) -> None:
        if not 0 <= index < len(self._items) or index == self._index:
            return
        self._index = index
        self._actions[index].setChecked(True)
        self.setText(self._items[index][0])
        self.currentIndexChanged.emit(index)

    def is_common(self, index: int) -> bool:
        """Whether the item is on the menu itself, not in the submenu."""
        return self._items[index][1] in self._common

    def _match_font(self) -> None:
        self._menu.setFont(self.font())
        self._more.setFont(self.font())
