# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Immutable per-language catalogs and t()/term() (SPEC-LOC-002 §3.2–3.4).

Cached lookups perform no disk I/O. source.py loads files; templates.py models
values; validation.py rejects invalid entries. I18N_PUBLIC=1 displays only
approved, current translations. Inherited templates retain their own language.
"""
from __future__ import annotations

import html
import json
import logging
import os
import string
from pathlib import Path
from types import MappingProxyType
from typing import Any, Dict, Iterable, List, Mapping, NamedTuple, Optional, Set, Tuple

from core.i18n import languages as _languages
from core.i18n import templates as _templates
from core.i18n.languages import ENGLISH
from core.i18n.pseudo import pseudo as _pseudo
from core.i18n.source import EnglishSource, _read_folder, _read_terms  # noqa: F401
from core.i18n.templates import (  # noqa: F401  (the historical public names)
    PLURAL_CATEGORIES, TemplateError, area_of, is_plural, is_select, source_hash,
    template_fields, unwrap_english, value_fields, variants)
from core.i18n.templates import _MAPS, _PARSER
from core.i18n.validation import (  # noqa: F401
    CatalogReport, compute_report as _compute_report, term_state as _term_state,
    validate_entry as _validate_entry)

log = logging.getLogger(__name__)

TERM_META_KEYS = frozenset(("gender", "policy", "src", "ok", "note"))


class TermRef(NamedTuple):
    """A domain term passed as a template param: ``t(k, "{planet} rules", planet=TermRef("planet", "Sun"))``.
    The catalog resolves it in the template's own language; ``{planet|gen}`` picks a form."""
    kind: str
    ident: Any


def public_build() -> bool:
    return os.environ.get("I18N_PUBLIC") == "1"


# --------------------------------------------------------------------------
# Catalog
# --------------------------------------------------------------------------

def _freeze(value: Any) -> Any:
    """A read-only deep copy: mappings -> MappingProxyType, lists -> tuples.
    Already frozen mappings (a parent catalog's values) are returned as they are."""
    if type(value) is dict:
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if type(value) in (list, tuple):
        return tuple(_freeze(v) for v in value)
    return value


def _frozen_values(texts: Dict[str, Any], candidates: Iterable[str]) -> Dict[str, Any]:
    """``texts`` with its non-string values frozen; only ``candidates`` (the keys
    that went through full validation) can hold one."""
    for key in [k for k in candidates if k in texts and type(texts[k]) is not str]:
        texts[key] = _freeze(texts[key])
    return texts


class Catalog:
    """One language's immutable, validated catalog.

    ``report`` (T-1 counts) is computed on first access from the files read at
    load, so the per-key source hashing is paid by the completeness report, not
    by the app's first lookup; validation and the display policy are applied at
    load."""

    __slots__ = ("code", "language", "messages", "terms", "pseudo", "public",
                 "_pseudo_cache", "_report", "_report_inputs", "message_languages", "__weakref__")

    def __init__(self, code: str, language, messages: Mapping[str, Any],
                 terms: Mapping[str, Mapping[str, Mapping[str, Any]]],
                 report_inputs: Optional[tuple], public: bool, message_languages=None):
        self.code = code
        self.language = language
        # Deep-frozen before caching (R1-4): no caller can edit a cached variant
        # or term entry. _build freezes the non-string values it validated (the
        # few plural/select entries), so the 4,000 plain strings are not walked.
        self.messages = MappingProxyType(messages)
        self.terms = MappingProxyType({k: _freeze(v) for k, v in terms.items()})
        self.pseudo = bool(language is not None and language.pseudo)
        self._pseudo_cache: Dict[str, Tuple[Any, Any]] = {}
        self.public = public
        self._report: Optional[CatalogReport] = None
        self._report_inputs, self.message_languages = report_inputs, MappingProxyType(dict(message_languages or {}))

    @property
    def report(self) -> Optional[CatalogReport]:
        """T-1 counts for this language's own files (None for English / pseudo)."""
        if self._report is None and self._report_inputs is not None:
            self._report = _compute_report(*self._report_inputs)
        return self._report

    @property
    def cardinal(self):
        return (self.language or _languages.get(ENGLISH)).cardinal

    @property
    def ordinal(self):
        return (self.language or _languages.get(ENGLISH)).ordinal

    def __repr__(self):
        return f"<Catalog {self.code} messages={len(self.messages)}>"


_CATALOGS: Dict[str, Catalog] = {}
_ENGLISH_SOURCE: Dict[str, EnglishSource] = {}
_MISSING: Dict[str, Set[str]] = {}          # lang -> keys looked up without a translation
_TERM_MISSES: Dict[Tuple[str, str], int] = {}   # (kind, ident) unknown to English -> count
_TERM_UNTRANSLATED: Dict[str, Set[Tuple[str, str]]] = {}
_process = {"lang": ENGLISH}


def _clear() -> None:
    _CATALOGS.clear()
    _templates.clear_memo()
    _ENGLISH_SOURCE.clear()
    _MISSING.clear()
    _TERM_MISSES.clear()
    _TERM_UNTRANSLATED.clear()


_languages.on_clear(_clear)


def english_source() -> EnglishSource:
    src = _ENGLISH_SOURCE.get("en")
    if src is None:
        src = _ENGLISH_SOURCE["en"] = EnglishSource(_languages.data_root())
        if public_build():
            src.hashes.complete()     # the public display policy compares every entry
    return src


def _build(code: str) -> Catalog:
    lang = _languages.get(code)
    public = public_build()
    if lang is None or lang.code == ENGLISH:
        return Catalog(ENGLISH if lang is None else code, lang or _languages.get(ENGLISH),
                       {}, english_source().terms, None, public)
    if lang.pseudo:
        return Catalog(code, lang, {}, _pseudo_terms(english_source().terms), None, public)
    return _translated(code, lang, public)


def _pseudo_terms(en_terms: Dict[str, Dict[str, dict]]) -> Dict[str, Dict[str, dict]]:
    return {kind: {ident: {f: (_pseudo(v) if f not in TERM_META_KEYS and isinstance(v, str)
                               else v) for f, v in entry.items()}
                   for ident, entry in table.items()}
            for kind, table in en_terms.items()}


def _translated(code: str, lang, public: bool) -> Catalog:
    """The catalog of a translated language: its own valid entries over its
    parent's (the display policy applied), English for everything else."""
    parent = catalog_for(lang.parent) if lang.parent and lang.parent != ENGLISH else None
    en = english_source()
    root = _languages.data_root() / code
    problems: List[str] = []
    raw = _read_folder(root / "ui", problems)
    texts, slow, invalid = _valid_texts(code, lang, raw, en)
    hidden = _hide_unapproved(texts, raw, en) if public else []
    messages, origins = _inherit_messages(parent, _frozen_values(texts, slow), code)
    own_terms = _read_terms(root / "terms", problems)
    terms = _merged_terms(parent, own_terms, en, public)
    for p in problems:
        log.warning("i18n %s: %s", code, p)
    return Catalog(code, lang, messages, terms,
                   (raw, own_terms, en, invalid, hidden, problems), public, origins)


def _inherit_messages(parent, texts, code):
    """Keep each template's language alongside inherited immutable values."""
    messages = dict(parent.messages) if parent else {}
    origins = dict(parent.message_languages) if parent else {}
    messages.update(texts)
    origins.update(dict.fromkeys(texts, code))
    return messages, origins


def _needs_validation(texts: Dict[str, Any], en_values: Dict[str, Any]) -> List[str]:
    """The keys whose translation or English is not plain text (templates,
    plurals, selects). A comprehension, not a loop: the INV-7 load budget."""
    return [k for k, v in texts.items()
            if type(v) is not str or not v or "{" in v or "}" in v
            or type(en_values[k]) is not str or "{" in en_values[k] or "}" in en_values[k]]


def _valid_texts(code: str, lang, raw: Dict[str, Any], en: EnglishSource
                 ) -> Tuple[Dict[str, Any], List[str], List[Tuple[str, str]]]:
    """(valid texts, the keys fully validated, (key, reason) of invalid entries)."""
    texts = {k: e["text"] for k, e in raw.items() if type(e) is dict and "text" in e}
    invalid = [(k, "entry must be an object with 'text'") for k in raw if k not in texts]
    for key in texts.keys() - en.values.keys():
        del texts[key]                # unused: no English source (reported)
    slow = _needs_validation(texts, en.values)
    for key in slow:
        reason = _validate_entry(lang, key, texts[key], en)
        if reason is not None:
            invalid.append((key, reason))
            log.debug("i18n %s: %s invalid (%s); English used", code, key, reason)
            del texts[key]
    return texts, slow, invalid


def _hide_unapproved(texts: Dict[str, Any], raw: Dict[str, Any], en: EnglishSource) -> List[str]:
    """Public build: drop every text not approved AND current (the parent's
    approved text, if any, stays); returns the hidden keys."""
    en_h = en.hashes.complete()
    hidden = [k for k in texts if raw[k].get("src") != en_h[k] or raw[k].get("ok") != en_h[k]]
    for key in hidden:
        del texts[key]
    return hidden


def _merged_terms(parent: Optional[Catalog], own_terms: Dict[str, Dict[str, dict]],
                  en: EnglishSource, public: bool) -> Dict[str, Dict[str, dict]]:
    terms = {k: dict(v) for k, v in parent.terms.items()} if parent else {}
    for kind, table in own_terms.items():
        en_table = en.terms.get(kind, {})
        terms.setdefault(kind, {}).update(
            {ident: entry for ident, entry in table.items()
             if not public or _term_state(entry, en_table.get(ident)) == "approved"})
    return terms


def catalog_for(code: Optional[str]) -> Catalog:
    """The cached catalog of ``code`` (None = the process UI language). An unknown
    code gets the English catalog (the fallback chain ends at English)."""
    if code is None:
        code = _process["lang"]
    cat = _CATALOGS.get(code)
    if cat is None:
        cat = _CATALOGS[code] = _build(code)
    return cat


def set_process_language(code: str) -> None:
    """Set the ONE process default (the UI language). Only LanguageManager calls
    this; headless code passes ``lang=`` explicitly instead (§3.2)."""
    _process["lang"] = code or ENGLISH


def current_process_language() -> str:
    return _process["lang"]


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

class _SafeFormatter(string.Formatter):
    """Named fields only; TermRef params resolved in the template's language;
    HTML-escaped values for ``.html`` keys."""

    def __init__(self, lang: str, escape: bool):
        super().__init__()
        self.lang = lang
        self.escape = escape

    def get_field(self, field_name, args, kwargs):
        if "." in field_name or "[" in field_name or not field_name or field_name.isdigit():
            raise KeyError(field_name)
        name, _, form = field_name.partition("|")
        value = kwargs[name]
        if isinstance(value, TermRef):
            value = term(value.kind, value.ident, form or "name", lang=self.lang)
        return value, field_name

    def format_field(self, value, format_spec):
        out = format(value, format_spec)
        return html.escape(out, quote=False) if self.escape else out


def _variant(value: Any, cat: Catalog, params: Dict[str, Any]) -> str:
    if isinstance(value, str):
        return value
    if is_select(value):
        return _select_variant(value, cat, params)
    return _plural_variant(value, cat, params)


def _select_variant(value: Any, cat: Catalog, params: Dict[str, Any]) -> str:
    sel = params.get(value["select"])
    gender = None
    if isinstance(sel, TermRef):
        gender = term_gender(sel.kind, sel.ident, lang=cat.code)
    elif sel is not None:
        gender = str(sel)
    chosen = value.get(gender) if gender else None
    return chosen if isinstance(chosen, str) else value.get("other", "")


def _plural_variant(value: Any, cat: Catalog, params: Dict[str, Any]) -> str:
    if "count" in params:
        chosen = value.get(cat.cardinal.category(params["count"]))
    elif "ordinal" in params:
        chosen = value.get(cat.ordinal.category(params["ordinal"]))
    else:
        chosen = None
    if not isinstance(chosen, str):
        chosen = value.get("other")
    if not isinstance(chosen, str):
        chosen = next((v for v in value.values() if isinstance(v, str)), "")
    return chosen


def _english() -> Catalog:
    return catalog_for(ENGLISH)


def _format(key: str, template: str, params: Dict[str, Any], lang: str) -> str:
    return _SafeFormatter(lang, key.endswith(".html")).vformat(template, (), params)


def _render(key: str, value: Any, default: Any, params: Dict[str, Any], cat: Catalog) -> str:
    text = _variant(value, cat, params)
    if text and not params:
        return text
    if text:
        try:
            return _format(key, text, params, cat.code)
        except Exception as exc:  # noqa: BLE001  (last guard: never a broken string)
            log.debug("i18n %s: %s format error (%s); English used", cat.code, key, exc)
    if value is default and cat.code == ENGLISH:
        return _lenient(key, text, params)
    en = _english()
    en_text = _variant(default, en, params)
    if not params:
        return en_text
    try:
        return _format(key, en_text, params, ENGLISH)
    except Exception:  # noqa: BLE001
        return _lenient(key, en_text, params)


class _Keep(dict):
    def __missing__(self, k):
        return "{" + k + "}"


def _lenient(key: str, text: str, params: Dict[str, Any]) -> str:
    """Format what can be formatted; leave broken fields as written."""
    out = []
    try:
        for lit, field, spec, conv in _PARSER.parse(text):
            out.append(lit)
            if field is None:
                continue
            written = "{" + field + ("!" + conv if conv else "") + (":" + spec if spec else "") + "}"
            try:
                out.append(_format(key, written, params, ENGLISH))
            except Exception:  # noqa: BLE001
                out.append(written)
        return "".join(out)
    except ValueError:
        return text


def _pseudo_value(value: Any) -> Any:
    if isinstance(value, str):
        return _pseudo(value)
    if isinstance(value, _MAPS):
        return {k: (v if k == "select" else _pseudo(v)) for k, v in value.items()}
    return value


def t(key: str, default: Any, *, lang: Optional[str] = None, tight: bool = False,
      **params: Any) -> str:
    """UI text for ``key`` in ``lang`` (None = the process UI language).

    ``default`` is the English source written at the call site: a template string,
    a plural object (``count=`` / ``ordinal=`` selects the CLDR category and is
    available as ``{count}`` / ``{ordinal}``) or a select object (gender
    agreement with a TermRef param). ``tight=True`` is extractor metadata
    (translators keep within +30% length). Never returns a key, a marker or an
    empty string (§3.3)."""
    code = lang or _process["lang"]
    cat = _CATALOGS.get(code)
    if cat is None or cat.pseudo:
        return _t_uncached(key, default, code, params)
    value = cat.messages.get(key)
    if value is None:
        cat, value = _missing(cat, key, default)
    if params or not isinstance(value, str) or not value:
        return _render_or_english(key, value, default, params,
                                  catalog_for(cat.message_languages.get(key, cat.code)))
    return value


def _t_uncached(key: str, default: Any, code: str, params: Dict[str, Any]) -> str:
    """t() for a language not loaded yet, or the pseudo language."""
    cat = catalog_for(code)
    if not cat.pseudo:
        return t(key, default, lang=code, **params)
    cached = cat._pseudo_cache.get(key)
    if cached is None or cached[0] != default:
        cached = cat._pseudo_cache[key] = (default, _pseudo_value(default))
    return _render(key, cached[1], default, params, cat) or _render(
        key, default, default, params, _english())


def _missing(cat: Catalog, key: str, default: Any) -> Tuple[Catalog, Any]:
    """(catalog, value) for a key the catalog has no translation of: English."""
    if cat.code != ENGLISH:
        _note_missing(cat.code, key)
        cat = _english()
    return cat, default


def _render_or_english(key: str, value: Any, default: Any, params: Dict[str, Any],
                       cat: Catalog) -> str:
    out = _render(key, value, default, params, cat)
    return out if out else _render(key, default, default, params, _english())


def _note_missing(code: str, key: str) -> None:
    seen = _MISSING.setdefault(code, set())
    if key not in seen:
        seen.add(key)
        log.debug("i18n %s: no translation for %s", code, key)


def missing_keys(code: str) -> Set[str]:
    """Keys looked up in ``code`` this session without a translation."""
    return set(_MISSING.get(code, ()))


# --------------------------------------------------------------------------
# Terms
# --------------------------------------------------------------------------

_ALIASES: Dict[str, Dict[str, Dict[str, str]]] = {}


def _aliases() -> Dict[str, Dict[str, str]]:
    table = _ALIASES.get("map")
    if table is None:
        table = {}
        path = _languages.data_root() / "terms_aliases.json"
        if path.is_file():
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                log.warning("i18n: terms_aliases.json unreadable (%s)", exc)
                doc = {}
            for section in ("generated", "manual"):
                for kind, mapping in (doc.get(section) or {}).items():
                    if isinstance(mapping, dict):
                        table.setdefault(kind, {}).update(
                            {str(k): str(v) for k, v in mapping.items()})
        _ALIASES["map"] = table
    return table


_languages.on_clear(_ALIASES.clear)


def canonical_ident(kind: str, ident: Any) -> str:
    """The canonical term id: an int index becomes its string; a spelling variant
    maps through i18n/terms_aliases.json."""
    if isinstance(ident, bool):
        ident = int(ident)
    key = str(ident)
    return _aliases().get(kind, {}).get(key, key)


def _term_entry(cat: Catalog, kind: str, ident: str):
    table = cat.terms.get(kind)
    return table.get(ident) if table is not None else None


def term(kind: str, ident: Any, form: str = "name", *, lang: Optional[str] = None) -> str:
    """The display text of a domain term (§3.2). ``ident`` is the engine's id
    (an index for ordered sets, a name for named sets, or an alias). ``form``:
    name, abbr, long, gloss, or a language-declared grammatical form; a missing
    form falls back to name. Unknown ident: returns ``str(ident)``, logged once,
    counted as a term miss."""
    code = lang or _process["lang"]
    cat = _CATALOGS.get(code) or catalog_for(code)
    cid = canonical_ident(kind, ident)
    entry = _term_entry(cat, kind, cid)
    if entry is None:
        entry = _english_term(cat, kind, cid)
        if entry is None:
            return _term_miss(kind, cid, ident)
    if form in TERM_META_KEYS:
        form = "name"
    value = entry.get(form)
    return value if isinstance(value, str) and value else entry["name"]


def _english_term(cat: Catalog, kind: str, cid: str):
    """The English entry of a term the catalog lacks (counted as untranslated)."""
    if cat.code == ENGLISH:
        return None
    en_entry = _term_entry(_english(), kind, cid)
    if en_entry is not None:
        _TERM_UNTRANSLATED.setdefault(cat.code, set()).add((kind, cid))
    return en_entry


def _term_miss(kind: str, cid: str, ident: Any) -> str:
    miss = (kind, cid)
    if miss not in _TERM_MISSES:
        log.debug("i18n: unknown term %s:%s", kind, cid)
    _TERM_MISSES[miss] = _TERM_MISSES.get(miss, 0) + 1
    return str(ident)


def term_tooltip(kind: str, ident: Any, *, lang: Optional[str] = None) -> str:
    """The native gloss of a ``keep_gloss`` term, ready for setToolTip; "" when
    the language declares no gloss (no tooltip)."""
    code = lang or _process["lang"]
    cat = catalog_for(code)
    cid = canonical_ident(kind, ident)
    entry = _term_entry(cat, kind, cid)
    if entry is None and cat.code != ENGLISH:
        entry = _term_entry(_english(), kind, cid)
    gloss = entry.get("gloss") if entry else None
    return gloss if isinstance(gloss, str) else ""


def term_gender(kind: str, ident: Any, *, lang: Optional[str] = None) -> Optional[str]:
    """The grammatical gender a language declares for a term, or None."""
    cat = catalog_for(lang)
    entry = _term_entry(cat, kind, canonical_ident(kind, ident))
    g = entry.get("gender") if entry else None
    return g if isinstance(g, str) else None


def term_idents(kind: str, lang: Optional[str] = ENGLISH) -> Tuple[str, ...]:
    """The idents a language's catalog has for ``kind`` (English: the generated set)."""
    table = catalog_for(lang).terms.get(kind) or {}
    return tuple(table)


def term_misses() -> Dict[Tuple[str, str], int]:
    """Unknown (kind, ident) lookups this session, with counts (T-1)."""
    return dict(_TERM_MISSES)


def untranslated_terms(code: str) -> Set[Tuple[str, str]]:
    return set(_TERM_UNTRANSLATED.get(code, ()))


def iter_term_kinds(root: Optional[Path] = None) -> Iterable[str]:
    folder = (root or _languages.data_root()) / ENGLISH / "terms"
    return sorted(p.stem for p in folder.glob("*.json")) if folder.is_dir() else []
