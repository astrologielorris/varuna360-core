# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Settings > Voice Input (td-mgcw8, test stage; main and LTS since 2026-10-22).

Three blocks: the speech library (sherpa-onnx, shipped with the app), the
speech model (downloaded once from here, with progress and Cancel), and a
microphone test that records, transcribes on this computer and shows how long
it took. Nothing is stored in the settings file yet: the model's presence on
disk is the state. Downloads and transcription run off the GUI thread."""
from __future__ import annotations

import threading
import time

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (QComboBox, QGroupBox, QHBoxLayout, QLabel,
                               QPlainTextEdit, QProgressBar, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from core.voice_input import store
from core.voice_input.catalog import DEFAULT_MODEL
from ui.voice_dictation import Dictation, forget_transcriber, model_loaded
from ui.qt_theme import (get_group_box_style, get_primary_button_style,
                         get_secondary_button_style, get_theme_colors,
                         scaled_area_px)

class _InstallWorker(QThread):
    progressed = Signal(int, int)
    finished_ok = Signal()
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cancel_event = threading.Event()

    def run(self):
        try:
            store.install(DEFAULT_MODEL, progress=self.progressed.emit,
                          cancel=self.cancel_event)
        except store.InstallCancelled:
            self.cancelled.emit()
        except Exception as exc:  # shown to the user, never swallowed
            self.failed.emit(str(exc))
        else:
            self.finished_ok.emit()


class VoiceInputSection(QWidget):
    """The Voice Input page of the Settings tab (Core and Pro)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._install_worker = None
        self.dictation = Dictation(self)
        self.dictation.state_changed.connect(self._on_dictation_state)
        self.dictation.transcribed.connect(self._on_transcribed)
        self.dictation.failed.connect(self._on_dictation_failed)
        self._record_timer = QTimer(self)
        self._record_timer.setInterval(200)
        self._record_timer.timeout.connect(self._tick_recording)
        self._build_ui()
        self._refresh_status()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        self.title = QLabel("Voice Input")
        layout.addWidget(self.title)
        self.intro = QLabel(
            "Speak instead of typing. Your voice is turned into text on this "
            "computer: nothing is sent anywhere, no graphics card is needed, and "
            "it works with every AI model.")
        self.intro.setWordWrap(True)
        layout.addWidget(self.intro)

        # Speech library
        self.library_box = QGroupBox("Speech library")
        lib = QVBoxLayout(self.library_box)
        self.library_label = QLabel()
        self.library_label.setWordWrap(True)
        lib.addWidget(self.library_label)
        layout.addWidget(self.library_box)

        # Speech model
        self.model_box = QGroupBox("Speech model")
        mod = QVBoxLayout(self.model_box)
        self.model_name = QLabel(DEFAULT_MODEL.label)
        mod.addWidget(self.model_name)
        self.model_langs = QLabel(DEFAULT_MODEL.languages + ".")
        self.model_langs.setWordWrap(True)
        mod.addWidget(self.model_langs)
        self.model_status = QLabel()
        self.model_status.setWordWrap(True)
        mod.addWidget(self.model_status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(True)
        self.progress.hide()
        mod.addWidget(self.progress)
        row = QHBoxLayout()
        self.install_btn = QPushButton("Download and install")
        self.install_btn.clicked.connect(self._start_install)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._cancel_install)
        self.cancel_btn.hide()
        self.remove_btn = QPushButton("Remove model")
        self.remove_btn.clicked.connect(self._remove_model)
        row.addWidget(self.install_btn)
        row.addWidget(self.cancel_btn)
        row.addWidget(self.remove_btn)
        row.addStretch()
        mod.addLayout(row)
        self.folder_label = QLabel()
        self.folder_label.setWordWrap(True)
        self.folder_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        mod.addWidget(self.folder_label)
        layout.addWidget(self.model_box)

        # Microphone test
        self.test_box = QGroupBox("Try it")
        test = QVBoxLayout(self.test_box)
        mic_row = QHBoxLayout()
        self.mic_label = QLabel("Microphone")
        mic_row.addWidget(self.mic_label)
        self.mic_combo = QComboBox()
        mic_row.addWidget(self.mic_combo, 1)
        test.addLayout(mic_row)
        rec_row = QHBoxLayout()
        self.record_btn = QPushButton("Start recording")
        self.record_btn.clicked.connect(self._toggle_recording)
        self.record_label = QLabel()
        rec_row.addWidget(self.record_btn)
        rec_row.addWidget(self.record_label, 1)
        test.addLayout(rec_row)
        self.transcript = QPlainTextEdit()
        self.transcript.setPlaceholderText("What you say appears here.")
        self.transcript.setMinimumHeight(110)
        test.addWidget(self.transcript)
        self.timing_label = QLabel()
        self.timing_label.setWordWrap(True)
        test.addWidget(self.timing_label)
        layout.addWidget(self.test_box)
        layout.addStretch()

        self._fill_microphones()
        self.refresh_theme()

    def refresh_theme(self):
        theme = get_theme_colors()
        self.setStyleSheet(
            f"VoiceInputSection, QScrollArea, QScrollArea > QWidget > QWidget "
            f"{{ background-color: {theme['secondary_dark']}; }}")
        self.title.setStyleSheet(
            f"font-size: {scaled_area_px('panel_titles')}px; font-weight: bold;")
        for box in (self.library_box, self.model_box, self.test_box):
            box.setStyleSheet(get_group_box_style())
        self.install_btn.setStyleSheet(get_primary_button_style())
        self.record_btn.setStyleSheet(get_primary_button_style())
        for btn in (self.cancel_btn, self.remove_btn):
            btn.setStyleSheet(get_secondary_button_style())
        text = f"color: {theme['primary_text']};"
        for label in (self.title, self.library_label, self.model_name,
                      self.model_status, self.mic_label, self.record_label):
            label.setStyleSheet(label.styleSheet() + text if label is self.title else text)
        muted = f"color: {theme['secondary_text']};"
        for label in (self.intro, self.model_langs, self.folder_label, self.timing_label):
            label.setStyleSheet(muted)

    def _fill_microphones(self):
        from PySide6.QtMultimedia import QMediaDevices
        current = self.mic_combo.currentData()
        keep = current.id() if current is not None else None
        self.mic_combo.clear()
        default = QMediaDevices.defaultAudioInput()
        for device in QMediaDevices.audioInputs():
            name = device.description()
            if device.id() == default.id():
                name += " (default)"
            self.mic_combo.addItem(name, device)
            if device.id() == (keep if keep is not None else default.id()):
                self.mic_combo.setCurrentIndex(self.mic_combo.count() - 1)
        if self.mic_combo.count() == 0:
            self.mic_combo.addItem("No microphone found", None)

    # -------------------------------------------------------------- status
    def _refresh_status(self):
        version = store.library_version()
        installed = store.is_installed(DEFAULT_MODEL)
        busy = self._install_worker is not None
        if version:
            self.library_label.setText(f"sherpa-onnx {version} is ready.")
        else:
            self.library_label.setText(
                "The speech library (sherpa-onnx) is not installed in this copy "
                "of the app, so voice input cannot run yet.")
        size_mb = DEFAULT_MODEL.archive_bytes / 1e6
        if busy:
            pass
        elif installed:
            self.model_status.setText("Installed.")
        else:
            self.model_status.setText(
                f"Not installed. The download is {size_mb:.0f} MB, done once.")
        self.install_btn.setVisible(not installed and not busy)
        self.install_btn.setEnabled(not busy)
        self.remove_btn.setVisible(installed and not busy)
        self.folder_label.setText(f"Folder: {store.model_path(DEFAULT_MODEL)}")
        ready = bool(version) and installed and not busy
        state = self.dictation.state
        self.record_btn.setEnabled(
            (ready and self.mic_combo.currentData() is not None and state == "idle")
            or state == "recording")
        if state == "idle":
            self.record_label.setText(
                "" if ready else
                "Install the speech model above to try it." if version
                else "Needs the speech library.")

    # ------------------------------------------------------------- install
    def _start_install(self):
        if self._install_worker is not None:
            return
        worker = _InstallWorker(self)
        worker.progressed.connect(self._on_progress)
        worker.finished_ok.connect(lambda: self._install_ended("Installed."))
        worker.failed.connect(lambda msg: self._install_ended(msg))
        worker.cancelled.connect(lambda: self._install_ended("Download cancelled."))
        self._install_worker = worker
        self.progress.setValue(0)
        self.progress.setFormat("Starting download...")
        self.progress.show()
        self.cancel_btn.show()
        self.cancel_btn.setEnabled(True)
        self.model_status.setText("Downloading...")
        self._refresh_status()
        worker.start()

    def _on_progress(self, done, total):
        self.progress.setValue(int(1000 * done / total) if total else 0)
        self.progress.setFormat(f"{done / 1e6:.0f} of {total / 1e6:.0f} MB")
        if done >= total:
            self.progress.setFormat("Unpacking...")
            self.cancel_btn.setEnabled(False)

    def _cancel_install(self):
        if self._install_worker is not None:
            self._install_worker.cancel_event.set()
            self.cancel_btn.setEnabled(False)
            self.progress.setFormat("Cancelling...")

    def _install_ended(self, message):
        worker, self._install_worker = self._install_worker, None
        if worker is not None:
            worker.wait(5000)
            worker.deleteLater()
        self.progress.hide()
        self.cancel_btn.hide()
        forget_transcriber()
        self._refresh_status()
        self.model_status.setText(message)

    def _remove_model(self):
        forget_transcriber()
        try:
            store.remove(DEFAULT_MODEL)
        except OSError as exc:
            self._refresh_status()
            self.model_status.setText(f"Could not remove the model: {exc}")
            return
        self._refresh_status()

    # ----------------------------------------------------------- recording
    def _toggle_recording(self):
        if self.dictation.state == "idle":
            self.timing_label.setText("")
        self.dictation.toggle(self.mic_combo.currentData())

    def _on_dictation_state(self, state):
        if state == "recording":
            self.record_btn.setText("Stop and transcribe")
            self._record_timer.start()
            self._tick_recording()
        else:
            self._record_timer.stop()
            self.record_btn.setText("Start recording")
            self._refresh_status()
            if state == "transcribing":
                self.record_label.setText(
                    "Transcribing..." if model_loaded()
                    else "Loading the model, then transcribing...")

    def _tick_recording(self):
        seconds = time.perf_counter() - self.dictation.started_at
        self.record_label.setText(f"Recording... {seconds:.0f} s")

    def _on_transcribed(self, text, audio_s, compute_s, load_s):
        self.transcript.setPlainText(text)
        line = (f"{audio_s:.1f} s of speech transcribed in {compute_s:.2f} s "
                f"on the processor")
        if load_s > 0.5:
            line += f" (the model took {load_s:.1f} s to load, only the first time)"
        self.timing_label.setText(line + ".")

    def _on_dictation_failed(self, message):
        self._refresh_status()
        self.record_label.setText(message)

    def hideEvent(self, event):
        self.dictation.cancel()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if self.dictation.state == "idle":
            self._fill_microphones()
        self._refresh_status()
