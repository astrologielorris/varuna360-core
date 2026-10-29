# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""User-initiated bug reporting (SPEC-SES-001 §4.5).

Turns "it says Save Failed sometimes" into something diagnosable, without
turning an astrology app into a telemetry client.

TWO RULES GOVERN THIS MODULE
----------------------------
INV-7 — nothing is transmitted without an explicit click. There is no
automatic reporting, no background beacon, no crash uploader. `send_report`
is called from a dialog's Send button and from nowhere else.

INV-8 — the payload carries no astrological or personal data. It is built
from a FIXED ALLOWLIST (build_payload below), never by walking the session or
copying whatever is to hand. Chart names, birth data, coordinates and recipes
are never included, and the user's home directory is redacted to '~'
everywhere — including inside the log tail, because a path like
/Users/marie-claire/... names the person as surely as a name field.

The dialog shows the user the exact dict this module will send, so the
allowlist is not a promise, it is visible.
"""
import json
import re
from pathlib import Path

from core.diagnostics import describe_environment, read_log_tail, redact_home

_CORE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _CORE_DIR.parent

# Reuse the licensing API host rather than introducing a second endpoint
# constant that can drift out of sync with it.
try:
    from managers.license_manager import API_BASE_URL
except Exception:
    API_BASE_URL = "https://api.360heartsinthesky.com"

REPORT_ENDPOINT = f"{API_BASE_URL}/bug-report"
SEND_TIMEOUT_SECONDS = 10

MAX_NOTE_CHARS = 4000
MAX_LOG_LINES = 200

# The server caps log_tail at 200_000 chars and last_error at 2000, and
# rejects anything larger with a 422 the user cannot act on ("the server
# rejected the report") — in precisely the broken-app case this feature
# exists for. 200 lines is normally ~30 KB, but one fat traceback blows past
# it, so cap on THIS side too and never send something the server must refuse.
#
# 100_000 chars rather than the server's 200_000: DynamoDB's item limit is
# 400 KB of BYTES, and accented French is 2 bytes/char (CJK 3), so a
# character-capped tail can still exceed it.
MAX_LOG_CHARS = 100_000
MAX_ERROR_CHARS = 2000


def app_version():
    """Version string from the VERSION file, or 'unknown'."""
    try:
        return (PROJECT_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except Exception:
        return "unknown"


def edition():
    """'pro' or 'core'.

    Detected by the presence of the pro/ package, which the public Core
    artifact strips entirely (that stripping is what release Gate 5's
    clean-room boot verifies), so this is a reliable discriminator.
    """
    try:
        return "pro" if (PROJECT_ROOT / "pro").is_dir() else "core"
    except Exception:
        return "unknown"


def _cap(value, limit, keep="start"):
    """Truncate to `limit` characters, marking that it happened.

    A silent truncation in a diagnostic report is its own small bug: the
    reader cannot tell a short log from a cut-off one.
    """
    if not value:
        return value
    text = str(value)
    if len(text) <= limit:
        return text
    if keep == "end":
        return f"[truncated: showing the last {limit} characters]\n" + text[-limit:]
    return text[:limit] + f"\n[truncated at {limit} characters]"


# --- schema 2 (SPEC-AIR-001 §4.3) -------------------------------------------

SCHEMA_VERSION = 2
# The serialized body stays under this (the backend trims only two fields,
# DynamoDB items cap at 400 KB of bytes).
MAX_BODY_BYTES = 120_000
MAX_EVIDENCE_CHARS = 40_000
MAX_QUESTION_CHARS = 2000
BASIC_RECENT_ERRORS = 5
KINDS = ("basic", "ai_report")
SURFACES = ("ai_capture", "ai_search", "ai_settings", "partner_reading", "app")
CATEGORIES = ("crash", "error_message", "wrong_result", "ai_behaviour", "slow", "other")

# EXACT paths (from the root) of the app's own protocol values (ids, enums,
# versions) and of the user's opt-ins shown verbatim: the scrubber leaves
# them alone. Everything else, at any depth and keys included, is text and is
# scrubbed (AIR-001 INV-3). A nested key with one of these names gets NO
# exemption (review W0 B2).
_PROTOCOL_PATHS = frozenset({
    ("schema",), ("report_id",), ("kind",), ("surface",), ("branch_build",),
    ("app_version",), ("edition",), ("platform",), ("python",), ("qt",),
    ("session_health",), ("last_error_at",), ("contact_email",),
    ("has_attachment",), ("user_edited",), ("attachment_sha256",), ("attachment_type",),
    ("ai", "engine"), ("ai", "model"), ("ai", "effort"),
    ("report", "category"), ("report", "confidence"), ("report", "evidence"),
    ("recent_errors", "id"), ("recent_errors", "ts"), ("recent_errors", "last_ts"),
    ("recent_errors", "surface"), ("recent_errors", "kind"),
    ("recent_errors", "exc_type"),
    ("reading_reference", "job_id"), ("reading_reference", "status"),
})
# Every key name the schema uses below the top level (report, recent_errors,
# ai, reading_reference): fixed by this module, never user text.
_FIELD_NAMES = frozenset({p[-1] for p in _PROTOCOL_PATHS} | {
    "category", "confidence", "title", "what_happened", "expected", "actual",
    "suspected_cause", "steps_to_reproduce", "evidence",                  # report
    "id", "ts", "last_ts", "surface", "kind", "exc_type", "message", "traceback",
    "count", "correlation_id", "detail", "thread", "app_version",         # recent_errors
    "engine", "model", "effort", "job_id", "status", "http_status"})
# Fields holding log text: their line-start timestamps are kept.
_LOG_PATHS = frozenset({("log_tail",), ("evidence",)})

# The AI-written report: exactly these fields (anything else is dropped).
# Protocol fields skip the scrub, so they may only hold an identifier-like
# token (an engine id, a model slug, a uuid); anything with a space or other
# free text is dropped rather than sent unscrubbed.
_TOKEN = re.compile(r"[A-Za-z0-9][\w.\-:/]{0,79}")


def _protocol_token(value):
    if isinstance(value, str) and _TOKEN.fullmatch(value):
        return value
    return None


REPORT_TEXT_CAPS = {"title": 120, "what_happened": 2000, "expected": 600, "actual": 600,
                    "suspected_cause": 1500}
REPORT_STEPS_MAX, REPORT_STEP_CHARS, REPORT_EVIDENCE_MAX = 10, 300, 40

_SCRUB_CACHE = {"ctx": None, "at": 0.0, "generation": None}
_SCRUB_TTL_SECONDS = 300


def _store_generation():
    """The chart index's generation (changes on any add, rename, removal),
    or None when it cannot be read. Cheap: one SQL aggregate."""
    try:
        from core.chart_search.store import StoreReader
        reader = StoreReader.open()
        try:
            # The write revision catches a rename the aggregate can miss
            # (an older updated_at after a clock change; review W1 m1).
            return (reader.revision(), reader.generation())
        finally:
            reader.close()
    except Exception:
        return None


def session_names():
    """Names the index may not know yet: the profile folder names (a profile
    is often a client). Never raises."""
    try:
        from state.user_data import get_user_data_dir
        root = Path(get_user_data_dir()) / "profiles"
        return tuple(p.name for p in root.iterdir() if p.is_dir())
    except Exception:
        return ()


def default_scrub_context(extra_names=()):
    """The chart-library scrub context. Cached, and rebuilt whenever the
    index changed (a chart added or renamed since: review W0 B1) or after a
    few minutes. Building reads the whole index (~1 s). Never raises."""
    import time
    from core.privacy_scrub import build_context
    extra_names = tuple(extra_names or ()) + session_names()
    now = time.monotonic()
    generation = _store_generation()
    cached = _SCRUB_CACHE["ctx"]
    if (cached is not None and generation == _SCRUB_CACHE["generation"]
            and now - _SCRUB_CACHE["at"] < _SCRUB_TTL_SECONDS
            and _SCRUB_CACHE.get("extra") == extra_names):
        return cached
    ctx = build_context(extra_names=extra_names)
    _SCRUB_CACHE.update(ctx=ctx, at=now, generation=generation, extra=extra_names)
    return ctx


def clean_report(report):
    """The AI report reduced to its schema (AIR-001 §4.2): known fields only,
    typed and capped. Unknown keys are dropped, never sent."""
    report = dict(report or {})
    out = {"category": str(report.get("category") or "other")[:40],
           "confidence": str(report.get("confidence") or "low")[:10]}
    for key, cap in REPORT_TEXT_CAPS.items():
        out[key] = str(report.get(key) or "")[:cap]
    steps = report.get("steps_to_reproduce") or []
    steps = steps if isinstance(steps, list) else [steps]
    out["steps_to_reproduce"] = [str(s)[:REPORT_STEP_CHARS] for s in steps[:REPORT_STEPS_MAX]]
    evidence = report.get("evidence") or []
    evidence = evidence if isinstance(evidence, list) else [evidence]
    import re
    ref = re.compile(r"^E\d{1,4}:[LJ]\d{1,5}(?:-[LJ]?\d{1,5})?$")
    out["evidence"] = [str(e) for e in evidence[:REPORT_EVIDENCE_MAX] if ref.match(str(e))]
    return out


def branch_build():
    """'main' or 'lts': read from the per-branch build switch file."""
    try:
        from core import build_features
        line = getattr(build_features, "BRANCH_LINE", None)
        if line:
            return line
        return "main" if getattr(build_features, "AI_CAPTURE_ENABLED", False) else "lts"
    except Exception:
        return "unknown"


def _recent_errors(limit):
    try:
        from core.error_journal import read_journal
        out = []
        for e in read_journal(limit=limit):
            out.append({k: e.get(k) for k in (
                "id", "ts", "last_ts", "surface", "kind", "exc_type", "message",
                "traceback", "count")})
        return out
    except Exception:
        return []


class ReportTooLarge(ValueError):
    """The report cannot be made to fit MAX_BODY_BYTES."""


def body_bytes(payload):
    """The size of the body EXACTLY as send_report transmits it: requests'
    json= encoder escapes non-ASCII (ensure_ascii), so measure the same way
    (review W0 M3: a UTF-8 measure undercounted CJK text 2x)."""
    return len(json.dumps(payload, default=str).encode("ascii", "backslashreplace"))


def _fit_body(payload):
    """Shrink until the body fits MAX_BODY_BYTES. Every step strictly
    shrinks a field (no header that keeps a field growing back), so the
    loop always ends; a report that still cannot fit raises ReportTooLarge
    instead of returning a body the server would refuse."""
    for key in ("log_tail", "evidence"):
        while body_bytes(payload) > MAX_BODY_BYTES and payload.get(key):
            text = str(payload[key])
            payload[key] = text[len(text) // 2:] if len(text) > 64 else ""
    while body_bytes(payload) > MAX_BODY_BYTES and payload.get("recent_errors"):
        payload["recent_errors"] = payload["recent_errors"][:-1]
    for key in ("user_question", "user_note", "last_error"):
        while body_bytes(payload) > MAX_BODY_BYTES and payload.get(key):
            text = str(payload[key])
            payload[key] = text[: len(text) // 2] if len(text) > 64 else ""
    if body_bytes(payload) > MAX_BODY_BYTES:
        raise ReportTooLarge(f"the report is larger than {MAX_BODY_BYTES} bytes")
    return payload


def build_payload(health=None, user_note="", contact_email="", *, surface="app",
                  kind="basic", report=None, ai=None, evidence=None,
                  user_question=None, reading_reference=None, include_log=True,
                  scrub_ctx=None, report_id=None, attachment=None):
    """Assemble the report, scrubbed (AIR-001 INV-3). No network, so the
    dialog can show the user exactly what Send will transmit.

    `health` is a SessionManager.health dict, or None for a general report
    unrelated to session saving. The legacy fields (SPEC-SES-001 §4.5) stay;
    schema 2 adds the AI-report fields, all optional.

    Not pure: it reads the log and the error journal. Callers snapshot the
    result and send THAT snapshot (SES-001 INV-7, AIR-001 INV-4).
    """
    import uuid

    env = describe_environment()
    health = health or {}
    surface = surface if surface in SURFACES else "app"
    kind = kind if kind in KINDS else "basic"

    payload = {
        "schema": SCHEMA_VERSION,
        "report_id": _protocol_token(report_id) or str(uuid.uuid4()),
        "kind": kind,
        "surface": surface,
        "branch_build": branch_build(),
        "app_version": app_version(),
        "edition": edition(),
        "platform": env.get("platform"),
        "python": env.get("python"),
        "qt": env.get("qt"),
        "frozen": env.get("frozen"),
        "session_health": health.get("state"),
        "consecutive_failures": health.get("consecutive_failures"),
        "total_failures": health.get("total_failures"),
        "configured_dir": redact_home(health.get("configured_dir")),
        "session_dir": redact_home(health.get("session_dir")),
        "last_error": _cap(redact_home(health.get("last_error")),
                           MAX_ERROR_CHARS),
        "last_error_at": health.get("last_error_at"),
        "user_note": (user_note or "")[:MAX_NOTE_CHARS],
        "contact_email": (contact_email or "").strip()[:200],
    }
    if kind == "basic":
        # Keep the TAIL of the tail: the last lines describe the failure.
        if include_log:
            payload["log_tail"] = _cap(read_log_tail(MAX_LOG_LINES), MAX_LOG_CHARS,
                                       keep="end")
        payload["recent_errors"] = _recent_errors(BASIC_RECENT_ERRORS)
    if ai:
        payload["ai"] = {k: _protocol_token(ai.get(k)) for k in ("engine", "model", "effort")}
    if report:
        payload["user_edited"] = bool(report.get("_user_edited", False))
        payload["report"] = clean_report(report)
    if evidence:
        payload["evidence"] = _cap(evidence, MAX_EVIDENCE_CHARS, keep="end")
    if user_question:
        payload["user_question"] = str(user_question)[:MAX_QUESTION_CHARS]
    if reading_reference:
        http = reading_reference.get("http_status")
        payload["reading_reference"] = {
            "job_id": _protocol_token(reading_reference.get("job_id")),
            "status": _protocol_token(reading_reference.get("status")),
            "http_status": http if isinstance(http, int) and not isinstance(http, bool) else None}
    # The picture is announced with its digest; the server grants an upload
    # only for these exact bytes (backend docs/bug-report-v2.md).
    payload["has_attachment"] = bool(attachment)
    if attachment:
        import hashlib
        payload["attachment_sha256"] = hashlib.sha256(attachment).hexdigest()
        payload["attachment_type"] = "image/png"

    # The final scrub: every text field, every kind (AIR-001 INV-3).
    from core.privacy_scrub import scrub_tree
    ctx = scrub_ctx if scrub_ctx is not None else default_scrub_context()
    counts = {}
    payload = scrub_tree(payload, ctx, counts, keep_keys=_PROTOCOL_PATHS,
                         log_keys=_LOG_PATHS, field_names=_FIELD_NAMES)
    payload["scrub"] = {
        "counts": {k.strip("<>"): v for k, v in sorted(counts.items())},
        "library": bool(getattr(ctx, "library_ok", False)),
    }
    return _fit_body(payload)


def payload_preview(payload):
    """Human-readable rendering of exactly what will be sent."""
    try:
        return json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    except Exception:
        return str(payload)


class SendResult:
    """What a send attempt produced. ``status`` is the HTTP status or None
    (no response); ``body`` the decoded JSON response or {}."""

    def __init__(self, ok, message, status=None, body=None):
        self.ok, self.message, self.status, self.body = ok, message, status, body or {}

    def __iter__(self):      # ok, message = send_report(...) keeps working
        return iter((self.ok, self.message))


def send_report(payload):
    """POST the report. Returns a SendResult (unpacks as (ok, message)).
    Never raises.

    Idempotent: the payload carries its ``report_id``; sending the same
    snapshot twice (a retry after a lost response) stores one report on a
    schema-2 backend (AIR-001 §4.3).

    Callers MUST offer the copy/save fallback on failure: a diagnostics
    feature that only works when the network works is worth very little, and
    the endpoint may not be deployed yet.
    """
    try:
        import requests
    except Exception:
        return SendResult(False, "The 'requests' library is not available in this build.")

    try:
        response = requests.post(
            REPORT_ENDPOINT,
            json=payload,
            timeout=SEND_TIMEOUT_SECONDS,
            headers={"Content-Type": "application/json"},
        )
    except Exception as e:
        return SendResult(False, f"Could not reach the server ({type(e).__name__}: {e}).")

    try:
        body = response.json()
        if not isinstance(body, dict):
            body = {}
    except Exception:
        body = {}
    code = response.status_code
    if 200 <= code < 300:
        return SendResult(True, "Report sent. Thank you.", code, body)
    if code == 404:
        return SendResult(False, ("The reporting service is not available yet. "
                                  "Please use Copy or Save and send it by email."), code, body)
    if code == 429:
        return SendResult(False, "Too many reports sent recently. Please try again later.",
                          code, body)
    return SendResult(False, f"The server rejected the report (HTTP {code}).", code, body)


MAX_ATTACHMENT_BYTES = 3_000_000


def upload_attachment(result, png: bytes):
    """After a report was stored: send the screenshot the user approved, with
    the presigned POST the server returned (SPEC-AIR-001 §4.4), then confirm
    it with its SHA-256. Returns (ok, message). Never raises."""
    import hashlib
    body = getattr(result, "body", None) or {}
    upload = body.get("upload") or {}
    url, fields = upload.get("url"), upload.get("fields")
    report_id = body.get("report_id")
    if not (isinstance(url, str) and url.startswith("https://") and isinstance(fields, dict)
            and isinstance(report_id, str)):
        return False, "The server did not offer a screenshot upload."
    if not png or len(png) > MAX_ATTACHMENT_BYTES:
        return False, "The screenshot is too large to send."
    try:
        import requests
        r = requests.post(url, data=fields, timeout=SEND_TIMEOUT_SECONDS * 3,
                          files={"file": ("screenshot.png", png,
                                          upload.get("content_type") or "image/png")})
        if not 200 <= r.status_code < 300:
            return False, f"The screenshot upload failed (HTTP {r.status_code})."
        done = requests.post(f"{REPORT_ENDPOINT}/{report_id}/attachment-complete",
                             json={"sha256": hashlib.sha256(png).hexdigest()},
                             timeout=SEND_TIMEOUT_SECONDS)
        if not 200 <= done.status_code < 300:
            return False, f"The screenshot could not be confirmed (HTTP {done.status_code})."
    except Exception as exc:                                      # noqa: BLE001
        return False, f"The screenshot could not be sent ({type(exc).__name__})."
    return True, "Screenshot sent."


def server_accepts(result, feature):
    """True when a schema-2 backend said it accepts `feature` (e.g.
    "screenshot"). An old backend sends no ``accepts`` list (AIR-001 §4.3)."""
    try:
        return feature in (result.body.get("accepts") or [])
    except Exception:
        return False


def save_report(payload, target_path):
    """Write the report to a file for manual sending. Returns (ok, message)."""
    try:
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload_preview(payload), encoding="utf-8")
        return True, f"Saved to {target}"
    except Exception as e:
        return False, f"Could not save the file ({type(e).__name__}: {e})."
