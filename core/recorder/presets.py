# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Quality presets, formats and the MB-per-minute estimate (SPEC-REC-001 §4.3).

The video is quality-targeted with a rate CAP, so a mostly still chart comes
out well under the estimate; the dialog says "up to".
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple

AUDIO_BPS = 128_000            # AAC-LC, 48 kHz mono (mobile §5.4)
AUDIO_RATE = 48_000
FPS_CHOICES = (30, 60)


@dataclass(frozen=True)
class Preset:
    key: str
    label: str
    max_height: Optional[int]   # None = native size
    cap_bps_30: int
    cap_bps_60: int

    def cap_bps(self, fps: int) -> int:
        return self.cap_bps_60 if fps >= 60 else self.cap_bps_30


PRESETS = (
    Preset("small", "Small · 720p", 720, 1_500_000, 2_200_000),
    Preset("standard", "Standard · 1080p", 1080, 3_000_000, 4_500_000),
    Preset("high", "High · full size", None, 6_000_000, 9_000_000),
)
DEFAULT_PRESET = "standard"


@dataclass(frozen=True)
class VideoFormat:
    key: str
    label: str
    note: str
    cap_factor: float           # cap multiplier against H.264
    software: Tuple[str, ...]   # encoder + its options
    hardware: Tuple[str, ...]   # GPU encoders the probe tries, in order
    quality: Tuple[str, ...]    # quality-target options for the software encoder


FORMATS = (
    VideoFormat("h264", "H.264", "plays everywhere", 1.0,
                ("libx264", "-preset", "veryfast", "-x264-params", "threads=4:lookahead-threads=1"),
                ("h264_nvenc",), ("-crf", "23")),
    VideoFormat("h265", "H.265", "about 40 % smaller, some older phones cannot play it", 0.6,
                ("libx265", "-preset", "fast",
                 "-x265-params", "log-level=error:pools=4:frame-threads=2"),
                ("hevc_nvenc",), ("-crf", "26")),
    VideoFormat("av1", "AV1", "smallest, needs a recent graphics card or more processor", 0.5,
                ("libsvtav1", "-preset", "10", "-svtav1-params", "lp=4"), ("av1_nvenc",), ("-crf", "35")),
)
DEFAULT_FORMAT = "h264"


def preset(key: str) -> Preset:
    for p in PRESETS:
        if p.key == key:
            return p
    return preset(DEFAULT_PRESET)


def video_format(key: str) -> VideoFormat:
    for f in FORMATS:
        if f.key == key:
            return f
    return video_format(DEFAULT_FORMAT)


def hardware_encoders(format_key: str, windows: bool = False) -> Tuple[str, ...]:
    """The GPU encoders the probe tries, in order. Windows adds Intel (QSV)
    and AMD (AMF) after NVIDIA (D-20); Linux keeps NVIDIA only."""
    nvenc = video_format(format_key).hardware
    if not windows:
        return nvenc
    stem = nvenc[0].rsplit("_", 1)[0]
    return nvenc + (f"{stem}_qsv", f"{stem}_amf")


def video_cap_bps(preset_key: str, format_key: str, fps: int) -> int:
    return int(preset(preset_key).cap_bps(fps) * video_format(format_key).cap_factor)


CONTAINER_OVERHEAD = 1.03     # MP4/MKV boxes and headers, rounded up (review R1 F10)


def estimate_mb_per_min(preset_key: str, format_key: str, fps: int, audio: bool) -> int:
    """Upper estimate in whole MB per minute, rounded UP:
    (video cap + audio) x 60 / 8 / 1e6 x container overhead. An estimate, not
    a contract: the encoder buffer allows short bursts above the cap."""
    bps = video_cap_bps(preset_key, format_key, fps) + (AUDIO_BPS if audio else 0)
    return math.ceil(bps * 60 / 8 / 1e6 * CONTAINER_OVERHEAD)


def even_down(value: int) -> int:
    return max(2, int(value) // 2 * 2)


def output_size(width: int, height: int, preset_key: str) -> Tuple[int, int]:
    """The encoded size: the captured size scaled down to the preset's height
    (never up), aspect kept, both sides even."""
    width, height = even_down(width), even_down(height)
    max_h = preset(preset_key).max_height
    if max_h is None or height <= max_h:
        return width, height
    scale = max_h / height
    return even_down(round(width * scale)), even_down(max_h)
