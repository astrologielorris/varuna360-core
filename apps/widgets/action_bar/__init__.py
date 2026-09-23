"""SPEC-BAR-001 action bar v2 (Vibrancy Segmented) — flag: ui.action_bar_v2.

Structure: bar_types (fonts + metrics, INV-3), segment_button / clusters /
title_well (thin stateful widgets), paint_controls / paint_surfaces (ALL
pixels — the design surface), action_bar (assembly + legacy attribute
census, INV-5).
"""
from .action_bar import ChartActionBar, create_action_bar

__all__ = ["ChartActionBar", "create_action_bar"]
