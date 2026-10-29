# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Dasha navigation state (SPEC-DSH-002).

Plain state objects for the dasha navigation subsystem, extracted from the
scattered ``ChartGUI`` attributes and ``DashaManager`` locals so the manager
owns one coherent store instead of a shared blackboard (Rule 4b). This module
is *inert* at wave 1 commit w1-1: nothing imports it yet; ``DashaManager`` wires
it in at w1-2.

Structure (decision 4: internal names are ``left`` / ``right`` only;
SPEC-DSH-004: the two sides have the same shape):
- ``SideState``   — one dasha side: its mode, the Vimshottari navigation (level,
                    parent chain, 120-year cycle offset, cached rows, ayanamsa
                    id), the Nisarga level and the ZR state.
- ``DashaState``  — the two sides and the nakshatra-family year length.
- ``ZRPanelState`` — one per side.

Imports only the stdlib and ``managers.dasha.modes`` (itself stdlib-only), so
there is no import cycle with ``dasha_manager``.
"""

import logging

logger = logging.getLogger(__name__)

# Boot defaults, also the fallbacks every settings read uses (never `value or
# default`: ayanamsa id 0 is a valid value). Keys: dasha.{left,right}.ayanamsa_id,
# dasha.{left,right}.mode.
LEFT_DEFAULT_AYANAMSA = 100
RIGHT_DEFAULT_AYANAMSA = 98
# SPEC-DSH-004: modes come from the one registry (managers/dasha/modes.py);
# both sides offer every mode, each with its own default.
from managers.dasha.modes import VALID_MODES, DEFAULT_MODE, normalize_mode  # noqa: E402
# SPEC-DSH-003: dasha year length for the nakshatra-dasha family (Vimshottari,
# both panels). Key: dasha.year_length.nakshatra. Keys mirror
# core.vimshottari_dasha.YEAR_LENGTHS; Saura is Kala's default and ours.
DEFAULT_YEAR_LENGTH = "saura"
VALID_YEAR_LENGTHS = ("saura", "savana", "nakshatra", "sidereal", "chandra", "lunar")


class ZRPanelState:
    """All Zodiacal Releasing panel state of one side (Rule 4b: lives on the
    side's SideState, read through DashaManager.zr_state(side), never on ChartGUI). Mutated only through DashaManager
    methods. `parent_chain` holds the drilled-into ancestor Period rows
    (L1 for level 2, [L1, L2] for level 3, [L1, L2, L3] for level 4)."""

    __slots__ = ("releaser", "spirit_shift", "show_age", "anchor",
                 "level", "parent_chain", "result")

    def __init__(self):
        self.releaser = "spirit"
        self.spirit_shift = True
        self.show_age = False
        self.anchor = "birth"
        self.level = 1
        self.parent_chain = []
        self.result = None      # last compute_zr() result (meta for tooltips)


class SideState:
    """One dasha panel side (SPEC-DSH-004 §3.4). Both sides have the same shape:
    the current `mode`, the Vimshottari navigation (`level`, `parent_chain`,
    `cycle_offset`, `rows`, `ayanamsa`; names kept from SPEC-DSH-002), the
    Nisarga level and the ZR state. `ayanamsa` is kept in every
    mode: the left one also drives the Pro Nakshatra and map pages' ayanamsa (INV-10)."""

    __slots__ = ("level", "parent_chain", "cycle_offset", "rows", "ayanamsa",
                 "mode", "nisarga_level", "zr")

    def __init__(self, ayanamsa, mode="vimshottari"):
        self.level = 1
        self.parent_chain = []      # parent lord entries for the filtered sub-dasha view
        self.cycle_offset = 0       # 120-year cycle offset (past/current/future)
        self.rows = None            # cached dasha rows (list of dicts) or None
        self.ayanamsa = ayanamsa    # ayanamsa id for this side's Vimshottari compute
        self.mode = mode            # registry key (managers/dasha/modes.py)
        self.nisarga_level = 1      # Nisarga: 1=periods, 2=maturation
        self.zr = ZRPanelState()

    def reset_all_navigation(self):
        """Chart-context reset of every mode's navigation on this side."""
        self.reset_navigation(offset=True)
        self.nisarga_level = 1
        self.zr.level = 1
        self.zr.parent_chain = []
        self.zr.result = None

    def reset_mode_entry(self, mode):
        """Targeted reset when this side (re)enters `mode`: only that mode's
        navigation resets (the Vimshottari cycle offset is kept)."""
        if mode == "nisarga":
            self.nisarga_level = 1
        elif mode == "vimshottari":
            self.reset_navigation(offset=False)
        elif mode == "zr":
            self.zr.level = 1
            self.zr.parent_chain = []
        else:
            # A registry mode with no state here keeps its navigation in its
            # renderer (reset in its enter()): adding a mode needs no edit
            # here. Validated against the LIVE registry, so it stays strict.
            from managers.dasha import modes
            if mode not in tuple(m.key for m in modes.MODES):
                raise ValueError(
                    f"unknown dasha mode {mode!r}; expected one of {VALID_MODES}")

    def reset_navigation(self, *, offset):
        """Reset navigation to level 1: level 1, empty parent chain, no cached
        rows. ``offset=True`` also zeroes the 120-year cycle offset (chart
        context and the ayanamsa-dialog routes); ``offset=False`` keeps it
        (Settings Apply, mode entry). The ayanamsa id is ALWAYS kept."""
        self.level = 1
        self.parent_chain = []
        self.rows = None
        if offset:
            self.cycle_offset = 0

    def mark_current(self, jd, lord, level):
        """Flip ``is_current`` in the CACHED rows only (``self.rows``). For every
        cached row at ``level``, ``is_current`` becomes True iff its (jd, lord)
        match the clicked entry; rows at other levels are untouched. Mirrors the
        cache-update block that today lives in
        ``DashaManager._select_dasha_entry`` (w1-2 wires it)."""
        if not self.rows:
            return
        for entry in self.rows:
            if entry.get('level', 0) == level:
                entry['is_current'] = (entry.get('jd') == jd
                                       and entry.get('lord') == lord)


class DashaState:
    """The whole dasha navigation subsystem's state: two identical sides plus the
    nakshatra-family year length they share. Owned by ``DashaManager``;
    constructed once at boot via ``from_settings``."""

    __slots__ = ("left", "right", "year_length", "session_options")

    def __init__(self, left_ayanamsa=LEFT_DEFAULT_AYANAMSA,
                 right_ayanamsa=RIGHT_DEFAULT_AYANAMSA,
                 right_mode=DEFAULT_MODE["right"],
                 year_length=DEFAULT_YEAR_LENGTH,
                 left_mode=DEFAULT_MODE["left"]):
        self.left = SideState(left_ayanamsa, left_mode)
        self.right = SideState(right_ayanamsa, right_mode)
        self.year_length = year_length            # shared by both Vimshottari sides
        # Title-menu picks of a LOCKED shared option (dasha.zr.*):
        # adopted for this session, never saved (the lock keeps the stored value).
        self.session_options = {}

    @classmethod
    def from_settings(cls, settings):
        """Build boot state from the authoritative settings store. Reads the two
        ayanamsa ids and the two modes with ``get(key, default)`` (never
        ``value or default`` — id 0 is a valid value). An unknown mode falls back
        to that side's default with one warning, so a bad key can never crash
        the boot reshape."""
        left_ayanamsa = settings.get("dasha.left.ayanamsa_id", LEFT_DEFAULT_AYANAMSA)
        right_ayanamsa = settings.get("dasha.right.ayanamsa_id", RIGHT_DEFAULT_AYANAMSA)
        modes = {side: normalize_mode(
                    side, settings.get(f"dasha.{side}.mode", DEFAULT_MODE[side]), logger)
                 for side in ("left", "right")}
        year_length = settings.get("dasha.year_length.nakshatra", DEFAULT_YEAR_LENGTH)
        if year_length not in VALID_YEAR_LENGTHS:
            logger.warning(
                "unknown dasha.year_length.nakshatra %r; falling back to %r",
                year_length, DEFAULT_YEAR_LENGTH)
            year_length = DEFAULT_YEAR_LENGTH
        return cls(left_ayanamsa, right_ayanamsa, modes["right"], year_length,
                   modes["left"])

    def side(self, name):
        """Return the ``SideState`` for ``name`` — ``"left"`` or ``"right"``
        ONLY (decision 4). Legacy names (``"vedanga"``, ``"vimshottari"``) are
        translated at the remote and widget boundaries, never here; passing one
        is a programming error and raises."""
        if name == "left":
            return self.left
        if name == "right":
            return self.right
        raise ValueError(
            f"unknown dasha side {name!r}; expected 'left' or 'right'")

    def reset_for_chart(self):
        """Chart-context reset (decision 2): a new chart clears ALL navigation of
        every mode on both sides. Called only from the chart-context sites."""
        self.left.reset_all_navigation()
        self.right.reset_all_navigation()

    def reset_mode_entry(self, side, mode):
        """Targeted reset when ``side`` enters ``mode``: only that mode's
        navigation on that side resets."""
        self.side(side).reset_mode_entry(mode)
