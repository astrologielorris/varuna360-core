# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Dictation shared by every box that takes a typed request (td-mgcw8, main
only): the AI task window, the AI setting panel, the AI search sheet and the
Settings > Voice Input test.

``Dictation`` records from a microphone (QtMultimedia), converts to 16 kHz
mono and transcribes on a worker thread with the one loaded model of the
process. ``MicButton`` puts it beside a QLineEdit or QPlainTextEdit: click to
record, click again and the words land at the cursor. Only one box records at
a time (one microphone)."""
from __future__ import annotations

import threading
import time
import weakref
from typing import Optional

import numpy as np
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QLineEdit, QPlainTextEdit, QToolButton, QToolTip

from core.voice_input import store
from core.voice_input.catalog import DEFAULT_MODEL
from core.voice_input.engine import SAMPLE_RATE

NOT_READY_TEXT = ("Voice input is not set up yet. Open Settings > Voice Input "
                  "to install it.")
BUSY_TEXT = "Another box is already listening. Stop it first."
SHORT_TEXT = "Too short, nothing was heard."
RECORDING_RED = "#E53935"   # semantic red (Rule 20 exception)

_transcriber = None
_transcriber_lock = threading.Lock()
# One native recognizer per process; its decoding is not shown to be
# reentrant, so two boxes never run it at the same time (review F3).
_infer_lock = threading.Lock()
# The box that holds the microphone, weakly: a box destroyed while recording
# must not keep every other microphone busy (review F2).
_active_ref: Optional[weakref.ref] = None
# Running transcriptions are owned here, not by the box: a box closed while
# its words are being written must not destroy a running QThread (review F1).
_workers: set = set()
_quit_hooked = False


def _active() -> Optional["Dictation"]:
    import shiboken6
    owner = _active_ref() if _active_ref is not None else None
    if owner is None or not shiboken6.isValid(owner) or owner.state != "recording":
        return None
    return owner


def _set_active(owner: Optional["Dictation"]) -> None:
    global _active_ref
    _active_ref = weakref.ref(owner) if owner is not None else None


def _wait_workers_at_quit():
    for worker in list(_workers):
        worker.wait(10000)


def is_ready() -> bool:
    """The library imports and the model is on disk."""
    return store.library_version() is not None and store.is_installed(DEFAULT_MODEL)


def model_loaded() -> bool:
    return _transcriber is not None


def get_transcriber():
    """One loaded model per process; loading takes a few seconds."""
    global _transcriber
    with _transcriber_lock:
        if _transcriber is None:
            from core.voice_input.engine import Transcriber
            _transcriber = Transcriber(DEFAULT_MODEL)
        return _transcriber


def forget_transcriber():
    global _transcriber
    with _transcriber_lock:
        _transcriber = None


def to_mono_16k(raw: bytes, fmt) -> np.ndarray:
    """Recorded bytes in the device's format -> float32 mono at 16 kHz."""
    from PySide6.QtMultimedia import QAudioFormat
    kind = fmt.sampleFormat()
    if kind == QAudioFormat.SampleFormat.Int16:
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif kind == QAudioFormat.SampleFormat.Int32:
        data = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    elif kind == QAudioFormat.SampleFormat.Float:
        data = np.frombuffer(raw, dtype=np.float32).copy()
    else:  # UInt8
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    channels = max(1, fmt.channelCount())
    if channels > 1:
        data = data[: len(data) - len(data) % channels].reshape(-1, channels).mean(axis=1)
    rate = fmt.sampleRate()
    if rate != SAMPLE_RATE and len(data):
        count = int(round(len(data) * SAMPLE_RATE / rate))
        data = np.interp(np.linspace(0, len(data) - 1, count),
                         np.arange(len(data)), data).astype(np.float32)
    return data.astype(np.float32)


class _TranscribeWorker(QThread):
    # generation, text, audio s, compute s, load s
    done = Signal(int, str, float, float, float)
    failed = Signal(int, str)

    def __init__(self, samples, generation, parent=None):
        super().__init__(parent)
        self._samples = samples
        self._generation = generation

    def run(self):
        try:
            started = time.perf_counter()
            transcriber = get_transcriber()
            load = time.perf_counter() - started
            with _infer_lock:
                result = transcriber.transcribe(self._samples, SAMPLE_RATE)
        except Exception as exc:  # shown to the user, never swallowed
            self.failed.emit(self._generation, str(exc))
        else:
            self.done.emit(self._generation, result.text, result.audio_seconds,
                           result.compute_seconds, load)


class Dictation(QObject):
    """One box's microphone. States: idle, recording, transcribing."""
    state_changed = Signal(str)
    transcribed = Signal(str, float, float, float)   # text, audio s, compute s, load s
    failed = Signal(str)                             # a sentence for the user

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = "idle"
        self._source = None
        self._buffer = None
        self._format = None
        self._generation = 0
        self.started_at = 0.0

    def toggle(self, device=None):
        if self.state == "recording":
            self.stop()
        elif self.state == "idle":
            self.start(device)

    def start(self, device=None) -> bool:
        if self.state != "idle":
            return False
        if not is_ready():
            self.failed.emit(NOT_READY_TEXT)
            return False
        holder = _active()
        if holder is not None and holder is not self:
            self.failed.emit(BUSY_TEXT)
            return False
        from PySide6.QtMultimedia import QAudioFormat, QAudioSource, QMediaDevices
        if device is None:
            device = QMediaDevices.defaultAudioInput()
        if device is None or device.isNull():
            self.failed.emit("No microphone found.")
            return False
        fmt = QAudioFormat()
        fmt.setSampleRate(SAMPLE_RATE)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if not device.isFormatSupported(fmt):
            fmt = device.preferredFormat()
        self._format = fmt
        self._buffer = QBuffer(self)
        self._buffer.open(QIODevice.ReadWrite)
        self._source = QAudioSource(device, fmt, self)
        self._source.start(self._buffer)
        self.started_at = time.perf_counter()
        _set_active(self)
        self._set_state("recording")
        return True

    def stop(self):
        """Stop recording and transcribe what was heard."""
        if self.state != "recording":
            return
        samples = self._end_recording()
        if len(samples) < SAMPLE_RATE // 2:
            self._set_state("idle")
            self.failed.emit(SHORT_TEXT)
            return
        global _quit_hooked
        self._set_state("transcribing")
        self._generation += 1
        generation = self._generation
        worker = _TranscribeWorker(samples, generation)   # no parent: see _workers
        # Bound methods of this QObject: delivered on its (GUI) thread, and
        # dropped by Qt if the box is destroyed first.
        worker.done.connect(self._on_done)
        worker.failed.connect(self._on_failed)
        _workers.add(worker)
        worker.finished.connect(worker.deleteLater)
        worker.destroyed.connect(lambda *_a, w=worker: _workers.discard(w))
        if not _quit_hooked:
            from PySide6.QtCore import QCoreApplication
            app = QCoreApplication.instance()
            if app is not None:
                app.aboutToQuit.connect(_wait_workers_at_quit)
                _quit_hooked = True
        worker.start()

    def cancel(self):
        """The box is closing: drop a recording, and ignore the words of a
        transcription still running (it finishes on its own)."""
        if self.state == "recording":
            self._end_recording()
            self._set_state("idle")
        elif self.state == "transcribing":
            self._generation += 1
            self._set_state("idle")

    def _end_recording(self) -> np.ndarray:
        source, self._source = self._source, None
        source.stop()
        raw = bytes(self._buffer.data())
        self._buffer.close()
        source.deleteLater()
        self._buffer.deleteLater()
        self._buffer = None
        if _active_ref is not None and _active_ref() is self:
            _set_active(None)
        return to_mono_16k(raw, self._format)

    def _current(self, generation) -> bool:
        import shiboken6
        return shiboken6.isValid(self) and generation == self._generation

    def _on_done(self, generation, text, audio_s, compute_s, load_s):
        if not self._current(generation):
            return
        self._set_state("idle")
        if text:
            self.transcribed.emit(text, audio_s, compute_s, load_s)
        else:
            self.failed.emit("Nothing was recognised.")

    def _on_failed(self, generation, message):
        if not self._current(generation):
            return
        self._set_state("idle")
        self.failed.emit(f"Transcription failed: {message}")

    def _set_state(self, state):
        self.state = state
        self.state_changed.emit(state)


def insert_dictated(target, text: str) -> None:
    """Put ``text`` at the cursor of a QLineEdit or QPlainTextEdit, with a
    space before it when it would otherwise touch the previous word."""
    if not text:
        return
    if isinstance(target, QLineEdit):
        start = (target.selectionStart() if target.hasSelectedText()
                 else target.cursorPosition())
        before = target.text()[:start]
        target.insert((" " if before and not before[-1].isspace() else "") + text)
    elif isinstance(target, QPlainTextEdit):
        cursor = target.textCursor()
        doc = target.toPlainText()
        before = doc[: cursor.selectionStart()]
        cursor.insertText((" " if before and not before[-1].isspace() else "") + text)
        target.setTextCursor(cursor)
    target.setFocus()


_MIC_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
    'stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
    '<rect x="9" y="3" width="6" height="11" rx="3" fill="{f}"/>'
    '<path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21M8.5 21h7"/></svg>')


def mic_icon(color: str, filled: bool = False, size: int = 18) -> QIcon:
    from PySide6.QtSvg import QSvgRenderer
    svg = _MIC_SVG.format(c=color, f=color if filled else "none")
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


class MicButton(QToolButton):
    """A microphone beside a text box. Click: listen; click again: the words
    go in at the cursor. Shows how to set it up when it is not installed."""

    def __init__(self, target, parent=None):
        super().__init__(parent)
        self._target = target
        self.dictation = Dictation(self)
        self.dictation.state_changed.connect(self._render)
        self.dictation.transcribed.connect(self._on_text)
        self.dictation.failed.connect(self._say)
        self.setObjectName("voice_mic_button")
        self.setCursor(Qt.PointingHandCursor)
        self.setAutoRaise(True)
        self.setIconSize(QSize(18, 18))
        self.clicked.connect(lambda: self.dictation.toggle())
        self._pulse = QTimer(self)
        self._pulse.setInterval(500)
        self._pulse.timeout.connect(self._blink)
        self._lit = False
        self._render("idle")

    def _color(self) -> str:
        from ui.qt_theme import get_theme_colors
        return get_theme_colors()["primary_text"]

    def _render(self, state):
        if state == "recording":
            self._lit = True
            self.setIcon(mic_icon(RECORDING_RED, filled=True))
            self.setToolTip("Listening. Click again to stop and write what you said.")
            self._pulse.start()
        elif state == "transcribing":
            self._pulse.stop()
            self.setIcon(mic_icon(RECORDING_RED))
            self.setToolTip("Writing what you said...")
        else:
            self._pulse.stop()
            self.setIcon(mic_icon(self._color()))
            self.setToolTip("Speak instead of typing (Voice Input)")
        self.setEnabled(state != "transcribing")

    def _blink(self):
        self._lit = not self._lit
        self.setIcon(mic_icon(RECORDING_RED, filled=self._lit))

    def refresh_theme(self):
        self._render(self.dictation.state)

    # Never smaller than its icon: an inherited stylesheet (the AI setting
    # panel's frame style under qt-material) gave the button a 3 px tall
    # size hint, so the microphone vanished from that row.
    _MIN_SIDE = 28

    def sizeHint(self):
        hint = super().sizeHint()
        return hint.expandedTo(QSize(self._MIN_SIDE, self._MIN_SIDE))

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        return hint.expandedTo(QSize(self._MIN_SIDE, self._MIN_SIDE))

    def _on_text(self, text, *_timing):
        insert_dictated(self._target, text)

    def _say(self, message):
        QToolTip.showText(self.mapToGlobal(self.rect().bottomLeft()), message, self)

    def hideEvent(self, event):
        self.dictation.cancel()
        super().hideEvent(event)
