# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
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
from contextlib import contextmanager
import urllib.parse
import webbrowser

from PySide6.QtCore import QObject, QEvent, QTimer
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
        kind = event.type()
        if kind == QEvent.Type.Show and _show_hooks:
            for hook in list(_show_hooks):
                try:
                    hook(obj)
                except Exception:
                    pass
            return False
        if kind != QEvent.Type.ContextMenu:
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
# Other app-wide Python filters under the same rule (install_app_filter), and
# the ids of every filter on the application right now.
_app_filters = []
_on = set()
# Whether it is on the application right now.
_installed = False
# Live objects (by id) that need the filter off for as long as they exist.
_held_off_by = set()
# Open search_context_menu_paused() blocks.
_paused = 0
# Callables run with each widget about to be shown, while the filter is on
# (add_show_hook): this one app-wide Python filter is reused, a second one
# would double the cost of every event.
_show_hooks = []


def add_show_hook(hook) -> None:
    """Run ``hook(widget)`` on every Show event while the filter is on the
    application (``is_search_context_menu_active``), before the widget's
    first paint. Idempotent. Used by ``ui.input_font_qss`` (td-8m3kd)."""
    if hook not in _show_hooks:
        _show_hooks.append(hook)


def install_search_context_menu(app):
    """Install the Search Google event filter on the QApplication.

    Call once at startup. The filter appends 'Search Google' to the right-click
    menu of any widget that has text selected.
    """
    global _filter_instance
    _filter_instance = _SearchEventFilter(app)
    _sync_filter()


def hold_off_search_context_menu(owner) -> None:
    """Keep the app-wide filter off for the whole life of ``owner``.

    Any Python event filter on the whole application crashes PySide 6.10.1
    (segfault in getWrapperForQObject, re-entered through the
    DynamicPropertyChange event it sends) when it sees an event for one of
    QWebEngineView's internal Qt Quick items, e.g. on the first mouse move
    over the page. A window holding a web view calls this BEFORE it creates
    the view. The filter comes back once no holder is alive AND no Qt Quick
    window is left: ``destroyed`` fires before Qt deletes the window's
    children, so the web view is still being torn down at that moment.
    """
    key = id(owner)
    _held_off_by.add(key)
    owner.destroyed.connect(lambda *_a, key=key: _release(key))
    _sync_filter()


@contextmanager
def search_context_menu_paused():
    """The app-wide filter off for the duration of the block (td-8m3kd).

    The filter is a Python callable on the whole application: every event of
    every widget crosses into Python to be dismissed (it only wants
    ContextMenu). An app-wide restyle (``QApplication.setStyleSheet``, the
    input-font sheet a font change re-applies) sends hundreds of thousands
    of events in one go; through the filter it took seconds of the font
    refresh. No context menu can open during the synchronous restyle, so
    nothing is lost. Nested blocks are fine."""
    global _paused
    _paused += 1
    _sync_filter()
    try:
        yield
    finally:
        _paused -= 1
        _sync_filter()


def is_search_context_menu_active() -> bool:
    """True when the filter is on the application right now."""
    return _installed


def _release(key) -> None:
    _held_off_by.discard(key)
    # Never from inside the destructor: the children are not deleted yet.
    QTimer.singleShot(0, _sync_filter)


def _quick_windows_alive(app) -> bool:
    """A Qt Quick window still exists (QWebEngineView renders through one)."""
    return any(w.inherits("QQuickWindow") for w in app.allWindows())


def install_app_filter(f) -> None:
    """Put another Python event filter on the whole application under the
    same rule as Search Google: off while a web view exists (the PySide
    segfault of ``hold_off_search_context_menu``), back once none is left.
    Every app-wide Python filter must come through here, never
    ``app.installEventFilter`` (a wheel guard installed directly crashed the
    app on opening the AI Readings window, 2026-10-22)."""
    if f not in _app_filters:
        _app_filters.append(f)
    _sync_filter()


def remove_app_filter(f) -> None:
    """Take a filter given to ``install_app_filter`` off for good."""
    if f in _app_filters:
        _app_filters.remove(f)
    app = QApplication.instance()
    if id(f) in _on and app is not None:
        try:
            app.removeEventFilter(f)
        except RuntimeError:
            pass
    _on.discard(id(f))


def _set_installed(app, f, want: bool) -> None:
    if want and id(f) not in _on:
        app.installEventFilter(f)
        _on.add(id(f))
    elif not want and id(f) in _on:
        try:
            app.removeEventFilter(f)
        except RuntimeError:
            pass
        _on.discard(id(f))


def _sync_filter() -> None:
    global _installed
    app = QApplication.instance()
    if app is None:
        return
    filters = list(_app_filters)
    if _filter_instance is not None:
        filters.insert(0, _filter_instance)
    if not filters:
        return
    blocked = bool(_paused or _held_off_by)
    if not blocked and _quick_windows_alive(app):
        blocked = True
        QTimer.singleShot(250, _sync_filter)       # a web view is still going away
    for f in filters:
        _set_installed(app, f, not blocked)
    _installed = _filter_instance is not None and id(_filter_instance) in _on
