# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Canonical env-key resolution for the AI engines (SPEC-PROV-001 §4), moved
from ``pro/providers/registry.py`` with the engines (SPEC-AIC-001 §4.6, plan 3
W5a) so Core reads API keys without the Pro tree. ``pro.providers.registry``
re-exports every name here.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

# Repo root — fallback .env location when SettingsManager is unavailable
# (e.g. a bare unit-test import with no app state configured).
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ENV_PATH = _PROJECT_ROOT / ".env"


def _settings_env_path() -> Path:
    """Resolve the .env path the SAME way SettingsManager does — one source of
    truth for where API keys live (SPEC-PROV-001 INV-4).

    In a dev checkout this is the repo-root ``.env``; in a frozen build
    SettingsManager resolves it under the user data directory
    (``get_user_data_dir()/.env``), so key reads must not hardcode the repo
    ``.env``. Import is lazy to avoid import-time coupling to the settings/Qt
    stack; any failure falls back to the repo ``.env``.
    """
    try:
        from managers.settings_manager import get_settings
        path = getattr(get_settings(), "_env_path", None)
        if path:
            return Path(path)
    except Exception:
        pass
    return _ENV_PATH

# Legacy env-key name -> canonical name.
LEGACY_ENV_KEY_ALIASES: Dict[str, str] = {
    "Deepseek_API_KEY": "DEEPSEEK_API_KEY",
    "Kimi_API_KEY": "KIMI_API_KEY",
    "Mistrale_API_KEY": "MISTRAL_API_KEY",
    # Google's SDK reads either name; GEMINI_API_KEY is the documented one.
    "GOOGLE_API_KEY": "GEMINI_API_KEY",
}

# Reverse map: canonical -> [legacy aliases].
_ALIASES_BY_CANONICAL: Dict[str, List[str]] = {}
for _legacy, _canonical in LEGACY_ENV_KEY_ALIASES.items():
    _ALIASES_BY_CANONICAL.setdefault(_canonical, []).append(_legacy)


@dataclass
class ResolvedEnvKey:
    """Outcome of resolving a canonical env-key against an environment.

    value          — the resolved key, or "" if unset.
    source_name    — the env-var name that supplied the value, or None.
    alias_used     — True when a legacy alias supplied the value.
    shadowed_alias — a legacy alias that also held a value but was ignored
                     because the canonical key won (None otherwise).
    """
    value: str
    source_name: Optional[str] = None
    alias_used: bool = False
    shadowed_alias: Optional[str] = None


def read_env(env_path: Optional[Path] = None) -> Dict[str, str]:
    """Return os.environ overlaid with the .env file, os.environ winning.

    The .env path is resolved via SettingsManager (``_settings_env_path``) so
    frozen builds read the user-data-dir .env, not the repo one — matching
    settings_manager.get_api_key, which also lets os.environ take precedence.
    Pass ``env_path`` explicitly to override (tests).
    """
    env: Dict[str, str] = {}
    path = env_path if env_path is not None else _settings_env_path()
    try:
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    env[key.strip()] = value.strip().strip("\"'")
    except Exception:
        pass
    env.update(os.environ)
    return env


def resolve_env_key(canonical: str, env: Dict[str, str]) -> ResolvedEnvKey:
    """Resolve a canonical env-key name against an environment mapping.

    Canonical wins; else the first legacy alias holding a value; else empty.
    """
    value = env.get(canonical, "")
    aliases = _ALIASES_BY_CANONICAL.get(canonical, [])
    if value:
        shadowed = next((a for a in aliases if env.get(a)), None)
        return ResolvedEnvKey(value=value, source_name=canonical,
                              alias_used=False, shadowed_alias=shadowed)
    for alias in aliases:
        alias_value = env.get(alias, "")
        if alias_value:
            return ResolvedEnvKey(value=alias_value, source_name=alias,
                                  alias_used=True)
    if canonical == "ZAI_CODING_PLAN_API_KEY":
        # GLM: with no plan key in the environment, the next GLM route
        # holding a credential (a ZCode Coding Plan login, a BigModel plan
        # key, a pay-per-use Z.ai or BigModel key) supplies it (td-2nxmo).
        from core.ai_engines.catalog import glm_route
        value, _url, source = glm_route(env)
        if value:
            return ResolvedEnvKey(value=value, source_name=source)
    return ResolvedEnvKey(value="", source_name=None)
