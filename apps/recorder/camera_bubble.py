# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Camera bubble (SPEC-REC-001 §4.6; desktop translation of
SPEC-RECCAM-MOBILE-001): your face in a round, always-on-top window that the
screen recording captures.

- Drag with the left button to move; mouse wheel to resize (88 px to 45 % of
  the screen's short side, the mobile bounds). Place and size are remembered.
- Circular ``setMask`` always: the X input shape is the circle too, so clicks
  beside it reach the app underneath (INV-5, review R1 F13); the white ring
  hides the mask's stair-step edge.
- Preview format closest to 640x480 at 30 fps or less; only the latest frame
  is painted. Never takes focus.
- The camera opens in ``start`` and closes in ``stop``; ``freeze`` closes the
  camera but keeps the last image on screen (mobile §5.5: the face stays in
  the last frames).
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPen, QRegion
from PySide6.QtWidgets import QWidget

MIN_DIAMETER = 88
DEFAULT_DIAMETER = 180
# The record dialog's Size choice (Lorris 2026-10-18: small stays the default,
# bigger on request); always clamped to 45 % of the screen's short side.
SIZES = {"small": 180, "medium": 260, "large": 360, "xlarge": 480}
WHEEL_STEP = 12
RING_PX = 2


MAX_FPS = 30
MIN_FRAME_MS = 1000 // MAX_FPS


def _pick_format(device):
    """The colour format closest to 640x480 that can run at <= 30 fps
    (formats whose slowest rate is above 30 are refused, review R2 F9)."""
    best, best_score = None, None
    for f in device.videoFormats():
        size = f.resolution()
        if size.width() < 160 or f.pixelFormat().name in ("Format_Y8", "Format_Y16"):
            continue
        if f.minFrameRate() > MAX_FPS + 0.5:
            continue
        score = abs(size.width() * size.height() - 640 * 480) + (100000 if f.maxFrameRate() < 15 else 0)
        if best_score is None or score < best_score:
            best, best_score = f, score
    return best


def default_camera():
    """The system default camera, else the first that offers colour formats."""
    from PySide6.QtMultimedia import QMediaDevices
    devices = QMediaDevices.videoInputs()
    default = QMediaDevices.defaultVideoInput()
    if not default.isNull() and _pick_format(default) is not None:
        return default
    for d in devices:
        if _pick_format(d) is not None:
            return d
    return None


def max_diameter(screen_rect: QRect) -> int:
    short = min(screen_rect.width(), screen_rect.height())
    return max(MIN_DIAMETER, min(int(0.45 * short), short - 32))


def clamp_diameter(d: int, screen_rect: QRect) -> int:
    return max(MIN_DIAMETER, min(int(d), max_diameter(screen_rect)))


def clamp_center(cx: int, cy: int, d: int, screen_rect: QRect) -> QPoint:
    r = d // 2
    x = max(screen_rect.left() + r, min(cx, screen_rect.right() - r))
    y = max(screen_rect.top() + r, min(cy, screen_rect.bottom() - r))
    return QPoint(x, y)


class CameraBubble(QWidget):
    moved = Signal(float, float, int)        # centre fractions of the screen, diameter
    failed = Signal(str)                     # reason text

    def __init__(self, device=None, mirror=True, ring=True, diameter=DEFAULT_DIAMETER):
        flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                 | Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus)
        super().__init__(None, flags)
        self.setObjectName("recorder_camera_bubble")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self._device = device
        self._mirror = mirror
        self._ring = ring
        self._image: Optional[QImage] = None
        self._drag: Optional[QPoint] = None
        self._camera = self._session = self._sink = None
        from PySide6.QtCore import QElapsedTimer
        self._since = QElapsedTimer()
        self._set_diameter(diameter)

    # ---------------------------------------------------------- geometry

    def _screen_rect(self) -> QRect:
        screen = self.screen() or QGuiApplication.primaryScreen()
        return screen.geometry() if screen else QRect(0, 0, 1920, 1080)

    def _set_diameter(self, d: int) -> None:
        d = clamp_diameter(d, self._screen_rect())
        centre = self.geometry().center() if self.isVisible() else None
        self.setFixedSize(d, d)
        self.setMask(QRegion(QRect(0, 0, d, d), QRegion.RegionType.Ellipse))
        if centre is not None:
            self.place_center(centre.x(), centre.y())
        self.update()

    def place_center(self, cx: int, cy: int) -> None:
        c = clamp_center(cx, cy, self.width(), self._screen_rect())
        self.move(c.x() - self.width() // 2, c.y() - self.height() // 2)

    def place_default(self, area: QRect) -> None:
        """Bottom right of the recorded area, 24 px in."""
        r = self.width() // 2
        self.place_center(area.right() - 24 - r, area.bottom() - 24 - r)

    def _emit_moved(self) -> None:
        s = self._screen_rect()
        c = self.geometry().center()
        self.moved.emit((c.x() - s.left()) / max(1, s.width()),
                        (c.y() - s.top()) / max(1, s.height()), self.width())

    # ---------------------------------------------------------- camera

    def start(self) -> bool:
        try:
            from PySide6.QtMultimedia import QCamera, QMediaCaptureSession, QVideoSink
        except ImportError:
            self.failed.emit("QtMultimedia is not available.")
            return False
        device = self._device or default_camera()
        if device is None:
            self.failed.emit("No camera found.")
            return False
        fmt = _pick_format(device)
        if fmt is None:                              # never an unchecked default (R3 F6)
            self.failed.emit("This camera offers no format at 30 frames a second or less.")
            return False
        self._camera = QCamera(device, self)
        self._camera.setCameraFormat(fmt)
        self._session = QMediaCaptureSession(self)
        self._sink = QVideoSink(self)
        self._session.setCamera(self._camera)
        self._session.setVideoSink(self._sink)
        self._sink.videoFrameChanged.connect(self._on_frame)
        self._camera.errorOccurred.connect(self._on_error)
        self._camera.start()
        self.show()
        self.raise_()
        return True

    def _on_frame(self, frame) -> None:
        if self._camera is None:
            return                                   # a late frame after freeze
        if self._since.isValid() and self._since.elapsed() < MIN_FRAME_MS:
            return                                   # at most 30 conversions a second
        self._since.restart()
        image = frame.toImage()
        if not image.isNull():
            self._image = image
            self.update()

    def _on_error(self, _error, text) -> None:
        self.failed.emit(text or "Camera stopped (error).")
        self.freeze()
        self.hide()

    def freeze(self) -> None:
        """Close the camera, keep the last image on screen."""
        cam, self._camera = self._camera, None
        if cam is not None:
            try:
                self._sink.videoFrameChanged.disconnect(self._on_frame)
            except (RuntimeError, TypeError):
                pass
            cam.stop()
            cam.deleteLater()

    def stop(self) -> None:
        self.freeze()
        self.hide()
        self._image = None

    # ---------------------------------------------------------- input

    def mousePressEvent(self, e):                       # noqa: N802 (Qt API)
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):                        # noqa: N802
        if self._drag is not None:
            top_left = e.globalPosition().toPoint() - self._drag
            self.place_center(top_left.x() + self.width() // 2, top_left.y() + self.height() // 2)

    def mouseReleaseEvent(self, _e):                    # noqa: N802
        if self._drag is not None:
            self._drag = None
            self._emit_moved()

    def wheelEvent(self, e):                            # noqa: N802
        step = WHEEL_STEP if e.angleDelta().y() > 0 else -WHEEL_STEP
        self._set_diameter(self.width() + step)
        self._emit_moved()

    # ---------------------------------------------------------- paint

    def paintEvent(self, _event):                       # noqa: N802
        d = self.width()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        clip = QPainterPath()
        clip.addEllipse(0, 0, d, d)
        p.setClipPath(clip)
        if self._image is not None:
            img = self._image
            side = min(img.width(), img.height())
            src = QRect((img.width() - side) // 2, (img.height() - side) // 2, side, side)
            if self._mirror:
                p.translate(d, 0)
                p.scale(-1, 1)
            p.drawImage(QRect(0, 0, d, d), img, src)
            p.resetTransform()
        else:
            p.fillRect(0, 0, d, d, QColor(0, 0, 0, 160))
        if self._ring:
            p.setClipping(False)
            p.setPen(QPen(QColor("white"), RING_PX * 2))
            p.drawEllipse(RING_PX, RING_PX, d - 2 * RING_PX, d - 2 * RING_PX)
