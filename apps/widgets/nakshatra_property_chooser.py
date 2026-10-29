# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""Corner chooser for the nakshatra wheel's outer property ring (Core and Lite).

A small floating button overlaid in the top-left corner of the Core F2 nakshatra
wheel (a child of the view, never a layout row, so the wheel keeps its full
height). It shows the property the outer ring draws, with a ▾; a click opens a
menu of the properties (Symbol, Deity, Yoni, Gana, Gunas...) plus the off state,
which keeps the 1 to 9 dasha numbers, as on the Pro tab's selector. The choice
is ``display.nakshatra.property_mode``, the same setting the Pro tab uses
(SPEC-NAK-LITE-001 amendment 2026-10-13).
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QMenu, QToolButton

from core.nakshatra_properties import PROPERTY_OPTIONS

SETTING_KEY = "display.nakshatra.property_mode"
OFF_CAPTION = "None (dasha numbers)"
MARGIN = 6


def caption_for(mode):
    """Menu caption of a property mode ("none" is the off state)."""
    return OFF_CAPTION if mode == "none" else dict(PROPERTY_OPTIONS).get(mode, mode)


class NakshatraPropertyChooser(QToolButton):
    """Floating ▾ button choosing the wheel's outer ring property."""

    def __init__(self, wheel_view):
        super().__init__(wheel_view)
        self.wheel_view = wheel_view
        self.setObjectName("nakshatra_property_chooser")
        self.setAccessibleName("Outer ring content")
        self.setToolTip("Outer ring: choose the nakshatra property it shows; "
                        "double-click a ring label for the details")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.menu_ = QMenu(self)
        self._group = QActionGroup(self)
        self._group.setExclusive(True)
        self._actions = {}
        for key, _caption in PROPERTY_OPTIONS:
            action = QAction(caption_for(key), self)
            action.setCheckable(True)
            action.setData(key)
            action.triggered.connect(lambda _on=False, k=key: self.choose(k))
            self._group.addAction(action)
            self.menu_.addAction(action)
            self._actions[key] = action
        self.setMenu(self.menu_)
        self.refresh_theme()
        self.sync()
        self.move(MARGIN, MARGIN)
        self.raise_()

    def sync(self):
        """Show the wheel's current property on the button and in the menu."""
        mode = self.wheel_view.property_mode
        self.setText(("Outer ring" if mode == "none" else caption_for(mode)) + " ▾")
        action = self._actions.get(mode)
        if action is not None:
            action.setChecked(True)
        self.adjustSize()

    def adopt_saved(self):
        """Follow the saved setting (the Pro tab's selector may have changed it)."""
        from managers.settings_manager import get_settings
        from core.settings_registry import default as _registry_default
        saved = get_settings().get(SETTING_KEY, _registry_default(SETTING_KEY))
        valid = {key for key, _caption in PROPERTY_OPTIONS}
        self.wheel_view.property_mode = saved if saved in valid else "none"
        self.sync()

    def choose(self, mode):
        """Draw ``mode`` on the outer ring and remember it (shared setting)."""
        from managers.settings_manager import get_settings
        self.wheel_view.property_mode = mode
        get_settings().set(SETTING_KEY, mode)
        if self.wheel_view._chart is not None:
            self.wheel_view._draw_wheel()
        self.sync()

    def refresh_theme(self):
        from ui.qt_theme import get_theme_colors, scaled_area_px
        c = get_theme_colors()
        px = scaled_area_px("buttons")
        row = px + 10   # compact: the material theme's tall default rows are overridden
        self.setStyleSheet(
            f"QToolButton {{ color: {c['secondary_text']}; background: {c['secondary']};"
            f" border: 1px solid {c['secondary_dark']}; border-radius: 4px;"
            f" padding: 0px 7px; margin: 0px; font-size: {px}px;"
            f" min-height: 0px; max-height: {row}px; }}"
            f"QToolButton:hover {{ border-color: {c['secondary_text']}; }}"
            "QToolButton::menu-indicator { image: none; width: 0px; }")
        self.setFixedHeight(row)
        self.menu_.setStyleSheet(
            f"QMenu {{ background: {c['secondary']}; color: {c['secondary_text']};"
            f" border: 1px solid {c['secondary_dark']}; font-size: {px}px; padding: 2px; }}"
            f"QMenu::item {{ min-height: 0px; height: {row - 4}px; padding: 0px 14px 0px 22px;"
            f" margin: 0px; color: {c['secondary_text']}; background: transparent; }}"
            f"QMenu::item:selected {{ background: {c['secondary_dark']}; }}"
            f"QMenu::indicator {{ width: {max(6, px - 4)}px; height: {max(6, px - 4)}px;"
            f" left: 6px; }}")
        self.adjustSize()
        self.raise_()
