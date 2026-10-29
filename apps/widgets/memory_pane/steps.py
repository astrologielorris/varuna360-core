# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The pane's four width steps (MC-INTENT "Width steps").

The window width picks a step; a step is ONE set of geometry and label
choices, applied together. No control ever disappears: at S3 the secondary
actions (SORT, SELECT, CLEAR ALL) live in the ⋯ menu, everywhere else every
action has its own visible cell.

    S0 >= 1600  full labels                     well 146, columns 70 / 90
    S1 1366+    CLEAR, A→Z (short labels)       well 146, columns 70 / 64
    S2 1200+    icons; SORT keeps its mode word well 112 (count + ticks + key)
    S3 < 1200   [SEARCH] over [⋯]               well 100, one 30 px column
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Step:
    name: str
    well_w: int        # profile well width
    col1: int          # first pill column (SEARCH / SELECT)
    col2: int          # second pill column (SORT / CLEAR); 0 = one column
    unit_gap: int      # gap between well, D-pad and actions
    labels: str        # "full" | "short" | "icons" | "fold"

    @property
    def folded(self) -> bool:
        return self.labels == "fold"

    @property
    def well_compact(self) -> bool:
        """Well shows count + ticks + key only (name, CHARTS, LOAD in tooltips)."""
        return self.labels in ("icons", "fold")


S0 = Step("S0", 146, 70, 90, 8, "full")
S1 = Step("S1", 146, 70, 64, 8, "short")
S2 = Step("S2", 112, 28, 58, 8, "icons")
S3 = Step("S3", 100, 30, 0, 6, "fold")
STEPS = (S0, S1, S2, S3)

# Window widths (px) at which each step starts.
_THRESHOLDS = ((1600, S0), (1366, S1), (1200, S2))


def step_for_width(width: int) -> Step:
    for minimum, step in _THRESHOLDS:
        if width >= minimum:
            return step
    return S3
