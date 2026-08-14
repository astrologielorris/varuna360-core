# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under the GNU AGPL-3.0. See LICENSE at the repository root.
"""Off-GUI-thread image-extraction worker, shared across paste consumers.

Runs an injected ``extractor(bytes, media_type) -> dict`` OFF the GUI thread so a
multi-second vision/network call never freezes the UI. It emits a plain dict
result, never an edition-specific type, and never references the paid edition:
the extractor is supplied by the host (``ChartGUI.ai_image_extractor()``), which
returns ``None`` outside the paid edition. So this widget ships everywhere.

Lifetime is the CALLER's responsibility. Construct the worker UNPARENTED and keep
it alive in a registry until ``QThread.finished``, rather than parenting it to a
widget that may be destroyed mid-run: destroying a live ``QThread`` aborts the
process with "QThread: Destroyed while thread is still running". The Add Chart
dialog and the token-bar paste controller both follow that rule.

Extracted from the Add Chart dialog's private worker so both consumers run the
extractor identically; the dialog keeps a back-compat alias to the old name.
"""

from PySide6.QtCore import QThread, Signal


class ImageExtractionWorker(QThread):
    """Run the injected extractor off the GUI thread; emit a plain dict.

    The result dict follows the extractor's contract (``ok`` / ``error`` /
    ``charts`` / ...). ``run`` never raises: any exception from the extractor is
    turned into an ``{"ok": False, "error": ...}`` dict so the failure reaches
    the UI legibly instead of dying on the worker thread.
    """

    finished_with = Signal(dict)

    def __init__(self, extractor, data: bytes, media_type: str):
        # Deliberately UNPARENTED (no parent argument): the caller keeps the
        # worker alive in a registry until QThread.finished. Parenting a live
        # thread to a widget that may be destroyed mid-run aborts the process.
        super().__init__()
        self._extractor = extractor
        self._data = data
        self._media_type = media_type

    def run(self):
        try:
            result = self._extractor(self._data, self._media_type)
            if not isinstance(result, dict):
                result = {"ok": False,
                          "error": "extractor returned an unexpected result"}
        except Exception as exc:  # noqa: BLE001 - must reach the UI legibly
            result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        self.finished_with.emit(result)
