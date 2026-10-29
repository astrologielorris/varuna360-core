# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The sky at this moment, at the current location, as a frozen chart.

SPEC-DUAL-001 §4.5 (td-1mgk7): extracted from ``ChartGUI._load_now_chart`` so
the NOW button and the Chart tab's "SKY NOW" chart B build the same chart,
recipe and birth data. Pure: no GUI, no state dispatch, no memory row.
"""

from dataclasses import dataclass

from core.i18n import t


def _weekday(index: int) -> str:
    """The weekday through the i18n API (was ``strftime('%A')``, English only)."""
    return (t("chart.now.weekday.monday", "Monday"), t("chart.now.weekday.tuesday", "Tuesday"),
            t("chart.now.weekday.wednesday", "Wednesday"),
            t("chart.now.weekday.thursday", "Thursday"), t("chart.now.weekday.friday", "Friday"),
            t("chart.now.weekday.saturday", "Saturday"),
            t("chart.now.weekday.sunday", "Sunday"))[index]


@dataclass
class NowChart:
    chart: object          # libaditya Chart, named "Now <weekday>"
    recipe: dict           # make_recipe(...) for the memory row / rebuild
    birth_data: dict       # the birth-data dict the NOW button dispatches
    tz: str                # IANA zone name used for local time
    name: str              # "Now <weekday>"
    city: str = ""
    country: str = ""


def build_now_chart(mode, ayanamsa, hsys, *, now_utc=None):
    """Build the sky now in ``mode`` / ``ayanamsa`` / ``hsys`` (house code).

    Returns a :class:`NowChart`, or ``None`` when the transit calculation fails
    (the caller reports it). One clock reading (``now_utc``, default the real
    UTC clock) drives both the chart and its local-time metadata; tests pin it.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from core.chart_factory import make_recipe
    from core.transit_utils import (calculate_transit_now, get_current_location,
                                    get_current_location_name)

    if now_utc is None:
        now_utc = datetime.now(ZoneInfo('UTC'))
    result = calculate_transit_now(mode=mode, ayanamsa=ayanamsa, hsys=hsys,
                                   target_dt=now_utc)
    if not result:
        return None
    chart, iana_tz_str = result

    lat, lon = get_current_location()
    location_name = get_current_location_name()
    city = location_name.split(",")[0].strip() if "," in location_name else location_name
    country = location_name.split(",")[1].strip() if "," in location_name else ""
    try:
        local_tz = ZoneInfo(iana_tz_str)
    except Exception:
        local_tz = ZoneInfo('UTC')
        iana_tz_str = 'UTC'

    # Convert UTC to true local time for display and metadata
    now_local = now_utc.astimezone(local_tz)
    name = t("chart.now.name", "Now {weekday}", weekday=_weekday(now_local.weekday()))
    chart.context.name = name

    timedec = now_local.hour + now_local.minute / 60.0 + now_local.second / 3600.0
    utc_off = now_local.utcoffset().total_seconds() / 3600.0 if now_local.utcoffset() else 0.0

    # metadata N/A: derived chart ("Now" transit, no birth metadata).
    recipe = make_recipe(
        name=name,
        year=now_local.year, month=now_local.month, day=now_local.day,
        timedec=timedec,
        utcoffset=utc_off,
        timezone=iana_tz_str,
        lat=lat, lon=lon,
        city=city, country=country,
    )
    birth_data = {
        'name': name,
        'year': now_local.year, 'month': now_local.month, 'day': now_local.day,
        'timedec': timedec,
        'hour': now_local.hour, 'minute': now_local.minute, 'second': now_local.second,
        'lat': lat, 'lon': lon,
        'utcoffset': utc_off,
        'iana_timezone': iana_tz_str, 'timezone': iana_tz_str,
        'city': city, 'country': country,
    }
    return NowChart(chart=chart, recipe=recipe, birth_data=birth_data,
                    tz=iana_tz_str, name=name, city=city, country=country)
