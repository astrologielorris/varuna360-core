# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under the GNU AGPL-3.0. See LICENSE at the repository root.
"""Core-safe image-paste line edit + sparkle AI toggle, shared across tabs.

Two small Core widgets so the "paste a chart image / date" affordance and its
sparkle AI on/off toggle exist ONCE and are reused by every consumer (the
Transit panel's reading-date field, the New & Edit token bar, and any future
one). Neither widget imports anything from the paid edition: the vision
capability is injected as a plain callable by the host, never referenced here,
so both widgets ship in every edition.

- ``ImagePasteLineEdit(QLineEdit)`` diverts pasted/dropped IMAGE data to the
  ``image_pasted(bytes, media_type)`` signal WITHOUT inserting text; all
  non-image content (typing, text paste, text drop) behaves as a normal line
  edit. It carries ONLY the paste-diversion behaviour: placeholder, sizing,
  styling, notices and any submit wiring belong to the subclass that needs them,
  so adopting it never imports another tab's geometry (review finding R3).
- ``AiToggleButton(QPushButton)`` is a checkable sparkle control persisted under
  a caller-supplied settings key (so two tabs toggle independently). OFF
  (default) = offline parsing only; ON = AI reads dates and images. The
  ``settings`` injection seam is preserved for tests (review finding R5).

Both self-theme from ``get_theme_colors()`` (Rule 20) and expose
``refresh_theme()`` for the host to cascade on a live theme switch.

Extracted from the transit panel's reading-date field (SPEC-TRN-005 B2); that
widget now subclasses these, so the paste logic and the toggle live once.
"""

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QKeySequence, QGuiApplication, QAction
from PySide6.QtWidgets import QLineEdit, QPushButton

from ui.qt_theme import get_theme_colors, dim_text
# One implementation of "is there an image on this clipboard" for every paste
# entry point in the app.
from ui.image_paste import extract_image as _extract_image


class ImagePasteLineEdit(QLineEdit):
    """Line edit that diverts image paste/drop to ``image_pasted`` and keeps
    text behaving normally.

    Paste-diversion behaviour ONLY. No placeholder / sizing / clear-button /
    stylesheet / notice opinions live here, so a consumer (the transit reading
    field, the New & Edit token entry) adopts it with a pure base-class swap and
    keeps its own geometry and theming.
    """

    image_pasted = Signal(bytes, str)   # (image_bytes, media_type)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

    # -- paste --------------------------------------------------------------
    #
    # QLineEdit has NO ``insertFromMimeData`` virtual reachable from Python, so
    # an override there is dead code. The real seams are ``keyPressEvent`` (which
    # receives the paste chord before the base dispatches to the C++-only insert
    # path) and the context-menu Paste action. Both route through
    # ``_handle_paste``.

    def _handle_paste(self) -> bool:
        """Inspect the live clipboard. If it carries an image, emit
        ``image_pasted`` and return True (consume, insert NO text even when a
        text fallback rides alongside). Otherwise return False so the caller runs
        the untouched base paste."""
        clipboard = QGuiApplication.clipboard()
        mime = clipboard.mimeData() if clipboard is not None else None
        if mime is None:
            return False
        found = _extract_image(mime)
        if found is not None:
            data, media_type = found
            self.image_pasted.emit(data, media_type)
            return True
        return False

    def keyPressEvent(self, event):
        """Catch the paste chord (Ctrl+V / Shift+Insert). An image on the
        clipboard is diverted to ``image_pasted`` and the event consumed (no
        text). No image runs the base handler (normal paste)."""
        if event.matches(QKeySequence.Paste) and self._handle_paste():
            event.accept()
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        """Right-click menu with the standard Paste action rerouted through the
        image-aware handler."""
        self._build_context_menu().exec(event.globalPos())

    def _build_context_menu(self):
        """Standard QLineEdit context menu with its Paste action rerouted through
        the image-aware handler. Split out so the reroute is unit-testable
        without a modal exec().

        The standard menu tags its Paste entry with the stable, locale-independent
        objectName "edit-paste"; its shortcut() is EMPTY (the "Ctrl+V" is in the
        display text only), so matching on shortcut would silently never fire."""
        menu = self.createStandardContextMenu()
        paste_action = None
        for action in menu.actions():
            if action.objectName() == "edit-paste":
                paste_action = action
                break
        if paste_action is not None:
            replacement = QAction(paste_action.text(), menu)
            replacement.setObjectName("edit-paste")
            replacement.setShortcut(QKeySequence(QKeySequence.Paste))
            # Qt disables the standard Paste for an image-only clipboard (no
            # text), which would grey out the exact case this field handles.
            # Enable when there is pasteable text OR a pasteable image.
            clipboard = QGuiApplication.clipboard()
            mime = clipboard.mimeData() if clipboard is not None else None
            has_image = mime is not None and _extract_image(mime) is not None
            replacement.setEnabled(paste_action.isEnabled() or has_image)
            replacement.triggered.connect(self._context_paste)
            menu.insertAction(paste_action, replacement)
            menu.removeAction(paste_action)
        return menu

    def _context_paste(self):
        """Context-menu Paste slot: image emits ``image_pasted``; else base text
        paste."""
        if not self._handle_paste():
            self.paste()  # public QLineEdit slot: normal text paste

    # -- drag & drop --------------------------------------------------------

    def dragEnterEvent(self, event):
        mime = event.mimeData()
        if mime.hasImage() or mime.hasUrls() or mime.hasText():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        mime = event.mimeData()
        if mime.hasImage() or mime.hasUrls() or mime.hasText():
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event):
        mime = event.mimeData()
        found = _extract_image(mime)
        if found is not None:
            data, media_type = found
            self.image_pasted.emit(data, media_type)
            event.acceptProposedAction()
            return  # image drop, no text inserted
        # Text (or anything else) runs the base QLineEdit drop. Delegating
        # (rather than setText) preserves undo history and drop-position/cursor
        # semantics.
        super().dropEvent(event)


class AiToggleButton(QPushButton):
    """Small checkable sparkle control selecting the reading engine.

    OFF (default) = offline parsing only (no network, no images); ON = AI reads
    dates and screenshots. State is persisted under the caller-supplied
    ``settings_key`` and reloaded on construction, so two tabs (Transit, New &
    Edit) keep independent state. ``ai_enabled`` exposes the state; the inherited
    ``toggled`` signal reports changes. ``settings`` may be injected for tests.
    """

    def __init__(self, settings_key, settings=None, tooltip=None, parent=None):
        super().__init__("✨", parent)   # sparkle
        self._settings_key = settings_key
        self._settings = settings
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(32)
        # Tooltip is injectable so a subclass keeps its own wording (the transit
        # toggle preserves its original copy) without duplicating the widget.
        self.setToolTip(tooltip or (
            "AI engine. OFF: offline parsing only (no network, no images). "
            "ON: AI reads dates and screenshots."
        ))
        # Load persisted state BEFORE connecting the persist slot so restoring
        # the value does not trigger a redundant write.
        self.setChecked(bool(self._get_settings().get(self._settings_key, False)))
        self.toggled.connect(self._persist)
        self.refresh_theme()

    # -- settings -----------------------------------------------------------

    def _get_settings(self):
        if self._settings is None:
            from managers.settings_manager import get_settings
            self._settings = get_settings()
        return self._settings

    def _persist(self, checked: bool):
        self._get_settings().set(self._settings_key, bool(checked))

    @property
    def ai_enabled(self) -> bool:
        """Current engine selection: True = AI (ON), False = offline (OFF)."""
        return self.isChecked()

    # -- theme (Rule 20) ----------------------------------------------------

    def _style(self) -> str:
        theme = get_theme_colors()
        # secondary_light is #ffffff on the light theme, so it must NOT be used
        # as a border or hover fill (invisible white-on-near-white). Border is a
        # dim_text hairline that contrasts on BOTH themes; hover lifts the accent
        # border instead of painting a fill. Checked fills with the accent; the
        # glyph is the ✨ emoji, which renders in its own colours regardless of
        # `color`, so primary_text (the theme's on-primary token) is fine here.
        return f"""
            QPushButton {{
                background-color: {theme["secondary"]};
                color: {dim_text(theme["secondary_text"], 0.70)};
                border: 1px solid {dim_text(theme["secondary_text"], 0.24)};
                border-radius: 6px;
                padding: 3px 8px;
                font-size: 12px;
                min-width: 22px;
            }}
            QPushButton:hover {{
                border-color: {theme["primary"]};
            }}
            QPushButton:checked {{
                background-color: {theme["primary"]};
                color: {theme["primary_text"]};
                border-color: {theme["primary"]};
            }}
        """

    def refresh_theme(self):
        """Re-apply the stylesheet from the current palette (host cascades this
        on a live theme switch)."""
        self.setStyleSheet(self._style())
