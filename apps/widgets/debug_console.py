# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Debug Console Widget - Captures and displays stdout/stderr output

This module provides a debug console that:
- Captures all stdout/stderr output
- Displays it in a styled text area with green-on-black terminal look
- Provides copy-to-clipboard functionality
- Supports app restart callback

Only used when app is started with -d/--debug flag.
"""

import sys

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit,
    QPushButton, QLabel, QApplication
)
from PySide6.QtCore import Qt, QTimer

from ui.qt_theme import scaled_area_px, get_theme_accent


class DebugConsoleWidget(QWidget):
    """
    Debug console widget that captures and displays stdout/stderr.
    Only used when app is started with -d flag.
    """

    def __init__(self, parent=None, restart_callback=None):
        super().__init__(parent)
        self.restart_callback = restart_callback
        self.setup_ui()

        # Store original stdout/stderr
        self._original_stdout = sys.stdout
        self._original_stderr = sys.stderr

        # Redirect stdout/stderr to this widget
        sys.stdout = self
        sys.stderr = self

    def setup_ui(self):
        """Setup the debug console UI with qt-material styling."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # Header with title and copy button
        header_layout = QHBoxLayout()

        # Title label
        title_label = QLabel("Debug Console Output")
        title_label.setStyleSheet(f"""
            QLabel {{
                font-size: {scaled_area_px('status')}px;
                font-weight: bold;
                color: #FFFFFF;
                padding: 8px;
            }}
        """)
        header_layout.addWidget(title_label)
        header_layout.addStretch()

        # Copy button with qt-material styling
        self.copy_button = QPushButton("📋 Copy Console")
        self.copy_button.setCursor(Qt.PointingHandCursor)
        accent = get_theme_accent()
        self.copy_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {accent["base"]};
                color: #FFFFFF;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-size: {scaled_area_px('status')}px;
                font-weight: bold;
                min-width: 120px;
            }}
            QPushButton:hover {{
                background-color: {accent["hover"]};
            }}
            QPushButton:pressed {{
                background-color: {accent["active"]};
            }}
        """)
        self.copy_button.clicked.connect(self.copy_console)
        header_layout.addWidget(self.copy_button)

        # Restart button (only if callback provided)
        if self.restart_callback:
            self.restart_button = QPushButton("🔄 Restart App")
            self.restart_button.setCursor(Qt.PointingHandCursor)
            self.restart_button.setStyleSheet(f"""
                QPushButton {{
                    background-color: #FF9500;
                    color: #FFFFFF;
                    border: none;
                    border-radius: 4px;
                    padding: 8px 16px;
                    font-size: {scaled_area_px('status')}px;
                    font-weight: bold;
                    min-width: 120px;
                }}
                QPushButton:hover {{
                    background-color: #E67E00;
                }}
                QPushButton:pressed {{
                    background-color: #CC7000;
                }}
            """)
            self.restart_button.clicked.connect(self.restart_callback)
            header_layout.addWidget(self.restart_button)

        layout.addLayout(header_layout)

        # Console output text area with monospace font
        self.console_output = QTextEdit()
        self.console_output.setReadOnly(True)
        self.console_output.setStyleSheet(f"""
            QTextEdit {{
                background-color: #0D0D0D;
                color: #00FF00;
                font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
                font-size: {scaled_area_px('status')}px;
                border: 1px solid #3D3D3D;
                border-radius: 4px;
                padding: 10px;
            }}
            QScrollBar:vertical {{
                background-color: #1C1C1E;
                width: 12px;
                border-radius: 6px;
            }}
            QScrollBar::handle:vertical {{
                background-color: #3D3D3D;
                border-radius: 6px;
                min-height: 30px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: #5A5A5C;
            }}
        """)
        layout.addWidget(self.console_output)

    def write(self, text):
        """Capture stdout/stderr and display in console."""
        if text:  # Only write non-empty strings
            self.console_output.insertPlainText(text)
            # Auto-scroll to bottom
            scrollbar = self.console_output.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
        return len(text) if text else 0

    def flush(self):
        """Flush method for compatibility with stdout/stderr."""
        pass

    def copy_console(self):
        """Copy all console output to clipboard."""
        text = self.console_output.toPlainText()
        if text:
            clipboard = QApplication.clipboard()
            clipboard.setText(text)
            self.copy_button.setText("✅ Copied!")
            # Reset button text after 2 seconds
            QTimer.singleShot(2000, lambda: self.copy_button.setText("📋 Copy Console"))

    def closeEvent(self, event):
        """Restore stdout/stderr when widget is closed."""
        sys.stdout = self._original_stdout
        sys.stderr = self._original_stderr
        event.accept()
