# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Windows pieces of the recorder (SPEC-REC-001 §4.12, D-20).

Everything here is a no-op or None on Linux, so callers need no platform test
of their own beyond ``IS_WINDOWS``. Win32 is reached with ctypes only:

- ``virtual_screen()``: the whole desktop in physical pixels. Its top-left can
  be negative (a monitor left of or above the main one). The app is
  per-monitor DPI aware (Qt 6 sets it), so the numbers are real pixels;
  the CLI calls ``make_dpi_aware()`` first.
- ``bind_to_app(pid)``: puts ffmpeg in a Job Object that kills it when the
  app dies (the Linux trampoline's PR_SET_PDEATHSIG, INV-4). A killed
  ffmpeg leaves the Matroska part file, recovered at the next start (INV-3).
- ``file_in_use(path)``: a part file another ffmpeg still writes (Linux reads
  ``/proc/*/fd``): opening it with no sharing fails with a sharing violation.
- ``no_window()``: subprocess flags so a probe never flashes a console window.
"""
from __future__ import annotations

import ctypes
import os
import sys
from typing import Optional

from core.recorder.region import Rect

IS_WINDOWS = sys.platform.startswith("win")

CREATE_NO_WINDOW = 0x08000000
_SM_XVIRTUALSCREEN, _SM_YVIRTUALSCREEN, _SM_CXVIRTUALSCREEN, _SM_CYVIRTUALSCREEN = 76, 77, 78, 79
_DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_JobObjectExtendedLimitInformation = 9
_PROCESS_SET_QUOTA, _PROCESS_TERMINATE = 0x0100, 0x0001
_GENERIC_READ = 0x80000000
_OPEN_EXISTING = 3
_ERROR_SHARING_VIOLATION = 32
_INVALID_HANDLE = ctypes.c_void_p(-1).value

_job = None          # one job per app process; its handle closes when the app dies


def no_window() -> dict:
    """``subprocess.run`` keyword arguments: no console window on Windows."""
    return {"creationflags": CREATE_NO_WINDOW} if IS_WINDOWS else {}


def make_dpi_aware() -> None:
    """Per-monitor DPI aware (what Qt sets in the app): window and screen
    numbers are then physical pixels, as ffmpeg's gdigrab expects."""
    if not IS_WINDOWS:
        return
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(
            ctypes.c_void_p(_DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2))
    except (AttributeError, OSError):
        pass


def virtual_screen() -> Optional[Rect]:
    """The whole desktop (every monitor) in physical pixels, or None."""
    if not IS_WINDOWS:
        return None
    try:
        m = ctypes.windll.user32.GetSystemMetrics
        r = Rect(m(_SM_XVIRTUALSCREEN), m(_SM_YVIRTUALSCREEN),
                 m(_SM_CXVIRTUALSCREEN), m(_SM_CYVIRTUALSCREEN))
    except (AttributeError, OSError):
        return None
    return r if r.w > 0 and r.h > 0 else None


class _BasicLimits(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", ctypes.c_uint32), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", ctypes.c_uint32),
                ("SchedulingClass", ctypes.c_uint32)]


class _IoCounters(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOperationCount", "WriteOperationCount",
                                               "OtherOperationCount", "ReadTransferCount",
                                               "WriteTransferCount", "OtherTransferCount")]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _BasicLimits), ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


def bind_to_app(pid: int) -> bool:
    """ffmpeg dies with the app (INV-4 on Windows). True when bound."""
    global _job
    if not IS_WINDOWS or not pid:
        return False
    try:
        k32 = ctypes.windll.kernel32
        k32.CreateJobObjectW.restype = ctypes.c_void_p
        k32.OpenProcess.restype = ctypes.c_void_p
        k32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        k32.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                                ctypes.c_void_p, ctypes.c_uint32]
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        if _job is None:
            job = k32.CreateJobObjectW(None, None)
            if not job:
                return False
            info = _ExtendedLimits()
            info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not k32.SetInformationJobObject(job, _JobObjectExtendedLimitInformation,
                                               ctypes.byref(info), ctypes.sizeof(info)):
                k32.CloseHandle(job)
                return False
            _job = job                    # never closed: the app's death closes it
        proc = k32.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, int(pid))
        if not proc:
            return False
        try:
            return bool(k32.AssignProcessToJobObject(_job, proc))
        finally:
            k32.CloseHandle(proc)
    except (AttributeError, OSError):
        return False


def file_in_use(path: str) -> bool:
    """True when another process holds ``path`` open (Windows only)."""
    if not IS_WINDOWS:
        return False
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateFileW.restype = ctypes.c_void_p
        k32.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                                    ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        h = k32.CreateFileW(os.fspath(path), _GENERIC_READ, 0, None, _OPEN_EXISTING, 0, None)
        if h in (None, _INVALID_HANDLE):
            return ctypes.get_last_error() == _ERROR_SHARING_VIOLATION
        k32.CloseHandle(h)
        return False
    except (AttributeError, OSError):
        return False
