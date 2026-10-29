# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Sound sources (SPEC-REC-001 §4.4).

Linux: PulseAudio / PipeWire sources. Microphones are the sources that are
not monitors; "computer sound" is the monitor of a sink (what the speakers
play). ``pactl`` answers on PulseAudio and on PipeWire's pulse layer alike.

Windows (D-20): DirectShow audio devices, as ffmpeg lists them. Windows has
no monitor source: computer sound needs a loopback recording device ("Stereo
Mix", "Mixage stéréo", a virtual cable...), recognised by its name; with none,
the computer sound row is disabled. A device is named by its DirectShow
alternative name (unique and stable) when ffmpeg gives one.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

from core.recorder import macos
from core.recorder.windows import IS_WINDOWS, no_window

# Names of Windows loopback recording devices (lower case, any language Windows ships).
LOOPBACK_HINTS = ("stereo mix", "stéréo mix", "mixage st", "stereomix", "mezcla est",
                  "missaggio stereo", "what u hear", "wave out", "loopback",
                  "virtual-audio-capturer", "cable output", "voicemeeter out")
_DSHOW_TTL = 5.0
_dshow_cache: dict = {}


@dataclass(frozen=True)
class Source:
    name: str
    description: str
    monitor: bool


def _pactl(args, runner: Callable) -> Optional[str]:
    try:
        r = runner(["pactl", *args], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def parse_sources_json(text: str) -> List[Source]:
    out = []
    for item in json.loads(text or "[]"):
        name = item.get("name") or ""
        if not name:
            continue
        monitor = name.endswith(".monitor") or bool(item.get("monitor_of_sink")
                                                     not in (None, "", "n/a"))
        out.append(Source(name, item.get("description") or name, monitor))
    return out


def parse_sources_text(text: str) -> List[Source]:
    """``pactl list sources`` plain output (old pactl without ``-f json``)."""
    out, name, desc = [], None, None
    for raw in (text or "").splitlines() + ["Source #end"]:
        line = raw.strip()
        if line.startswith("Source #"):
            if name:
                out.append(Source(name, desc or name, name.endswith(".monitor")))
            name, desc = None, None
        elif line.startswith("Name:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("Description:"):
            desc = line.split(":", 1)[1].strip()
    return out


def is_loopback(name: str) -> bool:
    low = (name or "").lower()
    return any(h in low for h in LOOPBACK_HINTS)


# ffmpeg 4-8 tag the lines "[dshow @ 0x...]", ffmpeg 9 "[in#0 @ 0x...]".
_PREFIX = re.compile(r"^\[[\w#:/.-]+ @ [0-9a-fA-Fx]+\]\s?")
_DEVICE = re.compile(r'^\s*"(.+)"(?:\s+\(([^)]*)\))?\s*$')
_ALT = re.compile(r'^\s*Alternative name\s+"(.+)"\s*$')


def parse_dshow_devices(text: str) -> List[Source]:
    """Audio devices from ``ffmpeg -list_devices true -f dshow -i dummy``
    stderr: the ffmpeg 5+ form (``"Name" (audio)``) and the older one
    (section headers ``DirectShow audio devices``)."""
    found, section = [], None
    for raw in (text or "").splitlines():
        if not _PREFIX.match(raw):
            continue                       # driver chatter some cameras print
        line = _PREFIX.sub("", raw)
        low = line.lower()
        if "directshow video devices" in low:
            section = "video"
            continue
        if "directshow audio devices" in low:
            section = "audio"
            continue
        alt = _ALT.match(line)
        if alt and found:
            found[-1][2] = alt.group(1)
            continue
        dev = _DEVICE.match(line)
        if dev:
            kinds = dev.group(2) if dev.group(2) is not None else (section or "")
            found.append([dev.group(1), kinds, None])
    out, seen = [], set()
    for friendly, kinds, alt in found:
        if "audio" not in kinds:
            continue
        name = alt or friendly
        if name in seen:
            continue
        seen.add(name)
        out.append(Source(name, friendly, is_loopback(friendly)))
    return out


def list_dshow(runner: Callable = subprocess.run, ffmpeg: Optional[str] = None) -> List[Source]:
    """Windows audio devices (cached a few seconds: the dialog asks for the
    list and both defaults while it opens)."""
    from core.recorder.ffmpeg_command import build_list_devices_argv
    if ffmpeg is None:
        from core.recorder.encoders import ffmpeg_program
        ffmpeg = ffmpeg_program()
    hit = _dshow_cache.get(ffmpeg)
    if hit and time.monotonic() - hit[0] < _DSHOW_TTL and runner is subprocess.run:
        return hit[1]
    try:
        r = runner(build_list_devices_argv(ffmpeg), capture_output=True, timeout=10, **no_window())
        err = r.stderr if isinstance(r.stderr, str) else (r.stderr or b"").decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        err = ""
    sources = parse_dshow_devices(err)
    if runner is subprocess.run:
        _dshow_cache[ffmpeg] = (time.monotonic(), sources)
    return sources


def list_sources(runner: Callable = subprocess.run) -> List[Source]:
    if IS_WINDOWS:
        return list_dshow(runner)
    if macos.IS_MACOS:                    # avfoundation devices, loopbacks as computer sound
        return macos.list_sources(runner)
    text = _pactl(["-f", "json", "list", "sources"], runner)
    if text:
        try:
            return parse_sources_json(text)
        except (ValueError, AttributeError):
            pass
    return parse_sources_text(_pactl(["list", "sources"], runner) or "")


def default_microphone(runner: Callable = subprocess.run) -> Optional[str]:
    if IS_WINDOWS:        # DirectShow does not say which is the default: the first one
        return next((s.name for s in list_dshow(runner) if not s.monitor), None)
    if macos.IS_MACOS:
        return macos.default_microphone(runner)
    return ((_pactl(["get-default-source"], runner) or "").strip()) or None


def default_computer_sound(runner: Callable = subprocess.run) -> Optional[str]:
    if IS_WINDOWS:
        return next((s.name for s in list_dshow(runner) if s.monitor), None)
    if macos.IS_MACOS:
        return macos.default_computer_sound(runner)
    sink = (_pactl(["get-default-sink"], runner) or "").strip()
    return f"{sink}.monitor" if sink else None


def resolve(wanted: Optional[str], available: List[Source], default: Optional[str]) -> Optional[str]:
    """The remembered device if it still exists, else the default."""
    names = {s.name for s in available}
    if wanted and wanted in names:
        return wanted
    return default
