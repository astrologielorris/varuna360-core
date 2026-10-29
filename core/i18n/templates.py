# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Message values (a template, a plural or a select object) and their templates
(SPEC-LOC-002 §3.3): named placeholders only, ``{name}`` or ``{name|form}``. Qt-free."""
from __future__ import annotations

import json
import re
import string
import zlib
from types import MappingProxyType
from typing import Any, Dict, List, Set, Tuple

PLURAL_CATEGORIES = frozenset(("zero", "one", "two", "few", "many", "other"))
# Key areas spanning two segments: one catalog file per panel / dialog.
_TWO_LEVEL_AREAS = frozenset(("panel", "dialog"))
_MAPS = (dict, MappingProxyType)       # a message value as read, or frozen in a catalog


class TemplateError(ValueError):
    pass


def source_hash(value: Any) -> str:
    """8-hex hash (CRC-32, UTF-8) of an English source: the text, or the canonical
    JSON of a plural/select object (sorted keys). It detects a CHANGED English
    source (stale translation, approval bound to its source); it is no security
    check. CRC-32 keeps the first catalog load inside the INV-7 budget."""
    if type(value) is str:
        data = value
    else:
        data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "%08x" % zlib.crc32(data.encode("utf-8"))


def area_of(key: str) -> str:
    """The catalog file a key lives in: its first segment, or the first two for
    ``panel.*`` / ``dialog.*`` keys (``panel.eclipse.col.date`` -> ``panel.eclipse``)."""
    parts = key.split(".")
    if parts[0] in _TWO_LEVEL_AREAS and len(parts) > 2:
        return ".".join(parts[:2])
    return parts[0]


_PARSER = string.Formatter()
_NO_FIELDS: frozenset = frozenset()
_FIELDS_MEMO: Dict[str, frozenset] = {}     # template -> names (pure; cleared with the caches)
# Plain text with {name} / {name|form} fields only, matched in C (R2-4): the common shape.
_SIMPLE = re.compile(r"(?:[^{}]|\{[A-Za-z_][A-Za-z0-9_]*(?:\|[A-Za-z0-9_]+)?\})*")
_SIMPLE_NAME = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)")


def clear_memo() -> None:
    _FIELDS_MEMO.clear()


def template_fields(template: str) -> frozenset:
    """The placeholder NAMES of one template (``{planet|gen}`` -> ``planet``);
    TemplateError for anything but named placeholders. Memoized per session."""
    if "{" not in template and "}" not in template:
        return _NO_FIELDS             # the common case: no placeholder at all
    got = _FIELDS_MEMO.get(template)
    if got is None:
        got = _FIELDS_MEMO[template] = _parse_fields(template)
    return got


def _parse_fields(template: str) -> frozenset:
    if _SIMPLE.fullmatch(template):
        return frozenset(_SIMPLE_NAME.findall(template))
    try:
        parsed = list(_PARSER.parse(template))
    except ValueError as exc:
        raise TemplateError(str(exc)) from exc
    return frozenset(_field_name(field, spec) for _lit, field, spec, _conv in parsed
                     if field is not None)


def _field_name(field: str, spec: str) -> str:
    """The name of one placeholder; TemplateError unless it is a named field."""
    if field == "" or field.isdigit():
        raise TemplateError("positional placeholder")
    if "." in field or "[" in field:
        raise TemplateError(f"attribute/index access in {{{field}}}")
    if spec and ("{" in spec or "}" in spec):
        raise TemplateError(f"nested field in {{{field}}}")
    return _checked_name(field)


def _checked_name(field: str) -> str:
    name, _, form = field.partition("|")
    if not name.isidentifier() or (form and not form.replace("_", "").isalnum()):
        raise TemplateError(f"bad placeholder {{{field}}}")
    return name


def is_plural(value: Any) -> bool:
    return isinstance(value, _MAPS) and "select" not in value and bool(value) \
        and set(value) <= PLURAL_CATEGORIES


def is_select(value: Any) -> bool:
    return isinstance(value, _MAPS) and isinstance(value.get("select"), str)


def variants(value: Any) -> List[str]:
    """The template strings of a message value."""
    if isinstance(value, str):
        return [value]
    if is_select(value):
        return [v for k, v in value.items() if k != "select"]
    if isinstance(value, _MAPS):
        return list(value.values())
    raise TemplateError(f"unsupported message value {type(value).__name__}")


def named_variants(value: Any) -> List[Tuple[str, str]]:
    """(variant name, template) pairs of a message value ("text" for a string)."""
    if isinstance(value, str):
        return [("text", value)]
    return [(k, v) for k, v in value.items() if k != "select"]


def value_fields(value: Any) -> Set[str]:
    names: Set[str] = set()
    for v in variants(value):
        if not isinstance(v, str):
            raise TemplateError("variant is not a string")
        names |= template_fields(v)
    if is_select(value):
        names.add(value["select"])
    return names


def unwrap_english(raw: Any) -> Tuple[Any, Dict[str, Any]]:
    """English file value -> (message value, metadata)."""
    if isinstance(raw, dict) and "text" in raw:
        meta = {k: v for k, v in raw.items() if k != "text"}
        return raw["text"], meta
    return raw, {}
