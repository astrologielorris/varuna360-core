# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Where the library lives: ``paths.library_root`` (D-33), empty meaning
``<Documents>/Varuna360/Library`` on every OS."""
from pathlib import Path
from typing import Optional


def documents() -> Path:
    return Path.home() / "Documents"


def library_root(value: Optional[str] = None) -> Path:
    """The library folder from the setting's value (empty: the default)."""
    value = (value or "").strip()
    return Path(value).expanduser() if value else documents() / "Varuna360" / "Library"


_PLAN_SOURCES: dict = {}


def _plan_source(latest: Path):
    """The latest plan's ``source``, read again only when that file changed:
    a plan is an 8 MB file, and this guard runs on every rating written."""
    import os
    from core.library import plan
    st = os.stat(latest)
    stamp = (st.st_mtime_ns, st.st_size, st.st_ino)
    hit = _PLAN_SOURCES.get(str(latest))
    if hit is not None and hit[0] == stamp:
        return hit[1]
    source = plan.load(latest).get("source")
    _PLAN_SOURCES[str(latest)] = (stamp, source)
    return source


def _documents_folders() -> list:
    """Documents, plus the OneDrive Documents a Windows machine may redirect
    it to (Kala then keeps its charts there)."""
    import os
    out = [documents()]
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        base = os.environ.get(var)
        if base:
            out.append(Path(base) / "Documents")
    return out


def kala_folders(library_root: Optional[Path] = None) -> list:
    """The old Kala chart folders, never written (LIB-002 INV-9): Documents/
    Kala/Charts and the source the latest library plan recorded."""
    import os
    out = [os.path.realpath(d / "Kala" / "Charts") for d in _documents_folders()]
    if library_root is not None and (Path(library_root) / ".library" / "plans").is_dir():
        try:
            from core.library import plan
            source = _plan_source(plan.latest(Path(library_root)))
            if source:
                out.append(os.path.realpath(source))
        except Exception:  # noqa: BLE001 - no plan: only the default folder
            pass
    return out


def _overlaps(a: str, b: str) -> bool:
    """True when ``a`` is ``b``, inside it, or holds it."""
    import os
    a, b = os.path.normcase(a), os.path.normcase(b)
    try:
        common = os.path.commonpath([a, b])
    except ValueError:  # different drives
        return False
    return common in (a, b)


def is_kala_folder(folder, library_root: Optional[Path] = None) -> bool:
    """True for a Kala chart folder, a folder inside one (Kala/Charts/personal)
    or a folder that holds one (Documents): writing or moving files there
    reaches Kala's charts (INV-9)."""
    import os
    if not folder:
        return False
    path = os.path.realpath(os.path.expanduser(str(folder)))
    return any(_overlaps(path, kala) for kala in kala_folders(library_root))
