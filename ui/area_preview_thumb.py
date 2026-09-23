# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under the GNU AGPL-3.0. See LICENSE at the repository root.
"""Font-area preview thumbnail for the Settings -> Font Sizes page (td-to202).

Each font-size row shows a real-screen picture of the part of the app that row
changes, so the user directly SEES which region a setting drives instead of
reading a description. The pictures are captured once on the real screen by the
RELEASE5_AREA_THUMBS scenario and committed under ``img/settings_previews/``.

Design constraints (from the brief):
  * Thumbnail scaled to a fixed width (aspect preserved), with an upper bound on
    height so a tall control's picture cannot stretch the settings row.
  * Click opens a frameless popup with the full-size picture; close on click or
    Esc.
  * A MISSING picture is not an error: no thumbnail, no crash, and NO placeholder
    text ever reaches the screen (placeholder rule). The caller checks
    ``has_image`` and simply omits the widget.
  * Pixmaps carry no theme colour, so there is nothing to restyle on a theme
    change -- the widget is deliberately outside the themed-replay path.

Kept in its own module so ui/settings_tab.py does not grow (Rule 4 / the SI
architecture ratchet). Core and Pro both build FontSizesSection from
ui/settings_tab.py, so this single implementation serves both.
"""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout

# img/ is a sibling of ui/ at the repo root; resolve relative to this file so it
# works from the main checkout and from any worktree.
_PREVIEW_DIR = Path(__file__).resolve().parent.parent / "img" / "settings_previews"

# Reference-image width (px, DPR 1).  This is deliberately near the captures'
# natural width: thin tab/header strips became unreadable when compressed to the
# former 240px thumbnail.  The dedicated Screenshot column can scroll on narrow
# Settings windows, while the popup still shows the original pixels.
_THUMB_WIDTH = 520

# Upper bound on the displayed height. Most area pictures are wide (a strip of a
# tab bar, a table row), so width is the binding constraint and this never fires.
# A few areas drive a TALL control (the vertical sign-selector column), and a
# pure width-scale would blow that up into a very tall settings row; the box cap
# keeps aspect while bounding the row. A wide strip remains width-bound and a
# tall capture remains large enough to inspect without dominating the page.
_MAX_THUMB_HEIGHT = 300


def preview_path(area_id: str) -> Path:
    """Absolute path to the picture for ``area_id`` (may not exist)."""
    return _PREVIEW_DIR / f"{area_id}.png"


class _EnlargedPreviewPopup(QDialog):
    """Frameless, borderless full-size view of one area picture. Closes on any
    mouse click or Esc (QDialog maps Esc to reject by default)."""

    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setModal(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel(self)
        label.setPixmap(pixmap)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)

    def mouseReleaseEvent(self, event):  # noqa: N802 (Qt override)
        self.accept()
        super().mouseReleaseEvent(event)


class AreaPreviewThumb(QLabel):
    """Clickable thumbnail of the screen region a font area drives.

    Construct with the area id; if the committed picture is present the widget
    shows a width-scaled thumbnail and opens the full-size popup on click. If the
    picture is missing or unreadable, ``has_image`` is False and the widget shows
    nothing -- the caller should not add it to the layout.
    """

    def __init__(self, area_id: str, parent=None):
        super().__init__(parent)
        self._full_pixmap = None

        path = preview_path(area_id)
        pixmap = QPixmap(str(path)) if path.exists() else QPixmap()
        if pixmap.isNull():
            # No picture yet: render nothing, never a placeholder string.
            self.setVisible(False)
            return

        self._full_pixmap = pixmap
        # Scale into a (width x max-height) box, aspect preserved: wide pictures
        # fill the width exactly (the common case), a tall one is height-capped so
        # it cannot stretch the settings row.
        self.setPixmap(
            pixmap.scaled(
                _THUMB_WIDTH, _MAX_THUMB_HEIGHT,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Click to enlarge")

    @property
    def has_image(self) -> bool:
        return self._full_pixmap is not None

    def mouseReleaseEvent(self, event):  # noqa: N802 (Qt override)
        if self._full_pixmap is not None and event.button() == Qt.MouseButton.LeftButton:
            popup = _EnlargedPreviewPopup(self._full_pixmap, self)
            popup.exec()
        super().mouseReleaseEvent(event)
