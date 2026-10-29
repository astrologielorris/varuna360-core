# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""search_charts: the catalog's first library-scope capability (design.md §4.8, D1).

Read only; never computes. Registered in ``registry.py`` with
``scope="library"``, so the default ``capabilities()`` / ``tool_schemas()``
(the AI Tools adapter, the task MCP: SPEC-AIC-001 D-13, ``--blind``) never
list it; ``varuna360 --tool search_charts`` runs it without ``--chart``.

**The search-system exception (SPEC-FIND-004, SPEC-SET-003 §4.4 one-liner).**
The six ``search_system.*`` options are ``INPUT`` rows, not settings: distinct
names, so ``external_options``' frame-key refusal does not trip. Absent, each
takes the resolved frame's value (source ``default``); given, source ``query``.
They never write a setting.

**Errors.** ``run`` re-raises ``ChartSearchError`` as ``OptionError`` with
``error_type`` = its code (``bad_option``, ``bad_filter``, ``no_index``,
``store_busy``), the catalog's typed-error pattern. A malformed option the
schema cannot express (a filter item without ``property``, an unknown kind) is
``bad_option`` too.
"""

from __future__ import annotations

import shlex
from collections.abc import Mapping
from typing import Any

from core.capabilities.catalog import OptionError
from core.capabilities.inputs import LibraryInput
from core.capabilities.setting_args import INPUT
from core.chart_search import facts
from core.chart_search.errors import ChartSearchError
from core.chart_search.extractors import registry
from core.chart_search.extractors.subjects import SUBJECT_GROUPS
from core.chart_search.search import (
    Coverage,
    Filter,
    Query,
    ResultEntry,
    Scope,
    SortKey,
    Sources,
    compute_command,
    result_labels,
    search,
)
from core.chart_search.sources import EntryKind
from core.chart_search.store import StoreReader
from core.chart_search.system import (
    CotPlanetOrder,
    Field,
    HdFrame,
    Mode,
    SearchSystem,
)
from core.chart_search.taxonomy import Naming, search_naming
from core.house_systems import HOUSE_SYSTEM_CODES
from core.settings_registry import default as registry_default

CAPABILITY_ID = "search_charts"
SYSTEM_PREFIX = "search_system."
SYSTEM_OPTIONS: Mapping[str, Field] = {SYSTEM_PREFIX + f.value: f for f in Field}
SOURCE_QUERY = "query"
SOURCE_DEFAULT = "default"
#: The setting the result labels' language follows (their names follow the
#: search system's mode, ``search_naming``): display only, never part of the
#: system.
SIGN_LANGUAGE_KEY = "zodiac.sign_language"

#: SPEC-SET-003 §4.4: every option classified; all are per-call inputs.
SETTING_ARGS: Mapping[str, tuple[str, ...]] = {
    "text": INPUT,
    "filters": INPUT,
    "sources": INPUT,
    "folders": INPUT,
    "include_fileless": INPUT,
    "kinds": INPUT,
    "sort": INPUT,
    "reverse": INPUT,
    "limit": INPUT,
    "columns": INPUT,
    "facts": INPUT,
    **{name: INPUT for name in SYSTEM_OPTIONS},
}

_SYSTEM_ENUMS: Mapping[Field, tuple[str, ...]] = {
    Field.MODE: tuple(m.value for m in Mode),
    Field.HOUSE_SYSTEM: tuple(sorted(HOUSE_SYSTEM_CODES)),
    Field.COT_PLANET_ORDER: tuple(o.value for o in CotPlanetOrder),
    Field.HD_FRAME: tuple(h.value for h in HdFrame),
}
_SYSTEM_DESCRIPTIONS: Mapping[Field, str] = {
    Field.MODE: "Zodiac system the stored values are searched in.",
    Field.AYANAMSA_ID: (
        "Ayanamsa id (sidereal; 97 refused). It also names the nakshatra"
        " division: 98 Equatorial Dhruva GC mid-Mula, 102 Ecliptic GC mid-Mula,"
        " 100 Equatorial Vedanga Jyotisha, 99 Ecliptic Vedanga Jyotisha."
    ),
    Field.HOUSE_SYSTEM: "House system the house values are searched in.",
    Field.COT_PLANET_ORDER: "Cards of Truth planet order.",
    Field.HD_FRAME: (
        "Human Design gate-1 frame, independent of mode: standard (13°15' Scorpio,"
        " Traditional), aditya (13°15' Vishnu), sidereal (moved by ayanamsa_id)."
    ),
}
_FILTER_KEYS = frozenset({"subject", "property", "value", "qualifiers"})
_GROUP_NAMES = ", ".join(SUBJECT_GROUPS)


def _system_property(field: Field) -> dict[str, Any]:
    description = (
        _SYSTEM_DESCRIPTIONS[field] + " Default: the app's resolved chart frame."
    )
    if field is Field.AYANAMSA_ID:
        # No enum, as the frame entry: the valid ids are named in the error.
        return {"type": "integer", "description": description}
    return {
        "type": "string",
        "enum": list(_SYSTEM_ENUMS[field]),
        "description": description,
    }


def options_schema() -> dict[str, Any]:
    """JSON Schema of the options above. ``filters[]`` items are
    ``{subject, property, value, qualifiers}`` (subject and value optional:
    absent or ``"*"`` is any; subject may be a group); enums from ``search.Sources``,
    ``search.SortKey``, ``sources.EntryKind`` and the system field enums;
    ``search_system.ayanamsa_id`` has no enum (``AYANAMSA_OPTIONS`` named in
    the error, as the frame entry does)."""
    return {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "default": "",
                "description": "Free text over name, place, country and notes.",
            },
            "filters": {
                "type": "array",
                "default": [],
                "description": (
                    "AND of filters: {subject, property, value, qualifiers}, "
                    "one property each; value and qualifier values may be "
                    "stored values or labels "
                    '(e.g. {"subject": "Sun", "property": "sign", "value": '
                    '"Leo", "qualifiers": {"varga": "D1"}}). Subject and value '
                    'are optional: absent or "*" is any '
                    '({"property": "nakshatra", "value": "Bharani"}: something '
                    f"in Bharani); subject may also be a group ({_GROUP_NAMES}). "
                    'An absent qualifier is any, except varga (absent: "D1", '
                    'the rashi; "*": any varga) and the side of a channel or '
                    'center (absent: "both", the whole chart; "*" rejected).'
                ),
                "items": {
                    "type": "object",
                    "required": ["property"],
                    "properties": {
                        "subject": {"type": "string"},
                        "property": {"type": "string"},
                        "value": {"type": ["integer", "string"]},
                        "qualifiers": {
                            "type": "object",
                            "additionalProperties": {"type": "string"},
                        },
                    },
                    "additionalProperties": False,
                },
            },
            "sources": {
                "type": "string",
                "enum": [s.value for s in Sources],
                "default": Sources.ALL.value,
                "description": "Every entry, the loaded charts, or the folders given.",
            },
            "folders": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
                "description": "Folder paths searched (with sources = folders).",
            },
            "include_fileless": {
                "type": "boolean",
                "default": True,
                "description": "Include loaded charts that have no file.",
            },
            "kinds": {
                "type": "array",
                "items": {"type": "string", "enum": [k.value for k in EntryKind]},
                "default": [EntryKind.BIRTH.value],
                "description": "Entry kinds searched.",
            },
            "sort": {
                "type": "string",
                "enum": [k.value for k in SortKey],
                "default": SortKey.NAME.value,
            },
            "reverse": {"type": "boolean", "default": False},
            "limit": {
                "type": "integer",
                "minimum": 0,
                "description": "Results returned (total counts all). Default: all.",
            },
            "columns": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [facts.PLACEMENTS_KEY, *facts.GROUPS_BY_KEY],
                },
                "description": (
                    "Extra stored facts per result, as the Find Chart panel's "
                    "columns (SPEC-FIND-005 §3.5): 'placements' adds the D1 sign "
                    "of every body; a group adds its facts for the placements "
                    "shown (Asc, Sun, Moon, or every body with 'placements')."
                ),
            },
            "facts": {
                "type": "boolean",
                "default": False,
                "description": (
                    "Add each result's stored facts as the panel's inspector "
                    "sections (use with limit)."
                ),
            },
            **{name: _system_property(f) for name, f in SYSTEM_OPTIONS.items()},
        },
        "additionalProperties": False,
    }


def output_schema() -> dict[str, Any]:
    """``results[]`` (entry_id, name, filepath ("" when file-less), kind, place,
    country, birth_local, loaded_in[], ascendant/sun/moon labels), ``total``,
    ``system`` (each field with value and source), ``coverage[]`` (each with
    ``compute_command`` when incomplete)."""
    string = {"type": "string"}
    return {
        "type": "object",
        "required": ["results", "total", "system", "coverage"],
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "entry_id",
                        "name",
                        "filepath",
                        "kind",
                        "place",
                        "country",
                        "birth_local",
                        "loaded_in",
                        "unsaved_changes",
                        "ascendant",
                        "sun",
                        "moon",
                    ],
                    "properties": {
                        "entry_id": string,
                        "name": string,
                        "filepath": string,
                        "kind": {
                            "type": "string",
                            "enum": [k.value for k in EntryKind],
                        },
                        "place": string,
                        "country": string,
                        "birth_local": string,
                        "loaded_in": {"type": "array", "items": string},
                        "unsaved_changes": {"type": "boolean"},
                        "ascendant": string,
                        "sun": string,
                        "moon": string,
                        "columns": {
                            "type": "array",
                            "description": (
                                "Only with the columns option: the extra "
                                "columns in panel order; text is \"\" when "
                                "nothing is stored."
                            ),
                            "items": {
                                "type": "object",
                                "required": ["key", "header", "text"],
                                "properties": {
                                    "key": string,
                                    "header": string,
                                    "text": string,
                                },
                            },
                        },
                        "facts": {
                            "type": "object",
                            "description": "Only with the facts option: the inspector.",
                            "required": ["cards", "sections"],
                            "properties": {
                                "cards": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {"body": string, "sign": string},
                                    },
                                },
                                "sections": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "required": [
                                            "key",
                                            "title",
                                            "state",
                                            "owners",
                                            "columns",
                                            "rows",
                                        ],
                                        "properties": {
                                            "key": string,
                                            "title": string,
                                            "state": {
                                                "enum": [
                                                    "computed",
                                                    "missing",
                                                    "failed",
                                                    "stale",
                                                    "partial",
                                                ]
                                            },
                                            "owners": {
                                                "type": "array",
                                                "items": {
                                                    "type": "object",
                                                    "properties": {
                                                        "extractor_id": string,
                                                        "state": string,
                                                        "error": string,
                                                    },
                                                },
                                            },
                                            "columns": {
                                                "type": "array",
                                                "items": string,
                                            },
                                            "rows": {
                                                "type": "array",
                                                "items": {
                                                    "type": "object",
                                                    "properties": {
                                                        "cells": {
                                                            "type": "array",
                                                            "items": string,
                                                        },
                                                        "retrograde": {"type": "boolean"},
                                                        "details": {
                                                            "type": "array",
                                                            "items": string,
                                                        },
                                                    },
                                                },
                                            },
                                        },
                                    },
                                },
                            },
                        },
                    },
                },
            },
            "total": {"type": "integer"},
            "system": {
                "type": "object",
                "required": [f.value for f in Field],
                "additionalProperties": {
                    "type": "object",
                    "required": ["value", "source"],
                    "properties": {"source": {"enum": [SOURCE_QUERY, SOURCE_DEFAULT]}},
                },
            },
            "coverage": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "extractor_id",
                        "label",
                        "domain",
                        "in_scope",
                        "computed",
                        "failed",
                        "computed_with",
                        "complete",
                        "compute_command",
                        "computed_elsewhere",
                    ],
                    "properties": {
                        "label": string,
                        "computed_with": {"type": "array", "items": string},
                        "complete": {"type": "boolean"},
                        "compute_command": {"type": ["string", "null"]},
                        "computed_elsewhere": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["fields", "computed", "search_flags"],
                                "properties": {
                                    "fields": {"type": "object"},
                                    "computed": {"type": "integer"},
                                    "search_flags": {"type": ["string", "null"]},
                                },
                            },
                        },
                    },
                },
            },
        },
    }


def _bad_option(message: str) -> OptionError:
    return OptionError(message, "bad_option")


def _filter(index: int, raw: object) -> Filter:
    """One ``filters[]`` item as a ``Filter``; its shape only (``search.resolve``
    checks the names and values: ``bad_filter``)."""
    where = f"filters[{index}]"
    if not isinstance(raw, Mapping):
        raise _bad_option(f"{where} must be an object, got {raw!r}")
    unknown = sorted(set(raw) - _FILTER_KEYS)
    if unknown:
        raise _bad_option(f"{where} has unknown key(s) {unknown}")
    if "property" not in raw:
        raise _bad_option(f"{where} needs 'property'")
    subject, prop, value = raw.get("subject"), raw["property"], raw.get("value")
    if not isinstance(subject, (str, type(None))) or not isinstance(prop, str):
        raise _bad_option(f"{where} subject and property are strings")
    if value is not None and (
        isinstance(value, bool) or not isinstance(value, (int, str))
    ):
        raise _bad_option(f"{where} value is an integer or a string, got {value!r}")
    qualifiers = raw.get("qualifiers") or {}
    if not isinstance(qualifiers, Mapping) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in qualifiers.items()
    ):
        raise _bad_option(f"{where} qualifiers map names to strings")
    return Filter(subject, prop, value, tuple(qualifiers.items()))


def _kinds(raw: object) -> frozenset[EntryKind]:
    valid = tuple(k.value for k in EntryKind)
    if not isinstance(raw, list) or not all(k in valid for k in raw):
        raise _bad_option(
            f"option 'kinds' items must be among {list(valid)}, got {raw!r}"
        )
    return frozenset(EntryKind(k) for k in raw)


def _scope(values: Mapping[str, Any]) -> Scope:
    sources = Sources(values.get("sources") or Sources.ALL.value)
    folders = values.get("folders") or []
    if not isinstance(folders, list) or not all(isinstance(f, str) for f in folders):
        raise _bad_option(f"option 'folders' is a list of paths, got {folders!r}")
    if sources is Sources.FOLDERS and not folders:
        raise _bad_option("sources = folders needs at least one folder")
    if folders and sources is not Sources.FOLDERS:
        raise _bad_option("option 'folders' applies with sources = folders only")
    include_fileless = values.get("include_fileless")
    kinds = values.get("kinds")
    return Scope(
        sources=sources,
        folders=tuple(folders),
        include_fileless=True if include_fileless is None else include_fileless,
        kinds=_kinds([EntryKind.BIRTH.value] if kinds is None else kinds),
    )


def query_from(
    values: Mapping[str, Any], default: SearchSystem
) -> tuple[Query, dict[Field, str]]:
    """The resolved options as a ``Query``, plus each system field's source.
    Raises ``BadSystemError`` / ``OptionError`` (``bad_option``)."""
    given = {
        field: values[name]
        for name, field in SYSTEM_OPTIONS.items()
        if values.get(name) is not None
    }
    system = default.with_values(given)
    sources = {
        field: SOURCE_QUERY if field in given else SOURCE_DEFAULT for field in Field
    }
    filters = values.get("filters") or []
    if not isinstance(filters, list):
        raise _bad_option(f"option 'filters' is a list, got {filters!r}")
    query = Query(
        system=system,
        text=values.get("text") or "",
        scope=_scope(values),
        filters=tuple(_filter(i, f) for i, f in enumerate(filters)),
        sort=SortKey(values.get("sort") or SortKey.NAME.value),
        reverse=bool(values.get("reverse")),
        limit=values.get("limit"),
    )
    return query, sources


def _naming(inp: LibraryInput, system: SearchSystem) -> Naming:
    language = inp.settings.get(SIGN_LANGUAGE_KEY, registry_default(SIGN_LANGUAGE_KEY))
    return search_naming(
        system.mode, sign_language=language if isinstance(language, str) else "en"
    )


def _result_dict(
    entry: ResultEntry, system: SearchSystem, naming: Naming
) -> dict[str, Any]:
    return {
        "entry_id": entry.entry_id,
        "name": entry.name,
        "filepath": entry.path or "",
        "kind": entry.kind.value,
        "place": entry.place,
        "country": entry.country,
        "birth_local": entry.birth_local,
        "loaded_in": list(entry.loaded_in),
        "unsaved_changes": entry.unsaved_changes,
        **result_labels(entry, system, naming),
    }


def _add_facts(store, found, naming, values, results) -> None:
    """The ``columns`` and ``facts`` options (SPEC-FIND-005 §3.10): stored
    facts only, never computing. Results without them keep no such key."""
    wanted = list(dict.fromkeys(values.get("columns") or ()))
    groups = [g for g in wanted if g != facts.PLACEMENTS_KEY]
    every = facts.PLACEMENTS_KEY in wanted
    ids = frozenset(e.moment_id for e in found.entries if e.moment_id is not None)
    if wanted:
        cols = facts.columns(groups, every)
        cells = facts.column_values(store, found.system, naming, ids, groups, every)
        for entry, result in zip(found.entries, results, strict=True):
            row = cells.get(entry.moment_id, {})
            result["columns"] = [
                {"key": c.key, "header": c.header, "text": row.get(c.key, "")}
                for c in cols
            ]
    if values.get("facts"):
        cache: dict = {}
        for entry, result in zip(found.entries, results, strict=True):
            if entry.moment_id is None:
                result["facts"] = {"cards": [], "sections": []}
                continue
            if entry.moment_id not in cache:
                cache[entry.moment_id] = facts_dict(
                    facts.chart_facts(store, found.system, naming, entry.moment_id)
                )
            result["facts"] = cache[entry.moment_id]


def facts_dict(chart: facts.ChartFacts) -> dict[str, Any]:
    """``results[].facts``: the inspector as JSON."""
    return {
        "cards": [{"body": body, "sign": sign} for body, sign in chart.cards],
        "sections": [
            {
                "key": s.key,
                "title": s.title,
                "state": s.state,
                "owners": [
                    {"extractor_id": o.extractor_id, "state": o.state, "error": o.error}
                    for o in s.owners
                ],
                "columns": list(s.columns),
                "rows": [
                    {
                        "cells": list(r.cells),
                        "retrograde": r.retrograde,
                        "details": list(r.details),
                    }
                    for r in s.rows
                ],
            }
            for s in chart.sections
        ],
    }


def coverage_dict(coverage: Coverage, system: SearchSystem) -> dict[str, Any]:
    """One ``coverage[]`` item (also ``chart_index status --json``)."""
    return {
        "extractor_id": coverage.extractor_id,
        "label": registry.label(coverage.extractor_id),
        "domain": coverage.domain,
        "in_scope": coverage.in_scope,
        "computed": coverage.computed,
        "failed": coverage.failed,
        "computed_with": list(coverage.computed_with),
        "complete": coverage.complete,
        "compute_command": None
        if coverage.complete
        else compute_command(coverage, system),
        "computed_elsewhere": [
            {
                "fields": dict(item.fields),
                "computed": item.computed,
                "search_flags": shlex.join(item.search_flags())
                if item.search_flags()
                else None,
            }
            for item in coverage.elsewhere
        ],
    }


def _check_columns(values: dict[str, Any]) -> None:
    valid = (facts.PLACEMENTS_KEY, *facts.GROUPS_BY_KEY)
    unknown = [k for k in values.get("columns") or () if k not in valid]
    if unknown:
        raise OptionError(
            f"unknown column group(s) {', '.join(map(str, unknown))}; "
            f"valid: {', '.join(valid)}",
            "bad_option",
        )


def run(inp: LibraryInput, values: dict[str, Any]) -> dict[str, Any]:
    _check_columns(values)
    default = SearchSystem.from_frame(inp.frame, inp.settings)
    try:
        query, sources = query_from(values, default)
        store = StoreReader.open()
    except ChartSearchError as exc:
        raise OptionError(str(exc), exc.error_type) from exc
    with store:
        try:
            found = search(store, query)
        except ChartSearchError as exc:
            raise OptionError(str(exc), exc.error_type) from exc
        naming = _naming(inp, found.system)
        results = [_result_dict(e, found.system, naming) for e in found.entries]
        _add_facts(store, found, naming, values, results)
    return {
        "results": results,
        "total": found.total,
        "system": found.system.describe(sources),
        "coverage": [coverage_dict(c, found.system) for c in found.coverage],
    }


def _register() -> None:
    from core.capabilities.catalog import SCOPE_LIBRARY, Capability, register

    register(
        Capability(
            id=CAPABILITY_ID,
            title="Find Chart search",
            description=(
                "Search the chart library (files in the chart folders and "
                "loaded charts) by free text and AND-ed filters on stored "
                "chart facts (signs, houses, nakshatras, dignity, avasthas, "
                "retinue, Human Design, Cards of Truth), in a search system "
                "that defaults to the app's. Read only: never computes; "
                "coverage[] says what is not computed yet and the command "
                "that computes it."
            ),
            run=run,
            options_schema=options_schema(),
            output_schema=output_schema(),
            sources=(
                ("core/chart_search/search.py", "search"),
                ("core/capabilities/chart_search.py", "run"),
            ),
            setting_args=dict(SETTING_ARGS),
            scope=SCOPE_LIBRARY,
        )
    )


_register()
