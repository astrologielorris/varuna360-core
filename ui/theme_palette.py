"""Per-theme palette overrides and the theme palette editor dialog."""
from __future__ import annotations

import colorsys
import os
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
    QPushButton, QSlider, QVBoxLayout, QWidget,
)

from managers.settings_manager import get_settings


PALETTE_KEYS = (
    ("primaryColor", "Accent"),
    ("primaryLightColor", "Accent light"),
    ("primaryTextColor", "Text on accent"),
    ("secondaryColor", "Panel background"),
    ("secondaryLightColor", "Raised / hover background"),
    ("secondaryDarkColor", "Main background"),
    ("secondaryTextColor", "Text on background"),
)

_COLOR_RE = re.compile(
    r'<color\s+name="([^"]+)"\s*>\s*(#[0-9a-fA-F]{3,8})\s*</color>')

# Themes whose shipped accent is too bright for white ink; they ship dark
# accent text unless the user saves an explicit foreground.
DARK_ACCENT_INK = frozenset({"dark_amber.xml", "dark_yellow.xml"})


def _source_path(theme_file: str) -> str:
    if os.path.exists(theme_file):
        return theme_file
    try:
        import qt_material
        return os.path.join(os.path.dirname(qt_material.__file__), "themes", theme_file)
    except Exception:
        return theme_file


def theme_base_palette(theme_file: str) -> dict[str, str]:
    """Read qt-material's palette without applying it."""
    try:
        with open(_source_path(theme_file), encoding="utf-8") as handle:
            return {name: value for name, value in _COLOR_RE.findall(handle.read())}
    except OSError:
        return {}


def theme_override(theme_file: str, applied: bool = False) -> dict:
    setting = "appearance.applied_theme_overrides" if applied else "appearance.theme_overrides"
    settings = get_settings()
    value = settings.get(setting, None)
    if value is None and applied:
        value = settings.get("appearance.theme_overrides", {})
    if not isinstance(value, dict):
        return {}
    item = value.get(os.path.basename(theme_file), {})
    return item if isinstance(item, dict) else {}


def effective_palette(theme_file: str, applied: bool = False) -> dict[str, str]:
    palette = theme_base_palette(theme_file)
    override = theme_override(theme_file, applied)
    colors = override.get("colors", {})
    if isinstance(colors, dict):
        palette.update({k: v for k, v in colors.items()
                        if k in dict(PALETTE_KEYS) and QColor(str(v)).isValid()})
    return palette


def accent_strength(theme_file: str, applied: bool = False) -> int:
    try:
        return max(0, min(100, int(theme_override(theme_file, applied).get("accent_strength", 100))))
    except (TypeError, ValueError):
        return 100


def _with_strength(color: str, strength: int) -> str:
    q = QColor(color)
    if not q.isValid() or strength >= 100:
        return color
    h, l, s = colorsys.rgb_to_hls(q.redF(), q.greenF(), q.blueF())
    r, g, b = colorsys.hls_to_rgb(h, l, s * strength / 100.0)
    return QColor.fromRgbF(r, g, b).name()


def transformed_palette(theme_file: str, applied: bool = False) -> dict[str, str]:
    palette = effective_palette(theme_file, applied)
    strength = accent_strength(theme_file, applied)
    for key in ("primaryColor", "primaryLightColor"):
        if key in palette:
            palette[key] = _with_strength(palette[key], strength)
    # Shipped readable defaults. A saved foreground always wins.
    saved_colors = theme_override(theme_file, applied).get("colors", {})
    if (not isinstance(saved_colors, dict) or "primaryTextColor" not in saved_colors) and \
            os.path.basename(theme_file) in DARK_ACCENT_INK:
        palette["primaryTextColor"] = "#212121"
    return palette

def theme_preview_colors(theme_file: str, fallback: list[str]) -> list[str]:
    palette = transformed_palette(theme_file) if theme_override(theme_file) else {}
    primary = palette.get("primaryColor")
    dark = QColor(primary).darker(140).name() if primary and QColor(primary).isValid() else None
    values = [primary, dark, palette.get("primaryLightColor")]
    return [v if v else fallback[i] for i, v in enumerate(values)]


def save_theme_override(theme_file: str, colors: dict[str, str], strength: int) -> None:
    settings = get_settings()
    overrides = settings.get("appearance.theme_overrides", {})
    overrides = dict(overrides) if isinstance(overrides, dict) else {}
    if settings.get("appearance.applied_theme_overrides", None) is None:
        settings.set("appearance.applied_theme_overrides", dict(overrides))
    base = theme_base_palette(theme_file)
    # Compare with the effective shipped foreground, not the raw XML white.
    if os.path.basename(theme_file) in DARK_ACCENT_INK:
        base["primaryTextColor"] = "#212121"
    changed = {k: v for k, v in colors.items() if base.get(k, "").lower() != v.lower()}
    key = os.path.basename(theme_file)
    if changed or strength != 100:
        overrides[key] = {"colors": changed, "accent_strength": int(strength)}
    else:
        overrides.pop(key, None)
    settings.set("appearance.theme_overrides", overrides)


def commit_theme_overrides() -> None:
    settings = get_settings()
    value = settings.get("appearance.theme_overrides", {})
    settings.set("appearance.applied_theme_overrides", dict(value) if isinstance(value, dict) else {})


class _ColorButton(QPushButton):
    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self._color = color
        self.clicked.connect(self._choose)
        self._render()

    def color(self) -> str:
        return self._color

    def set_color(self, color: str) -> None:
        self._color = QColor(color).name()
        self._render()

    def _render(self) -> None:
        q = QColor(self._color)
        fg = "#111111" if q.lightnessF() > .55 else "#ffffff"
        self.setText(self._color.upper())
        self.setStyleSheet(f"background:{self._color}; color:{fg}; min-width:110px; padding:6px;")

    def _choose(self) -> None:
        color = QColorDialog.getColor(QColor(self._color), self, "Choose color")
        if color.isValid():
            self.set_color(color.name())


class ThemePaletteDialog(QDialog):
    """Edit and save a palette draft without applying the application theme."""
    def __init__(self, theme_file: str, theme_name: str, preview_callback, parent=None):
        super().__init__(parent)
        self.theme_file = theme_file
        self._preview_callback = preview_callback
        self._base = theme_base_palette(theme_file)
        self.setWindowTitle(f"Edit {theme_name}")
        self.setMinimumWidth(430)
        self.setAccessibleName(f"{theme_name} palette editor")

        root = QVBoxLayout(self)
        intro = QLabel(
            "Save stores this palette and updates its theme card. "
            "Use Apply on the Appearance page to activate it.")
        intro.setWordWrap(True)
        root.addWidget(intro)
        form = QFormLayout()
        self.color_buttons = {}
        current = effective_palette(theme_file)
        # Show the shipped readable foreground for amber/yellow in the editor,
        # while keeping accent colors unmodified so strength is not applied twice.
        current["primaryTextColor"] = transformed_palette(theme_file).get(
            "primaryTextColor", current.get("primaryTextColor", "#ffffff"))
        for key, label in PALETTE_KEYS:
            color = current.get(key, self._base.get(key, "#808080"))
            button = _ColorButton(color, self)
            button.setAccessibleName(label)
            self.color_buttons[key] = button
            form.addRow(label + ":", button)

        strength_row = QWidget(self)
        strength_layout = QHBoxLayout(strength_row)
        strength_layout.setContentsMargins(0, 0, 0, 0)
        self.strength_slider = QSlider(Qt.Orientation.Horizontal)
        self.strength_slider.setRange(0, 100)
        self.strength_slider.setValue(accent_strength(theme_file))
        self.strength_value = QLabel()
        strength_layout.addWidget(self.strength_slider)
        strength_layout.addWidget(self.strength_value)
        self.strength_slider.valueChanged.connect(self._strength_changed)
        self._strength_changed(self.strength_slider.value())
        form.addRow("Accent strength:", strength_row)
        root.addLayout(form)

        reset = QPushButton("Reset theme")
        reset.setToolTip("Restore this theme's original palette")
        reset.clicked.connect(self.reset_theme)
        root.addWidget(reset, alignment=Qt.AlignmentFlag.AlignLeft)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def draft(self) -> tuple[dict[str, str], int]:
        return ({key: button.color() for key, button in self.color_buttons.items()},
                self.strength_slider.value())

    def _strength_changed(self, value: int) -> None:
        self.strength_value.setText(f"{value}%")

    def reset_theme(self) -> None:
        for key, button in self.color_buttons.items():
            button.set_color(self._base.get(key, "#808080"))
        if "primaryTextColor" in self.color_buttons and \
                os.path.basename(self.theme_file) in DARK_ACCENT_INK:
            self.color_buttons["primaryTextColor"].set_color("#212121")
        self.strength_slider.blockSignals(True)
        self.strength_slider.setValue(100)
        self.strength_slider.blockSignals(False)
        self._strength_changed(100)

    def _save(self) -> None:
        colors, strength = self.draft()
        save_theme_override(self.theme_file, colors, strength)
        self._preview_callback(self.theme_file)
        self.accept()
