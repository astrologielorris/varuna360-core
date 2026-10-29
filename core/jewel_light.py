# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""The V2 star light strength (SPEC-RST-001 D-32, td-9scg9). Qt-free.

``chart.retinue_strength_light_amount`` (0..100, default 50) is THE control of the Jewel
Lamp star (the Chesta light channel: the centred radial light and the two rays): the
Chesta part becomes ``clamp(chesta / 60 x amount / 60)``. 60 = the first V2 look, 50 = 5/6
of it, 0 = no star; the colour strength no longer scales the light. V1 never reads it.
"""
from core.settings_registry import default

KEY_LIGHT = "chart.retinue_strength_light_amount"
PLAIN = 60.0


def scale(amount) -> float:
    """``amount / 60`` (``amount`` clamped to 0..100); missing or invalid = the registry default."""
    try:
        return max(0.0, min(100.0, float(amount))) / PLAIN
    except (TypeError, ValueError):
        return float(default(KEY_LIGHT)) / PLAIN
