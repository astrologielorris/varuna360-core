# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Login Dialog for Varuna360 Desktop App.

PySide6 QDialog for Firebase email/password authentication.
Appears before the main window when no cached license is available.
"""

import webbrowser
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from ui.qt_theme import (
    BG, SURFACE, BORDER, TEXT_PRIMARY, TEXT_SECONDARY, GOLD,
    get_primary_button_style,
    scaled_area_font, scaled_area_px,
)
from managers.license_manager import LicenseState


SUBSCRIBE_URL = "https://360heartsinthesky.com/subscribe"
FORGOT_PASSWORD_URL = "https://360heartsinthesky.com/forgot-password"


class LoginDialog(QDialog):
    """Login dialog for Varuna360 subscription validation."""

    login_successful = Signal(object)  # emits LicenseState

    def __init__(
        self,
        parent=None,
        message: str = "",
        show_continue_without_account: bool = True,
    ):
        """Initialize the login dialog.

        Args:
            parent: optional Qt parent widget.
            message: optional message rendered above the form (e.g., a
                rejected-login reason).
            show_continue_without_account: when True (default), an
                "Continue without account" text button is rendered above
                the subscribe link so users can dismiss the dialog and
                keep using the app anonymously. Set to False in contexts
                where anonymous dismiss is not a valid outcome — notably
                the pre-main() bundled-installer flow, where declining
                sign-in means `sys.exit(0)` and the misleading "Continue"
                label would contradict the actual behavior.
        """
        super().__init__(parent)
        self.setWindowTitle("Varuna360 — Sign In")
        self.setFixedSize(420, 620)
        self.setModal(True)
        self._license_state = None
        self._show_continue_without_account = show_continue_without_account

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {BG};
            }}
            QLabel {{
                color: {TEXT_PRIMARY};
            }}
        """)

        self._build_ui(message)

    def _build_ui(self, message: str):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(40, 30, 40, 30)

        # ── App Title ──
        title = QLabel("Varuna360")
        title.setFont(scaled_area_font('panel_titles', bold=True))
        title.setStyleSheet(f"color: {GOLD};")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("Tropical Vedic Astrology")
        subtitle.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: {scaled_area_px('status')}px;")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        layout.addSpacing(10)

        # ── Message (if any) ──
        if message:
            msg_label = QLabel(message)
            msg_label.setWordWrap(True)
            msg_label.setStyleSheet(
                f"color: #E57373; font-size: {scaled_area_px('status')}px; padding: 8px; "
                f"background-color: rgba(229, 115, 115, 0.1); "
                f"border-radius: 4px;"
            )
            msg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(msg_label)

        # ── Separator ──
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"background-color: {BORDER};")
        line.setFixedHeight(1)
        layout.addWidget(line)

        layout.addSpacing(5)

        # ── Email Field ──
        email_label = QLabel("Email")
        email_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: {scaled_area_px('buttons')}px;")
        layout.addWidget(email_label)

        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("your@email.com")
        self.email_input.setStyleSheet(self._input_style())
        self.email_input.returnPressed.connect(lambda: self.password_input.setFocus())
        layout.addWidget(self.email_input)

        # ── Password Field ──
        password_label = QLabel("Password")
        password_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: {scaled_area_px('buttons')}px;")
        layout.addWidget(password_label)

        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Password")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setStyleSheet(self._input_style())
        self.password_input.returnPressed.connect(self._on_login_clicked)
        layout.addWidget(self.password_input)

        # ── Forgot Password ──
        forgot_btn = QPushButton("Forgot password?")
        forgot_btn.setFlat(True)
        forgot_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        forgot_btn.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: {scaled_area_px('status')}px; text-align: left; "
            f"border: none; padding: 0; text-decoration: underline;"
        )
        forgot_btn.clicked.connect(lambda: webbrowser.open(FORGOT_PASSWORD_URL))
        layout.addWidget(forgot_btn)

        layout.addSpacing(10)

        # ── Login Button ──
        self.login_btn = QPushButton("Sign In")
        self.login_btn.setStyleSheet(get_primary_button_style())
        self.login_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.login_btn.clicked.connect(self._on_login_clicked)
        layout.addWidget(self.login_btn)

        # ── Or separator ──
        or_layout = QHBoxLayout()
        or_line1 = QFrame()
        or_line1.setFrameShape(QFrame.Shape.HLine)
        or_line1.setStyleSheet(f"background-color: {BORDER};")
        or_line1.setFixedHeight(1)
        or_label = QLabel("or")
        or_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: {scaled_area_px('status')}px;")
        or_label.setFixedWidth(20)
        or_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        or_line2 = QFrame()
        or_line2.setFrameShape(QFrame.Shape.HLine)
        or_line2.setStyleSheet(f"background-color: {BORDER};")
        or_line2.setFixedHeight(1)
        or_layout.addWidget(or_line1)
        or_layout.addWidget(or_label)
        or_layout.addWidget(or_line2)
        layout.addLayout(or_layout)

        # ── Google Sign In Button ──
        self.google_btn = QPushButton("Sign in with Google")
        self.google_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: white; color: #333;
                border: 1px solid #ddd; border-radius: 4px;
                font-size: {scaled_area_px('buttons')}px; font-weight: bold;
                padding: 8px 16px; min-height: 32px;
            }}
            QPushButton:hover {{ background-color: #f5f5f5; border-color: #4285f4; }}
            QPushButton:pressed {{ background-color: #e8e8e8; }}
        """)
        self.google_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.google_btn.clicked.connect(self._on_google_login_clicked)
        layout.addWidget(self.google_btn)

        # ── Error Label ──
        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet(f"color: #E57373; font-size: {scaled_area_px('status')}px;")
        self.error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.error_label.hide()
        layout.addWidget(self.error_label)

        layout.addStretch()

        # ── Continue without account ──
        # Only rendered when show_continue_without_account is True (the
        # default). In the pre-main() bundled-installer flow, main()
        # passes show_continue_without_account=False because declining
        # sign-in means sys.exit(0) — a "Continue" label there would
        # promise behavior the caller does not deliver. When invoked
        # from the Account menu on an anonymous source build, the flag
        # is True and clicking Continue simply closes the dialog with
        # no state change.
        if self._show_continue_without_account:
            continue_btn = QPushButton("Continue without account")
            continue_btn.setFlat(True)
            continue_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            continue_btn.setStyleSheet(
                f"color: {TEXT_SECONDARY}; font-size: {scaled_area_px('status')}px; border: none; "
                f"text-decoration: underline;"
            )
            continue_btn.clicked.connect(self.reject)
            layout.addWidget(continue_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        # ── Subscribe Link ──
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"background-color: {BORDER};")
        sep2.setFixedHeight(1)
        layout.addWidget(sep2)

        subscribe_layout = QHBoxLayout()
        no_account_label = QLabel("No account?")
        no_account_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: {scaled_area_px('status')}px;")
        subscribe_layout.addWidget(no_account_label)

        subscribe_btn = QPushButton("Subscribe at 360heartsinthesky.com")
        subscribe_btn.setFlat(True)
        subscribe_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        subscribe_btn.setStyleSheet(
            f"color: {GOLD}; font-size: {scaled_area_px('status')}px; border: none; "
            f"text-decoration: underline; font-weight: bold;"
        )
        subscribe_btn.clicked.connect(lambda: webbrowser.open(SUBSCRIBE_URL))
        subscribe_layout.addWidget(subscribe_btn)
        subscribe_layout.addStretch()

        layout.addLayout(subscribe_layout)

    def _input_style(self) -> str:
        return f"""
            QLineEdit {{
                background-color: {SURFACE};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER};
                border-radius: 4px;
                padding: 10px 12px;
                font-size: {scaled_area_px('tables')}px;
            }}
            QLineEdit:focus {{
                border-color: {GOLD};
            }}
        """

    def _on_google_login_clicked(self):
        """Open browser for Google OAuth in background thread."""
        self.google_btn.setEnabled(False)
        self.google_btn.setText("Opening browser...")
        self.login_btn.setEnabled(False)
        self.error_label.hide()

        from managers.license_workers import GoogleOAuthWorker
        self._oauth_worker = GoogleOAuthWorker()
        self._oauth_worker.finished.connect(self._on_login_success)
        self._oauth_worker.error.connect(self._on_oauth_error)
        self._oauth_worker.start()

    def _on_oauth_error(self, msg: str):
        self._show_error(msg)
        self.google_btn.setEnabled(True)
        self.google_btn.setText("Sign in with Google")
        self.login_btn.setEnabled(True)

    def _on_login_clicked(self):
        email = self.email_input.text().strip()
        password = self.password_input.text()

        if not email or not password:
            self._show_error("Please enter your email and password.")
            return

        self.login_btn.setEnabled(False)
        self.login_btn.setText("Signing in...")
        self.google_btn.setEnabled(False)
        self.error_label.hide()

        from managers.license_workers import LoginWorker
        self._login_worker = LoginWorker(email, password)
        self._login_worker.finished.connect(self._on_login_success)
        self._login_worker.error.connect(self._on_login_error)
        self._login_worker.start()

    def _on_login_success(self, state):
        """Called when login/OAuth worker succeeds (any method)."""
        self._license_state = state
        self.login_successful.emit(state)
        self.accept()

    def _on_login_error(self, msg: str):
        self._show_error(msg)
        self.login_btn.setEnabled(True)
        self.login_btn.setText("Sign In")
        self.google_btn.setEnabled(True)

    def _show_error(self, msg: str):
        self.error_label.setText(msg)
        self.error_label.show()

    def reject(self):
        """Handle dialog close — disconnect and clean up any running workers."""
        for attr in ('_login_worker', '_oauth_worker'):
            worker = getattr(self, attr, None)
            if worker is not None:
                # Disconnect all signals to prevent delivery into destroyed dialog
                try:
                    worker.finished.disconnect()
                    worker.error.disconnect()
                except RuntimeError:
                    pass  # already disconnected
                if worker.isRunning():
                    worker.wait(2000)
                worker.deleteLater()
                setattr(self, attr, None)
        super().reject()

    def get_license_state(self) -> LicenseState:
        return self._license_state or LicenseState()
