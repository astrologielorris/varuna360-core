"""APP DIALOGS (help / about / license) cluster, extracted from ChartGUI (Stage 1b, move-only).

Move-only mixin per the split-investigation plan Option 4 (see
proprietary_docs/docs/god_object_decomposition/). Method BODIES are moved
byte-identically (AST-identical); ChartGUI inherits this mixin so every
self.* resolves unchanged via the MRO and no self.gui.* write is created.
Imports are MODULE-TOP here (not method-local) to preserve body byte-identity
— the Kala mixin needed zero top-level imports, this cluster references
module-level names, so they are imported at module top and cycle-checked.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox


class AppDialogsMixin:
    """APP DIALOGS (help / about / license) behaviour for ChartGUI (see module docstring)."""

    def _show_manual(self):
        """Open the help manual dialog (singleton — only one instance at a time)."""
        if hasattr(self, '_help_dialog') and self._help_dialog is not None:
            self._help_dialog.raise_()
            self._help_dialog.activateWindow()
            return
        from apps.widgets.help_dialog import HelpDialog
        self._help_dialog = HelpDialog(parent=self)
        self._help_dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._help_dialog.destroyed.connect(lambda: setattr(self, '_help_dialog', None))
        self._help_dialog.show()

    def _show_about(self):
        """Show about dialog."""
        from core.bug_report import app_version
        QMessageBox.about(
            self,
            "About Varuna360",
            "<h2>Varuna360</h2>"
            "<p><b>Tropical Vedic Astrology</b></p>"
            f"<p>Version: {app_version()}</p>"
            "<p>A professional astrology chart calculator combining the "
            "Aditya Circle system with Tropical Western and Sidereal "
            "astrology, powered by Swiss Ephemeris calculations.</p>"
            "<p>Default settings follow Ernst Wilhelm's Tropical Vedic approach. "
            "Classic Western and Sidereal options are also available.</p>"
            "<p><i>&copy; 2024-2026 Lorris Turpin / 360 Hearts in the Sky</i></p>"
            "<p>License: AGPL-3.0</p>"
        )

    def _show_about_pro(self):
        """Show the About-Varuna360-Pro static marketing dialog.

        This is the SINGLE point of Pro awareness in the Core GUI. All
        content is read from core/pro_marketing.py — pure constants, no
        runtime detection of whether Pro is installed. The dialog renders
        the same content regardless of whether the user has Pro or not.
        """
        from core.pro_marketing import (
            PRO_UPGRADE_URL,
            PRO_TAGLINE,
            PRO_DESCRIPTION,
            PRO_FEATURES,
            PRO_PRICE_DISPLAY,
        )

        feature_list_html = "".join(
            f"<li>{feature}</li>" for feature in PRO_FEATURES
        )

        # Use QMessageBox.about() so the dialog gets the standard "info"
        # styling, supports rich-text rendering of HTML, and exposes the
        # URL as a clickable link via Qt's automatic <a href> handling.
        QMessageBox.about(
            self,
            "About Varuna360 Pro",
            f"<h2>Varuna360 Pro</h2>"
            f"<p><b>{PRO_TAGLINE}</b></p>"
            f"<p>{PRO_DESCRIPTION}</p>"
            f"<h3>Pro features</h3>"
            f"<ul>{feature_list_html}</ul>"
            f"<p><b>Pricing:</b> {PRO_PRICE_DISPLAY}</p>"
            f'<p><a href="{PRO_UPGRADE_URL}">{PRO_UPGRADE_URL}</a></p>'
            f"<p><i>Varuna360 Core is and remains open source under AGPL-3.0. "
            f"Pro is the larger paid edition, also AGPL-3.0, for users who "
            f"want the additional research tooling.</i></p>"
        )

    # ──────────────────────────────────────────────────────────────────
    # License menu handlers (top-level License menu — sibling of Help)
    # ──────────────────────────────────────────────────────────────────

    def _show_key_dialog(self):
        """Open the paste-key dialog from the License menu.

        The desktop has no account: the user pastes a license key copied from
        their 360heartsinthesky.com account. On success the LicenseState is
        stashed on the window so the periodic key-refresh worker picks it up;
        if the dialog is closed, nothing changes.
        """
        from apps.widgets.key_dialog import KeyDialog
        dialog = KeyDialog(
            parent=self,
            trial_days_left=self._trial_days_left(),
            license_state=getattr(self, "_license_state", None),
        )
        if dialog.exec() == KeyDialog.DialogCode.Accepted:
            state = dialog.get_license_state()
            # Accepted with no state means the user dismissed an already-licensed
            # dialog without entering a new key; keep the session's state.
            if state is not None:
                self._license_state = state

    def _trial_days_left(self) -> int:
        """Whole days remaining in the no-key free trial, or 0 when not on trial.

        Reads the LicenseState already resolved at boot / by the periodic
        refresh; makes no engine or server call. Returns 0 for a licensed build
        and for the anonymous source path (where _license_state is None).
        """
        state = getattr(self, "_license_state", None)
        if state is not None and getattr(state, "is_trial", False):
            try:
                return max(0, int(getattr(state, "trial_days_left", 0) or 0))
            except (TypeError, ValueError, OverflowError):
                return 0
        return 0

    def _refresh_license_menu_status(self):
        """Show the current license status in the License menu.

        A disabled status item reports either the trial countdown ("Free trial:
        N days left") or, for a key-licensed session, a green-check confirmation
        ("License active: Explorateur"). This gives an always-reachable proof of
        purchase that mirrors the mobile app, without adding a toolbar row.
        Hidden when there is no license and no trial.
        """
        action = getattr(self, "_trial_status_action", None)
        if action is None:
            return
        days = self._trial_days_left()
        if days > 0:
            unit = "day" if days == 1 else "days"
            action.setText(f"Free trial: {days} {unit} left")
            action.setVisible(True)
            return
        state = getattr(self, "_license_state", None)
        if state is not None and getattr(state, "is_licensed", False):
            from apps.widgets.key_dialog import _tier_display_name
            action.setText(
                f"✓ License active: {_tier_display_name(getattr(state, 'tier', ''))}"
            )
            action.setVisible(True)
            return
        action.setVisible(False)

    def _show_tier_dialog(self):
        """Open the plans comparison dialog (singleton, non-modal)."""
        if hasattr(self, '_tier_dialog') and self._tier_dialog is not None:
            self._tier_dialog.raise_()
            self._tier_dialog.activateWindow()
            return
        from apps.widgets.tier_dialog import TierDialog
        self._tier_dialog = TierDialog(parent=self)
        self._tier_dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._tier_dialog.destroyed.connect(
            lambda: setattr(self, '_tier_dialog', None)
        )
        self._tier_dialog.show()
