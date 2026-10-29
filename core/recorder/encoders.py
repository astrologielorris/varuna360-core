# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Which encoder a format uses on this machine, and whether recording can run
at all here (SPEC-REC-001 §4.3, INV-9).

The GPU encoders of a format are tried in order with a five-frame probe; the
first that works is used, else the software encoder. Results are cached for
the process (a probe costs about 0.3 s).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from typing import Callable, Dict, Optional, Sequence, Tuple

from core.recorder import macos, presets
from core.recorder.ffmpeg_command import (BACKEND_AVFOUNDATION, BACKEND_WINDOWS, BACKEND_X11,
                                          build_filters_argv, build_probe_argv)
from core.recorder.windows import IS_WINDOWS, no_window

_CACHE: Dict[Tuple, Optional[str]] = {}
_FILTERS: Dict[str, Optional[frozenset]] = {}

# Draft wording (orchestrator draft, for Lorris's review).
INSTALL_FFMPEG_WINDOWS = ("ffmpeg is not installed. Install it with "
                          "\"winget install Gyan.FFmpeg\" (or put ffmpeg.exe in the Varuna360 "
                          "folder), then start Varuna360 again.")
TOO_OLD_FFMPEG_WINDOWS = ("The ffmpeg found ({path}) is too old for recording. Install a recent one "
                          "with \"winget install Gyan.FFmpeg\", then start Varuna360 again.")


def _windows_candidates(env=None, app_dir: Optional[str] = None):
    """Where ffmpeg.exe usually is on Windows when it is not on PATH yet
    (winget adds it to PATH only for programs started after the install)."""
    env = os.environ if env is None else env
    app_dir = app_dir or os.path.dirname(os.path.abspath(sys.executable))
    local = env.get("LOCALAPPDATA", "")
    out = [os.path.join(app_dir, "ffmpeg.exe"), os.path.join(app_dir, "ffmpeg", "bin", "ffmpeg.exe")]
    if local:
        out.append(os.path.join(local, "Microsoft", "WinGet", "Links", "ffmpeg.exe"))
        winget = os.path.join(local, "Microsoft", "WinGet", "Packages")
        try:
            for name in sorted(os.listdir(winget)):
                if name.lower().startswith("gyan.ffmpeg"):
                    pkg = os.path.join(winget, name)
                    for sub in sorted(os.listdir(pkg), reverse=True):
                        out.append(os.path.join(pkg, sub, "bin", "ffmpeg.exe"))
        except OSError:
            pass
    for root in (env.get("ProgramFiles", ""), "C:\\"):
        if root:
            out.append(os.path.join(root, "ffmpeg", "bin", "ffmpeg.exe"))
    if env.get("ProgramData"):
        out.append(os.path.join(env["ProgramData"], "chocolatey", "bin", "ffmpeg.exe"))
    if env.get("USERPROFILE"):
        out.append(os.path.join(env["USERPROFILE"], "scoop", "shims", "ffmpeg.exe"))
    return out


MIN_VERSION = (5, 1)          # -fps_mode; older Windows copies hide in tool folders
_VERSIONS: Dict[str, Optional[Tuple[int, int]]] = {}


# libavutil major of each ffmpeg release (git builds print it too).
_AVUTIL_TO_RELEASE = {56: (4, 0), 57: (5, 0), 58: (6, 0), 59: (7, 0), 60: (8, 0)}


def parse_version(text: str) -> Optional[Tuple[int, int]]:
    """(major, minor) of ``ffmpeg -version``: the release number when there is
    one, else read from the ``libavutil`` line (git builds such as
    ``N-56000-g...``); None when neither is there (taken as recent)."""
    text = (text or "").strip()
    m = re.match(r"ffmpeg version n?(\d+)\.(\d+)", text)
    if m:
        return int(m.group(1)), int(m.group(2))
    a = re.search(r"^libavutil\s+(\d+)\.\s*(\d+)", text, re.M)
    if a:
        major, minor = int(a.group(1)), int(a.group(2))
        if major < 56:
            return (3, 0)
        if major in _AVUTIL_TO_RELEASE:
            rel = _AVUTIL_TO_RELEASE[major]
            # 5.1 shipped libavutil 57.28: a 57 git build before that is "5.0".
            return (5, 1) if major == 57 and minor >= 28 else rel
        return (99, 0)
    return None


def _version_ok(exe: str, runner: Callable = subprocess.run) -> bool:
    if exe not in _VERSIONS:
        try:
            r = runner([exe, "-version"], capture_output=True, text=True, timeout=10, **no_window())
            _VERSIONS[exe] = parse_version(r.stdout) if r.returncode == 0 else (0, 0)
        except (OSError, subprocess.SubprocessError):
            _VERSIONS[exe] = (0, 0)
    v = _VERSIONS[exe]
    return v is None or v >= MIN_VERSION


def _windows_found(env=None):
    """Every ffmpeg.exe on PATH (in order), then the usual folders."""
    env = os.environ if env is None else env
    hits = [os.path.join(d, "ffmpeg.exe") for d in env.get("PATH", "").split(os.pathsep) if d]
    seen, out = set(), []
    for c in hits + _windows_candidates(env):
        key = os.path.normcase(os.path.abspath(c))
        if key not in seen and os.path.isfile(c):
            seen.add(key)
            out.append(c)
    return out


def old_ffmpeg() -> Optional[str]:
    """Windows: an ffmpeg that was found but is older than MIN_VERSION
    (when no usable one exists), for the install message."""
    if not IS_WINDOWS or ffmpeg_path():
        return None
    return next(iter(_windows_found()), None)


def ffmpeg_path() -> Optional[str]:
    if IS_WINDOWS:
        # Windows (D-20): the first ffmpeg recent enough, PATH first: a tool's
        # folder on PATH can carry a ten-year-old copy (seen on Lorris's machine).
        return next((c for c in _windows_found() if _version_ok(c)), None)
    found = shutil.which("ffmpeg")
    if found or not macos.IS_MACOS:
        return found
    # macOS (D-21): a Finder-started app has no Homebrew PATH.
    return next((c for c in macos.ffmpeg_candidates() if os.path.isfile(c)), None)


def ffmpeg_program() -> str:
    """What to start: on Windows and macOS the found ffmpeg (it may not be on
    PATH: a Finder-started Mac app has no Homebrew PATH), else the bare name
    (Linux argv unchanged; a missing one fails to start and is reported as
    FFMPEG_MISSING)."""
    return (ffmpeg_path() or "ffmpeg") if IS_WINDOWS or macos.IS_MACOS else "ffmpeg"


def capture_backend(platform: Optional[str] = None) -> str:
    platform = sys.platform if platform is None else platform
    if platform.startswith("darwin"):
        return BACKEND_AVFOUNDATION
    return BACKEND_WINDOWS if platform.startswith("win") else BACKEND_X11


# Where the recorder runs: Linux (ffmpeg x11grab + PulseAudio/PipeWire + Xlib)
# Windows (gdigrab + DirectShow), D-20, and macOS (avfoundation), D-21.
SUPPORTED_SYSTEMS = "Linux (on an X11 desktop), Windows and macOS"

_OS_NAMES = (("win", "Windows"), ("darwin", "macOS"))


def os_name(platform: Optional[str] = None) -> str:
    """A person's name for the operating system (``sys.platform`` by default)."""
    platform = sys.platform if platform is None else platform
    for prefix, name in _OS_NAMES:
        if platform.startswith(prefix):
            return name
    return "this system"


def unsupported_reason(platform_name: str, env=None, platform: Optional[str] = None) -> Optional[str]:
    """Why recording cannot run here, or None. ``platform_name`` is
    ``QGuiApplication.platformName()``; ``platform`` is ``sys.platform``."""
    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform
    if platform.startswith("win"):
        if ffmpeg_path() is not None:
            return None
        old = old_ffmpeg()
        return (TOO_OLD_FFMPEG_WINDOWS.format(path=old) if old else INSTALL_FFMPEG_WINDOWS)
    if platform.startswith("darwin"):
        return macos.unsupported_reason(ffmpeg_path() is not None)
    if not platform.startswith("linux"):
        return (f"The screen recorder works on {SUPPORTED_SYSTEMS}. "
                f"It does not work on {os_name(platform)} yet.")
    if (platform_name != "xcb" or env.get("XDG_SESSION_TYPE", "x11") == "wayland"
            or env.get("WAYLAND_DISPLAY")):     # XWayland also reports "xcb" (review R1 F14)
        return "Screen recording needs an X11 session (Wayland is not supported yet)."
    if not env.get("DISPLAY"):
        return "No X display found."
    if ffmpeg_path() is None:
        return "ffmpeg is not installed (sudo apt install ffmpeg)."
    return None


def _probe(argv, runner: Callable) -> bool:
    try:
        return runner(argv, capture_output=True, timeout=15, **no_window()).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def gpu_encoder(format_key: str, preset_key: str, fps: int, size: Sequence[int],
                runner: Callable = subprocess.run) -> Optional[str]:
    """The first GPU encoder of the format that encodes ten frames with the
    take's real settings (size, rate, cap) here, else None (review R1 F9)."""
    key = (format_key, preset_key, fps, tuple(size))
    if key not in _CACHE:
        found = None
        hardware = macos.hardware_encoders(format_key) if macos.IS_MACOS \
            else presets.hardware_encoders(format_key, IS_WINDOWS)
        for encoder in hardware:
            if _probe(build_probe_argv(format_key, preset_key, fps, encoder, size,
                                       ffmpeg_program()), runner):
                found = encoder
                break
        _CACHE[key] = found
    return _CACHE[key]


_FILTER_LINE = re.compile(r"^\s*[A-Z.|]{2,4}\s+(\S+)\s+\S*->\S*")


def parse_filters(text: str) -> frozenset:
    """Filter names from ``ffmpeg -filters``: lines like `` T.C zmq  N->N ...``
    (ffmpeg 4-8, three flag columns) or `` .. zmq  V->V ...`` (ffmpeg 9, two)."""
    names = set()
    for line in (text or "").splitlines():
        m = _FILTER_LINE.match(line)
        if m:
            names.add(m.group(1))
    return frozenset(names)


def has_filter(name: str, runner: Callable = subprocess.run) -> Optional[bool]:
    """Whether this ffmpeg build has filter ``name``; None when ffmpeg could
    not answer (unknown: the take itself will tell)."""
    exe = ffmpeg_path()
    if exe not in _FILTERS:
        try:
            r = runner(build_filters_argv(exe or "ffmpeg"), capture_output=True, text=True,
                       timeout=15, **no_window())
            _FILTERS[exe] = parse_filters(r.stdout) if r.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            _FILTERS[exe] = None
    names = _FILTERS[exe]
    return None if names is None else name in names


def clear_cache() -> None:
    _CACHE.clear()
    _FILTERS.clear()
    _VERSIONS.clear()
