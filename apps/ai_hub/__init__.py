# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The AI button and the AI hub (SPEC-COACH-001 §4.7): one entry point in
the status bar, where the six AI pills were, opening a glass sheet of the AI
features. Nothing is stored on ChartGUI (Rule 4b): the button is found by its
object name, the sheet through ``sheet.sheet_for``. Lite ships this package
with only the button (D-21): the hub, its tiles and the coach are reached
through ``core.edition_features.ai_features()`` (SPEC-EDN-002 P4)."""
from __future__ import annotations

def hub_available() -> bool:
    """The button shows when the hub has at least one tile."""
    from core.edition_features import ai_features
    features = ai_features()
    return features is not None and features.hub_has_tiles()


def pro_message_only() -> bool:
    """Lite (SPEC-EDN-002 D-21): the AI button stays, and a click says the AI
    is in Pro instead of opening the hub. Not when the branch switched AI
    capture off: then no edition has AI to point to."""
    from core.build_features import ai_capture_enabled
    from core.edition_features import edition_has
    return not edition_has("ai") and ai_capture_enabled()


def show_pro_message(gui) -> None:
    """The Lite message, with a way to the About Varuna360 Pro dialog."""
    from PySide6.QtWidgets import QMessageBox
    from core.pro_marketing import PRO_AI_MORE, PRO_AI_REQUIRED, PRO_AI_TITLE
    box = QMessageBox(gui)
    box.setIcon(QMessageBox.Information)
    box.setWindowTitle(PRO_AI_TITLE)
    box.setText(PRO_AI_REQUIRED)
    more = box.addButton(PRO_AI_MORE, QMessageBox.ActionRole)
    box.setEscapeButton(box.addButton(QMessageBox.Ok))   # Escape closes it
    box.exec()
    if box.clickedButton() is more and hasattr(gui, "_show_about_pro"):
        gui._show_about_pro()


def install_button(gui):
    """The AI button in the status bar, before the question field. None when
    the hub would be empty; in Lite the button only shows the Pro message."""
    lite = pro_message_only()
    if not lite and not hub_available():
        return None
    from apps.ai_hub.button import AIButton
    button = AIButton()
    button.clicked.connect(lambda: toggle(gui))
    gui.statusBar().addPermanentWidget(button)
    if lite:
        return button
    try:
        from core.edition_features import ai_features
        ai_features().follow_coach(gui, button)
    except Exception as e:                               # noqa: BLE001
        print(f"[AI hub] Warning: the button does not follow the coach: {e}")
    return button


def install_window_ai(gui) -> None:
    """The window's AI at boot: this button, then (Pro and up) the coach's
    question field, the edition's pills and a pending mynatal reading."""
    install_button(gui)
    from core.edition_features import ai_features
    features = ai_features()
    if features is not None:
        features.install_window(gui)


def window_refresh_parts(gui):
    """The window's AI theme and font fan-out, [(name, callable)]: in Lite
    the button alone; Pro and up add the pills, the open AI windows and the
    coach field (the capture refresh re-themes this button and the hub)."""
    from core.edition_features import ai_features
    features = ai_features()
    if features is None:
        return [("ai_button", lambda: refresh(gui))]
    return features.refresh_parts(gui)


def find_button(gui):
    from apps.ai_hub.button import AIButton, BUTTON_NAME
    return gui.findChild(AIButton, BUTTON_NAME)


def toggle(gui) -> None:
    if pro_message_only():
        show_pro_message(gui)
        return
    from core.edition_features import ai_features
    features = ai_features()
    if features is not None:
        features.toggle_hub(gui)


def open_hub(gui) -> None:
    if pro_message_only():
        show_pro_message(gui)
        return
    from core.edition_features import ai_features
    features = ai_features()
    if features is not None:
        features.open_hub(gui)


def refresh(gui) -> None:
    """Theme and font fan-out: the button re-measures, an open hub rebuilds."""
    button = find_button(gui)
    if button is not None:
        button.refresh_theme()
    from core.edition_features import ai_features
    features = ai_features()
    if features is not None:
        features.refresh_hub(gui)
