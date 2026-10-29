# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""macOS pieces of the recorder (SPEC-REC-001 §4.13, D-21): ffmpeg avfoundation.

Everything here is unused on Linux and Windows; callers test ``IS_MACOS``
(as ``windows.IS_WINDOWS``). CoreGraphics is reached with ctypes only.

- Video: ``-f avfoundation -i "Capture screen N:none"`` records ONE whole
  display at its pixel size (a Retina display at twice its points). A window
  or rectangle is cut out with ``crop`` first in the filter graph
  (``capture_source``). N is the display's place in
  ``CGGetActiveDisplayList``, the list avfoundation numbers its screens from.
- Sound: each source is its own audio-only avfoundation input
  (``-i "none:<device>"``). macOS has no "monitor" of the speakers: computer
  sound needs a loopback device (BlackHole, Loopback, Soundflower...) that
  the user sends the sound to; without one the row is off with a note.
- Timestamps: every avfoundation input is stamped with the wall clock
  (``-use_wallclock_as_timestamps 1``, as on Windows), so ``-copyts`` and the
  shared origin ``t0`` apply exactly as on Linux.
- Encoders: ``h264_videotoolbox`` / ``hevc_videotoolbox``, probed like NVENC,
  else the software encoder. AV1 is software only.
- Screen Recording permission (TCC): ``CGPreflightScreenCaptureAccess``;
  ``ask_permission()`` (from the record dialog only) makes macOS list the app.
- ffmpeg: a Finder-started app does not see Homebrew's PATH, so the usual
  Homebrew and MacPorts places are tried too.

Tested on the Intel macOS Sequoia 15.7 VM (QEMU), not on Apple Silicon
hardware (2026-10-22); the argv, the parsing and the geometry are also unit
tested on Linux. §6 of the spec marks what still needs a real Mac.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
import re
import subprocess
import sys
import time
from typing import Callable, Dict, List, Optional, Tuple

from core.recorder.region import Rect, clip_even, intersect, to_native, union

IS_MACOS = sys.platform.startswith("darwin")

PIXEL_FORMAT = "nv12"             # a native screen format, closest to yuv420p
SCREEN_PREFIX = "Capture screen "
FFMPEG_PLACES = ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/opt/local/bin/ffmpeg",
                 "~/bin/ffmpeg")    # Homebrew (Apple Silicon), Intel copies, MacPorts, a user copy
# Loopback ("virtual") audio devices that carry what the speakers play.
LOOPBACK_HINTS = ("blackhole", "loopback", "soundflower", "background music",
                  "eqmac", "ishowu")
HARDWARE = {"h264": ("h264_videotoolbox",), "h265": ("hevc_videotoolbox",)}
LIST_TTL_S = 5.0
FFMPEG_URL = "https://ffmpeg.org/download.html#build-mac"

# Draft wording (orchestrator draft, for Lorris's review).
TEXT = {
    "no_ffmpeg": ("ffmpeg is not installed. On an Apple Silicon Mac: brew install ffmpeg. "
                  "On an Intel Mac (Homebrew no longer serves them): download ffmpeg from "
                  "ffmpeg.org (macOS builds) and put it in /usr/local/bin. "
                  "Then start Varuna360 again."),
    "permission": ("Varuna360 may not record the screen yet. Open System Settings > "
                   "Privacy & Security > Screen Recording, turn on Varuna360 (or the "
                   "Terminal that started it), then quit and reopen Varuna360."),
    "no_loopback": ("Computer sound on macOS needs a loopback audio device such as "
                    "BlackHole 2ch (free). Install it, then send the sound to it (Audio MIDI "
                    "Setup > Multi-Output Device keeps your speakers on too)."),
    "no_zmq": ("This ffmpeg cannot blur in the video (it has no zmq filter), so the blur "
               "options are off. Homebrew's ffmpeg has it (Apple Silicon: brew install "
               "ffmpeg); many downloadable builds do not."),
    "notifications": ("macOS does not let an app hide notification banners: turn on "
                      "Do Not Disturb (Control Centre > Focus) before recording."),
}

_list_cache: Dict[str, tuple] = {}
_asked_permission = False


def ffmpeg_candidates() -> Tuple[str, ...]:
    return tuple(os.path.expanduser(p) for p in FFMPEG_PLACES)


# ------------------------------------------------------------- devices

_SECTION = re.compile(r"AVFoundation (video|audio) devices:")
# "[<log context>] [N] Name": ffmpeg 4-7 name the context "AVFoundation indev"
# or "AVFoundation input device", newer ones "in#0" (as for DirectShow).
_ITEM = re.compile(r"^\[[^\]]*\]\s*\[(\d+)\]\s+(.*\S)\s*$")


def parse_device_list(text: str) -> Dict[str, List[Tuple[int, str]]]:
    """``ffmpeg -f avfoundation -list_devices true -i ""`` (stderr) ->
    {"video": [(index, name)], "audio": [(index, name)]}."""
    out: Dict[str, List[Tuple[int, str]]] = {"video": [], "audio": []}
    section = None
    for line in (text or "").splitlines():
        m = _SECTION.search(line)
        if m:
            section = m.group(1)
            continue
        if section is None:
            continue
        m = _ITEM.match(line)
        if m:
            out[section].append((int(m.group(1)), m.group(2)))
        else:
            section = None                  # the device list ended
    return out


def build_list_devices_argv(ffmpeg: str = "ffmpeg") -> List[str]:
    return [ffmpeg, "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""]


def list_devices(runner: Callable = subprocess.run, ffmpeg: Optional[str] = None):
    """The parsed device list (cached a few seconds: the dialog asks for the
    list and both defaults while it opens)."""
    if ffmpeg is None:
        from core.recorder.encoders import ffmpeg_program
        ffmpeg = ffmpeg_program()
    hit = _list_cache.get(ffmpeg)
    if hit and time.monotonic() - hit[0] < LIST_TTL_S and runner is hit[2]:
        return hit[1]
    try:
        r = runner(build_list_devices_argv(ffmpeg), capture_output=True, text=True, timeout=10)
        text = (r.stderr or "") + (r.stdout or "")
    except (OSError, subprocess.SubprocessError):
        text = ""
    parsed = parse_device_list(text)
    _list_cache[ffmpeg] = (time.monotonic(), parsed, runner)
    return parsed


def clear_cache() -> None:
    _list_cache.clear()


def _cached_audio() -> List[Tuple[int, str]]:
    hits = sorted(_list_cache.values(), key=lambda h: h[0])
    return hits[-1][1]["audio"] if hits else []


def is_loopback(name: str) -> bool:
    low = (name or "").lower()
    return any(h in low for h in LOOPBACK_HINTS)


def list_sources(runner: Callable = subprocess.run):
    from core.recorder.audio_devices import Source
    return [Source(name, name, is_loopback(name)) for _i, name in list_devices(runner)["audio"]]


def default_microphone(runner: Callable = subprocess.run) -> Optional[str]:
    """avfoundation does not say which is the default: the first microphone."""
    return next((s.name for s in list_sources(runner) if not s.monitor), None)


def default_computer_sound(runner: Callable = subprocess.run) -> Optional[str]:
    return next((s.name for s in list_sources(runner) if s.monitor), None)


def computer_sound_note(sources) -> Optional[str]:
    return None if any(s.monitor for s in sources) else TEXT["no_loopback"]


def audio_spec(name: str, devices: Optional[List[Tuple[int, str]]] = None) -> str:
    """What follows ``none:`` for a device. avfoundation reads a leading
    number as an index, splits on ``:`` and matches a name by its first
    letters ("BlackHole" would also take "BlackHole 16ch"), so a name that
    could be misread goes by its index from the last device list."""
    devices = _cached_audio() if devices is None else devices
    index = next((i for i, n in devices if n == name), None)
    risky = name[:1].isdigit() or ":" in name or \
        any(n != name and n.startswith(name) for _i, n in devices)
    return str(index) if risky and index is not None else name


# ------------------------------------------------------------- displays

class _CGRect(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double),
                ("w", ctypes.c_double), ("h", ctypes.c_double)]


def _coregraphics():
    if not IS_MACOS:
        return None
    for path in ("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics",
                 ctypes.util.find_library("CoreGraphics")):
        if path:
            try:
                return ctypes.CDLL(path)
            except OSError:
                continue
    return None


def displays(cg=None) -> List[Tuple[Rect, float]]:
    """The active displays in avfoundation's order: (bounds in points in the
    global space Qt also uses, pixels per point). Empty when unknown."""
    cg = cg if cg is not None else _coregraphics()
    if cg is None:
        return []
    try:
        ids = (ctypes.c_uint32 * 16)()
        count = ctypes.c_uint32(0)
        cg.CGGetActiveDisplayList.restype = ctypes.c_int32
        cg.CGGetActiveDisplayList.argtypes = [ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p]
        cg.CGDisplayBounds.restype = _CGRect
        cg.CGDisplayBounds.argtypes = [ctypes.c_uint32]
        cg.CGDisplayCopyDisplayMode.restype = ctypes.c_void_p
        cg.CGDisplayCopyDisplayMode.argtypes = [ctypes.c_uint32]
        cg.CGDisplayModeGetPixelWidth.restype = ctypes.c_size_t
        cg.CGDisplayModeGetPixelWidth.argtypes = [ctypes.c_void_p]
        cg.CGDisplayModeRelease.argtypes = [ctypes.c_void_p]
        if cg.CGGetActiveDisplayList(16, ids, ctypes.pointer(count)) != 0:
            return []
        out = []
        for i in range(count.value):
            b = cg.CGDisplayBounds(ids[i])
            mode = cg.CGDisplayCopyDisplayMode(ids[i])
            px = int(cg.CGDisplayModeGetPixelWidth(mode)) if mode else 0
            if mode:
                cg.CGDisplayModeRelease(mode)
            scale = px / b.w if b.w and px else 1.0
            out.append((Rect(round(b.x), round(b.y), round(b.w), round(b.h)), scale))
        return out
    except (OSError, AttributeError):
        return []


def capture_root(screens: Optional[List[Tuple[Rect, float]]] = None) -> Optional[Rect]:
    """Every display in the recorder's native space (each keeps its logical
    origin, scaled by its own ratio: ``region.to_native``); the top-left can
    be negative (a display left of or above the main one)."""
    screens = displays() if screens is None else screens
    root = None
    for geo, dpr in screens:
        n = to_native(geo, (geo.x, geo.y), dpr)
        root = n if root is None else union(root, n)
    return root


def screen_size():
    """(width, height) in pixels of the main display (CLI), or None."""
    found = displays()
    if not found:
        return None
    geo, dpr = found[0]
    n = to_native(geo, (geo.x, geo.y), dpr)
    return n.w, n.h


def capture_source(rect: Optional[Rect], logical: Optional[Rect],
                   fallback: Optional[List[Tuple[Rect, float]]] = None):
    """("Capture screen N", rect clipped to that display, crop in its pixels).

    ``rect`` is in the native space (``capture_root``), ``logical`` the same
    area in points. The display is the one holding most of ``logical`` (with
    mixed ratios the displays overlap in native space); a rectangle spanning
    two keeps its part on that display: avfoundation records one. Displays
    come from CoreGraphics (avfoundation's order), else from ``fallback``
    (Qt's screens, assumed to be in the same order)."""
    screens = displays() or list(fallback or [])
    device = SCREEN_PREFIX + "0"
    if rect is None or not screens:
        return device, None, None
    best, best_area = None, 0
    for i, (geo, dpr) in enumerate(screens):
        native = to_native(geo, (geo.x, geo.y), dpr)
        part = intersect(logical, geo) if logical is not None else intersect(rect, native)
        area = part.w * part.h if part else 0
        if area > best_area:
            best, best_area = (i, native), area
    if best is None:
        return device, None, None
    index, native = best
    clipped = clip_even(rect, native)
    if clipped is None:
        return SCREEN_PREFIX + str(index), None, None
    # Always cropped, also for a whole display: the graph then works on the
    # size the masks and the scaling expect even if the capture is bigger.
    crop = Rect(clipped.x - native.x, clipped.y - native.y, clipped.w, clipped.h)
    return SCREEN_PREFIX + str(index), clipped, crop


# ------------------------------------------------------------- permission

def screen_capture_allowed(cg=None) -> bool:
    """False only when macOS says this app may not record the screen.
    Unknown (no CoreGraphics, macOS before 10.15) = True: ffmpeg tries."""
    cg = cg if cg is not None else _coregraphics()
    preflight = getattr(cg, "CGPreflightScreenCaptureAccess", None) if cg is not None else None
    if preflight is None:
        return True
    preflight.restype = ctypes.c_bool
    return bool(preflight())


def ask_permission(cg=None) -> None:
    """Once per run, when recording is not allowed: macOS shows its prompt
    and lists the app under Screen Recording. Called from the record dialog,
    never from a menu that is only being looked at."""
    global _asked_permission
    cg = cg if cg is not None else _coregraphics()
    if _asked_permission or cg is None or screen_capture_allowed(cg):
        return
    request = getattr(cg, "CGRequestScreenCaptureAccess", None)
    if request is not None:
        _asked_permission = True
        request.restype = ctypes.c_bool
        request()


def unsupported_reason(ffmpeg_found: bool) -> Optional[str]:
    if not ffmpeg_found:
        return TEXT["no_ffmpeg"]
    if not screen_capture_allowed():
        return TEXT["permission"]
    return None


# ------------------------------------------------------------- ffmpeg

def video_input_args(cfg, video_queue: str) -> List[str]:
    device = cfg.display if cfg.display.startswith(SCREEN_PREFIX) else SCREEN_PREFIX + "0"
    return ["-thread_queue_size", video_queue, "-f", "avfoundation",
            "-capture_cursor", "1", "-capture_mouse_clicks", "0",
            "-pixel_format", PIXEL_FORMAT, "-framerate", str(cfg.fps),
            "-use_wallclock_as_timestamps", "1", "-i", f"{device}:none"]


def audio_input_args(source: str, audio_queue: str) -> List[str]:
    return ["-thread_queue_size", audio_queue, "-f", "avfoundation",
            "-use_wallclock_as_timestamps", "1", "-i", f"none:{audio_spec(source)}"]


def hardware_encoders(format_key: str) -> Tuple[str, ...]:
    return HARDWARE.get(format_key, ())


def encoder_args(encoder: str, cap: int) -> List[str]:
    """VideoToolbox has no quality target on every Mac (``-q:v`` is Apple
    Silicon only): an average of two thirds of the cap, capped."""
    return ["-c:v", encoder, "-realtime", "1", "-b:v", str(cap * 2 // 3),
            "-maxrate", str(cap), "-bufsize", str(2 * cap)]


# ------------------------------------------------------------- ffmpeg dies with the app

TRAMPOLINE = (
    "import os,select,signal,sys\n"
    "app=int(sys.argv[1]);me=os.getpid()\n"
    "os.getppid() == app or sys.exit(70)\n"
    "if os.fork() == 0:\n"
    " n=os.open(os.devnull,os.O_RDWR)\n"
    " for f in (0,1,2): os.dup2(n,f)\n"
    " kq=select.kqueue();go=False\n"
    " try:\n"
    "  kq.control([select.kevent(app,select.KQ_FILTER_PROC,select.KQ_EV_ADD,select.KQ_NOTE_EXIT)],0)\n"
    " except OSError:\n"
    "  go=True\n"
    " if not go:\n"
    "  try:\n"
    "   kq.control([select.kevent(me,select.KQ_FILTER_PROC,select.KQ_EV_ADD,select.KQ_NOTE_EXIT)],0)\n"
    "   go=any(e.ident==app for e in kq.control(None,1))\n"
    "  except OSError:\n"
    "   go=False\n"
    " if go:\n"
    "  try: os.kill(me,signal.SIGTERM)\n"
    "  except OSError: pass\n"
    " os._exit(0)\n"
    "try:\n os.execvp(sys.argv[2], sys.argv[2:])\n"
    "except OSError:\n sys.exit(127)\n"
)
"""No ``PR_SET_PDEATHSIG`` on macOS: the trampoline forks a tiny watcher
that waits (kqueue ``NOTE_EXIT``) for the app or ffmpeg to exit, and sends
ffmpeg SIGTERM when the app goes first (INV-4). The watcher lets go of the
take's pipes, so nothing waits on it."""
