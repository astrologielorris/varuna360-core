# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Welcome Dialog — shown exactly once per install on first launch.

Modal QDialog displayed before the main window appears. It introduces
Varuna360 in product-sale framing, explains that the desktop runs
anonymously and fully, and points to the Account menu and the
subscription page for users who want to attach a tier.

The "once per install" behavior is driven by a flag file at
~/.config/Varuna360/.welcome_shown — writing the file on first close
is what makes the popup never appear again. Deleting the flag file
resurrects the popup on the next launch, which is the documented way
for a user to intentionally see it again (e.g., to show a friend).

The dialog is modal and intrusive by design. The user asked for
"no free launch" — a non-modal or after-the-main-window-shows popup
gets dismissed while the user is already distracted by the main UI
and the welcome message fails to register.
"""

from __future__ import annotations

import webbrowser
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from ui.qt_theme import scaled_area_size

from core.pro_marketing import (
    PRO_UPGRADE_URL, WELCOME_BODY, WELCOME_TITLE,
)

# Flag file location. Uses XDG config dir on Linux, which is what every
# other settings path in the project uses. Windows/Mac fall back to the
# same path pattern under the user's home directory.
FLAG_DIR = Path.home() / ".config" / "Varuna360"
FLAG_FILE = FLAG_DIR / ".welcome_shown"


def should_show_welcome() -> bool:
    """Return True if the welcome popup has not been shown yet on this install."""
    return not FLAG_FILE.exists()


def mark_welcome_shown() -> None:
    """Write the flag file so the welcome popup never appears again.

    Any failure to write is silent — the flag file is best-effort. If
    writing fails (filesystem full, permission denied, etc.) the popup
    will appear again on the next launch, which is not great but is
    strictly better than crashing the entire boot path over a popup.
    """
    try:
        FLAG_DIR.mkdir(parents=True, exist_ok=True)
        FLAG_FILE.write_text("1\n", encoding="utf-8")
    except OSError:
        pass


class WelcomeDialog(QDialog):
    """Modal first-launch welcome dialog.

    Shown once per install before the main window appears. Explains the
    product model, points to the Account menu and the subscription page,
    and writes a flag file on close so it never shows again.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(WELCOME_TITLE)
        self.setModal(True)
        self.setMinimumWidth(520)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(32, 28, 32, 24)

        # ── Title ──
        title = QLabel(WELCOME_TITLE)
        title_font = QFont()
        title_font.setPointSize(scaled_area_size('panel_titles'))
        title_font.setBold(True)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # ── Body ──
        body = QLabel(WELCOME_BODY)
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignmentFlag.AlignLeft)
        body_font = QFont()
        body_font.setPointSize(scaled_area_size('info_text'))
        body.setFont(body_font)
        layout.addWidget(body)

        # ── Buttons ──
        button_row = QHBoxLayout()
        button_row.setSpacing(8)

        subscribe_btn = QPushButton("Subscribe at 360heartsinthesky.com")
        subscribe_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        subscribe_btn.clicked.connect(self._on_subscribe_clicked)
        button_row.addWidget(subscribe_btn)

        button_row.addStretch(1)

        continue_btn = QPushButton("Continue")
        continue_btn.setDefault(True)
        continue_btn.setAutoDefault(True)
        continue_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        continue_btn.clicked.connect(self.accept)
        button_row.addWidget(continue_btn)

        layout.addLayout(button_row)

    def _on_subscribe_clicked(self) -> None:
        """Open the subscription page in the default browser and close the dialog."""
        webbrowser.open(PRO_UPGRADE_URL)
        self.accept()

    def accept(self) -> None:
        mark_welcome_shown()
        super().accept()

    def reject(self) -> None:
        # Closing via the window X button also counts as "shown".
        mark_welcome_shown()
        super().reject()
