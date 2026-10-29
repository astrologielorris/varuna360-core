"""Stop the mouse wheel from changing values inside the Settings tab.

Scrolling down a settings page while the pointer passes over a dropdown,
number box or slider used to change that setting by accident. Inside a
guarded tree the wheel never edits those controls: it scrolls the page
instead. Clicking and typing still work as before; an opened dropdown list
still scrolls normally (the list popup is not one of the blocked types).

The filter lives on the QApplication so controls built later (lazy pages,
rebuilt rows) are covered without re-wiring.
"""

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import (
    QAbstractScrollArea, QAbstractSpinBox, QApplication, QComboBox, QSlider,
    QWidget,
)

_GUARD_PROPERTY = "_v360_block_wheel_edits"
_BLOCKED_TYPES = (QComboBox, QAbstractSpinBox, QSlider)

_filter = None


class _WheelGuard(QObject):
    def eventFilter(self, obj, event):
        if event.type() != QEvent.Type.Wheel:
            return False
        if not isinstance(obj, _BLOCKED_TYPES) or not _inside_guarded_tree(obj):
            return False
        area = _scroll_area_above(obj)
        if area is not None:
            bar = area.verticalScrollBar()
            if bar is not None and bar.isVisible():
                QApplication.sendEvent(bar, event)
        return True


def _inside_guarded_tree(widget: QWidget) -> bool:
    w = widget
    while w is not None:
        if w.property(_GUARD_PROPERTY):
            return True
        w = w.parentWidget()
    return False


def _scroll_area_above(widget: QWidget):
    w = widget.parentWidget()
    while w is not None:
        if isinstance(w, QAbstractScrollArea):
            return w
        w = w.parentWidget()
    return None


def guard(root: QWidget) -> None:
    """Block wheel edits on every dropdown, spin box and slider under root."""
    global _filter
    root.setProperty(_GUARD_PROPERTY, True)
    app = QApplication.instance()
    if app is not None and _filter is None:
        # Through the shared rule: a plain app-wide Python filter segfaults
        # PySide as soon as a web view (AI windows) exists.
        from managers.context_menu_manager import install_app_filter
        _filter = _WheelGuard(app)
        install_app_filter(_filter)
