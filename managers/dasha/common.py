# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Small pieces the dasha renderers share (SPEC-DSH-004): written once."""

from PySide6.QtCore import Qt


def menu_style(theme):
    """Stylesheet of the dasha title and mode menus."""
    return f"""
            QMenu {{ background-color: {theme["secondary"]}; color: {theme["secondary_text"]};
                border: 1px solid {theme["secondary_dark"]}; }}
            QMenu::item:selected {{ background-color: {theme["secondary_light"]}; }}
        """


def clear_all_channels(panel):
    """Clear every delegate channel (period, maturation, selection, lord) of
    a sign-dasha list before it fills."""
    d = panel.delegate
    if d is not None:
        d.update_highlights(set())
        d.update_maturation_highlights(set())
        d.update_selected_row(None)
        d.update_karaka_highlights(set())
        d.update_cusp_lord_highlights(set())
        d.update_whole_sign_highlights(set())


def move_current_marker(panel, item, mark):
    """Single click on a one-level list: move the current marker `mark` to the
    clicked row (no drill); updates is_current AND the leading glyph on every
    displayed row, and the period highlight."""
    entry = item.data(Qt.ItemDataRole.UserRole)
    if not entry or entry.get("is_separator"):
        return
    lst = panel.list_widget
    highlight = set()
    for i in range(lst.count()):
        it = lst.item(i)
        e = it.data(Qt.ItemDataRole.UserRole)
        if not e or e.get("is_separator"):
            continue
        is_this = it is item
        e["is_current"] = is_this
        text = it.text()
        if text:
            it.setText((mark if is_this else " ") + text[1:])
        it.setData(Qt.ItemDataRole.UserRole, e)
        if is_this:
            highlight.add(i)
    if panel.delegate is not None:
        panel.delegate.update_highlights(highlight)
        lst.viewport().update()
