# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Start ffmpeg so it dies with the app (SPEC-REC-001 INV-4, review R1 F4).

PySide6 has no ``QProcess.setChildProcessModifier``, so the take runs through
a three-line Python trampoline: it asks Linux to send it SIGTERM when its
parent dies (``prctl(PR_SET_PDEATHSIG)``, kept across ``exec``), checks the
parent did not die already, then becomes ffmpeg. SIGTERM makes ffmpeg finish
the Matroska file cleanly, so a crashed app still leaves a usable take.
"""
from __future__ import annotations

import os
import sys
from typing import List

PR_SET_PDEATHSIG = 1
EXEC_FAILED = 127          # the trampoline could not start ffmpeg
_TRAMPOLINE = (
    "import ctypes,os,signal,sys\n"
    "ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGTERM)\n"
    "os.getppid() == int(sys.argv[1]) or sys.exit(70)\n"
    "try:\n os.execvp(sys.argv[2], sys.argv[2:])\n"
    "except OSError:\n sys.exit(127)\n"
)


def wrap(argv: List[str], python: str = sys.executable, parent_pid: int = 0,
         platform: str = "") -> List[str]:
    """``[python, -c, trampoline, <parent pid>, ffmpeg, args...]`` on Linux
    and macOS (its own trampoline, ``macos.TRAMPOLINE``); the argv unchanged
    elsewhere."""
    platform = platform or sys.platform
    if platform.startswith("darwin"):
        from core.recorder.macos import TRAMPOLINE
        source = TRAMPOLINE
    elif platform.startswith("linux"):
        source = _TRAMPOLINE
    else:
        return list(argv)
    return [python, "-I", "-c", source, str(parent_pid or os.getpid()), *argv]



def is_trampoline(argv: List[str]) -> bool:
    """``argv`` is ``[app, -I, -c, <one of this package's trampolines>, ...]``."""
    from core.recorder.macos import TRAMPOLINE as macos_source
    return len(argv) >= 4 and argv[1:3] == ["-I", "-c"] and argv[3] in (_TRAMPOLINE, macos_source)


def run_bundled_trampoline(argv: List[str]) -> int:
    """Run a trampoline the app was started as (``run_app.py``).

    In a packaged build ``sys.executable`` is the app itself, not a Python,
    so ``wrap`` starts ``Varuna360 -I -c <trampoline> <pid> ffmpeg ...``.
    Without this the app would open a second window instead of ffmpeg
    (review 2026-10-23). Only the two trampolines of this package run; any
    other source returns 2 without running. ``sys.argv`` is laid out as
    ``python -c`` gives it, ``["-c", <pid>, ffmpeg, ...]``. A PyInstaller
    bundle points LD_LIBRARY_PATH at its own libraries: the system ffmpeg
    gets the caller's original value back before the exec."""
    if not is_trampoline(argv):
        return 2
    original = os.environ.pop("LD_LIBRARY_PATH_ORIG", None)
    if original is not None:
        os.environ["LD_LIBRARY_PATH"] = original
    elif getattr(sys, "_MEIPASS", None):
        os.environ.pop("LD_LIBRARY_PATH", None)
    sys.argv = ["-c", *argv[4:]]
    exec(compile(argv[3], "<recorder-trampoline>", "exec"), {"__name__": "__main__"})
    return 0
