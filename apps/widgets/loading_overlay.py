# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Reusable loading overlay widget for Varuna360.

Displays a semi-transparent overlay with a spinner and status message
to indicate that the application is performing work (not frozen).
Prevents the OS "not responding" dialog during expected heavy operations.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QProgressBar, QApplication,
    QGraphicsDropShadowEffect
)
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QPainter, QColor

from ui.qt_theme import (
    SURFACE, TEXT_PRIMARY, BORDER, ACCENTS,
    get_theme_accent, get_theme_colors, scaled_area_px,
)


class LoadingOverlay(QWidget):
    """Full-window overlay with a centered loading card.

    Shows a semi-transparent dark background covering the parent window,
    with a centered rounded card containing a status message and
    an indeterminate progress bar (spinner effect).

    Usage:
        overlay = LoadingOverlay(main_window)
        overlay.show_loading("Loading chart...")
        # ... do work, call update_message() as needed ...
        overlay.hide_loading()
    """

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("LoadingOverlay")

        # Cover entire parent, stay on top
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowFlags(Qt.WindowType.Widget)

        # Block all mouse/keyboard events from reaching widgets underneath
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Build the centered card UI
        self._build_ui()

        # Track parent resize to stay full-size
        if parent:
            parent.installEventFilter(self)

        # Start hidden
        self.hide()

    def _build_ui(self):
        """Build the overlay card with message label and progress bar."""
        # Main layout fills the overlay
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # --- Card container ---
        # SPEC-THM-001 G13: live theme colors (were frozen SURFACE/BORDER).
        theme = get_theme_colors()
        self._card = QWidget(self)
        self._card.setFixedSize(320, 110)
        self._card.setStyleSheet(f"""
            QWidget {{
                background-color: {theme['secondary']};
                border: 1px solid {theme['secondary_light']};
                border-radius: 12px;
            }}
        """)

        # Drop shadow on card
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(30)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 160))
        self._card.setGraphicsEffect(shadow)
        del shadow  # Qt owns it now (Rule 18)

        card_layout = QVBoxLayout(self._card)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.setSpacing(14)
        card_layout.setContentsMargins(20, 16, 20, 16)

        # Status message label
        # SPEC-THM-001 G13: live theme color (was frozen TEXT_PRIMARY).
        self._message_label = QLabel("Loading...")
        self._message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._message_label.setStyleSheet(f"""
            QLabel {{
                color: {theme['secondary_text']};
                font-size: {scaled_area_px('info_text')}px;
                font-weight: bold;
                background: transparent;
                border: none;
            }}
        """)
        card_layout.addWidget(self._message_label)

        # Progress bar (indeterminate by default — range 0,0 = spinner)
        self._progress_bar = QProgressBar()
        self._progress_bar.setFixedWidth(260)
        self._progress_bar.setFixedHeight(6)
        self._progress_bar.setRange(0, 0)  # Indeterminate spinner
        self._progress_bar.setTextVisible(False)
        accent = get_theme_accent()
        # SPEC-THM-001 G13: live theme color for progress bar border + track.
        self._progress_bar.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid {theme['secondary_light']};
                border-radius: 3px;
                background-color: {theme['secondary_dark']};
                height: 6px;
            }}
            QProgressBar::chunk {{
                background-color: {accent["base"]};
                border-radius: 2px;
            }}
        """)
        card_layout.addWidget(self._progress_bar)

        layout.addWidget(self._card)

    def show_loading(self, message: str = "Loading..."):
        """Show the overlay with the given status message."""
        self._message_label.setText(message)
        self._progress_bar.setRange(0, 0)  # Reset to indeterminate
        self._resize_to_parent()
        self.raise_()
        self.show()
        QApplication.processEvents()

    def update_message(self, message: str):
        """Update the status message while overlay is visible."""
        self._message_label.setText(message)
        QApplication.processEvents()

    def set_progress(self, current: int, total: int):
        """Switch to determinate mode and set progress value.

        Args:
            current: Current step number
            total: Total number of steps
        """
        if self._progress_bar.maximum() != total:
            self._progress_bar.setRange(0, total)
        self._progress_bar.setValue(current)
        QApplication.processEvents()

    def hide_loading(self):
        """Hide the overlay."""
        self.hide()
        QApplication.processEvents()

    def refresh_theme(self):
        """Re-apply theme colors to card, label, and progress bar.

        SPEC-THM-001 G13: overlay had no refresh_theme(). After a theme
        switch the overlay's card/label kept old colors. Re-apply all
        inline stylesheets that were set in _build_ui using current theme.
        """
        theme = get_theme_colors()
        if hasattr(self, '_card'):
            self._card.setStyleSheet(f"""
                QWidget {{
                    background-color: {theme['secondary']};
                    border: 1px solid {theme['secondary_light']};
                    border-radius: 12px;
                }}
            """)
        if hasattr(self, '_message_label'):
            self._message_label.setStyleSheet(f"""
                QLabel {{
                    color: {theme['secondary_text']};
                    font-size: {scaled_area_px('info_text')}px;
                    font-weight: bold;
                    background: transparent;
                    border: none;
                }}
            """)
        if hasattr(self, '_progress_bar'):
            accent = get_theme_accent()
            self._progress_bar.setStyleSheet(f"""
                QProgressBar {{
                    border: 1px solid {theme['secondary_light']};
                    border-radius: 3px;
                    background-color: {theme['secondary_dark']};
                    height: 6px;
                }}
                QProgressBar::chunk {{
                    background-color: {accent["base"]};
                    border-radius: 2px;
                }}
            """)

    # --- Event handling ---

    def paintEvent(self, event):
        """Paint the semi-transparent dark background."""
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 120))
        painter.end()

    def eventFilter(self, obj, event):
        """Track parent resize to keep overlay full-size."""
        if obj == self.parent() and event.type() == QEvent.Type.Resize:
            self._resize_to_parent()
        return super().eventFilter(obj, event)

    def mousePressEvent(self, event):
        """Block mouse clicks from reaching widgets underneath."""
        event.accept()

    def mouseReleaseEvent(self, event):
        event.accept()

    def keyPressEvent(self, event):
        """Block keyboard events (except Escape for safety)."""
        event.accept()

    def _resize_to_parent(self):
        """Resize overlay to match parent dimensions."""
        if self.parent():
            self.setGeometry(0, 0, self.parent().width(), self.parent().height())
