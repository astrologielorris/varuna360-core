# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Sending one request to a running app (SPEC-SET-003 §4.5b). Standard library
only (no Qt), so ``settings.py`` and the Codex task server stay Qt-free.

Wire format, one JSON object per line (UTF-8, ``\\n`` terminated)::

    request  {"v": 1, "token": "...", "id": "...", "op": "set_app_setting", ...}
    reply    {"v": 1, "id": "...", "status": "...", ...}

``send`` returns the reply for every status except ``refused``, and raises a
typed ``EndpointError`` otherwise, whose ``code`` is one of:

- ``no_app``    nothing listens at the endpoint, or the app closed the
                connection before replying (the target is gone: refused,
                never retried elsewhere, D-18);
- ``timeout``   no reply within the timeout (10 s by default);
- ``bad_token`` the app refused the token;
- ``refused``   the app refused the request (``reason``: ``unknown_op``,
                ``unavailable``, ``bad_request``...; ``reply`` holds it all);
- ``bad_reply`` the app answered something that is not a protocol reply.

Linux and macOS connect with ``socket.AF_UNIX`` to the socket path; Windows
opens the named pipe with ``CreateFileW`` / ``WaitNamedPipeW`` (busy pipes
waited for until the timeout, from the real ``GetLastError()`` code), then
does the blocking I/O in a worker thread so the timeout holds.
"""
from __future__ import annotations

import json
import socket
import sys
import threading
import time
import uuid
from typing import Optional

PROTOCOL_VERSION = 1
DEFAULT_TIMEOUT = 10.0
MAX_LINE = 64 * 1024


class EndpointError(Exception):
    code = "error"
    # True when the request may have reached the app before the failure (the
    # connection closed after the request was written): the outcome is then
    # unknown, the app may have applied it (W6b fix round 1).
    delivered = False

    def __init__(self, message: str = "", reply: Optional[dict] = None,
                 delivered: bool = False):
        super().__init__(message or self.code)
        self.reply = reply
        self.delivered = bool(delivered)


class NoApp(EndpointError):
    code = "no_app"


class Timeout(EndpointError):
    code = "timeout"


class BadToken(EndpointError):
    code = "bad_token"


class Refused(EndpointError):
    code = "refused"

    @property
    def reason(self) -> Optional[str]:
        return (self.reply or {}).get("reason")


class BadReply(EndpointError):
    code = "bad_reply"


def build_request(token: str, op: str, payload: Optional[dict] = None,
                  request_id: Optional[str] = None) -> dict:
    """The request object; ``payload`` fields go beside the envelope and may
    not override it."""
    req = dict(payload or {})
    for reserved in ("v", "token", "id", "op"):
        if reserved in req:
            raise ValueError(f"payload may not set {reserved!r}")
    req.update({"v": PROTOCOL_VERSION, "token": token, "op": op,
                "id": request_id or uuid.uuid4().hex})
    return req


def send(endpoint, op: str, payload: Optional[dict] = None, *,
         request_id: Optional[str] = None, timeout: float = DEFAULT_TIMEOUT) -> dict:
    """Send one request to ``endpoint`` (a ``discovery.Endpoint``) and return
    the reply. Raises an ``EndpointError`` (see the module docstring)."""
    request = build_request(endpoint.token, op, payload, request_id)
    line = (json.dumps(request, sort_keys=True) + "\n").encode("utf-8")
    raw = exchange(endpoint.server, line, timeout)
    return _check_reply(raw, request["id"])


def exchange(server: str, line: bytes, timeout: float = DEFAULT_TIMEOUT) -> bytes:
    """Write ``line`` to the endpoint at ``server`` and return the first reply
    line (without its newline). Raises NoApp or Timeout."""
    if sys.platform == "win32":
        return _exchange_pipe(server, line, timeout)
    return _exchange_unix(server, line, timeout)


def _exchange_unix(path: str, line: bytes, timeout: float) -> bytes:
    deadline = time.monotonic() + timeout
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(max(0.001, deadline - time.monotonic()))
        try:
            sock.connect(path)
        except socket.timeout:
            raise Timeout("connect timed out")
        except OSError as exc:
            raise NoApp(f"cannot connect: {exc}")
        try:
            sock.settimeout(max(0.001, deadline - time.monotonic()))
            sock.sendall(line)
            buf = b""
            while b"\n" not in buf:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise Timeout("no reply")
                sock.settimeout(remaining)
                chunk = sock.recv(65536)
                if not chunk:
                    raise NoApp("the app closed the connection before replying", delivered=True)
                buf += chunk
                if len(buf) > MAX_LINE:
                    raise BadReply("reply too long")
        except socket.timeout:
            raise Timeout("no reply")
        except (ConnectionError, BrokenPipeError) as exc:
            raise NoApp(f"the app closed the connection: {exc}", delivered=True)
        return buf.split(b"\n", 1)[0]
    finally:
        try:
            sock.close()
        except OSError:
            pass


ERROR_FILE_NOT_FOUND = 2      # Windows: no such pipe
ERROR_ACCESS_DENIED = 5       # Windows: the pipe is another account's
ERROR_PIPE_BUSY = 231         # Windows: the pipe exists, every instance is busy
PIPE_BUSY_RETRY_S = 0.05
PIPE_WAIT_STEP_MS = 1000      # WaitNamedPipeW's step; the deadline still rules
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3


class _Win32Pipe:
    """Windows: open a named pipe with ``CreateFileW`` and wait on a busy one
    with ``WaitNamedPipeW`` (W6b fix F5), through ctypes with
    ``use_last_error=True``, so the decision rests on the real
    ``GetLastError()`` code. Python's own ``open()`` goes through the C
    runtime (``_wopen``), whose exception carries only an errno: a busy pipe
    cannot be told from other failures there. ``kernel32``,
    ``get_last_error`` and ``to_file`` are injectable (fakes in tests, any
    OS)."""

    def __init__(self, kernel32=None, get_last_error=None, to_file=None):
        import ctypes
        if kernel32 is None:
            from ctypes import wintypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                             ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                             wintypes.HANDLE]
            kernel32.CreateFileW.restype = wintypes.HANDLE
            kernel32.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
            kernel32.WaitNamedPipeW.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL
        self.kernel32 = kernel32
        self.get_last_error = get_last_error or ctypes.get_last_error
        self.invalid = ctypes.c_void_p(-1).value
        self.to_file = to_file or self._handle_to_file

    def _handle_to_file(self, handle):
        import msvcrt
        import os
        fd = msvcrt.open_osfhandle(handle, os.O_RDWR | getattr(os, "O_BINARY", 0))
        return open(fd, "r+b", buffering=0)

    def open(self, path: str, deadline: float):
        """The open pipe as a binary file object. ``NoApp`` when the pipe
        does not exist (or is refused); ``Timeout`` when it stays busy until
        ``deadline``."""
        k = self.kernel32
        while True:
            handle = k.CreateFileW(path, GENERIC_READ | GENERIC_WRITE, 0, None,
                                   OPEN_EXISTING, 0, None)
            if handle is not None and handle != self.invalid and handle != -1:
                try:
                    return self.to_file(handle)
                except Exception:
                    k.CloseHandle(handle)
                    raise
            err = self.get_last_error()
            if err != ERROR_PIPE_BUSY:
                if err == ERROR_FILE_NOT_FOUND:
                    raise NoApp("cannot open the pipe: it does not exist")
                raise NoApp(f"cannot open the pipe: Windows error {err}")
            remaining_ms = int((deadline - time.monotonic()) * 1000)
            if remaining_ms <= 0:
                raise Timeout("the pipe stayed busy")
            if not k.WaitNamedPipeW(path, min(remaining_ms, PIPE_WAIT_STEP_MS)):
                # timed out this step, or the pipe vanished: CreateFileW says which
                time.sleep(min(PIPE_BUSY_RETRY_S, max(0.0, deadline - time.monotonic())))


def _open_pipe(path: str, deadline: float, opener=None):
    """Open the pipe before ``deadline`` (W6b, spec §4.5b; fix F5).

    Default (``opener`` None): ``_Win32Pipe``, which knows a busy pipe from
    ``GetLastError() == ERROR_PIPE_BUSY`` and waits for it with
    ``WaitNamedPipeW``; a missing pipe is ``NoApp`` at once.

    With an ``opener`` of Python's ``open`` signature (the C runtime path):
    only ``FileNotFoundError`` is known to mean "no pipe" (``NoApp`` at
    once). Every other ``OSError`` carries no Windows code there, so it may
    be the busy pipe: it is retried until the deadline, then ``Timeout``
    (never a premature ``no_app``)."""
    if opener is None:
        return _Win32Pipe().open(path, deadline)
    while True:
        try:
            return opener(path, "r+b", buffering=0)
        except FileNotFoundError as exc:
            raise NoApp(f"cannot open the pipe: {exc}")
        except OSError:
            if time.monotonic() + PIPE_BUSY_RETRY_S >= deadline:
                raise Timeout("the pipe stayed busy or unopenable until the timeout")
            time.sleep(PIPE_BUSY_RETRY_S)


def _exchange_pipe(path: str, line: bytes, timeout: float, opener=None) -> bytes:
    """Windows named pipe: open it (a busy pipe is waited for until the
    timeout, ``_open_pipe``); blocking I/O in a daemon thread so the timeout
    holds (a stuck read is abandoned, not waited for)."""
    result = {}
    deadline = time.monotonic() + timeout

    def work():
        try:
            with _open_pipe(path, deadline, opener) as pipe:
                pipe.write(line)
                buf = b""
                while b"\n" not in buf:
                    chunk = pipe.read(1)
                    if not chunk:
                        result["error"] = NoApp("the app closed the pipe before replying",
                                                delivered=True)
                        return
                    buf += chunk
                    if len(buf) > MAX_LINE:
                        result["error"] = BadReply("reply too long")
                        return
                result["line"] = buf.split(b"\n", 1)[0]
        except EndpointError as exc:
            result["error"] = exc
        except OSError as exc:
            result["error"] = NoApp(f"pipe error: {exc}")

    worker = threading.Thread(target=work, name="app-endpoint-client", daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        raise Timeout("no reply")
    if "error" in result:
        raise result["error"]
    return result["line"]


def _check_reply(raw: bytes, request_id: str) -> dict:
    try:
        reply = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise BadReply("reply is not JSON")
    if not isinstance(reply, dict) or reply.get("v") != PROTOCOL_VERSION \
            or not isinstance(reply.get("status"), str):
        raise BadReply("reply is not a protocol v1 object", reply)
    if reply.get("status") == "refused":
        if reply.get("reason") == "bad_token":
            raise BadToken("the app refused the token", reply)
        raise Refused(f"refused: {reply.get('reason')}", reply)
    if reply.get("id") != request_id:
        raise BadReply("reply id does not match the request", reply)
    return reply
