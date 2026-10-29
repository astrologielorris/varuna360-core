# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Output files (SPEC-REC-001 §3.1, INV-3).

A take is written as ``Varuna360_<date>_<time>.part.mkv`` and remuxed to
``Varuna360_<date>_<time>.mp4`` at Stop. A ``.part.mkv`` found at start
belongs to a crashed session and is remuxed the same way.
"""
from __future__ import annotations

import datetime as _dt
import os
import re
from pathlib import Path
from typing import List, Optional

from core.recorder import windows

PREFIX = "Varuna360_"
PART_SUFFIX = ".part.mkv"
FINAL_SUFFIX = ".mp4"
ACTIONS_SUFFIX = ".actions.jsonl"   # the AI action log beside a take (D-23)
LOCK_SUFFIX = ".take.lock"


def default_folder(movies_location: Optional[str] = None) -> str:
    base = movies_location or os.path.join(os.path.expanduser("~"), "Videos")
    return os.path.join(base, "Varuna360")


def stem_for(now: _dt.datetime) -> str:
    return PREFIX + now.strftime("%Y-%m-%d_%H-%M-%S")


def part_path(folder: str, now: _dt.datetime) -> str:
    """A part path RESERVED for this take: created empty with O_EXCL, so two
    takes (two app instances) starting in the same second never share a name
    (review R2 F10). A second take in the same second gets ``_2``."""
    stem = stem_for(now)
    n = 1
    while True:
        name = stem + (f"_{n}" if n > 1 else "")
        candidate = os.path.join(folder, name + PART_SUFFIX)
        if not os.path.exists(final_path_for(candidate)):
            try:
                os.close(os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644))
                return candidate
            except FileExistsError:
                pass
        n += 1


def segment_path(first_part: str, n: int) -> str:
    """Part ``n`` (2, 3...) of a paused take, RESERVED like ``part_path``:
    ``<stem>_seg<n>.part.mkv`` beside the first part. Joined into the first
    part's MP4 at Stop (SPEC-REC-001 D-22)."""
    stem = first_part[: -len(PART_SUFFIX)]
    while True:
        candidate = f"{stem}_seg{n}{PART_SUFFIX}"
        try:
            os.close(os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644))
            return candidate
        except FileExistsError:
            n += 1


_SEG = re.compile(r"_seg(\d+)$")


def take_stem(part: str) -> str:
    """The stem of the take a part belongs to (``_seg<n>`` removed)."""
    return _SEG.sub("", part[: -len(PART_SUFFIX)])


def segment_number(part: str) -> int:
    m = _SEG.search(part[: -len(PART_SUFFIX)])
    return int(m.group(1)) if m else 1


def lock_path(part: str) -> str:
    """Held open by the app for the whole life of a take, pauses included:
    another instance's recovery leaves the take's parts alone while it is."""
    return take_stem(part) + LOCK_SUFFIX


def lock_held(lock: str, held: set) -> bool:
    return os.path.exists(lock) and (os.path.realpath(lock) in held or windows.file_in_use(lock))


def concat_list_path(part: str) -> str:
    """The ffmpeg concat list that joins the parts of a paused take."""
    return part[: -len(PART_SUFFIX)] + ".concat.txt"


def write_concat_list(parts: List[str], list_path: str) -> str:
    """One ``file '<path>'`` line per part (quotes escaped as ffmpeg wants)."""
    with open(list_path, "w", encoding="utf-8") as f:
        for p in parts:
            f.write("file '" + os.path.abspath(p).replace("'", "'\\''") + "'\n")
    return list_path


def action_log_path(video_or_part: str) -> str:
    """The AI action log beside a take (D-23): same stem, ``.actions.jsonl``."""
    for suffix in (PART_SUFFIX, FINAL_SUFFIX, ".mkv"):
        if video_or_part.endswith(suffix):
            return video_or_part[: -len(suffix)] + ACTIONS_SUFFIX
    return os.path.splitext(video_or_part)[0] + ACTIONS_SUFFIX



def prospective_part_path(folder: str, now: _dt.datetime) -> str:
    """The name a take WOULD get, without reserving it (dry runs)."""
    return os.path.join(folder, stem_for(now) + PART_SUFFIX)


def publish(tmp: str, final: str) -> str:
    """Move the finished MP4 to its final name WITHOUT ever overwriting an
    existing file (``os.link`` fails when the name exists, review R3 F3); a
    taken name gets ``_2``, ``_3``... Returns the published path."""
    base, ext = os.path.splitext(final)
    candidate, n = final, 2
    while True:
        try:
            try:
                os.link(tmp, candidate)
            except FileExistsError:
                raise
            except OSError:
                # No hard links on this drive (FAT32/exFAT, a VirtualBox or
                # network share; Windows VM run 2026-10-22 kept every take as
                # MKV): reserve the name with an exclusive create, then
                # replace that empty reservation with the MP4.
                with open(candidate, "xb"):
                    pass
                try:
                    os.replace(tmp, candidate)
                except OSError:
                    _remove_quietly(candidate)
                    raise
            else:
                os.remove(tmp)
            return candidate
        except FileExistsError:
            candidate = f"{base}_{n}{ext}"
            n += 1


def _remove_quietly(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def final_path_for(part: str) -> str:
    assert part.endswith(PART_SUFFIX)
    return part[: -len(PART_SUFFIX)] + FINAL_SUFFIX


TMP_SUFFIX = ".tmp.mp4"
SETTLE_SECONDS = 15.0


def tmp_path_for(part: str) -> str:
    """Where the remux writes before the rename to the final name."""
    return part[: -len(PART_SUFFIX)] + TMP_SUFFIX


def files_open_by_processes(proc_root: str = "/proc") -> set:
    """Every path some process holds open (Linux /proc/*/fd), so a part
    file another ffmpeg is still writing is never touched (review R1 F4)."""
    held = set()
    try:
        pids = [d for d in os.listdir(proc_root) if d.isdigit()]
    except OSError:
        return held
    for pid in pids:
        fd_dir = os.path.join(proc_root, pid, "fd")
        try:
            for fd in os.listdir(fd_dir):
                try:
                    held.add(os.readlink(os.path.join(fd_dir, fd)))
                except OSError:
                    pass
        except OSError:
            pass
    return held


def leftover_parts(folder: str, exclude: Optional[str] = None, now: Optional[float] = None,
                   held: Optional[set] = None) -> List[str]:
    """Part files of crashed takes, oldest first: never the running one, never
    one any process still has open, never one written in the last 15 s."""
    import time
    now = time.time() if now is None else now
    try:
        names = sorted(p for p in Path(folder).glob(PREFIX + "*" + PART_SUFFIX))
    except OSError:
        return []
    held = files_open_by_processes() if held is None else held
    out = []
    for p in names:
        try:
            st = p.stat()
        except OSError:
            continue
        if (str(p) == exclude or st.st_size == 0 or str(p.resolve()) in held
                or now - st.st_mtime < SETTLE_SECONDS or windows.file_in_use(str(p))
                or lock_held(lock_path(str(p)), held)):    # a paused take of a live app
            continue
        out.append(str(p))
    return out


def group_parts(parts: List[str]) -> List[List[str]]:
    """Leftover parts grouped by take, each group in recording order, so a
    paused take that crashed is recovered as ONE video (D-22)."""
    groups: dict = {}
    for p in parts:
        groups.setdefault(take_stem(p), []).append(p)
    return [sorted(g, key=segment_number) for _k, g in sorted(groups.items())]


def human_size(size_bytes: int) -> str:
    mb = size_bytes / 1e6
    return f"{mb:.1f} MB" if mb < 1000 else f"{mb / 1000:.2f} GB"
