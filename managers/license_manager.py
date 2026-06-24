# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
License Manager for Varuna360 Desktop App.

Handles:
- Firebase REST API authentication (email/password)
- License token validation via 360hearts API
- RSA JWT verification with embedded public key
- Encrypted local token cache (machine-bound)
- Machine fingerprint generation
- Offline grace period (72 hours)
"""

import os
import sys
import json
import hashlib
import functools
import logging
import platform
import uuid
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import requests
import jwt

logger = logging.getLogger(__name__)

# Firebase REST API (public key — safe to embed)
FIREBASE_API_KEY = "AIzaSyBnOADtG6JL5vjtMk3lXThd__CoaGvF1nY"
FIREBASE_AUTH_URL = "https://identitytoolkit.googleapis.com/v1/accounts"

# License API
API_BASE_URL = "https://api.360heartsinthesky.com"
API_DEV_URL = "http://localhost:8000"

# JWT verification
LICENSE_ISSUER = "360hearts-license-server"

# Grace period
GRACE_HOURS = 72

# Embedded RSA public key for offline JWT verification
# This is a PUBLIC key — safe to embed in the binary
LICENSE_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAsTRLI90BRVgCZFH95KJF
PMHWceUILTWFxSIoJDMevWUf4xkjf0lYL7LLm3hmOWY9QM0KqGRuXLu8RDgZcroq
WU5K2g51F2Ev4MRgqtk4/bX0DgkU4lpB7Kel9yYBKSbDbpBZiUXZQBSfDwRm7h+N
uy57ogTqi3qfAn2nbdZjkcmzUvLRKjHxbIzGbJwg3yGl2qMnJGgLz1J0CEsNRNAH
iq/rSy+81EGwLaumYX0VrJVxVpFDkAGBCfSrSEMYKJ0BzTsbz2NHVMDJbU859Y6y
YWWSY2XQFh0QvDrRIqEXKcv3TDWL61RmMAZW1X2Fqh0urDwRtbmF/pHITs3KJXaE
twIDAQAB
-----END PUBLIC KEY-----"""


def _get_api_url() -> str:
    """Return API base URL (dev or production)."""
    if os.environ.get("VARUNA_DEV"):
        return API_DEV_URL
    return API_BASE_URL


def _normalize_valid_until(value) -> str:
    """Normalize valid_until to ISO 8601 string, regardless of source type.

    Offline JWT returns exp as int (Unix timestamp), online API returns string.
    """
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
    return str(value) if value else ""


def _get_cache_dir() -> Path:
    """Return platform-specific cache directory."""
    if platform.system() == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    cache_dir = base / "Varuna360" / "license_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


# ─── Machine Fingerprint ────────────────────────────────────────────

def _get_machine_id() -> str:
    """Get or create a stable machine identifier.

    Tries OS-level IDs first (Linux machine-id, Windows MachineGuid),
    falls back to a persistent installation UUID.
    """
    if platform.system() == "Linux":
        try:
            return Path("/etc/machine-id").read_text().strip()
        except (FileNotFoundError, PermissionError):
            pass
    elif platform.system() == "Windows":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
            )
            guid, _ = winreg.QueryValueEx(key, "MachineGuid")
            return guid
        except Exception:
            pass

    # Fallback: persistent installation ID (survives NIC/hardware changes)
    install_id_file = _get_cache_dir() / "installation_id"
    if install_id_file.exists():
        try:
            return install_id_file.read_text().strip()
        except OSError:
            pass
    new_id = str(uuid.uuid4())
    try:
        install_id_file.write_text(new_id)
        logger.info("Generated new installation ID: %s", new_id[:8])
    except OSError:
        pass
    return new_id


@functools.lru_cache(maxsize=1)
def get_machine_fingerprint() -> str:
    """Generate a stable hardware fingerprint for this machine (cached).

    Uses OS + architecture + machine-id. Does NOT use MAC address (too volatile
    across VM migrations, VPN toggles, NIC changes) or platform.processor()
    (returns empty on some Linux systems).
    """
    components = []
    components.append(f"os:{platform.system()}-{platform.machine()}")
    mid = _get_machine_id()
    if mid:
        components.append(f"mid:{mid}")
    raw = "|".join(sorted(components))
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _legacy_fingerprint() -> str:
    """Compute the old-format fingerprint for migration of existing caches.

    Old format included MAC address and CPU identifier, which are volatile.
    """
    components = []
    mac = uuid.getnode()
    components.append(f"mac:{mac}")
    components.append(f"os:{platform.system()}-{platform.machine()}")
    if platform.system() == "Linux":
        try:
            mid = Path("/etc/machine-id").read_text().strip()
            components.append(f"mid:{mid}")
        except (FileNotFoundError, PermissionError):
            pass
    elif platform.system() == "Windows":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
            )
            guid, _ = winreg.QueryValueEx(key, "MachineGuid")
            components.append(f"mid:{guid}")
        except Exception:
            pass
    components.append(f"cpu:{platform.processor()}")
    raw = "|".join(sorted(components))
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


# ─── Firebase REST Auth ──────────────────────────────────────────────

def firebase_login(email: str, password: str) -> dict:
    """
    Authenticate with Firebase via REST API.

    Returns: {"id_token": str, "refresh_token": str, "email": str, "uid": str}
    Raises: LicenseError on failure.
    """
    url = f"{FIREBASE_AUTH_URL}:signInWithPassword?key={FIREBASE_API_KEY}"
    payload = {
        "email": email,
        "password": password,
        "returnSecureToken": True,
    }

    try:
        resp = requests.post(url, json=payload, timeout=15)
        data = resp.json()

        if resp.status_code != 200:
            error_msg = data.get("error", {}).get("message", "Unknown error")
            raise LicenseError(f"Login failed: {error_msg}")

        return {
            "id_token": data["idToken"],
            "refresh_token": data["refreshToken"],
            "email": data["email"],
            "uid": data["localId"],
        }

    except requests.RequestException as e:
        raise LicenseError(f"Network error during login: {e}")


# ─── Google OAuth for Desktop ────────────────────────────────────────

GOOGLE_AUTH_DOMAIN = "heartsinthesky-auth.firebaseapp.com"
_OAUTH_PREFERRED_PORTS = [8923, 8924, 8925]


def _bind_oauth_server(handler_class) -> "HTTPServer":
    """Create and bind OAuth callback server, trying preferred ports then ephemeral.

    Binds directly (no TOCTOU gap between port check and bind).
    """
    from http.server import HTTPServer
    for port in _OAUTH_PREFERRED_PORTS:
        try:
            server = HTTPServer(("127.0.0.1", port), handler_class)
            return server
        except OSError:
            continue
    # Fall back to OS-assigned ephemeral port
    server = HTTPServer(("127.0.0.1", 0), handler_class)
    return server


def _exchange_google_token_for_firebase(google_token: str) -> dict:
    """
    Exchange a Google OAuth token for a Firebase ID token + refresh token
    via Firebase's signInWithIdp REST endpoint.

    Tries id_token format first, falls back to access_token format.
    Returns: {"id_token": str, "refresh_token": str, "email": str}
    """
    url = f"{FIREBASE_AUTH_URL}:signInWithIdp?key={FIREBASE_API_KEY}"

    # Try as id_token first (Google ID token from OAuth redirect)
    for token_key in ("id_token", "access_token"):
        payload = {
            "postBody": f"{token_key}={google_token}&providerId=google.com",
            "requestUri": "http://localhost",
            "returnIdpCredential": True,
            "returnSecureToken": True,
        }
        try:
            resp = requests.post(url, json=payload, timeout=15)
            data = resp.json()

            if resp.status_code == 200 and "idToken" in data:
                return {
                    "id_token": data["idToken"],
                    "refresh_token": data.get("refreshToken", ""),
                    "email": data.get("email", ""),
                }

            error_msg = data.get("error", {}).get("message", "")
            # INVALID_IDP_RESPONSE means wrong token type — try the other format
            if "INVALID_IDP_RESPONSE" in error_msg and token_key == "id_token":
                continue
            raise LicenseError(f"Firebase token exchange failed: {error_msg or 'Unknown error'}")

        except requests.RequestException as e:
            raise LicenseError(f"Network error during token exchange: {e}")

    raise LicenseError("Could not exchange Google token for Firebase session.")


def google_oauth_login() -> "LicenseState":
    """
    Google OAuth login flow for desktop app.

    Opens browser → Google consent → redirects to localhost → exchanges
    code for Firebase ID token → validates license.
    """
    import webbrowser
    import urllib.parse
    from http.server import BaseHTTPRequestHandler

    # Storage for the OAuth result
    oauth_result = {"id_token": None, "error": None}

    class OAuthCallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)

            # Extract the token or error from callback
            if "id_token" in params:
                oauth_result["id_token"] = params["id_token"][0]
            elif "error" in params:
                oauth_result["error"] = params["error"][0]

            # Also check fragment (hash) params sent via POST-redirect
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"""
            <html><body style="background:#1a1a2e;color:#d4af37;font-family:sans-serif;
            display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
            <div style="text-align:center">
            <h1>Varuna360</h1>
            <p>Sign-in complete. You can close this tab.</p>
            <script>
                // Firebase redirects with token in URL fragment
                const hash = window.location.hash.substring(1);
                const params = new URLSearchParams(hash);
                const idToken = params.get('id_token') || params.get('access_token');
                if (idToken) {
                    fetch('/token?id_token=' + encodeURIComponent(idToken));
                }
                // Also try query params
                const query = new URLSearchParams(window.location.search);
                const qToken = query.get('id_token');
                if (qToken) {
                    fetch('/token?id_token=' + encodeURIComponent(qToken));
                }
                setTimeout(() => window.close(), 2000);
            </script>
            </div></body></html>
            """)

        def log_message(self, format, *args):
            pass  # Suppress HTTP server logs

    # Bind server directly (no TOCTOU gap between port check and bind)
    server = _bind_oauth_server(OAuthCallbackHandler)
    server.timeout = 120  # 2 minute timeout
    port = server.server_address[1]

    # Build sign-in URL with the actual bound port
    signin_url = (
        f"https://{GOOGLE_AUTH_DOMAIN}/"
        f"__/auth/handler?"
        f"apiKey={FIREBASE_API_KEY}&"
        f"authType=signInViaRedirect&"
        f"providerId=google.com&"
        f"scopes=email%20profile&"
        f"redirectUrl=http%3A%2F%2Flocalhost%3A{port}%2Fcallback"
    )

    # Open browser
    logger.info("Opening Google sign-in in browser (port %d)...", port)
    webbrowser.open(signin_url)

    # Handle requests until we get the token or timeout
    # (browsers may send extra requests like favicon between the redirect and JS fetch)
    deadline = time.monotonic() + 120
    while not oauth_result["id_token"] and not oauth_result["error"]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        server.timeout = min(remaining, 30)
        server.handle_request()
    server.server_close()

    if oauth_result.get("error"):
        raise LicenseError(f"Google sign-in failed: {oauth_result['error']}")

    google_token = oauth_result.get("id_token")
    if not google_token:
        raise LicenseError(
            "Could not receive Google sign-in token. "
            "Try email/password login instead."
        )

    # Exchange Google token for Firebase session (ID token + refresh token)
    fb = _exchange_google_token_for_firebase(google_token)

    # Validate license with the Firebase ID token
    result = validate_license_online(fb["id_token"])

    state = LicenseState()
    state.is_licensed = True
    state.tier = result.get("tier", "subscriber")
    state.email = fb.get("email", result.get("email", ""))
    state.valid_until = _normalize_valid_until(result.get("valid_until", ""))
    state.license_token = result.get("license_token", "")
    state.firebase_refresh_token = fb["refresh_token"]

    # Cache tokens — now with refresh token for silent renewal
    save_token_cache(
        license_token=state.license_token,
        refresh_token=fb["refresh_token"],
    )

    logger.info("Google OAuth login successful for %s", state.email)
    return state


def firebase_refresh_token(refresh_token: str) -> dict:
    """
    Refresh a Firebase ID token using the refresh token.

    Returns: {"id_token": str, "refresh_token": str}
    """
    url = f"https://securetoken.googleapis.com/v1/token?key={FIREBASE_API_KEY}"
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }

    try:
        resp = requests.post(url, data=payload, timeout=15)  # form-encoded, not JSON
        data = resp.json()

        if resp.status_code != 200:
            error_msg = data.get("error", {}).get("message", "Unknown error")
            raise LicenseError(f"Token refresh failed: {error_msg}")

        return {
            "id_token": data["id_token"],
            "refresh_token": data["refresh_token"],
        }

    except requests.RequestException as e:
        raise LicenseError(f"Network error during token refresh: {e}")


# ─── License Validation ─────────────────────────────────────────────

def validate_license_online(firebase_id_token: str) -> dict:
    """
    Call the license validation API.

    Returns the server response dict with license_token, tier, etc.
    Raises: LicenseError on failure.
    """
    url = f"{_get_api_url()}/license/validate"
    headers = {"Authorization": f"Bearer {firebase_id_token}"}
    payload = {
        "machine_id": get_machine_fingerprint(),
        "app_version": _get_app_version(),
        "platform": platform.system().lower(),
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=20)
        data = resp.json()

        if resp.status_code == 401:
            raise LicenseError("Authentication expired. Please log in again.")
        if resp.status_code != 200:
            raise LicenseError(f"License validation failed: {data.get('detail', 'Unknown error')}")

        if not data.get("valid"):
            reason = data.get("reason", "unknown")
            if reason == "no_subscription":
                raise SubscriptionError("No active subscription. Subscribe at 360heartsinthesky.com")
            elif reason == "subscription_expired":
                raise SubscriptionError("Your subscription has expired. Please renew.")
            elif reason == "too_many_machines":
                max_m = data.get("max_machines", 2)
                raise SubscriptionError(
                    f"Device limit reached ({max_m} devices). "
                    "Deregister a device at 360heartsinthesky.com/account"
                )
            else:
                raise LicenseError(f"License validation failed: {reason}")

        return data

    except requests.RequestException as e:
        raise LicenseError(f"Network error: {e}")


def verify_license_token_offline(token: str) -> dict:
    """
    Verify a cached license JWT using the embedded public key.

    Returns decoded claims if valid.
    Raises: LicenseError if invalid/expired.
    """
    try:
        decoded = jwt.decode(
            token,
            LICENSE_PUBLIC_KEY,
            algorithms=["RS256"],
            issuer=LICENSE_ISSUER,
        )
        return decoded
    except jwt.ExpiredSignatureError:
        raise LicenseExpiredError("License token expired")
    except jwt.InvalidTokenError as e:
        raise LicenseError(f"Invalid license token: {e}")


# ─── Token Cache ─────────────────────────────────────────────────────

def _restrict_cache_file(file_path: Path):
    """Restrict token cache file to current user only."""
    if platform.system() == "Windows":
        try:
            import subprocess
            username = os.environ.get("USERNAME", "")
            if not username:
                return
            subprocess.run(
                ["icacls", str(file_path), "/inheritance:r",
                 "/grant:r", f"{username}:(F)"],
                capture_output=True, timeout=5, check=True,
            )
        except Exception as e:
            logger.warning("Failed to set Windows ACL on cache: %s", e)
    else:
        try:
            file_path.chmod(0o600)
        except OSError as e:
            logger.warning("Failed to set permissions on cache: %s", e)


def save_token_cache(license_token: str, refresh_token: str,
                     update_online_check: bool = True):
    """Save license + refresh tokens to local cache.

    Args:
        update_online_check: If False, preserves the existing last_online_check
            timestamp (used when saving a rotated refresh token before validation
            confirms the license is still active — avoids resetting grace clock).
    """
    cache_dir = _get_cache_dir()

    # Preserve existing last_online_check if requested
    last_online = datetime.now(timezone.utc).isoformat()
    if not update_online_check:
        # Read cache file directly (not via load_token_cache to avoid recursion)
        cache_file = cache_dir / "token.json"
        if cache_file.exists():
            try:
                existing = json.loads(cache_file.read_text())
                if isinstance(existing, dict) and "last_online_check" in existing:
                    last_online = existing["last_online_check"]
            except (json.JSONDecodeError, OSError):
                pass

    cache_data = {
        "license_token": license_token,
        "refresh_token": refresh_token,
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "last_online_check": last_online,
        "machine_id": get_machine_fingerprint(),
    }

    cache_file = cache_dir / "token.json"
    tmp_file = cache_file.with_suffix(".tmp")

    # Write to temp file with restricted permissions from the start
    if platform.system() != "Windows":
        # Create file with 0o600 from the start (never world-readable)
        fd = os.open(str(tmp_file), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(json.dumps(cache_data, indent=2))
    else:
        tmp_file.write_text(json.dumps(cache_data, indent=2))

    tmp_file.replace(cache_file)  # atomic on POSIX

    # Apply ACL on Windows (icacls); Linux already has 0o600 from os.open
    if platform.system() == "Windows":
        _restrict_cache_file(cache_file)

    logger.info("License token cached at %s", cache_file)


def load_token_cache() -> Optional[dict]:
    """Load cached tokens. Returns None if no cache or unreadable."""
    cache_file = _get_cache_dir() / "token.json"
    if not cache_file.exists():
        return None

    try:
        data = json.loads(cache_file.read_text())
        if not isinstance(data, dict):
            logger.warning("Corrupt token cache: expected dict, got %s", type(data).__name__)
            return None

        cached_mid = data.get("machine_id")
        current_mid = get_machine_fingerprint()

        if cached_mid == current_mid:
            return data

        # Check legacy fingerprint for one-time migration
        if cached_mid == _legacy_fingerprint():
            logger.info("Migrating cache from legacy fingerprint to new format")
            data["machine_id"] = current_mid
            save_token_cache(data.get("license_token", ""), data.get("refresh_token", ""))
            return data

        logger.warning("Cache machine mismatch — ignoring cached token")
        return None
    except (json.JSONDecodeError, KeyError, AttributeError) as e:
        logger.warning("Corrupt token cache: %s", e)
        return None


def clear_token_cache():
    """Remove cached tokens (logout).

    Security exception to the 'never delete' project rule:
    Credentials are overwritten with zeros then deleted (not trashed)
    to prevent sensitive tokens from persisting in a user-browsable folder.
    """
    cache_file = _get_cache_dir() / "token.json"
    if cache_file.exists():
        try:
            cache_file.write_bytes(b'\x00' * cache_file.stat().st_size)
        except OSError:
            pass  # best effort — file might be locked
        cache_file.unlink(missing_ok=True)
        logger.info("Token cache cleared (overwritten + deleted)")


# ─── High-Level License Flow ─────────────────────────────────────────

class LicenseState:
    """Tracks the current license state for the app session."""

    def __init__(self):
        self.is_licensed = False
        self.tier = "free"
        self.email = ""
        self.valid_until = ""
        self.firebase_refresh_token = ""
        self.license_token = ""
        self.grace_active = False

    def to_dict(self) -> dict:
        return {
            "is_licensed": self.is_licensed,
            "tier": self.tier,
            "email": self.email,
            "valid_until": self.valid_until,
            "grace_active": self.grace_active,
        }


def attempt_cached_login() -> LicenseState:
    """
    Try to restore a session from cached tokens.

    1. Check for developer bypass (environment variable)
    2. Load cached token
    3. Verify JWT offline (check signature + expiry)
    4. If JWT expired, try online refresh using cached refresh token
    5. If refresh fails and within grace period, allow with grace flag
    6. If beyond grace, require online re-validation
    """
    state = LicenseState()

    # Developer bypass — set VARUNA360_DEV_BYPASS=1 in your environment
    if os.environ.get("VARUNA360_DEV_BYPASS") == "1":
        state.is_licensed = True
        state.tier = "developer"
        state.email = "dev@local"
        logger.info("Developer bypass active (environment variable)")
        return state

    cache = load_token_cache()

    if cache is None:
        return state

    license_token = cache.get("license_token", "")
    refresh_token = cache.get("refresh_token", "")
    last_online = cache.get("last_online_check", "")

    # Try offline JWT verification
    expired_claims = None
    try:
        claims = verify_license_token_offline(license_token)
        state.is_licensed = True
        state.tier = claims.get("tier", "subscriber")
        state.email = claims.get("email", "")
        state.valid_until = _normalize_valid_until(claims.get("exp", ""))
        state.license_token = license_token
        state.firebase_refresh_token = refresh_token
        logger.info("Cached license valid for %s (tier=%s)", state.email, state.tier)
        return state
    except LicenseExpiredError:
        # Token was valid but expired — extract claims for grace period use
        try:
            expired_claims = jwt.decode(
                license_token, LICENSE_PUBLIC_KEY,
                algorithms=["RS256"], issuer=LICENSE_ISSUER,
                options={"verify_exp": False},
            )
        except jwt.InvalidTokenError:
            pass
    except LicenseError as e:
        # Token is tampered/invalid — no grace, force re-login
        logger.warning("Invalid cached token (tampered?): %s", e)
        clear_token_cache()
        return state

    # JWT expired — try silent refresh using cached refresh token
    if refresh_token:
        try:
            logger.info("JWT expired — attempting silent refresh...")
            fb = firebase_refresh_token(refresh_token)

            # Save new refresh token IMMEDIATELY — Firebase rotates tokens on use,
            # so the old one in cache is now invalid. If we crash or validation fails
            # below, at least the new refresh token is preserved for next launch.
            # Don't reset last_online_check — validation hasn't confirmed yet.
            save_token_cache(
                license_token=license_token,  # keep old JWT for now
                refresh_token=fb["refresh_token"],
                update_online_check=False,
            )

            result = validate_license_online(fb["id_token"])

            state.is_licensed = True
            state.tier = result.get("tier", "subscriber")
            state.email = result.get("email", "")
            state.valid_until = _normalize_valid_until(result.get("valid_until", ""))
            state.license_token = result.get("license_token", "")
            state.firebase_refresh_token = fb["refresh_token"]

            # Update cache with the fresh license token too
            save_token_cache(
                license_token=state.license_token,
                refresh_token=fb["refresh_token"],
            )

            logger.info("Silent refresh successful for %s (tier=%s)", state.email, state.tier)
            return state
        except SubscriptionError as e:
            # Subscription cancelled/expired — deny access, clear cache
            logger.warning("Subscription invalid during refresh: %s", e)
            clear_token_cache()
            return state  # is_licensed remains False
        except LicenseError as e:
            logger.warning("Silent refresh failed: %s", e)
            # Fall through to grace period check

    # Refresh failed or no refresh token — check grace period
    if last_online:
        try:
            last_dt = datetime.fromisoformat(last_online)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            hours_since = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600

            if hours_since <= GRACE_HOURS:
                # Grace period active — allow with flag, preserve tier/email from expired JWT
                state.is_licensed = True
                state.grace_active = True
                state.tier = (expired_claims or {}).get("tier", "subscriber")
                state.email = (expired_claims or {}).get("email", "")
                state.valid_until = _normalize_valid_until((expired_claims or {}).get("exp", ""))
                state.license_token = license_token
                state.firebase_refresh_token = refresh_token
                logger.info(
                    "Grace period active: %.1f hours since last check (max %d)",
                    hours_since, GRACE_HOURS,
                )
                return state
        except (ValueError, TypeError):
            pass

    logger.info("Cached token expired and beyond grace period — online login required")
    return state


def login_and_validate(email: str, password: str) -> LicenseState:
    """
    Full login flow: Firebase auth → license validation → cache tokens.

    Raises LicenseError with user-facing message on failure.
    """
    state = LicenseState()

    # Step 1: Firebase login
    fb = firebase_login(email, password)
    state.email = fb["email"]

    # Step 2: Validate license with server
    result = validate_license_online(fb["id_token"])

    # Step 3: Store state
    state.is_licensed = True
    state.tier = result.get("tier", "subscriber")
    state.valid_until = _normalize_valid_until(result.get("valid_until", ""))
    state.license_token = result.get("license_token", "")
    state.firebase_refresh_token = fb["refresh_token"]

    # Step 4: Cache tokens
    save_token_cache(
        license_token=state.license_token,
        refresh_token=fb["refresh_token"],
    )

    logger.info("Login successful for %s (tier=%s)", state.email, state.tier)
    return state


def refresh_license(state: LicenseState) -> LicenseState:
    """
    Refresh the license token using the cached Firebase refresh token.

    Called by the 12h QTimer via LicenseRefreshWorker. Returns a NEW
    LicenseState — never mutates the original (thread safety).
    """
    if not state.firebase_refresh_token:
        logger.warning("No refresh token available")
        return state

    # Build a new state from the current one (don't mutate the original)
    new_state = LicenseState()
    new_state.is_licensed = state.is_licensed
    new_state.tier = state.tier
    new_state.email = state.email
    new_state.valid_until = state.valid_until
    new_state.firebase_refresh_token = state.firebase_refresh_token
    new_state.license_token = state.license_token
    new_state.grace_active = state.grace_active

    try:
        # Refresh Firebase token
        fb = firebase_refresh_token(state.firebase_refresh_token)
        new_state.firebase_refresh_token = fb["refresh_token"]

        # Re-validate license
        result = validate_license_online(fb["id_token"])
        new_state.is_licensed = True
        new_state.tier = result.get("tier", "subscriber")
        new_state.valid_until = _normalize_valid_until(result.get("valid_until", ""))
        new_state.license_token = result.get("license_token", "")
        new_state.grace_active = False

        # Update cache
        save_token_cache(
            license_token=new_state.license_token,
            refresh_token=fb["refresh_token"],
        )

        logger.info("License refreshed for %s (tier=%s)", new_state.email, new_state.tier)

    except SubscriptionError:
        # Subscription genuinely expired/cancelled — revoke access + clear disk cache
        new_state.is_licensed = False
        new_state.tier = "free"
        clear_token_cache()
        logger.warning("Subscription expired during session — revoking license, cache cleared")

    except LicenseError as e:
        # Network error or transient failure — keep current state, grace handles it
        logger.warning("License refresh failed (transient): %s", e)

    return new_state


def logout(state: LicenseState) -> LicenseState:
    """Clear session and cached tokens."""
    clear_token_cache()
    return LicenseState()


# ─── Helpers ──────────────────────────────────────────────────────────

def _get_app_version() -> str:
    """Return the app version string."""
    try:
        from state.user_data import get_user_data_dir, get_project_root
        settings_path = (get_user_data_dir() or get_project_root()) / "app_settings.json"
        if settings_path.exists():
            data = json.loads(settings_path.read_text())
            return data.get("version", "3.0.0")
    except Exception:
        pass
    return "3.0.0"


class LicenseError(Exception):
    """User-facing license error with descriptive message."""
    pass


class LicenseExpiredError(LicenseError):
    """Token expired but was previously valid — grace period may apply."""
    pass


class SubscriptionError(LicenseError):
    """Subscription-level issue (expired, cancelled, device limit) — not a network error."""
    pass
