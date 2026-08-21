# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
License-key dialog for Varuna360 Core/Lite.

The desktop app does not sign users in. The account owner activates with
their 360heartsinthesky.com license KEY, two ways (SPEC-LIC-001):
  * "Activate with my browser": the loopback link flow fetches the key
    automatically, no copy-paste (LinkActivationWorker).
  * the manual field: paste the key copied from the account page.
Both paths store the same credential pair; the app exchanges the key for a
signed token and verifies that token offline. This dialog is the only
activation UI in the app.

It has three visible states:
  * no license  -> the paste-key form
  * on trial    -> the form plus a gold "Free trial: N days left" line
  * licensed    -> a green confirmation, either the success view shown right
                   after a successful activation, or a status card at the top
                   when the dialog is reopened later

The confirmation states exist so a paying customer gets unambiguous proof the
purchase landed: a green check, the plan they are on, and how long it runs.

Network validation runs on a KeyValidationWorker so the UI never blocks.
"""

import webbrowser
from datetime import datetime

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QWidget,
)
from PySide6.QtCore import Qt, Signal

from ui.qt_theme import (
    BG, SURFACE, BORDER, TEXT_PRIMARY, TEXT_SECONDARY, GOLD, STATUS,
    get_primary_button_style,
    scaled_area_font, scaled_area_px,
)
from managers.license_manager import LicenseState


ACCOUNT_URL = "https://360heartsinthesky.com/account#desktop-key"
SUBSCRIBE_URL = "https://360heartsinthesky.com/subscribe"

# Semantic success green (Rule 20 allows the semantic red/green pair).
SUCCESS = STATUS["success"]

# Signed token `tier` claims mapped to the plan name a customer recognises.
# The token carries "subscriber" for a paying Explorateur customer and "vip"
# for an admin/complimentary account; neither string means anything to a user.
_TIER_DISPLAY = {
    "subscriber": "Explorateur",
    "vip": "Complimentary access",
    "trial": "Free trial",
}


def _tier_display_name(tier: str) -> str:
    """Return the customer-facing plan name for a signed tier claim."""
    key = str(tier or "").strip().lower()
    return _TIER_DISPLAY.get(key, key.title() if key else "Active")


def _format_valid_until(value) -> str:
    """Format an ISO date string as a readable date, or "" if not usable.

    STRICT on purpose: anything that is not a parseable ISO string returns "",
    so a caller can fall back to a safe label. Echoing unparseable input back
    would put whatever the server sent straight into a "Valid until ..." row.
    """
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not text:
        return ""
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return ""
    return dt.strftime("%d %B %Y")


def _subscription_end(state) -> str:
    """Return the SUBSCRIPTION end date to show the customer, or "".

    Deliberately NOT LicenseState.valid_until. That field carries the signed
    token's `exp`, which is a re-verification deadline (the desktop token is
    issued for 7 days and the app silently re-checks), not the date the
    subscription runs out. Showing it as "Valid until" tells a customer who paid
    for a year that their license dies next week, which is the opposite of the
    reassurance this dialog exists to give.

    A true period end (Stripe's current_period_end) is not in the token or the
    validate-key response today. When the backend starts sending one, exposing it
    on LicenseState under either name below makes this dialog show
    "Valid until <date>" with no further change here.

    Fails closed: a value that is not a parseable ISO string is skipped (the
    next attribute is tried, then ""), so malformed server data can never be
    echoed into a "Valid until ..." row, and a value whose __str__ raises is
    never stringified at all.
    """
    for attr in ("subscription_until", "current_period_end"):
        try:
            raw = getattr(state, attr, "")
        except Exception:
            continue  # a property that raises must not break the dialog
        formatted = _format_valid_until(raw)
        if formatted:
            return formatted
    return ""


class KeyDialog(QDialog):
    """License-key activation dialog for Varuna360 Core/Lite."""

    activated = Signal(object)  # emits LicenseState

    def __init__(
        self,
        parent=None,
        message: str = "",
        show_continue_without_account: bool = True,
        trial_days_left: int = 0,
        license_state=None,
    ):
        """Initialize the key dialog.

        Args:
            parent: optional Qt parent widget.
            message: optional message rendered above the field (e.g. a
                rejected-activation reason).
            show_continue_without_account: when True (default) a
                "Continue without a key" text button lets the user dismiss
                the dialog. Set to False in the pre-main() bundled flow,
                where declining means the app exits and a "Continue" label
                would promise behavior the caller does not deliver.
            trial_days_left: whole days remaining in the no-key free trial.
                When positive, a "Free trial: N days left" status line is
                shown (the same countdown the mobile app displays), so a user
                still inside the trial can see how long they have before a key
                is required. Zero (the default, and the trial-ended boot case)
                shows no trial line.
            license_state: the session's current LicenseState, when there is
                one. If it is already licensed by a KEY (not the trial), a green
                "License active" card is shown at the top with the plan and the
                valid-until date, so reopening this dialog confirms the purchase
                instead of presenting a blank box.
        """
        super().__init__(parent)
        self.setWindowTitle("Activate Varuna360")
        self.setModal(True)
        self._license_state = None
        self._link_worker = None
        self._show_continue_without_account = show_continue_without_account
        # Coerce defensively: this is a public kwarg and the value may arrive
        # from a deserialized state. Any non-numeric/NaN/infinite input fails
        # closed to 0 (no countdown line) rather than crashing construction.
        try:
            self._trial_days_left = max(0, int(trial_days_left or 0))
        except (TypeError, ValueError, OverflowError):
            self._trial_days_left = 0

        # An existing KEY license (the trial is shown by its own countdown line).
        self._existing_license = None
        if (license_state is not None
                and getattr(license_state, "is_licensed", False)
                and not getattr(license_state, "is_trial", False)):
            self._existing_license = license_state

        self.setFixedSize(420, 630 if self._existing_license else 560)

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {BG};
            }}
            QLabel {{
                color: {TEXT_PRIMARY};
            }}
        """)

        self._build_ui(message)

    # ── construction ────────────────────────────────────────────────────

    def _build_ui(self, message: str):
        # The form lives in its own container so a successful activation can
        # swap the whole thing out for the success view without rebuilding
        # the dialog or leaving stale widgets behind.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._form_widget = QWidget()
        outer.addWidget(self._form_widget)

        layout = QVBoxLayout(self._form_widget)
        layout.setSpacing(12)
        layout.setContentsMargins(40, 30, 40, 30)

        title = QLabel("Varuna360")
        title.setFont(scaled_area_font('panel_titles', bold=True))
        title.setStyleSheet(f"color: {GOLD};")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel(
            "Your license is active" if self._existing_license
            else "Activate on this computer"
        )
        subtitle.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: {scaled_area_px('status')}px;")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        layout.addSpacing(10)

        if self._existing_license is not None:
            layout.addWidget(self._build_status_card(self._existing_license))
            layout.addSpacing(4)

        if self._trial_days_left > 0:
            unit = "day" if self._trial_days_left == 1 else "days"
            trial_label = QLabel(f"Free trial: {self._trial_days_left} {unit} left")
            trial_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            trial_label.setStyleSheet(
                f"color: {GOLD}; font-size: {scaled_area_px('buttons')}px; "
                f"font-weight: bold; padding: 8px; "
                f"background-color: rgba(212, 175, 55, 0.12); border-radius: 4px;"
            )
            layout.addWidget(trial_label)
            layout.addSpacing(4)

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

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"background-color: {BORDER};")
        line.setFixedHeight(1)
        layout.addWidget(line)

        layout.addSpacing(5)

        # ── Automatic path: browser link activation (SPEC-LIC-001) ──
        # The primary path for the normal case: one click, no copy-paste.
        # Lives in its own container so an unbindable loopback can hide the
        # whole section while the manual field below stays fully usable
        # (INV-3: the manual path is never removed or degraded).
        self._browser_section = QWidget()
        bs_layout = QVBoxLayout(self._browser_section)
        bs_layout.setContentsMargins(0, 0, 0, 0)
        bs_layout.setSpacing(6)

        self.browser_btn = QPushButton("Activate with my browser")
        self.browser_btn.setStyleSheet(get_primary_button_style())
        self.browser_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.browser_btn.clicked.connect(self._on_browser_clicked)
        bs_layout.addWidget(self.browser_btn)

        or_label = QLabel("or enter your key manually")
        or_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        or_label.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: {scaled_area_px('status')}px;"
        )
        bs_layout.addWidget(or_label)

        layout.addWidget(self._browser_section)

        # Shown only when the browser refuses to open: the same activation URL
        # for hand-opening; the listener keeps running so it still works.
        self.link_url_label = QLabel("")
        self.link_url_label.setWordWrap(True)
        self.link_url_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.link_url_label.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: {scaled_area_px('status')}px; "
            f"padding: 6px; background-color: rgba(212, 175, 55, 0.10); "
            f"border-radius: 4px;"
        )
        self.link_url_label.hide()
        layout.addWidget(self.link_url_label)

        key_label = QLabel(
            "Enter a different key" if self._existing_license else "License key"
        )
        key_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: {scaled_area_px('buttons')}px;")
        layout.addWidget(key_label)

        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText("VARD-XXXX-XXXX-XXXX-XXXX")
        self.key_input.setStyleSheet(self._input_style())
        self.key_input.returnPressed.connect(self._on_activate_clicked)
        layout.addWidget(self.key_input)

        # This is the NORMAL way to obtain a key, not an FAQ footnote: it opens
        # the account page the key is copied from. Worded and coloured as the
        # call to action it is.
        find_key_btn = QPushButton("Click here to get my key")
        find_key_btn.setFlat(True)
        find_key_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        find_key_btn.setStyleSheet(
            f"color: {GOLD}; font-size: {scaled_area_px('buttons')}px; text-align: left; "
            f"border: none; padding: 0; text-decoration: underline; font-weight: bold;"
        )
        find_key_btn.clicked.connect(lambda: webbrowser.open(ACCOUNT_URL))
        layout.addWidget(find_key_btn)

        layout.addSpacing(10)

        self.activate_btn = QPushButton("Activate")
        self.activate_btn.setStyleSheet(get_primary_button_style())
        self.activate_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.activate_btn.clicked.connect(self._on_activate_clicked)
        layout.addWidget(self.activate_btn)

        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet(f"color: #E57373; font-size: {scaled_area_px('status')}px;")
        self.error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.error_label.hide()
        layout.addWidget(self.error_label)

        layout.addStretch()

        if self._show_continue_without_account:
            continue_btn = QPushButton(
                "Close" if self._existing_license else "Continue without a key"
            )
            continue_btn.setFlat(True)
            continue_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            continue_btn.setStyleSheet(
                f"color: {TEXT_SECONDARY}; font-size: {scaled_area_px('status')}px; border: none; "
                f"text-decoration: underline;"
            )
            continue_btn.clicked.connect(self.reject)
            layout.addWidget(continue_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"background-color: {BORDER};")
        sep2.setFixedHeight(1)
        layout.addWidget(sep2)

        subscribe_layout = QHBoxLayout()
        no_key_label = QLabel(
            "Manage your subscription" if self._existing_license else "No key yet?"
        )
        no_key_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: {scaled_area_px('status')}px;")
        subscribe_layout.addWidget(no_key_label)

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

    def _build_status_card(self, state) -> QWidget:
        """Compact green "License active" card for an already-licensed session."""
        card = QFrame()
        card.setObjectName("licenseStatusCard")
        card.setStyleSheet(
            f"QFrame#licenseStatusCard {{ border: 1px solid {SUCCESS}; "
            f"border-radius: 6px; background-color: rgba(76, 175, 80, 0.10); }}"
        )
        row = QHBoxLayout(card)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(10)

        check = QLabel("✓")
        check.setStyleSheet(
            f"color: {SUCCESS}; font-size: {scaled_area_px('panel_titles')}px; "
            f"font-weight: bold; border: none; background: transparent;"
        )
        row.addWidget(check, alignment=Qt.AlignmentFlag.AlignTop)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        headline = QLabel("License active")
        headline.setStyleSheet(
            f"color: {SUCCESS}; font-size: {scaled_area_px('buttons')}px; "
            f"font-weight: bold; border: none; background: transparent;"
        )
        text_col.addWidget(headline)

        detail_bits = [_tier_display_name(getattr(state, "tier", ""))]
        until = _subscription_end(state)  # never the token's re-check deadline
        if until:
            detail_bits.append(f"valid until {until}")
        else:
            detail_bits.append("checked automatically")
        detail = QLabel("  ·  ".join(detail_bits))
        detail.setWordWrap(True)
        detail.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: {scaled_area_px('status')}px; "
            f"border: none; background: transparent;"
        )
        text_col.addWidget(detail)

        row.addLayout(text_col, 1)
        return card

    def _build_success_widget(self, state) -> QWidget:
        """Full-panel activation confirmation shown right after a key is accepted.

        This is the moment a paying customer needs reassurance, so it is
        deliberately generous: a big green check, an unambiguous headline, and
        the concrete facts of what they now have.
        """
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)
        layout.setContentsMargins(40, 30, 40, 30)

        layout.addStretch()

        badge = QLabel("✓")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedSize(72, 72)
        badge.setStyleSheet(
            f"color: {SUCCESS}; font-size: 40px; font-weight: bold; "
            f"border: 3px solid {SUCCESS}; border-radius: 36px; "
            f"background-color: rgba(76, 175, 80, 0.12);"
        )
        layout.addWidget(badge, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addSpacing(6)

        headline = QLabel("License activated")
        headline.setFont(scaled_area_font('panel_titles', bold=True))
        headline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        headline.setStyleSheet(f"color: {SUCCESS};")
        layout.addWidget(headline)

        blurb = QLabel("Thank you. Varuna360 is unlocked on this computer.")
        blurb.setWordWrap(True)
        blurb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        blurb.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: {scaled_area_px('status')}px;"
        )
        layout.addWidget(blurb)

        layout.addSpacing(12)

        details = QFrame()
        details.setObjectName("activationDetails")
        details.setStyleSheet(
            f"QFrame#activationDetails {{ border: 1px solid {BORDER}; "
            f"border-radius: 6px; background-color: {SURFACE}; }}"
        )
        dcol = QVBoxLayout(details)
        dcol.setContentsMargins(16, 12, 16, 12)
        dcol.setSpacing(8)

        rows = [("Plan", _tier_display_name(getattr(state, "tier", "")))]
        until = _subscription_end(state)
        # Only show a date when it is a REAL subscription end (see
        # _subscription_end). Otherwise say the license is active, rather than
        # printing the token's short re-check deadline as an expiry date.
        rows.append(("Valid until", until) if until else ("Status", "Active"))
        email = str(getattr(state, "email", "") or "").strip()
        if email:
            rows.append(("Account", email))
        rows.append(("Device", "This computer"))

        for label_text, value_text in rows:
            line = QHBoxLayout()
            lab = QLabel(label_text)
            lab.setStyleSheet(
                f"color: {TEXT_SECONDARY}; font-size: {scaled_area_px('status')}px; "
                f"border: none; background: transparent;"
            )
            val = QLabel(value_text)
            val.setStyleSheet(
                f"color: {TEXT_PRIMARY}; font-size: {scaled_area_px('status')}px; "
                f"font-weight: bold; border: none; background: transparent;"
            )
            val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            line.addWidget(lab)
            line.addStretch()
            line.addWidget(val)
            dcol.addLayout(line)

        layout.addWidget(details)

        layout.addSpacing(8)

        note = QLabel(
            "Your subscription is checked automatically. Varuna360 keeps "
            "working offline between checks."
        )
        note.setWordWrap(True)
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        note.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: {scaled_area_px('status')}px;"
        )
        layout.addWidget(note)

        layout.addSpacing(12)

        self.done_btn = QPushButton("Start using Varuna360")
        self.done_btn.setStyleSheet(get_primary_button_style())
        self.done_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.done_btn.clicked.connect(self.accept)
        layout.addWidget(self.done_btn)

        layout.addStretch()
        return page

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

    # ── browser link activation (SPEC-LIC-001) ─────────────────────────

    _BROWSER_IDLE_TEXT = "Activate with my browser"
    _BROWSER_WAITING_TEXT = "Waiting for your browser... click to cancel"

    def _set_manual_enabled(self, enabled: bool):
        """Enable/disable the manual key path while a browser flow runs.

        One active flow per DIALOG, not per path: if both paths could run at
        once, two workers could validate concurrently and the dialog could
        emit two activations while disk holds whichever pair won the commit.
        """
        self.key_input.setEnabled(enabled)
        self.activate_btn.setEnabled(enabled)

    def _on_browser_clicked(self):
        """Start the loopback flow, or cancel the one in progress.

        One active flow per dialog (INV-9): while a flow runs, the primary
        button IS the cancel button, so a second flow cannot start without the
        first being cancelled, the MANUAL path is disabled for the duration,
        and every signal handler checks the worker's identity so a stale
        flow's late result is discarded.
        """
        if self._link_worker is not None:
            self._cancel_link_flow()
            return

        self.error_label.hide()
        self.link_url_label.hide()
        self._set_manual_enabled(False)

        from managers.license_workers import LinkActivationWorker
        worker = LinkActivationWorker()
        self._link_worker = worker
        worker.succeeded.connect(
            lambda state, w=worker: self._on_link_success(w, state))
        worker.failed.connect(
            lambda msg, w=worker: self._on_link_failed(w, msg))
        worker.unavailable.connect(
            lambda msg, w=worker: self._on_link_unavailable(w, msg))
        worker.open_url_failed.connect(
            lambda url, w=worker: self._on_link_url_fallback(w, url))
        # QThread's own finished (run() returned) drives deletion, so a
        # cancelled worker that outlives the dialog still cleans itself up.
        worker.finished.connect(worker.deleteLater)
        self.browser_btn.setText(self._BROWSER_WAITING_TEXT)
        worker.start()

    def _cancel_link_flow(self):
        worker = self._link_worker
        self._link_worker = None
        if worker is not None:
            worker.cancel()
        self.browser_btn.setText(self._BROWSER_IDLE_TEXT)
        self.link_url_label.hide()
        self._set_manual_enabled(True)

    def _is_current_link(self, worker) -> bool:
        return (not getattr(self, "_closed", False)
                and worker is self._link_worker)

    def _on_link_success(self, worker, state):
        if not self._is_current_link(worker):
            return  # stale flow or dialog already dismissed (INV-9)
        self._link_worker = None
        self.browser_btn.setText(self._BROWSER_IDLE_TEXT)
        self.link_url_label.hide()
        self._license_state = state
        self.activated.emit(state)
        self._show_success_view(state)

    def _on_link_failed(self, worker, msg):
        if not self._is_current_link(worker):
            return
        self._link_worker = None
        self.browser_btn.setText(self._BROWSER_IDLE_TEXT)
        self.link_url_label.hide()
        self._set_manual_enabled(True)
        self._show_error(msg)

    def _on_link_unavailable(self, worker, msg):
        if not self._is_current_link(worker):
            return
        self._link_worker = None
        self._set_manual_enabled(True)
        # No loopback socket on this machine: the automatic path cannot work
        # here, so hide it rather than offer a button that always fails. The
        # manual field stays (INV-3, failure matrix row 1).
        self._browser_section.hide()
        self._show_error(msg)

    def _on_link_url_fallback(self, worker, url):
        if not self._is_current_link(worker):
            return
        # The worker stays current: the flow is still listening, and opening
        # this address by hand completes it normally.
        self.link_url_label.setText(
            "Your browser did not open. Visit this address to continue:\n"
            f"{url}"
        )
        self.link_url_label.show()

    # ── activation ──────────────────────────────────────────────────────

    def _on_activate_clicked(self):
        key = self.key_input.text().strip()
        if not key:
            self._show_error("Please paste your license key.")
            return

        self.activate_btn.setEnabled(False)
        self.activate_btn.setText("Activating...")
        # One active flow per dialog: no browser flow while a manual
        # validation runs (mirror of _set_manual_enabled).
        self.browser_btn.setEnabled(False)
        self.error_label.hide()

        from managers.license_workers import KeyValidationWorker
        self._key_worker = KeyValidationWorker(key)
        self._key_worker.finished.connect(self._on_activate_success)
        self._key_worker.error.connect(self._on_activate_error)
        self._key_worker.start()

    def _on_activate_success(self, state):
        if getattr(self, "_closed", False):
            return  # dialog already dismissed; do not mutate state
        self._license_state = state
        self._cleanup_worker()
        self.activated.emit(state)
        # Show the confirmation instead of vanishing: the user just paid, and a
        # dialog that simply closes gives them nothing to trust. The dialog is
        # accepted when they dismiss the success view (see reject(), which
        # upgrades any dismissal to accept once a license has been obtained).
        self._show_success_view(state)

    def _show_success_view(self, state):
        """Swap the paste-key form for the activation confirmation."""
        self._form_widget.hide()
        self._success_widget = self._build_success_widget(state)
        self.layout().addWidget(self._success_widget)

    def _on_activate_error(self, msg: str):
        if getattr(self, "_closed", False):
            return
        self._cleanup_worker()
        self._show_error(msg)
        self.activate_btn.setEnabled(True)
        self.activate_btn.setText("Activate")
        # Manual flow over: the browser path is available again (unless it was
        # hidden as unavailable, in which case re-enabling a hidden button is
        # a no-op).
        self.browser_btn.setEnabled(True)

    def _cleanup_worker(self):
        worker = getattr(self, "_key_worker", None)
        if worker is not None:
            worker.deleteLater()
            self._key_worker = None

    def _show_error(self, msg: str):
        self.error_label.setText(msg)
        self.error_label.show()

    def reject(self):
        """Handle dialog close — disconnect and clean up any running worker.

        Sets _closed so a worker that finishes after the dialog is dismissed
        cannot mutate dialog state or accept it. A successful activation whose
        signal lands after close still persists the (valid) token+key to disk;
        that is benign because the user did present a valid key.

        If a license WAS obtained in this dialog, any dismissal (the success
        view's button, Escape, or the window close box) resolves as ACCEPTED.
        Callers gate on the accepted/rejected result, and the boot gate exits
        the app on a rejection: closing the window after a successful
        activation must never be read as "declined".
        """
        self._closed = True
        # Cancel a running browser flow: the listener shuts down and the port
        # is released; a late result finds _closed/_link_worker mismatched and
        # mutates nothing (INV-9, §4.3 "dialog closed mid-flow"). The worker
        # deletes itself via its finished signal, so an exchange already in
        # flight is allowed to run to completion detached rather than being
        # destroyed while running.
        link_worker = self._link_worker
        self._link_worker = None
        if link_worker is not None:
            link_worker.cancel()
            if link_worker.isRunning():
                link_worker.wait(3000)
        worker = getattr(self, '_key_worker', None)
        if worker is not None:
            try:
                worker.finished.disconnect()
                worker.error.disconnect()
            except RuntimeError:
                pass
            if worker.isRunning():
                worker.wait(2000)
            worker.deleteLater()
            self._key_worker = None
        if self._license_state is not None:
            super().accept()
            return
        super().reject()

    def get_license_state(self) -> LicenseState:
        """Return the LicenseState produced by a successful activation, or None."""
        return self._license_state
