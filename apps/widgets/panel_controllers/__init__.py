# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0.
"""
Panel controllers — Phase 4 self-updating panels.

Each controller subscribes to ChartState.state_changed and refreshes its
target widget without requiring panel_update_manager push calls.

Controllers are added to this package one wave at a time (W1 through W2.11).
"""

from apps.widgets.panel_controllers.elements_controller import ElementsController
from apps.widgets.panel_controllers.modality_controller import ModalityController
from apps.widgets.panel_controllers.hora_controller import HoraController
from apps.widgets.panel_controllers.trimsamsa_controller import TrimsamsaController
from apps.widgets.panel_controllers.house_graph_controller import HouseGraphController
from apps.widgets.panel_controllers.karakas_controller import KarakasController
from apps.widgets.panel_controllers.strength_controller import StrengthController
from apps.widgets.panel_controllers.aspects_controller import AspectsController
from apps.widgets.panel_controllers.avastha_controller import AvasthaController
from apps.widgets.panel_controllers.shame_controller import ShameController
from apps.widgets.panel_controllers.tajika_matrix_controller import TajikaMatrixController
from apps.widgets.panel_controllers.tajika_relationships_controller import TajikaRelationshipsController
from apps.widgets.panel_controllers.tajika_yogas_controller import TajikaYogasController
from apps.widgets.panel_controllers.dignities_controller import DignitiesController
from apps.widgets.panel_controllers.interchange_controller import InterchangeController

__all__ = [
    "ElementsController",
    "ModalityController",
    "HoraController",
    "TrimsamsaController",
    "HouseGraphController",
    "KarakasController",
    "StrengthController",
    "AspectsController",
    "AvasthaController",
    "ShameController",
    "TajikaMatrixController",
    "TajikaRelationshipsController",
    "TajikaYogasController",
    "DignitiesController",
    "InterchangeController",
]
