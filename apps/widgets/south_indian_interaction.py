"""Camera policy with scalar state and explicitly scoped Qt camera capabilities."""
from dataclasses import dataclass
from typing import Callable
from PySide6.QtCore import Qt, QSize, QRectF
from PySide6.QtWidgets import QGraphicsView
from apps.widgets.south_indian_geometry import SCENE_SIZE

@dataclass(frozen=True)
class CameraOps:
    viewport_size: Callable[[], QSize]
    scene_bounds: Callable[[], QRectF]
    reset: Callable[[], None]
    scale: Callable[[float, float], None]
    center: Callable
    anchor: Callable

class InteractionController:
    def __init__(self):
        self.zoom_factor = .45
        self.min_zoom = .01
        self.max_zoom = 3.0
        self.zoom_step = 1.15
        self._fit_mode = 'page'
        self._fit_zoom_applied = False
        self._is_dragging = False

    def reapply(self, camera):
        camera.reset()
        camera.scale(self.zoom_factor, self.zoom_factor)
        camera.center(SCENE_SIZE/2, SCENE_SIZE/2)

    def resize(self, camera, updating):
        if self._fit_mode and self._fit_zoom_applied and not updating:
            if self._fit_mode == 'width':
                self.fit_width(camera)
            else:
                self.reset_zoom(camera)

    def dispose(self):
        # Capabilities are per-call, so no bound QWidget callback survives here.
        self._is_dragging = False

    def _compute_fit_zoom(self, camera):
        """Return zoom factor that fits the full chart in the current viewport."""
        vp = camera.viewport_size()
        side = min(vp.width(), vp.height())
        if side < 100:
            return 0.45
        return max(0.01, min(self.max_zoom, side / camera.scene_bounds().width() * 0.92))

    def _apply_fit_zoom(self, camera):
        """Deferred auto-fit — runs after layout (viewport size valid)."""
        if self._fit_zoom_applied:
            return
        self._fit_zoom_applied = True
        # An explicit zoom/width request wins over the queued first-show fit.
        if self._fit_mode == 'page':
            self.reset_zoom(camera)

    def wheelEvent(self, camera, event):
        """Cursor-anchored zoom (NI donor :809-862).

            Cross-platform: pixelDelta on macOS, kinetic-momentum filtering on
            Wayland, exponential steps so two half-clicks == one full click.
            """
        if event.phase() == Qt.ScrollPhase.ScrollMomentum:
            event.accept()
            return
        if event.hasPixelDelta():
            raw = event.pixelDelta().y()
            if raw == 0:
                event.accept()
                return
            steps = raw * 0.02
        else:
            delta = event.angleDelta().y()
            if delta == 0:
                event.accept()
                return
            steps = delta / 120.0
        if event.isInverted():
            steps = -steps
        step = self.zoom_step ** abs(steps)
        if steps > 0:
            new_zoom = self.zoom_factor * step
        else:
            new_zoom = self.zoom_factor / step
        new_zoom = max(self.min_zoom, min(self.max_zoom, new_zoom))
        self._fit_mode = None
        if new_zoom != self.zoom_factor:
            factor = new_zoom / self.zoom_factor
            self.zoom_factor = new_zoom
            camera.anchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
            camera.scale(factor, factor)
            camera.anchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        event.accept()

    def zoom_in(self, camera):
        """Zoom in by one step."""
        new_zoom = min(self.zoom_factor * self.zoom_step, self.max_zoom)
        self._fit_mode = None
        if new_zoom != self.zoom_factor:
            self.zoom_factor = new_zoom
            camera.reset()
            camera.scale(self.zoom_factor, self.zoom_factor)

    def zoom_out(self, camera):
        """Zoom out by one step."""
        new_zoom = max(self.zoom_factor / self.zoom_step, self.min_zoom)
        self._fit_mode = None
        if new_zoom != self.zoom_factor:
            self.zoom_factor = new_zoom
            camera.reset()
            camera.scale(self.zoom_factor, self.zoom_factor)

    def fit_width(self, camera):
        self._fit_mode = 'width'
        self.zoom_factor = max(0.01, camera.viewport_size().width() / camera.scene_bounds().width() * 0.96)
        camera.reset()
        camera.scale(self.zoom_factor, self.zoom_factor)
        camera.center(camera.scene_bounds().center())

    def reset_zoom(self, camera):
        """Reset zoom to fit the full chart in the current viewport."""
        self._fit_mode = 'page'
        self.zoom_factor = self._compute_fit_zoom(camera)
        camera.reset()
        camera.scale(self.zoom_factor, self.zoom_factor)
        camera.center(SCENE_SIZE / 2, SCENE_SIZE / 2)

    @staticmethod
    def focus_index(count, current, forward, has_focus):
        if current is not None:
            target = current + (1 if forward else -1)
            return target if 0 <= target < count else None
        return (0 if forward else count-1) if count and has_focus else None

    @staticmethod
    def key_intent(key):
        return {Qt.Key.Key_Escape:'clear', Qt.Key.Key_Plus:'in',
                Qt.Key.Key_Equal:'in', Qt.Key.Key_Minus:'out', Qt.Key.Key_0:'reset'}.get(key)

    def double_click_intent(self, left_button, sector, hits):
        if not left_button:
            return None
        if sector is not None:
            self._is_dragging = False
            return PointerIntent('retinue', sector)
        for hit in hits:
            if hit.kind in ('planet', 'sign'):
                self._is_dragging = False
                return hit
        return None


@dataclass(frozen=True)
class PointerIntent:
    kind: str
    payload: tuple
