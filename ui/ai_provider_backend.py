# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Settings-only AI provider metadata and probes for the Lite application.

This module deliberately contains no chat/session execution.  It supplies the
shared settings page with the same account, model, key and effort schema as the
Pro provider registry, plus install-only CLI probes.  Finding a CLI never means
that its user is authenticated: session rows remain ``installed_unverified``.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


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
     "Runs on this machine. Nothing leaves it, and nothing is charged."),
]

KEY_ACCOUNT_LABELS = {
    "OPENAI_API_KEY": "OpenAI",
    "Deepseek_API_KEY": "DeepSeek",
    "Kimi_API_KEY": "Moonshot",
    "Mistrale_API_KEY": "Mistral",
    None: "LM Studio",
}

EFFORT_LABELS = [
    ("None", "none"), ("Low", "low"), ("Medium", "medium"),
    ("High", "high"), ("Extra high", "xhigh"),
]
_EFFORTS = {value for _label, value in EFFORT_LABELS}

_KEY_PROVIDERS = [
    {"name": "DeepSeek V4 Pro", "env_key": "Deepseek_API_KEY", "model": "deepseek-v4-pro", "url": "https://api.deepseek.com/v1/chat/completions", "vision": False, "vision_model": None, "context_window": 131072, "supports_tool_loop": True},
    {"name": "DeepSeek V4 Flash", "env_key": "Deepseek_API_KEY", "model": "deepseek-v4-flash", "url": "https://api.deepseek.com/v1/chat/completions", "vision": False, "vision_model": None, "context_window": 131072, "supports_tool_loop": True},
    {"name": "GPT-5.6 Sol", "env_key": "OPENAI_API_KEY", "model": "gpt-5.6-sol", "url": "https://api.openai.com/v1/chat/completions", "vision": True, "vision_model": "gpt-5.6-sol", "supports_reasoning_effort": True, "context_window": 400000, "supports_tool_loop": True},
    {"name": "GPT-5.6 Terra", "env_key": "OPENAI_API_KEY", "model": "gpt-5.6-terra", "url": "https://api.openai.com/v1/chat/completions", "vision": True, "vision_model": "gpt-5.6-terra", "supports_reasoning_effort": True, "context_window": 400000, "supports_tool_loop": True},
    {"name": "GPT-5.6 Luna", "env_key": "OPENAI_API_KEY", "model": "gpt-5.6-luna", "url": "https://api.openai.com/v1/chat/completions", "vision": True, "vision_model": "gpt-5.6-luna", "supports_reasoning_effort": True, "context_window": 400000, "supports_tool_loop": True},
    {"name": "GPT-5.4 Nano", "env_key": "OPENAI_API_KEY", "model": "gpt-5.4-nano", "url": "https://api.openai.com/v1/chat/completions", "vision": True, "vision_model": "gpt-5.4-nano", "supports_reasoning_effort": True, "context_window": 400000, "supports_tool_loop": True},
    {"name": "Kimi K3", "env_key": "Kimi_API_KEY", "model": "kimi-k3", "url": "https://api.moonshot.ai/v1/chat/completions", "vision": True, "vision_model": "kimi-k3", "context_window": 262144, "supports_tool_loop": True},
    {"name": "Kimi K2.6", "env_key": "Kimi_API_KEY", "model": "kimi-k2.6", "url": "https://api.moonshot.ai/v1/chat/completions", "vision": True, "vision_model": "kimi-k3", "context_window": 262144, "supports_tool_loop": True},
    {"name": "Mistral Large", "env_key": "Mistrale_API_KEY", "model": "mistral-large-latest", "url": "https://api.mistral.ai/v1/chat/completions", "vision": True, "vision_model": "mistral-small-latest", "context_window": 131072, "supports_tool_loop": True},
    {"name": "Qwen 3.5 9B", "env_key": None, "model": "qwen/qwen3.5-9b", "url": "http://localhost:1234/v1/chat/completions", "vision": False, "vision_model": None, "context_window": 131072, "supports_tool_loop": True},
]

_SESSION_MODELS = {
    "Claude": (("Claude Opus 4.6", "claude-opus-4-6"),
               ("Claude Sonnet 4.6", "claude-sonnet-4-6"),
               ("Claude Opus 5", "claude-opus-5"),
               ("Claude Sonnet 5", "claude-sonnet-5")),
    "Codex": (("Codex GPT-5.6 Sol", "gpt-5.6-sol"),
              ("Codex GPT-5.6 Terra", "gpt-5.6-terra"),
              ("Codex GPT-5.6 Luna", "gpt-5.6-luna")),
}

_LEGACY_NAMES = {
    "GPT-5.5": "GPT-5.6 Terra", "GPT-5.4 Mini": "GPT-5.6 Luna",
    "GPT-4.1 Mini": "GPT-5.6 Luna", "GPT-4.1 Nano": "GPT-5.4 Nano",
    "Kimi K2.5": "Kimi K2.6", "GPT-5.6": "GPT-5.6 Sol",
    "DeepSeek": "DeepSeek V4 Flash", "Mistral": "Mistral Large",
    "LM Studio": "Qwen 3.5 9B", "Codex": "Codex GPT-5.6 Terra",
    "Claude Opus (High Think)": "Claude Opus 5",
    "Claude Opus (Medium Think)": "Claude Opus 5",
    "Claude Sonnet (Medium Think)": "Claude Sonnet 5",
}


@dataclass(frozen=True)
class ProviderAccountRow:
    id: str
    label: str
    kind: str
    env_key: Optional[str] = None
    driver_name: Optional[str] = None
    models: tuple = ()


class _Instance:
    def __init__(self, driver):
        self.driver = driver

    def snapshot(self):
        if self.driver.family is ProviderFamily.SESSION:
            binary = self.driver.name.lower()
            path = shutil.which(binary)
            if not path:
                return ProviderSnapshot(ProviderStatus.NOT_INSTALLED,
                                        f"{binary} not found on PATH.")
            try:
                result = subprocess.run([path, "--version"], capture_output=True,
                                        text=True, timeout=2.5, check=False)
                version = next((x.strip() for x in
                                (result.stdout + "\n" + result.stderr).splitlines()
                                if x.strip()), "")
                detail = f"{binary} installed"
                if version:
                    detail += f" (version {version})"
                detail += "; login state not probed."
            except Exception as exc:
                detail = (f"{binary} installed at {path}; version probe failed "
                          f"({type(exc).__name__}); login state not probed.")
            return ProviderSnapshot(ProviderStatus.INSTALLED_UNVERIFIED, detail)

        key = self.driver.env_key
        if not key:
            return ProviderSnapshot(ProviderStatus.READY, "No API key required.",
                                    models=[self.driver.model])
        canonical = LEGACY_ENV_KEY_ALIASES.get(key, key)
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
        return next((dict(c) for c in _KEY_PROVIDERS
                     if c["name"] == canonical), None)

    def vision_provider_configs(self):
        configs = [dict(c, kind="openai") for c in _KEY_PROVIDERS
                   if c.get("vision")]
        configs.append({"name": "Anthropic API", "env_key": "ANTHROPIC_API_KEY",
                        "model": "claude-haiku-4-5", "url": None,
                        "vision": True, "vision_model": "claude-haiku-4-5",
                        "kind": "anthropic"})
        return configs

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
            kind = ACCOUNT_KEY if key else ACCOUNT_LOCAL
            rows.append(ProviderAccountRow(
                key or f"local:{configs[0]['url']}",
                KEY_ACCOUNT_LABELS.get(key, key or "Local"), kind,
                env_key=key,
                models=tuple((c["name"], c["model"]) for c in configs)))
        return rows


_DEFAULT_BACKEND = LiteProviderBackend()


def default_provider_backend():
    return _DEFAULT_BACKEND
