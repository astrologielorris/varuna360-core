# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Pure dasha compute/render engine (SPEC-DSH-002, td-t761 wave 2, w2-1).

Plain functions over plain lists of row dicts — NO Qt, NO ChartGUI, NO other
`managers.*` import. The only non-stdlib dependency is `core.time_utils`
(display-only JD→civil helpers), whose two display settings are passed in
EXPLICITLY so the engine never reads app settings (sol r1-1).

Every function is total over its own inputs (no exception escapes for well-typed
rows) and touches no global state. The one exception to totality is the caller's
`progress` callback passed to :func:`filter_rows`: exceptions it raises PROPAGATE
unchanged, because that is how the controller's `_StaleRender` aborts a stale
render (sol r1-1).

Bodies are ported VERBATIM from `managers/dasha_manager.py` at the wave-1 merge
`097735f9`; the source line anchors are cited per function. Behaviour is
byte-identical to the two paired renderers this replaces — the engine holds the
logic, the w2-2 controller executes the Qt side.

Row dicts (from `core/vimshottari_dasha.py`) carry the keys:
``lord date time indent is_current jd end_jd level`` with ``indent == "  " * level``.
"""

from dataclasses import dataclass

from core.time_utils import display_revjul, format_display_ymd

# Row prefixes (moved from the manager's _PREFIX_CURRENT / _PREFIX_NORMAL).
PREFIX_CURRENT = "▶ "
PREFIX_NORMAL = "  "

FLAT_VIEW_CAP = 500      # max flat rows shown at level >= 3 with no parent chain
MAX_LEVEL = 5            # deepest drill level
CYCLE_YEARS = 120        # one Vimshottari cycle


@dataclass(frozen=True)
class ComputeStep:
    """One compute decision the controller must execute.

    kind:
      "full"  -> calculate_dasha_from_birth_data(dlevels=dlevels, nak_mode=...)
      "sub"   -> calculate_sub_dashas_for_period(parent['jd'], parent['end_jd'], parent_lord)
      "probe" -> calculate_dasha_from_birth_data(dlevels=dlevels, nak_mode=...) then decide_after_probe
      "reset" -> the absolute fallback: reset the side to level 1 / empty chain,
                 then calculate_dasha_from_birth_data(dlevels=1, nak_mode=...)

    with_nak_mode means "this calculate_dasha_from_birth_data call passes
    nak_mode": True on full, probe and reset (td-2yqd fixed the full path to pass
    nak_mode too, so the level-1-2 seed follows nakshatra_coords like the drilled
    levels — Kala applies the setting at level 1); irrelevant to "sub" (a
    different engine function that takes no nak_mode).
    """

    kind: str
    dlevels: int = None
    with_nak_mode: bool = False
    parent: dict = None
    parent_lord: str = None


# --------------------------------------------------------------------------- #
# Focused-calc decision (verbatim dasha_manager.py:1214-1251)                  #
# --------------------------------------------------------------------------- #

def lord_depth(lord):
    """Depth of a slash-joined lord path: 'Su' -> 1, 'Su/Mo/Ma' -> 3."""
    return lord.count("/") + 1


def focused_calc_decision(level, chain):
    """The parent lord to run a focused sub-calc on, or None for the full calc.

    Verbatim :1218-1222: focus only when level >= 3, a chain exists, and the
    chain's last lord is deep enough (depth >= level - 1); else None.
    """
    if level >= 3 and chain:
        parent_lord = chain[-1]
        if lord_depth(parent_lord) >= level - 1:
            return parent_lord
    return None


def find_parent_entry(rows, lord):
    """The FIRST row whose 'lord' matches, or None (verbatim :1225-1229).

    No key check here — `decide_compute` / `decide_after_probe` validate that the
    matched row carries 'jd' and 'end_jd' and probe when they are missing
    (sol r1-9).
    """
    if not rows:
        return None
    for entry in rows:
        if entry.get("lord") == lord:
            return entry
    return None


def decide_compute(level, chain, cached_rows):
    """Choose the compute step from the level, the parent chain and the cache.

    Mirrors :1214-1284: no focus -> full; focus with a valid cached parent ->
    sub; focus with a cache miss (parent absent OR missing jd/end_jd) -> probe at
    just enough depth (len(chain)), passing nak_mode.
    """
    focus = focused_calc_decision(level, chain)
    if focus is None:
        return ComputeStep(kind="full", dlevels=level, with_nak_mode=True)
    entry = find_parent_entry(cached_rows, focus)
    if entry is not None and "jd" in entry and "end_jd" in entry:
        return ComputeStep(kind="sub", parent=entry, parent_lord=focus)
    return ComputeStep(kind="probe", dlevels=len(chain),
                       with_nak_mode=True, parent_lord=focus)


def decide_after_probe(fresh_rows, parent_lord):
    """After the probe recompute (:1246-1275): sub if the parent surfaced with
    jd/end_jd, else the absolute fallback reset to level 1."""
    entry = find_parent_entry(fresh_rows, parent_lord)
    if entry is not None and "jd" in entry and "end_jd" in entry:
        return ComputeStep(kind="sub", parent=entry, parent_lord=parent_lord)
    return ComputeStep(kind="reset", dlevels=1, with_nak_mode=True)


# --------------------------------------------------------------------------- #
# Parent-chain helpers (verbatim :428-443, :519-525, :884-903)                 #
# --------------------------------------------------------------------------- #

def trim_chain_for_level(chain, level):
    """Trim a parent chain to `level` (verbatim :447-455 minus the auto-build).

    [] at level 1; otherwise chain[:level-1], dropped to [] when its last lord is
    shallower than level-1. The caller auto-builds (auto_chain + probe) when the
    result is empty and level >= 2.
    """
    if level == 1:
        return []
    trimmed = chain[:level - 1]
    if trimmed:
        last_depth = lord_depth(trimmed[-1])
        if last_depth < level - 1:
            trimmed = []
    return trimmed


def auto_chain(rows, needed_depth):
    """Current lords at each depth 1..needed_depth (verbatim _extract_current_chain).

    Stops early at the first depth with no is_current entry (a gap), so the chain
    may be shorter than needed_depth.
    """
    if not rows:
        return []
    chain = []
    for depth in range(needed_depth):
        for entry in rows:
            if not entry.get("is_current"):
                continue
            lord = entry.get("lord", "")
            if lord.count("/") + 1 == depth + 1:
                chain.append(lord)
                break
        else:
            break
    return chain


def click_expansion(clicked_lord, current_level):
    """Expansion decision for a click on `clicked_lord` (verbatim :519-525).

    Returns (new_chain, new_level, expand): the cumulative lord prefixes as the
    new chain, the new level capped at MAX_LEVEL, and whether to expand (True) or
    fall through to the max-depth toggle-select (False).
    """
    lord_parts = clicked_lord.split("/")
    new_chain = ["/".join(lord_parts[:i + 1]) for i in range(len(lord_parts))]
    new_level = min(len(new_chain) + 1, MAX_LEVEL)
    expand = new_level > current_level or current_level < MAX_LEVEL
    return new_chain, new_level, expand


def parent_chain_of(entry, all_rows, index):
    """Trace `entry`'s parent lords by walking back through less-indented rows
    (verbatim extract_parent_chain_from_entry, :884-903)."""
    parents = []
    current_indent = len(entry.get("indent", ""))
    for i in range(index - 1, -1, -1):
        prev_entry = all_rows[i]
        prev_indent = len(prev_entry.get("indent", ""))
        if prev_indent < current_indent:
            parents.insert(0, prev_entry.get("lord", ""))
            current_indent = prev_indent
            if current_indent == 0:
                break
    return parents


# --------------------------------------------------------------------------- #
# The filter walk (verbatim :1302-1330)                                        #
# --------------------------------------------------------------------------- #

def filter_rows(rows, chain, level, used_focused,
                flat_cap=FLAT_VIEW_CAP, progress=None):
    """Select the visible rows in order (verbatim loop :1308-1330, Qt-free).

    Returns (visible, capped): `visible` is a list of (source_index, entry) for
    the rows that should be shown, in source order; `capped` is True when the
    flat-view cap stopped the walk (the caller appends the notice row).

    `progress(i)` is invoked at every source index i with i % 100 == 0 and i > 0
    — the verbatim processEvents cadence (:1310). The controller passes its own
    closure `lambda i: self._pump(gen)`, NEVER QApplication.processEvents itself
    (which would read i as its flags argument). Exceptions from `progress`
    PROPAGATE unchanged, so a `_StaleRender` aborts the walk here.
    """
    flat_view_cap = flat_cap if (not chain and level >= 3) else None
    visible = []
    display_row = 0
    capped = False
    for i, entry in enumerate(rows):
        if i % 100 == 0 and i > 0:
            if progress is not None:
                progress(i)

        entry_indent_level = len(entry.get("indent", "")) // 2

        if len(chain) > 0:
            if entry_indent_level != len(chain):
                continue
            if used_focused:
                entry_parents = chain
            else:
                entry_parents = parent_chain_of(entry, rows, i)
            if entry_parents != chain:
                continue
        else:
            if entry_indent_level >= level:
                continue
            if flat_view_cap is not None and display_row >= flat_view_cap:
                capped = True
                break

        visible.append((i, entry))
        display_row += 1
    return visible, capped


# --------------------------------------------------------------------------- #
# Cycle offset + row text (verbatim :1149-1153, :1341-1357)                    #
# --------------------------------------------------------------------------- #

def shift_years(cycle_offset):
    """Years to shift the displayed dates for a 120-year cycle offset."""
    return cycle_offset * CYCLE_YEARS


def cycle_range_text(offset):
    """Year-range label for a 120-year cycle offset (verbatim _cycle_range_text)."""
    start = offset * CYCLE_YEARS
    end = start + CYCLE_YEARS
    return f"{start}-{end}y"


def age_text(entry_jd, birth_ymd, years_offset=0):
    """'Xy Zm' duration from birth to a period start (verbatim _age_str body).

    An AGE IS A DURATION (td-okit c0-7): both endpoints are read in the FIXED
    astronomical calendar (display_revjul(jd, "astronomical")), so the value is
    invariant to display.calendar_convention and byte-equivalent to
    core/zodiacal_releasing._age_ym. The 120-year cycle offset is applied ONCE as
    years_offset. Returns "" when entry_jd is None or a birth component is falsy.
    """
    try:
        if entry_jd is None:
            return ""
        birth_y, birth_m, birth_d = birth_ymd
        if not all([birth_y, birth_m, birth_d]):
            return ""

        y, m, d, _h = display_revjul(entry_jd, "astronomical")
        y = int(y) + years_offset
        m, d = int(m), int(d)
        birth_y, birth_m, birth_d = int(birth_y), int(birth_m), int(birth_d)

        # Sign-aware month borrow (c0-5): valid only in the direction of elapsed
        # time. Entry on/after birth -> months birth->entry; entry before birth
        # -> months entry->birth, then negate.
        if (y, m, d) >= (birth_y, birth_m, birth_d):
            total_months = (y - birth_y) * 12 + (m - birth_m)
            if d < birth_d:
                total_months -= 1
            return f"{total_months // 12}y {total_months % 12}m"

        total_months = (birth_y - y) * 12 + (birth_m - m)
        if birth_d < d:
            total_months -= 1
        if total_months == 0:
            return "0y 0m"          # zero completed months carries no sign
        month_part = f"-{total_months % 12}m" if total_months % 12 else "0m"
        return f"-{total_months // 12}y {month_part}"
    except Exception:
        return ""


def display_date_at_offset(entry_jd, years_offset, *, date_format, convention):
    """The row's date with its YEAR shifted by years_offset (verbatim
    _display_date_at_offset), month/day untouched, no normalisation (carry-over 1).

    The two display settings are EXPLICIT arguments (sol r1-1): the retained
    manager helper `_display_date_at_offset` resolves date_format / convention per
    invocation through the public readers and passes them; the engine never reads
    settings.
    """
    y, m, d, _h = display_revjul(entry_jd, convention)
    return format_display_ymd(y + years_offset, m, d, date_format)


def row_text(entry, date_str, age, marked):
    """The list-item text for a row (verbatim :1349-1353 formats).

    `date_str` is the already-offset display date; `age` the age column; `marked`
    selects the ▶ prefix for a current period.
    """
    prefix = PREFIX_CURRENT if marked else PREFIX_NORMAL
    lord = entry["lord"]
    date = date_str
    time_str = entry["time"]
    indent = entry["indent"]
    return f"{prefix}{indent}{lord:8}  {date} {time_str}        {age}"


def highlight_rows(visible, cycle_offset):
    """Display indices (positions in `visible`) whose entry is a current period,
    only when cycle_offset == 0 (verbatim :1348-1350)."""
    if cycle_offset != 0:
        return set()
    return {display_idx
            for display_idx, (_src_i, entry) in enumerate(visible)
            if entry.get("is_current", False)}
