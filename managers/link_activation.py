# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Loopback browser-activation flow for Varuna360 Core/Lite (SPEC-LIC-001).

The OAuth 2.0 native-app pattern (RFC 8252, the flow Claude Code and the
GitHub CLI use): the app binds a loopback HTTP listener on an ephemeral port,
opens the account's desktop-link page in the browser with a PKCE challenge,
and waits for the browser to navigate back to http://127.0.0.1:{port}/callback
with a one-time code. The code is then redeemed via
managers.license_key.activate_via_link(), which stores the SAME credential
pair the paste-key path stores (license key + signed token, INV-1).

Security posture (spec §3.2):
  * PKCE S256 is mandatory (INV-4): the verifier is CSPRNG, lives only in this
    process's memory, and is never written to disk or a URL. `state` alone
    cannot stop a co-resident local process from redeeming an intercepted
    loopback code; the verifier can.
  * The credential NEVER travels in a redirect URL (INV-5): the callback
    carries only the one-time code; the key+token arrive in the TLS-protected
    exchange response body.
  * The listener is loopback-only, hardened, single-consumption and
    time-bounded (INV-6): direct bind on a hardcoded loopback literal with
    port 0 (no check-then-bind gap, D-9), socket HELD for the whole flow, and
    only a FULLY VALID callback consumes it. Everything else (wrong path,
    wrong Host, non-GET, duplicate params, wrong state) gets 404/400 and
    leaves the flow pending until timeout: a wrong-state request is exactly
    what a hostile local page sends, and cancelling on it would hand any local
    process a one-request denial of service.
  * Request URLs are never logged (they carry code and state).

No PySide6 imports here: the Qt worker lives in managers/license_workers.py.
"""

import base64
import hashlib
import hmac
import logging
import secrets
import socket
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

logger = logging.getLogger(__name__)

SITE_URL = "https://360heartsinthesky.com"
DESKTOP_LINK_PATH = "/account/desktop-link"
CALLBACK_PATH = "/callback"

# Spec §3.2 step 10 / §4.3: no callback within this window ends the flow.
FLOW_TIMEOUT_S = 180.0

# INV-6 bounds: request-target under 8 KB, canonical bounded param values.
_MAX_TARGET_LEN = 8192
_MAX_PARAM_LEN = 512
_B64URL_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
_SLUG_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz_")

_CALLBACK_HTML = (
    "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
    "<title>Varuna360</title></head>"
    "<body style=\"font-family: sans-serif; text-align: center; "
    "padding-top: 4em; background: #1a1a2e; color: #eaeaea;\">"
    "<h2>Varuna360</h2>"
    "<p>You can close this tab and return to Varuna360.</p>"
    "</body></html>"
)


class LinkUnavailableError(Exception):
    """No loopback socket could be bound (IPv4 and IPv6 both failed)."""


def generate_state() -> str:
    """43-char urlsafe base64 of 32 CSPRNG bytes (spec §3.3(1))."""
    return secrets.token_urlsafe(32)


def generate_pkce() -> tuple:
    """Return (verifier, challenge): S256, challenge unpadded base64url (INV-4)."""
    verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


class LinkResult:
    """Outcome of one flow run.

    kind: 'code' (callback delivered a one-time code), 'error' (callback
    delivered an §3.4 slug, e.g. the customer declined), 'timeout',
    'cancelled', each terminal for the flow.
    """

    def __init__(self, kind, code=None, error_slug=None):
        self.kind = kind
        self.code = code
        self.error_slug = error_slug


class _LinkServer(HTTPServer):
    """Loopback HTTP server carrying a reference back to its flow."""

    allow_reuse_address = False  # never share the advertised port

    def __init__(self, server_address, handler_class, flow, family):
        self.address_family = family
        self._flow = flow
        super().__init__(server_address, handler_class)

    def server_bind(self):
        # On Windows, allow_reuse_address=False alone is not exclusive: a
        # same-user process can still bind our advertised port with
        # SO_REUSEADDR and race callback delivery. SO_EXCLUSIVEADDRUSE (set
        # before bind) forbids that. The attribute only exists on Windows, so
        # this is a no-op elsewhere.
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(
                socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def handle_error(self, request, client_address):
        # Default implementation prints a traceback (which would carry the
        # request context) to stderr; log the class only, never the URL.
        import sys
        exc = sys.exc_info()[1]
        logger.warning("Callback listener error (%s)", type(exc).__name__)


class _CallbackHandler(BaseHTTPRequestHandler):
    """One-request handler enforcing the INV-6 validation ladder."""

    # A client that connects and never sends a request must not stall the
    # flow past its deadline; the run loop re-checks time after each request.
    timeout = 5
    server_version = "Varuna360"
    sys_version = ""

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        pass  # request lines carry code+state; never logged (INV-6)

    def _respond(self, status, body=b"", content_type="text/plain"):
        try:
            self.send_response(status)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            if body:
                self.wfile.write(body)
        except OSError:
            pass  # client went away; the flow outcome is already decided

    def _reject(self, status=404):
        self._respond(status, b"Not found" if status == 404 else b"Bad request")

    def do_GET(self):
        flow = self.server._flow
        outcome = flow._evaluate_callback(self.path, self.headers.get("Host"))
        if outcome is None:
            # Invalid in some way: refuse, flow STAYS PENDING (INV-6).
            self._reject(400 if self.path.startswith(CALLBACK_PATH) else 404)
            return
        # Fully valid: single consumption under the flow's own guard.
        if not flow._consume(outcome):
            self._reject(404)  # already consumed by an earlier valid callback
            return
        self._respond(200, _CALLBACK_HTML.encode("utf-8"),
                      content_type="text/html")

    # Anything but GET is refused without consuming the flow (INV-6).
    def do_POST(self):
        self._reject()

    do_HEAD = do_PUT = do_DELETE = do_OPTIONS = do_PATCH = do_POST


class LinkActivationFlow:
    """One browser-activation attempt: bind, build URL, wait, deliver result.

    Usage (from a worker thread):
        flow = LinkActivationFlow()
        url = flow.start()          # binds + holds the socket, then builds URL
        webbrowser.open(url)
        result = flow.run()         # blocks until callback/timeout/cancel
    cancel() may be called from any thread.
    """

    def __init__(self, timeout=FLOW_TIMEOUT_S, site_url=SITE_URL):
        self._timeout = timeout
        self._site_url = site_url
        self._server = None
        self._port = None
        self._host_literal = None  # "127.0.0.1" or "[::1]" as seen in Host:
        self._state = None
        self._verifier = None
        self._result = None
        self._consumed = False
        self._cancelled = False
        self._closed = False
        # Serializes _consume() against cancel(): without it a callback
        # arriving in the same instant as a cancel could consume the flow and
        # let a cancelled run still hand a code to the worker.
        self._state_lock = threading.Lock()

    # ── properties the worker needs for the exchange ────────────────────

    @property
    def state(self):
        return self._state

    @property
    def verifier(self):
        """PKCE verifier: in-memory only, read exactly once for the exchange."""
        return self._verifier

    @property
    def port(self):
        return self._port

    # ── lifecycle ───────────────────────────────────────────────────────

    def start(self) -> str:
        """Bind the loopback listener and return the browser URL.

        The socket is created BEFORE the URL is built and held until the flow
        ends (INV-6): the port in the URL is always a port we still own.
        Raises LinkUnavailableError when neither family binds (§4.3 row 1).
        """
        self._server, addr_slug = self._bind()
        self._port = self._server.server_address[1]
        self._state = generate_state()
        self._verifier, challenge = generate_pkce()

        from managers.license_key import _platform_string
        from managers.license_manager import (
            _get_app_version, get_machine_fingerprint,
        )
        params = urllib.parse.urlencode({
            "state": self._state,
            "port": self._port,
            "machine_id": get_machine_fingerprint(),
            "app_version": _get_app_version(),
            "platform": _platform_string(),
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "addr": addr_slug,
        })
        return f"{self._site_url}{DESKTOP_LINK_PATH}?{params}"

    def _bind(self):
        """Direct-bind port 0 on 127.0.0.1, falling back to ::1 (D-9/D-10)."""
        try:
            server = _LinkServer(("127.0.0.1", 0), _CallbackHandler,
                                 flow=self, family=socket.AF_INET)
            self._host_literal = "127.0.0.1"
            return server, "ipv4"
        except OSError:
            logger.warning("IPv4 loopback bind failed; trying ::1")
        try:
            server = _LinkServer(("::1", 0), _CallbackHandler,
                                 flow=self, family=socket.AF_INET6)
            self._host_literal = "[::1]"
            return server, "ipv6"
        except OSError:
            logger.warning("IPv6 loopback bind failed too")
            raise LinkUnavailableError(
                "No loopback socket could be bound on this computer."
            )

    def run(self) -> LinkResult:
        """Serve until a fully valid callback, timeout, or cancel.

        Only a fully valid callback consumes the listener (INV-6); invalid
        requests are answered 404/400 and the deadline keeps running.
        """
        if self._server is None:
            raise RuntimeError("start() must be called before run()")
        deadline = time.monotonic() + self._timeout
        self._server.timeout = 0.25
        try:
            while (not self._consumed and not self._cancelled
                   and time.monotonic() < deadline):
                try:
                    self._server.handle_request()
                except OSError:
                    break  # socket closed under us (cancel from another thread)
        finally:
            self.close()
        # Cancel wins a photo-finish with a callback: "cancel = no state
        # change" (§4.3) must hold even when the callback landed in the same
        # tick, so a cancelled flow never surfaces a code to redeem.
        if self._cancelled:
            return LinkResult("cancelled")
        if self._consumed:
            return self._result
        return LinkResult("timeout")

    def cancel(self):
        """Thread-safe: end the flow now. Safe to call at any point."""
        with self._state_lock:
            self._cancelled = True
        self.close()

    def close(self):
        """Shut the listener down and release the port. Idempotent."""
        if self._closed:
            return
        self._closed = True
        server = self._server
        if server is not None:
            try:
                server.server_close()
            except OSError:
                pass

    # ── callback validation (INV-6) ─────────────────────────────────────

    def _evaluate_callback(self, target: str, host):
        """Validate one request. Returns a LinkResult to consume, or None.

        The ladder, every rung fail-closed:
        request-target size, exact path, exact loopback Host, well-formed
        query, no duplicate keys, exactly one `state`, exactly one of
        `code`/`error`, canonical bounded values, constant-time state match.
        Params other than code/state/error are ignored entirely and never
        read (INV-5 allowlist: a `key=` or `token=` param is dead on arrival).
        """
        if not isinstance(target, str) or len(target) > _MAX_TARGET_LEN:
            return None
        try:
            split = urllib.parse.urlsplit(target)
        except ValueError:
            return None
        if split.path != CALLBACK_PATH:
            return None
        expected_host = f"{self._host_literal}:{self._port}"
        if not isinstance(host, str) or host.strip() != expected_host:
            return None  # DNS-rebinding / cross-origin probe
        try:
            pairs = urllib.parse.parse_qsl(
                split.query, keep_blank_values=True, strict_parsing=True)
        except ValueError:
            return None
        seen = {}
        for k, v in pairs:
            if k in seen:
                return None  # duplicate key, ANY key (parameter smuggling)
            seen[k] = v

        state = seen.get("state")
        code = seen.get("code")
        error = seen.get("error")
        if state is None:
            return None
        if (code is None) == (error is None):
            return None  # exactly one of code | error
        if not self._canonical(state, _B64URL_CHARS):
            return None
        if code is not None and not self._canonical(code, _B64URL_CHARS):
            return None
        if error is not None and not self._canonical(error, _SLUG_CHARS, 64):
            return None
        if not hmac.compare_digest(state, self._state or ""):
            # Exactly what a hostile local page sends; refuse WITHOUT ending
            # the flow, and log without the URL or values (§4.3).
            logger.warning("Callback with mismatched state refused; "
                           "flow stays pending")
            return None
        if code is not None:
            return LinkResult("code", code=code)
        return LinkResult("error", error_slug=error)

    @staticmethod
    def _canonical(value: str, charset, max_len=_MAX_PARAM_LEN) -> bool:
        return 0 < len(value) <= max_len and all(c in charset for c in value)

    def _consume(self, result: LinkResult) -> bool:
        """Single consumption guard: only the FIRST valid callback wins, and
        a cancelled flow refuses consumption entirely (cancel wins races)."""
        with self._state_lock:
            if self._consumed or self._cancelled:
                return False
            self._result = result
            self._consumed = True
            return True
