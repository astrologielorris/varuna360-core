# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""What users type into Find Chart, as ``search.Filter`` (design.md §4.8, D8).

Two syntaxes, one module, shared by ``AI_tools/cli/find_chart.py`` and the
panel's search box (§4.9):

- **The legacy term** (``parse_term``): free text plus ``body:label`` tokens,
  exactly the tokens ``ChartIndexCache.search`` read (``\\b(\\w+):(\\w+)\\b``).
  ``sun:Dhata`` / ``sun:Aries`` / ``sun:Bélier`` becomes a ``sign`` filter at
  varga D1, matched in the search system's mode; ``sun_being:Vasuki`` becomes a
  ``hora_being`` filter when the label is a hora being, else a
  ``trimsamsa_being`` one (the legacy cache matched either; the two domains
  are disjoint, so the routing loses nothing). A token whose key is neither is
  dropped from the text, as before, and returned in ``ignored``.
- **``--where``** (``parse_where``): ``Subject.property=value [q=v ...]``.
  The subject may be a group (``planets.cusp_house=7``) and subject or value
  ``*`` (any): ``*.nakshatra=Bharani``, ``Sun.gate=* side=design``.

Syntax only: values and labels stay as typed; ``search.resolve`` (through
``taxonomy``) checks and translates them, so a bad label is ``bad_filter``
listing the valid ones, on every route.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

from core.chart_search import taxonomy
from core.chart_search.errors import BadFilterError
from core.chart_search.extractors.retinue import SUBJECTS as RETINUE_SUBJECTS
from core.chart_search.extractors.subjects import BODIES
from core.chart_search.search import Filter

#: The legacy cache's token pattern (``ChartIndexCache.search``), kept verbatim.
TOKEN = re.compile(r"\b(\w+):(\w+)\b")
#: What the legacy cache stripped from the ends of the remaining text.
TEXT_PUNCTUATION = ".,;:!?()[]{}\"'-/"
BEING_SUFFIX = "_being"
LEGACY_VARGA = "D1"
WHERE_FORM = (
    "Subject.property=value [qualifier=value ...] "
    "(Subject may be a group or *, value may be *)"
)

_BODY_KEYS = {b.casefold(): b for b in BODIES}
_BEING_KEYS = {b.casefold() + BEING_SUFFIX: b for b in RETINUE_SUBJECTS}


@dataclass(frozen=True)
class ParsedTerm:
    text: str  # free text, for the FTS
    filters: tuple[Filter, ...]
    ignored: tuple[str, ...] = ()  # ``key:value`` tokens with an unknown key


def parse_term(term: str) -> ParsedTerm:
    """The legacy search term as free text and filters. Never raises: the
    filters' labels are checked when the search resolves them."""
    filters: list[Filter] = []
    ignored: list[str] = []
    for match in TOKEN.finditer(term):
        key, label = match.group(1).casefold(), match.group(2)
        if key in _BODY_KEYS:
            filters.append(
                Filter(_BODY_KEYS[key], "sign", label, (("varga", LEGACY_VARGA),))
            )
        elif key in _BEING_KEYS:
            filters.append(Filter(_BEING_KEYS[key], _being_property(label), label))
        else:
            ignored.append(match.group(0))
    text = " ".join(TOKEN.sub("", term).split()).strip(TEXT_PUNCTUATION).strip()
    return ParsedTerm(text, tuple(filters), tuple(ignored))


def _being_property(label: str) -> str:
    try:
        taxonomy.parse_value(taxonomy.catalogue()["hora_being"], label)
    except BadFilterError:
        return "trimsamsa_being"
    return "hora_being"


def parse_where(spec: str) -> Filter:
    """``"Mars.lajjitaadi=shamed by=Saturn via=aspect"`` as a ``Filter``.
    Quotes group a value with spaces. Raises ``BadFilterError`` for text not
    in that form (names and values are checked by ``search.resolve``)."""
    try:
        tokens = shlex.split(spec)
    except ValueError as exc:
        raise _malformed(spec, str(exc)) from exc
    if not tokens:
        raise _malformed(spec, "empty")
    head, *rest = tokens
    target, sep, value = head.partition("=")
    subject, dot, prop = target.partition(".")
    if not (sep and dot and subject and prop and value):
        raise _malformed(spec, f"{head!r} is not Subject.property=value")
    qualifiers: list[tuple[str, str]] = []
    for token in rest:
        name, sep, qualifier = token.partition("=")
        if not (sep and name):
            raise _malformed(spec, f"{token!r} is not qualifier=value")
        if any(name == given for given, _value in qualifiers):
            raise _malformed(spec, f"qualifier {name!r} given twice")
        qualifiers.append((name, qualifier))
    return Filter(subject, prop, value, tuple(qualifiers))


def _malformed(spec: str, why: str) -> BadFilterError:
    return BadFilterError(f"--where {spec!r}: {why}; the form is {WHERE_FORM}", ())
