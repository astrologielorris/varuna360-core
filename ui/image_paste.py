# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under the GNU AGPL-3.0. See LICENSE at the repository root.
"""Clipboard/drag-drop image extraction shared by every paste surface.

Two widgets accept a pasted chart screenshot:

* Pro's Transit reading-date field (``pro/widgets/reading_date_field.py``)
* the Add Chart dialog's birth-line input (``ui/add_chart_dialog_qt.py``)

The Qt side of "is there an image on this clipboard, and what are its bytes"
is identical for both and carries real platform subtleties (raw image payload
vs local file urls, the ``application/x-qt-image`` fallback), so it lives here
once instead of being copied per widget.

This module is CORE (no ``pro`` imports): the Add Chart dialog ships in every
edition. Whether the AI actually runs on the pasted bytes is a separate,
Pro-gated decision made by the caller — see ``ChartGUI.ai_image_extractor``.
"""

import os

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QImage

# File-extension -> MIME media type for dropped/pasted image FILES.
EXT_MEDIA_TYPE = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}


def qimage_to_png_bytes(image: QImage) -> bytes:
    """Serialize a QImage to PNG bytes (in-memory, no temp file)."""
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    image.save(buf, "PNG")
    buf.close()
    return bytes(ba)


def extract_image(mime) -> "tuple | None":
    """Return ``(bytes, media_type)`` if ``mime`` carries an image, else None.

    Order: raw image payload first (a screenshot pasted from the clipboard
    arrives as ``hasImage``), then local image FILE urls (drag-drop from a file
    manager). A url that is not a readable local image is ignored so a plain
    web/text url still falls through to normal text handling.
    """
    if mime is None:
        return None

    if mime.hasImage():
        img = mime.imageData()
        if isinstance(img, QImage) and not img.isNull():
            return qimage_to_png_bytes(img), "image/png"
        # Some platforms deliver the image only via the QImage-constructible
        # "application/x-qt-image" payload; QImage() from the QVariant covers it.
        img2 = QImage(img) if img is not None else QImage()
        if not img2.isNull():
            return qimage_to_png_bytes(img2), "image/png"

    if mime.hasUrls():
        for url in mime.urls():
            if not url.isLocalFile():
                continue
            path = url.toLocalFile()
            ext = os.path.splitext(path)[1].lower()
            media_type = EXT_MEDIA_TYPE.get(ext)
            if media_type and os.path.isfile(path):
                try:
                    with open(path, "rb") as fh:
                        return fh.read(), media_type
                except OSError:
                    return None
    return None
