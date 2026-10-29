# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Screen recorder lifecycle (SPEC-REC-001 §3.1-§3.3): one ffmpeg process per
take, the snapshot, stop, remux and crash recovery. Main only.

Phases ``idle -> starting -> recording -> finalizing -> idle``. ``recording``
starts at ffmpeg's first written frame (``frame=N`` on the progress pipe).
Pause (D-22) ends the running ffmpeg like Stop and keeps its part file:
``recording -> paused``; Resume starts a new part (``paused -> starting ->
recording``), and Stop joins every part by stream copy into one MP4. Delete
ends the take and moves every part to the trash, no result.
Stop sends ``q`` on stdin, then terminate after 5 s, then kill after 3 s more
(INV-4). The take is Matroska while it runs and becomes an MP4 by stream copy
at the end; a failed remux keeps the MKV as the result (INV-3).

The manager knows nothing about overlays or the blur: the GUI controller
(``apps/recorder/controller.py``) prepares those before ``start`` and removes
them on every phase change away from recording. One manager per main window,
found with ``for_gui(gui)``; ChartGUI gains no attribute (Rule 4b).
"""
from __future__ import annotations

import dataclasses
import os
import re
import time
import weakref
from dataclasses import dataclass, field, replace
from typing import Callable, List, Optional

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from core.recorder import levels, launcher, output, windows, zmtp
from core.recorder.ffmpeg_command import (RecordingConfig, build_concat_argv, build_record_argv,
                                         build_remux_argv, mask_box, mask_command)
from core.recorder.region import Rect, union

IDLE, STARTING, RECORDING, FINALIZING = "idle", "starting", "recording", "finalizing"
PAUSED = "paused"
Q_GRACE_MS = 5000
TERM_GRACE_MS = 3000
MASK_SETTLE_MS = 250               # a moved box shrinks back once the screen settled
START_TIMEOUT_MS = 10000
TAIL_LINES = 40

# Draft wording (orchestrator draft, for Lorris's review).
TEXT = {
    "FFMPEG_MISSING": "ffmpeg could not be started.",
    "NO_FRAMES": "ffmpeg stopped before recording anything.",
    "START_TIMEOUT": "The screen capture did not start within 10 seconds.",
    "DISK_FULL": "The disk is full: what was recorded before is kept.",
    "FFMPEG_ERROR": "ffmpeg stopped with an error.",
    "kept_mkv": "kept as MKV (the MP4 conversion failed)",
    "kept_parts": "kept as {n} MKV parts (joining them failed)",
    "recovered": "recovered after the app closed during a take",
    "privacy_stop": "stopped early to protect privacy: {reason}",
    "unbound": "note: ffmpeg could not be tied to the app; if the app crashes, end ffmpeg in Task Manager",
}


@dataclass(frozen=True)
class Saved:
    path: str
    size_bytes: int
    seconds: float
    note: str = ""

    def to_dict(self):
        return {"kind": "saved", "path": self.path, "size_bytes": self.size_bytes,
                "seconds": round(self.seconds, 1), "note": self.note}


@dataclass(frozen=True)
class Failed:
    code: str
    message: str
    path: str = ""               # what was recorded before the failure, kept (INV-3)
    size_bytes: int = 0

    def to_dict(self):
        d = {"kind": "failed", "code": self.code, "message": self.message}
        if self.path:
            d.update(path=self.path, size_bytes=self.size_bytes)
        return d


def result_from_dict(d) -> Optional[object]:
    if not isinstance(d, dict):
        return None
    if d.get("kind") == "saved" and d.get("path"):
        return Saved(d["path"], int(d.get("size_bytes") or 0), float(d.get("seconds") or 0),
                     d.get("note") or "")
    if d.get("kind") == "failed":
        return Failed(d.get("code") or "FFMPEG_ERROR", d.get("message") or "",
                      d.get("path") or "", int(d.get("size_bytes") or 0))
    return None


@dataclass
class RecorderSnapshot:
    phase: str = IDLE
    started_at: Optional[float] = None
    output_path: Optional[str] = None
    carried: float = 0.0              # seconds recorded by the earlier parts (pause, D-22)
    last_result: Optional[object] = None
    log_tail: List[str] = field(default_factory=list)

    @property
    def elapsed(self) -> float:
        running = 0.0 if self.started_at is None else max(0.0, time.monotonic() - self.started_at)
        return self.carried + running


class ScreenRecorderManager(QObject):
    snapshot_changed = Signal(object)        # RecorderSnapshot
    capture_ended = Signal()                 # ffmpeg exited: no more frames can be taken
    level_changed = Signal(float)            # momentary loudness
    quiet_changed = Signal(bool)             # "the microphone hears no voice"

    def __init__(self, ffmpeg: Optional[str] = None,
                 persist: Optional[Callable[[dict], None]] = None, parent=None):
        super().__init__(parent)
        self._ffmpeg_fixed = ffmpeg            # None: found again at each take (encoders.ffmpeg_path)
        self._persist = persist
        self.snapshot = RecorderSnapshot()
        self._proc: Optional[QProcess] = None
        self._remux: Optional[QProcess] = None
        self._pending_remux: List[tuple] = []      # (part, note, seconds)
        self._out_buf = b""
        self._err_buf = b""
        self._watch_mic = False
        self._quiet = False
        self._watch = levels.QuietWatch()
        self._levels = levels.LevelParser()
        self._cfg: Optional[RecordingConfig] = None
        self._fallback_used = False
        self._cancelled = False                  # Stop was asked for this take (review R2 F2)
        self._stop_timer = QTimer(self, singleShot=True)
        self._stop_timer.timeout.connect(self._escalate)
        self._start_timer = QTimer(self, singleShot=True)
        self._start_timer.timeout.connect(self._start_timed_out)
        self._escalated = False
        self._start_failure: Optional[Failed] = None
        # Pause and delete (D-22): the closed parts of this take, in order;
        # the video seconds they hold (wall clock from each part's t0).
        self._segments: List[str] = []
        self._video_carried = 0.0
        self._had_frames = False
        self._anchor: Optional[float] = None    # wall time of this part's first frame
        self._pausing = False
        self._deleting = False
        self._resume_wanted = False
        self._lock = None                       # held open for the take's life
        self._part_carried = 0.0                # video seconds before the running part
        self._last_out = None                   # last out_time of the running part (s)
        # Video-only privacy boxes (INV-7): where each box should be, and
        # where ffmpeg was last told it is.
        self._mask_target: List[Optional[Rect]] = []
        self._mask_prev: List[Optional[Rect]] = []
        self._mask_shown: List[Optional[Rect]] = []      # acknowledged by the channel write
        self._channel = None
        self._stop_note = ""
        self._mask_settle = QTimer(self, singleShot=True)
        self._mask_settle.timeout.connect(self._settle_masks)

    # ------------------------------------------------------------ state

    @property
    def _ffmpeg(self) -> str:
        if self._ffmpeg_fixed:
            return self._ffmpeg_fixed
        from core.recorder.encoders import ffmpeg_program
        return ffmpeg_program()

    @property
    def phase(self) -> str:
        return self.snapshot.phase

    @property
    def busy(self) -> bool:
        return self.phase != IDLE or self._remux is not None

    def set_persist(self, persist: Optional[Callable[[dict], None]]) -> None:
        """Where each new last result is saved (the recorder state file)."""
        self._persist = persist

    def set_last_result(self, result) -> None:
        """Restore the result remembered from an earlier session."""
        self.snapshot.last_result = result

    def report_failure(self, result: Failed) -> None:
        """A failure found before ffmpeg ran (name reservation): saved and
        announced like any other result (review R4 F4)."""
        self._set(last_result=result)

    def _take_lock(self, part: str) -> None:
        self._release_lock()
        try:
            self._lock = open(output.lock_path(part), "w")
            self._lock.write(str(os.getpid()))
            self._lock.flush()
        except OSError:
            self._lock = None

    def _release_lock(self) -> None:
        fh, self._lock = self._lock, None
        if fh is not None:
            try:
                fh.close()
            except OSError:
                pass
            _discard(fh.name)

    def _set(self, **changes) -> None:
        self.snapshot = dataclasses.replace(self.snapshot, **changes)   # no dynamic setattr (Rule 4b census)
        if changes.get("phase") == IDLE and not self._pending_remux_of_take():
            self._release_lock()
        if "last_result" in changes and self._persist and changes["last_result"] is not None:
            try:
                self._persist(changes["last_result"].to_dict())
            except Exception:                       # a settings write never breaks a take
                pass
        self.snapshot_changed.emit(self.snapshot)

    # ------------------------------------------------------------ start

    def start(self, cfg: RecordingConfig, _retry: bool = False, _resume: bool = False) -> bool:
        if self.busy and not (_retry or _resume):
            return False
        if _retry or _resume:              # the boxes where they are NOW
            cfg = replace(cfg, masks=tuple(self._mask_target))
        if cfg.masks:                      # a fresh port for the zmq filter
            cfg = replace(cfg, mask_port=zmtp.free_port())
        targets = list(cfg.masks)
        if cfg.masks:
            # Until the filter line is up, box 0 covers the WHOLE frame: a
            # move during ffmpeg's start-up can then show nothing (review
            # v0.4 R2 F1). The real places are applied on the handshake.
            full = Rect(0, 0, cfg.rect.w, cfg.rect.h)
            cfg = replace(cfg, masks=(full,) + tuple(cfg.masks[1:]))
        self._cfg = cfg
        if not _retry:
            self._fallback_used = False
            self._cancelled = False
        if not (_retry or _resume):        # a new take: no earlier parts
            self._segments = []
            self._video_carried = 0.0
            self._deleting = False
            self._resume_wanted = False
            self.snapshot.carried = 0.0
            self._take_lock(cfg.output)
        self._part_carried = self._video_carried
        self._last_out = None
        self._had_frames = False
        self._anchor = None
        self._pausing = False
        self._mask_target = targets
        self._mask_prev = list(targets)
        self._mask_shown = list(cfg.masks)
        self._stop_note = ""
        self._mask_settle.stop()
        self._close_channel()
        os.makedirs(os.path.dirname(cfg.output) or ".", exist_ok=True)
        self._out_buf = self._err_buf = b""
        self._escalated = False
        self._start_failure = None
        self._watch = levels.QuietWatch()
        self._levels = levels.LevelParser()
        self._watch_mic = bool(cfg.mic)
        self._quiet = False
        self.snapshot.log_tail = []
        proc = QProcess(self)
        argv = launcher.wrap(build_record_argv(cfg, self._ffmpeg))
        proc.setProgram(argv[0])
        proc.setArguments(argv[1:])
        proc.readyReadStandardOutput.connect(self._read_out)
        proc.readyReadStandardError.connect(self._read_err)
        proc.finished.connect(self._finished)
        proc.errorOccurred.connect(self._error)
        self._proc = proc
        self.snapshot.output_path = cfg.output
        proc.start()                       # launched BEFORE anyone hears STARTING (R3 F2)
        if self._proc is not proc:
            return False                   # failed to start (handled in _error)
        if windows.IS_WINDOWS and not windows.bind_to_app(proc.processId()):
            # Windows: ffmpeg dies with the app (INV-4); say so when it cannot be bound.
            self.snapshot.log_tail = self.snapshot.log_tail + [TEXT["unbound"]]
        if cfg.mask_port:
            self._open_channel(cfg.mask_port)
        self._set(phase=STARTING, started_at=None, output_path=cfg.output)
        if self._proc is proc:
            self._start_timer.start(START_TIMEOUT_MS)
        return True

    def _error(self, err) -> None:
        if err == QProcess.ProcessError.FailedToStart and self._proc is not None:
            # Retire the process object and the empty reserved part, as
            # _finished does: each failed start left both behind (review
            # 2026-10-23: four failed starts, four live QProcess children).
            proc, self._proc = self._proc, None
            proc.deleteLater()
            _discard(self.snapshot.output_path)
            self._close_channel()
            self.capture_ended.emit()
            self._start_timer.stop()
            failure = Failed("FFMPEG_MISSING", TEXT["FFMPEG_MISSING"])
            parts, self._segments = self._segments, []
            if parts:                      # a resume that failed: the paused parts stay
                self._set(phase=FINALIZING)
                self._queue_remux(parts[0], "", self.snapshot.elapsed, failure=failure, parts=parts)
                return
            self._set(phase=IDLE, started_at=None, output_path=None, carried=0.0,
                      last_result=failure)

    def _start_timed_out(self) -> None:
        if self.phase == STARTING:
            self._start_failure = Failed("START_TIMEOUT", TEXT["START_TIMEOUT"])
            self.stop()

    # ------------------------------------------------------------ output parsing

    def _read_out(self) -> None:
        if self._proc is None:
            return
        self._out_buf += bytes(self._proc.readAllStandardOutput())
        *lines, self._out_buf = self._out_buf.split(b"\n")
        for raw in lines:
            line = raw.decode(errors="replace").strip()
            if line.startswith("out_time_us="):
                try:
                    self._last_out = int(line[12:]) / 1e6
                except ValueError:
                    pass
                continue
            if line.startswith("frame="):
                try:
                    frames = int(line[6:])
                except ValueError:
                    continue
                if frames > 0 and self.phase == STARTING:
                    self._start_timer.stop()
                    self._had_frames = True
                    if self._anchor is None:     # ffmpeg never named its start
                        self._anchor = time.time()
                    self._set(phase=RECORDING, started_at=time.monotonic())

    def _read_err(self) -> None:
        if self._proc is None:
            return
        self._err_buf += bytes(self._proc.readAllStandardError())
        *lines, self._err_buf = self._err_buf.split(b"\n")
        for raw in lines:
            line = raw.decode(errors="replace").rstrip()
            if levels.LevelParser.is_meter_line(line):
                got = self._levels.feed(line)
                if got is None:
                    continue
            else:
                if line:
                    self.snapshot.log_tail = (self.snapshot.log_tail + [line])[-TAIL_LINES:]
                    self._read_anchor(line)
                continue
            t, level = got
            self.level_changed.emit(level)
            if self._watch_mic:
                self._watch.feed(t, level)
                if self._watch.quiet != self._quiet:
                    self._quiet = self._watch.quiet
                    self.quiet_changed.emit(self._quiet)

    # ------------------------------------------------------------ stop

    # ------------------------------------------------------------ privacy boxes

    def set_mask(self, slot: int, rect: Optional[Rect]) -> None:
        """Move privacy box ``slot`` (capture pixels, None = nothing to hide).
        A move first GROWS the box over the old place, the new place and one
        more step in the same direction (the window is often still moving),
        then shrinks to the new place once the target has been still for
        MASK_SETTLE_MS. An unchanged target changes nothing (review v0.4 F4)."""
        if not 0 <= slot < len(self._mask_target):
            return
        if rect == self._mask_target[slot]:
            return
        self._mask_prev[slot] = self._mask_target[slot]
        self._mask_target[slot] = rect
        self._apply_mask(slot)

    def _apply_mask(self, slot: int) -> None:
        target, cur = self._mask_target[slot], self._mask_shown[slot]
        if cur == target:
            return
        if cur is None or target is None:
            self._send_box(slot, target, grow=True)
            return
        cover = union(cur, target)
        prev = self._mask_prev[slot]
        if prev is not None and (prev.w, prev.h) == (target.w, target.h):
            dx, dy = target.x - prev.x, target.y - prev.y
            cover = union(cover, Rect(target.x + dx, target.y + dy, target.w, target.h))
        if cover != cur:
            self._send_box(slot, cover, grow=True)
        self._mask_settle.start(MASK_SETTLE_MS)

    def _settle_masks(self) -> None:
        for slot, target in enumerate(self._mask_target):
            if self._mask_shown[slot] != target:
                self._send_box(slot, target, grow=False)

    def _send_box(self, slot: int, rect: Optional[Rect], grow: bool) -> None:
        """All four values in one write: the filter applies every waiting
        command before its next frame. Kept ordered so a split write still
        never uncovers the old place. Allowed until ffmpeg has exited (the
        capture goes on while it finalizes, review v0.4 F3)."""
        if self._proc is None or self._channel is None:
            return
        x, y, w, h = mask_box(rect)
        values = {"x": x, "y": y, "w": w, "h": h}
        order = ("w", "h", "x", "y") if grow else ("x", "y", "w", "h")
        if self._channel.send(mask_command(slot, k, values[k]) for k in order):
            self._mask_shown[slot] = rect
        # not connected yet: _channel_ready resends what is still off target

    def _open_channel(self, port: int) -> None:
        from managers.recorder_mask_channel import MaskChannel
        self._channel = MaskChannel(self)
        self._channel.ready.connect(self._channel_ready)
        self._channel.failed.connect(self._channel_failed)
        self._channel.start(port)

    def _channel_ready(self) -> None:
        """The real places, straight from the full-frame start box: every
        waiting command is applied before the next frame."""
        for slot, target in enumerate(self._mask_target):
            if self._mask_shown[slot] != target:
                self._send_box(slot, target, grow=False)

    def _channel_failed(self, reason: str) -> None:
        """The boxes can no longer follow the screen: end the take now and
        keep what was recorded (privacy first)."""
        if self._proc is None or self.phase not in (STARTING, RECORDING):
            return                         # ffmpeg is ending anyway: its exit closed the line
        self._stop_note = TEXT["privacy_stop"].format(reason=reason)
        self.stop()

    def _close_channel(self) -> None:
        ch, self._channel = self._channel, None
        if ch is not None:
            ch.close()
            ch.deleteLater()

    def _read_anchor(self, line: str) -> None:
        """``Input #0, x11grab, from ...: Duration: N/A, start: 1761300000.12``:
        every input is stamped with the wall clock, so ``start`` is the wall
        time of the first captured frame. The finished MP4 begins at that
        frame (the start-up gap of each part is dropped), so it anchors the
        action log's clock."""
        if self._anchor is not None or self._cfg is None:
            return
        m = _START.search(line)
        if m:
            value = float(m.group(1))
            if abs(value - (self._cfg.t0 or time.time())) < 60:
                self._anchor = value

    def _settle_part_clock(self) -> None:
        """The closed part runs until ffmpeg handled ``q``, a little after the
        Pause click: its real length is its last output time minus its first
        frame's (both on the ``t0`` origin)."""
        if self._last_out is None or self._anchor is None or self._cfg is None:
            return
        length = self._last_out - (self._anchor - self._cfg.t0)
        if 0 <= length < 24 * 3600:
            self._video_carried = self._part_carried + length

    def video_time(self) -> float:
        """Seconds into the finished video NOW (the action log's clock, D-23):
        the earlier parts plus this part's time since its first frame."""
        if self.phase in (STARTING, RECORDING) and self._anchor is not None:
            return self._video_carried + max(0.0, time.time() - self._anchor)
        return self._video_carried

    def pause(self) -> bool:
        """End the running part like Stop and keep it (D-22); only while
        frames are being recorded."""
        if self._proc is None or self.phase != RECORDING:
            return False
        self._video_carried = self.video_time()
        self._pausing = True
        self._cancelled = True              # no software retry, our own end
        self._set(phase=PAUSED, carried=self.snapshot.elapsed, started_at=None)
        self._send_q()
        return True

    def resume(self) -> bool:
        """A new part after a pause, with the same settings and the privacy
        boxes where they are now."""
        if self.phase == PAUSED and self._proc is not None and self._pausing:
            self._resume_wanted = True       # the paused part is still closing
            return True
        if self.phase != PAUSED or self._proc is not None or not self._segments:
            return False
        try:
            seg = output.segment_path(self._segments[0], len(self._segments) + 1)
        except OSError:
            self.stop()                     # keep what was recorded
            return False
        cfg = replace(self._cfg, output=seg, t0=time.time())
        if not self.start(cfg, _resume=True):
            _discard(seg)
            return False
        return True

    def delete(self) -> bool:
        """End the take and move every part to the trash; no result (D-22).
        The last result shown in the dialog stays the previous one."""
        if self.phase not in (STARTING, RECORDING, PAUSED) or self._deleting:
            return False
        self._deleting = True
        self._start_timer.stop()
        if self._proc is None:
            self._finish_delete(None)
            return True
        self._cancelled = True
        self._pausing = False
        self._set(phase=FINALIZING)
        self._send_q()
        return True

    def _finish_delete(self, part: Optional[str]) -> None:
        for p in self._segments + ([part] if part else []):
            _trash(p)
        self._segments = []
        self._video_carried = 0.0
        self._deleting = False
        self.capture_ended.emit()
        self._set(phase=IDLE, started_at=None, output_path=None, carried=0.0)

    def _send_q(self) -> None:
        try:
            self._proc.write(b"q")
            self._proc.closeWriteChannel()
        except RuntimeError:
            pass
        self._stop_timer.start(Q_GRACE_MS)

    def stop(self) -> None:
        """Stop the take, also while it is still starting or paused;
        harmless when nothing runs (INV-4)."""
        if self.phase == PAUSED:
            self._cancelled = True
            if self._proc is not None:      # the paused part is still closing
                self._pausing = False       # _finished joins the parts
                self._set(phase=FINALIZING)
                return
            self._set(phase=FINALIZING)
            self.capture_ended.emit()
            parts = list(self._segments)
            self._segments = []
            self._queue_remux(parts[0], self._stop_note, self.snapshot.elapsed, parts=parts)
            return
        if self._proc is None or self.phase not in (STARTING, RECORDING):
            return
        self._start_timer.stop()
        self._cancelled = True
        self._video_carried = self.video_time()   # the log's clock stops with the take
        self._set(phase=FINALIZING)
        self._send_q()

    def _escalate(self) -> None:
        if self._proc is None:
            return
        if not self._escalated:
            self._escalated = True
            if windows.IS_WINDOWS:         # terminate() cannot stop a console program there
                self._proc.kill()
                return
            self._proc.terminate()
            self._stop_timer.start(TERM_GRACE_MS)
        else:
            self._proc.kill()

    def _finished(self, code, status) -> None:
        if self._proc is not None:
            self._read_out()                # the last progress lines (out_time)
        proc, self._proc = self._proc, None
        if proc is None:
            return
        self._close_channel()
        self._stop_timer.stop()
        self._start_timer.stop()
        self._read_tail(proc)
        seconds = self.snapshot.elapsed
        part = self.snapshot.output_path
        had_frames = self._had_frames
        if self._deleting:
            proc.deleteLater()
            self._finish_delete(part)
            return
        pausing = self._pausing and self.phase == PAUSED
        self._pausing = False
        if self.phase not in (FINALIZING, PAUSED):
            self._set(phase=FINALIZING)
        proc.deleteLater()
        size = _size(part)
        if (not had_frames and self._cfg is not None and self._cfg.encoder
                and not self._fallback_used and self._start_failure is None
                and not self._cancelled and not self._segments):
            # (never for a resumed part: its codec must match the first parts'
            # for the stream-copy join)
            # The GPU encoder passed the probe but refused the real take:
            # try once more with the software encoder (review R1 F9).
            from dataclasses import replace
            self._fallback_used = True      # same reserved part file (R3 F3)
            self.start(replace(self._cfg, encoder=None), _retry=True)
            return
        kept = had_frames and size > 0
        failure = None
        if kept and self._disk_full():
            failure = Failed("DISK_FULL", TEXT["DISK_FULL"])
        elif kept and self._genuine_failure(code, status):
            failure = self._failure_from_log(code, True)      # review R2 F11, R3 F4
        if pausing and kept and failure is None:
            self._segments.append(part)     # paused: no capture_ended, overlays stay
            self._settle_part_clock()
            self._set(output_path=None)
            if self._resume_wanted:
                self._resume_wanted = False
                QTimer.singleShot(0, self.resume)
            return
        if self.phase == PAUSED:
            self._set(phase=FINALIZING)
        self.capture_ended.emit()
        parts = self._segments + ([part] if kept else [])
        self._segments = []
        if not kept:
            _discard(part)
        if not parts:
            failure = self._start_failure or self._failure_from_log(code, had_frames)
            self._set(phase=IDLE, started_at=None, output_path=None, carried=0.0,
                      last_result=failure)
            return
        if not kept and (not self._cancelled or self._start_failure):   # a resumed part that never started
            failure = self._start_failure or self._failure_from_log(code, had_frames)
        self._queue_remux(parts[0], self._stop_note, seconds, failure=failure, parts=parts)

    def _read_tail(self, proc) -> None:
        try:
            rest = bytes(proc.readAllStandardError())
        except RuntimeError:
            rest = b""
        for raw in (self._err_buf + rest).split(b"\n"):
            line = raw.decode(errors="replace").rstrip()
            if line and not levels.LevelParser.is_meter_line(line):
                self.snapshot.log_tail = (self.snapshot.log_tail + [line])[-TAIL_LINES:]
        self._err_buf = b""

    def _genuine_failure(self, code, status) -> bool:
        """A failure of the capture itself. Ending on its own is one; after
        Stop, a non-zero exit is one too unless WE forced it (terminate/kill),
        and a muxer or I/O error in the log always is."""
        if any(("Error writing trailer" in l or "Input/output error" in l)
               for l in self._diagnostics()):
            return True
        if not self._cancelled:
            return code != 0 or status != QProcess.ExitStatus.NormalExit
        return not self._escalated and (code != 0 or status != QProcess.ExitStatus.NormalExit)

    def _diagnostics(self):
        """The log lines that can carry a diagnostic. ffmpeg names the output
        in informational ``Output #0 ... to '...'`` lines, and a folder may be
        called "Error writing trailer" or hold an apostrophe: those header
        lines are skipped and the take's own path is blanked wherever it
        appears, without relying on balanced quotes (review R4 F1, R5)."""
        path = self._cfg.output if self._cfg is not None else ""
        names = [n for n in (path, os.path.dirname(path)) if n]
        out = []
        for line in self.snapshot.log_tail:
            if _HEADER.match(line):
                continue
            for n in names:
                line = line.replace(n, "<output>")
            out.append(line)
        return out

    def _disk_full(self) -> bool:
        return any("No space left" in l for l in self._diagnostics())

    def _failure_from_log(self, code, had_frames) -> Failed:
        if self._disk_full():
            return Failed("DISK_FULL", TEXT["DISK_FULL"])
        if code == launcher.EXEC_FAILED and not had_frames:
            return Failed("FFMPEG_MISSING", TEXT["FFMPEG_MISSING"])
        last = next((l for l in reversed(self.snapshot.log_tail)
                     if "rror" in l or "nvalid" in l or "annot" in l), "")
        if not had_frames:
            return Failed("NO_FRAMES", (TEXT["NO_FRAMES"] + (" " + last if last else "")).strip())
        return Failed("FFMPEG_ERROR", (TEXT["FFMPEG_ERROR"] + (" " + last if last else "")).strip())

    # ------------------------------------------------------------ remux

    def recover(self, folder: str) -> int:
        """Remux every part file a crashed session left in ``folder``."""
        mine = set(self._segments) | {self.snapshot.output_path}
        queued = {p for q in self._pending_remux for p in (q[5] or [q[0]])}
        parts = [p for p in output.leftover_parts(folder, exclude=self.snapshot.output_path)
                 if p not in mine and p not in queued]
        groups = output.group_parts(parts)
        for g in groups:                    # a paused take's parts become one video
            self._queue_remux(g[0], TEXT["recovered"], 0.0, finishing_take=False, parts=g)
        return len(groups)

    def _pending_remux_of_take(self) -> bool:
        return any(q[3] for q in self._pending_remux)

    def _queue_remux(self, part, note, seconds, finishing_take=True, failure=None,
                     parts=None) -> None:
        parts = list(parts) if parts and len(parts) > 1 else None
        self._pending_remux.append((part, note, seconds, finishing_take, failure, parts))
        if self._remux is None:
            self._next_remux()

    def _next_remux(self) -> None:
        if not self._pending_remux:
            return
        part, parts = self._pending_remux[0][0], self._pending_remux[0][5]
        proc = QProcess(self)
        proc.setProgram(self._ffmpeg)
        if parts:                          # a paused take: join the parts (D-22)
            try:
                listing = output.write_concat_list(parts, output.concat_list_path(part))
            except OSError:
                listing = None
            argv = (build_concat_argv(listing, output.tmp_path_for(part), self._ffmpeg)
                    if listing else [self._ffmpeg, "-version"])   # cannot join: keep the parts
        else:
            argv = build_remux_argv(part, output.tmp_path_for(part), self._ffmpeg)
        proc.setArguments(argv[1:])
        proc.finished.connect(lambda c, s, p=proc: self._remux_done(p, c == 0 and s == QProcess.ExitStatus.NormalExit))
        proc.errorOccurred.connect(lambda e, p=proc: e == QProcess.ProcessError.FailedToStart and self._remux_done(p, False))
        self._remux = proc
        proc.start()

    def _remux_done(self, proc, ok) -> None:
        if proc is not self._remux:
            return
        self._remux = None
        proc.deleteLater()
        part, note, seconds, finishing, failure, parts = self._pending_remux.pop(0)
        if parts:
            _discard(output.concat_list_path(part))
            ok = ok and _size(output.tmp_path_for(part)) > 0
        self._complete(part, note, seconds, finishing, ok, failure, parts)
        self._next_remux()

    def _complete(self, part, note, seconds, finishing, ok, failure=None, parts=None) -> None:
        final, tmp = output.final_path_for(part), output.tmp_path_for(part)
        if ok and _size(tmp) > 0:
            try:
                final = output.publish(tmp, final)    # never overwrites (R3 F3)
            except OSError:
                ok = False
        if ok and _size(final) > 0:
            for p in parts or [part]:
                _discard(p)
            result = Saved(final, _size(final), seconds, note)
        else:
            _discard(tmp)
            kept = TEXT["kept_parts"].format(n=len(parts)) if parts else TEXT["kept_mkv"]
            result = Saved(part, sum(_size(p) for p in parts or [part]), seconds,
                           "; ".join(x for x in (note, kept) if x))
        if failure is not None:                 # keep the partial take with the failure
            result = Failed(failure.code, failure.message, result.path, result.size_bytes)
        if finishing:
            self._set(phase=IDLE, started_at=None, output_path=None, carried=0.0,
                      last_result=result)
        else:
            self._set(last_result=result)

    # ------------------------------------------------------------ app close

    def stop_and_wait(self, timeout_s: float = 10.0) -> None:
        """Synchronous end for app close: stop, wait, remux in-line."""
        self._cancelled = True                   # never a software retry from here
        while self._proc is not None:            # every capture process, retries included
            self.stop()
            proc = self._proc
            if not proc.waitForFinished(int(Q_GRACE_MS)):
                self._escalated = True           # our own terminate, not a failure (R4 F2)
                proc.terminate()
                if not proc.waitForFinished(int(TERM_GRACE_MS)):
                    proc.kill()
                    proc.waitForFinished(1000)
            if self._proc is proc:               # finished never arrived: drop it
                self._proc = None
                self._close_channel()
                self.capture_ended.emit()
            # _finished ran (signal is direct for waitForFinished) and queued a remux
        if self.phase == PAUSED:                 # paused: join the parts now
            self.stop()
        deadline = time.monotonic() + timeout_s
        while self._remux is not None and time.monotonic() < deadline:
            # finished is emitted from inside waitForFinished: _remux_done
            # runs and starts the next queued remux, if any.
            self._remux.waitForFinished(int(max(0.5, deadline - time.monotonic()) * 1000))
        if self._remux is not None:
            # Too slow for app close: stop converting; the part file stays and
            # the next start recovers it (INV-3).
            proc, self._remux = self._remux, None
            proc.kill()
            proc.waitForFinished(1000)
            for part, *_rest in self._pending_remux:
                _discard(output.tmp_path_for(part))
                _discard(output.concat_list_path(part))
            self._pending_remux.clear()
            self._set(phase=IDLE, started_at=None, output_path=None)


_HEADER = re.compile(r"\s*(Input|Output) #\d+, ")
_START = re.compile(r"start: (\d{9,}\.\d+)")


def _size(path: Optional[str]) -> int:
    try:
        return os.path.getsize(path) if path else 0
    except OSError:
        return 0


def _trash(path: Optional[str]) -> None:
    """Delete (D-22): the system trash when there is one, so a take deleted
    by mistake can still be brought back; removed otherwise."""
    if not path or not os.path.exists(path):
        return
    from PySide6.QtCore import QFile
    try:
        if QFile.moveToTrash(path):
            return
    except Exception:
        pass
    _discard(path)


def _discard(path: Optional[str]) -> None:
    """Remove the app's own intermediate file (an empty or converted part)."""
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


_MANAGERS: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def for_gui(gui, **kwargs) -> ScreenRecorderManager:
    mgr = _MANAGERS.get(gui)
    if mgr is None:
        mgr = ScreenRecorderManager(parent=gui, **kwargs)
        _MANAGERS[gui] = mgr
    return mgr
