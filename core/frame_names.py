# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The name a chart frame is shown under, for headings over computed data.

Made only of the names the app already shows (SPEC-SET-003 W8 fix round 2,
N1): the zodiac mode's name as the app's zodiac buttons and the dasha and
Zodiacal Releasing outputs write it (``core.zodiacal_releasing._ZODIAC_DISPLAY``:
Aditya Circle, Tropical Classic, Sidereal), and the app's own `` *`` mark on
that button when the signs carry the other label set
(``ChartGUI._update_toggle_button_styles``: "Aditya Circle *" is the Aditya
Circle with the Western names, "Sidereal *" the Sidereal zodiac with the
Aditya names). A heading built from these is data about the frame, never a
fixed claim that the data is in the Aditya Circle.

Qt-free, data only.
"""
from __future__ import annotations

from typing import Optional

from core.zodiacal_releasing import _ZODIAC_DISPLAY as MODE_NAMES

#: The app's mark for the other label set (the zodiac button's text suffix).
OTHER_LABELS_MARK = " *"


def native_western_names(mode: str) -> bool:
    """The label set a mode shows by default: the Western names everywhere
    but in the Aditya Circle (``ChartFrame.resolve``'s native label set)."""
    return mode != "aditya"


def frame_name(mode: str, use_western_names: Optional[bool] = None) -> str:
    """``mode``'s shown name, with the app's mark when ``use_western_names``
    is the other label set (None: the mode's own names)."""
    name = MODE_NAMES.get(mode, mode)
    if use_western_names is not None and bool(use_western_names) != native_western_names(mode):
        name += OTHER_LABELS_MARK
    return name


def frame_name_of(frame) -> str:
    """The shown name of a ``ChartFrame`` (its mode and label set)."""
    return frame_name(frame.mode, frame.use_western_names)
