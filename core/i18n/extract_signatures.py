# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""What tools/i18n_extract.py reads (SPEC-LOC-002 INV-2).

1. KEY_APIS: every key-taking API and the position of its key and English
   default arguments. A project wrapper that forwards a key and a default is
   declared here too; the AST pass then reads its call sites.
2. LIST_APIS: list binders taking a list of (key, default) pairs.
3. TERM_APIS: term lookups (kind, ident), counted for the term-miss report.
4. REGISTERED_SOURCES: declared English source tables. Each yields
   (key, English text) pairs; a DYNAMIC key at a call site is legal only when it
   starts with one of these prefixes.
5. PARAM_SETS: key prefixes whose call offers a declared param set; a
   translation may use any subset (date patterns order and pad their own way).

Qt-free; the tables are imported lazily, only by the extractor.
"""
from __future__ import annotations

import importlib
from typing import Callable, Dict, Iterator, NamedTuple, Optional, Tuple


class KeyApi(NamedTuple):
    key: int                  # positional index of the key (self excluded)
    default: int              # positional index of the English default
    modules: Tuple[str, ...]  # a bare name call counts when imported from one of these;
                              # () = any attribute call of that name (methods)


KEY_APIS: Dict[str, KeyApi] = {
    "t": KeyApi(0, 1, ("core.i18n", "core.i18n.catalog")),
    # ui/translated_text.py (W1b): bind_text(widget, setter, key, default, **params)
    "bind_text": KeyApi(2, 3, ("ui.translated_text",)),
    # TranslatedTextMixin._bind_text(widget, setter, key, default, **params) (W1b)
    "_bind_text": KeyApi(2, 3, ()),
}

# bind_list_text(widget, setter, [(key, default), ...]) (W1b list setters)
LIST_APIS: Dict[str, Tuple[int, Tuple[str, ...]]] = {
    "bind_list_text": (2, ("ui.translated_text",)),
    "_bind_list_text": (2, ()),
}

TERM_APIS: Dict[str, Tuple[str, ...]] = {
    "term": ("core.i18n", "core.i18n.terms", "core.i18n.catalog"),
    "term_tooltip": ("core.i18n", "core.i18n.terms", "core.i18n.catalog"),
    "TermRef": ("core.i18n", "core.i18n.terms", "core.i18n.catalog"),
}

PARAM_SETS: Dict[str, str] = {
    "format.date.": "core.i18n.dates:PARAM_NAMES",
}


def _table(target: str):
    module, _, name = target.partition(":")
    return getattr(importlib.import_module(module), name)


# --------------------------------------------------------------------------
# Registered sources
# --------------------------------------------------------------------------

def _settings() -> Iterator[Tuple[str, str]]:
    from core import settings_registry as reg
    from core.settings_registry.schema import ChoicesRef
    for e in reg.entries():
        if e.label:
            yield f"settings.{e.key}.label", e.label
        if e.help:
            yield f"settings.{e.key}.help", e.help
        choices = e.choices
        if isinstance(choices, ChoicesRef):
            if choices.target.startswith("core.i18n."):
                continue        # language endonyms: data of the registry, never translated
            choices = choices.resolve()
        for c in choices or ():
            if c.label:
                yield f"settings.{e.key}.choice.{c.value}", c.label


def _vargas() -> Iterator[Tuple[str, str]]:
    for n, name in _table("core.varga_codes:VARGA_NAMES").items():
        yield f"varga.name.{n}", name
    for n, label in _table("core.varga_codes:_VARGA_DISPLAY_LABEL").items():
        yield f"varga.label.{n}", label


def _house_systems() -> Iterator[Tuple[str, str]]:
    for value, label in _table("core.house_systems:HOUSE_SYSTEM_LABELS").items():
        yield f"house_system.{value}", label


_MODE_FIELDS = (("label", "label"), ("short_label", "short_label"),
                ("status_label", "status_label"), ("title_static", "title"),
                ("title_tooltip", "title_tooltip"))


def _dasha_modes() -> Iterator[Tuple[str, str]]:
    for spec in _table("managers.dasha.modes:MODES"):
        for attr, leaf in _MODE_FIELDS:
            value = getattr(spec, attr, None)
            if isinstance(value, str) and value:
                yield f"dasha.mode.{spec.key}.{leaf}", value


def _aditya_card_text() -> Iterator[Tuple[str, str]]:
    for key, text in _table("core.aditya_data:_UI_TEXT_EN").items():
        yield f"content.aditya.{key}", text


def _exchange_ranks() -> Iterator[Tuple[str, str]]:
    from AI_tools.AI_main_function.interchange_rank import RANK_LINES, RANK_WORDS
    for suffix, table in (("word", RANK_WORDS), ("line", RANK_LINES)):
        for rank, text in table.items():
            yield f"panel.exchange.rank.{rank}.{suffix}", text


class Source(NamedTuple):
    prefix: str
    produce: Callable[[], Iterator[Tuple[str, str]]]
    origin: str


REGISTERED_SOURCES: Tuple[Source, ...] = (
    Source("panel.exchange.rank.", _exchange_ranks,
           "AI_tools/AI_main_function/interchange_rank.py RANK_WORDS, RANK_LINES"),
    Source("settings.", _settings, "core/settings_registry (label, help, Choice.label)"),
    Source("varga.", _vargas, "core/varga_codes.py VARGA_NAMES, _VARGA_DISPLAY_LABEL"),
    Source("house_system.", _house_systems, "core/house_systems.py HOUSE_SYSTEM_LABELS"),
    Source("dasha.mode.", _dasha_modes, "managers/dasha/modes.py MODES"),
    Source("content.aditya.", _aditya_card_text, "core/aditya_data.py _UI_TEXT_EN"),
)


def registered_prefix(key_prefix: str) -> Optional[Source]:
    """The registered source covering a dynamic key whose literal prefix is given."""
    for src in REGISTERED_SOURCES:
        if key_prefix.startswith(src.prefix):
            return src
    return None


def param_set(key: str) -> Optional[Tuple[str, ...]]:
    for prefix, target in PARAM_SETS.items():
        if key.startswith(prefix):
            return tuple(_table(target))
    return None
