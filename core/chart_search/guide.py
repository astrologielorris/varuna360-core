# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The Find Chart filter guide, generated (plan 2026-10-18 F3, R11).

What an AI (or a person at a terminal) needs to write ``--where`` filters and
``search_charts`` ``filters[]``: every property with its extractor, its
subjects and groups, its values with their labels, its qualifiers with their
defaults, where it sits in the panel, and a worked example. Everything comes
from the code that parses filters (``taxonomy.catalogue()``, the extractor
registry, ``facets.FACETS``, ``subjects.SUBJECT_GROUPS``), so a new extractor
appears here with no edit, and every example parses back to the filter it
shows (tested).

Three shapes, one source:

- ``topics()``: one short line per property (the AI's table of contents);
- ``property_guide(name, ...)``: one property in full, its values paged so a
  reply stays under ``REPLY_BUDGET`` characters;
- ``markdown(...)``: the whole guide as a page, checked in as
  ``docs/find_chart_filter_guide.md`` with a drift test.

Labels follow the search system's mode and naming (the panel's): the value
list shows the label of that naming first and the other accepted spellings
after it. Parsing is lenient (``taxonomy``), display is not.

No Qt, no store: the guide describes what can be asked, never what is stored.
"""

from __future__ import annotations

import shlex
from collections.abc import Mapping
from typing import Any

from core.chart_search import facets, taxonomy
from core.chart_search.extractors import registry
from core.chart_search.extractors.subjects import SUBJECT_GROUPS
from core.chart_search.system import Mode
from core.chart_search.taxonomy import Codec, Naming, PropertySpec, Value
from core.chart_search.terms import WHERE_FORM

#: A tool reply's ceiling, as the AI setting panel's (SPEC-AIC-001 §4.5).
REPLY_BUDGET = 8000
#: Values per page in ``property_guide``; the largest domain (112 crosses)
#: takes two pages.
PAGE_SIZE = 60
#: Domains longer than this are summarised in ``markdown`` (count, first
#: values, the command that lists them all).
MARKDOWN_VALUES_SHOWN = 64
#: The command a summarised domain points to (text in the guide, never run).
LIST_VALUES_COMMAND = "python AI_tools/cli/find_chart.py --guide {} --json --page N"
#: Namings whose labels are listed as "also accepted" (the localized sign
#: names parse too, but would swamp the list).
_LISTED_NAMINGS = (Naming(use_western_names=False), taxonomy.ENGLISH_WESTERN)

_ALIAS_OF = {
    subject: alias
    for alias, subject in taxonomy.SUBJECT_ALIASES.items()
    if " " in subject and alias.startswith("cusp")
}


def where_subject(subject: str) -> str:
    """The subject as ``--where`` can spell it before its dot (``Cusp 7`` ->
    ``cusp7``)."""
    return _ALIAS_OF.get(subject, subject)


def _groups(spec: PropertySpec) -> tuple[str, ...]:
    return tuple(
        name
        for name, members in SUBJECT_GROUPS.items()
        if any(s in members for s in spec.subjects)
    )


def _panel_paths(name: str) -> tuple[str, ...]:
    """Where the property sits in the panel's first dropdown: ``Places >
    Houses > Whole-sign house``."""
    by_key = {f.key: f for f in facets.FACETS}
    paths: list[str] = []
    for facet in facets.FACETS:
        # The facet whose pick is the property's value; qualifier facets
        # (Varga, Side, ...) follow it in the row.
        if name not in facet.properties or facet.slot is not facets.Slot.VALUE:
            continue
        chain = [facet.label]
        parent = facet
        while parent.menu is not None:
            parent = by_key[parent.menu]
            chain.insert(0, parent.label)
        if parent.section is not None:
            chain.insert(0, parent.section.value)
        path = " > ".join(chain)
        if path not in paths:
            paths.append(path)
    return tuple(paths)


def _panel_relabels(name: str) -> list[dict[str, Any]]:
    """Facets that show the property's values under other names (Strategy
    over the Human Design types): each shown name with the value a filter
    must use. The shown names are panel labels, not filter spellings."""
    spec = taxonomy.catalogue()[name]
    out = []
    for facet in facets.FACETS:
        if name not in facet.properties or facet.relabel is None:
            continue
        out.append(
            {
                "panel": facet.label,
                "shows": [
                    {"shown": facet.relabel(v), "filter_value": v} for v in spec.values
                ],
            }
        )
    return out


def _value_entry(spec: PropertySpec, value: Value, mode: Mode, naming: Naming):
    shown = taxonomy.label(spec, value, mode, naming)
    also: list[str] = []
    for other in _LISTED_NAMINGS:
        text = taxonomy.label(spec, value, mode, other)
        if text != shown and text not in also:
            also.append(text)
    for aliased, names in spec.aliases:
        if aliased == value:
            also += [n for n in names if n != shown and n not in also]
    if str(value) != shown and spec.codec is not Codec.NUMBER:
        also.append(str(value))
    return {"value": value, "label": shown, "also": also}


def _qualifiers(spec: PropertySpec) -> list[dict[str, Any]]:
    return [
        {
            "name": q.name,
            "values": None if q.values is None else list(q.values),
            "default": q.default,
            "any_allowed": q.allows_any,
            "absent_means": q.default if q.default is not None else "any",
        }
        for q in spec.qualifiers
    ]


def _example_subject(spec: PropertySpec) -> str:
    groups = _groups(spec)
    if len(spec.subjects) > 1 and "planets" in groups:
        return spec.subjects[1] if spec.subjects[0] == "Ascendant" else spec.subjects[0]
    return where_subject(spec.subjects[0])


def examples(name: str, mode: Mode, naming: Naming) -> tuple[str, ...]:
    """``--where`` strings that parse back to a valid filter on ``name``:
    the plain form, then (when it has qualifiers) one with its first
    qualifier given, then an open subject."""
    spec = taxonomy.catalogue()[name]
    subject = _example_subject(spec)
    value = taxonomy.label(spec, spec.values[0], mode, naming)
    head = f"{subject}.{name}={shlex.quote(value)}"
    out = [head]
    for q in spec.qualifiers:
        if q.values:
            choice = next(
                (v for v in q.values if v and v != q.default and v != subject),
                q.values[0],
            )
            out.append(f"{head} {q.name}={shlex.quote(choice)}")
            break
    if len(spec.subjects) > 1:
        out.append(f"*.{name}={shlex.quote(value)}")
    return tuple(out)


def topics(mode: Mode = Mode.ADITYA, naming: Naming | None = None) -> list[dict[str, Any]]:
    """One line per property, in extractor build order."""
    naming = naming or taxonomy.search_naming(mode)
    out = []
    for extractor in registry.EXTRACTORS:
        for spec in extractor.properties:
            out.append(
                {
                    "property": spec.name,
                    "extractor": registry.label(extractor.id),
                    "panel": list(_panel_paths(spec.name)),
                    "subjects": len(spec.subjects),
                    "values": len(spec.values),
                    "qualifiers": [q.name for q in spec.qualifiers],
                    "example": examples(spec.name, mode, naming)[0],
                }
            )
    return out


def property_guide(
    name: str,
    mode: Mode = Mode.ADITYA,
    naming: Naming | None = None,
    page: int = 1,
) -> dict[str, Any]:
    """One property in full; values paged by ``PAGE_SIZE``. Raises
    ``BadFilterError`` (listing the properties) for an unknown name, the
    retired ones naming their replacements."""
    naming = naming or taxonomy.search_naming(mode)
    extractor = registry.get(taxonomy.owner(name))
    spec = taxonomy.catalogue()[name]
    pages = max(1, -(-len(spec.values) // PAGE_SIZE))
    page = min(max(1, page), pages)
    chunk = spec.values[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]
    return {
        "property": name,
        "extractor_id": extractor.id,
        "extractor": registry.label(extractor.id),
        "domain": extractor.domain,
        "panel": list(_panel_paths(name)),
        "panel_relabels": _panel_relabels(name),
        "form": WHERE_FORM,
        "subjects": [where_subject(s) for s in spec.subjects],
        "groups": list(_groups(spec)),
        "any_subject": taxonomy.ANY,
        "several_rows_per_subject": spec.multi,
        "qualifiers": _qualifiers(spec),
        "values": [_value_entry(spec, v, mode, naming) for v in chunk],
        "value_count": len(spec.values),
        "page": page,
        "pages": pages,
        "examples": list(examples(name, mode, naming)),
    }


#: The rules every filter follows, stated once (SPEC-FIND-004 §6).
RULES = (
    "Filters combine with AND. There is no OR and no NOT in this version.",
    "One filter names one body: `Moon.nakshatra=Bharani` is Moon in Bharani; "
    "`Moon.sign=*` with `*.nakshatra=Bharani` is a Moon anywhere and "
    "something in Bharani.",
    "A chart not computed for a filter's extractor never matches it; the "
    "result says so and gives the `chart_index compute` command.",
    "Values may be typed as the stored value or any label: Aditya and zodiac "
    "sign names both work in every mode (division 1 is Dhata = Aries).",
    "A qualifier left out means its default when it has one (`varga` is D1, "
    "a channel or center's `side` is both), else any. `*` means any, where "
    "allowed.",
    "Subjects with a space are written without it before the dot: `cusp7` "
    "for Cusp 7; `Asc` and `Lagna` mean the Ascendant.",
    "Free text (the positional term) matches names, places, countries and "
    "notes; a text match is not a verified birthplace.",
)


def _markdown_values(spec: PropertySpec, entries: list[dict[str, Any]]) -> str:
    shown = entries[:MARKDOWN_VALUES_SHOWN]
    parts = []
    for item in shown:
        text = f"`{item['label']}`"
        if item["also"]:
            text += " (" + ", ".join(f"`{a}`" for a in item["also"]) + ")"
        parts.append(text)
    line = ", ".join(parts)
    if len(entries) > len(shown):
        line += (
            f", ... {len(entries)} values in all: "
            f"`{LIST_VALUES_COMMAND.format(spec.name)}` lists them, "
            f"{PAGE_SIZE} a page (N = 1 to {-(-len(entries) // PAGE_SIZE)})"
        )
    return line


def property_markdown(name: str, mode: Mode, naming: Naming) -> list[str]:
    """One property's section of ``markdown``, as lines."""
    spec = taxonomy.catalogue()[name]
    guide = property_guide(name, mode, naming)
    entries = [_value_entry(spec, v, mode, naming) for v in spec.values]
    lines = [
        f"## `{name}`",
        "",
        f"- Extractor: {guide['extractor']} (`{guide['extractor_id']}`)",
    ]
    if guide["panel"]:
        lines.append("- In the panel: " + "; ".join(guide["panel"]))
    for relabel in guide["panel_relabels"]:
        pairs = ", ".join(
            f"{item['shown']} = `{item['filter_value']}`" for item in relabel["shows"]
        )
        lines.append(
            f"- The panel's {relabel['panel']} shows these values by other names "
            f"(filter with the value): {pairs}"
        )
    subjects = ", ".join(f"`{s}`" for s in guide["subjects"])
    if guide["groups"]:
        subjects += "; groups " + ", ".join(f"`{g}`" for g in guide["groups"])
    lines.append(f"- Subjects: {subjects}; `*` any")
    if spec.multi:
        lines.append("- Several values per subject")
    lines.append(f"- Values: {_markdown_values(spec, entries)}")
    for q in guide["qualifiers"]:
        values = (
            "the stored values"
            if q["values"] is None
            else ", ".join(f"`{v}`" if v else "`` (none)" for v in q["values"])
        )
        any_note = "" if q["any_allowed"] else "; `*` refused"
        lines.append(
            f"- Qualifier `{q['name']}`: {values}; left out means "
            f"{q['absent_means']}{any_note}"
        )
    lines.append(
        "- Examples: " + "; ".join(f'`--where "{e}"`' for e in guide["examples"])
    )
    return lines


def markdown(mode: Mode = Mode.ADITYA, naming: Naming | None = None) -> str:
    """The whole guide as one Markdown page."""
    naming = naming or taxonomy.search_naming(mode)
    lines = [
        "# Find Chart filter guide",
        "",
        "<!-- Generated by core/chart_search/guide.py (`python "
        "AI_tools/cli/find_chart.py --guide --markdown`). Do not edit by hand: "
        "test/test_chart_search_guide.py fails when this file and the code "
        "differ. -->",
        "",
        f"Labels below are in the `{mode.value}` mode's own names. Form: "
        f"`--where \"{WHERE_FORM}\"`, repeatable.",
        "",
        "## Rules",
        "",
        *(f"- {rule}" for rule in RULES),
        "",
        "## Subject groups",
        "",
        *(
            f"- `{name}`: " + ", ".join(where_subject(s) for s in members)
            for name, members in SUBJECT_GROUPS.items()
        ),
        "",
    ]
    for extractor in registry.EXTRACTORS:
        for spec in extractor.properties:
            lines += property_markdown(spec.name, mode, naming)
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def guide_for(
    name: str | None, mode: Mode, naming: Naming, page: int = 1
) -> Mapping[str, Any] | list[dict[str, Any]]:
    """``find_chart.py --guide [PROPERTY]``: the topics, or one property."""
    if name is None:
        return topics(mode, naming)
    return property_guide(name, mode, naming, page)
