"""SPEC-BAR-001 — TransitSegmentButton: the v2 TRANSIT control (SPEC-TRN-006).

`TransitDropButton`'s drop-accept contract rebased onto `SegmentButton`
(INV-5: recognition, accept-and-refuse, and forwarding semantics are
verbatim from `apps/widgets/transit_drop_button.py`; zero business logic —
the payload goes to ChartOverlayManager). What CHANGED is only the
affordance: the legacy stylesheet snapshot/restore swap is replaced by the
`drop_hover` PAINT state (dashed accent ring, report 02 §1 row 7) plus a
tooltip swap — the box never moves and the label never swaps (constant-box
discipline; the legacy "⟐ Overlay chart" text swap needed a reserved-width
hack the painted ring makes unnecessary).
"""
from __future__ import annotations

from PySide6.QtCore import Qt

from .segment_button import SegmentButton

_HOVER_TOOLTIP = "Drop to overlay this chart on the active chart"


class TransitSegmentButton(SegmentButton):
    def __init__(self, spec, metrics, tokens_fn, gui, parent=None):
        super().__init__(spec, metrics, tokens_fn, parent)
        self._gui = gui
        self._pre_drag_tooltip = spec.tooltip
        self.setAcceptDrops(True)

    # --- payload recognition (verbatim contract) --------------------------
    def _payload_kind(self, mime):
        from apps.widgets.chart_drop_common import classify_chart_drop
        from apps.widgets.chart_memory_button import CHART_ENTRY_MIME
        if mime.hasFormat(CHART_ENTRY_MIME):
            return "memory"
        files, folders = classify_chart_drop(mime)
        if files:
            return "files"
        if folders:
            return "folder"
        return None

    # --- drag events -------------------------------------------------------
    def dragEnterEvent(self, event):
        # Accept ANY recognised chart payload, even with no base chart, so the
        # drop cannot fall through to the ChartDropTab ancestor (B-3); the
        # no-base-chart refusal happens in dropEvent with a status message.
        if self._payload_kind(event.mimeData()) is not None:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.acceptProposedAction()
            self._enter_drop_look()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if self._payload_kind(event.mimeData()) is not None:
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event):
        self._exit_drop_look()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._exit_drop_look()  # highlight can never survive a drop
        mime = event.mimeData()
        if self._payload_kind(mime) is None:
            super().dropEvent(event)
            return
        event.acceptProposedAction()
        if self._payload_kind(mime) == "folder":
            # consume and refuse: no single chart to overlay, and it must NOT
            # fall through to the tab body's load-a-library behaviour.
            try:
                self._gui.statusBar().showMessage(
                    "A folder cannot be overlaid. Drop a single chart on "
                    "Transit.", 5000)
            except Exception:
                pass
            return
        mgr = getattr(self._gui, "chart_overlay_manager", None)
        if mgr is not None:
            mgr.handle_drop(mime)

    def hideEvent(self, event):
        # A tier drop can hide the button mid-drag; never reveal it later
        # still wearing the drop affordance.
        self._exit_drop_look()
        super().hideEvent(event)

    # --- affordance (paint state, not stylesheet) --------------------------
    def _enter_drop_look(self):
        # Snapshot the LIVE tooltip (legacy contract): the overlay manager
        # rewrites it at runtime ("Overlay: <name>…"), and restoring the
        # construction-time one after a drag would lose that.
        if not self._drop_hover:
            self._pre_drag_tooltip = self.toolTip()
        self.set_drop_hover(True)
        self.setToolTip(_HOVER_TOOLTIP)

    def _exit_drop_look(self):
        # No-op while idle: dragLeave/hide/drop all call this defensively,
        # and an inactive exit must not restore a STALE snapshot over a
        # tooltip the overlay manager set since (Sol delta2).
        if not self._drop_hover:
            return
        self.set_drop_hover(False)
        self.setToolTip(self._pre_drag_tooltip)
