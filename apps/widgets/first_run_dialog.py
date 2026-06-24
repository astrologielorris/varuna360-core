# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
First-run data directory dialog for AppImage/frozen installs.

Shown once on first launch when no bootstrap config exists. Asks the
user where to store profiles, settings, and session files. The chosen
path is saved to ~/.config/varuna360/bootstrap.json so all subsequent
launches use it automatically.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QVBoxLayout,
)

from state.user_data import get_default_data_dir, set_user_data_dir

from ui.qt_theme import scaled_area_font


class FirstRunDialog(QDialog):
    """Modal dialog asking the user where to store application data."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Varuna360 — First Run Setup")
        self.setModal(True)
        self.setMinimumWidth(550)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 25, 30, 25)
        layout.setSpacing(18)

        title = QLabel("Welcome to Varuna360")
        title.setFont(scaled_area_font('panel_titles', bold=True))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        desc = QLabel(
            "Please choose a folder where Varuna360 will store your "
            "settings, profiles, and session data.\n\n"
            "You can change this later in Settings > Default Folders."
        )
        desc.setWordWrap(True)
        desc_font = scaled_area_font('info_text')
        desc.setFont(desc_font)
        layout.addWidget(desc)

        # Path input row
        path_layout = QHBoxLayout()
        path_layout.setSpacing(8)

        path_label = QLabel("Data folder:")
        path_label.setFont(desc_font)
        path_layout.addWidget(path_label)

        self._path_edit = QLineEdit()
        self._path_edit.setText(str(get_default_data_dir()))
        self._path_edit.setFont(desc_font)
        self._path_edit.setMinimumWidth(300)
        path_layout.addWidget(self._path_edit, stretch=1)

        browse_btn = QPushButton("Browse...")
        browse_btn.setFont(scaled_area_font('buttons'))
        browse_btn.clicked.connect(self._on_browse)
        path_layout.addWidget(browse_btn)

        layout.addLayout(path_layout)

        # Buttons row
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        ok_btn = QPushButton("Continue")
        ok_btn.setDefault(True)
        ok_btn.setMinimumWidth(120)
        ok_btn.setFont(scaled_area_font('buttons', bold=True))
        ok_btn.clicked.connect(self._on_accept)
        btn_layout.addWidget(ok_btn)

        cancel_btn = QPushButton("Quit")
        cancel_btn.setMinimumWidth(80)
        cancel_btn.setFont(scaled_area_font('buttons'))
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

    def _on_browse(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Data Folder",
            str(Path.home() / "Documents"),
        )
        if folder:
            self._path_edit.setText(folder)

    def _on_accept(self):
        chosen = self._path_edit.text().strip()
        if not chosen:
            return
        path = Path(chosen)
        try:
            set_user_data_dir(path)
            self.accept()
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self,
                "Cannot use this folder",
                f"Failed to create data folder:\n{e}\n\n"
                "Please choose a different location.",
            )
