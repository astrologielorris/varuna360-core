# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Which in-app action or shortcut already uses a key combination: the
recorder's and the AI capture's hotkey dialogs share it (every edition;
moved out of apps/ai_capture/entry_points, SPEC-EDN-002)."""
from __future__ import annotations

from typing import Optional

from PySide6.QtGui import QAction, QKeySequence, QShortcut

HOTKEY_NAME = "ai_capture_hotkey"        # the AI capture's QShortcut objectName (Pro)


def shortcut_owner(gui, keys: QKeySequence, exclude=("ai_capture_action",)) -> Optional[str]:
    """The name of the in-app action or shortcut already using ``keys``
    (the actions named in ``exclude`` and the capture's own shortcut
    excluded), else None."""
    target = keys.toString(QKeySequence.SequenceFormat.PortableText)
    for action in gui.findChildren(QAction):
        if action.objectName() in exclude:
            continue
        for seq in action.shortcuts():
            if seq.toString(QKeySequence.SequenceFormat.PortableText) == target:
                return action.text().replace("&", "") or action.objectName() or target
    for sc in gui.findChildren(QShortcut):
        if sc.objectName() == HOTKEY_NAME:
            continue
        if sc.key().toString(QKeySequence.SequenceFormat.PortableText) == target:
            return sc.objectName() or sc.whatsThis() or target
    return None
