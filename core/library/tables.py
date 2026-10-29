# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The file-owned tables ``library``, ``rating`` and ``biography`` (§3.6, D-23).

The only module that reads, sets and removes them. Read with the app's reader
(``canonicalize=False``), change ``_toml_extra["_top"]``, encode with
``TOMLChartWriter.encode``, check that only that table changed, replace the
file atomically. A file in an unsorted downloads folder is changed under
``chart_sort``'s ``.sort.lock``.
"""
import contextlib
import functools
import os
import tempfile
import tomllib
from pathlib import Path
from typing import Any, Optional

FILE_OWNED = ("library", "rating", "biography")


class TableError(ValueError):
    """The change would touch more than the named table, or the file is not a chart."""


def _read(path: Path) -> dict:
    from core.toml_chart import TOMLChartReader
    return TOMLChartReader().read_toml_file(path, canonicalize=False)


def get(path, key: str) -> Optional[Any]:
    """One file-owned table of a library .toml (None when absent)."""
    if key not in FILE_OWNED:
        raise TableError(f"not a file-owned table: {key}")
    with open(path, "rb") as f:
        doc = tomllib.load(f)
    value = doc.get(key)
    return value if isinstance(value, dict) else None


def tables(path) -> dict:
    """Every file-owned table present in the file."""
    with open(path, "rb") as f:
        doc = tomllib.load(f)
    return {k: doc[k] for k in FILE_OWNED if isinstance(doc.get(k), dict)}


@contextlib.contextmanager
def _maybe_locked(path: Path):
    from core import chart_sort
    folder = path.parent
    if folder.name == chart_sort.UNSORTED_FOLDER:
        with chart_sort._locked(folder):
            yield
    else:
        yield


def _replace(path: Path, text: str) -> None:
    mode = path.stat().st_mode & 0o777
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".toml.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


#: (size, sha256) of the bytes the last set/remove left in its file (this
#: thread's write: the GUI thread or one worker), what a later UNDO expects.
_last_written = None


def last_written():
    return _last_written


class Changed(TableError):
    """The file is not the one the caller saw (``expect`` fingerprint)."""


def _change(path, key: str, value: Optional[dict], expect=None) -> bool:
    import hashlib
    from core.toml_chart import TOMLChartWriter
    if key not in FILE_OWNED:
        raise TableError(f"not a file-owned table: {key}")
    path = Path(path)
    with _maybe_locked(path):
        raw_bytes = path.read_bytes()
        if expect is not None and (len(raw_bytes), hashlib.sha256(raw_bytes).hexdigest()) \
                != tuple(expect):
            raise Changed(f"{path.name} changed since it was shown")
        before_text = raw_bytes.decode("utf-8")
        before = tomllib.loads(before_text)
        raw = _read(path)
        extra = {t: dict(v) for t, v in (raw.get("_toml_extra") or {}).items()}
        top = dict(extra.get("_top", {}))
        if value is None:
            top.pop(key, None)
        else:
            top[key] = dict(value)
        extra["_top"] = top
        raw["_toml_extra"] = extra
        text = TOMLChartWriter().encode(raw)
        after = tomllib.loads(text)
        expected = dict(before)
        if value is None:
            expected.pop(key, None)
        else:
            expected[key] = after.get(key)
        if after != expected or (value is not None and after.get(key) != dict(value)):
            raise TableError(f"{path.name}: writing {key} would change other fields")
        global _last_written
        if text == before_text:
            _last_written = (len(raw_bytes), hashlib.sha256(raw_bytes).hexdigest())
            return False
        if expect is not None and path.read_bytes() != raw_bytes:
            raise Changed(f"{path.name} changed while it was being written")
        _replace(path, text)
        data = text.encode("utf-8")
        _last_written = (len(data), hashlib.sha256(data).hexdigest())
        return True


def set_table(path, key: str, value: dict, expect=None) -> bool:
    """Set one file-owned table; True when the file changed. ``expect``:
    the file's (size, sha256) the caller saw; checked on the bytes this
    write reads (under the sort lock in an unsorted folder), ``Changed`` else."""
    return _change(path, key, value, expect)


def remove_table(path, key: str, expect=None) -> bool:
    """Remove one file-owned table; True when the file changed."""
    return _change(path, key, None, expect)



def _drop_file_owned(birth_data: dict) -> dict:
    data = dict(birth_data)
    if data.get("_toml_extra") is not None:
        extra = {t: dict(k) for t, k in data["_toml_extra"].items() if t not in FILE_OWNED}
        for key in FILE_OWNED:
            extra.get("_top", {}).pop(key, None)
        data["_toml_extra"] = extra
    return data


def save_birth_data(path, birth_data: dict) -> bool:
    """An app save of an existing ``.toml`` (Chart Info, Save As, New & Edit):
    the chart fields from ``birth_data``, the file-owned tables from the disk
    (D-23). The incoming copy of ``library``, ``rating`` and ``biography`` is
    dropped, so a save never brings back a table changed on disk after the
    chart was loaded."""
    return KeepingTOMLWriter().update_toml_birth_data(path, birth_data)


@functools.lru_cache(maxsize=1)
def _keeping_writer():
    from core.toml_chart import TOMLChartWriter

    class _Keeping(TOMLChartWriter):
        """``TOMLChartWriter`` whose ``update_toml_birth_data`` keeps the
        disk's file-owned tables (New & Edit's writer dispatch)."""

        def update_toml_birth_data(self, path, birth_data: dict) -> bool:
            if Path(path).exists():
                try:  # an unreadable file would be overwritten and lose its tables
                    _read(Path(path))
                except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
                    raise TableError(f"{path} cannot be read, so it is not "
                                     f"overwritten: {exc}") from exc
            return super().update_toml_birth_data(path, _drop_file_owned(birth_data))

    return _Keeping


def KeepingTOMLWriter():  # noqa: N802 - built on first use (no import cycle)
    return _keeping_writer()()
