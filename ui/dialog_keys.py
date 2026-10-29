# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Enter in a dialog's text field belongs to that field.

A QLineEdit emits ``returnPressed`` on Enter, then ignores the key, so the
QDialog around it clicks its default button as well (with none set, the first
auto-default button). In the AI setting window that opened Report a problem
on every Enter, after Ask had already run (macOS VM test 2026-10-27). A dialog
whose fields send on Enter calls ``field_enter`` first in its keyPressEvent.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLineEdit, QPushButton

_ENTER = (Qt.Key.Key_Return, Qt.Key.Key_Enter)


def field_enter(dialog, event) -> bool:
    """True (the key is consumed) when ``event`` is Enter coming from a text
    field of ``dialog``: the field's own ``returnPressed`` has already run,
    so no button of the dialog is clicked."""
    if event.key() not in _ENTER:
        return False
    if not isinstance(dialog.focusWidget(), QLineEdit):
        return False
    event.accept()
    return True


def no_fallback_button(dialog) -> None:
    """No button of ``dialog`` becomes its default on its own: Enter from a
    list or a combo box, which leave the key to the dialog too, clicks
    nothing. Qt otherwise makes an auto-default button the default (the
    first in the focus chain: Report a problem on macOS, New conversation
    elsewhere). Space still clicks the focused button."""
    for button in dialog.findChildren(QPushButton):
        button.setAutoDefault(False)
        button.setDefault(False)
