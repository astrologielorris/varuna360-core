"""SIDE DRAWERS & ANIMATION cluster, extracted from ChartGUI (Stage 1b, move-only).

Move-only mixin per the split-investigation plan Option 4 (see
proprietary_docs/docs/god_object_decomposition/). Method BODIES are moved
byte-identically (AST-identical); ChartGUI inherits this mixin so every
self.* resolves unchanged via the MRO and no self.gui.* write is created.
Imports are MODULE-TOP here (not method-local) to preserve body byte-identity
— the Kala mixin needed zero top-level imports, this cluster references
module-level names, so they are imported at module top and cycle-checked.
"""

from PySide6.QtCore import QEasingCurve, QPropertyAnimation


class SideDrawersMixin:
    """SIDE DRAWERS & ANIMATION behaviour for ChartGUI (see module docstring)."""

    def _toggle_side_drawer(self, side):
        """Toggle a group of side panels with slide animation."""
        if side == "left":
            panels = [self.vedanga_panel, self.varga_column]
            is_open = self._left_drawer_open
            # Close the other side first
            if self._right_drawer_open:
                self._close_drawer("right")
        else:
            panels = [self.right_scroll, self.vimshottari_panel]
            is_open = self._right_drawer_open
            if self._left_drawer_open:
                self._close_drawer("left")

        if is_open:
            self._close_drawer(side)
        else:
            self._open_drawer(side, panels)

    def _open_drawer(self, side, panels):
        """Slide panels in from the edge."""
        self._stop_all_anims()

        for panel in panels:
            target_w = self._panel_target_widths[panel]
            panel.setMinimumWidth(0)
            panel.setMaximumWidth(0)
            panel.setVisible(True)

            anim = QPropertyAnimation(panel, b"maximumWidth")
            anim.setStartValue(0)
            anim.setEndValue(target_w)
            anim.setDuration(self.DRAWER_ANIM_MS)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            # Restore fixed width when animation finishes
            anim.finished.connect(lambda p=panel, w=target_w: (
                p.setMinimumWidth(w), p.setMaximumWidth(w)
            ))
            anim.start()
            self._running_anims.append(anim)

        if side == "left":
            self._left_drawer_open = True
            self._left_toggle.setText("\u25c0")  # arrow points left = "close"
        else:
            self._right_drawer_open = True
            self._right_toggle.setText("\u25b6")  # arrow points right = "close"

    def _close_drawer(self, side):
        """Slide panels out toward the edge."""
        self._stop_all_anims()

        if side == "left":
            panels = [self.vedanga_panel, self.varga_column]
        else:
            panels = [self.right_scroll, self.vimshottari_panel]

        for panel in panels:
            current_w = self._panel_target_widths[panel]
            panel.setMinimumWidth(0)

            anim = QPropertyAnimation(panel, b"maximumWidth")
            anim.setStartValue(current_w)
            anim.setEndValue(0)
            anim.setDuration(self.DRAWER_ANIM_MS)
            anim.setEasingCurve(QEasingCurve.Type.InCubic)
            anim.finished.connect(lambda p=panel: p.setVisible(False))
            anim.start()
            self._running_anims.append(anim)

        if side == "left":
            self._left_drawer_open = False
            self._left_toggle.setText("\u25b6")
        else:
            self._right_drawer_open = False
            self._right_toggle.setText("\u25c0")

    def _stop_all_anims(self):
        """Stop all running drawer animations."""
        for anim in self._running_anims:
            anim.stop()
        self._running_anims.clear()

    # === DASHA NAVIGATION METHODS ===
