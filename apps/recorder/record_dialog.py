# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The record dialog (SPEC-REC-001 §4.1): every choice for the next take,
pre-filled from the last one; the last result with Open folder; the live
MB-per-minute estimate. Words are a draft for Lorris's review."""
from __future__ import annotations

import os
from dataclasses import dataclass, fields
from typing import List, Optional

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QLabel, QPushButton, QRadioButton,
                               QSpinBox, QVBoxLayout, QWidget)

from core.recorder import audio_devices, macos, output, presets

# Draft wording (orchestrator draft, for Lorris's review).
TEXT = {
    "title": "Record the screen",
    "last_saved": "Last recording: {name} · {size}",
    "last_failed": "Last recording failed: {message}",
    "kept": "What was recorded is kept: {name} · {size}",
    "open_folder": "Open folder",
    "what": "What to record",
    "window": "Varuna360 window (its place on screen when you press Start)",
    "screen": "Whole screen",
    "rect": "Draw a rectangle",
    "sound": "Sound",
    "mic": "Microphone",
    "computer": "Computer sound (what the speakers play)",
    "computer_windows_na": ("Windows records computer sound through a \"Stereo Mix\" device: "
                            "turn it on in Sound settings > Recording, then open this window again."),
    "quality": "Quality",
    "format": "Format",
    "estimate": "Up to about {mb} MB per minute (less while the screen is still)",
    "camera": "Camera",
    "camera_box": "My face in a round bubble",
    "camera_size_tip": "Size of the bubble; during the take, the mouse wheel over it resizes it too",
    "camera_sizes": {"small": "Small", "medium": "Medium", "large": "Large", "xlarge": "Extra large"},
    "privacy": "Privacy",
    "blur": "Blur the chart names in the memory panel (in the video only)",
    "blur_title": "Blur the chart name in the title (in the video only)",
    "notif": "Hide desktop notifications",
    "notif_na": "Hide desktop notifications (not available on this desktop)",
    "blur_na": ("This ffmpeg cannot blur in the video (it has no zmq filter), so the blur options "
                "are off. Install the full ffmpeg build to turn them on: on Windows, "
                "winget install Gyan.FFmpeg, or download the full build."),
    "blur_get": "Get the full ffmpeg…",
    "cursor": "Cursor",
    "highlight": "Highlight",
    "opacity": "opacity",
    "save_to": "Save to",
    "change": "Change…",
    "start": "Start",
    "no_tray": "No tray icon here: stop with the same shortcut.",
    "device_gone": "{what} “{old}” is not connected: using {new} instead.",
    "colours": {"red": "Red", "rose": "Rose", "orange": "Orange", "yellow": "Yellow",
                "blue": "Blue", "green": "Green"},
    "sizes": {"S": "Small", "M": "Medium", "L": "Large"},
    "shapes": {"disc_ring": "Disc and ring", "disc": "Disc", "ring": "Ring"},
}


@dataclass
class RecordChoices:
    region: str = "window"
    screen: str = ""
    mic_enabled: bool = True
    mic_device: str = ""
    computer_enabled: bool = False
    computer_device: str = ""
    preset: str = presets.DEFAULT_PRESET
    fps: int = 30
    format: str = presets.DEFAULT_FORMAT
    camera_enabled: bool = False
    camera_device: str = ""
    camera_size: str = "small"
    blur_memory: bool = True
    blur_title: bool = True
    hide_notifications: bool = True
    highlight_enabled: bool = True
    highlight_color: str = "red"
    highlight_opacity: int = 50
    highlight_size: str = "M"
    highlight_shape: str = "disc_ring"
    highlight_always: bool = False
    folder: str = ""

    @classmethod
    def load(cls, settings) -> "RecordChoices":
        from core.settings_registry import default as reg_default
        values = {}
        for f in fields(cls):
            key = "recorder." + f.name
            value = settings.get(key, reg_default(key))
            values[f.name] = value if isinstance(value, type(getattr(cls, f.name))) else reg_default(key)
        return cls(**values)

    def save(self, settings) -> None:
        for f in fields(self):
            settings.set("recorder." + f.name, getattr(self, f.name))


def _combo(items, current) -> QComboBox:
    box = QComboBox()
    for value, label in items:
        box.addItem(label, value)
    idx = box.findData(current)
    box.setCurrentIndex(idx if idx >= 0 else 0)
    return box


FULL_FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/"


class RecordDialog(QDialog):
    def __init__(self, choices: RecordChoices, last_result=None, unsupported: Optional[str] = None,
                 tray_available: bool = True, notifications_available: bool = True,
                 blur_available: bool = True,
                 sources: Optional[List[audio_devices.Source]] = None, cameras=None, parent=None):
        super().__init__(parent)
        self.setObjectName("recorder_dialog")
        self.setWindowTitle(TEXT["title"])
        self.choices = choices
        lay = QVBoxLayout(self)

        # Last result, or why recording cannot run here.
        top = QHBoxLayout()
        self.status = QLabel()
        self.status.setWordWrap(True)
        top.addWidget(self.status, 1)
        self.open_btn = QPushButton(TEXT["open_folder"])
        self.open_btn.clicked.connect(self._open_folder)
        top.addWidget(self.open_btn)
        lay.addLayout(top)
        self._last_result = last_result
        self._show_status(unsupported)

        form = QFormLayout()
        lay.addLayout(form)

        # What to record
        self.r_window = QRadioButton(TEXT["window"])
        self.r_screen = QRadioButton(TEXT["screen"])
        self.r_rect = QRadioButton(TEXT["rect"])
        {"window": self.r_window, "screen": self.r_screen, "rect": self.r_rect}.get(
            choices.region, self.r_window).setChecked(True)
        screens = [(s.name(), f"{s.name()} ({s.geometry().width()}×{s.geometry().height()})")
                   for s in QGuiApplication.screens()]
        self.screen_box = _combo(screens, choices.screen)
        what = QVBoxLayout()
        what.addWidget(self.r_window)
        row = QHBoxLayout()
        row.addWidget(self.r_screen)
        row.addWidget(self.screen_box, 1)
        what.addLayout(row)
        what.addWidget(self.r_rect)
        form.addRow(TEXT["what"], _wrap(what))

        # Sound
        sources = audio_devices.list_sources() if sources is None else sources
        mics = [(s.name, s.description) for s in sources if not s.monitor]
        monitors = [(s.name, s.description) for s in sources if s.monitor]
        # A remembered device that is gone falls back to the SYSTEM default,
        # and the dialog says so (review R2 F8; spec §4.4).
        notes = []
        mic_now = audio_devices.resolve(choices.mic_device, [s for s in sources if not s.monitor],
                                        audio_devices.default_microphone())
        pc_now = audio_devices.resolve(choices.computer_device, [s for s in sources if s.monitor],
                                       audio_devices.default_computer_sound())
        for what, old, new, items in ((TEXT["mic"], choices.mic_device, mic_now, mics),
                                      (TEXT["computer"].split(" (")[0], choices.computer_device,
                                       pc_now, monitors)):
            if old and old != new and items:
                label = dict(items).get(new, new or "the first device")
                notes.append(TEXT["device_gone"].format(what=what, old=old, new=label))
        self.mic_check = QCheckBox(TEXT["mic"])
        self.mic_check.setChecked(choices.mic_enabled and bool(mics))
        self.mic_box = _combo(mics, mic_now)
        self.pc_check = QCheckBox(TEXT["computer"])
        self.pc_check.setChecked(choices.computer_enabled and bool(monitors))
        self.pc_box = _combo(monitors, pc_now)
        if not monitors and audio_devices.IS_WINDOWS:
            self.pc_check.setToolTip(TEXT["computer_windows_na"])
        if not monitors and macos.IS_MACOS:       # no loopback device (D-21)
            self.pc_check.setToolTip(macos.TEXT["no_loopback"])
            notes.append(macos.TEXT["no_loopback"])
        sound = QVBoxLayout()
        for check, box in ((self.mic_check, self.mic_box), (self.pc_check, self.pc_box)):
            r = QHBoxLayout()
            r.addWidget(check)
            r.addWidget(box, 1)
            check.setEnabled(box.count() > 0)
            sound.addLayout(r)
        self.device_note = QLabel("\n".join(notes))
        self.device_note.setWordWrap(True)
        self.device_note.setVisible(bool(notes))
        sound.addWidget(self.device_note)
        form.addRow(TEXT["sound"], _wrap(sound))

        # Quality, format, estimate
        self.preset_box = _combo([(p.key, p.label) for p in presets.PRESETS], choices.preset)
        self.fps_box = _combo([(f, f"{f} fps") for f in presets.FPS_CHOICES], choices.fps)
        q = QHBoxLayout()
        q.addWidget(self.preset_box, 1)
        q.addWidget(self.fps_box)
        form.addRow(TEXT["quality"], _wrap(q))
        self.format_box = _combo([(f.key, f"{f.label}, {f.note}") for f in presets.FORMATS],
                                 choices.format)
        form.addRow(TEXT["format"], self.format_box)
        self.estimate = QLabel()
        form.addRow("", self.estimate)

        # Camera
        cameras = cameras if cameras is not None else _cameras()
        self.cam_check = QCheckBox(TEXT["camera_box"])
        self.cam_check.setChecked(choices.camera_enabled and bool(cameras))
        self.cam_check.setEnabled(bool(cameras))
        ids = [c[0] for c in cameras]
        self.cam_box = _combo(cameras, choices.camera_device if choices.camera_device in ids
                              else _default_camera_id())
        self.cam_size = _combo(TEXT["camera_sizes"].items(), choices.camera_size)
        self.cam_size.setToolTip(TEXT["camera_size_tip"])
        self.cam_size.setEnabled(bool(cameras))
        c = QHBoxLayout()
        c.addWidget(self.cam_check)
        c.addWidget(self.cam_box, 1)
        c.addWidget(self.cam_size)
        form.addRow(TEXT["camera"], _wrap(c))

        # Privacy
        # Without ffmpeg's zmq filter the boxes cannot follow the window: the
        # options are greyed out and unticked, the saved choice is kept for
        # when the full build is installed (Lorris 2026-10-22, D-20).
        self._blur_available = blur_available
        self.blur_check = QCheckBox(TEXT["blur"])
        self.blur_check.setChecked(choices.blur_memory and blur_available)
        self.blur_title_check = QCheckBox(TEXT["blur_title"])
        self.blur_title_check.setChecked(choices.blur_title and blur_available)
        for check in (self.blur_check, self.blur_title_check):
            check.setEnabled(blur_available)
        self.blur_note = QLabel(macos.TEXT["no_zmq"] if macos.IS_MACOS else TEXT["blur_na"])
        self.blur_note.setObjectName("recorder_blur_note")
        self.blur_note.setWordWrap(True)
        self.blur_get = QPushButton(TEXT["blur_get"])
        self.blur_get.setObjectName("recorder_blur_get")
        self.blur_get.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl(macos.FFMPEG_URL if macos.IS_MACOS else FULL_FFMPEG_URL)))
        for w in (self.blur_note, self.blur_get):
            w.setVisible(not blur_available)
        self.notif_check = QCheckBox(TEXT["notif"] if notifications_available else TEXT["notif_na"])
        self.notif_check.setChecked(choices.hide_notifications and notifications_available)
        self.notif_check.setEnabled(notifications_available)
        if not notifications_available and macos.IS_MACOS:
            self.notif_check.setToolTip(macos.TEXT["notifications"])
        pv = QVBoxLayout()
        pv.addWidget(self.blur_check)
        pv.addWidget(self.blur_title_check)
        # The note on its own full-width line: a word-wrapped label sharing a
        # row with a button gets too little height and its last line is cut
        # (seen on the macOS VM, 2026-10-22).
        pv.addWidget(self.blur_note)
        blur_row = QHBoxLayout()
        blur_row.addWidget(self.blur_get)
        blur_row.addStretch(1)
        pv.addLayout(blur_row)
        pv.addWidget(self.notif_check)
        form.addRow(TEXT["privacy"], _wrap(pv))

        # Cursor highlight
        self.hl_check = QCheckBox(TEXT["highlight"])
        self.hl_check.setChecked(choices.highlight_enabled)
        self.hl_colour = _combo(TEXT["colours"].items(), choices.highlight_color)
        self.hl_size = _combo(TEXT["sizes"].items(), choices.highlight_size)
        self.hl_shape = _combo(TEXT["shapes"].items(), choices.highlight_shape)
        self.hl_opacity = QSpinBox()
        self.hl_opacity.setRange(20, 80)
        self.hl_opacity.setSingleStep(5)
        self.hl_opacity.setSuffix(" %")
        self.hl_opacity.setValue(choices.highlight_opacity)
        h = QHBoxLayout()
        for w in (self.hl_check, self.hl_colour, self.hl_size, self.hl_shape,
                  QLabel(TEXT["opacity"]), self.hl_opacity):
            h.addWidget(w)
        form.addRow(TEXT["cursor"], _wrap(h))

        # Folder
        self.folder_label = QLabel(choices.folder or output.default_folder(_movies()))
        change = QPushButton(TEXT["change"])
        change.clicked.connect(self._change_folder)
        fr = QHBoxLayout()
        fr.addWidget(self.folder_label, 1)
        fr.addWidget(change)
        form.addRow(TEXT["save_to"], _wrap(fr))

        if not tray_available:
            lay.addWidget(QLabel(TEXT["no_tray"]))

        buttons = QDialogButtonBox()
        self.start_btn = buttons.addButton(TEXT["start"], QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.start_btn.setDefault(True)
        self.start_btn.setEnabled(unsupported is None)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        for w in (self.preset_box, self.fps_box, self.format_box):
            w.currentIndexChanged.connect(self._update_estimate)
        for w in (self.mic_check, self.pc_check):
            w.toggled.connect(self._update_estimate)
        self._update_estimate()
        # Open at the full size hint: a top-level layout's minimum ignores the
        # word-wrapped notes' height-for-width, so some platforms (offscreen,
        # Cocoa on the macOS VM) opened shorter and cut the wrapped lines.
        self.resize(self.sizeHint())

    # ---------------------------------------------------------- pieces

    def _show_status(self, unsupported):
        res = self._last_result
        if unsupported:
            self.status.setText(unsupported)
        elif res is not None and not hasattr(res, "code"):
            text = TEXT["last_saved"].format(name=os.path.basename(res.path),
                                             size=output.human_size(res.size_bytes))
            self.status.setText(text + (f" ({res.note})" if res.note else ""))
        elif res is not None:
            text = TEXT["last_failed"].format(message=res.message)
            if res.path:
                text += " " + TEXT["kept"].format(name=os.path.basename(res.path),
                                                  size=output.human_size(res.size_bytes))
            self.status.setText(text)
        else:
            self.status.setText("")
        self.open_btn.setVisible(bool(getattr(res, "path", "")) and not unsupported)

    def _open_folder(self):
        res = self._last_result
        folder = os.path.dirname(res.path) if getattr(res, "path", "") else \
            self.folder_label.text()
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _change_folder(self):
        folder = QFileDialog.getExistingDirectory(self, TEXT["save_to"], self.folder_label.text())
        if folder:
            self.folder_label.setText(folder)

    def _update_estimate(self):
        mb = presets.estimate_mb_per_min(self.preset_box.currentData(), self.format_box.currentData(),
                                         self.fps_box.currentData(),
                                         self.mic_check.isChecked() or self.pc_check.isChecked())
        self.estimate.setText(TEXT["estimate"].format(mb=mb))

    def _accept(self):
        c = self.choices
        c.region = "screen" if self.r_screen.isChecked() else "rect" if self.r_rect.isChecked() else "window"
        c.screen = self.screen_box.currentData() or ""
        c.mic_enabled = self.mic_check.isChecked()
        c.mic_device = self.mic_box.currentData() or ""
        c.computer_enabled = self.pc_check.isChecked()
        c.computer_device = self.pc_box.currentData() or ""
        c.preset = self.preset_box.currentData()
        c.fps = int(self.fps_box.currentData())
        c.format = self.format_box.currentData()
        c.camera_enabled = self.cam_check.isChecked()
        c.camera_device = self.cam_box.currentData() or ""
        c.camera_size = self.cam_size.currentData() or "small"
        if self._blur_available:               # greyed out: keep the saved choice
            c.blur_memory = self.blur_check.isChecked()
            c.blur_title = self.blur_title_check.isChecked()
        c.hide_notifications = self.notif_check.isChecked()
        c.highlight_enabled = self.hl_check.isChecked()
        c.highlight_color = self.hl_colour.currentData()
        c.highlight_size = self.hl_size.currentData()
        c.highlight_shape = self.hl_shape.currentData()
        c.highlight_opacity = int(self.hl_opacity.value())
        folder = self.folder_label.text()
        c.folder = "" if folder == output.default_folder(_movies()) else folder
        self.accept()


def _wrap(layout) -> QWidget:
    w = QWidget()
    layout.setContentsMargins(0, 0, 0, 0)
    w.setLayout(layout)
    return w


def _movies() -> Optional[str]:
    from PySide6.QtCore import QStandardPaths
    locs = QStandardPaths.standardLocations(QStandardPaths.StandardLocation.MoviesLocation)
    return locs[0] if locs else None


def _cameras():
    try:
        from PySide6.QtMultimedia import QMediaDevices
        from apps.recorder.camera_bubble import _pick_format
    except ImportError:
        return []
    return [(bytes(d.id().data()).decode(errors="replace"), d.description())
            for d in QMediaDevices.videoInputs() if _pick_format(d) is not None]


def _default_camera_id() -> str:
    try:
        from apps.recorder.camera_bubble import default_camera
        d = default_camera()
        return bytes(d.id().data()).decode(errors="replace") if d is not None else ""
    except ImportError:
        return ""


def output_folder(choices: RecordChoices) -> str:
    return choices.folder or output.default_folder(_movies())
