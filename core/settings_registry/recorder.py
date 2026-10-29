# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Screen recorder preferences (SPEC-REC-001 §4). The record dialog
writes them after each Start, so the next take opens with the same choices;
the hotkey is changed through the same refusal rules as the AI capture hotkey.
Dynamic writer keys: not in DEFAULT_SETTINGS (persisted=False), like the AI
task picks. Run-time and layout state (last result, saved notification value, the
last drawn rectangle, the camera bubble's place and size) is NOT here: it
lives in ``core/recorder/state_store.py`` (review R1 F16)."""
from dataclasses import replace

from core.settings_registry.rules import APP_AI as APP
from core.settings_registry.schema import Choice, Setting

_V = "core.settings_registry.validators:"
# Device and screen names come from the machine at run time (pactl, QMediaDevices,
# QScreen): a catalog checked at use, never a copied list.
_CATALOG = replace(APP, validate=_V + "catalog_name")

_COLOURS = ("red", "rose", "orange", "yellow", "blue", "green")

SETTINGS = (
    Setting("recorder.hotkey", str, "Ctrl+Alt+R", persisted=False,
            rules=replace(APP, validate=_V + "shortcut")),
    Setting("recorder.region", str, "window", persisted=False,
            choices=(Choice("window"), Choice("screen"), Choice("rect")), rules=APP),
    Setting("recorder.screen", str, "", persisted=False, rules=_CATALOG),
    Setting("recorder.mic_enabled", bool, True, persisted=False, rules=APP),
    Setting("recorder.mic_device", str, "", persisted=False, rules=_CATALOG),
    Setting("recorder.computer_enabled", bool, False, persisted=False, rules=APP),
    Setting("recorder.computer_device", str, "", persisted=False, rules=_CATALOG),
    Setting("recorder.preset", str, "standard", persisted=False,
            choices=(Choice("small"), Choice("standard"), Choice("high")), rules=APP),
    Setting("recorder.fps", int, 30, persisted=False,
            choices=(Choice(30), Choice(60)), rules=APP),
    Setting("recorder.format", str, "h264", persisted=False,
            choices=(Choice("h264"), Choice("h265"), Choice("av1")), rules=APP),
    Setting("recorder.camera_enabled", bool, False, persisted=False, rules=APP),
    Setting("recorder.camera_device", str, "", persisted=False, rules=_CATALOG),
    Setting("recorder.camera_mirror", bool, True, persisted=False, rules=APP),
    Setting("recorder.camera_ring", bool, True, persisted=False, rules=APP),
    Setting("recorder.camera_size", str, "small", persisted=False,
            choices=(Choice("small"), Choice("medium"), Choice("large"), Choice("xlarge")),
            rules=APP),
    Setting("recorder.blur_memory", bool, True, persisted=False, rules=APP),
    Setting("recorder.blur_title", bool, True, persisted=False, rules=APP),
    Setting("recorder.hide_notifications", bool, True, persisted=False, rules=APP),
    Setting("recorder.highlight_enabled", bool, True, persisted=False, rules=APP),
    Setting("recorder.highlight_color", str, "red", persisted=False,
            choices=tuple(Choice(c) for c in _COLOURS), rules=APP),
    Setting("recorder.highlight_opacity", int, 50, persisted=False, bounds=(20, 80), rules=APP),
    Setting("recorder.highlight_size", str, "M", persisted=False,
            choices=(Choice("S"), Choice("M"), Choice("L")), rules=APP),
    Setting("recorder.highlight_shape", str, "disc_ring", persisted=False,
            choices=(Choice("disc"), Choice("ring"), Choice("disc_ring")), rules=APP),
    Setting("recorder.highlight_always", bool, False, persisted=False, rules=APP),
    Setting("recorder.folder", str, "", persisted=False,
            rules=replace(APP, validate=_V + "path")),
)
