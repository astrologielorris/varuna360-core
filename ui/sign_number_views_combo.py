# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The "Signs as numbers" drop-down of Settings > Chart Display.

Looks like the page's other combos, but opens a menu BELOW itself holding one
real QCheckBox per chart view that can show signs as numbers
(ui.sign_numbers.SIGN_NUMBER_VIEWS). Real check boxes, because the app theme
(qt-material) draws no tick for checkable combo items; below the box, because a
combo list opens over the box with its first row under the pointer, so the
release of the opening click ticked it. The menu opens on the click's release
(opened on the press, the theme closed it again on the release). Clicking a box ticks it and leaves the
menu open; the closed combo names the ticked views. The value is the list of
ticked view keys, the stored form of ``display.sign_number_views``.
"""
from PySide6.QtCore import QPoint, QTimer, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QMenu, QStyle, QStyleOptionComboBox,
                               QStylePainter, QWidgetAction)

from ui import settings_rows as _rows
from ui.qt_theme import scaled_area_px
from ui.sign_numbers import SIGN_NUMBER_VIEWS


class _StayOpenMenu(QMenu):
    """A menu whose clicks toggle the check box under the pointer and keep it
    open. The boxes are transparent to the mouse, so every click reaches this
    menu: left to QCheckBox, the themed QMenu took the click itself and closed
    without ticking anything."""

    def mousePressEvent(self, event):
        if self._box_at(event) is None:
            super().mousePressEvent(event)   # outside: close as usual
        else:
            event.accept()

    def mouseReleaseEvent(self, event):
        box = self._box_at(event)
        if box is None:
            super().mouseReleaseEvent(event)
        else:
            box.toggle()
            event.accept()

    def _box_at(self, event):
        action = self.actionAt(event.position().toPoint())
        return action.defaultWidget() if isinstance(action, QWidgetAction) else None


class SignNumberViewsCombo(QComboBox):
    """Multi-select drop-down of chart views; ``views()`` / ``set_views()``."""

    changed = Signal()

    def __init__(self, parent=None, max_width=260):
        super().__init__(parent)
        labels = dict(_rows.choices("chart.view_type"))
        self.menu = _StayOpenMenu(self)
        self.boxes = {}
        for key in SIGN_NUMBER_VIEWS:
            box = QCheckBox(labels.get(key, key))
            box.setStyleSheet(f"font-size: {scaled_area_px('buttons')}px; padding: 6px 12px;")
            box.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            box.toggled.connect(self._on_toggled)
            action = QWidgetAction(self.menu)
            action.setDefaultWidget(box)
            self.menu.addAction(action)
            self.boxes[key] = box
        _rows.calculation_tooltip(self, "display.sign_number_views")
        if max_width:
            self.setMaximumWidth(max_width)

    def _on_toggled(self, _checked):
        self.update()
        self.changed.emit()

    def mousePressEvent(self, event):
        # Open on RELEASE, not press: a menu opened on the press receives that
        # same click's release outside itself and closes at once (seen in the
        # themed app).
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            QTimer.singleShot(0, self.showPopup)
        event.accept()

    def showPopup(self):
        self.menu.setMinimumWidth(self.width())
        self.menu.popup(self.mapToGlobal(QPoint(0, self.height())))

    def hidePopup(self):
        self.menu.hide()

    def views(self):
        return [key for key, box in self.boxes.items() if box.isChecked()]

    def set_views(self, views):
        wanted = set(views) if isinstance(views, (list, tuple)) else set()
        for key, box in self.boxes.items():
            box.blockSignals(True)
            box.setChecked(key in wanted)
            box.blockSignals(False)
        self.update()

    def summary(self):
        names = [box.text() for box in self.boxes.values() if box.isChecked()]
        return ", ".join(names) if names else "None"

    def paintEvent(self, event):
        painter = QStylePainter(self)
        opt = QStyleOptionComboBox()
        self.initStyleOption(opt)
        opt.currentText = self.summary()
        painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, opt)
        painter.drawControl(QStyle.ControlElement.CE_ComboBoxLabel, opt)
