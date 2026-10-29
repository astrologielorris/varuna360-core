# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The live line to ffmpeg's zmq filter (SPEC-REC-001 INV-7): moves the
video-only privacy boxes. A QTcpSocket on the Qt event loop, no thread.

- ``start(port)`` connects to the filter (it binds when ffmpeg builds its
  graph, so the first tries may be refused; retried every 40 ms).
- ``ready`` is emitted once the ZMTP handshake is done; commands sent before
  that are refused (``send`` returns False) and the manager resends the
  current boxes on ``ready`` (review v0.4 F1: nothing is lost at startup).
- ``acked`` counts the filter's answers, for tests and diagnostics.
- ``failed(reason)`` once, when the line cannot protect the video: no
  handshake within HANDSHAKE_MS, a bad greeting or READY, a ZMTP ERROR, a
  command the filter refused, commands left unanswered for REPLY_MS (a
  silent but open line, review v0.4 R3), or the connection lost after the
  handshake (review v0.4 R2). The manager then stops the take.
  REPLY_MS is generous on purpose: slow encoders (AV1, 4K H.265 at 60 fps)
  hold the whole pipeline back for over a second at start and under load
  (review v0.4 R4: 1 s stopped healthy takes). The real filter answers in the
  same step that applies a move, so a silent filter with frames still being
  captured needs ffmpeg itself to misbehave.
"""
from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QAbstractSocket, QTcpSocket

from core.recorder import zmtp

RETRY_MS = 40
HANDSHAKE_MS = 5000            # ffmpeg binds within a few hundred ms
REPLY_MS = 5000


class MaskChannel(QObject):
    ready = Signal()
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sock = QTcpSocket(self)
        self._sock.connected.connect(self._on_connected)
        self._sock.readyRead.connect(self._on_read)
        self._sock.errorOccurred.connect(self._on_error)
        self._sock.disconnected.connect(self._on_disconnected)
        self._deadline = QTimer(self, singleShot=True)
        self._deadline.timeout.connect(lambda: self._fail("no answer from the ffmpeg blur filter"))
        self._reply_deadline = QTimer(self, singleShot=True)
        self._reply_deadline.timeout.connect(
            lambda: self._fail("the ffmpeg blur filter stopped answering"))
        self.outstanding = 0
        self._retry = QTimer(self, singleShot=True)
        self._retry.timeout.connect(self._connect)
        self._port = 0
        self._tries = 0
        self._reader = zmtp.Reader()
        self._handshake = False
        self.is_ready = False
        self.acked = 0
        self.closed = False

    def start(self, port: int) -> None:
        self._port = port
        self._deadline.start(HANDSHAKE_MS)
        self._connect()

    def _fail(self, reason: str) -> None:
        if self.closed:
            return
        self.close()
        self.failed.emit(reason)

    def _connect(self) -> None:
        if self.closed:
            return
        self._tries += 1
        self._sock.abort()
        self._reader = zmtp.Reader()
        self._sock.connectToHost("127.0.0.1", self._port)

    def _on_error(self, _err) -> None:
        if self.closed:
            return
        if self.is_ready or self._handshake:
            self._fail("the line to the ffmpeg blur filter was lost")
        elif self._deadline.isActive():
            self._retry.start(RETRY_MS)       # not listening yet: try again

    def _on_disconnected(self) -> None:
        if not self.closed and (self.is_ready or self._handshake):
            self._fail("the line to the ffmpeg blur filter was lost")

    def _on_connected(self) -> None:
        self._sock.write(zmtp.greeting())

    def _on_read(self) -> None:
        for kind, body in self._reader.feed(bytes(self._sock.readAll().data())):
            if self.closed:
                return
            if kind == "greeting":
                if not zmtp.valid_greeting(body):
                    return self._fail("unexpected answer on the blur filter port")
                self._sock.write(zmtp.ready_command())
            elif kind == "command":
                name, props = zmtp.parse_command(body)
                if name == "READY" and props.get(b"Socket-Type") == b"REP" and not self._handshake:
                    self._handshake = True
                    self.is_ready = True
                    self._deadline.stop()
                    self.ready.emit()
                elif name == "ERROR" or not self._handshake:
                    return self._fail("the blur filter refused the connection")
            elif kind == "message":
                self.acked += 1
                self.outstanding = max(0, self.outstanding - 1)

                if self.outstanding == 0:
                    self._reply_deadline.stop()
                else:
                    self._reply_deadline.start(REPLY_MS)   # progress: the next answer is due
                reply = body[-1].decode(errors="replace") if body else ""
                if not reply.startswith("0 "):    # ffmpeg answers "<status> <text>"
                    return self._fail(f"the blur filter refused a move ({reply.strip()})")

    def send(self, commands: Iterable[str]) -> bool:
        """All the commands in one write; the filter applies every waiting
        one on its next frame. False when not connected yet."""
        if not self.is_ready or self._sock.state() != QAbstractSocket.SocketState.ConnectedState:
            return False
        commands = list(commands)
        self._sock.write(b"".join(zmtp.request(c) for c in commands))
        self._sock.flush()
        self.outstanding += len(commands)

        if not self._reply_deadline.isActive():
            self._reply_deadline.start(REPLY_MS)
        return True

    def close(self) -> None:
        self.closed = True
        self.is_ready = False
        self._retry.stop()
        self._deadline.stop()
        self._reply_deadline.stop()
        self._sock.abort()
