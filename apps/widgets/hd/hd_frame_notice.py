"""apps/widgets/hd/hd_frame_notice.py — the Beginner frame lock, made visible.

Human Design is pinned to the Standard frame in Beginner mode (the default):
``managers.hd_manager.HDManager.frame()`` returns ``"standard"`` whatever the
top-bar zodiac buttons say. Until now that pin was SILENT. Clicking Aditya
Circle moved every other view, recomputed the bodygraph to the identical model,
and said nothing, so the page looked broken rather than locked (Lorris,
2026-08-29: "I can click on the Aditya circle when I'm in beginner mode and I
shouldn't be able to for the human design").

This module is the visible half of that lock, and nothing else:

  * ``maybe_warn_frame_locked(gui)`` is the ONE call the zodiac-mode handler
    makes. It shows the notice when, and only when, the user is in Beginner AND
    Human Design is actually on screen AND they have not muted it. Every other
    time it returns False and costs a dictionary lookup.
  * ``explain_frames(parent)`` is the same text without the mute box, for the
    link in Settings.
  * The mute is one setting, ``ui.hd_frame_notice_hidden``, written only by the
    checkbox.

Decisions taken by Lorris (2026-08-29), so a later session does not re-open them:
  * NO lock indicator on the bodygraph page itself. The lock is explained in
    Settings; the page stays clean.
  * The notice fires EVERY time a zodiac button is clicked, not once per
    session, with a "do not show this again" box for people who have read it.
  * The 88 degree Design chart is covered by the same lock, so the notice fires
    for it too (``gui.is_human_design``), not only for the bodygraph page.

Rule 4b: this module writes no ``gui.*`` attribute. It reads the settings store
and two read-only facts off the GUI.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QLabel, QVBoxLayout,
)

from ui.qt_theme import scaled_area_px
from ui.popup_fonts import tier_px

EXPERIENCE_KEY = "ui.hd_experience_level"
MUTED_KEY = "ui.hd_frame_notice_hidden"

# The manual section the "Read the manual" button lands on. HelpDialog scrolls
# by HEADING TEXT (see help_dialog._on_toc_clicked), not by anchor, so this is
# the heading string, and it must keep matching the <h2> in docs/help/manual.html.
MANUAL_SECTION = "Human Design"

# ---------------------------------------------------------------------------
# COPY. Every string a user reads is written by the orchestrator session and
# reviewed by Lorris, then pasted in here verbatim (standing rule, 2026-08-29).
# This session writes none of it. The four below are placeholders and MUST NOT
# ship: test_the_copy_is_still_pending is an xfail(strict) that turns red the
# moment real copy lands, so the marker cannot be forgotten either way.
# The button labels below are the orchestrator's own, already given.
# ---------------------------------------------------------------------------
PLACEHOLDER = "[COPY PENDING]"

_BODY = (
    "Human Design is locked to the Tropical Classic frame while your experience "
    "level is Beginner. Your astrology chart follows the button you clicked; the "
    "bodygraph and the Design chart stay on Tropical Classic.\n\n"
    "Why the lock: Human Design has astrology inside it. Its creator wrote in his "
    "first book that the Design chart is calculated 88 degrees of the Sun before "
    "birth, which is a planetary calculation. Yet most Human Design teaching uses "
    "little or no astrology, and its creator said himself that he knew little of "
    "it. So whether Human Design should follow a different zodiac frame, and "
    "whether it works in practice at all, is an open question that people "
    "disagree about. Every Human Design website shows a Tropical Classic chart, "
    "and a beginner who sees an Aditya Circle or Sidereal bodygraph will get "
    "lost.\n\n"
    "If you already know Human Design and want to test the other frames, switch "
    "the experience level to Advanced in Settings > Zodiac > Human Design. The "
    "manual explains the three frames and what changes between them."
)
NOTICE_TITLE = "Human Design and the zodiac frame"
NOTICE_BODY = _BODY
EXPLAIN_TITLE = "Human Design and the zodiac frame"
EXPLAIN_BODY = _BODY

MUTE_LABEL = "Do not show this again"
MANUAL_LABEL = "Open the manual"
SETTINGS_LABEL = "Open Settings"


def copy_is_pending() -> bool:
    """True while any reader-facing string here is still the placeholder.

    A placeholder must never reach a screen. Marking the strings was not
    enough: on 2026-08-30 "[COPY PENDING]" shipped to main as the visible
    label of the Settings link and Lorris met it in his running app. So the
    check is enforced in code rather than left to each caller to remember, and
    every surface that would show one of these strings asks this first.
    """
    return PLACEHOLDER in (NOTICE_TITLE, NOTICE_BODY, EXPLAIN_TITLE, EXPLAIN_BODY)

# The Settings tab's title in the main tab bar (core_gui_qt.py:954). Matched by
# text rather than by index: the Debug tab is conditional, so the index moves.
SETTINGS_TAB_TITLE = "Settings"


# ---- settings ---------------------------------------------------------------
def _settings():
    """The settings store, or None when it cannot be reached.

    Every reader below treats None as "assume the safe answer" rather than
    raising: this module is called from a signal handler, where an exception
    would leave the app with a half-applied zodiac switch.
    """
    try:
        from managers.settings_manager import get_settings
        return get_settings()
    except Exception:
        return None


def is_beginner() -> bool:
    """True when Human Design is pinned to Standard (the default).

    Mirrors ``managers.hd_manager._hd_is_advanced`` inverted, and defaults to
    Beginner for an absent or unreadable setting exactly as the manager does,
    so the notice can never disagree with the pin it is describing.
    """
    settings = _settings()
    if settings is None:
        return True
    try:
        return settings.get(EXPERIENCE_KEY, "beginner") != "advanced"
    except Exception:
        return True


def notice_is_muted() -> bool:
    """True when the reader ticked "do not show this again"."""
    settings = _settings()
    if settings is None:
        return False
    try:
        return bool(settings.get(MUTED_KEY, False))
    except Exception:
        return False


def mute_notice(muted: bool = True) -> None:
    """Remember the checkbox. Silent on a settings failure, as above."""
    settings = _settings()
    if settings is None:
        return
    try:
        settings.set(MUTED_KEY, bool(muted))
    except Exception:
        pass


# ---- "is Human Design actually in front of the reader" -----------------------
def human_design_is_on_screen(gui) -> bool:
    """True when the bodygraph page is current OR the 88 degree mode is on.

    Asked of the GUI rather than of ``VIEW_STACK_INDEX``: the widget identity
    is true on every branch and cannot go stale against a renumbered stack.
    A notice about Human Design must not interrupt someone who is looking at a
    wheel.
    """
    view = getattr(gui, "human_design_view", None)
    stack = getattr(gui, "chart_stack", None)
    if view is not None and stack is not None:
        try:
            if stack.currentWidget() is view:
                return True
        except Exception:
            pass
    return bool(getattr(gui, "is_human_design", False))


def should_warn(gui) -> bool:
    """The whole predicate: real copy, Beginner, not muted, HD on screen.

    Silence is better than a placeholder: while the copy is pending the notice
    stays shut rather than showing "[COPY PENDING]" over the chart.
    """
    if copy_is_pending():
        return False
    return is_beginner() and not notice_is_muted() and human_design_is_on_screen(gui)


# ---- the manual --------------------------------------------------------------
def open_manual_at_human_design(parent) -> bool:
    """Open the help manual scrolled to the Human Design section.

    Reuses the GUI's own singleton opener (``_show_manual``) when there is one,
    so the reader never ends up with two manual windows, then drives the table
    of contents through its PUBLIC signal. HelpDialog has no open-at-section
    API (cards_of_truth_view says the same in its own comment); emitting
    ``itemClicked`` runs the very slot a click would, with no private call and
    no edit to a file this session does not own.
    """
    dialog = None
    opener = getattr(parent, "_show_manual", None)
    if callable(opener):
        try:
            opener()
            dialog = getattr(parent, "_help_dialog", None)
        except Exception:
            dialog = None
    if dialog is None:
        try:
            from apps.widgets.help_dialog import HelpDialog
            dialog = HelpDialog(parent=parent)
            dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            dialog.show()
        except Exception:
            return False
    toc = getattr(dialog, "toc_list", None)
    if toc is None:
        return False
    for row in range(toc.count()):
        item = toc.item(row)
        if item.text().strip() == MANUAL_SECTION:
            toc.setCurrentItem(item)
            toc.itemClicked.emit(item)
            return True
    return False


def open_settings(gui) -> bool:
    """Bring the Settings tab to the front.

    The tab is a lazy placeholder that builds itself on ``currentChanged``
    (core_gui_qt._create_settings_widget), so selecting it is the whole job —
    there is nothing to construct here and no private call to make.
    """
    tabs = getattr(gui, "tab_widget", None)
    if tabs is None:
        return False
    try:
        for index in range(tabs.count()):
            if tabs.tabText(index).replace("&&", "&") == SETTINGS_TAB_TITLE:
                tabs.setCurrentIndex(index)
                return True
    except Exception:
        return False
    return False


# ---- the dialog --------------------------------------------------------------
class HDFrameNotice(QDialog):
    """The notice itself. Two shapes, one class.

    ``mutable=True`` is the one raised by a zodiac click and carries the
    checkbox; ``mutable=False`` is the same text opened deliberately from
    Settings, where a mute box would be a trap (you cannot ask for an
    explanation and switch it off in the same gesture).

    No stylesheet: qt-material themes it, which is one less place for a
    hardcoded colour to go stale (Rule 20).
    """

    def __init__(self, parent=None, *, title=NOTICE_TITLE, body=NOTICE_BODY,
                 mutable=True, offer_settings=True):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        self.message = QLabel(body)
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        # Follow the info_text area via QSS (not setFont, which qt-material's
        # universal `* {font-size:13px}` rule would override) so the notice body
        # honours the user's Font Sizes setting instead of freezing at 13px
        # (F-D3). Transient dialog: reads the current size at construction.
        self.message.setStyleSheet(f"font-size: {scaled_area_px('info_text')}px;")
        # Word wrap alone gives a tall thin column when the text is long; a
        # minimum width makes it read as a paragraph.
        self.message.setMinimumWidth(420)
        layout.addWidget(self.message)

        self.mute_box = QCheckBox(MUTE_LABEL) if mutable else None
        if self.mute_box is not None:
            # SPEC-FONT-001 §3.2 (td-168ze, supersedes G7b): an in-dialog control
            # follows buttons, even when its label is a sentence (same ruling as
            # the Bulk export checkbox). Own-QSS beats the universal 13px rule.
            self.mute_box.setStyleSheet(f"font-size: {tier_px('buttons', 11)}px;")
            layout.addWidget(self.mute_box)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        # G7: box-level QSS reaches every child button (Close + the action ones).
        buttons.setStyleSheet(
            f"QPushButton {{ font-size: {tier_px('action_buttons', 10)}px; }}")
        self.settings_button = None
        if offer_settings:
            # Not offered when the dialog was opened FROM Settings: a button
            # that takes you where you already are reads as broken.
            self.settings_button = buttons.addButton(
                SETTINGS_LABEL, QDialogButtonBox.ButtonRole.ActionRole)
            self.settings_button.clicked.connect(self._on_settings)
        self.manual_button = buttons.addButton(
            MANUAL_LABEL, QDialogButtonBox.ButtonRole.ActionRole)
        self.manual_button.clicked.connect(self._on_manual)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def muted(self) -> bool:
        return bool(self.mute_box is not None and self.mute_box.isChecked())

    def _on_manual(self):
        """Manual first, then close: the notice has nothing more to say."""
        open_manual_at_human_design(self.parent())
        self.accept()

    def _on_settings(self):
        """Same shape: switch tabs, then get out of the way."""
        open_settings(self.parent())
        self.accept()

    def done(self, result):
        """One place to persist the checkbox.

        Whichever way the dialog leaves — Close, the manual button, Escape, the
        window's X — Qt routes it through done(), so the tick cannot be lost to
        an exit path nobody wired.
        """
        if self.muted():
            mute_notice(True)
        super().done(result)


# ---- the one call the GUI makes ---------------------------------------------
def maybe_warn_frame_locked(gui) -> bool:
    """Show the notice if this zodiac change was one Human Design ignored.

    Returns True when a notice was shown, for the probes. Never raises: it is
    called from the ``aditya_mode_changed`` handler, and an exception there
    would abort the rest of the mode switch.
    """
    try:
        if not should_warn(gui):
            return False
        HDFrameNotice(gui).exec()
        return True
    except Exception as error:
        # Swallowed, but never silent: a swallow with no trace is how a dialog
        # that stopped appearing goes unnoticed for weeks.
        print(f"[WARNING] Human Design frame notice failed: {error}")
        return False


def explain_frames(parent) -> bool:
    """The Settings link: the same explanation, opened on purpose, no mute box.

    Returns False and opens nothing while the copy is pending, so a caller that
    forgot to hide its link shows an inert link rather than a placeholder page.
    """
    if copy_is_pending():
        return False
    HDFrameNotice(parent, title=EXPLAIN_TITLE, body=EXPLAIN_BODY,
                  mutable=False, offer_settings=False).exec()
    return True
