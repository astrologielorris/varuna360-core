# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""Row and column header heights of the info panel tables, from the font areas (W6 R5).

One formula for ``info_panels`` (its ``_table_row_height`` and ``_column_header_height``
pass their own ``scaled_area_px``) and for the key headers of the two center drawings
(``tajika_center_keys``, ``vedic_center_keys``), which so never import ``info_panels``.
"""
from __future__ import annotations

from typing import Callable, Optional


def _area_px(area_id: str) -> int:
    from ui.qt_theme import scaled_area_px
    return scaled_area_px(area_id)


def table_row_height(area_id: str = "tables", padding: int = 8, min_h: int = 18,
                     px: Optional[Callable[[str], int]] = None) -> int:
    """Row height = the effective font pixel size of ``area_id`` + padding, with a floor."""
    return max(min_h, (px or _area_px)(area_id) + padding)


def column_header_height(px: Optional[Callable[[str], int]] = None) -> int:
    """The compact column header height, from the ``table_headers`` font size."""
    return max(20, (px or _area_px)("table_headers") + 8)
