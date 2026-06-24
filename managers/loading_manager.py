# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Loading manager for Varuna360.

Coordinates showing/hiding the LoadingOverlay widget across the application.
Supports nesting (multiple overlapping operations) and minimum display time
to prevent flicker.
"""

from PySide6.QtWidgets import QMainWindow, QApplication
from PySide6.QtCore import QTimer, QElapsedTimer

from apps.widgets.loading_overlay import LoadingOverlay


class LoadingManager:
    """Coordinates the loading overlay for the main window.

    Supports nesting: if operation A starts the overlay and operation B
    also starts it before A finishes, the overlay stays visible until
    both call finish(). Uses a reference counter internally.

    Usage in managers:
        self.gui.loading_manager.start("Loading chart...")
        # ... do work ...
        self.gui.loading_manager.update("Calculating positions...")
        # ... more work ...
        self.gui.loading_manager.finish()
    """

    # Minimum time (ms) the overlay stays visible to prevent flicker
    MIN_DISPLAY_MS = 200

    def __init__(self, gui: QMainWindow):
        self._gui = gui
        self._overlay = LoadingOverlay(gui)
        self._ref_count = 0
        self._elapsed = QElapsedTimer()
        self._pending_hide = False

    def start(self, message: str = "Loading..."):
        """Show the overlay (or update message if already visible).

        Can be called multiple times for nested operations — the overlay
        stays visible until all callers have called finish().
        """
        self._ref_count += 1
        self._pending_hide = False

        if self._ref_count == 1:
            # First caller — show overlay and start timer
            self._elapsed.start()
            self._overlay.show_loading(message)
        else:
            # Already visible — just update the message
            self._overlay.update_message(message)

    def update(self, message: str):
        """Update the status message while overlay is visible.

        Also calls processEvents() to keep the event loop alive.
        """
        if self._ref_count > 0:
            self._overlay.update_message(message)

    def set_progress(self, current: int, total: int):
        """Switch to determinate progress mode.

        Args:
            current: Current step (0 to total)
            total: Total number of steps
        """
        if self._ref_count > 0:
            self._overlay.set_progress(current, total)

    def finish(self):
        """Signal that one operation is done.

        The overlay hides only when ALL nested operations have finished.
        Respects minimum display time to prevent flicker.
        """
        if self._ref_count <= 0:
            return

        self._ref_count -= 1

        if self._ref_count == 0:
            elapsed_ms = self._elapsed.elapsed()
            remaining = self.MIN_DISPLAY_MS - elapsed_ms

            if remaining > 0:
                # Delay hide to meet minimum display time
                self._pending_hide = True
                QTimer.singleShot(int(remaining), self._try_hide)
            else:
                self._overlay.hide_loading()

    def force_finish(self):
        """Force-hide the overlay regardless of ref count.

        Use only as a safety net (e.g., error recovery).
        """
        self._ref_count = 0
        self._pending_hide = False
        self._overlay.hide_loading()

    @property
    def is_active(self) -> bool:
        """Whether the overlay is currently visible."""
        return self._ref_count > 0

    def _try_hide(self):
        """Delayed hide — only proceeds if no new start() happened."""
        if self._pending_hide and self._ref_count == 0:
            self._pending_hide = False
            self._overlay.hide_loading()

    def refresh_theme(self):
        """Forward theme refresh to the wrapped LoadingOverlay (SPEC-THM-001 G13)."""
        if hasattr(self._overlay, 'refresh_theme'):
            self._overlay.refresh_theme()
