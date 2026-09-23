"""Appearance values and callables used for one paint pass, never retained by painters."""
from dataclasses import dataclass
from typing import Callable
from apps.widgets.south_indian_items import PlanetClickSignal, SignClickSignal
from PySide6.QtGui import QColor, QPixmap
from ui.south_indian_finishes import WOOD
from apps.widgets.south_indian_material import pigment
@dataclass(frozen=True)
class RenderStyle:
    finish: str
    sign_display: str
    language: str
    display: dict
    planet_sizes: dict
    sign_icon: "Callable[[int, int], QPixmap | None]"
    planet_icon: "Callable[[str, int], QPixmap | None]"
    sign_variation: "Callable[[int], int]"
    house_number_font: int
    foreground_only: bool = False
    @property
    def wood(self):
        return WOOD.get(self.finish)

    def ink(self, key, fallback):
        return pigment(self.wood['ink'][key]) if self.wood else QColor(fallback)

@dataclass
class LayoutMetrics:
    badge_band: dict
    pill_bottom: dict

@dataclass(frozen=True)
class ClickSignals:
    planet: PlanetClickSignal
    sign: SignClickSignal
