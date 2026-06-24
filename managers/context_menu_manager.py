# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Context Menu Manager — Application-wide "Search Google" on right-click.

Installs as an event filter on QApplication. When any widget with selected
text receives a context menu request, "Search Google" is appended to the
widget's existing context menu (preserving Copy, Select All, etc.).

Works on QLabel, QLineEdit, QTextEdit, QTextBrowser, and any widget that
exposes selectedText() or textCursor().selectedText().

Usage (in core_gui_qt.py):
    from managers.context_menu_manager import install_search_context_menu
    install_search_context_menu(app)   # app = QApplication instance
"""
import urllib.parse
import webbrowser

from PySide6.QtCore import QObject, QEvent
from PySide6.QtWidgets import QMenu, QApplication


def _get_selected_text(widget) -> str:
    """Extract selected text from any common Qt widget type."""
    # QLineEdit, QLabel — have .selectedText()
    if hasattr(widget, 'selectedText'):
        text = widget.selectedText()
        if text:
            return text.strip()

    # QTextEdit, QTextBrowser — use textCursor
    if hasattr(widget, 'textCursor'):
        cursor = widget.textCursor()
        if cursor.hasSelection():
            return cursor.selectedText().strip()

    return ""


def _search_google(text: str):
    """Open default browser with a Google search for the given text."""
    query = urllib.parse.quote_plus(text)
    url = f"https://www.google.com/search?q={query}"
    webbrowser.open(url)


class _SearchEventFilter(QObject):
    """Event filter that appends 'Search Google' to context menus app-wide."""

    def eventFilter(self, obj, event):
        if event.type() != QEvent.Type.ContextMenu:
            return False

        selected = _get_selected_text(obj)
        if not selected:
            return False  # No selection — let default context menu handle it

        # Get the widget's standard context menu if it has one (QTextEdit,
        # QTextBrowser, QLineEdit all provide createStandardContextMenu)
        if hasattr(obj, 'createStandardContextMenu'):
            menu = obj.createStandardContextMenu()
        else:
            # Widgets without a standard menu (e.g., QLabel) — build minimal one
            menu = QMenu(obj)
            copy_action = menu.addAction("Copy")
            copy_action.triggered.connect(
                lambda: QApplication.clipboard().setText(selected)
            )

        # Append separator + Search Google
        menu.addSeparator()
        preview = selected[:50] + "..." if len(selected) > 50 else selected
        search_action = menu.addAction(f'Search Google: "{preview}"')
        search_action.triggered.connect(lambda: _search_google(selected))

        # Show the menu at cursor position
        menu.exec(event.globalPos())
        menu.deleteLater()

        return True  # We handled the context menu


# Singleton filter instance
_filter_instance = None


def install_search_context_menu(app):
    """Install the Search Google event filter on the QApplication.

    Call once at startup. The filter appends 'Search Google' to the right-click
    menu of any widget that has text selected.
    """
    global _filter_instance
    _filter_instance = _SearchEventFilter(app)
    app.installEventFilter(_filter_instance)
