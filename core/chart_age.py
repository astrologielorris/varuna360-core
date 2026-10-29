# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Current age of a chart's native, as the title pill shows it ("  35y 7m").

SPEC-DUAL-001 §4.1 (td-1mgk7): extracted from ``ChartGUI._update_chart_title``
so the pill's well A and well B compute the age the same way. Pure.
"""


def age_suffix(birth_data, today=None):
    """Return ``"  <years>y <months>m"`` for ``birth_data`` (local date keys
    ``local_year`` / ``local_month`` / ``local_day`` preferred over ``year`` /
    ``month`` / ``day``), or ``""`` when the date is missing, in the future or
    under one month. ``today`` (a date or datetime) pins the clock for tests.
    """
    try:
        if not birth_data:
            return ""
        b_y = birth_data['local_year'] if 'local_year' in birth_data else birth_data.get('year')
        b_m = birth_data['local_month'] if 'local_month' in birth_data else birth_data.get('month')
        b_d = birth_data['local_day'] if 'local_day' in birth_data else birth_data.get('day')
        if not (b_y and b_m and b_d):
            return ""
        if today is None:
            from datetime import datetime
            today = datetime.now()
        total_months = (today.year - b_y) * 12 + (today.month - b_m)
        if today.day < b_d:
            total_months -= 1
        years = total_months // 12
        months = total_months % 12
        if years > 0 or months > 0:
            return f"  {years}y {months}m"
    except Exception:
        pass
    return ""
