# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Session save health banner (SPEC-SES-001 §4.4).

Replaces the modal "Save Failed" dialog. When session autosave is failing, the
user is not interrupted — they find out here, in Settings, in their own time,
with the real error rather than an invented guess about disk space.

DESIGN RULES THIS WIDGET OBEYS
------------------------------
1. Hidden entirely when health is "ok". No chrome when nothing is wrong.
2. Colour is SEMANTIC (orange = degraded, red = failing). Rule 20 requires
   theme colours from get_theme_colors() and exempts semantic red/green;
   these are that exemption. Everything else — surface, body text — comes
   from the live palette.
3. It states what still works. A user reading "your session is not being
   saved" needs to know in the same breath that their charts are fine and the
   app is not about to eat their work (INV-2).
4. It never blocks. Every action is optional; the banner is informational.

THE PALETTE HAS 8 KEYS AND NONE OF THEM ARE 'border'
----------------------------------------------------
get_theme_colors() returns exactly: primary, primary_dark, primary_light,
primary_text, secondary, secondary_dark, secondary_light, secondary_text.
There is no 'border' and no 'text_primary'. Reaching for either raises
KeyError while the Settings page is being built, i.e. a crash on open.

This widget ends up not needing any of them: see _apply_theme for why a
translucent accent tint beats naming a surface colour.
"""
import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from ui.qt_theme import hex_to_rgb_str
from ui.themed_style import ThemedStyleMixin

# Semantic status colours (Rule 20 exemption — see module docstring).
WARN_ORANGE = "#E8A33D"
ERROR_RED = "#D9534F"

_HEADLINES = {
    "failing": "Your session is not being saved",
    "degraded": "Your session did not save just now",
    "recovered": "Your session failed to save earlier",
    "relocated": "Varuna360 could not use your chosen folder",
}

_BODIES = {
    "failing": (
        "Charts you open now will not be restored the next time you start "
        "Varuna360. Everything else works normally, and your saved chart "
        "files have not been touched."
    ),
    # "degraded" must NOT read like "recovered". The last attempt failed, and
    # the next one is 30 seconds away; saying "working again" here was the
    # bug this state was added to fix.
    "degraded": (
        "The last attempt to save your open charts did not work. Varuna360 "
        "will try again shortly. Everything else works normally."
    ),
    "recovered": (
        "Saving is working again. This is worth reporting if it keeps "
        "happening, because it usually means something else on the computer "
        "is holding the file."
    ),
    "relocated": (
        "Your session is being saved to a temporary location instead, so "
        "nothing is lost. Choose a different folder below to make it "
        "permanent."
    ),
}

# Shown instead of the state body when charts were dropped from the save.
# That is silent permanent loss at the next restore, so it outranks whatever
# else the state has to say.
_SKIPPED_HEADLINE = "Some charts could not be saved"
_SKIPPED_BODY = (
    "{n} of your open charts are missing the data needed to rebuild them, so "
    "they were left out of the saved session and will not come back on "
    "restart. The other charts saved normally. Please report this: it is a "
    "bug in Varuna360, not something you did."
)


def make_report_button(parent=None, health_provider=None):
    """A standalone 'Report a problem…' button for the Settings Paths section.

    The banner hides itself when everything is healthy (by design), which
    would otherwise make reporting reachable only while broken — useless for
    reporting anything else. This button is always available.

    `health_provider` is an optional zero-arg callable returning the current
    SessionManager.health dict, so the report carries live state rather than a
    snapshot frozen at construction time.
    """
    button = QPushButton("Report a problem…", parent)
    button.setToolTip(
        "Send a technical report about a problem. Contains no chart data."
    )

    def _open():
        health = None
        if health_provider is not None:
            try:
                health = health_provider()
            except Exception:
                health = None
        try:
            from ui.bug_report_dialog import BugReportDialog
            BugReportDialog(health=health, parent=button.window()).exec()
        except Exception:
            pass

    button.clicked.connect(_open)
    return button


class SessionHealthBanner(ThemedStyleMixin, QFrame):
    """Warning strip shown at the top of the Settings Paths section.

    Wired by the settings tab::

        banner = SessionHealthBanner()
        banner.attach(gui.session_manager)
        layout.insertWidget(0, banner)
    """

    report_requested = Signal(dict)
    choose_folder_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._health = {"state": "ok"}
        self._manager = None
        self._build_ui()
        self.setVisible(False)

    # -- construction ---------------------------------------------------

    def _build_ui(self):
        self.setFrameShape(QFrame.Shape.NoFrame)
        # Style via objectName, NOT a "SessionHealthBanner { }" type selector.
        # A QSS type selector naming a custom Python class silently matches
        # nothing in PySide6 (Qt resolves type selectors against its own
        # registered class hierarchy), so the banner would render unstyled
        # with no error anywhere. Documented trap in this codebase.
        self.setObjectName("sessionHealthBanner")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(8)

        self.headline = QLabel()
        headline_font = QFont()
        headline_font.setPointSize(11)
        headline_font.setBold(True)
        self.headline.setFont(headline_font)
        self.headline.setWordWrap(True)
        outer.addWidget(self.headline)

        self.body = QLabel()
        self.body.setWordWrap(True)
        body_font = QFont()
        body_font.setPointSize(9)
        self.body.setFont(body_font)
        outer.addWidget(self.body)

        # Monospace detail block: folder, error, time. Selectable, because the
        # first thing anyone does with an error string is copy it.
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        self.detail.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        detail_font = QFont("monospace")
        detail_font.setStyleHint(QFont.StyleHint.Monospace)
        detail_font.setPointSize(8)
        self.detail.setFont(detail_font)
        outer.addWidget(self.detail)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.log_button = QPushButton("Open Log Folder")
        self.log_button.clicked.connect(self._open_log_folder)
        row.addWidget(self.log_button)

        self.folder_button = QPushButton("Choose Another Folder…")
        self.folder_button.clicked.connect(self._choose_folder)
        row.addWidget(self.folder_button)

        self.report_button = QPushButton("Report a problem…")
        self.report_button.clicked.connect(self._open_report_dialog)
        row.addWidget(self.report_button)
        row.addStretch()
        outer.addLayout(row)

        self._apply_theme()

    # -- wiring ---------------------------------------------------------

    def attach(self, session_manager):
        """Subscribe to a SessionManager and render its current state.

        Safe to call with None (the settings page can be built before the
        manager exists) — the banner simply stays hidden.
        """
        self._manager = session_manager
        if session_manager is None:
            # The eager attach from _create_settings_tab can legitimately
            # arrive before ChartGUI.__init__ has assigned session_manager.
            # Retry off the event loop rather than giving up silently, which
            # is what left the banner permanently unwired.
            self.setVisible(False)
            QTimer.singleShot(0, self._try_late_attach)
            return
        try:
            session_manager.add_health_listener(self.update_health)
            self.update_health(session_manager.health)
        except Exception:
            # A manager without the health API (older build, or a test
            # double) must not stop the Settings page from opening.
            self.setVisible(False)

    def _resolve_manager(self):
        """Find the app's SessionManager by walking up to the main window.

        WHY THIS EXISTS. attach_all() is called from the _create_settings_tab
        factory, and the settings tab is built during ChartGUI.__init__ —
        BEFORE self.session_manager is assigned. So the eager attach passed
        None and the banner was never wired to anything: it would have stayed
        invisible in the real app no matter how badly saving was failing,
        while every isolated widget test passed.

        Resolving lazily on first show removes the ordering dependency
        entirely, instead of trying to sequence two lazily-built objects.
        """
        try:
            window = self.window()
            manager = getattr(window, "session_manager", None)
            if manager is None:
                parent = self.parent()
                while parent is not None and manager is None:
                    manager = getattr(parent, "session_manager", None)
                    parent = parent.parent()
            return manager
        except Exception:
            return None

    def _try_late_attach(self, attempts_left=5):
        """Resolve the manager once the event loop is running.

        showEvent is NOT usable for this: the banner starts hidden (correctly,
        since healthy saving shows nothing), and Qt never delivers showEvent
        to a widget that is never shown — so attaching on show would deadlock
        against the very state that needs to make it appear.

        A deferred timer has no such problem. By the time the event loop
        turns, ChartGUI.__init__ has finished and session_manager exists.
        """
        if self._manager is not None:
            return
        manager = self._resolve_manager()
        if manager is not None:
            self.attach(manager)
            return
        if attempts_left > 0:
            QTimer.singleShot(
                250, lambda: self._try_late_attach(attempts_left - 1)
            )

    def update_health(self, health):
        """Render a health snapshot. Never raises."""
        try:
            self._health = dict(health or {})
            state = self._health.get("state", "ok")

            if state == "ok":
                self.setVisible(False)
                return

            skipped = self._health.get("skipped_charts") or 0
            if skipped:
                self.headline.setText(_SKIPPED_HEADLINE)
                self.body.setText(_SKIPPED_BODY.format(n=skipped))
            else:
                self.headline.setText(
                    _HEADLINES.get(state, "Session save problem")
                )
                self.body.setText(_BODIES.get(state, ""))
            self.detail.setText(self._format_detail())
            # Relocation is the only state where offering a new folder helps;
            # in the others the folder is fine and something else is wrong.
            self.folder_button.setVisible(state == "relocated")
            self._apply_theme()
            self.setVisible(True)
        except Exception:
            # Hiding on error is the safe visual outcome, but a warning widget
            # that silently vanishes when IT breaks fails at the one moment it
            # matters, and leaves no trace to debug from. Log before hiding.
            # (This bit during development: a mid-edit run showed the banner
            # hidden in every state and looked like a logic bug.)
            try:
                from core.diagnostics import get_logger
                get_logger("ui").exception(
                    "session health banner failed to render; hiding"
                )
            except Exception:
                pass
            self.setVisible(False)

    def _format_detail(self):
        from core.diagnostics import redact_home

        lines = []
        session_dir = self._health.get("session_dir")
        configured = self._health.get("configured_dir")
        if session_dir:
            lines.append(f"Saving to:  {redact_home(session_dir)}")
        if configured and str(configured) != str(session_dir):
            lines.append(f"You chose:  {redact_home(configured)}")
        error = self._health.get("last_error")
        if error:
            lines.append(f"Problem:    {redact_home(error)}")
        when = self._health.get("last_error_at")
        if when:
            lines.append(f"Since:      {when.replace('T', ' ')}")
        return "\n".join(lines)

    # -- theming --------------------------------------------------------

    def _accent(self):
        # Dropped charts are red regardless of state: it is silent permanent
        # data loss, which is more serious than a save that will retry.
        if self._health.get("skipped_charts"):
            return ERROR_RED
        return ERROR_RED if self._health.get("state") == "failing" else WARN_ORANGE

    def _apply_theme(self):
        """Repaint against the live palette. Called on build and on change.

        THE BACKGROUND IS A TRANSLUCENT ACCENT TINT, NOT A PALETTE COLOUR.

        Naming a surface colour here (the obvious `theme['secondary_dark']`)
        breaks in light themes: it painted a dark slab inside a light Settings
        page. It is also not reliably fixable by copying what the parent tab
        does, because the parent sets its own background with a custom-class
        QSS type selector (`DefaultFoldersTab { ... }`) which silently matches
        NOTHING in PySide6 — so the surface the banner would be matching is
        not the surface actually drawn.

        rgba(accent, 0.12) sidesteps the whole question: it darkens a light
        background and lightens a dark one, and always reads as "this belongs
        to the warning".

        Body and detail text set NO colour at all, so they inherit the
        widget palette Qt already resolved for the current theme. Hardcoding
        a foreground here is how text ends up light-on-light.
        """
        accent = self._accent()
        tint = hex_to_rgb_str(accent)
        self.setStyleSheet(
            f"QFrame#sessionHealthBanner {{"
            f"  background-color: rgba({tint}, 0.12);"
            f"  border: 1px solid {accent};"
            f"  border-left: 4px solid {accent};"
            f"  border-radius: 4px;"
            f"}}"
        )
        self.headline.setStyleSheet(
            f"color: {accent}; background: transparent; border: none;"
        )
        for label in (self.body, self.detail):
            label.setStyleSheet("background: transparent; border: none;")

    def refresh_theme(self):
        """Theme-switch hook (SPEC-THM-001)."""
        self._replay_themed()
        self._apply_theme()

    # -- actions --------------------------------------------------------

    @staticmethod
    def attach_all(settings_tab, session_manager):
        """Attach every banner inside `settings_tab` to `session_manager`.

        Uses findChildren rather than a known attribute path, so the Core
        (`DefaultFoldersTab`) and Pro (`_PathsSection`) placements are handled
        by one implementation and neither can silently lose its wiring by
        being renamed or moved.

        Never raises: a Settings page that opens without a health banner is a
        missing warning; a Settings page that will not open is a broken app.
        """
        try:
            for banner in settings_tab.findChildren(SessionHealthBanner):
                banner.attach(session_manager)
        except Exception:
            pass

    def _choose_folder(self):
        """Pick a new data folder and persist it (SPEC-SES-001, relocated).

        This button is offered ONLY in the relocated state, where the banner
        body tells the user to "choose a different folder below to make it
        permanent" — so it has to actually do that. It previously only
        emitted a signal that nothing in the tree connected: instructions
        pointing at a dead control, in the one state where it is the recovery
        action.

        The signal is still emitted first, so a host can override.
        """
        self.choose_folder_requested.emit()
        try:
            from PySide6.QtWidgets import QFileDialog, QMessageBox
            from state.user_data import set_user_data_dir, get_default_data_dir

            start = str(self._health.get("session_dir")
                        or get_default_data_dir())
            chosen = QFileDialog.getExistingDirectory(
                self.window(), "Choose a folder for Varuna360 data", start
            )
            if not chosen:
                return

            # set_user_data_dir write-probes and raises OSError if unusable,
            # so an unwritable pick is refused here rather than becoming the
            # next silent failure.
            set_user_data_dir(chosen)

            # A modal here is legitimate and does NOT breach INV-1: that
            # invariant forbids dialogs raised BY a save failure on a
            # background timer. This one answers a button the user just
            # pressed, which is the opposite situation.
            QMessageBox.information(
                self.window(),
                "Folder changed",
                f"Varuna360 will use:\n{chosen}\n\n"
                "Restart the app for this to take effect.",
            )
        except OSError as e:
            try:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(
                    self.window(), "Cannot use that folder",
                    f"That folder cannot be written to:\n{e}\n\n"
                    "Please choose another.",
                )
            except Exception:
                pass
        except Exception:
            pass

    def _open_report_dialog(self):
        """Open the bug report dialog, pre-filled with the current health.

        The signal is still emitted, so a host that wants to intercept and
        present its own flow can; the default is to just do the useful thing
        rather than require every call site to wire it up.
        """
        health = dict(self._health)
        self.report_requested.emit(health)
        try:
            from ui.bug_report_dialog import BugReportDialog
            BugReportDialog(health=health, parent=self.window()).exec()
        except Exception:
            pass

    def _open_log_folder(self):
        """Open the diagnostics log folder in the platform file manager."""
        try:
            from core.diagnostics import log_path, _log_root
            target = log_path()
            folder = Path(target).parent if target else _log_root()
            folder.mkdir(parents=True, exist_ok=True)

            if sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            elif os.name == "nt":
                os.startfile(str(folder))  # noqa: S606 — Windows-only API
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception:
            # Opening a file manager is a convenience. If the desktop has no
            # handler, the path is already printed in the detail block.
            pass
