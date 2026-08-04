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


def build_payload(health=None, user_note="", contact_email=""):
    """Assemble the report. Pure and side-effect free, so the dialog can show
    the user exactly what Send will transmit.

    `health` is a SessionManager.health dict, or None for a general report
    unrelated to session saving.
    """
    env = describe_environment()
    health = health or {}

    payload = {
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
        # Keep the TAIL of the tail: the last lines are the ones describing
        # the failure being reported. Truncating the front would throw away
        # the most relevant part.
        "log_tail": _cap(read_log_tail(MAX_LOG_LINES), MAX_LOG_CHARS,
                         keep="end"),
        "user_note": (user_note or "")[:MAX_NOTE_CHARS],
        "contact_email": (contact_email or "").strip()[:200],
    }
    return payload


def payload_preview(payload):
    """Human-readable rendering of exactly what will be sent."""
    try:
        return json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    except Exception:
        return str(payload)


def send_report(payload):
    """POST the report. Returns (ok, message). Never raises.

    Callers MUST offer the copy/save fallback on failure: a diagnostics
    feature that only works when the network works is worth very little, and
    the endpoint may not be deployed yet.
    """
    try:
        import requests
    except Exception:
        return False, "The 'requests' library is not available in this build."

    try:
        response = requests.post(
            REPORT_ENDPOINT,
            json=payload,
            timeout=SEND_TIMEOUT_SECONDS,
            headers={"Content-Type": "application/json"},
        )
    except Exception as e:
        return False, f"Could not reach the server ({type(e).__name__}: {e})."

    if 200 <= response.status_code < 300:
        return True, "Report sent. Thank you."
    if response.status_code == 404:
        return False, ("The reporting service is not available yet. "
                       "Please use Copy or Save and send it by email.")
    if response.status_code == 429:
        return False, "Too many reports sent recently. Please try again later."
    return False, f"The server rejected the report (HTTP {response.status_code})."


def save_report(payload, target_path):
    """Write the report to a file for manual sending. Returns (ok, message)."""
    try:
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload_preview(payload), encoding="utf-8")
        return True, f"Saved to {target}"
    except Exception as e:
        return False, f"Could not save the file ({type(e).__name__}: {e})."
