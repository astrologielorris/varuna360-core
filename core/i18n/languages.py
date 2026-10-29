# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The language registry (SPEC-LOC-002 §3.5, INV-1).

``i18n/languages.json`` is the ONE list of languages; this module loads and
validates it (the content map: core/i18n/content.py). It has no per-language
code: a new language is a row in the JSON, never a Python edit.

Qt-free. The data root defaults to the ``i18n/`` folder at the project root;
tests point it elsewhere with ``set_data_root()`` (every i18n cache is cleared).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from core.i18n.plural import PluralRuleError, PluralRules

ENGLISH = "en"
STATUSES = ("terms_only", "partial", "complete")
_REQUIRED = ("code", "endonym", "english_name", "parent", "qt_locale", "script",
             "cardinal", "ordinal", "fonts", "status")

_DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "i18n"
_state = {"root": _DEFAULT_ROOT, "registry": None}
_clear_hooks: List[Callable[[], None]] = []


class LanguageRegistryError(ValueError):
    """languages.json or content.json is invalid (all problems listed)."""


def data_root() -> Path:
    return _state["root"]


def project_root() -> Path:
    """Content paths in content.json are relative to this (the i18n root's parent)."""
    return _state["root"].parent


def set_data_root(path: Optional[Path]) -> Path:
    """Point every i18n lookup at another data folder (tests; None = default).
    Clears every i18n cache. Returns the previous root."""
    previous = _state["root"]
    _state["root"] = Path(path) if path is not None else _DEFAULT_ROOT
    clear_caches()
    return previous


def clear_caches() -> None:
    _state["registry"] = None
    for hook in list(_clear_hooks):
        hook()


def on_clear(hook: Callable[[], None]) -> None:
    """Register a cache-clear callback (catalog and term caches)."""
    _clear_hooks.append(hook)


@dataclass(frozen=True)
class Language:
    code: str
    endonym: str
    english_name: str
    parent: Optional[str]
    qt_locale: Optional[str]
    script: str
    cardinal: PluralRules
    ordinal: PluralRules
    fonts: Tuple[str, ...]
    font_files: Tuple[str, ...]
    status: str
    dev_only: bool = False
    pseudo: bool = False
    # Locales whose qtbase .qm file is loaded when Qt ships none for qt_locale
    # (pt-PT -> pt_BR). Only the .qm file choice; formatting stays qt_locale.
    qt_qm_fallback: Tuple[str, ...] = ()

    @property
    def choice_label(self) -> str:
        """The Settings choice label: endonym, plus the English name when it differs."""
        if self.endonym == self.english_name:
            return self.endonym
        return f"{self.endonym} ({self.english_name})"


@dataclass(frozen=True)
class Registry:
    cldr_version: str
    languages: Tuple[Language, ...]
    by_code: Dict[str, Language]


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _qm_fallback(row: dict, where: str, problems: List[str]) -> Tuple[str, ...]:
    """The optional ``qt_qm_fallback`` list: non-empty locale names, and only
    for a row that has a ``qt_locale`` (it picks a qtbase .qm file, nothing else)."""
    value = row.get("qt_qm_fallback", [])
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        problems.append(f"{where}: qt_qm_fallback must be a list of Qt locale names")
        return ()
    if value and not row.get("qt_locale"):
        problems.append(f"{where}: qt_qm_fallback without a qt_locale")
        return ()
    return tuple(value)


def qm_locale_candidates(language: Language) -> Tuple[str, ...]:
    """The Qt locale names to try, in order, when loading the qtbase .qm file of
    ``language``: its qt_locale, then its qt_qm_fallback. Formatting always uses
    qt_locale alone, and QLocale.setDefault is never called (§4.3, OD-7)."""
    if not language.qt_locale:
        return ()
    return (language.qt_locale, *language.qt_qm_fallback)


def _validate_row(row, idx: int, problems: List[str]) -> Optional[Language]:
    where = f"languages[{idx}]"
    if not isinstance(row, dict):
        problems.append(f"{where}: not an object")
        return None
    missing = [k for k in _REQUIRED if k not in row]
    if missing:
        problems.append(f"{where}: missing {missing}")
        return None
    where = f"language {row['code']!r}"
    if not _strings_ok(row, where, problems):
        return None
    _check_optional(row, where, problems)
    fonts = _str_list(row, "fonts", where, problems, "fonts must be a list of family names")
    font_files = _str_list(row, "font_files", where, problems, "font_files must be a list of paths")
    problems += [f"{where}: font file {f!r} not found" for f in font_files
                 if not (project_root() / f).is_file()]
    rules = _rules(row, where, problems)
    if rules is None:
        return None
    return Language(code=row["code"], endonym=row["endonym"], english_name=row["english_name"],
                    parent=row["parent"], qt_locale=row["qt_locale"], script=row["script"],
                    cardinal=rules["cardinal"], ordinal=rules["ordinal"],
                    fonts=tuple(fonts), font_files=tuple(font_files),
                    status=row["status"], dev_only=bool(row.get("dev_only", False)),
                    pseudo=bool(row.get("pseudo", False)),
                    qt_qm_fallback=_qm_fallback(row, where, problems))


def _strings_ok(row: dict, where: str, problems: List[str]) -> bool:
    for k in ("code", "endonym", "english_name", "script"):
        if not isinstance(row[k], str) or not row[k]:
            problems.append(f"{where}: {k} must be a non-empty string")
            return False
    return True


def _check_optional(row: dict, where: str, problems: List[str]) -> None:
    for k in ("parent", "qt_locale"):
        if row[k] is not None and not isinstance(row[k], str):
            problems.append(f"{where}: {k} must be a string or null")
    if row["status"] not in STATUSES:
        problems.append(f"{where}: status {row['status']!r} not in {STATUSES}")


def _str_list(row: dict, key: str, where: str, problems: List[str], message: str) -> list:
    value = row.get(key, [])
    if not isinstance(value, list) or not all(isinstance(f, str) for f in value):
        problems.append(f"{where}: {message}")
        return []
    return value


def _rules(row: dict, where: str, problems: List[str]) -> Optional[Dict[str, PluralRules]]:
    rules = {}
    for kind in ("cardinal", "ordinal"):
        spec = row[kind]
        if not isinstance(spec, dict) or "other" not in spec \
                or not all(isinstance(v, str) for v in spec.values()):
            problems.append(f"{where}: {kind} must map categories to rule strings, incl. 'other'")
            return None
        try:
            rules[kind] = PluralRules(spec)
        except PluralRuleError as exc:
            problems.append(f"{where}: {kind} rule: {exc}")
            return None
    return rules


def read_doc(path: Path):
    """A registry JSON document; LanguageRegistryError when unreadable."""
    try:
        return _load_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        raise LanguageRegistryError(f"{path}: {exc}") from exc


def load_registry(path: Optional[Path] = None) -> Registry:
    """Parse and validate languages.json; raise LanguageRegistryError on any problem."""
    path = path or data_root() / "languages.json"
    doc = read_doc(path)
    problems: List[str] = []
    rows = doc.get("languages") if isinstance(doc, dict) else None
    if not isinstance(rows, list) or not rows:
        raise LanguageRegistryError(f"{path}: 'languages' must be a non-empty list")
    langs = [lang for idx, row in enumerate(rows)
             if (lang := _validate_row(row, idx, problems)) is not None]
    by_code = _by_code(langs, problems)
    problems += [p for p in (_parent_problem(lang, by_code) for lang in langs) if p]
    if problems:
        raise LanguageRegistryError(f"{path}: " + "; ".join(problems))
    return Registry(cldr_version=str(doc.get("cldr_version", "")),
                    languages=tuple(langs), by_code=by_code)


def _by_code(langs: List[Language], problems: List[str]) -> Dict[str, Language]:
    by_code: Dict[str, Language] = {}
    for lang in langs:
        if lang.code in by_code:
            problems.append(f"language {lang.code!r}: duplicate code")
        by_code[lang.code] = lang
    if ENGLISH not in by_code:
        problems.append("the registry must contain English ('en'), the fallback language")
    return by_code


def _parent_problem(lang: Language, by_code: Dict[str, Language]) -> Optional[str]:
    seen, cur = {lang.code}, lang.parent
    while cur is not None:
        if cur not in by_code:
            return f"language {lang.code!r}: unknown parent {cur!r}"
        if cur in seen:
            return f"language {lang.code!r}: parent cycle"
        seen.add(cur)
        cur = by_code[cur].parent
    return None


def registry() -> Registry:
    reg = _state["registry"]
    if reg is None:
        reg = _state["registry"] = load_registry()
    return reg


def get(code: Optional[str]) -> Optional[Language]:
    if code is None:
        return None
    return registry().by_code.get(code)


def codes(*, include_dev: bool = False) -> Tuple[str, ...]:
    return tuple(lang.code for lang in registry().languages
                 if include_dev or not lang.dev_only)


def user_languages() -> Tuple[Language, ...]:
    """The languages offered to users (menu, Settings, capability enum)."""
    return tuple(lang for lang in registry().languages if not lang.dev_only)


def chain(code: Optional[str]) -> Tuple[str, ...]:
    """The fallback chain of a language WITHOUT the final English default:
    ("pt-PT", "pt") for pt-PT, () for English or an unknown code."""
    out: List[str] = []
    lang = get(code)
    while lang is not None and lang.code != ENGLISH:
        out.append(lang.code)
        lang = get(lang.parent)
    return tuple(out)


def setting_choices() -> Dict[str, str]:
    """{code: label} for the zodiac.sign_language setting, in registry order."""
    return {lang.code: lang.choice_label for lang in user_languages()}


def __getattr__(name: str):
    # ChoicesRef("core.i18n.languages:LANGUAGE_CHOICES") resolves here, lazily,
    # so importing this module never reads a file.
    if name == "LANGUAGE_CHOICES":
        return setting_choices()
    raise AttributeError(name)
