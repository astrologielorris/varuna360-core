# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Settings-only AI provider metadata and probes for the Lite application.

This module deliberately contains no chat/session execution.  It supplies the
shared settings page with the same account, model, key and effort schema as the
Pro provider registry, plus install-only CLI probes.  Finding a CLI never means
that its user is authenticated, so each session CLI is also asked for its own
login state (``claude auth status``, ``codex login status``). Those commands
only read the CLI's stored login; they never start a session or bill anything.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from core.settings_registry import get as _registry_get


class ProviderStatus(Enum):
    READY = "ready"
    LOGGED_OUT = "logged_out"
    NOT_INSTALLED = "not_installed"
    INSTALLED_UNVERIFIED = "installed_unverified"
    MISSING_KEY = "missing_key"


class ProviderFamily(Enum):
    SESSION = "session"
    KEY = "key"


@dataclass
class ProviderAccount:
    email: Optional[str] = None
    plan: Optional[str] = None
    auth_kind: Optional[str] = None


@dataclass
class ProviderSnapshot:
    status: ProviderStatus
    detail_msg: str = ""
    account: Optional[ProviderAccount] = None
    models: List[str] = field(default_factory=list)


LEGACY_ENV_KEY_ALIASES = {
    "Deepseek_API_KEY": "DEEPSEEK_API_KEY",
    "Kimi_API_KEY": "KIMI_API_KEY",
    "Mistrale_API_KEY": "MISTRAL_API_KEY",
}

ACCOUNT_SUBSCRIPTION = "subscription"
ACCOUNT_KEY = "key"
ACCOUNT_LOCAL = "local"
ACCOUNT_GROUPS = [
    (ACCOUNT_SUBSCRIPTION, "Subscription logins — no API key",
     "Billed to your existing plan. The CLI owns the login; Varuna360 only reads it."),
    (ACCOUNT_KEY, "API keys — one key per vendor",
     "Billed per token. One key unlocks every model listed under it."),
    (ACCOUNT_LOCAL, "Local AI — no key, no billing",
     "Uses the server address below. For local processing, choose a server on this machine or your own network."),
]

from core.ai_engines import catalog as _catalog  # noqa: E402

KEY_ACCOUNT_LABELS = _catalog.KEY_ACCOUNT_LABELS

# (label, value) pairs of the effort combos: the registry's ai.effort choices
# (SPEC-SET-003 W3e, one declaration).
EFFORT_LABELS = [(c.label, c.value) for c in _registry_get("ai.effort").choices]
_EFFORTS = {value for _label, value in EFFORT_LABELS}

# One model table for every edition (core/ai_engines/catalog.py, td-2nxmo).
_KEY_PROVIDERS = _catalog.KEY_PROVIDERS
_SESSION_MODELS = {"Claude": _catalog.CLAUDE_SESSION_MODELS,
                   "Codex": _catalog.CODEX_SESSION_MODELS}
_LEGACY_NAMES = _catalog.LEGACY_NAMES


@dataclass(frozen=True)
class ProviderAccountRow:
    id: str
    label: str
    kind: str
    env_key: Optional[str] = None
    driver_name: Optional[str] = None
    models: tuple = ()


from core.session_cli import find_cli, run_cli as _run_cli  # noqa: E402,F401


def _claude_login(path):
    """(status, account, note) from `claude auth status` (JSON by default)."""
    result = _run_cli(path, ["auth", "status", "--json"], timeout=8)
    try:
        data = json.loads(result.stdout)
    except (TypeError, ValueError):
        return None, None, "this version cannot report its login"
    if not data.get("loggedIn"):
        return ProviderStatus.LOGGED_OUT, None, "Run `claude auth login` in a terminal."
    method = data.get("authMethod") or ""
    kind = {"claude.ai": "oauth"}.get(method, method or None)
    plan = data.get("subscriptionType")
    return ProviderStatus.READY, ProviderAccount(
        email=data.get("email"), plan=plan.capitalize() if plan else None,
        auth_kind=kind), ""


def _codex_login(path):
    """(status, account, note) from `codex login status` (text on stderr)."""
    result = _run_cli(path, ["login", "status"], timeout=8)
    text = " ".join((result.stdout + " " + result.stderr).split())
    low = text.lower()
    if "not logged in" in low:
        return ProviderStatus.LOGGED_OUT, None, "Run `codex login` in a terminal."
    if result.returncode == 0 and "logged in" in low:
        kind = "chatgpt" if "chatgpt" in low else ("apikey" if "api key" in low else None)
        return ProviderStatus.READY, ProviderAccount(auth_kind=kind), ""
    return None, None, "this version cannot report its login"


_LOGIN_PROBES = {"claude": _claude_login, "codex": _codex_login}


class _Instance:
    def __init__(self, driver):
        self.driver = driver

    def snapshot(self):
        if self.driver.family is ProviderFamily.SESSION:
            binary = self.driver.name.lower()
            path = find_cli(binary)
            if not path:
                return ProviderSnapshot(ProviderStatus.NOT_INSTALLED,
                                        f"{binary} not found.")
            version = ""
            try:
                result = _run_cli(path, ["--version"], timeout=4)
                version = next((x.strip() for x in
                                (result.stdout + "\n" + result.stderr).splitlines()
                                if x.strip()), "")
            except Exception:
                pass
            detail = f"{binary} installed" + (f" (version {version})" if version else "")
            try:
                status, account, note = _LOGIN_PROBES[binary](path)
            except Exception as exc:
                status, account, note = None, None, f"login check failed ({type(exc).__name__})"
            if status is ProviderStatus.READY:
                return ProviderSnapshot(status, detail, account=account)
            if status is ProviderStatus.LOGGED_OUT:
                return ProviderSnapshot(status, note)
            return ProviderSnapshot(ProviderStatus.INSTALLED_UNVERIFIED,
                                    f"{detail}; {note}.")

        key = self.driver.env_key
        if not key:
            return ProviderSnapshot(ProviderStatus.READY, "No API key required.",
                                    models=[self.driver.model])
        canonical = LEGACY_ENV_KEY_ALIASES.get(key, key)
        if key in _catalog.SUBSCRIPTION_ENV_KEYS:
            _key, _url, source = _catalog.glm_route()
            if not _key:
                return ProviderSnapshot(ProviderStatus.LOGGED_OUT,
                                        "Sign in to a GLM Coding Plan in ZCode, or enter "
                                        "a key under GLM pay-per-use in AI Settings.")
            return ProviderSnapshot(ProviderStatus.READY, f"Using your {source}.",
                                    models=[self.driver.model])
        from managers.settings_manager import get_settings
        if not get_settings().get_api_key(canonical):
            return ProviderSnapshot(ProviderStatus.MISSING_KEY,
                                    f"No API key found; set {canonical} in .env.")
        return ProviderSnapshot(ProviderStatus.READY,
                                f"Key present ({canonical}).",
                                models=[self.driver.model])


class _Driver:
    def __init__(self, name, family, env_key=None, model=None, url=None):
        self.name, self.family = name, family
        self.env_key, self.model, self.url = env_key, model, url

    def create(self, config=None):
        return _Instance(self)


class _Registry:
    def __init__(self, drivers):
        self._drivers = list(drivers)

    def all(self):
        return list(self._drivers)

    def names(self):
        return [driver.name for driver in self._drivers]


class LiteProviderBackend:
    """Backend consumed by :mod:`ui.ai_provider_settings`."""
    ProviderStatus = ProviderStatus
    ProviderSnapshot = ProviderSnapshot
    ProviderFamily = ProviderFamily
    ACCOUNT_LOCAL = ACCOUNT_LOCAL
    ACCOUNT_KEY = ACCOUNT_KEY
    ACCOUNT_SUBSCRIPTION = ACCOUNT_SUBSCRIPTION
    ACCOUNT_GROUPS = ACCOUNT_GROUPS
    LEGACY_ENV_KEY_ALIASES = LEGACY_ENV_KEY_ALIASES
    KEY_ACCOUNT_LABELS = KEY_ACCOUNT_LABELS
    EFFORT_LABELS = EFFORT_LABELS

    def __init__(self):
        drivers = [_Driver("Codex", ProviderFamily.SESSION),
                   _Driver("Claude", ProviderFamily.SESSION)]
        drivers.extend(_Driver(c["name"], ProviderFamily.KEY, c["env_key"],
                               c["model"], c["url"]) for c in _KEY_PROVIDERS)
        self._registry = _Registry(drivers)

    def registry(self):
        return self._registry

    def clear_detection_cache(self):
        return None

    def canonical_effort(self, value, default="medium"):
        value = (value or "").strip().lower()
        value = "none" if value == "minimal" else value
        return value if value in _EFFORTS else default

    def canonical_provider_name(self, name):
        return _LEGACY_NAMES.get(name or "", name or "")

    def builtin_key_provider_config(self, name):
        canonical = self.canonical_provider_name(name)
        from core.local_ai_config import local_provider_config
        cfg = next((c for c in _KEY_PROVIDERS if c["name"] == canonical), None)
        return local_provider_config(cfg) if cfg is not None else None

    def vision_provider_configs(self):
        # Only what core.chart_image_extraction can route; anything else
        # would be selectable here and then refused as "unavailable".
        from core.chart_image_extraction import (LEGACY_VISION_NAMES,
                                                 VISION_PROVIDERS)
        routable = {c["name"] for c in VISION_PROVIDERS} | set(LEGACY_VISION_NAMES)
        configs = [dict(c, kind="openai") for c in _KEY_PROVIDERS
                   if c.get("vision") and c["name"] in routable]
        configs.append({"name": "Anthropic API", "env_key": "ANTHROPIC_API_KEY",
                        "model": "claude-haiku-5-5", "url": None,
                        "vision": True, "vision_model": "claude-haiku-5-5",
                        "kind": "anthropic"})
        # Claude Code / Codex subscriptions read images through their CLI.
        configs += [{"name": c["name"], "env_key": None, "model": c["model"],
                     "url": None, "vision": True, "vision_model": c["model"],
                     "kind": c["kind"]}
                    for c in VISION_PROVIDERS
                    if c["kind"] in ("claude_cli", "codex_cli")]
        from core.local_ai_config import local_provider_config
        return [local_provider_config(c) for c in configs]

    def builtin_accounts(self):
        rows = [ProviderAccountRow({"Claude": "claude-code",
                                    "Codex": "codex-cli"}[name],
                                   {"Claude": "Claude Code",
                                    "Codex": "Codex CLI"}[name],
                                   ACCOUNT_SUBSCRIPTION, driver_name=name,
                                   models=models)
                for name, models in _SESSION_MODELS.items()]
        grouped = {}
        for cfg in _KEY_PROVIDERS:
            grouped.setdefault(cfg["env_key"], []).append(cfg)
        for key, configs in grouped.items():
            kind = (ACCOUNT_SUBSCRIPTION if key in _catalog.SUBSCRIPTION_ENV_KEYS
                    else ACCOUNT_KEY if key else ACCOUNT_LOCAL)
            rows.append(ProviderAccountRow(
                key or f"local:{configs[0]['url']}",
                KEY_ACCOUNT_LABELS.get(key, key or "Local"), kind,
                env_key=key,
                models=tuple((c["name"], c["model"]) for c in configs)))
        return rows


_DEFAULT_BACKEND = LiteProviderBackend()


def default_provider_backend():
    return _DEFAULT_BACKEND
