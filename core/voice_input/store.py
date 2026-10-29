# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Where speech models live and how they get there (td-mgcw8).

The store is a per-user cache folder, not the app's data folder: a model is
hundreds of MB, regenerable by downloading again, and shared by every copy of
the app on the computer (worktrees, Core and Pro). Linux ``$XDG_CACHE_HOME``
(else ``~/.cache``), macOS ``~/Library/Caches``, Windows ``%LOCALAPPDATA%``,
each under ``Varuna360/voice_models``. ``VARUNA360_VOICE_MODELS_DIR``
overrides it (tests).

An install is all-or-nothing: the archive downloads to a ``.part`` file, its
size is checked, it unpacks into a temporary folder with tarfile's ``data``
filter (no absolute paths, no ``..``, no links out), the required files are
checked, and only then is the folder renamed into place. A cancel or an error
leaves no half model behind."""
from __future__ import annotations

import os
import shutil
import sys
import tarfile
import threading
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from core.voice_input.catalog import SpeechModel

MODELS_DIR_ENV = "VARUNA360_VOICE_MODELS_DIR"
_CHUNK = 1 << 20


class InstallCancelled(Exception):
    """The user pressed Cancel; nothing was installed."""


class InstallError(Exception):
    """The download or the archive was not what the catalog promised."""


def models_dir() -> Path:
    override = os.environ.get(MODELS_DIR_ENV)
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "Varuna360" / "voice_models"


def model_path(model: SpeechModel) -> Path:
    return models_dir() / model.model_id


def is_installed(model: SpeechModel) -> bool:
    folder = model_path(model)
    return all((folder / name).is_file() for name in model.required_files)


def library_version() -> Optional[str]:
    """The sherpa-onnx version, or None when the library is not installed."""
    try:
        import sherpa_onnx
    except ImportError:
        return None
    return getattr(sherpa_onnx, "__version__", "unknown")


def install(model: SpeechModel,
            progress: Optional[Callable[[int, int], None]] = None,
            cancel: Optional[threading.Event] = None,
            opener: Callable = urllib.request.urlopen) -> Path:
    """Download and unpack ``model``; return its folder. ``progress(done,
    total)`` is called from this thread after each chunk. Raises
    InstallCancelled or InstallError, leaving the store as it was."""
    root = models_dir()
    root.mkdir(parents=True, exist_ok=True)
    final = model_path(model)
    part = root / f".{model.model_id}.part"
    staging = root / f".{model.model_id}.unpack"
    try:
        _download(model, part, progress, cancel, opener)
        _check_cancel(cancel)
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir()
        try:
            with tarfile.open(part, "r:*") as archive:
                archive.extractall(staging, filter="data")
        except (tarfile.TarError, OSError) as exc:
            raise InstallError(f"The archive could not be unpacked: {exc}") from exc
        unpacked = staging / model.archive_root
        missing = [n for n in model.required_files if not (unpacked / n).is_file()]
        if missing:
            raise InstallError("The archive is missing " + ", ".join(missing))
        _check_cancel(cancel)
        if final.exists():
            shutil.rmtree(final)
        os.replace(unpacked, final)
        return final
    finally:
        if part.exists():
            part.unlink()
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def remove(model: SpeechModel) -> None:
    folder = model_path(model)
    if folder.exists():
        shutil.rmtree(folder)


def _check_cancel(cancel: Optional[threading.Event]) -> None:
    if cancel is not None and cancel.is_set():
        raise InstallCancelled()


def _download(model, part, progress, cancel, opener) -> None:
    total = model.archive_bytes
    done = 0
    try:
        with opener(model.url, timeout=60) as response, open(part, "wb") as out:
            while True:
                _check_cancel(cancel)
                chunk = response.read(_CHUNK)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if progress is not None:
                    progress(done, total)
    except InstallCancelled:
        raise
    except OSError as exc:
        raise InstallError(f"The download failed: {exc}") from exc
    if done != total:
        raise InstallError(
            f"The download is {done:,} bytes, expected {total:,}. Try again.")
