# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under the GNU AGPL-3.0. See LICENSE at the repository root.
"""Glue controller: paste a chart image into the New & Edit token bar.

Owns everything the token bar's own diff must NOT contain (shared-file
coordination): the capability probe, the off-thread worker and its safe lifetime,
payload validation, and non-blocking notices. The token bar side is only a
base-class swap plus mounting the sparkle toggle and constructing this
controller.

Nothing here imports the paid edition: the extractor arrives as a plain callable
from ``ChartGUI.ai_image_extractor()`` (which returns ``None`` outside the paid
edition), so this widget ships in every edition. On a single paste it fills the
bar with exactly the FIRST detected chart (multi-chart is a separate task,
td-9rse); the branch point is ``_on_done``.
"""

import html
import traceback

from PySide6.QtCore import QObject, QPoint
from PySide6.QtWidgets import QToolTip, QApplication

from ui.image_extraction_worker import ImageExtractionWorker
from ui.add_chart_dialog_qt import (
    render_extraction_line, strict_ambiguous, strict_confidence,
    REVIEW_AUTO_CONFIRM_CONFIDENCE_THRESHOLD,
)


_UNSET = object()

# Unparented workers are kept alive here until ``QThread.finished`` so a bar
# destroyed mid-extraction never deletes a running QThread (which aborts the
# process with "QThread: Destroyed while thread is still running"). Review
# finding R1: parent-chain teardown of a live thread is unsafe.
_LIVE_WORKERS = set()
_DRAIN_INSTALLED = False


def _install_exit_drain():
    """Once per process, wait (bounded) on any still-running registered worker
    at application quit, so a slow/hung provider does not leave a live QThread to
    be destroyed during interpreter teardown (review finding R1 / exit path)."""
    global _DRAIN_INSTALLED
    if _DRAIN_INSTALLED:
        return
    app = QApplication.instance()
    if app is None:
        return
    app.aboutToQuit.connect(_drain_live_workers)
    _DRAIN_INSTALLED = True


def _drain_live_workers():
    for worker in list(_LIVE_WORKERS):
        try:
            if worker.isRunning():
                worker.requestInterruption()
                worker.wait(2000)   # bounded; best effort for a hung provider
        except Exception:
            pass


class TokenBarImagePaste(QObject):
    """Wires a token bar's ``image_pasted`` signal to the shared image
    extractor and drops the first detected chart into the bar as a parseable
    line. Non-blocking throughout; never a modal.
    """

    def __init__(self, bar, line_edit, toggle, extractor_provider,
                 notify=None, parent=None):
        """Args:
            bar: the token bar; only ``set_line(str)`` is used (duck-typed).
            line_edit: source of ``image_pasted(bytes, media_type)``.
            toggle: the sparkle AiToggleButton (enabled/disabled by capability),
                or None.
            extractor_provider: a zero-arg callable returning the image
                extractor callable, or None outside the paid edition. Probed
                LAZILY at paste time (bound ``ChartGUI.ai_image_extractor``), so
                a Lite/Pro decision is always current.
            notify: optional callable(str) for a non-blocking inline notice;
                when None, a QToolTip anchored on the line edit is used.
        """
        super().__init__(parent if parent is not None else bar)
        self._bar = bar
        self._line_edit = line_edit
        self._toggle = toggle
        self._extractor_provider = extractor_provider
        self._notify = notify
        self._active_worker = None
        # Remember the toggle's own tooltip so capability changes can restore it
        # instead of leaving the transient "Pro-only" text behind.
        self._toggle_default_tip = toggle.toolTip() if toggle is not None else ""
        line_edit.image_pasted.connect(self._on_image_pasted)
        self._apply_capability()

    # -- capability probe ---------------------------------------------------

    def _extractor(self):
        """Resolve the current extractor callable, or None. Never raises."""
        provider = self._extractor_provider
        if provider is None:
            return None
        try:
            return provider()
        except Exception:
            return None

    def _apply_capability(self, extractor=_UNSET):
        """Enable the toggle only when an extractor is available; otherwise
        disable it and mark it Pro-only. Re-run on each paste so a capability
        that appears later (Pro loaded after boot) unlocks the toggle."""
        if self._toggle is None:
            return
        if extractor is _UNSET:
            extractor = self._extractor()
        if extractor is not None:
            self._toggle.setEnabled(True)
            self._toggle.setToolTip(self._toggle_default_tip)
        else:
            self._toggle.setEnabled(False)
            self._toggle.setToolTip("Chart image reading is a Pro-only feature")

    # -- paste --------------------------------------------------------------

    def _on_image_pasted(self, data, media_type):
        extractor = self._extractor()
        self._apply_capability(extractor)   # refresh toggle state on each paste
        if extractor is None:
            self._show("Chart image reading is a Pro-only feature")
            return
        if self._toggle is not None and not self._toggle.isChecked():
            self._show("AI reading is off. Click the sparkle button to enable it.")
            return
        # A worker is active from start() until its OWN finished slot clears it;
        # isRunning() can already be False between run() returning and the queued
        # finished slot, so gate on identity, not isRunning (single-flight race).
        if self._active_worker is not None:
            self._show("Still reading the previous image")
            return
        _install_exit_drain()
        worker = ImageExtractionWorker(extractor, data, media_type)  # UNPARENTED
        self._active_worker = worker
        _LIVE_WORKERS.add(worker)
        worker.finished_with.connect(self._on_done)
        # Native finished -> deleteLater (not a lambda); registry drop and busy
        # clear are separate, each bound to this worker's identity.
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(lambda w=worker: _LIVE_WORKERS.discard(w))
        worker.finished.connect(lambda w=worker: self._clear_busy(w))
        self._set_busy()
        worker.start()

    def _set_busy(self):
        if self._toggle is not None:
            self._toggle.setEnabled(False)
        self._show("Reading the chart image...")

    def _clear_busy(self, worker):
        # Only the worker that is currently active may clear the busy state; a
        # stale worker's late finished slot must not re-enable the toggle while a
        # newer extraction is running.
        if self._active_worker is not worker:
            return
        self._active_worker = None
        self._apply_capability()

    # -- result -------------------------------------------------------------

    def _on_done(self, payload):
        """Consume exactly the first chart. Every failure mode notifies and
        leaves the bar untouched; only a clean, dated, non-empty rendered line
        reaches ``set_line`` (review finding R4)."""
        if not isinstance(payload, dict):
            self._show("Could not read the image")
            return
        # provider_unavailable results are ALSO ok=False, so check it FIRST
        # (review finding R7) or the specific message never runs.
        if payload.get("provider_unavailable"):
            self._show("AI provider unavailable. Check the AI settings.")
            return
        if not payload.get("ok"):
            self._show(payload.get("error") or "Could not read the image")
            return
        charts = payload.get("charts")
        if not isinstance(charts, list) or not charts:
            self._show("No chart was found in the image")
            return
        chart = charts[0]
        if not isinstance(chart, dict):
            self._show("The reading could not be understood")
            return
        # A dateless chart renders a positional line that the parser mis-maps
        # (place lands in the date slot). Require a date before filling.
        if not str(chart.get("date") or "").strip():
            self._show("No date could be read from the image")
            return
        try:
            line = render_extraction_line(chart)
        except Exception:
            line = ""
        if not line.strip():
            self._show("The reading could not be understood")
            return
        try:
            self._bar.set_line(line)
        except Exception:
            traceback.print_exc()   # log, do not swallow silently
            return
        notes = []
        if len(charts) > 1:
            # Multi-chart handling is td-9rse; for now use the first and say so.
            notes.append("%d charts detected. Using the first one." % len(charts))
        # Low-confidence / ambiguous reading: fill best-effort, but warn. Same
        # gate Add Chart uses (>= 0.85 to trust); anything less is uncertain.
        confidence = strict_confidence(payload.get("confidence"))
        if strict_ambiguous(payload) or confidence < REVIEW_AUTO_CONFIRM_CONFIDENCE_THRESHOLD:
            notes.append("Low-confidence reading. Check every field.")
        if notes:
            self._show(" ".join(notes))

    # -- non-blocking notice ------------------------------------------------

    def _show(self, message):
        """Show a non-blocking notice: the bar's own inline notice if one was
        supplied, else a transient QToolTip on the line edit. Never a modal."""
        if self._notify is not None:
            try:
                self._notify(message)
                return
            except Exception:
                pass
        # HTML-escape: the text can be LLM/paste-derived and QToolTip renders
        # rich text (review finding R8).
        try:
            QToolTip.showText(
                self._line_edit.mapToGlobal(
                    QPoint(0, self._line_edit.height())),
                html.escape(str(message)), self._line_edit)
        except Exception:
            pass
