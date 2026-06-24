# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
QThread workers for license operations.

Keeps license_manager.py free of PySide6 dependencies (testable without Qt).
Workers follow the same pattern as WikidataWorker, etc.
"""

from PySide6.QtCore import QThread, Signal

from managers.license_manager import (
    login_and_validate,
    google_oauth_login,
    refresh_license,
    LicenseState,
    LicenseError,
)


class LoginWorker(QThread):
    """Background worker for email/password login."""

    finished = Signal(object)  # LicenseState
    error = Signal(str)

    def __init__(self, email: str, password: str):
        super().__init__()
        self._email = email
        self._password = password

    def run(self):
        try:
            state = login_and_validate(self._email, self._password)
            self.finished.emit(state)
        except LicenseError as e:
            self.error.emit(str(e))
        except Exception as e:
            self.error.emit(f"Unexpected error: {e}")


class GoogleOAuthWorker(QThread):
    """Background worker for Google OAuth login."""

    finished = Signal(object)  # LicenseState
    error = Signal(str)

    def run(self):
        try:
            state = google_oauth_login()
            self.finished.emit(state)
        except LicenseError as e:
            self.error.emit(str(e))
        except Exception as e:
            self.error.emit(f"Google sign-in failed: {e}")


class LicenseRefreshWorker(QThread):
    """Background worker for 12h license refresh."""

    finished = Signal(object)  # LicenseState
    error = Signal(str)

    def __init__(self, state: LicenseState):
        super().__init__()
        self._state = state

    def run(self):
        try:
            updated = refresh_license(self._state)
            self.finished.emit(updated)
        except Exception as e:
            self.error.emit(str(e))
