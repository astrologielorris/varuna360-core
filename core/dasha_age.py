# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The dasha age column: one function for the Dasha panel, get_dasha and the
command-line tools (review round 17).

Moved here from managers/dasha/engine.py (which re-exports it) so the core
calculation (core/vimshottari_dasha.py) and the CLIs compute the age with the
panel's own function instead of their former fractional-year estimate. Qt-free;
the only dependency is core.time_utils.
"""
from core.time_utils import display_revjul


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
