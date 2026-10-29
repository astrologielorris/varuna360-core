"""The classic hover preview and the chains (SPEC-EXCH-002 3.4.3, td-x0z8g): the
preview takes the centre (no chain while it shows) and leaves with the mouse, so
the chains come back. Wired once per classic view, on its first chain pass."""
import weakref
from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QCursor
from apps.widgets import exchange_chain_centre as xcn
from apps.widgets.exchange_chain_centre import classic_centre_sync

__all__ = ["classic_si_pass", "classic_centre_sync"]
WIRED = "xc_hover_wired"


class _LeaveFilter(QObject):
    """Viewport Leave with the cursor really off the chart (a menu over it also sends Leave)."""

    def __init__(self, view):
        super().__init__(view)                 # Qt owns it with the view
        self._view = weakref.ref(view)

    def eventFilter(self, obj, event):
        view = self._view()
        if (event.type() == QEvent.Type.Leave and view is not None and view.current_hover_sign is not None
                and not obj.rect().contains(obj.mapFromGlobal(QCursor.pos()))):
            view._hide_center_preview()
            classic_centre_sync(view)
        return False


def _wire(view):
    if not view.center_box_enabled or view.property(WIRED):
        return
    view.setProperty(WIRED, True)
    view.viewport().installEventFilter(_LeaveFilter(view))
    ref = weakref.ref(view)                # after the view's own preview slot: the sign is set
    view.hover_signal.hover_enter.connect(lambda _i: (v := ref()) is not None and classic_centre_sync(v))


def classic_si_pass(view, get=None):
    _wire(view)
    return xcn.classic_si_pass(view, get)
