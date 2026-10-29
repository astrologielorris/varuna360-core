# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The folder map (§4.2 step 1): ``.library/folder_map.json``, longest prefix wins.

The map is data written by the architect from the survey and corrected by
Lorris; it never lives in the repo (INV-9). Format::

    {"version": 1,
     "rules": {"<folder prefix>": {"class": "<class>", "section": "<name or null>"}},
     "collections": {"<folder prefix>": "<collection name>"},
     "section_names": {"<section as found>": "<clear section name>"}}

A rule with no section takes the first folder under its prefix as the section.
"""
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Tuple

CLASSES = ("public-people", "public-events", "private-people", "private-events",
           "research-cases", "mixed", "skip")
KIND = {"public-people": "person", "private-people": "person", "public-events": "event",
        "private-events": "event", "research-cases": "case"}
PRIVACY = {"public-people": "public", "public-events": "public", "research-cases": "public",
           "private-people": "private", "private-events": "private"}


class FolderMapError(ValueError):
    """The folder map file is missing a field or names an unknown class."""


@dataclass(frozen=True)
class Placement:
    cls: str
    section: Optional[str]
    rule: str  # the matching prefix, "" for the root rule, None-like "(no rule)"


@dataclass
class FolderMap:
    rules: Dict[str, Tuple[str, Optional[str]]] = field(default_factory=dict)
    collections: Dict[str, str] = field(default_factory=dict)
    renames: Dict[str, str] = field(default_factory=dict)

    def place(self, folder: str) -> Placement:
        """Class and section of a source folder (relative, '/' separated)."""
        parts = [] if folder in ("", ".") else folder.split("/")
        for n in range(len(parts), -1, -1):
            key = "/".join(parts[:n])
            if key in self.rules:
                cls, section = self.rules[key]
                if section is None and n < len(parts):
                    section = parts[n]
                return Placement(cls, self.rename(section), key)
        return Placement("mixed", None, "(no rule)")

    def rename(self, section: Optional[str]) -> Optional[str]:
        """The clear section name: looked up as found, then ignoring case and as a
        clear name ('Scientists_Inventors', 'scientists inventors' are one section)."""
        if section is None:
            return None
        from core.library.names import clear_name
        folded = {k.lower(): v for k, v in self.renames.items()}
        return (self.renames.get(section) or folded.get(section.lower())
                or folded.get(clear_name(section).lower()) or section)

    def collection(self, folder: str) -> Optional[str]:
        """The collection a source folder belongs to (longest prefix), if any."""
        parts = [] if folder in ("", ".") else folder.split("/")
        for n in range(len(parts), 0, -1):
            name = self.collections.get("/".join(parts[:n]))
            if name:
                return name
        return None


def parse(doc: dict) -> FolderMap:
    """A FolderMap from the decoded JSON document (validated)."""
    rules = {}
    for prefix, rule in (doc.get("rules") or {}).items():
        cls = (rule or {}).get("class")
        if cls not in CLASSES:
            raise FolderMapError(f"folder map rule {prefix!r}: unknown class {cls!r}")
        rules[prefix.strip("/")] = (cls, rule.get("section") or None)
    collections = {k.strip("/"): str(v) for k, v in (doc.get("collections") or {}).items()}
    renames = {str(k): str(v) for k, v in (doc.get("section_names") or {}).items()}
    return FolderMap(rules, collections, renames)


def load(path: Path) -> FolderMap:
    """Read ``folder_map.json``; a missing file gives an empty map (all mixed)."""
    path = Path(path)
    if not path.exists():
        return FolderMap()
    return parse(json.loads(path.read_text(encoding="utf-8")))
