# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The few bytes of ZeroMQ's wire protocol (ZMTP 3.0, NULL security) needed
to talk to ffmpeg's ``zmq`` filter, without the pyzmq library.

Why not ffmpeg's stdin ``c`` command: ffmpeg 6.1 looks at the keyboard at
most every 100 ms and takes one command each time, so a box move (four
commands) lagged 400 ms and names showed in the video (review v0.4 F1-F3).
The zmq filter reads every waiting message on each frame.

We are a DEALER peer: several requests may be in flight; the filter's REP
socket answers each in order ("0 Success"). Each request is an empty
delimiter frame followed by the command text.
"""
from __future__ import annotations

import socket
import struct
from typing import List, Tuple

GREETING_SIZE = 64
SOCKET_TYPE = b"DEALER"
_MORE, _LONG, _COMMAND = 0x01, 0x02, 0x04


def greeting() -> bytes:
    """Signature, version 3.0, NULL mechanism, as-server 0, filler."""
    return (b"\xff" + b"\x00" * 8 + b"\x7f" + bytes([3, 0]) + b"NULL".ljust(20, b"\x00")
            + b"\x00" + b"\x00" * 31)


def _frame(body: bytes, more: bool = False, command: bool = False) -> bytes:
    flags = (_MORE if more else 0) | (_COMMAND if command else 0)
    if len(body) > 255:
        return bytes([flags | _LONG]) + struct.pack(">Q", len(body)) + body
    return bytes([flags, len(body)]) + body


def ready_command(socket_type: bytes = SOCKET_TYPE) -> bytes:
    body = (b"\x05READY" + bytes([len(b"Socket-Type")]) + b"Socket-Type"
            + struct.pack(">I", len(socket_type)) + socket_type)
    return _frame(body, command=True)


def request(text: str) -> bytes:
    """One request: the empty delimiter, then the command text."""
    return _frame(b"", more=True) + _frame(text.encode())


class Reader:
    """Feed received bytes; returns the parts completed so far as
    ("greeting", bytes) / ("command", body) / ("message", [frames])."""

    def __init__(self):
        self._buf = b""
        self._greeted = False
        self._parts: List[bytes] = []

    def feed(self, data: bytes) -> List[Tuple[str, object]]:
        self._buf += data
        out: List[Tuple[str, object]] = []
        if not self._greeted:
            if len(self._buf) < GREETING_SIZE:
                return out
            out.append(("greeting", self._buf[:GREETING_SIZE]))
            self._buf = self._buf[GREETING_SIZE:]
            self._greeted = True
        while len(self._buf) >= 2:
            flags = self._buf[0]
            if flags & _LONG:
                if len(self._buf) < 9:
                    break
                size, head = struct.unpack(">Q", self._buf[1:9])[0], 9
            else:
                size, head = self._buf[1], 2
            if len(self._buf) < head + size:
                break
            body = self._buf[head:head + size]
            self._buf = self._buf[head + size:]
            if flags & _COMMAND:
                out.append(("command", body))
                continue
            self._parts.append(body)
            if not flags & _MORE:
                out.append(("message", self._parts))
                self._parts = []
        return out


def valid_greeting(data: bytes) -> bool:
    """ZMTP 3.x signature, NULL mechanism."""
    return (len(data) == GREETING_SIZE and data[0] == 0xFF and data[9] == 0x7F
            and data[10] >= 3 and data[12:32].rstrip(b"\x00") == b"NULL")


def parse_command(body: bytes):
    """(name, {property: value}) of a command frame; ("", {}) when garbled."""
    try:
        n = body[0]
        if len(body) < 1 + n:
            return "", {}
        name = body[1:1 + n].decode("ascii")
        props, i = {}, 1 + n
        if name != "READY":
            return name, props
        while i < len(body):
            k = body[i]
            key = body[i + 1:i + 1 + k]
            i += 1 + k
            vlen = struct.unpack(">I", body[i:i + 4])[0]
            if len(body) < i + 4 + vlen:
                return "", {}
            props[key] = body[i + 4:i + 4 + vlen]
            i += 4 + vlen
        return name, props
    except (IndexError, UnicodeDecodeError, struct.error):
        return "", {}


def free_port() -> int:
    """A free local TCP port for the filter to bind (tiny race, acceptable:
    a taken port fails the take at start, before any frame)."""
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()
