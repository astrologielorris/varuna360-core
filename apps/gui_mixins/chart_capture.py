"""CHART CAPTURE (screenshot/PNG) methods, extracted from ChartGUI
(Stage 1b W5, move-only SPLIT of the TOGGLE BUTTON STYLES & CAPTURE cluster).

Only the 3 capture methods move here; the two toggle-button STYLE methods
(_update_toggle_button_styles, _legacy_toggle_button_styles) deliberately stay
in ChartGUI — they are Stage 3 theme-refresh territory and carry the cluster's
only source-location-sensitive test coupling (test_bar_construction.py keys on
the _legacy_ regex). Bodies moved byte-identically; imports are module-top for
AST-identity (cycle-checked).
"""

from pathlib import Path
from PySide6.QtGui import QColor


class ChartCaptureMixin:
    """Chart capture (screenshot/PNG) behaviour for ChartGUI (see module docstring)."""

    def _take_screenshot(self):
        """Capture chart view and save as PNG. Delegates to ChartManager."""
        self.chart_manager.take_screenshot()

    def _save_chart_as_png(self):
        """Export current chart view as high-quality PNG with file dialog."""
        from PySide6.QtWidgets import QFileDialog
        from PySide6.QtGui import QImage, QPainter
        from PySide6.QtCore import Qt

        # Get the current chart widget. The four scene-based views export at
        # their native 2048px scene resolution; Cards of Truth (SPEC-COT-001)
        # paints straight onto the widget with no scene, so it exports the
        # rendered widget instead — WYSIWYG at screen resolution rather than a
        # 2x upscale that would soften the planet-icon raster art.
        current = self.chart_stack.currentWidget()
        if not current:
            self.statusBar().showMessage("No chart to save", 3000)
            return
        scene_based = hasattr(current, 'scene')

        # Build default filename from chart name
        chart_name = "chart"
        if self.current_chart_data:
            chart_name = self.current_chart_data.get('name', 'chart')
            chart_name = "".join(c for c in chart_name if c.isalnum() or c in " _-").strip()
            chart_name = chart_name.replace(" ", "_")
            # The filter above removes Windows-illegal characters, but a name
            # made only of them collapses to "" (yielding a dotfile like
            # ".png"), and CON/NUL/COM1 survive it intact.
            from core.fs_safety import windows_safe_filename
            chart_name = windows_safe_filename(chart_name, default="chart")

        default_path = str(Path.home() / f"{chart_name}.png")

        filepath, _ = QFileDialog.getSaveFileName(
            self, "Save Chart as PNG", default_path,
            "PNG Images (*.png);;All Files (*)"
        )
        if not filepath:
            return

        if scene_based:
            # Render scene at native resolution (scene is already 2048px — high quality)
            scene = current.scene
            scene_rect = scene.sceneRect()
            width = int(scene_rect.width())
            height = int(scene_rect.height())

            from PySide6.QtCore import QRectF
            image = QImage(width, height, QImage.Format.Format_ARGB32)
            image.fill(QColor("#1a1a1e"))  # Dark background

            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            # Explicit target (full image) ← source (full scene) mapping
            target = QRectF(0, 0, width, height)
            scene.render(painter, target, scene_rect)
            painter.end()
        else:
            image = current.grab().toImage()

        # PNG compression: 0 = max compression (smaller file), 100 = no compression
        image.save(filepath, "PNG", 50)
        self.statusBar().showMessage(f"Chart saved: {filepath}", 5000)

    def _save_full_view_as_png(self):
        """Export chart content area as PNG (dasha panels + chart + info panels)."""
        from PySide6.QtWidgets import QFileDialog

        chart_name = "chart"
        if self.current_chart_data:
            chart_name = self.current_chart_data.get('name', 'chart')
            chart_name = "".join(c for c in chart_name if c.isalnum() or c in " _-").strip()
            chart_name = chart_name.replace(" ", "_")
            # The filter above removes Windows-illegal characters, but a name
            # made only of them collapses to "" (yielding a dotfile like
            # ".png"), and CON/NUL/COM1 survive it intact.
            from core.fs_safety import windows_safe_filename
            chart_name = windows_safe_filename(chart_name, default="chart")

        default_path = str(Path.home() / f"{chart_name}_full.png")

        filepath, _ = QFileDialog.getSaveFileName(
            self, "Save Full View as PNG", default_path,
            "PNG Images (*.png);;All Files (*)"
        )
        if not filepath:
            return

        # Grab just the chart content area (Vedanga → Chart → Info → Vimshottari)
        # Excludes toolbar, memory panel, tab bar
        pixmap = self.chart_content.grab()
        pixmap.save(filepath, "PNG", 50)
        self.statusBar().showMessage(f"Full view saved: {filepath}", 5000)
