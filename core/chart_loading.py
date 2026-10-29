# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""THE chart-file loading path, shared by the app and every CLI.

Kept out of core.chart_factory (whose size is ratcheted by the South Indian
architecture guard): this module only composes BirthDataManager and
chart_factory.jd_from_birth_data.
"""
from core.chart_factory import jd_from_birth_data


def load_birth_data_and_jd(path, *, canonicalize=False, warnings_to=None):
    """THE chart-file load: ``(birth_data, jd)`` for a .chtk or .toml file.

    The one loading path the app uses (ChartManager.load_chart and
    build_chart_from_file) and every CLI must use, so a CLI shows the chart
    the app shows: BirthDataManager.create_birth_data_from_file (Rule 6 UTC
    method, DST flag resolution, LMT; SPEC-UTC-001) then jd_from_birth_data
    (file JD honoured, else calendar-aware civil UTC to JD: Julian calendar
    before 1582-10-15, SPEC-CAL-001 section 2). The old hand-rolled CLI
    loaders built the JD with bare swe.julday (Gregorian) and landed 4 to 10
    days away from the app on pre-1582 charts.

    ``canonicalize`` is forwarded (True only for the interactive GUI load,
    which may write a canonical .toml back; read-only callers keep False).
    The JD does not depend on it. ``warnings_to`` (a text stream, e.g.
    sys.stderr for a CLI so --json stdout stays parseable) receives the
    loader's timezone warnings (``birth_data['tz_warnings']``, the GUI's
    SPEC-TZ-001 8a text, e.g. the DST flag -1 resolution), one per line.
    Raises ValueError when the file yields no birth data.
    """
    from managers.birth_data_manager import BirthDataManager
    birth_data = BirthDataManager.create_birth_data_from_file(
        str(path), canonicalize=canonicalize)
    if not birth_data:
        raise ValueError(f"cannot read chart {path}")
    if warnings_to is not None:
        for warning in birth_data.get('tz_warnings') or []:
            print(warning, file=warnings_to)
    return birth_data, jd_from_birth_data(birth_data)
