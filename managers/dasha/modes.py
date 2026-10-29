# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The dasha mode registry (SPEC-DSH-004 §3.2): the ONE list of modes a dasha
panel can show. Both panels offer every row. Adding a dasha = one row here +
one renderer class; the Settings combos, the mode menu, F7/Shift+F7, boot
validation, AI capture regions and remote control all read this table (INV-3).
A renderer implements the protocol of managers/dasha/side.py plus
`capture_options()` (the capability options that reproduce what it lists).

stdlib only; no Qt, no manager import (dasha_state imports it).
"""

from typing import NamedTuple, Optional


class ModeSpec(NamedTuple):
    key: str                 # stored in dasha.<side>.mode
    label: str               # mode menu, Settings combos, status text
    levels: int              # level buttons shown
    nav: str                 # DashaPanelWidget.set_shape nav kind
    title_static: Optional[str]      # fixed title text, None = renderer writes it
    title_tooltip: Optional[str]     # fixed tooltip, None = renderer writes it
    title_enabled: bool
    capability: str         # capability the AI capture region calls
    region: str             # region id stem (right side keeps the bare stem)
    renderer: str           # "module:Class" of the renderer (lazy import)
    status_label: str       # status-bar text after a switch
    reads: tuple            # settings leaves this mode's rows depend on
                            # ("{side}" = the side name); a pending write to one
                            # of them re-lists a side in this mode (§4.5).
                            # "view.*" = a view input (shown varga, ascendant
                            # override): DashaManager.on_view_input_changed
    region_name: str = ""   # AI capture region name (default: status_label)
    short_label: str = ""   # chart title submenu label (default: label)
    relist_on_apply: bool = True   # Settings Apply re-lists (and resets) a side
                                   # in this mode (Planetary Ages: no, as before)


MODES = (
    ModeSpec("vimshottari", "Vimshottari", 5, "cycle", None,
             "Click to change ayanamsa", True,
             "get_dasha", "dasha", "managers.dasha.side_controller:VimshottariSideController",
             "Vimshottari Dasha",
             ("dasha.{side}.ayanamsa_id", "dasha.year_length.nakshatra",
              "display.date_format", "display.calendar_convention"), "Dasha"),
    ModeSpec("nisarga", "Planetary Ages", 5, "hidden", "Planetary Ages",
             "Natural Planetary Ages", False,
             "get_planetary_ages", "planetary_ages", "managers.dasha.nisarga:NisargaRenderer",
             "Planetary Ages", ("display.date_format",), relist_on_apply=False),
    ModeSpec("zr", "Zodiacal Releasing", 4, "strip", None, None, True,
             "get_zodiacal_releasing", "zodiacal_releasing", "managers.dasha.zr:ZRRenderer",
             "Zodiacal Releasing",
             ("display.date_format", "display.calendar_convention", "view.sign_names",
              "dasha.zr.releaser", "dasha.zr.spirit_shift", "dasha.zr.show_age",
              "dasha.zr.anchor"), short_label="Releasing"),
)

VALID_MODES = tuple(m.key for m in MODES)

# Per-side defaults keep today's screen on upgrade (INV-6, D-5).
DEFAULT_MODE = {"left": "vimshottari", "right": "nisarga"}

SIDES = ("left", "right")


def mode_spec(key):
    """The ModeSpec for `key`; KeyError on an unknown mode."""
    for m in MODES:
        if m.key == key:
            return m
    raise KeyError(f"unknown dasha mode {key!r}; expected one of {VALID_MODES}")


def next_mode(key):
    """The mode after `key` in registry order (F7 / Shift+F7 cycle); an unknown
    key starts at the first mode."""
    if key in VALID_MODES:
        return VALID_MODES[(VALID_MODES.index(key) + 1) % len(VALID_MODES)]
    return VALID_MODES[0]


def normalize_mode(side, mode, logger=None):
    """`mode` if valid, else the side's default with one warning (per-side
    version of the old right-only rule, review R1-4)."""
    if mode in VALID_MODES:
        return mode
    default = DEFAULT_MODE[side]
    if logger is not None:
        logger.warning("unknown dasha.%s.mode %r; falling back to %r",
                       side, mode, default)
    return default


def region_id(side, mode_key):
    """AI capture region id for (side, mode). Existing ids stay byte-identical
    (SPEC-DSH-004 §4.6): right = the bare stem except Vimshottari, which is
    `dasha_right`; left = `dasha_left` for Vimshottari, `<stem>_left` otherwise."""
    m = mode_spec(mode_key)
    if m.key == "vimshottari":
        return f"dasha_{side}"
    return m.region if side == "right" else f"{m.region}_left"


def mode_reads(key, side):
    """The settings leaves mode `key` reads on `side`."""
    return {leaf.format(side=side) for leaf in mode_spec(key).reads}
