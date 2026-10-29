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
        """Toggle a side drawer. The right side is owned by ChartLayoutManager
        (SPEC-LAYOUT-001): its drawer only exists as the last-resort fallback
        and never interacts with the left drawer."""
        if side != "left":
            self.chart_layout.toggle_right_drawer()
            return
        if self._left_drawer_open:
            self._close_drawer("left")
        else:
            self._open_drawer("left", [self.vedanga_panel, self.varga_column])

    def _open_drawer(self, side, panels):
        """Slide the left panels in from the edge."""
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

        self._left_drawer_open = True
        self._left_toggle.setText("\u25c0")  # arrow points left = "close"

    def _close_drawer(self, side):
        """Slide the left panels out toward the edge."""
        self._stop_all_anims()

        for panel in [self.vedanga_panel, self.varga_column]:
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

        self._left_drawer_open = False
        self._left_toggle.setText("\u25b6")

    def _stop_all_anims(self):
        """Stop all running drawer animations."""
        for anim in self._running_anims:
            anim.stop()
        self._running_anims.clear()

    # === DASHA NAVIGATION METHODS ===
