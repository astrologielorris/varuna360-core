# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Dasha navigation state (SPEC-DSH-002).

Plain state objects for the dasha navigation subsystem, extracted from the
scattered ``ChartGUI`` attributes and ``DashaManager`` locals so the manager
owns one coherent store instead of a shared blackboard (Rule 4b). This module
is *inert* at wave 1 commit w1-1: nothing imports it yet; ``DashaManager`` wires
it in at w1-2.

Structure (decision 4: internal names are ``left`` / ``right`` only):
- ``SideState``   — one Vimshottari-family side (the left panel, or the right
                    panel while it is in Vimshottari mode): level, parent chain,
                    120-year cycle offset, cached rows, ayanamsa id.
- ``DashaState``  — the whole subsystem: the two ``SideState`` sides, the right
                    panel's current mode, the Nisarga level (Nisarga has no
                    cached rows and no chain), and the ZR panel state.
- ``ZRPanelState``— all Zodiacal Releasing panel state, moved here unchanged
                    from ``DashaManager``.

stdlib only; imports NOTHING from ``managers`` (no import cycle — ``dasha_manager``
imports from here at w1-2).
"""

import logging

logger = logging.getLogger(__name__)

# Boot defaults, also the fallbacks every settings read uses (never `value or
# default`: ayanamsa id 0 is a valid value). Keys: dasha.left.ayanamsa_id,
# dasha.right.ayanamsa_id, dasha.right.mode.
LEFT_DEFAULT_AYANAMSA = 100
RIGHT_DEFAULT_AYANAMSA = 98
DEFAULT_RIGHT_MODE = "nisarga"
VALID_RIGHT_MODES = ("vimshottari", "nisarga", "zr")
# SPEC-DSH-003: dasha year length for the nakshatra-dasha family (Vimshottari,
# both panels). Key: dasha.year_length.nakshatra. Keys mirror
# core.vimshottari_dasha.YEAR_LENGTHS; Saura is Kala's default and ours.
DEFAULT_YEAR_LENGTH = "saura"
VALID_YEAR_LENGTHS = ("saura", "savana", "nakshatra", "sidereal")


class ZRPanelState:
    """All Zodiacal Releasing panel state (Rule 4b: lives on DashaManager as
    `self.zr_state`, never on ChartGUI). Mutated only through DashaManager
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
    """One Vimshottari-family side: the left panel, or the right panel while it
    is in Vimshottari mode. Nisarga (no cached rows, level in
    ``DashaState.nisarga_level``) and ZR (``DashaState.zr``) are NOT sides."""

    __slots__ = ("level", "parent_chain", "cycle_offset", "rows", "ayanamsa")

    def __init__(self, ayanamsa):
        self.level = 1
        self.parent_chain = []      # parent lord entries for the filtered sub-dasha view
        self.cycle_offset = 0       # 120-year cycle offset (past/current/future)
        self.rows = None            # cached dasha rows (list of dicts) or None
        self.ayanamsa = ayanamsa    # ayanamsa id for this side's compute

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
    """The whole dasha navigation subsystem's state. Owned by ``DashaManager``
    (w1-2); constructed once at boot via ``from_settings`` so a saved or locked
    config is honoured before the first dasha compute."""

    __slots__ = ("left", "right", "right_mode", "nisarga_level", "zr",
                 "year_length")

    def __init__(self, left_ayanamsa=LEFT_DEFAULT_AYANAMSA,
                 right_ayanamsa=RIGHT_DEFAULT_AYANAMSA,
                 right_mode=DEFAULT_RIGHT_MODE,
                 year_length=DEFAULT_YEAR_LENGTH):
        self.left = SideState(left_ayanamsa)
        self.right = SideState(right_ayanamsa)   # right panel in Vimshottari mode only
        self.right_mode = right_mode
        self.year_length = year_length            # shared by both Vimshottari sides
        self.nisarga_level = 1                    # Nisarga: 1=periods, 2=maturation
        self.zr = ZRPanelState()

    @classmethod
    def from_settings(cls, settings):
        """Build boot state from the authoritative settings store. Reads the two
        ayanamsa ids and the right-panel mode with ``get(key, default)`` (never
        ``value or default`` — id 0 is a valid value). An unknown or bogus mode
        (a future build's mode, a corrupt profile) falls back to
        ``DEFAULT_RIGHT_MODE`` with one warning, so a bad key can never crash the
        boot reshape."""
        left_ayanamsa = settings.get("dasha.left.ayanamsa_id", LEFT_DEFAULT_AYANAMSA)
        right_ayanamsa = settings.get("dasha.right.ayanamsa_id", RIGHT_DEFAULT_AYANAMSA)
        mode = settings.get("dasha.right.mode", DEFAULT_RIGHT_MODE)
        if mode not in VALID_RIGHT_MODES:
            logger.warning(
                "unknown dasha.right.mode %r; falling back to %r",
                mode, DEFAULT_RIGHT_MODE)
            mode = DEFAULT_RIGHT_MODE
        year_length = settings.get("dasha.year_length.nakshatra", DEFAULT_YEAR_LENGTH)
        if year_length not in VALID_YEAR_LENGTHS:
            logger.warning(
                "unknown dasha.year_length.nakshatra %r; falling back to %r",
                year_length, DEFAULT_YEAR_LENGTH)
            year_length = DEFAULT_YEAR_LENGTH
        return cls(left_ayanamsa, right_ayanamsa, mode, year_length)

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
        """Chart-context reset (decision 2): a new chart clears ALL navigation.
        Both sides reset navigation including the cycle offset; Nisarga level and
        the ZR drill state reset to their entry points. Called only from the
        three chart-context sites (new chart, memory panel, HD toggle)."""
        self.left.reset_navigation(offset=True)
        self.right.reset_navigation(offset=True)
        self.nisarga_level = 1
        self.zr.level = 1
        self.zr.parent_chain = []
        self.zr.result = None

    def reset_mode_entry(self, mode):
        """Targeted reset when the right panel enters ``mode`` (from
        ``configure_right_panel``). Only the entered mode's navigation resets;
        the other modes' stored state is untouched (today's behaviour: entering
        Vimshottari resets its chain, but the cycle offset is kept)."""
        if mode == "nisarga":
            self.nisarga_level = 1
        elif mode == "vimshottari":
            self.right.reset_navigation(offset=False)
        elif mode == "zr":
            self.zr.level = 1
            self.zr.parent_chain = []
        else:
            raise ValueError(
                f"unknown right-panel mode {mode!r}; "
                f"expected one of {VALID_RIGHT_MODES}")
