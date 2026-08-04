# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
The floating card that tells you what your click means (SPEC-MAP-002 §4.4).

A child of the map's VIEWPORT, not a scene item. A scene item would pan away
with the map and would need transform-ignoring text layout to stay readable;
a widget stays pinned to the corner and gets the ordinary stylesheet pipeline,
including the live theme refresh.

The card carries two clocks and has to be honest about it. The Ascendant line
is computed for the hovered or selected place using THAT place's timezone, so
it answers "what would I get if I clicked here". The bands underneath are drawn
for one fixed instant. Across a timezone border those legitimately disagree,
which is why the basis line exists: it names the instant the bands belong to
rather than leaving the user to assume the two agree.
"""

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from ui.themed_style import ThemedStyleMixin

__all__ = ["MapInfoCard"]

#: Distance from the viewport corner, in device-independent pixels.
CARD_MARGIN = 12


class MapInfoCard(ThemedStyleMixin, QFrame):
    """Place, coordinates, timezone and Ascendant for the current point."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("mapInfoCard")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 11, 14, 11)
        layout.setSpacing(2)

        self.place_label = QLabel("")
        self.country_label = QLabel("")
        self.coord_label = QLabel("")
        self.tz_label = QLabel("")
        self.asc_label = QLabel("")
        self.basis_label = QLabel("")

        for widget in (self.place_label, self.country_label, self.coord_label,
                       self.tz_label, self.asc_label, self.basis_label):
            layout.addWidget(widget)

        self._register_themed(self, self._card_style)
        self._register_themed(self.place_label, self._place_style)
        self._register_themed(self.country_label, self._muted_style)
        self._register_themed(self.coord_label, self._mono_style)
        self._register_themed(self.tz_label, self._mono_style)
        self._register_themed(self.asc_label, self._asc_style)
        self._register_themed(self.basis_label, self._basis_style)

        self.basis_label.hide()
        self.hide()

    # -- styles (each re-decides polarity per call, so replay works) --------

    @staticmethod
    def _colors():
        """Live palette. NOT the ui.qt_theme module constants.

        Those are frozen at import to the dark values, so reading them in a
        light theme paints a near-black card on a light map — which is what the
        first real-screen capture of this card actually showed.
        """
        from apps.widgets.map_chrome import live_palette
        p = live_palette()
        return p["surface"], p["border"], p["text"], p["muted"]

    def _card_style(self):
        surface, border, _p, _s = self._colors()
        return f"""
            QFrame#mapInfoCard {{
                background-color: {surface};
                border: 1px solid {border};
                border-radius: 10px;
            }}
        """

    def _place_style(self):
        _s, _b, primary, _sec = self._colors()
        from ui.qt_theme import scaled_area_px
        return (f"color: {primary}; font-size: {scaled_area_px('info_text')}px;"
                f" font-weight: 600; letter-spacing: 1px;"
                f" border: none; background: transparent;")

    def _muted_style(self):
        _s, _b, _p, secondary = self._colors()
        from ui.qt_theme import scaled_area_px
        from apps.widgets.map_chrome import dim
        # In a light theme `text` and `muted` resolve to the same key, so the
        # hierarchy has to come from opacity rather than from a second colour.
        secondary = dim(secondary)
        return (f"color: {secondary};"
                f" font-size: {scaled_area_px('status')}px;"
                f" border: none; background: transparent;")

    def _mono_style(self):
        _s, _b, primary, _sec = self._colors()
        from ui.qt_theme import scaled_area_px
        # Fixed pitch: this line updates on every hover, and proportional
        # digits change width as they change value, which reads as a twitch.
        return (f"color: {primary};"
                f" font-size: {scaled_area_px('status')}px;"
                f" font-family: monospace; border: none; background: transparent;")

    def _asc_style(self):
        from ui.qt_theme import get_theme_accent, scaled_area_px
        accent = get_theme_accent()
        return (f"color: {accent['base']};"
                f" font-size: {scaled_area_px('info_text')}px;"
                f" font-weight: 600; border: none; background: transparent;")

    def _basis_style(self):
        _s, _b, _p, secondary = self._colors()
        from ui.qt_theme import scaled_area_px
        from apps.widgets.map_chrome import dim
        secondary = dim(secondary, 0.55)
        return (f"color: {secondary};"
                f" font-size: {scaled_area_px('status')}px;"
                f" font-style: italic; border: none; background: transparent;")

    # -- content -----------------------------------------------------------

    def set_place(self, city: str = "", country: str = ""):
        self.place_label.setText(city or "Selected point")
        self.country_label.setText(country or "")
        self.country_label.setVisible(bool(country))

    def set_coordinates(self, lat: float, lon: float):
        ns = "N" if lat >= 0 else "S"
        ew = "E" if lon >= 0 else "W"
        self.coord_label.setText(
            f"{abs(lat):8.4f} {ns}   {abs(lon):8.4f} {ew}")

    def set_timezone(self, name: str = "", offset: str = ""):
        if not name:
            self.tz_label.setText("")
            return
        self.tz_label.setText(f"{name}   {offset}".rstrip())

    def set_ascendant(self, text: str = ""):
        self.asc_label.setText(text)
        self.asc_label.setVisible(bool(text))

    def set_basis(self, text: str = ""):
        """Name the instant the bands were computed for, or hide the line."""
        self.basis_label.setText(text)
        self.basis_label.setVisible(bool(text))

    def reposition(self):
        """Pin to the top-right of the parent viewport."""
        parent = self.parentWidget()
        if parent is None:
            return
        self.adjustSize()
        self.move(max(CARD_MARGIN, parent.width() - self.width() - CARD_MARGIN),
                  CARD_MARGIN)

    def refresh_theme(self):
        # ThemedStyleMixin supplies the registry, not a refresh_theme; the
        # subclass owns the method and calls the replay itself.
        self._replay_themed()
        self.reposition()
