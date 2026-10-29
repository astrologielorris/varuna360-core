# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The switch (§4.8, D-22): the library root becomes the first chart folder and
the old source folder leaves the list. The source stays on disk, never written.

``new_folders`` is the folder rule; ``carry_favorites`` copies the source's
``favorites.json`` into the library with each chart path mapped through the
manifest to its library file (an unmapped path is kept as it was). Refused
unless ``verify`` of the latest plan passes.
"""
import json
import os
from pathlib import Path
from typing import List, Optional

from core.library import admin

SLOTS = 3


def _same(a: str, b: str) -> bool:
    if not a or not b:
        return False
    return os.path.normcase(os.path.realpath(os.path.expanduser(a))) == \
        os.path.normcase(os.path.realpath(os.path.expanduser(b)))


def new_folders(folders: List[str], library_root: Path, source: Path) -> List[str]:
    """The library root first, the source out, the other folders kept in order."""
    rest = [f for f in folders if f and not _same(f, str(source))
            and not _same(f, str(library_root))]
    out = [str(library_root)] + rest
    if len(out) > SLOTS:
        raise ValueError("no free chart folder slot for the library: remove one in "
                         "Find Chart > Library first")
    return out + [""] * (SLOTS - len(out))


def path_map(library_root: Path, source: Path) -> dict:
    """Absolute source chart path -> absolute library chart path (manifest)."""
    out = {}
    for row in admin.read_manifest(library_root).values():
        target = row.get("path")
        if not target:
            continue
        for rel in row.get("sources_all") or []:
            out[_key(Path(source) / rel)] = str(Path(library_root) / target)
    return out


def _key(path) -> str:
    return os.path.normcase(os.path.realpath(str(path)))


def _absolute(stored: str, base: Path) -> Path:
    p = Path(stored).expanduser()
    return p if p.is_absolute() else Path(base) / p


def _portable(path: str, base: Path) -> str:
    """Relative to the favorites folder when inside it (favorites_manager's rule)."""
    try:
        return str(Path(path).relative_to(base))
    except ValueError:
        return str(path)


def carry_favorites(library_root: Path, source: Path) -> Optional[dict]:
    """Bring the source's ``favorites.json`` into the library root (owner only).
    Each chart path (absolute, or relative to the source as favorites_manager
    stores it) is mapped through the manifest to its library file and stored
    relative to the library; an unmapped path is kept, made absolute so it
    still points at its file. A favorite whose id the library already has is
    not added twice. Returns ``{"mapped", "kept", "added"}`` or None when the
    source has no favorites."""
    src, dst = Path(source) / "favorites.json", Path(library_root) / "favorites.json"
    if not src.exists():
        return None
    doc = json.loads(src.read_text(encoding="utf-8"))
    have = json.loads(dst.read_text(encoding="utf-8")) if dst.exists() else \
        {k: v for k, v in doc.items() if k != "favorites"}
    have.setdefault("favorites", [])
    ids = {f.get("id") for f in have["favorites"]}
    mapping, mapped, kept, added = path_map(library_root, source), 0, 0, 0
    changed = False
    for fav in have["favorites"]:  # a library favorite still pointing at the source
        old = fav.get("chtk_path")
        new = mapping.get(_key(_absolute(old, library_root))) if old else None
        if new:
            fav["chtk_path"] = _portable(new, Path(library_root))
            mapped += 1
            changed = True
    for fav in doc.get("favorites") or []:
        if fav.get("id") in ids:
            continue
        fav = dict(fav)
        old = fav.get("chtk_path")
        if old:
            full = _absolute(old, source)
            new = mapping.get(_key(full))
            if new:
                fav["chtk_path"] = _portable(new, Path(library_root))
                mapped += 1
            else:
                fav["chtk_path"] = str(full)
                kept += 1
        have["favorites"].append(fav)
        ids.add(fav.get("id"))
        added += 1
    if added or changed:
        admin.write_text(dst, json.dumps(have, ensure_ascii=False, indent=2))
    return {"mapped": mapped, "kept": kept, "added": added}


def remap_sessions(profiles_dir: Path, library_root: Path, source: Path) -> dict:
    """Every profile's open charts (``session.json``) that point at a source
    file now point at its library file, so a later save never writes into the
    old folder. Each profile under its own session lock; a profile that is
    locked or unreadable is left untouched and listed. Returns
    ``{"charts": n, "profiles": n, "skipped": [ids]}``."""
    from datetime import datetime, timezone
    from state.profile_store import LOAD_MISSING, LOAD_OK, ProfileStore
    mapping = path_map(library_root, source)
    store = ProfileStore(profiles_dir)
    charts, profiles, skipped = 0, 0, []
    for pid in store.list_profiles():
        with store.profile_lock(pid) as held:
            if not held:
                skipped.append(pid)
                continue
            data = store.load_profile(pid)
            if store.last_load_status not in (LOAD_OK, LOAD_MISSING):
                skipped.append(pid)
                continue
            n = 0
            for entry in data.get("charts") or []:
                old = entry.get("chtk_path")
                new = mapping.get(_key(_absolute(old, source))) if old else None
                if new:
                    entry["chtk_path"] = new
                    entry["updated_at"] = datetime.now(timezone.utc).isoformat()
                    n += 1
            if n:
                if not store.save_profile(pid, data):
                    skipped.append(pid)
                    continue
                charts, profiles = charts + n, profiles + 1
    return {"charts": charts, "profiles": profiles, "skipped": skipped}
