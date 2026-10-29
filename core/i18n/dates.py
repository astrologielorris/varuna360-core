# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Dates with month and weekday names in the UI language (SPEC-LOC-002 §4.6).

``format_date(dt, pattern_key, lang=None)`` replaces every ``strftime`` that
prints a month or day name (``%b %B %a %A``). Month and weekday names come from
``term("month", 1..12)`` / ``term("weekday", 0..6)`` (Monday = 0, as
``datetime.weekday()``); the pattern itself is a catalog entry
``format.date.<pattern_key>`` so each language orders the parts its own way.

Placeholders: {d} day, {dd} zero-padded day, {m} month number, {mm} zero-padded,
{y} year, {month} / {month|abbr} month name, {weekday} / {weekday|abbr},
{hour} {minute} {second} zero-padded time. English output equals the strftime it replaces:

  long             "%d %B %Y"         -> "05 March 2026"
  day_month_year   f"{d} {month} {y}" -> "5 March 2026"
  month_year_abbr  "%b %Y"            -> "Mar 2026"
  month_day_abbr   "%b %d"            -> "Mar 05"
  month_day_time_abbr "%b %d %H:%M"   -> "Mar 05 14:07"
  weekday          "%A"               -> "Thursday"
Numeric-only strftime calls stay as they are.
"""
from __future__ import annotations

from typing import Optional

from core.i18n.catalog import TermRef, t


def _pattern(key: str, lang: Optional[str], params: dict) -> str:
    # One inline English default per pattern (INV-2: the extractor reads them here).
    if key == "long":
        return t("format.date.long", "{dd} {month} {y}", lang=lang, **params)
    if key == "day_month_year":
        return t("format.date.day_month_year", "{d} {month} {y}", lang=lang, **params)
    if key == "month_year_abbr":
        return t("format.date.month_year_abbr", "{month|abbr} {y}", lang=lang, **params)
    if key == "month_day_abbr":
        return t("format.date.month_day_abbr", "{month|abbr} {dd}", lang=lang, **params)
    if key == "month_day_time_abbr":
        return t("format.date.month_day_time_abbr", "{month|abbr} {dd} {hour}:{minute}",
                 lang=lang, **params)
    if key == "weekday":
        return t("format.date.weekday", "{weekday}", lang=lang, **params)
    raise KeyError(f"unknown date pattern {key!r}")


# Every pattern may use any of these (a language orders and pads its own way); the
# extractor records them as the keys' "params" metadata, so a translation's
# placeholders must be a SUBSET of this set rather than equal English's.
PARAM_NAMES = ("d", "dd", "m", "mm", "y", "month", "weekday", "hour", "minute", "second")

PATTERN_KEYS = ("long", "day_month_year", "month_year_abbr", "month_day_abbr",
                "month_day_time_abbr", "weekday")


def format_date(dt, pattern_key: str, lang: Optional[str] = None) -> str:
    """``dt`` (date or datetime) formatted with ``format.date.<pattern_key>``."""
    hour = getattr(dt, "hour", 0)
    minute = getattr(dt, "minute", 0)
    second = getattr(dt, "second", 0)
    params = {
        "d": dt.day, "dd": f"{dt.day:02d}", "m": dt.month, "mm": f"{dt.month:02d}",
        "y": dt.year, "month": TermRef("month", dt.month),
        "weekday": TermRef("weekday", dt.weekday()),
        "hour": f"{hour:02d}", "minute": f"{minute:02d}", "second": f"{second:02d}",
    }
    return _pattern(pattern_key, lang, params)
