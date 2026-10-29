# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Translation validation (INV-5: an invalid entry is dropped for the session and
English used) and the T-1 catalog report (SPEC-LOC-002). Qt-free."""
from __future__ import annotations

from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from core.i18n.source import EnglishSource
from core.i18n.templates import (
    TemplateError, is_plural, is_select, named_variants, source_hash, template_fields,
    variants)


class CatalogReport(NamedTuple):
    present: Tuple[str, ...]      # keys present in the language's own files
    approved: Tuple[str, ...]     # ok == src == current English hash
    current: Tuple[str, ...]      # src == current English hash
    stale: Tuple[str, ...]        # src != current English hash
    invalid: Tuple[Tuple[str, str], ...]   # (key, reason): English used instead
    unused: Tuple[str, ...]       # no English source for the key
    hidden: Tuple[str, ...]       # valid but not shown (public build, not approved+current)
    terms_present: int
    terms_approved: int
    terms_stale: Tuple[str, ...]  # "kind:ident"
    problems: Tuple[str, ...]     # file-level problems


def term_state(entry: dict, en_entry: Optional[dict]) -> str:
    """approved | current | stale for a translated term entry."""
    if en_entry is None:
        return "stale"
    now = source_hash(en_entry["name"])
    if entry.get("src") != now:
        return "stale"
    return "approved" if entry.get("ok") == now else "current"


def compute_report(raw: Dict[str, Any], own_terms: Dict[str, Dict[str, dict]],
                   en: EnglishSource, invalid: List[Tuple[str, str]],
                   hidden: List[str], problems: List[str]) -> CatalogReport:
    approved, current, stale, unused = _message_states(raw, en, invalid)
    t_present, t_approved, t_stale = _term_counts(own_terms, en)
    return CatalogReport(tuple(raw), tuple(approved), tuple(current), tuple(stale),
                         tuple(invalid), tuple(unused), tuple(hidden), t_present,
                         t_approved, tuple(t_stale), tuple(problems))


def _message_states(raw: Dict[str, Any], en: EnglishSource,
                    invalid: List[Tuple[str, str]]) -> Tuple[list, list, list, list]:
    """(approved, current, stale, unused) keys of a language's own files."""
    approved, current, stale, unused = [], [], [], []
    bad = {k for k, _ in invalid}
    for key, entry in raw.items():
        if key not in en.values:
            unused.append(key)
        elif key in bad or type(entry) is not dict:
            continue
        elif entry.get("src") != en.hashes[key]:
            stale.append(key)
        else:
            current.append(key)
            if entry.get("ok") == en.hashes[key]:
                approved.append(key)
    return approved, current, stale, unused


def _term_counts(own_terms: Dict[str, Dict[str, dict]], en: EnglishSource
                 ) -> Tuple[int, int, List[str]]:
    present, approved, stale = 0, 0, []
    for kind, table in own_terms.items():
        en_table = en.terms.get(kind, {})
        for ident, entry in table.items():
            present += 1
            state = term_state(entry, en_table.get(ident))
            if state == "approved":
                approved += 1
            elif state == "stale":
                stale.append(f"{kind}:{ident}")
    return present, approved, stale


def _plain_pair(en_value: Any, text: Any) -> bool:
    return type(en_value) is str and type(text) is str and bool(text) \
        and "{" not in en_value and "}" not in en_value and "{" not in text and "}" not in text


def validate_entry(lang, key: str, text: Any, en: EnglishSource) -> Optional[str]:
    """None when ``text`` is a valid translation of ``key``, else the reason."""
    en_value = en.values[key]
    if _plain_pair(en_value, text):
        return None                   # fast path: plain text on both sides
    if type(en_value) is str and type(text) is str and text and key not in en.meta:
        return _template_reason(en_value, text)   # R2-4: one template each, no declared params
    try:
        en_fields = en.fields(key)
    except TemplateError as exc:
        return f"English source invalid: {exc}"
    return _shape_reason(lang, key, text, en_value, en) or _variants_reason(key, text, en, en_fields)


def _template_reason(en_value: str, text: str) -> Optional[str]:
    """Without declared params the call offers and requires exactly the English fields."""
    try:
        need = template_fields(en_value)
    except TemplateError as exc:
        return f"English source invalid: {exc}"
    return _variant_reason("text", text, need, need, need)


def _shape_reason(lang, key: str, text: Any, en_value: Any, en: EnglishSource) -> Optional[str]:
    """Why ``text`` does not have the shape of the English value, or None."""
    if isinstance(en_value, str):
        return _string_shape(text)
    if is_select(en_value):
        return _select_shape(text, en_value)
    if is_plural(en_value):
        return _plural_shape(lang, key, text, en)
    return "English source has an unsupported shape"


def _string_shape(text: Any) -> Optional[str]:
    if not isinstance(text, str):
        return "English is a plain text, translation is not"
    return None if text else "empty translation"


def _select_shape(text: Any, en_value: Any) -> Optional[str]:
    if not is_select(text) or text["select"] != en_value["select"]:
        return "select entry must select on the same param"
    return None if "other" in text else "select entry without 'other'"


def _plural_shape(lang, key: str, text: Any, en: EnglishSource) -> Optional[str]:
    if not is_plural(text):
        return "plural entry expected"
    rules = lang.ordinal if en.selector(key) == "ordinal" else lang.cardinal
    need = set(rules.categories)
    return None if set(text) == need else f"plural categories {sorted(text)} != {sorted(need)}"


def _variants_reason(key: str, text: Any, en: EnglishSource, en_fields) -> Optional[str]:
    """Each variant on its own (R1-2): a union would let one drop a param another uses."""
    if any(not v for v in variants(text)):
        return "empty variant"
    offered, required = en.call_params(key)
    for name, v in named_variants(text):
        reason = _variant_reason(name, v, offered, required, en_fields)
        if reason is not None:
            return reason
    return None


def _variant_reason(name: str, v: Any, offered: frozenset, required: frozenset,
                    en_fields) -> Optional[str]:
    if type(v) is not str:
        return f"malformed template: variant {name!r} is not a string"
    try:
        got = template_fields(v)
    except TemplateError as exc:
        return f"malformed template: {exc}"
    extra, missing = got - offered, required - got
    if extra:
        return f"variant {name!r}: placeholders {sorted(extra)} not offered by the call"
    if missing:
        return (f"variant {name!r}: placeholders {sorted(missing)} missing "
                f"(English {sorted(en_fields)})")
    return None
