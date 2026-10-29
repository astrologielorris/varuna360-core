# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The ffmpeg command line of a take (SPEC-REC-001 §4.3, §4.4, D-9).

One process grabs the screen rectangle (pointer drawn), reads zero, one or
two sound sources and writes Matroska (INV-3). Linux: ``x11grab`` + ``pulse``
(PulseAudio/PipeWire). Windows (D-20): ``gdigrab`` of the desktop at an offset
+ ``dshow`` sources; every Windows input is stamped with the wall clock
(``-use_wallclock_as_timestamps``) so the ``t0`` shift below applies to it
exactly as to the Linux inputs, and ``dshow`` reads 50 ms buffers so a sound
packet's stamp is at most that late. Progress goes to
stdout (``-progress pipe:1``), the log and the microphone meter to stderr,
and ``q`` on stdin stops it cleanly.

A/V alignment (review R1 F7): every input keeps its wall-clock timestamps
(``-copyts``) and every stream is shifted by the SAME origin ``t0`` (the
launch time), so an input that opened late starts late in the file instead of
being slid to zero; ``aresample=async`` pads the late start of an audio
source with silence and absorbs drift. Mixing uses fixed gains with no
normalisation (mic 1.0, computer sound 0.7, the mobile gains), then a limiter.
The microphone meter reads the microphone branch BEFORE mixing (RMS dBFS,
four values a second), so loud computer sound cannot hide a dead mic.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from core.recorder import presets
from core.recorder.region import Rect

MIC_GAIN = 1.0
COMPUTER_GAIN = 0.7
VIDEO_QUEUE = "16"        # raw frames: 1080p RGB is ~8 MB each (review R1 F11)
AUDIO_QUEUE = "512"       # small packets
NVENC_CQ = {"h264": "28", "h265": "30", "av1": "34"}
METER_SAMPLES = 12000     # 250 ms at 48 kHz

# Video-only privacy boxes (SPEC-REC-001 INV-7, v0.4): ffmpeg blurs these
# areas in the RECORDING; the screen stays sharp. One drawbox per slot, moved
# live through ffmpeg's zmq filter (core/recorder/zmtp.py) as the window or
# panel moves; every waiting command is applied on the next frame.
MASK_SLOTS = ("memory", "title", "titlebar", "find", "search")   # search: the chart search window
PARKED = (-64, -64, 2, 2)     # off-frame: drawbox w=0/h=0 would mean FULL frame
BLUR_DOWNSCALE = 8

BACKEND_X11 = "x11"           # x11grab + pulse (Linux)
BACKEND_WINDOWS = "gdigrab"   # gdigrab + dshow (Windows)
BACKEND_AVFOUNDATION = "avfoundation"   # avfoundation screen + sound (macOS, D-21)
DSHOW_BUFFER_MS = "50"


@dataclass(frozen=True)
class RecordingConfig:
    display: str                 # X display, e.g. ":0" or ":0.0" (unused on Windows)
    rect: Rect                   # screen pixels, even size (Windows: may be negative)
    output: str                  # the .part.mkv path
    fps: int = 30
    preset: str = presets.DEFAULT_PRESET
    video_format: str = presets.DEFAULT_FORMAT
    encoder: Optional[str] = None  # GPU encoder that passed the probe, None = software
    mic: Optional[str] = None    # pulse source name / dshow device name
    computer: Optional[str] = None  # pulse monitor source / dshow loopback device
    t0: float = 0.0              # wall-clock origin (time.time() at launch)
    # One entry per MASK_SLOTS slot, in capture pixels (None = parked); an
    # empty tuple records with no mask graph at all.
    masks: Tuple[Optional[Rect], ...] = ()
    mask_port: int = 0           # local TCP port the zmq filter binds (0 = no live moves)
    backend: str = BACKEND_X11   # BACKEND_X11, BACKEND_WINDOWS or BACKEND_AVFOUNDATION
    # macOS: avfoundation records a whole display (``display`` = "Capture
    # screen N"); ``crop`` is the rectangle inside it, in its pixels.
    crop: Optional[Rect] = None

    @property
    def has_audio(self) -> bool:
        return bool(self.mic or self.computer)


def _display_input(display: str, rect: Rect) -> str:
    base = display if "." in display.split(":")[-1] else display + ".0"
    return f"{base}+{rect.x},{rect.y}"


def _shift(cfg: RecordingConfig, audio: bool) -> str:
    fn = "asetpts" if audio else "setpts"
    return f"{fn}=PTS-{cfg.t0:.6f}/TB"


def _video_head(cfg: RecordingConfig) -> str:
    """The first filters on the picture: the rectangle cut out of a
    whole-display capture (macOS), then the timestamp shift."""
    c = cfg.crop
    return (f"crop={c.w}:{c.h}:{c.x}:{c.y}," if c else "") + _shift(cfg, False)


def mask_filter(slot: int) -> str:
    return f"drawbox@rm{slot}"


def mask_box(rect: Optional[Rect]) -> Tuple[int, int, int, int]:
    """(x, y, w, h) for a slot; never a zero size (drawbox reads 0 as full)."""
    if rect is None or rect.w <= 0 or rect.h <= 0:
        return PARKED
    return (rect.x, rect.y, rect.w, rect.h)


def mask_command(slot: int, key: str, value: int) -> str:
    """One command for the zmq filter: ``TARGET COMMAND ARG``."""
    return f"{mask_filter(slot)} {key} {int(value)}"


def _mask_graph(cfg: RecordingConfig) -> str:
    """[o] original, [bl] heavily blurred copy, [mask] white where hidden;
    the blurred copy is laid over the original only inside the mask."""
    w, h = cfg.rect.w, cfg.rect.h
    sw, sh = max(2, w // BLUR_DOWNSCALE), max(2, h // BLUR_DOWNSCALE)
    radius = max(1, min(2, sw // 2 - 1, sh // 2 - 1))
    boxes = []
    for i, r in enumerate(cfg.masks):
        x, y, bw, bh = mask_box(r)
        boxes.append(f"{mask_filter(i)}=x={x}:y={y}:w={bw}:h={bh}:color=white:t=fill")
    zmq = (f"zmq=bind_address=tcp\\\\://127.0.0.1\\\\:{cfg.mask_port},"
           if cfg.mask_port else "")
    return (f"[0:v]{_video_head(cfg)},split=3[o][b][m];"
            f"[b]scale={sw}:{sh}:flags=area,boxblur={radius}:1,"
            f"scale={w}:{h}:flags=bilinear,format=yuva420p[bl];"
            f"[m]{zmq}format=gray,lut=c0=0,{','.join(boxes)},lut=c0=gt(val\\,127)*255[mask];"
            f"[bl][mask]alphamerge[bm];[o][bm]overlay=format=auto[ov]")


def _video_filter(cfg: RecordingConfig) -> str:
    out_w, out_h = presets.output_size(cfg.rect.w, cfg.rect.h, cfg.preset)
    chain = [] if cfg.masks else [_video_head(cfg)]
    if (out_w, out_h) != (cfg.rect.w, cfg.rect.h):
        chain.append(f"scale={out_w}:{out_h}:flags=bicubic")
    chain.append("format=yuv420p")
    if cfg.masks:
        return _mask_graph(cfg) + ";[ov]" + ",".join(chain) + "[v]"
    return "[0:v]" + ",".join(chain) + "[v]"


def _audio_filters(cfg: RecordingConfig) -> List[str]:
    align = "aresample=48000:async=1000:first_pts=0"
    out, idx, branches = [], 1, []
    if cfg.mic:
        out.append(f"[{idx}:a]{_shift(cfg, True)},{align},"
                   "aformat=channel_layouts=mono,asplit=2[mic][micm]")
        out.append(f"[micm]asetnsamples=n={METER_SAMPLES}:p=0,"
                   "astats=metadata=1:reset=1:measure_perchannel=none:measure_overall=RMS_level,"
                   "ametadata=print:key=lavfi.astats.Overall.RMS_level,anullsink")
        branches.append(("mic", MIC_GAIN))
        idx += 1
    if cfg.computer:
        out.append(f"[{idx}:a]{_shift(cfg, True)},{align},aformat=channel_layouts=mono[pc]")
        branches.append(("pc", COMPUTER_GAIN))
    if not branches:
        return []
    if len(branches) == 2:
        out.append(f"[mic][pc]amix=inputs=2:weights={MIC_GAIN} {COMPUTER_GAIN}"
                   ":normalize=0:duration=longest,alimiter=limit=0.99:level=0[a]")
    else:
        label, gain = branches[0]
        out.append(f"[{label}]volume={gain}[a]")
    return out


def video_codec_args(format_key: str, preset_key: str, fps: int,
                     encoder: Optional[str]) -> List[str]:
    fmt = presets.video_format(format_key)
    cap = presets.video_cap_bps(preset_key, format_key, fps)
    rate = ["-maxrate", str(cap), "-bufsize", str(2 * cap)]
    if encoder and encoder.endswith("_videotoolbox"):     # macOS (D-21)
        from core.recorder import macos
        return macos.encoder_args(encoder, cap)
    if encoder and encoder.endswith("_nvenc"):
        return ["-c:v", encoder, "-preset", "p5", "-rc", "vbr", "-cq", NVENC_CQ[fmt.key],
                "-b:v", "0"] + rate
    # Intel and AMD (Windows): variable rate aiming at two thirds of the cap.
    if encoder and encoder.endswith("_qsv"):
        return ["-c:v", encoder, "-preset", "veryfast", "-b:v", str(cap * 2 // 3)] + rate
    if encoder and encoder.endswith("_amf"):
        return ["-c:v", encoder, "-quality", "speed", "-rc", "vbr_peak",
                "-b:v", str(cap * 2 // 3)] + rate
    return ["-c:v", *fmt.software, *fmt.quality] + rate


def _video_input(cfg: RecordingConfig) -> List[str]:
    if cfg.backend == BACKEND_AVFOUNDATION:
        from core.recorder import macos
        return macos.video_input_args(cfg, VIDEO_QUEUE)
    if cfg.backend == BACKEND_WINDOWS:
        # The desktop at an offset, never a window title: a window capture
        # would miss the highlight and bubble overlays (as on Linux).
        return ["-thread_queue_size", VIDEO_QUEUE, "-f", "gdigrab", "-draw_mouse", "1",
                "-framerate", str(cfg.fps),
                "-offset_x", str(cfg.rect.x), "-offset_y", str(cfg.rect.y),
                "-video_size", f"{cfg.rect.w}x{cfg.rect.h}",
                "-use_wallclock_as_timestamps", "1", "-i", "desktop"]
    return ["-thread_queue_size", VIDEO_QUEUE, "-f", "x11grab", "-draw_mouse", "1",
            "-framerate", str(cfg.fps),
            "-video_size", f"{cfg.rect.w}x{cfg.rect.h}",
            "-i", _display_input(cfg.display, cfg.rect)]


def _audio_input(cfg: RecordingConfig, source: str) -> List[str]:
    if cfg.backend == BACKEND_AVFOUNDATION:
        from core.recorder import macos
        return macos.audio_input_args(source, AUDIO_QUEUE)
    if cfg.backend == BACKEND_WINDOWS:
        return ["-thread_queue_size", AUDIO_QUEUE, "-f", "dshow",
                "-audio_buffer_size", DSHOW_BUFFER_MS,
                "-use_wallclock_as_timestamps", "1", "-i", f"audio={source}"]
    return ["-thread_queue_size", AUDIO_QUEUE, "-f", "pulse",
            "-sample_rate", str(presets.AUDIO_RATE), "-i", source]


def build_record_argv(cfg: RecordingConfig, ffmpeg: str = "ffmpeg") -> List[str]:
    argv = [ffmpeg, "-hide_banner", "-y", "-loglevel", "info",
            "-nostats", "-progress", "pipe:1", "-stats_period", "0.5", "-copyts",
            "-filter_complex_threads", "2"] + _video_input(cfg)
    for source in (cfg.mic, cfg.computer):
        if source:
            argv += _audio_input(cfg, source)
    filters = [_video_filter(cfg)] + _audio_filters(cfg)
    argv += ["-filter_complex", ";".join(filters), "-map", "[v]"]
    if cfg.has_audio:
        argv += ["-map", "[a]"]
    argv += video_codec_args(cfg.video_format, cfg.preset, cfg.fps, cfg.encoder)
    argv += ["-g", str(cfg.fps * 2), "-fps_mode", "cfr", "-r", str(cfg.fps)]
    if cfg.has_audio:
        argv += ["-c:a", "aac", "-b:a", str(presets.AUDIO_BPS),
                 "-ar", str(presets.AUDIO_RATE), "-ac", "1"]
    argv += ["-flush_packets", "1", "-cluster_time_limit", "1000",
             "-f", "matroska", cfg.output]
    return argv


def build_remux_argv(part_path: str, tmp_path: str, ffmpeg: str = "ffmpeg") -> List[str]:
    """Stream copy MKV to a temporary MP4 with the index at the front
    (renamed to the final name only once complete)."""
    return [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", part_path,
            "-map", "0", "-c", "copy", "-movflags", "+faststart", "-f", "mp4", tmp_path]


def build_concat_argv(list_path: str, tmp_path: str, ffmpeg: str = "ffmpeg") -> List[str]:
    """The parts of a paused take joined by stream copy into one temporary
    MP4 (SPEC-REC-001 D-22); same codecs in every part, so no re-encode."""
    return [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
            "-i", list_path, "-map", "0", "-c", "copy", "-movflags", "+faststart",
            "-f", "mp4", tmp_path]


def build_probe_argv(format_key: str, preset_key: str, fps: int, encoder: str,
                     size: Sequence[int] = (1920, 1080), ffmpeg: str = "ffmpeg") -> List[str]:
    """Encode ten frames with the take's real encoder settings at the take's
    output size and rate; exit code 0 = usable here (review R1 F9)."""
    w, h = size
    return [ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
            "-i", f"testsrc2=s={w}x{h}:r={fps}", "-frames:v", "10", "-pix_fmt", "yuv420p",
            *video_codec_args(format_key, preset_key, fps, encoder), "-f", "null", "-"]


def build_list_devices_argv(ffmpeg: str = "ffmpeg") -> List[str]:
    """Windows: ffmpeg names the DirectShow devices on stderr (§4.4)."""
    return [ffmpeg, "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"]


def build_filters_argv(ffmpeg: str = "ffmpeg") -> List[str]:
    """The filters this ffmpeg build has (the privacy blur needs ``zmq``)."""
    return [ffmpeg, "-hide_banner", "-filters"]
