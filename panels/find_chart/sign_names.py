# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The Find Chart sign-name switcher (varuna/47).

Find Chart's own display choice: by system (the Aditya names in the Aditya
Circle, the zodiac names in Tropical Classic and Sidereal), the Aditya names or
the zodiac names. It persists under ``SIGN_NAMES_KEY`` and never writes the
app's ``zodiac.use_western_names``.
"""

from __future__ import annotations

from collections.abc import Mapping

from core.chart_search.taxonomy import SignNames
from managers.settings_manager import get_settings
from panels.find_chart.combos import ReadableCombo
from ui.qt_theme import scaled_area_px

#: The settings registry key the choice persists under (house rule 2).
SIGN_NAMES_KEY = "ui.find_chart_sign_names"
LABELS: Mapping[SignNames, str] = {
    SignNames.BY_SYSTEM: "Names: by system",
    SignNames.ADITYA: "Aditya names",
    SignNames.ZODIAC: "Zodiac names",
}


def saved_sign_names() -> SignNames:
    """The saved choice, or by system when it is not one this build knows."""
    try:
        return SignNames(get_settings().get(SIGN_NAMES_KEY, SignNames.BY_SYSTEM.value))
    except ValueError:
        return SignNames.BY_SYSTEM


class SignNamesCombo(ReadableCombo):
    """Emits ``currentIndexChanged`` after saving the pick."""

    def __init__(self) -> None:
        super().__init__()
        for names, label in LABELS.items():
            self.addItem(label, names.value)
        self.setCurrentIndex(self.findData(saved_sign_names().value))
        self.setToolTip(
            "The sign names in this panel only. By system: the Aditya names in "
            "the Aditya Circle, the zodiac names in Tropical Classic and Sidereal."
        )
        self.currentIndexChanged.connect(self._save)
        self.refresh_style()

    def sign_names(self) -> SignNames:
        return SignNames(self.currentData())

    def _save(self, _index: int) -> None:
        get_settings().set(SIGN_NAMES_KEY, self.currentData())

    def refresh_style(self) -> None:
        self.setStyleSheet(f"QComboBox {{ font-size: {scaled_area_px('buttons')}px; }}")
