# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The long-form content map (SPEC-LOC-002 §3.5, OD-13). Qt-free.

``i18n/content.json`` maps each long-form content id to its English base file
and per-language files (paths relative to the project root). A language gains
content by adding a file and an entry there, never a Python edit. Lookups follow
the language's parent chain and fall back to English; the map and the file
checks are cached until ``languages.clear_caches()``.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.i18n import languages as _languages
from core.i18n.languages import ENGLISH, LanguageRegistryError

_state: Dict[str, object] = {"content": None, "available": {}}


def _clear() -> None:
    _state["content"] = None
    _state["available"] = {}


_languages.on_clear(_clear)


@dataclass(frozen=True)
class ContentEntry:
    content_id: str
    base: Path
    languages: Dict[str, Path]


def load_content_map(path: Optional[Path] = None) -> Dict[str, ContentEntry]:
    path = path or _languages.data_root() / "content.json"
    if not path.exists():
        return {}
    doc = _languages.read_doc(path)
    content = doc.get("content") if isinstance(doc, dict) else None
    if not isinstance(content, dict):
        raise LanguageRegistryError(f"{path}: 'content' must be an object")
    problems: List[str] = []
    known = _languages.registry().by_code
    root = _languages.project_root()
    out: Dict[str, ContentEntry] = {}
    for cid, spec in content.items():
        entry = _content_entry(cid, spec, known, root, problems)
        if entry is not None:
            out[cid] = entry
    if problems:
        raise LanguageRegistryError(f"{path}: " + "; ".join(problems))
    return out


def _content_entry(cid: str, spec, known, root: Path, problems: List[str]) -> Optional[ContentEntry]:
    if not isinstance(spec, dict) or not isinstance(spec.get("base"), str):
        problems.append(f"content {cid!r}: needs a 'base' path")
        return None
    langs = spec.get("languages", {})
    if not isinstance(langs, dict):
        problems.append(f"content {cid!r}: 'languages' must be an object")
        return None
    files: Dict[str, Path] = {}
    for code, rel in langs.items():
        if code not in known:
            problems.append(f"content {cid!r}: unknown language {code!r}")
        elif not isinstance(rel, str):
            problems.append(f"content {cid!r}: path for {code!r} must be a string")
        else:
            files[code] = root / rel
    return ContentEntry(cid, root / spec["base"], files)


def content_map() -> Dict[str, ContentEntry]:
    cmap = _state["content"]
    if cmap is None:
        cmap = _state["content"] = load_content_map()
    return cmap


def _resolve(content_id: str, code: Optional[str]) -> Tuple[str, Optional[Path]]:
    """(language, file) of ``content_id`` for ``code``: the first language of its
    chain whose listed file exists, else (English, None). Cached with the content
    map (R2-6): the file checks run once per (content, language) until
    languages.clear_caches()."""
    got = _state["available"].get((content_id, code))
    if got is None:
        entry = content_map().get(content_id)
        files = [(c, entry.languages.get(c)) for c in _languages.chain(code)] if entry else []
        got = next(((c, p) for c, p in files if p is not None and p.is_file()), (ENGLISH, None))
        _state["available"][(content_id, code)] = got
    return got


def content_path(content_id: str, code: Optional[str]) -> Optional[Path]:
    """The translated file of ``content_id`` for ``code`` (following the parent
    chain), or None when only English exists. A listed but missing file is None."""
    return _resolve(content_id, code)[1]


def content_language(content_id: str, code: Optional[str]) -> str:
    """The language ``content_id`` is shown in for ``code``: the first language of
    its chain that has the content, else English."""
    return _resolve(content_id, code)[0]
