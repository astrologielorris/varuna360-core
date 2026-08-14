# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""TRANSIT button that also accepts chart drops for overlay (SPEC-TRN-006).

A checkable QPushButton subclass that keeps its normal click-to-toggle behaviour
and additionally accepts:
  - a memory chart button drag (custom MIME carrying the entry id), and
  - an external .chtk / .toml file drag,
delegating the drop to ChartOverlayManager. Zero business logic lives here: the
widget only recognises the payload, shows the themed affordance, and forwards the
mime data to the manager (Rule 4).

Accept-and-refuse: a recognised chart payload is accepted at drag-enter even when
no base chart is loaded, so the drop does NOT fall through to the ChartDropTab
ancestor (which would load the file as the active chart, the opposite of the
intended overlay). The refusal is reported from dropEvent instead.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton

from ui.qt_theme import get_theme_colors, scaled_area_px
from apps.widgets.chart_memory_button import CHART_ENTRY_MIME
from apps.widgets.chart_drop_common import classify_chart_drop

_HOVER_TEXT = "⟐ Overlay chart"
_HOVER_TOOLTIP = "Drop to overlay this chart on the active chart"


class TransitDropButton(QPushButton):
    """Checkable transit button that also accepts chart drops for overlay."""

    def __init__(self, text, gui, parent=None):
        super().__init__(text, parent)
        self._gui = gui
        self.setAcceptDrops(True)
        self._hover_snapshot = None  # (style, text, tooltip) captured live on enter

    # --- payload recognition -------------------------------------------------
    def _payload_kind(self, mime):
        """Return 'memory', 'files', 'folder', or None.

        A folder is RECOGNISED (so the button consumes the drop and refuses it
        with a message) rather than ignored — otherwise Qt would hand the folder
        to the ChartDropTab ancestor, which loads it as a chart library (the
        ancestor-fallthrough B-3 requires the button to prevent).
        """
        if mime.hasFormat(CHART_ENTRY_MIME):
            return "memory"
        files, folders = classify_chart_drop(mime)
        if files:
            return "files"
        if folders:
            return "folder"
        return None

    # --- drag events ---------------------------------------------------------
    def dragEnterEvent(self, event):
        # Accept ANY recognised chart payload, even with no base chart, so the
        # drop cannot fall through to the ChartDropTab ancestor. The no-base-chart
        # refusal happens in dropEvent with a status message.
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
        # Folder: consume and refuse (no single chart to overlay); do NOT let it
        # fall through to the tab body's load-a-library behaviour.
        if self._payload_kind(mime) == "folder":
            try:
                self._gui.statusBar().showMessage(
                    "A folder cannot be overlaid. Drop a single chart on Transit.",
                    5000)
            except Exception:
                pass
            return
        mgr = getattr(self._gui, "chart_overlay_manager", None)
        if mgr is not None:
            mgr.handle_drop(mime)

    def hideEvent(self, event):
        # Compact mode can hide the button mid-drag; make sure it is never later
        # revealed still wearing the drop highlight.
        self._exit_drop_look()
        super().hideEvent(event)

    # --- themed affordance ---------------------------------------------------
    def _enter_drop_look(self):
        if self._hover_snapshot is not None:
            return  # already hovering
        # Snapshot the LIVE presentation (not a construction-time snapshot, which
        # would be empty and would clobber an active "Overlay" label on restore).
        self._hover_snapshot = (self.styleSheet(), self.text(), self.toolTip())
        theme = get_theme_colors()
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme["primary_dark"]};
                color: {theme["primary_text"]};
                font-size: {scaled_area_px('buttons')}px;
                border: 2px dashed {theme["primary_light"]};
                border-radius: 8px;
                padding: 8px 10px;
            }}
        """)
        self.setText(_HOVER_TEXT)
        self.setToolTip(_HOVER_TOOLTIP)

    def _exit_drop_look(self):
        if self._hover_snapshot is None:
            return
        style, text, tooltip = self._hover_snapshot
        self._hover_snapshot = None
        self.setStyleSheet(style)
        self.setText(text)
        self.setToolTip(tooltip)
