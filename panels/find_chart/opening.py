# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Opening a result (design.md §4.9, D11). Qt-free.

A result matched in the search system, so it opens in it: the app is put on
the search's mode, ayanamsa and house system through its runtime zodiac
controls (the toolbar's path, ``ZodiacSettingsManager``) before the chart
loads. The Human Design frame, the Cards of Truth order and the nakshatra
coordinates have no runtime control (the HD frame follows the HD experience
level; the other two are Settings-tab preferences), so the app keeps its own
and the open says so.

Which chart opens: a file entry by its path (``chart_selected``); a session
entry of the current profile by its session id (``session_chart_selected``);
a session entry of another profile is copied into the current session first,
its own profile never written (Q11).
"""

from __future__ import annotations

import json
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from core.chart_search.system import (
    ECLIPTIC_GC_MID_MULA_ID,
    EQUATORIAL_DHRUVA_ID,
    FIELD_SETTINGS,
    Field,
    SearchSystem,
    search_ayanamsa_id,
)
from core.hd_model import hd_frame_for

SESSION_PREFIX = "session:"
#: Find Chart's own ayanamsa ids -> the app's ``zodiac.ayanamsa_id`` that
#: carries it (with the nakshatra coordinates, which stay the app's).
APP_AYANAMSA_IDS: Mapping[int, int] = {ECLIPTIC_GC_MID_MULA_ID: EQUATORIAL_DHRUVA_ID}
#: The runtime keys, in the order they are applied: the ayanamsa and the house
#: system before the mode, so a switch into Sidereal rebuilds the chart once.
MODE_KEY = FIELD_SETTINGS[Field.MODE]
AYANAMSA_KEY = FIELD_SETTINGS[Field.AYANAMSA_ID]
HOUSE_KEY = FIELD_SETTINGS[Field.HOUSE_SYSTEM]
NAKSHATRA_COORDS = "zodiac.nakshatra_coords"
APPLY_ORDER: tuple[str, ...] = (AYANAMSA_KEY, HOUSE_KEY, MODE_KEY)


@dataclass(frozen=True)
class AppFrame:
    """The app's live zodiac frame (``ChartGUI`` state, not the saved settings:
    a write-back lock can keep those behind)."""

    mode: str
    ayanamsa_id: int
    nakshatra_coords: str
    house_system: str


@dataclass(frozen=True)
class SessionRef:
    profile: str
    session_id: str


def session_ref(entry_id: str) -> SessionRef | None:
    """``session:{profile}:{session_id}`` (``sources._session_chart``) split;
    None for a file entry. The session id is a uuid, so the last colon splits."""
    if not entry_id.startswith(SESSION_PREFIX):
        return None
    profile, sep, session_id = entry_id[len(SESSION_PREFIX) :].rpartition(":")
    return SessionRef(profile, session_id) if sep and profile and session_id else None


def session_entry_id(profile: str, session_id: str) -> str:
    return f"{SESSION_PREFIX}{profile}:{session_id}"


def memory_index(charts: Sequence[Mapping[str, object]], session_id: str) -> int:
    """The memory panel index of the chart ``session_id``, -1 when gone."""
    return next((i for i, c in enumerate(charts) if c.get("id") == session_id), -1)


def read_profile_chart(
    profiles_dir: Path, ref: SessionRef
) -> Mapping[str, object] | None:
    """Another profile's session chart, read only; None when it or its
    recipe is gone or the session does not parse."""
    try:
        data = json.loads(
            (profiles_dir / ref.profile / "session.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return None
    charts = data.get("charts") if isinstance(data, dict) else None
    if not isinstance(charts, list):
        return None
    for chart in charts:
        if (
            isinstance(chart, dict)
            and chart.get("id") == ref.session_id
            and isinstance(chart.get("recipe"), dict)
        ):
            return chart
    return None


def frame_changes(target: SearchSystem, app: AppFrame) -> dict[str, object]:
    """The runtime values that put the app on ``target``'s mode, ayanamsa and
    house system, in ``APPLY_ORDER``; empty when it is already there."""
    changes: dict[str, object] = {}
    if target.ayanamsa_id != search_ayanamsa_id(app.ayanamsa_id, app.nakshatra_coords):
        app_id = APP_AYANAMSA_IDS.get(target.ayanamsa_id, target.ayanamsa_id)
        if app_id != app.ayanamsa_id:
            changes[AYANAMSA_KEY] = app_id
    if target.house_system != app.house_system:
        changes[HOUSE_KEY] = target.house_system
    if target.mode.value != app.mode:
        changes[MODE_KEY] = target.mode.value
    return changes


def kept_fields(
    target: SearchSystem,
    app: AppFrame,
    changes: Mapping[str, object],
    pinned: Collection[Field],
    *,
    cot_order: str,
    hd_level: object,
) -> tuple[Field | str, ...]:
    """What the app still differs on from ``target`` once ``changes`` are
    applied: ``NAKSHATRA_COORDS``, and a pinned HD frame or Cards order
    (unpinned, they follow the app's own rule). ``cot_order`` and
    ``hd_level`` are the app's settings."""
    kept: list[Field | str] = []
    new_id = changes.get(AYANAMSA_KEY)
    app_id = new_id if isinstance(new_id, int) else app.ayanamsa_id
    if search_ayanamsa_id(app_id, app.nakshatra_coords) != target.ayanamsa_id:
        kept.append(NAKSHATRA_COORDS)
    if Field.HD_FRAME in pinned and (
        hd_frame_for(target.mode.value, hd_level) != target.hd_frame.value
    ):
        kept.append(Field.HD_FRAME)
    if Field.COT_PLANET_ORDER in pinned and cot_order != target.cot_planet_order.value:
        kept.append(Field.COT_PLANET_ORDER)
    return tuple(kept)
