# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The recorder hotkey (SPEC-REC-001 §4.10): application-scoped,
default Ctrl+Alt+R, stored in ``recorder.hotkey``; a combination already used
in the app is refused, the AI capture hotkey included (review R1 F15).

``install(gui)`` is the ONE call the main window makes. It also hooks the
window's close (stop and save the take first) and runs crash recovery.
Nothing is stored on ChartGUI (Rule 4b).
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QShortcut

HOTKEY_SETTING = "recorder.hotkey"
HOTKEY_NAME = "recorder_hotkey"
RECORD_ACTION_NAME = "recorder_record_action"     # the menu item only DISPLAYS the keys
_OWN_NAMES = (HOTKEY_NAME, RECORD_ACTION_NAME)

TEXT = {
    "menu": "&Recorder",
    "record": "Record the screen…",
    "stop": "Stop recording",
    "open_folder": "Open the recordings folder",
    "duplicate": "{keys} is already used by “{owner}”. Choose another combination.",
    "modifier": "Use Ctrl, Alt or Meta in the combination.",
}


def current_hotkey() -> str:
    from core.settings_registry import default
    from managers.settings_manager import get_settings
    value = get_settings().get(HOTKEY_SETTING, default(HOTKEY_SETTING))
    return value if isinstance(value, str) and value else default(HOTKEY_SETTING)


def find_hotkey(gui) -> Optional[QShortcut]:
    return gui.findChild(QShortcut, HOTKEY_NAME)


def conflict(gui, keys: QKeySequence) -> Optional[str]:
    """Who already uses ``keys`` (the AI capture action and hotkey count)."""
    from apps.shortcut_conflicts import HOTKEY_NAME as AI_HOTKEY, shortcut_owner
    owner = shortcut_owner(gui, keys, exclude=_OWN_NAMES)
    if owner:
        return owner
    ai = gui.findChild(QShortcut, AI_HOTKEY)                 # shortcut_owner skips it
    if ai is not None and ai.key().matches(keys) == QKeySequence.SequenceMatch.ExactMatch:
        return "AI capture"
    return None


class _CloseHook(QObject):
    def __init__(self, gui):
        super().__init__(gui)
        self._gui = gui

    def eventFilter(self, obj, event):                       # noqa: N802 (Qt API)
        if obj is self._gui and event.type() == QEvent.Type.Close:
            from apps.recorder.controller import for_gui
            for_gui(self._gui).close_app()
        return False


def install(gui, keys: Optional[str] = None) -> Optional[QShortcut]:
    """Bind the hotkey, hook the close, schedule crash recovery. Returns the
    shortcut, or None when the combination is taken (nothing bound then)."""
    from apps.recorder.controller import for_gui
    seq = QKeySequence(keys or current_hotkey())
    shortcut = find_hotkey(gui)
    if shortcut is None:
        if conflict(gui, seq):
            return None
        shortcut = QShortcut(gui)
        shortcut.setObjectName(HOTKEY_NAME)
        shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        shortcut.setAutoRepeat(False)
        shortcut.activated.connect(lambda: for_gui(gui).toggle())
        gui.installEventFilter(_CloseHook(gui))
        ctl = for_gui(gui)
        QTimer.singleShot(3000, ctl, lambda: ctl.ensure_started())   # bound to the controller's life
    shortcut.setKey(seq)
    return shortcut


def set_hotkey(gui, keys: QKeySequence) -> Optional[str]:
    """Store and bind ``keys``; the refusal message, or None on success."""
    from core.settings_registry import valid
    from managers.settings_manager import get_settings
    text = keys.toString(QKeySequence.SequenceFormat.PortableText)
    combo = keys[0].keyboardModifiers() if keys.count() else Qt.KeyboardModifier.NoModifier
    needed = (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
              | Qt.KeyboardModifier.MetaModifier)
    if keys.count() != 1 or not (combo & needed) or not valid(HOTKEY_SETTING, text):
        return TEXT["modifier"]
    owner = conflict(gui, keys)
    if owner:
        return TEXT["duplicate"].format(keys=text, owner=owner)
    get_settings().set(HOTKEY_SETTING, text)
    install(gui, text)
    return None


# ----------------------------------------------------------------- menu


def build_recorder_menu(gui, menubar):
    """The Recorder menu, right after AI (Lorris 2026-10-17). Its first item
    does what the hotkey does: the dialog when idle, Stop while recording."""
    from apps.recorder.controller import for_gui
    menu = menubar.addMenu(TEXT["menu"])
    menu.setObjectName("recorder_menu")
    # First line: why recording cannot run here (Windows, macOS, Wayland, no
    # ffmpeg); hidden when it can. Refreshed each time the menu opens.
    note = QAction("", gui)
    note.setObjectName("recorder_unsupported_note")
    note.setEnabled(False)
    note.setVisible(False)
    menu.addAction(note)
    note_sep = menu.addSeparator()
    note_sep.setVisible(False)
    record = QAction(TEXT["record"], gui)
    record.setObjectName(RECORD_ACTION_NAME)
    record.setShortcut(QKeySequence(current_hotkey()))
    # The application QShortcut is the live binding; the menu only shows the keys.
    record.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
    record.triggered.connect(lambda: for_gui(gui).toggle())
    menu.addAction(record)
    folder = QAction(TEXT["open_folder"], gui)
    folder.triggered.connect(lambda: for_gui(gui).open_folder())
    menu.addAction(folder)

    def refresh():
        from PySide6.QtGui import QGuiApplication
        from core.recorder import encoders
        reason = encoders.unsupported_reason(QGuiApplication.platformName())
        note.setText((reason or "").replace("&", "&&"))   # "Privacy & Security": a lone & is a mnemonic
        note.setVisible(bool(reason))
        note_sep.setVisible(bool(reason))
        ctl = for_gui(gui)
        busy = ctl.manager.busy or ctl._capturing
        record.setText(TEXT["stop"] if busy else TEXT["record"])
        shortcut = find_hotkey(gui)
        record.setShortcut(shortcut.key() if shortcut is not None else QKeySequence(current_hotkey()))
    menu.aboutToShow.connect(refresh)
    return menu
