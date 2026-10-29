# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The admin folder ``<library>/.library`` (owner only, 0700, never indexed):
folder map, verdicts, plans, manifest, logs, cache. Files are .json, .jsonl or
.md, never .toml (INV-11)."""
import json
import os
import tempfile
from pathlib import Path
from typing import Dict, Iterable

ADMIN = ".library"


def ensure_dir(path: Path, owner_only: bool) -> Path:
    """Create ``path`` and its missing parents; owner-only folders are 0700."""
    path = Path(path)
    missing = []
    p = path
    while not p.exists():
        missing.append(p)
        p = p.parent
    for p in reversed(missing):
        p.mkdir()
        if owner_only:
            os.chmod(p, 0o700)
    if owner_only:
        os.chmod(path, 0o700)
    return path


def root(library_root: Path) -> Path:
    return ensure_dir(Path(library_root) / ADMIN, True)


def folder(library_root: Path, name: str) -> Path:
    return ensure_dir(root(library_root) / name, True)


def write_text(path: Path, text: str, mode: int = 0o600) -> None:
    """Atomic write with the given permissions."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def read_json(path: Path, default):
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def read_manifest(library_root: Path) -> Dict[str, dict]:
    path = Path(library_root) / ADMIN / "manifest.jsonl"
    if not path.exists():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            out[rec["id"]] = rec
    return out


def write_manifest(library_root: Path, records: Iterable[dict]) -> None:
    text = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                   for r in sorted(records, key=lambda r: r["id"]))
    write_text(root(library_root) / "manifest.jsonl", text)
