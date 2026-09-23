"""Typed graphics capabilities; callbacks close over weak references at composition."""
from dataclasses import dataclass
from typing import Callable
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QLabel,QMenu
from apps.widgets.south_indian_paint_style import RenderStyle

@dataclass(frozen=True)
class LayerServices:
    scene: object
    style: RenderStyle
    ruler: bool
    notice: QLabel
    translate: Callable[[str], str]
    menu_factory: Callable[[], QMenu]
    global_position: Callable[[QPointF], object]

    @property
    def wood(self):
        return self.style.wood

    @property
    def vector_finish(self):
        return self.style.finish

    @property
    def display_settings(self):
        return self.style.display
