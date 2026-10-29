# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""``find_ingresses`` and ``body_track``: when a body changes sign, and where
it stands over a span, in the chart's zodiac (SPEC-COACH-001 §4.4).

The chart only supplies the frame (zodiac system, ayanamsa, label set) and the
place whose clock the local times use; the positions are the sky's at each
moment (``core.ingress``). Dates without a UTC offset are read on that place's
clock, the clock of the chart on screen.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from core.capabilities.setting_args import INPUT, setting

BODY_PROP = {"type": "string", "default": "Moon",
             "enum": ["Sun", "Moon", "Mercury", "Venus", "Mars", "Jupiter", "Saturn",
                      "Rahu", "Ketu", "Uranus", "Neptune", "Pluto"],
             "description": "The moving body."}
FROM_PROP = {"type": "string",
              "description": ("Start, ISO date or date-time ('2026-10-27' or "
                              "'2026-10-27T09:41'). Without an offset it is read on the "
                              "chart place's clock. Default: now.")}
TO_PROP = {"type": "string",
            "description": "End, same format. Default: 'from' plus 7 days."}
TZ_PROP = {"type": "string",
           "description": ("IANA time zone for reading and showing times, e.g. "
                           "'Indian/Reunion' for where the user lives. Default: the "
                           "chart place's zone.")}

SIGN_LANGUAGE_ARG = {"sign_language": setting("zodiac.sign_language")}


def _sign_language_prop():
    from core.settings_registry import option_schema
    return option_schema("zodiac.sign_language", "sign_language",
                         description="Language of the Western sign names.")


def place_zone(inp):
    """The IANA zone of the chart's place (open water: the nautical zone)."""
    from core.tz_finder import timezone_at_or_offset
    return timezone_at_or_offset(inp.chart.latitude, inp.chart.longitude)


def _zone(name: str):
    from zoneinfo import ZoneInfo
    try:
        return ZoneInfo(name)
    except Exception:
        return timezone.utc


def _jd(dt_utc: datetime) -> float:
    from libaditya import swe
    h = dt_utc.hour + dt_utc.minute / 60 + dt_utc.second / 3600 + dt_utc.microsecond / 3.6e9
    return swe.julday(dt_utc.year, dt_utc.month, dt_utc.day, h)


def jd_to_utc(jd: float) -> datetime:
    """UT Julian day to an aware UTC datetime, to the second."""
    return (datetime(2000, 1, 1, 12, tzinfo=timezone.utc)
            + timedelta(seconds=round((jd - 2451545.0) * 86400)))


def parse_moment(text: Optional[str], zone_name: str, default_jd: float) -> float:
    """ISO date or date-time to a UT Julian day; naive values on ``zone_name``."""
    from core.capabilities.catalog import OptionError
    if text in (None, ""):
        return default_jd
    try:
        dt = datetime.fromisoformat(str(text).strip().replace("Z", "+00:00"))
    except ValueError:
        raise OptionError(f"not an ISO date or date-time: {text!r}") from None
    if dt.tzinfo is None:
        naive, dt = dt, dt.replace(tzinfo=_zone(zone_name))
        # A wall-clock time the clocks skip (spring forward) does not exist there.
        if dt.astimezone(timezone.utc).astimezone(dt.tzinfo).replace(tzinfo=None) != naive:
            raise OptionError(f"{text!r} does not exist on the {zone_name} clock "
                              "(the clocks skip it); give another time or an offset")
    return _jd(dt.astimezone(timezone.utc))


def moment_fields(jd: float, zone_name: str) -> Dict[str, str]:
    utc = jd_to_utc(jd)
    local = utc.astimezone(_zone(zone_name))
    return {"time_utc": utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "time_local": local.strftime("%Y-%m-%dT%H:%M:%S%z")}


def span(inp, options) -> Tuple[float, float, str]:
    from core.capabilities.catalog import OptionError
    zone = options.get("timezone") or place_zone(inp)
    if options.get("timezone"):
        from zoneinfo import ZoneInfo
        try:
            ZoneInfo(zone)
        except Exception:
            raise OptionError(f"unknown time zone {zone!r}") from None
    start = parse_moment(options.get("from"), zone, inp.view.reference_jd)
    end = parse_moment(options.get("to"), zone, start + 7.0)
    return start, end, zone


def _frame(inp, zone: str) -> Dict[str, Any]:
    return {"mode": inp.frame.mode, "ayanamsa_id": inp.frame.ayanamsa_id,
            "use_western_names": inp.frame.use_western_names, "timezone": zone}


def _engine_call(fn, *args, **kwargs):
    from core.capabilities.catalog import OptionError
    from core.ingress import IngressError
    try:
        return fn(*args, **kwargs)
    except IngressError as exc:
        raise OptionError(str(exc)) from exc


def _run_find_ingresses(inp, options):
    from core.ingress import find_ingresses, sign_label
    start, end, zone = span(inp, options)
    mode, west = inp.frame.mode, inp.frame.use_western_names
    lang = options.get("sign_language") or "en"
    found = _engine_call(find_ingresses, start, end, options.get("body") or "Moon",
                         mode=mode, ayanamsa=inp.frame.ayanamsa_id,
                         lat=inp.chart.latitude, lon=inp.chart.longitude)
    items = [{"body": x["body"],
              "sign_from": sign_label(x["from_index"], mode, west, lang),
              "sign_to": sign_label(x["to_index"], mode, west, lang),
              "from_index": x["from_index"], "to_index": x["to_index"],
              "retrograde": x["retrograde"], "jd": x["jd"],
              **moment_fields(x["jd"], zone)} for x in found]
    return {"body": options.get("body") or "Moon", "start": moment_fields(start, zone),
            "end": moment_fields(end, zone), "frame": _frame(inp, zone),
            "ingresses": items}


def _run_body_track(inp, options):
    from core.ingress import body_track, sign_label
    start, end, zone = span(inp, options)
    mode, west = inp.frame.mode, inp.frame.use_western_names
    lang = options.get("sign_language") or "en"
    step_h = float(options.get("step_hours") or 6.0)
    samples = _engine_call(body_track, start, end, step_h / 24.0,
                           options.get("body") or "Moon", mode=mode,
                           ayanamsa=inp.frame.ayanamsa_id,
                           lat=inp.chart.latitude, lon=inp.chart.longitude)
    for s in samples:
        s["sign"] = sign_label(s["sign_index"], mode, west, lang)
        s.update(moment_fields(s["jd"], zone))
    return {"body": options.get("body") or "Moon", "step_hours": step_h,
            "frame": _frame(inp, zone), "samples": samples}


def _register():
    from core.capabilities.catalog import Capability, register
    register(Capability(
        id="find_ingresses", title="Sign changes",
        description=("When a planet, the Moon or a node changes sign over a span of "
                     "time, in the chart's zodiac, with UTC and local times."),
        guidance=("Use it for 'when does the Moon change sign', ingress dates and transit "
                  "stories. Times are exact to the second; local times are on the chart "
                  "place's clock. Never compute ingress times yourself."),
        run=_run_find_ingresses,
        options_schema={"type": "object", "additionalProperties": False,
                        "properties": {"body": BODY_PROP, "from": FROM_PROP,
                                       "to": TO_PROP, "timezone": TZ_PROP,
                                       "sign_language": _sign_language_prop()}},
        setting_args={"body": INPUT, "from": INPUT, "to": INPUT, "timezone": INPUT,
                      **SIGN_LANGUAGE_ARG},
        output_schema={"type": "object", "required": ["body", "frame", "ingresses"]},
        sources=(("core/ingress.py", "find_ingresses"),)))
    register(Capability(
        id="body_track", title="Body track",
        description=("Where a planet, the Moon or a node stands at regular steps over a "
                     "span of time: sign, degree in the sign, nakshatra and pada."),
        guidance=("Use it to follow a transit step by step (the Moon every few hours, a "
                  "slow planet every few days). At most 2000 samples."),
        run=_run_body_track,
        options_schema={"type": "object", "additionalProperties": False,
                        "properties": {"body": BODY_PROP, "from": FROM_PROP,
                                       "to": TO_PROP, "timezone": TZ_PROP,
                                       "step_hours": {"type": "number", "minimum": 0.25,
                                                      "maximum": 8760, "default": 6,
                                                      "description": "Hours between samples."},
                                       "sign_language": _sign_language_prop()}},
        setting_args={"body": INPUT, "from": INPUT, "to": INPUT, "timezone": INPUT,
                      "step_hours": INPUT,
                      **SIGN_LANGUAGE_ARG},
        output_schema={"type": "object", "required": ["body", "frame", "samples"]},
        sources=(("core/ingress.py", "body_track"),)))


_register()
