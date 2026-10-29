# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The app side of the Core app endpoint (SPEC-SET-003 §4.5b, W6e). Qt.

``AppEndpointServer`` is a ``QLocalServer`` (a Unix socket on Linux and macOS,
a named pipe on Windows) created on the GUI thread, so every request is
handled on the GUI thread by construction. It is a collaborator owned by a
manager (``ZodiacSettingsManager``, beside the live frame publisher), never a
``ChartGUI`` attribute (Rule 4b).

Protocol (one JSON object per line each way, see ``client``):

- a request that is not a JSON object, has another ``v`` or no string ``id``
  is refused ``bad_request``; a wrong token is refused ``bad_token`` and the
  connection closed; an ``op`` outside the dispatch table is refused
  ``unknown_op``;
- the dispatch table has exactly ONE slot, ``set_app_setting``, which W6b
  fills (``set_handler``). An empty slot answers ``refused`` / ``unavailable``.
  There is no generic method call and no other op;
- a connection idle for 10 s is closed.

One endpoint per process: the discovery file is ``<pid>.json``, so starting a
second server in the same process (a test that builds a second window) stops
the first one. The discovery file is removed at clean exit (``aboutToQuit``),
when the owner is destroyed, and by an ``atexit`` safety net; each removal
only touches the file while it still holds this server's token.
"""
from __future__ import annotations

import atexit
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import stat
import sys
import tempfile
from pathlib import Path
from typing import Callable, Dict, Optional

from PySide6.QtCore import QObject, QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from core.app_endpoint import discovery

PROTOCOL_VERSION = 1
IDLE_MS = 10_000
MAX_LINE = 64 * 1024
MAX_ID = 128

# The fixed set of op slots. W6b fills ``set_app_setting``; the desktop MCP
# server's link (SPEC-LMCP-001 §4.4, D-6) fills ``get_open_chart``,
# ``open_chart`` and ``window_action`` (§4.10, an allowlisted catalog, not a
# generic dispatch). Nothing else can ever be registered (spec §4.5b).
OP_SLOTS = ("set_app_setting", "get_open_chart", "open_chart", "window_action")

_TOKEN_RE = re.compile(r"\A[0-9a-f]{32}\Z")
_log = logging.getLogger(__name__)
_current: Optional["AppEndpointServer"] = None


def server_name(folder, pid: Optional[int] = None) -> str:
    """The local server name of an instance: a hash of the user-data folder
    and the PID (short, so the Unix socket path stays far below its limit).
    On Linux and macOS the server listens at this name inside
    ``private_socket_dir()``; on Windows it is the pipe name."""
    pid = os.getpid() if pid is None else int(pid)
    digest = hashlib.sha256(f"{os.path.abspath(str(folder))}\0{pid}".encode("utf-8"))
    return f"varuna360-{digest.hexdigest()[:20]}"


def private_socket_dir() -> Path:
    """Linux and macOS: the folder holding the endpoint sockets,
    ``<temp>/varuna360-<uid>``, created 0700. Qt's ``UserAccessOption`` has no
    effect on macOS Unix sockets, so the directory is what keeps other users
    out, on every Unix. Raises when the folder exists but is not this user's
    private, real directory (a symlink, another owner, group/other access)."""
    path = Path(tempfile.gettempdir()) / f"varuna360-{os.getuid()}"
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    info = os.lstat(path)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise PermissionError(f"{path} is not a directory owned by this user")
    if stat.S_IMODE(info.st_mode) & 0o077:
        os.chmod(path, 0o700)
        if stat.S_IMODE(os.lstat(path).st_mode) & 0o077:
            raise PermissionError(f"{path} is open to other users")
    return path


def listen_address(folder) -> str:
    """What the server listens on: the pipe name on Windows, the socket's
    full path in the private directory elsewhere."""
    name = server_name(folder)
    if sys.platform == "win32":
        return name
    return str(private_socket_dir() / name)


def current() -> Optional["AppEndpointServer"]:
    """This process's running endpoint, or None."""
    return _current if _current is not None and _current.is_listening() else None


class AppEndpointServer(QObject):
    """One instance's endpoint: the local server, its discovery file and the
    one-slot dispatch table."""

    def __init__(self, folder, edition: Optional[str] = None, parent=None,
                 idle_ms: int = IDLE_MS):
        super().__init__(parent)
        self.folder = Path(folder)
        self._edition = edition
        self.idle_ms = int(idle_ms)
        self.token = secrets.token_hex(16)            # 128 bits
        self._handlers: Dict[str, Optional[Callable[[dict], dict]]] = {
            op: None for op in OP_SLOTS}
        self._server: Optional[QLocalServer] = None
        self._sockets = {}                              # socket -> [buffer, idle timer]
        self.discovery_path: Optional[Path] = None
        self.last_error: Optional[str] = None
        self.handled = 0                                # requests answered (diagnostics)

    # ── lifecycle ────────────────────────────────────────────────────────

    @classmethod
    def start_in(cls, owner: QObject, folder, edition: Optional[str] = None):
        """Make this instance discoverable, then start its endpoint for
        user-data folder ``folder``, owned by ``owner`` (cleaned up when it
        is destroyed). Returns the server, or None when ``folder`` is unknown
        or the server could not start (the app runs on without an endpoint;
        ``last_error`` says why). Never raises.

        W6b fix F7 / F3-R1: the instance is known to be running whether or
        not its endpoint starts (``app_requests.secure_running_instance``:
        the liveness marker, else the fallback marker, else the sentinel
        lock), so ``settings.py set --app`` refuses ``endpoint_unavailable``
        instead of writing the file offline under a running window. When no
        marker of any kind and no endpoint can be published, the settings
        lock stays held by this process (the startup hold, or taken now), so
        an offline writer is refused ``busy``. A marker or the endpoint
        releases that hold. A settings lock that cannot be opened is never
        taken for an exclusion (W6b fix F3-R2): this waits until it opens
        (repairing this user's own lock file closed by its permission bits)
        or a marker is published."""
        if not folder:
            return None
        from core.settings_registry import app_requests
        app_requests.secure_running_instance(folder)
        server = None
        try:
            server = cls(folder, edition=edition, parent=owner)
        except Exception as exc:                        # pragma: no cover
            _log.warning("app endpoint not created: %s", exc)
        started = server is not None and server.start()
        app_requests.secure_running_instance(folder, endpoint_started=started)
        return server if started else None

    def start(self) -> bool:
        global _current
        if self._server is not None:
            return True
        previous = _current
        if previous is not None and previous is not self:
            previous.stop()                             # one endpoint per process
        try:
            discovery.prune_stale(self.folder)
            name = listen_address(self.folder)
            # A socket left by a crashed process that had this PID: the name
            # holds our PID, so nothing alive can own it.
            QLocalServer.removeServer(name)
            server = QLocalServer(self)
            server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
            server.setMaxPendingConnections(8)
            if not server.listen(name):
                self.last_error = f"listen failed: {server.errorString()}"
                _log.warning("app endpoint: %s", self.last_error)
                server.deleteLater()
                return False
            server.newConnection.connect(self._on_new_connection)
            self._server = server
            self.discovery_path = discovery.write_endpoint(
                self.folder, server.fullServerName(), self.token, self._edition_now())
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            _log.warning("app endpoint not started: %s", self.last_error)
            self._close_server()
            return False
        _current = self
        _install_exit_hooks(self)
        return True

    def stop(self) -> None:
        """Close the server and every connection, remove the discovery file.
        Idempotent; never raises."""
        global _current
        self._close_server()
        if self.discovery_path is not None:
            discovery.remove_endpoint(self.folder, token=self.token)
            self.discovery_path = None
        if _current is self:
            _current = None

    def _close_server(self) -> None:
        for sock in list(self._sockets):
            self._drop(sock)
        server, self._server = self._server, None
        if server is not None:
            try:
                server.close()
                server.deleteLater()
            except RuntimeError:                        # already deleted by Qt
                pass

    def is_listening(self) -> bool:
        try:
            return self._server is not None and self._server.isListening()
        except RuntimeError:
            return False

    def _edition_now(self) -> str:
        if self._edition is None:
            from core.edition_features import running_edition
            self._edition = running_edition()
        return self._edition

    def identity_env(self) -> Dict[str, str]:
        """Environment entries handing THIS window's endpoint to a process it
        launches (the task MCP server, W6b): the discovery file's path and a
        fingerprint of the token (the token itself stays in the 0600 file).
        Empty when not running."""
        if self.discovery_path is None or not self.is_listening():
            return {}
        return {discovery.ENDPOINT_ENV: str(self.discovery_path.resolve()),
                discovery.ENDPOINT_FP_ENV: discovery.token_fingerprint(self.token)}

    # ── dispatch table ───────────────────────────────────────────────────

    def set_handler(self, op: str, handler: Optional[Callable[[dict], dict]]) -> None:
        """Fill (or empty, with None) one op slot. Only the fixed slots exist
        (``OP_SLOTS``); any other name raises KeyError. ``handler(request)``
        runs on the GUI thread and returns the reply fields (``status`` and
        any others); ``v`` and ``id`` are added by the server."""
        if op not in self._handlers:
            raise KeyError(f"no op slot {op!r}; slots: {', '.join(OP_SLOTS)}")
        self._handlers[op] = handler

    def handle_line(self, line: bytes):
        """One request line -> (reply dict, close the connection after)."""
        try:
            request = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return _reply(None, "refused", reason="bad_request"), True
        if not isinstance(request, dict):
            return _reply(None, "refused", reason="bad_request"), True
        rid = request.get("id")
        rid = rid if isinstance(rid, str) and 0 < len(rid) <= MAX_ID else None
        token = request.get("token")
        # format first: a JSON string may hold lone surrogates that cannot be
        # encoded, and compare_digest only takes ASCII strings
        if not isinstance(token, str) or not _TOKEN_RE.match(token) \
                or not hmac.compare_digest(token, self.token):
            return _reply(rid, "refused", reason="bad_token"), True
        if request.get("v") != PROTOCOL_VERSION or rid is None:
            return _reply(rid, "refused", reason="bad_request"), False
        op = request.get("op")
        if not isinstance(op, str) or op not in self._handlers:
            return _reply(rid, "refused", reason="unknown_op"), False
        handler = self._handlers[op]
        if handler is None:
            return _reply(rid, "refused", reason="unavailable"), False
        try:
            fields = handler(dict(request))
        except Exception as exc:
            _log.exception("app endpoint op %s failed", op)
            self.last_error = f"{op}: {type(exc).__name__}: {exc}"
            return _reply(rid, "refused", reason="internal_error"), False
        if not isinstance(fields, dict) or not isinstance(fields.get("status"), str):
            return _reply(rid, "refused", reason="internal_error"), False
        out = {k: v for k, v in fields.items() if k not in ("v", "id")}
        return {"v": PROTOCOL_VERSION, "id": rid, **out}, False

    # ── connections ──────────────────────────────────────────────────────

    def _on_new_connection(self) -> None:
        server = self._server
        while server is not None and server.hasPendingConnections():
            sock = server.nextPendingConnection()
            if sock is None:
                break
            timer = QTimer(sock)
            timer.setSingleShot(True)
            timer.setInterval(self.idle_ms)
            timer.timeout.connect(lambda s=sock: self._drop(s))
            # Qt stops reading from the OS once this much is buffered, so a
            # client that never sends a newline cannot grow the GUI's memory.
            sock.setReadBufferSize(MAX_LINE + 1)
            self._sockets[sock] = [b"", timer]
            sock.readyRead.connect(lambda s=sock: self._on_ready_read(s))
            sock.disconnected.connect(lambda s=sock: self._drop(s))
            timer.start()

    def _on_ready_read(self, sock: QLocalSocket) -> None:
        """Read at most one line's worth beyond what is buffered, answer every
        complete line, and repeat while Qt holds more: memory stays bounded by
        MAX_LINE whatever the client sends."""
        while sock in self._sockets:
            entry = self._sockets[sock]
            room = MAX_LINE + 1 - len(entry[0])
            try:
                pending = sock.bytesAvailable()
                if room > 0 and pending:
                    chunk = bytes(sock.read(room).data())
                    if not chunk:
                        return
                    entry[0] += chunk
            except RuntimeError:
                self._sockets.pop(sock, None)
                return
            entry[1].start()                            # activity: restart idle
            if not self._answer_lines(sock):
                return
            try:
                if not sock.bytesAvailable():
                    return
            except RuntimeError:
                return

    def _answer_lines(self, sock: QLocalSocket) -> bool:
        """Answer the complete lines buffered for ``sock``. False when the
        connection was dropped or a line is still incomplete and over the
        limit (refused and closed)."""
        while sock in self._sockets:
            buf = self._sockets[sock][0]
            if b"\n" not in buf:
                if len(buf) > MAX_LINE:
                    self._write(sock, _reply(None, "refused", reason="bad_request"))
                    self._drop(sock)
                    return False
                return True
            line, rest = buf.split(b"\n", 1)
            self._sockets[sock][0] = rest
            if len(line) > MAX_LINE:
                reply, close = _reply(None, "refused", reason="bad_request"), True
            else:
                reply, close = self.handle_line(line.strip())
            self.handled += 1
            self._write(sock, reply)
            if close:
                self._drop(sock)
                return False
        return False

    def _write(self, sock: QLocalSocket, reply: dict) -> None:
        try:
            sock.write((json.dumps(reply, sort_keys=True) + "\n").encode("utf-8"))
            sock.flush()
        except RuntimeError:
            pass

    def _drop(self, sock: QLocalSocket) -> None:
        """Forget and close one connection. Its signals are disconnected
        first: a socket destroyed later (with the server, or the owner)
        emits ``disconnected`` again, and a Python slot running during that
        destruction crashes the interpreter."""
        entry = self._sockets.pop(sock, None)
        if entry is None:
            return
        for signal in ("readyRead", "disconnected"):
            try:
                getattr(sock, signal).disconnect()
            except (RuntimeError, TypeError):
                pass
        try:
            entry[1].stop()
            entry[1].timeout.disconnect()
        except (RuntimeError, TypeError):
            pass
        try:
            sock.abort()
            sock.deleteLater()
        except RuntimeError:
            pass


def _reply(rid, status: str, **fields) -> dict:
    return {"v": PROTOCOL_VERSION, "id": rid, "status": status, **fields}


def _install_exit_hooks(server: AppEndpointServer) -> None:
    """Remove the discovery file at clean exit (``aboutToQuit``), when the
    owner is destroyed, and at interpreter exit. Each hook removes the file
    only while it holds this server's token."""
    folder, token = server.folder, server.token
    from PySide6.QtCore import QCoreApplication
    app = QCoreApplication.instance()
    if app is not None:
        app.aboutToQuit.connect(server.stop)
    server.destroyed.connect(
        lambda *_a, f=folder, t=token: discovery.remove_endpoint(f, token=t))
    atexit.register(discovery.remove_endpoint, folder, token)
