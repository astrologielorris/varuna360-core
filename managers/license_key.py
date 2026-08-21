# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
License-KEY authentication for Varuna360 Core/Lite.

The mobile app (Varuna_Arjuna, SPEC-LIC-MOBILE-001) does not sign users in.
It holds a license KEY that the account owner copies from their
360heartsinthesky.com account page, and exchanges that key roughly weekly for
an RSA-signed JWT via POST /license/validate-key. The JWT is verified OFFLINE
against the embedded public key, so neither the entitlement nor its expiry can
be forged by editing local storage.

This module ports that flow to the desktop Core/Lite edition. It deliberately
REUSES the existing desktop primitives in license_manager.py rather than
duplicating them:

    - get_machine_fingerprint()      device id for the server's device limit
    - _get_api_url()                 dev/prod base URL switch
    - save/load/clear_token_cache()  the machine-bound, 0o600 JWT cache
    - verify_license_token_offline() RS256 verify against the SAME embedded
                                     public key + issuer the mobile token uses
    - LicenseState / GRACE_HOURS     the shared session model + grace window

FROZEN CONTRACT (td-zoc7, settled with the website session 2026-08-19)
----------------------------------------------------------------------
Endpoint : POST /license/validate-key (the SAME URL as mobile; extended, not a
           sibling). The server ROUTES the entitlement check on `platform`:
           android -> mobile-subscription rule; a desktop OS -> the Explorateur
           rule below. The tier VALUE in the token comes from the account, not
           the platform string.
Entitlement (server-side): passes when the key's account tier is 'subscriber'
           (the €9.99 Explorateur) or 'vip'. No client logic.
Reason code: 'no_lite_entitlement' when a real key's account is not on a tier
           that includes desktop Lite (confirmed exact string).
Machine cap: SAME AS MOBILE — cap 8, EVICT-OLDEST. The server evicts the oldest
           device rather than rejecting, so on desktop 'too_many_machines' is
           not expected in normal operation; we still handle it defensively.
Token    : exp 7 days, grace_hours 168 in the response (7-day grace, mobile
           parity; frozen by Lorris 2026-08-19, superseding an earlier 72). We
           honour whatever the token carries, so these are informational.

Semantics that could still be tuned stay funnelled through the ADAPTER section
(`_REASON_MESSAGES`, `_raise_for_rejection`) so a future tweak is a one-line
change with no call-site churn.

The gate that removes account login from shipped Lite stays OFF
(LITE_KEY_AUTH_ENABLED, apps/core_gui_qt.py) until the website session ships and
deploys the server desktop branch AND Lorris green-lights the cutover. This
module is the client half, wired but not yet the default.
"""

import contextlib
import json
import os
import platform
import logging
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
import jwt

# Fallback grace when a signed token carries no grace_hours claim. Matches the
# mobile app's kDefaultGraceHours (license_service.dart:35) = 7 days, so the
# desktop key flow uses the SAME grace algorithm AND the same fallback. The
# EFFECTIVE grace is whatever the token's grace_hours claim says; the frozen
# desktop contract issues 168h (7 days, mobile parity), so this default and the
# server's claim now agree. The default only applies to a token missing the claim.
DEFAULT_GRACE_HOURS = 168
_GRACE_CLAMP_MAX_HOURS = 24 * 30  # 30 days, mirrors mobile's .clamp(0, 24*30)

# ─── No-key free trial ───────────────────────────────────────────────────────
# A packaged build runs fully for TRIAL_DAYS from its first launch with NO key,
# then requires a license key. This is the deliberate low-friction on-ramp: a
# curious user clicks and tests immediately, without going to the website for a
# key, and pays once hooked. It is also the convenient path for our own testing
# of a frozen build. The trial is anchored to a first-launch timestamp on disk;
# it only defers commitment (payers use keys). The anchor is stored ENCRYPTED and
# machine-bound (see _encode_anchor) so it is not a plaintext date a normal user
# is tempted to hand-edit, a copied or edited anchor fails authentication (fail
# closed), and it is written REDUNDANTLY to several independent locations with the
# OLDEST surviving copy winning (see _read_trial_anchor), so clearing one obvious
# cache dir does not reset it. A determined user who finds and deletes EVERY copy
# still restarts a fresh 7 days (same as a first install); that residual is by
# design, since the real paid entitlement is the signed token, not this file.
TRIAL_DAYS = 7
# Opaque filename + opaque contents: nothing here invites a text editor.
# DELIBERATELY no migration from the old plaintext "trial.json": 4.5.0 (the first
# build with any trial) has not shipped, so no plaintext anchor exists in the
# wild. A plaintext-read fallback would also REOPEN the hand-edit hole this change
# closes (an attacker could just drop a plaintext trial.json), so the new format
# is the only accepted one. A leftover plaintext file is simply ignored.
_TRIAL_FILE_NAME = "trial.dat"

# Static pepper mixed with the machine fingerprint to derive the anchor key.
# HONEST NOTE: this file is AGPL and PUBLIC, so this pepper is not a secret and
# gives NO protection against someone who reads the source. Its only job is to
# make the on-disk trial anchor opaque and tamper-EVIDENT for a normal user: the
# file is not human-readable, a hand-edited date fails Fernet authentication, and
# the blob is bound to one machine so it cannot be copied to another. Real paid
# entitlement is the signed RS256 token, which this does not touch. Determined
# bypass (delete-to-reset, build-from-source) stays possible by design.
_ANCHOR_PEPPER = b"V360-trial-anchor-v1|not-a-secret|derive-with-machine-fp|9f3c1a7e"

# Tiers whose signed token entitles the DESKTOP app. The shared verifier accepts
# any token our issuer signed (mobile tokens included), so the offline path must
# additionally check this signed `tier` claim: otherwise a cheaper Mobile token
# planted in the cache would unlock the desktop without a server round-trip.
#
# Values are the token CLAIM values the backend actually issues, confirmed
# against license_handler._validate_desktop_key / jwt_issuer.issue_license_token:
# a paying Explorateur customer's DESKTOP token carries tier="subscriber"; an
# admin/comp carries "vip". The string "explorateur" is the Stripe/config tier,
# NOT the token claim, and is never issued. The Mobile token carries
# tier="mobile" (refused); "free" never receives a token at all.
_DESKTOP_ENTITLED_TIERS = frozenset({"subscriber", "vip"})

from managers.license_manager import (
    _get_api_url,
    _get_app_version,
    _normalize_valid_until,
    get_machine_fingerprint,
    save_token_cache,
    load_token_cache,
    clear_token_cache,
    verify_license_token_offline,
    _get_cache_dir,
    LICENSE_PUBLIC_KEY,
    LICENSE_ISSUER,
    LicenseState,
    LicenseError,
    LicenseExpiredError,
    SubscriptionError,
    GRACE_HOURS,
)

logger = logging.getLogger(__name__)


def _safe_int(value, default=0) -> int:
    """int() that never raises on wrong-typed server metadata (crash guard)."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _verify_claims_ignoring_expiry(token: str) -> dict:
    """Verify RS256 signature + issuer with ONLY expiry disabled.

    Raises jwt.InvalidTokenError on any signature / issuer / parse failure, so
    a grace decision can never grant access on an unverifiable token. This is
    the single helper the grace path uses (never a bare verify_exp=False decode
    whose failure could be swallowed into a grant).
    """
    return jwt.decode(
        token, LICENSE_PUBLIC_KEY,
        algorithms=["RS256"], issuer=LICENSE_ISSUER,
        options={"verify_exp": False},
    )


def _grace_state(license_token: str):
    """Return a grace LicenseState, or None if grace does not apply.

    Mirrors the mobile app's grace classification (license_service.dart
    _classify): grace runs from the token's SIGNED `exp` claim to
    `exp + grace_hours`, where grace_hours comes from the token's own
    `grace_hours` claim (fallback DEFAULT_GRACE_HOURS, clamped to 30 days).

    Anchoring to the signed exp claim (not a local last_online timestamp) means
    grace needs no editable local state: it cannot be extended by editing the
    cache, and a 7-day token gets its full grace regardless of when we last
    reached the server. Grace is granted ONLY when the token re-verifies
    (signature + issuer, expiry ignored); any verification failure grants
    nothing (no fail-open).
    """
    try:
        claims = _verify_claims_ignoring_expiry(license_token)
    except jwt.InvalidTokenError:
        return None
    # Grace must honour the SAME desktop entitlement + machine binding as a live
    # token: an expired Mobile token, or a desktop token copied to another
    # machine, gets no grace here.
    try:
        _assert_desktop_entitlement(claims)
    except LicenseError:
        return None
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)):
        return None
    exp_dt = datetime.fromtimestamp(exp, tz=timezone.utc)

    grace_hours = claims.get("grace_hours")
    if not isinstance(grace_hours, (int, float)):
        grace_hours = DEFAULT_GRACE_HOURS
    grace_hours = max(0, min(int(grace_hours), _GRACE_CLAMP_MAX_HOURS))

    deadline = exp_dt + timedelta(hours=grace_hours)
    if datetime.now(timezone.utc) >= deadline:
        return None

    state = LicenseState()
    state.is_licensed = True
    state.grace_active = True
    state.tier = claims.get("tier", "subscriber")
    state.email = claims.get("email", "")
    state.valid_until = _normalize_valid_until(exp)
    state.license_token = license_token
    logger.info("Lite grace active until %s (grace_hours=%d)",
                deadline.isoformat(), grace_hours)
    return state

# ─── Transport contract (FROZEN mobile facts — safe to build to) ─────────
#
# POST {base}/license/validate-key
#   request : {license_key, machine_id, app_version, platform}
#   response: {valid, license_token, valid_until, tier, grace_hours,
#              server_time, machines_registered, max_machines, reason}
KEY_VALIDATE_PATH = "/license/validate-key"

# Browser link activation (SPEC-LIC-001): the desktop redeems the one-time
# code from the loopback callback for the SAME credential pair the paste path
# stores (license key + signed token).
EXCHANGE_CODE_PATH = "/license/exchange-code"

# The stored key file lives beside token.json in the same 0o600 cache dir.
_KEY_FILE_NAME = "license_key.json"


def _platform_string() -> str:
    """OS identifier sent to the server: linux / windows / darwin.

    Per the desktop-Lite contract, `platform` is the OPERATING SYSTEM, not an
    edition tag: the server derives the tier/entitlement from the key's
    account, never from a "desktop"/"lite" string. Matches the existing
    validate_license_online() convention (platform.system().lower()).
    """
    return platform.system().lower()


# ─── ADAPTER (semantics that may still move on Lorris's restructure) ─────
#
# Map a server reason code to a user-facing message + the exception class that
# carries it. This is the ONE place to edit when the website session freezes
# the desktop entitlement rule (e.g. a new `no_lite_entitlement` reason for
# "key valid but this account is not entitled to desktop Lite"). Keep the keys
# in sync with license_handler.py; unknown reasons fall back generically.
_REASON_MESSAGES = {
    "invalid_key": (
        LicenseError,
        "That license key was not recognised. Check it and try again, "
        "or copy it again from your 360heartsinthesky.com account page.",
    ),
    "subscription_expired": (
        SubscriptionError,
        "Your subscription has expired. Renew it at 360heartsinthesky.com "
        "to keep using Varuna360.",
    ),
    "no_subscription": (
        SubscriptionError,
        "This account has no active subscription. Subscribe at "
        "360heartsinthesky.com.",
    ),
    # Desktop-Lite entitlement check: a real key whose account is not on a tier
    # that includes desktop Lite (i.e. not 'subscriber'/Explorateur or 'vip').
    # 'no_lite_entitlement' is the confirmed, frozen reason string.
    "no_lite_entitlement": (
        SubscriptionError,
        "This account is not on a plan that includes the desktop app. "
        "See your options at 360heartsinthesky.com.",
    ),
    "too_many_machines": (
        SubscriptionError,
        "Device limit reached for this key. Deregister a device at "
        "360heartsinthesky.com/account, then try again.",
    ),
    # ── Browser link activation slugs (SPEC-LIC-001 §3.4) ──
    # Every one of these is an ACTIVATION-ATTEMPT outcome, never a revocation
    # (INV-8): raising them reports failure to the dialog and touches no cache.
    "access_denied": (
        LicenseError,
        "Activation was declined in the browser. Nothing was changed. "
        "You can try again, or enter your key below.",
    ),
    "not_signed_in": (
        LicenseError,
        "You are not signed in on 360heartsinthesky.com. Sign in there, "
        "then try again.",
    ),
    "expired_code": (
        LicenseError,
        "The activation link expired. Click the browser button to start again.",
    ),
    "code_used": (
        LicenseError,
        "That activation link was already used. Click the browser button "
        "to start again.",
    ),
    "pkce_failed": (
        LicenseError,
        "The activation security check failed. Click the browser button "
        "to start again.",
    ),
    "state_mismatch": (
        LicenseError,
        "The activation security check failed. Click the browser button "
        "to start again.",
    ),
    "bad_request": (
        LicenseError,
        "The activation request was refused. Try again, or enter your key.",
    ),
    "server_error": (
        LicenseError,
        "The server had a problem. Try again in a moment, or enter your key.",
    ),
    "service_unavailable": (
        LicenseError,
        "The server is temporarily unavailable. Try again in a moment, "
        "or enter your key.",
    ),
}

_GENERIC_REJECTION = (
    LicenseError,
    "This license key could not be activated. Please try again later or "
    "contact support at 360heartsinthesky.com.",
)


class KeyValidation:
    """Parsed outcome of a /license/validate-key call.

    outcome is one of: 'accepted', 'rejected', 'unreachable'.
      - accepted   -> `token` carries the signed JWT to cache
      - rejected   -> `reason` is the server's explicit verdict; only an
                      explicit 200 {valid:false} produces this
      - unreachable -> transient (network, non-200, service_unavailable):
                      never wipes a paying user's cached token
    """

    def __init__(self, outcome, token=None, reason=None,
                 machines_registered=0, max_machines=0,
                 tier="free", valid_until="", grace_hours=None,
                 server_time="", license_key=None):
        self.outcome = outcome
        self.token = token
        self.reason = reason
        self.machines_registered = machines_registered
        self.max_machines = max_machines
        self.tier = tier
        self.valid_until = valid_until
        self.grace_hours = grace_hours
        self.server_time = server_time
        # Present only on an accepted exchange-code response (SPEC-LIC-001
        # INV-1): the account's license key, stored exactly as a pasted one.
        self.license_key = license_key


def validate_key_online(license_key: str) -> KeyValidation:
    """Exchange a license key for a fresh signed token.

    Mirrors the mobile app's validateKeyOnline() rejection discipline: ANY
    non-200 (429 throttle, 5xx, gateway/WAF) and an explicit
    reason=='service_unavailable' are 'try again later', NEVER a rejection —
    a rejection can wipe a paying user's token, and only an explicit
    200 {valid:false} verdict from our own handler is trustworthy enough for
    that.
    """
    key = (license_key or "").strip()
    if not key:
        return KeyValidation("rejected", reason="invalid_key")

    url = f"{_get_api_url()}{KEY_VALIDATE_PATH}"
    payload = {
        "license_key": key,
        "machine_id": get_machine_fingerprint(),
        "app_version": _get_app_version(),
        "platform": _platform_string(),
    }

    try:
        # allow_redirects=False: the endpoint contract has no redirects, and a
        # followed 307/308 would resend the key to the redirect target. A 3xx
        # falls through to the non-200 branch of the parser (unreachable).
        resp = requests.post(url, json=payload, timeout=20,
                             allow_redirects=False)
    except requests.RequestException as e:
        logger.warning("Key validation network error: %s", e)
        return KeyValidation("unreachable")

    return _parse_validation_body(resp)


def _parse_validation_body(resp, *, require_license_key: bool = False) -> KeyValidation:
    """Parse a validate-key or exchange-code HTTP response into a KeyValidation.

    ONE parser for both endpoints so the success shape cannot drift between
    them (SPEC-LIC-001 §4.1). What differs between the endpoints is the
    OUTCOME POLICY applied by the caller, not the parsing: validate-key
    rejections may clear a stored credential (refresh path), exchange-code
    rejections never touch any cache (INV-8).

    require_license_key: exchange-code responses MUST carry the account's
    license key (INV-1); a success body without one is a malformed protocol
    response and is treated as unreachable, never as licensed (T-15: a session
    licensed without a stored key cannot survive restart). validate-key does
    not require it because the client already holds the key it sent.

    Never logs the response body (INV-5a: the exchange body carries the key).
    """
    if resp.status_code != 200:
        logger.warning("Key validation non-200 (%s) — treating as unreachable",
                       resp.status_code)
        return KeyValidation("unreachable")

    try:
        body = resp.json()
    except ValueError:
        logger.warning("Key validation returned non-JSON body")
        return KeyValidation("unreachable")

    if not isinstance(body, dict):
        return KeyValidation("unreachable")

    reason = body.get("reason")
    if not isinstance(reason, str):
        reason = None  # normalize wrong-typed reason so downstream .get() is safe
    if reason == "service_unavailable":
        return KeyValidation("unreachable")

    valid = body.get("valid")
    token = body.get("license_token")

    if valid is True and isinstance(token, str) and token:
        license_key = body.get("license_key")
        if not (isinstance(license_key, str) and license_key.strip()):
            license_key = None
        if require_license_key and license_key is None:
            # INV-1 regression guard: never license a session that cannot
            # survive restart. Malformed protocol response, not a rejection.
            logger.warning("Exchange response missing license_key — "
                           "treating as unreachable")
            return KeyValidation("unreachable")
        return KeyValidation(
            "accepted",
            token=token,
            tier=body.get("tier", "free"),
            valid_until=body.get("valid_until", "") or "",
            grace_hours=body.get("grace_hours"),
            server_time=body.get("server_time", "") or "",
            machines_registered=_safe_int(body.get("machines_registered")),
            max_machines=_safe_int(body.get("max_machines")),
            license_key=license_key,
        )

    if valid is False:
        return KeyValidation(
            "rejected",
            reason=reason or "invalid_key",
            machines_registered=_safe_int(body.get("machines_registered")),
            max_machines=_safe_int(body.get("max_machines")),
        )

    # Any OTHER 200 shape (valid missing / None / non-bool, or valid True with a
    # missing/empty/non-string token) is a malformed protocol response, NOT a
    # rejection. Only an explicit valid==False may clear a paying user's cache;
    # treat everything else as unreachable so a transient server bug is harmless.
    logger.warning("Key validation: malformed 200 body — treating as unreachable")
    return KeyValidation("unreachable")


def exchange_link_code(code: str, code_verifier: str, state: str) -> KeyValidation:
    """Redeem a browser-flow one-time code for the credential pair (SPEC-LIC-001).

    POSTs /license/exchange-code with the code, the PKCE verifier that never
    left this process (INV-4), and the flow's state, plus the same machine
    identity fields validate-key sends. The success body carries BOTH the
    account's license key and a signed token (INV-1); the key travels only in
    this TLS response body, never in a URL (INV-5).

    Outcome mapping mirrors validate_key_online: non-200 / non-JSON /
    malformed 200 / service_unavailable are 'unreachable' (retryable), an
    explicit valid:false is 'rejected'. What the CALLER does with a rejection
    differs (INV-8): an exchange rejection may only be reported, never used to
    clear an existing stored credential.

    Never logs the request or response body at any level (INV-5a).
    """
    url = f"{_get_api_url()}{EXCHANGE_CODE_PATH}"
    payload = {
        "code": code,
        "code_verifier": code_verifier,
        "state": state,
        "machine_id": get_machine_fingerprint(),
        "app_version": _get_app_version(),
        "platform": _platform_string(),
    }
    try:
        # allow_redirects=False: a followed 307/308 would resend code, state
        # and the PKCE verifier to the redirect target (INV-5a). A 3xx falls
        # through to the non-200 branch of the parser (unreachable).
        resp = requests.post(url, json=payload, timeout=20,
                             allow_redirects=False)
    except requests.RequestException as e:
        # Log the exception CLASS only: a requests error string can embed the
        # request URL and, in exotic proxy failures, request data (INV-5a).
        logger.warning("Link exchange network error (%s)", type(e).__name__)
        return KeyValidation("unreachable")
    return _parse_validation_body(resp, require_license_key=True)


def _raise_for_rejection(v: KeyValidation):
    """Translate a rejected KeyValidation into the mapped user-facing error.

    Defensive only for too_many_machines: the desktop server uses the mobile
    evict-oldest policy (cap 8), so it should not normally return this. If it
    ever does, show the cap (defaulting to 8 when the field is absent).
    """
    exc_cls, message = _REASON_MESSAGES.get(v.reason, _GENERIC_REJECTION)
    if v.reason == "too_many_machines":
        cap = v.max_machines or 8
        message = (
            f"Device limit reached ({cap} devices) for this key. "
            "Deregister a device at 360heartsinthesky.com/account, then try again."
        )
    raise exc_cls(message)


# ─── Stored key (so weekly re-validation needs no re-prompt) ─────────────

def _key_file():
    return _get_cache_dir() / _KEY_FILE_NAME


def store_license_key(license_key: str):
    """Persist the license key with 0o600 perms (same discipline as token.json).

    The key is not a secret the way a password is, but it is account-scoped, so
    it gets the same user-only permissions as the token cache.
    """
    import json
    key = (license_key or "").strip()
    if not key:
        return
    path = _key_file()
    tmp = path.with_suffix(".tmp")
    data = json.dumps({
        "license_key": key,
        "stored_at": datetime.now(timezone.utc).isoformat(),
    })
    if platform.system() != "Windows":
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        # O_CREAT's mode is ignored if tmp already exists with looser perms;
        # fchmod the descriptor so the file is 0o600 regardless.
        try:
            os.fchmod(fd, 0o600)
        except OSError:
            pass
        with os.fdopen(fd, "w") as f:
            f.write(data)
    else:
        tmp.write_text(data)
    tmp.replace(path)
    if platform.system() == "Windows":
        from managers.license_manager import _restrict_cache_file
        _restrict_cache_file(path)


def load_license_key() -> str:
    """Return the stored license key, or '' if none/unreadable.

    The activation envelope is read FIRST: it is the authoritative committed
    copy (INV-9) — the envelope replace is the transaction point, and either
    derived legacy view write after it can fail independently (disk full
    mid-activation), leaving license_key.json stale. Reading the stale legacy
    file first would hand back the pre-activation key next to the new token
    (a torn pair). The legacy file only serves pre-envelope installs.
    clear_license_key() removes the envelope too, so a revoked key cannot
    resurrect through it.
    """
    key = _read_envelope().get("license_key")
    if isinstance(key, str) and key.strip():
        return key.strip()
    path = _key_file()
    try:
        data = json.loads(path.read_text())
        if isinstance(data, dict):
            key = (data.get("license_key") or "").strip()
            if key:
                return key
    except (OSError, ValueError):
        pass
    return ""


def _stored_license_token() -> str:
    """The committed license token, envelope-first (same authority rule as
    load_license_key: the envelope pair is atomic, the legacy token.json is a
    derived view that can be stale after a partial derived-write failure)."""
    token = _read_envelope().get("license_token")
    if isinstance(token, str) and token.strip():
        return token.strip()
    cache = load_token_cache()
    return ((cache or {}).get("license_token", "") or "") if cache else ""


def clear_license_key():
    """Overwrite + delete the stored key AND any crash-left temp (logout / hard rejection).

    Also removes the activation envelope: it holds the same key, and
    load_license_key() falls back to it, so leaving it behind would resurrect
    a revoked key on the next launch.
    """
    for path in (_key_file(), _key_file().with_suffix(".tmp"), _envelope_file()):
        if path.exists():
            wiped = True
            try:
                path.write_bytes(b"\x00" * path.stat().st_size)
            except OSError:
                wiped = False
            try:
                path.unlink(missing_ok=True)
            except OSError:
                if not wiped:
                    # Neither overwrite nor unlink worked: the file still
                    # holds readable credentials and load_license_key() could
                    # resurrect them. Loud, filename only (no content).
                    logger.error("Could not clear credential file %s: it may "
                                 "still hold the revoked key", path.name)


# ─── Atomic activation commit (SPEC-LIC-001 INV-9 / D-13) ────────────────
#
# The credential SET (license key + signed token) commits as one versioned
# envelope under a cross-process lock. store_license_key() and
# save_token_cache() write two separate files through separate temp paths, so
# on their own they can neither commit the pair atomically nor arbitrate two
# concurrent activators ("latest verified wins" would be a race). The envelope
# is the arbiter and the authoritative copy; the two legacy files are derived
# views refreshed under the same lock so every existing reader keeps working.
#
# CAS discipline: an activator captures `current_activation_seq()` BEFORE its
# online validation/exchange, and the commit is discarded when a newer commit
# landed in between. A slow activation that verified before a newer one can
# therefore never overwrite it. Manual paste, browser link and the periodic
# refresh all commit through this one path.

_ENVELOPE_NAME = "activation.json"
_ACTIVATION_LOCK_NAME = "activation.lock"


def _envelope_file():
    return _get_cache_dir() / _ENVELOPE_NAME


@contextlib.contextmanager
def _activation_lock():
    """Exclusive cross-process lock on the credential set (INV-9).

    flock on POSIX, msvcrt.locking on Windows, over a dedicated lockfile in
    the cache dir. The lockfile itself carries no data.
    """
    cache_dir = _get_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    lock_path = cache_dir / _ACTIVATION_LOCK_NAME
    f = open(lock_path, "a+b")
    try:
        if platform.system() == "Windows":
            import errno as _errno
            import msvcrt
            import time as _t
            # Retry ONLY on lock contention (EACCES/EDEADLOCK, the errnos
            # _locking uses for a held lock). Any other OSError (bad
            # descriptor, invalid argument) is permanent and retrying it
            # would hang activation and dialog shutdown forever.
            _contention = {_errno.EACCES, getattr(_errno, "EDEADLOCK", -1),
                           getattr(_errno, "EDEADLK", -1)}
            while True:
                try:
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
                    break
                except OSError as e:
                    if e.errno not in _contention:
                        raise
                    _t.sleep(0.1)  # LK_LOCK gives up after ~10s; keep waiting
            try:
                yield
            finally:
                with contextlib.suppress(OSError):
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                with contextlib.suppress(OSError):
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    finally:
        f.close()


def current_activation_seq() -> int:
    """Read the stored activation_seq (0 when no envelope exists).

    Capture this BEFORE starting an online validation/exchange; pass it to
    _persist_activation so a commit that raced a newer one is discarded.
    """
    try:
        data = json.loads(_envelope_file().read_text())
        if isinstance(data, dict):
            seq = data.get("activation_seq")
            if isinstance(seq, int) and seq >= 0:
                return seq
    except (OSError, ValueError):
        pass
    return 0


def _read_envelope() -> dict:
    """Return the envelope dict, or {} when absent/unreadable."""
    try:
        data = json.loads(_envelope_file().read_text())
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}


def _commit_credentials(license_key: str, license_token: str,
                        baseline_seq: int) -> bool:
    """Atomically commit the credential pair; False = a newer commit won.

    Under the lock: CAS on activation_seq, one os.replace of the envelope
    through a temp path unique per process and attempt (two crashed writers
    can never collide on a fixed .tmp), then the derived legacy views. The
    legacy writes happen inside the same lock, and the envelope replace is the
    commit point: if a legacy write fails afterwards the envelope still holds
    the complete pair and load_license_key() falls back to it.

    D-15: the token view is written with update_online_check=False so an
    activation never resets the refresh clock; grace is anchored to the signed
    token's own exp + grace_hours, not to this timestamp.
    """
    with _activation_lock():
        stored = current_activation_seq()
        if stored > baseline_seq:
            logger.info("Activation commit discarded: a newer activation "
                        "(seq %s) already landed", stored)
            return False
        path = _envelope_file()
        tmp = path.with_name(
            f".{_ENVELOPE_NAME}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        payload = json.dumps({
            "activation_seq": stored + 1,
            "license_key": license_key,
            "license_token": license_token,
            "committed_at": datetime.now(timezone.utc).isoformat(),
        })
        try:
            if platform.system() != "Windows":
                fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                             0o600)
                try:
                    os.fchmod(fd, 0o600)
                except OSError:
                    pass
                with os.fdopen(fd, "w") as fh:
                    fh.write(payload)
            else:
                tmp.write_text(payload)
            os.replace(tmp, path)
        finally:
            with contextlib.suppress(OSError):
                tmp.unlink(missing_ok=True)
        if platform.system() == "Windows":
            from managers.license_manager import _restrict_cache_file
            _restrict_cache_file(path)
        # Derived legacy views, same lock. The envelope replace above IS the
        # commit: the pair is durable and every reader prefers the envelope,
        # so each view write is independently best-effort — a token-view
        # failure must not skip the key view, and neither failure may bubble
        # up as "activation failed" after a successful commit.
        try:
            save_token_cache(license_token=license_token, refresh_token="",
                             update_online_check=False)
        except Exception as e:
            logger.warning("Token view write failed after envelope commit "
                           "(%s); envelope remains authoritative",
                           type(e).__name__)
        try:
            store_license_key(license_key)
        except Exception as e:
            logger.warning("Key view write failed after envelope commit "
                           "(%s); envelope remains authoritative",
                           type(e).__name__)
        return True


def _clear_credentials_if_baseline(baseline_seq: int) -> bool:
    """Seq-guarded revocation: clear the credential set ONLY when no newer
    activation committed since baseline_seq was captured.

    A refresh that validates old key A can be overtaken by a browser
    activation committing key B; A's delayed rejection must then NOT erase B
    (the rejection verdict was about A, not about what is stored now). Under
    the same lock as commits: compare the stored seq to the baseline the
    caller captured BEFORE its online call; clear only on equality.

    Returns True when the clear ran, False when a newer activation was
    preserved. Clearing is best-effort inside the lock; a raised unlink can
    never divert a revocation into retained access for the CALLER's state
    (callers still return unlicensed when this returns True).
    """
    with _activation_lock():
        stored = current_activation_seq()
        if stored != baseline_seq:
            logger.warning(
                "Rejection for a superseded credential (baseline %s, stored "
                "%s): newer activation preserved, nothing cleared",
                baseline_seq, stored)
            return False
        try:
            clear_token_cache()
        except Exception:
            pass
        try:
            clear_license_key()
        except Exception:
            pass
        return True


def _persist_activation(license_key: str, license_token: str,
                        baseline_seq: int) -> LicenseState:
    """Shared persistence tail of BOTH activation paths (SPEC-LIC-001 INV-1).

    In order: offline verify + desktop entitlement assert (INV-2: the browser
    flow introduces no new way to become licensed), the atomic credential
    commit of INV-9, then mark_licensed_before(). The paste path calls this
    after validate_key_online; the browser path after exchange_link_code.

    Raises LicenseError with a user-facing message on a bad token or a
    persistence failure; a persistence failure leaves the previous credential
    set intact (atomic replace).
    """
    key = (license_key or "").strip()
    if not key:
        raise LicenseError(
            "The server returned an invalid activation response. Please try "
            "again later."
        )
    try:
        state = _state_from_token(license_token)
    except LicenseError:
        logger.warning("Server returned a token that failed offline verification")
        raise LicenseError(
            "The server returned an invalid activation token. Please try "
            "again later."
        )
    try:
        committed = _commit_credentials(key, license_token, baseline_seq)
    except LicenseError:
        raise
    except Exception as e:
        logger.warning("Could not persist activation: %s", type(e).__name__)
        raise LicenseError(
            "Varuna360 could not save the license on this computer. Check "
            "disk space and permissions, then try again."
        )
    if not committed:
        # A newer verified activation won the race (INV-9). This machine IS
        # licensed by that newer commit; report ITS state, offline only.
        stored = _read_envelope()
        try:
            return _state_from_token(stored.get("license_token", ""))
        except Exception:
            raise LicenseError(
                "Another activation completed at the same time. Restart "
                "Varuna360 to pick it up."
            )
    mark_licensed_before()  # this machine may never be offered the free trial again
    return state


class ActivationCancelled(Exception):
    """The user cancelled the flow mid-activation; nothing was persisted."""


def activate_via_link(code: str, code_verifier: str, state: str,
                      cancel_check=None) -> LicenseState:
    """Browser-flow activation: redeem the loopback code, persist like a paste.

    Raises LicenseError / SubscriptionError (mapped, user-facing) on rejection
    or unreachability. NO outcome of this function may clear or alter an
    existing stored credential (INV-8): a rejection raises and touches nothing;
    only the periodic revalidation of the STORED credential may de-license.

    cancel_check: optional zero-arg callable polled at the last moment before
    persistence. When it returns True the exchange result is DISCARDED and
    ActivationCancelled raised, so closing the dialog during the (up to 20 s)
    exchange POST honours "cancel = no state change". The one-time code is
    consumed server-side either way; a fresh flow simply issues a new one.
    """
    baseline = current_activation_seq()
    v = exchange_link_code(code, code_verifier, state)
    if cancel_check is not None and cancel_check():
        raise ActivationCancelled()
    if v.outcome == "unreachable":
        raise LicenseError(
            "Could not reach the server. Try again, or enter your key."
        )
    if v.outcome == "rejected":
        _raise_for_rejection(v)  # raises; clears nothing (INV-8)
    return _persist_activation(v.license_key, v.token, baseline)


def link_error_message(slug: str) -> str:
    """User-facing message for a browser-redirect error slug (§3.4).

    Unknown slugs fall back to the generic message; the slug itself is never
    shown (it is server-controlled text and means nothing to a customer).
    """
    entry = _REASON_MESSAGES.get(str(slug or "").strip())
    return entry[1] if entry else _GENERIC_REJECTION[1]


# ─── No-key free trial ───────────────────────────────────────────────────

def _redundant_anchor_dirs():
    """Extra base directories that each hold a copy of the trial anchor.

    Independent of the primary cache dir (XDG_DATA_HOME) so that clearing one
    obvious location does not reset the trial. These are best-effort: a base that
    is missing or unwritable is simply skipped.
    """
    if platform.system() == "Windows":
        bases = [os.environ.get("APPDATA"), os.environ.get("USERPROFILE")]
    else:
        home = Path.home()
        bases = [
            os.environ.get("XDG_CONFIG_HOME", str(home / ".config")),
            os.environ.get("XDG_CACHE_HOME", str(home / ".cache")),
        ]
    return [Path(b) / "Varuna360" / "license_cache" for b in bases if b]


def _trial_anchor_paths():
    """All on-disk locations for the trial anchor, primary first.

    The primary is the standard cache dir (so test monkeypatching of
    _get_cache_dir and existing single-file assertions keep working); the rest are
    redundant copies under independent bases. _read_trial_anchor takes the OLDEST
    valid copy across all of them, and _persist writes every location, so removing
    one file does not restart the trial. Deliberately overridable as one unit in
    tests to keep redundant writes out of the real home directory.

    NEVER raises: _get_cache_dir() may mkdir and fail, and Path.home() may raise,
    but the read/persist loops call this outside their own error handling. Each
    source is guarded independently so that one unavailable base (e.g. a read-only
    primary) still yields the other locations rather than losing the whole trial.
    """
    paths = []
    try:
        paths.append(_get_cache_dir() / _TRIAL_FILE_NAME)
    except (OSError, RuntimeError):
        pass
    try:
        for extra in _redundant_anchor_dirs():
            paths.append(extra / _TRIAL_FILE_NAME)
    except (OSError, RuntimeError):
        pass
    # De-duplicate while preserving order (bases can collapse to the same dir).
    seen, out = set(), []
    for p in paths:
        key = str(p)
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def _anchor_key() -> bytes:
    """Derive the Fernet key for the trial anchor from the pepper + machine fp.

    Binding to the machine fingerprint means an anchor blob authenticates on
    exactly one machine: copying a still-valid blob to another machine (or a VM
    clone) yields a key mismatch and the blob is rejected as if absent.
    """
    import base64
    import hashlib
    fp = get_machine_fingerprint() or ""
    digest = hashlib.sha256(_ANCHOR_PEPPER + fp.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _encode_anchor(dt) -> bytes:
    """Serialize + authenticate + encrypt the first-launch datetime.

    Fernet gives AES-128-CBC + HMAC-SHA256 (a reviewed primitive, not hand-rolled
    crypto): the output is opaque bytes with an authentication tag, so any edit
    fails decryption. Raises on a crypto/import failure so the caller fails closed.
    """
    import json
    from cryptography.fernet import Fernet
    payload = json.dumps({"first_launch": dt.isoformat()}).encode("utf-8")
    return Fernet(_anchor_key()).encrypt(payload)


def _decode_anchor(blob: bytes):
    """Return the first-launch datetime from an anchor blob, or None if invalid.

    Any tamper (edited byte, truncation, plaintext substitution) or a blob from a
    different machine fails Fernet authentication and returns None, so the caller
    treats it as no anchor and fails closed.
    """
    import json
    from cryptography.fernet import Fernet, InvalidToken
    try:
        payload = Fernet(_anchor_key()).decrypt(blob)
        data = json.loads(payload.decode("utf-8"))
    except (InvalidToken, ValueError, TypeError):
        return None
    ts = data.get("first_launch") if isinstance(data, dict) else None
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _read_trial_anchor():
    """Return the OLDEST valid first-launch datetime across all copies, or None.

    Each copy is an opaque, machine-bound, authenticated blob (see _encode_anchor).
    A missing, unreadable, tampered, or foreign-machine file contributes nothing.
    Taking the OLDEST surviving copy is what makes the redundant anchors resist a
    reset: deleting some files leaves the earliest first-launch intact, and an
    attacker who writes an extra copy can only make the date older (expire sooner)
    or fail authentication, never extend the trial. If no copy is valid, returns
    None so the trial fails closed.
    """
    found = []
    for path in _trial_anchor_paths():
        try:
            if not path.exists():
                continue
            blob = path.read_bytes()
        except OSError:
            continue
        dt = _decode_anchor(blob)
        if dt is not None:
            found.append(dt)
    return min(found) if found else None


def _write_anchor_blob(path, blob) -> bool:
    """Write one anchor copy atomically at 0o600. Returns True on success."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        if platform.system() != "Windows":
            fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try:
                os.fchmod(fd, 0o600)
            except OSError:
                pass
            with os.fdopen(fd, "wb") as f:
                f.write(blob)
        else:
            tmp.write_bytes(blob)
        tmp.replace(path)
        return True
    except OSError:
        return False


def _persist_trial_anchor(dt) -> bool:
    """Write the first-launch timestamp (0o600, encrypted) to EVERY copy and
    CONFIRM at least one landed.

    Returns True only if the anchor is afterwards readable, so a caller can fail
    CLOSED when it could not be persisted anywhere. Without the read-back a
    read-only cache dir would grant a trial that never records its start,
    restarting a fresh 7 days on every launch. Best effort per location: a base
    that is unwritable is skipped, and success needs only one surviving copy (the
    read-back also proves the encrypt/decrypt round-trips on this machine).
    """
    try:
        blob = _encode_anchor(dt)
    except Exception:
        # A crypto or import failure must not crash the boot gate; fail closed.
        logger.warning("Could not encode trial anchor")
        return False
    wrote_any = False
    for path in _trial_anchor_paths():
        if _write_anchor_blob(path, blob):
            wrote_any = True
    if not wrote_any:
        logger.warning("Could not persist trial anchor to any location")
        return False
    return _read_trial_anchor() is not None


def ensure_install_anchor():
    """Stamp the first-launch anchor now if none exists yet.

    Called at every packaged boot BEFORE the key check, so the trial window is
    measured from install time even for a user who licenses immediately and
    never triggers the trial. Without this, a day-one payer whose key is later
    revoked (caches cleared) would look anchor-less and be handed a fresh 7-day
    trial long after install. Best effort: if it cannot persist, trial_state()
    fails closed later anyway.
    """
    if _read_trial_anchor() is None:
        _persist_trial_anchor(datetime.now(timezone.utc))


def trial_state(start_if_absent: bool = True):
    """Return a LicenseState granting the free trial, or None if it has ended.

    Grants access while within TRIAL_DAYS of the persisted install anchor. On a
    fresh install with start_if_absent=True the anchor is written now (and must
    persist, or we fail closed) and the full window is granted, so a packaged
    build opens immediately with no key.

    start_if_absent=False re-evaluates an already-started trial WITHOUT creating
    an anchor (the periodic mid-run re-check, which must never revive a consumed
    trial by writing a fresh anchor).
    """
    import math
    now = datetime.now(timezone.utc)
    start = _read_trial_anchor()
    if start is None:
        if not start_if_absent:
            return None
        # Fail CLOSED if the anchor cannot be persisted (see _persist_trial_anchor).
        if not _persist_trial_anchor(now):
            return None
        start = now
    # Clock-move clamp: an anchor in the future (clock was ahead, then corrected)
    # is pinned to now, so the trial neither expires instantly nor never starts.
    # PERSIST the clamp: otherwise a user could set the clock far ahead, launch
    # once to stamp a (validly signed) future anchor, correct the clock, and get
    # a rolling fresh 7 days on every later launch as the in-memory clamp repeats.
    # Overwriting the future timestamp with now destroys that exploit on the first
    # launch. Best effort: if the rewrite fails we still grant this run (a legit
    # user is never denied), and it retries next launch.
    if start > now:
        start = now
        # If the clamp cannot be written to any location, refuse rather than grant:
        # otherwise a future anchor that stays on disk re-clamps in memory every
        # launch and rolls a fresh 7 days forever. A legit user with a genuinely
        # future anchor AND a fully unwritable disk is vanishingly rare and can
        # enter a key. When at least one copy lands, redundancy handles the rest.
        if not _persist_trial_anchor(start):
            return None
    remaining = timedelta(days=TRIAL_DAYS) - (now - start)
    if remaining.total_seconds() <= 0:
        return None
    state = LicenseState()
    state.is_licensed = True
    state.tier = "trial"
    state.is_trial = True
    state.trial_days_left = max(1, math.ceil(remaining.total_seconds() / 86400))
    state.valid_until = (start + timedelta(days=TRIAL_DAYS)).isoformat()
    return state


# ─── High-level flows ────────────────────────────────────────────────────

def _assert_desktop_entitlement(claims: dict):
    """Raise LicenseError unless `claims` entitle THIS machine to the desktop.

    Two signed claims are enforced on top of the signature/issuer/expiry check
    that produced `claims`, so a validly-signed token cannot be misused:

    - `tier` must be in _DESKTOP_ENTITLED_TIERS. A Mobile (tier="mobile") or any
      non-desktop token is refused, so it cannot unlock the desktop offline.
    - `machine_id` must equal this machine's fingerprint. The server signs the
      machine_id the client sent at activation, which is exactly
      get_machine_fingerprint() (see validate_key_online), so a token copied to
      another machine carries the original id and fails this equality there.

    Both claims must be present and matching; a missing/other/malformed value
    fails closed. tier is coerced with str() so a non-string claim (e.g. a number
    in a malformed token) raises a clean LicenseError, never an AttributeError
    that could escape a caller's `except LicenseError`.
    """
    tier = str(claims.get("tier") or "").strip().lower()
    if tier not in _DESKTOP_ENTITLED_TIERS:
        raise LicenseError("This license does not include the desktop app.")
    if claims.get("machine_id") != get_machine_fingerprint():
        raise LicenseError("This license is registered to a different device.")


def _state_from_token(token: str, grace_active: bool = False) -> LicenseState:
    """Build a LicenseState by verifying `token` offline (proves authenticity).

    Beyond signature/issuer/expiry, the desktop entitlement (tier) and machine
    binding are enforced (_assert_desktop_entitlement): a validly-signed but
    non-desktop or foreign-machine token is rejected rather than granting access.
    """
    claims = verify_license_token_offline(token)
    _assert_desktop_entitlement(claims)
    state = LicenseState()
    state.is_licensed = True
    state.tier = (claims.get("tier") or "").strip().lower()
    state.email = claims.get("email", "")
    state.valid_until = _normalize_valid_until(claims.get("exp", ""))
    state.license_token = token
    state.grace_active = grace_active
    return state


def apply_license_key(license_key: str) -> LicenseState:
    """Activate a pasted license key: validate online, cache, return state.

    Raises LicenseError / SubscriptionError (mapped, user-facing) on rejection
    or when the server is unreachable. On success the signed token and the key
    are both cached so future launches restore silently and re-validate weekly.

    Persistence goes through _persist_activation (SPEC-LIC-001 INV-1): the
    same offline verify + entitlement assert + atomic envelope commit the
    browser flow uses, with the seq baseline captured BEFORE the online call
    so a slow activation can never overwrite a newer one (INV-9).
    """
    baseline = current_activation_seq()
    v = validate_key_online(license_key)

    if v.outcome == "unreachable":
        raise LicenseError(
            "Could not reach the license server. Check your connection and "
            "try again."
        )
    if v.outcome == "rejected":
        _raise_for_rejection(v)

    state = _persist_activation((license_key or "").strip(), v.token, baseline)
    logger.info("License key activated (tier=%s)", state.tier)
    return state


def attempt_key_login() -> LicenseState:
    """Restore a Lite session from the cached key/token, offline-first.

    1. Offline-verify the cached JWT — valid -> licensed, no network.
    2. Expired -> re-validate the stored KEY online for a fresh token.
    3. Server unreachable -> grace window (last_online_check + GRACE_HOURS).
    4. Server rejects -> clear caches, unlicensed.

    Unlike attempt_cached_login(), this path honours NO developer bypass: the
    key flow is the new surface and deliberately does not carry the
    VARUNA360_DEV_BYPASS affordance.
    """
    state = LicenseState()
    stored_key = load_license_key()

    # The KEY is the credential in this flow. With no stored key we grant
    # nothing from a cached token alone: that stops an account-path token.json
    # (present at cutover) or a token transplanted from another machine from
    # satisfying the key gate without a key ever being presented.
    if not stored_key:
        return state

    license_token = _stored_license_token()

    # 1. Offline verify the cached JWT.
    if license_token:
        try:
            return _state_from_token(license_token)
        except LicenseExpiredError:
            pass  # fall through to online re-validation / grace
        except LicenseError:
            logger.warning("Cached Lite token tampered/invalid — clearing")
            clear_token_cache()
            license_token = ""

    # 2. Token expired or absent — re-validate the stored key online.
    baseline = current_activation_seq()
    v = validate_key_online(stored_key)
    if v.outcome == "accepted":
        try:
            fresh = _state_from_token(v.token)
        except LicenseError:
            fresh = None
        if fresh is not None:
            # Same lock + seq as activation (INV-9): a concurrent activation
            # that landed mid-validation wins the disk; this session is
            # licensed by its own verified token either way.
            try:
                _commit_credentials(stored_key, v.token, baseline)
            except Exception:
                logger.warning("Could not persist re-validated token; "
                               "will re-validate next launch")
            logger.info("Lite key re-validated (tier=%s)", fresh.tier)
            return fresh
    elif v.outcome == "rejected":
        logger.warning("Stored Lite key rejected (%s) — clearing caches", v.reason)
        if not _clear_credentials_if_baseline(baseline):
            # A newer activation committed while this key was being checked;
            # the rejection was about the OLD key. Boot from the new pair.
            try:
                return _state_from_token(_read_envelope().get("license_token", ""))
            except Exception:
                pass
        return state  # unlicensed
    # unreachable -> fall through to grace

    # 3. Grace on an expired-but-authentic token we could not refresh. Grace is
    #    anchored to the token's signed exp + grace_hours claim (mobile algo),
    #    so it re-verifies the signature and needs no local timestamp.
    if license_token:
        graced = _grace_state(license_token)
        if graced is not None:
            return graced

    logger.info("No valid Lite key/token and beyond grace — key entry required")
    return state


def refresh_key_license(state: LicenseState) -> LicenseState:
    """Periodic (weekly/12h) re-validation of the stored key.

    Returns a NEW LicenseState; never mutates the original (thread safety),
    mirroring refresh_license(). A transient failure keeps the current state
    (grace handles it); only an explicit server rejection revokes access.

    This function must NEVER raise: a raised refresh reaches only the worker's
    error signal, which the GUI logs while RETAINING the old licensed state, so a
    persistent filesystem/exception would keep a session licensed indefinitely.
    Any unexpected error therefore falls to _enforce_cached_or_revoke(), which
    bounds access to the cached token's own validity + grace window.
    """
    try:
        stored_key = load_license_key()
    except Exception:
        stored_key = ""

    if stored_key:
        try:
            baseline = current_activation_seq()
        except Exception:
            baseline = 0
        try:
            v = validate_key_online(stored_key)
        except Exception:
            v = None

        if v is not None and v.outcome == "rejected":
            # TERMINAL for the key that was checked: an explicit rejection
            # ALWAYS revokes IT, whether or not cache cleanup succeeds. But a
            # newer activation that committed mid-check was NOT what the
            # server rejected — the seq guard preserves it and this refresh
            # reports the newer credential's state instead.
            try:
                cleared = _clear_credentials_if_baseline(baseline)
            except Exception:
                cleared = True  # lock failure: fail closed, revoke
            if not cleared:
                try:
                    return _state_from_token(
                        _read_envelope().get("license_token", ""))
                except Exception:
                    pass  # newer pair unreadable — fall through to revoke
            logger.warning("Lite key rejected during refresh (%s) — access revoked",
                           getattr(v, "reason", ""))
            return LicenseState()  # is_licensed False, tier 'free'

        if v is not None and v.outcome == "accepted":
            try:
                fresh = _state_from_token(v.token)
                # Same lock + seq as activation (INV-9); a lost race to a
                # newer activation leaves the newer credentials in place.
                _commit_credentials(stored_key, v.token, baseline)
                return fresh
            except Exception:
                pass  # bad/non-entitled/malformed token — bounded local enforcement
        # unreachable / no result / accepted-bad-token -> bounded local enforcement

    # No stored key, a transient failure, a bad token, OR an unexpected error all
    # converge here: retain access ONLY while the cached JWT is cryptographically
    # valid AND entitled. This must NOT raise (a raised refresh leaves the GUI
    # holding the old licensed state), so any error here revokes (fail closed).
    try:
        return _enforce_cached_or_revoke(state)
    except Exception:
        logger.warning("Local enforcement raised during refresh — revoking", exc_info=True)
        return LicenseState()


# ─── "Has ever been licensed" marker (trial-abuse guard) ─────────────────────

_LICENSED_MARKER_NAME = "licensed_before.marker"


def _licensed_marker_file():
    return _get_cache_dir() / _LICENSED_MARKER_NAME


def mark_licensed_before():
    """Record that this machine activated a real key at least once.

    A machine that has ever been licensed must NOT be handed the no-key free
    trial again: a former payer whose subscription lapses re-enters their key,
    they do not get a fresh 7 days. This marker makes that guard robust even when
    the trial anchor failed to persist on the original licensed launch (which
    would otherwise let a later revocation stamp a brand-new anchor). Best effort:
    a write failure only weakens the guard, never grants anything.
    """
    try:
        _licensed_marker_file().write_text(datetime.now(timezone.utc).isoformat())
    except OSError:
        logger.warning("Could not write licensed-before marker")


def has_been_licensed() -> bool:
    """True if this machine has ever activated a real key (see mark_licensed_before)."""
    return _licensed_marker_file().exists()


def _enforce_cached_or_revoke(state: LicenseState) -> LicenseState:
    """Keep `state` iff the cached JWT is still valid, entitled, and within grace.

    The cached token is re-checked for desktop entitlement + machine binding, not
    just signature/expiry: otherwise swapping an unexpired Mobile (or foreign)
    token into the cache after boot would preserve access through this periodic
    path. Any unexpected error revokes (fail closed) rather than keeping access.
    """
    try:
        cache = load_token_cache()
    except Exception:
        return LicenseState()
    token = (cache or {}).get("license_token", "") if cache else ""
    if token:
        try:
            claims = verify_license_token_offline(token)
            _assert_desktop_entitlement(claims)
            return state  # still unexpired, entitled, bound — keep current state
        except LicenseExpiredError:
            try:
                graced = _grace_state(token)  # itself asserts entitlement + binding
            except Exception:
                graced = None
            if graced is not None:
                return graced
        except Exception:
            # tampered / non-entitled / foreign machine / malformed claim / any
            # unexpected error — fall through to revoke (fail closed).
            pass
    return LicenseState()  # beyond grace or no valid entitled token — revoke
