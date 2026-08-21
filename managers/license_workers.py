# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
QThread workers for license operations.

Keeps license_manager.py free of PySide6 dependencies (testable without Qt).
Workers follow the same pattern as WikidataWorker, WebSearchWorker, etc.

The desktop app is license-KEY only (mobile parity): the account sign-in path
(email/password and Google OAuth) is retired. Only the two key workers below
remain. license_key.py is imported lazily inside run() so its requests import
is not pulled in until a key is actually being activated or refreshed.
"""

from PySide6.QtCore import QThread, Signal

from managers.license_manager import LicenseError


class KeyValidationWorker(QThread):
    """Background worker for Core/Lite license-key activation.

    Runs apply_license_key() off the UI thread. Imported lazily inside run()
    so managers/license_key.py (and its requests import) is not pulled in until
    a key is actually being activated.
    """

    finished = Signal(object)  # LicenseState
    error = Signal(str)

    def __init__(self, license_key: str):
        super().__init__()
        self._key = license_key

    def run(self):
        try:
            from managers.license_key import apply_license_key
            state = apply_license_key(self._key)
            self.finished.emit(state)
        except LicenseError as e:
            self.error.emit(str(e))
        except Exception as e:
            self.error.emit(f"Unexpected error: {e}")


class LinkActivationWorker(QThread):
    """Background worker for the browser link-activation flow (SPEC-LIC-001).

    Owns one LinkActivationFlow: binds the loopback listener, opens the
    browser, waits for the callback, redeems the code, persists the credential
    pair. All slow parts (the 180 s wait, the exchange POST) run off the GUI
    thread. cancel() is thread-safe and ends the wait promptly.

    Signals (custom names so QThread's own `finished` stays usable for
    deleteLater wiring):
      succeeded(LicenseState)  activation complete and persisted
      failed(str)              user-facing message; existing license untouched
      unavailable(str)         no loopback socket binds: hide the browser path
      open_url_failed(str)     browser did not open; carry the URL so the
                               dialog can show it for hand-opening (the flow
                               keeps listening, so hand-opening still works)
    """

    succeeded = Signal(object)
    failed = Signal(str)
    unavailable = Signal(str)
    open_url_failed = Signal(str)

    _TIMEOUT_MESSAGE = (
        "Activation timed out. If your browser runs on another computer "
        "(remote desktop, VM), the automatic flow cannot reach this app; "
        "use the manual key instead. Otherwise just try again."
    )
    _UNAVAILABLE_MESSAGE = (
        "Automatic activation is unavailable on this computer. "
        "Enter your key instead."
    )

    def __init__(self, flow=None):
        super().__init__()
        # The flow is constructed lazily in run() unless injected (tests);
        # cancel() before run() is honoured via the flag.
        self._flow = flow
        self._cancel_requested = False

    def cancel(self):
        """Thread-safe: abort the flow; no signal is emitted for a cancel."""
        self._cancel_requested = True
        flow = self._flow
        if flow is not None:
            flow.cancel()

    def run(self):
        import webbrowser
        from managers.link_activation import (
            LinkActivationFlow, LinkUnavailableError,
        )
        from managers.license_key import (
            ActivationCancelled, activate_via_link, link_error_message,
        )

        if self._flow is None:
            self._flow = LinkActivationFlow()
        flow = self._flow
        if self._cancel_requested:
            flow.cancel()
            return

        try:
            url = flow.start()
        except LinkUnavailableError:
            self.unavailable.emit(self._UNAVAILABLE_MESSAGE)
            return
        except Exception:
            flow.close()
            self.unavailable.emit(self._UNAVAILABLE_MESSAGE)
            return

        if self._cancel_requested:
            flow.cancel()
            return

        try:
            opened = webbrowser.open(url)
        except Exception:
            opened = False
        if not opened:
            # Keep listening: the user can open the shown URL by hand and the
            # callback still lands (§4.3 row 2).
            self.open_url_failed.emit(url)

        result = flow.run()

        if result.kind == "cancelled":
            return
        if result.kind == "timeout":
            self.failed.emit(self._TIMEOUT_MESSAGE)
            return
        if result.kind == "error":
            self.failed.emit(link_error_message(result.error_slug))
            return

        # result.kind == "code": redeem it. The verifier never left this
        # process (INV-4); a rejection below reports and changes nothing
        # (INV-8). Cancel is honoured right up to the persistence point:
        # checked here before the exchange starts, and again inside
        # activate_via_link after the exchange returns (cancel_check), so a
        # dialog closed during the up-to-20 s POST persists nothing.
        if self._cancel_requested:
            return
        try:
            state = activate_via_link(
                result.code, flow.verifier, flow.state,
                cancel_check=lambda: self._cancel_requested)
        except ActivationCancelled:
            return  # cancel emits nothing, changes nothing
        except LicenseError as e:
            self.failed.emit(str(e))
            return
        except Exception as e:
            self.failed.emit(f"Unexpected error: {type(e).__name__}")
            return
        if self._cancel_requested:
            # Late success after the dialog closed: the credential is validly
            # persisted (the user did approve in the browser), but nobody is
            # listening; do not emit into a dead dialog.
            return
        self.succeeded.emit(state)


class KeyRefreshWorker(QThread):
    """Background worker for the periodic Core/Lite license-KEY re-validation.

    Re-validates the stored license key and enforces the bounded grace window
    on transient failure, so an open session cannot keep access indefinitely
    past expiry or server revocation. Lazy import keeps license_key.py off the
    startup path.
    """

    finished = Signal(object)  # LicenseState
    error = Signal(str)

    def __init__(self, state):
        super().__init__()
        self._state = state

    def run(self):
        try:
            from managers.license_key import refresh_key_license
            updated = refresh_key_license(self._state)
            self.finished.emit(updated)
        except Exception as e:
            self.error.emit(str(e))
