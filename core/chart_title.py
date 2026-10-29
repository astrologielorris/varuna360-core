# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The birth date and time the app's chart title shows (review round 17).

One Qt-free function for managers.chart_manager._format_chart_title (the
window/chart title) and the command-line tools that print a "Born:" line
(show_dasha, show_nakshatra), so a tool shows the same birth moment as the
app: the LOCAL civil fields (``local_*`` keys preferred over the plain ones),
the date as MM/DD/YYYY under the display calendar convention, the time as
HH:MM:SS (seconds for D-60 precision).
"""
from __future__ import annotations


def title_civil_fields(chart_data):
    """(year, month, day, hour, minute, second) of the title: each ``local_*``
    key when present, else the plain key (the title's rule)."""
    def pick(name, default):
        local = "local_" + name
        return chart_data[local] if local in chart_data else chart_data.get(name, default)
    return (pick("year", 1900), pick("month", 1), pick("day", 1),
            pick("hour", 0), pick("minute", 0), pick("second", 0))


def title_date_time(chart_data, convention=None):
    """(date_str, time_str) as the chart title shows them.

    ``convention``: display.calendar_convention; None reads the setting (the
    app's own reading). A CLI passes the value it resolved, so reading the
    settings never happens here."""
    from core.time_utils import display_civil_date
    year, month, day, hour, minute, second = title_civil_fields(chart_data)
    disp_year, disp_month, disp_day = display_civil_date(year, month, day, convention)
    date_str = f"{disp_month:02d}/{disp_day:02d}/{disp_year}"
    time_str = f"{hour:02d}:{minute:02d}:{int(second):02d}"
    return date_str, time_str
