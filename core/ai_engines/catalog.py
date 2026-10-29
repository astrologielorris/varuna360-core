# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The one AI model table of the app (td-2nxmo, SPEC-PMT-001 INV-5). Qt-free.

Every model picker reads its list from here: Settings > AI providers, the AI
Tools (Exploration) panel and its chat pane, the blind reading, the AI task
window, the AI setting panel, the Find Chart AI search, the vision provider,
the terminal's ``?`` prompt. Before this module the same models lived in five
hand-kept tables (``pro/providers/registry``, ``ui/ai_provider_backend``,
``exploration_chat_manager.PROVIDERS``, ``core/chart_image_extraction`` and
``core/ai_capture/models``), which drifted: the AI Tools menu still offered
Claude Opus 5 after Opus 5.5 shipped, and no picker knew GPT-6.

Three kinds of model:

- **Subscription sessions** (``CLAUDE_SESSION_MODELS``, ``CODEX_SESSION_MODELS``):
  the user's Claude Code and Codex logins. The AI task window resolves Claude
  through the CLI's family aliases and Codex through its live model list; these
  tables give the explicit ids the AI Tools panel sends and the Settings rows.
- **HTTP models** (``KEY_PROVIDERS``): an OpenAI-compatible
  ``/chat/completions`` endpoint and a credential. The GLM Coding Plan is one
  of them, with a subscription credential (the Z.ai login ZCode keeps) rather
  than a per-token key: ``SUBSCRIPTION_ENV_KEYS``.
- **Local** (``env_key`` None): the server of ``ai.local_server``.

Model ids checked live on 2026-10-20 against each vendor's /models endpoint and
a tool-call request (``reasoning_effort`` "none" where the API takes it):

- OpenAI API: gpt-6-astra and gpt-6.1-sol refuse function tools on
  /v1/chat/completions at every effort ("none" is not accepted, any other
  effort 400s with tools), so their rows say ``"api": "responses"``: the tool
  loops send them to /v1/responses (``core/ai_engines/responses_api``), where
  they run tools at the user's effort (checked live 2026-10-20). gpt-6-luna,
  gpt-5.6-sol, gpt-5.6-terra, gpt-5.4-nano run tools on chat/completions with
  effort "none".
- DeepSeek: the live ids are deepseek-v4-pro and deepseek-flash; the older
  deepseek-v4-flash still answers (as deepseek-flash).
- Moonshot: kimi-k3, kimi-k2.6 listed (the account was out of balance, so no
  answer was checked).
- Mistral: the ``-latest`` aliases follow each family's newest release
  (Large 4 since v26.10, Medium 3.5, Small 4). This account's tier lists
  Medium and Small, not Large (403): a tier limit, the model stays.
- GLM: glm-5.3 and glm-5.3-flash run tools on the Z.ai Coding Plan
  (https://api.z.ai/api/coding/paas/v4) and, with the same plan key, on
  https://open.bigmodel.cn/api/coding/paas/v4 (glm-5-turbo now answers as
  glm-5.3-flash). The pay-per-use routes (``GLM_ROUTES``) follow Z.ai's
  documented ``/api/paas/v4``; not checked live (no working key here).
- Gemini (generativelanguage.googleapis.com OpenAI layer) and Grok
  (api.x.ai): ids from the vendors' model pages, not checked live (no key
  here). Gemini 3+ cannot turn reasoning off: no ``reasoning_effort`` sent.
- Claude over the Claude Code login: claude-opus-4-6, -opus-5-5, -fable-5-1,
  -sonnet-5-5, -haiku-5-5 all answer.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# The GLM credential. The GLM rows name one env key, but a user reaches GLM
# in one of several ways (``GLM_ROUTES``): a Z.ai or BigModel Coding Plan (a
# key in the environment / .env, or the login ZCode keeps in
# ``~/.zcode/v2/config.json``: "the CLI owns the login; Varuna360 only reads
# it", SPEC-PMT-001 §4.1), or a pay-per-use Z.ai or BigModel API key. The
# first route holding a credential gives both the key and the endpoint, so
# the two always match.
ZAI_CODING_PLAN_KEY = "ZAI_CODING_PLAN_API_KEY"
SUBSCRIPTION_ENV_KEYS = frozenset({ZAI_CODING_PLAN_KEY})
_ZAI = "https://api.z.ai/api"
_BIGMODEL = "https://open.bigmodel.cn/api"
ZAI_CODING_PLAN_URL = _ZAI + "/coding/paas/v4/chat/completions"
_ZCODE_CONFIG = Path.home() / ".zcode" / "v2" / "config.json"
_ZCODE_PROVIDERS = ("builtin:zai-coding-plan", "builtin:bigmodel-coding-plan")
# (kind, where the credential is, chat url, what the Settings row says).
# kind "env": an environment / .env name; "zcode": a ZCode provider id.
GLM_ROUTES: Tuple[Tuple[str, str, str, str], ...] = (
    ("env", ZAI_CODING_PLAN_KEY, ZAI_CODING_PLAN_URL, "Z.ai Coding Plan key"),
    ("zcode", "builtin:zai-coding-plan", ZAI_CODING_PLAN_URL, "Z.ai Coding Plan login (ZCode)"),
    ("zcode", "builtin:bigmodel-coding-plan", _BIGMODEL + "/coding/paas/v4/chat/completions",
     "BigModel Coding Plan login (ZCode)"),
    ("env", "BIGMODEL_CODING_PLAN_API_KEY", _BIGMODEL + "/coding/paas/v4/chat/completions",
     "BigModel Coding Plan key"),
    ("env", "ZAI_API_KEY", _ZAI + "/paas/v4/chat/completions", "Z.ai API key"),
    ("env", "ZHIPUAI_API_KEY", _BIGMODEL + "/paas/v4/chat/completions", "BigModel API key"),
    ("env", "BIGMODEL_API_KEY", _BIGMODEL + "/paas/v4/chat/completions", "BigModel API key"),
)

# The pay-per-use GLM key a user enters in Settings > AI Settings (td-hblfz,
# SPEC-PMT-001 §4.7). One row, a choice of where the key was issued: each
# choice is an env name of ``GLM_ROUTES``, so the saved key reaches its own
# endpoint through ``glm_route`` and never the Coding Plan one.
# (env name the row writes, choice label, env names that choice owns).
GLM_PAYG_ACCOUNT = "GLM_PAY_PER_USE"
GLM_PAYG_CHOICES: Tuple[Tuple[str, str, Tuple[str, ...]], ...] = (
    ("ZAI_API_KEY", "Z.ai (api.z.ai)", ("ZAI_API_KEY",)),
    ("ZHIPUAI_API_KEY", "BigModel (open.bigmodel.cn)",
     ("ZHIPUAI_API_KEY", "BIGMODEL_API_KEY")),
)
GLM_PAYG_ENV_KEYS: Tuple[str, ...] = tuple(
    name for _w, _l, names in GLM_PAYG_CHOICES for name in names)

# The Anthropic API key (SPEC-PMT-001 D-10 amendment, td-hblfz): AI Tools
# Claude, the "Anthropic API" image reader and the reverse-chart tool use it
# when there is no Claude login. A key row under API keys, not a model.
ANTHROPIC_KEY = "ANTHROPIC_API_KEY"

_OPENAI = "https://api.openai.com/v1/chat/completions"
_DEEPSEEK = "https://api.deepseek.com/v1/chat/completions"
_MOONSHOT = "https://api.moonshot.ai/v1/chat/completions"
_MISTRAL = "https://api.mistral.ai/v1/chat/completions"
_GEMINI = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
_XAI = "https://api.x.ai/v1/chat/completions"
# Efforts the GPT-6 Astra / 6.1 Sol API accepts ("none" is refused).
_GPT6_EFFORTS = ("low", "medium", "high", "xhigh")

# Field meanings: see pro/providers/registry.py (vision, vision_model,
# supports_reasoning_effort, context_window, supports_tool_loop).
# ``reasoning_efforts``: the efforts the model accepts when it is narrower
# than the usual list; a request clamps to it.
# ``api``: "responses" = the tool loops talk to /v1/responses beside ``url``
# (``core/ai_engines/responses_api``); absent = /chat/completions.
# Order IS the menu order of the AI Tools panel and of every API list.
KEY_PROVIDERS: List[Dict[str, Any]] = [
    # --- GLM Coding Plan (Z.ai subscription; thinking model) ---
    {"name": "GLM-5.3", "env_key": ZAI_CODING_PLAN_KEY, "model": "glm-5.3",
     "url": ZAI_CODING_PLAN_URL, "vision": False, "vision_model": None,
     "context_window": 1000000, "supports_tool_loop": True},
    {"name": "GLM-5.3 Flash", "env_key": ZAI_CODING_PLAN_KEY, "model": "glm-5.3-flash",
     "url": ZAI_CODING_PLAN_URL, "vision": True, "vision_model": "glm-5.3-flash",
     "context_window": 1000000, "supports_tool_loop": True},
    # --- DeepSeek (text only) ---
    {"name": "DeepSeek V4 Flash", "env_key": "Deepseek_API_KEY", "model": "deepseek-flash",
     "url": _DEEPSEEK, "vision": False, "vision_model": None,
     "context_window": 131072, "supports_tool_loop": True},
    {"name": "DeepSeek V4 Pro", "env_key": "Deepseek_API_KEY", "model": "deepseek-v4-pro",
     "url": _DEEPSEEK, "vision": False, "vision_model": None,
     "context_window": 131072, "supports_tool_loop": True},
    # --- OpenAI (natively multimodal) ---
    {"name": "GPT-6 Astra", "env_key": "OPENAI_API_KEY", "model": "gpt-6-astra",
     "url": _OPENAI, "vision": False, "vision_model": None,
     "supports_reasoning_effort": True, "reasoning_efforts": _GPT6_EFFORTS,
     "api": "responses", "context_window": 400000, "supports_tool_loop": True},
    {"name": "GPT-6.1 Sol", "env_key": "OPENAI_API_KEY", "model": "gpt-6.1-sol",
     "url": _OPENAI, "vision": False, "vision_model": None,
     "supports_reasoning_effort": True, "reasoning_efforts": _GPT6_EFFORTS,
     "api": "responses", "context_window": 400000, "supports_tool_loop": True},
    {"name": "GPT-6 Luna", "env_key": "OPENAI_API_KEY", "model": "gpt-6-luna",
     "url": _OPENAI, "vision": True, "vision_model": "gpt-6-luna",
     "supports_reasoning_effort": True,
     "context_window": 400000, "supports_tool_loop": True},
    {"name": "GPT-5.6 Sol", "env_key": "OPENAI_API_KEY", "model": "gpt-5.6-sol",
     "url": _OPENAI, "vision": True, "vision_model": "gpt-5.6-sol",
     "supports_reasoning_effort": True,
     "context_window": 400000, "supports_tool_loop": True},
    {"name": "GPT-5.6 Terra", "env_key": "OPENAI_API_KEY", "model": "gpt-5.6-terra",
     "url": _OPENAI, "vision": True, "vision_model": "gpt-5.6-terra",
     "supports_reasoning_effort": True,
     "context_window": 400000, "supports_tool_loop": True},
    {"name": "GPT-5.4 Nano", "env_key": "OPENAI_API_KEY", "model": "gpt-5.4-nano",
     "url": _OPENAI, "vision": True, "vision_model": "gpt-5.4-nano",
     "supports_reasoning_effort": True,
     "context_window": 400000, "supports_tool_loop": True},
    # --- Moonshot (K3 natively multimodal) ---
    {"name": "Kimi K3", "env_key": "Kimi_API_KEY", "model": "kimi-k3",
     "url": _MOONSHOT, "vision": True, "vision_model": "kimi-k3",
     "context_window": 262144, "supports_tool_loop": True},
    {"name": "Kimi K2.6", "env_key": "Kimi_API_KEY", "model": "kimi-k2.6",
     "url": _MOONSHOT, "vision": True, "vision_model": "kimi-k3",
     "context_window": 262144, "supports_tool_loop": True},
    # --- Mistral (family names: each -latest alias follows the newest) ---
    {"name": "Mistral Large", "env_key": "Mistrale_API_KEY",
     "model": "mistral-large-latest", "url": _MISTRAL,
     "vision": True, "vision_model": "mistral-large-latest",
     "context_window": 262144, "supports_tool_loop": True},
    {"name": "Mistral Medium", "env_key": "Mistrale_API_KEY",
     "model": "mistral-medium-latest", "url": _MISTRAL,
     "vision": True, "vision_model": "mistral-medium-latest",
     "context_window": 131072, "supports_tool_loop": True},
    {"name": "Mistral Small", "env_key": "Mistrale_API_KEY",
     "model": "mistral-small-latest", "url": _MISTRAL,
     "vision": True, "vision_model": "mistral-small-latest",
     "context_window": 131072, "supports_tool_loop": True},
    # --- Google Gemini (OpenAI layer; natively multimodal; reasoning cannot
    # be turned off, so no reasoning_effort is sent) ---
    {"name": "Gemini 4 Argon", "env_key": "GEMINI_API_KEY", "model": "gemini-4-argon",
     "url": _GEMINI, "vision": True, "vision_model": "gemini-4-argon",
     "context_window": 1048576, "supports_tool_loop": True},
    {"name": "Gemini 3.8 Flash", "env_key": "GEMINI_API_KEY", "model": "gemini-3.8-flash",
     "url": _GEMINI, "vision": True, "vision_model": "gemini-3.8-flash",
     "context_window": 1048576, "supports_tool_loop": True},
    {"name": "Gemini 3.5 Flash Lite", "env_key": "GEMINI_API_KEY",
     "model": "gemini-3.5-flash-lite", "url": _GEMINI,
     "vision": True, "vision_model": "gemini-3.5-flash-lite",
     "context_window": 1048576, "supports_tool_loop": True},
    # --- xAI Grok ---
    {"name": "Grok 4.7", "env_key": "XAI_API_KEY", "model": "grok-4.7",
     "url": _XAI, "vision": True, "vision_model": "grok-4.7",
     "context_window": 500000, "supports_tool_loop": True},
    # --- Local server (ai.local_server resolves url and model at use time) ---
    {"name": "Qwen 3.5 9B", "env_key": None, "model": "qwen/qwen3.5-9b",
     "url": "http://localhost:1234/v1/chat/completions",
     "vision": True, "vision_model": "qwen/qwen3.5-9b",
     "context_window": 131072, "supports_tool_loop": True},
]

# env_key -> the account that issues it (the Settings row label).
KEY_ACCOUNT_LABELS: Dict[Optional[str], str] = {
    ZAI_CODING_PLAN_KEY: "GLM (Z.ai)",
    "OPENAI_API_KEY": "OpenAI",
    "Deepseek_API_KEY": "DeepSeek",
    "Kimi_API_KEY": "Moonshot",
    "Mistrale_API_KEY": "Mistral",
    "GEMINI_API_KEY": "Google Gemini",
    "XAI_API_KEY": "xAI",
    None: "LM Studio",
}

# (display name, model id), preference order, not version order: Opus 4.6
# first because Lorris rates it above 5 for astrology reports.
CLAUDE_SESSION_MODELS: Tuple[Tuple[str, str], ...] = (
    ("Claude Opus 4.6", "claude-opus-4-6"),
    ("Claude Opus 5.5", "claude-opus-5-5"),
    ("Claude Fable 5.1", "claude-fable-5-1"),
    ("Claude Sonnet 5.5", "claude-sonnet-5-5"),
    ("Claude Haiku 5.5", "claude-haiku-5-5"),
)
# The GPT families of Codex's live model/list, newest of each (2026-10-20).
CODEX_SESSION_MODELS: Tuple[Tuple[str, str], ...] = (
    ("Codex GPT-6 Astra", "gpt-6-astra"),
    ("Codex GPT-6.1 Sol", "gpt-6.1-sol"),
    ("Codex GPT-6 Luna", "gpt-6-luna"),
    ("Codex GPT-5.6 Terra", "gpt-5.6-terra"),
)

# Retired display names -> current ones. A stored choice migrates on READ
# (``canonical_name``) instead of falling back to the first entry.
LEGACY_NAMES: Dict[str, str] = {
    "GPT-5.5": "GPT-5.6 Terra",
    "GPT-5.4 Mini": "GPT-6 Luna",
    "GPT-4.1 Mini": "GPT-6 Luna",
    "GPT-4.1 Nano": "GPT-5.4 Nano",
    "GPT-5.6 Luna": "GPT-6 Luna",
    "GPT-5.6": "GPT-5.6 Sol",
    "Kimi K2.5": "Kimi K2.6",
    "DeepSeek": "DeepSeek V4 Flash",
    "Mistral": "Mistral Large",
    "Mistral Medium 3.5": "Mistral Medium",
    "LM Studio": "Qwen 3.5 9B",
    "Claude Opus (High Think)": "Claude Opus 5.5",
    "Claude Opus (Medium Think)": "Claude Opus 5.5",
    "Claude Sonnet (Medium Think)": "Claude Sonnet 5.5",
    "Claude Opus 5": "Claude Opus 5.5",
    "Claude Sonnet 5": "Claude Sonnet 5.5",
    "Claude Sonnet 4.6": "Claude Sonnet 5.5",
    "Claude Haiku 4.5": "Claude Haiku 5.5",
    "Codex": "Codex GPT-5.6 Terra",
    "Codex GPT-5.6 Sol": "Codex GPT-6.1 Sol",
    "Codex GPT-5.6 Luna": "Codex GPT-6 Luna",
}


def canonical_name(name: Optional[str]) -> str:
    """A (possibly retired) model display name -> its current name."""
    return LEGACY_NAMES.get(name or "", name or "")


def key_provider(name: Optional[str]) -> Optional[Dict[str, Any]]:
    """The HTTP model row for ``name`` (retired names migrated), a copy."""
    canonical = canonical_name(name)
    row = next((r for r in KEY_PROVIDERS if r["name"] == canonical), None)
    return dict(row) if row is not None else None


# ------------------------------------------------------------- credentials

def zcode_coding_plan_key(path: Optional[Path] = None) -> str:
    """The Z.ai Coding Plan key of the user's ZCode login, or "". Read only;
    the file is ZCode's and is never written."""
    for pid in _ZCODE_PROVIDERS:
        key = _zcode_key(pid, path)
        if key:
            return key
    return ""


def glm_route(env: Optional[Dict[str, str]] = None,
              zcode_path: Optional[Path] = None) -> Tuple[str, str, str]:
    """``(key, chat url, source)`` of the first GLM route holding a
    credential (``GLM_ROUTES`` order: Coding Plans before pay-per-use keys),
    or ``("", ZAI_CODING_PLAN_URL, "")``."""
    if env is None:
        from core.ai_engines.env import read_env
        env = read_env()
    for kind, where, url, source in GLM_ROUTES:
        if kind == "env":
            value = (env.get(where) or "").strip()
        else:
            value = _zcode_key(where, zcode_path)
        if value:
            return value, url, source
    return "", ZAI_CODING_PLAN_URL, ""


def glm_payg_state(env: Dict[str, str],
                   zcode_path: Optional[Path] = None) -> Tuple[str, str, str]:
    """``(choice, held_in, source in use)`` of the pay-per-use GLM row.

    ``choice``: the ``GLM_PAYG_CHOICES`` env name the row should select (the
    one whose names hold a key, first in ``GLM_ROUTES`` order; Z.ai when
    none). ``held_in``: the env name actually holding that key, or "".
    ``source in use``: what ``glm_route`` answers for ``env`` (a Coding Plan
    goes first, so a saved pay-per-use key can be present and unused)."""
    held_in = next((n for n in GLM_PAYG_ENV_KEYS if (env.get(n) or "").strip()), "")
    choice = next((write for write, _label, names in GLM_PAYG_CHOICES
                   if held_in in names), GLM_PAYG_CHOICES[0][0])
    _key, _url, source = glm_route(env, zcode_path)
    return choice, held_in, source


def _zcode_key(provider_id: str, path: Optional[Path] = None) -> str:
    try:
        data = json.loads((path or _ZCODE_CONFIG).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    providers = data.get("provider") if isinstance(data, dict) else None
    entry = providers.get(provider_id) if isinstance(providers, dict) else None
    if not isinstance(entry, dict) or entry.get("enabled") is False:
        return ""
    options = entry.get("options")
    key = options.get("apiKey") if isinstance(options, dict) else None
    return key.strip() if isinstance(key, str) and key.strip() else ""


def resolve_glm(config: Dict[str, Any]) -> Dict[str, Any]:
    """A GLM row with the endpoint of the route its credential comes from
    (other rows unchanged). Applied by ``local_provider_config``, which every
    path calls before sending."""
    if config.get("env_key") != ZAI_CODING_PLAN_KEY:
        return config
    _key, url, source = glm_route()
    out = dict(config)
    out["url"] = url
    out["credential_source"] = source
    return out


def provider_key(env_key: Optional[str]) -> str:
    """The credential for ``env_key`` (canonical or legacy name; GLM falls
    back through ``GLM_ROUTES``), or ""."""
    if not env_key:
        return ""
    from core.ai_engines.env import (LEGACY_ENV_KEY_ALIASES, read_env,
                                     resolve_env_key)
    canonical = LEGACY_ENV_KEY_ALIASES.get(env_key, env_key)
    return resolve_env_key(canonical, read_env()).value


def has_key(env_key: Optional[str]) -> bool:
    return bool(provider_key(env_key))


def http_config(name: Optional[str], settings=None) -> Optional[Dict[str, Any]]:
    """The ready-to-send config of an HTTP model: its row plus ``api_key``
    (the local server: its url and model from ``ai.local_server``). None for
    an unknown name; ``api_key`` "" when the credential is missing."""
    row = key_provider(name)
    if row is None:
        return None
    from core.local_ai_config import local_provider_config
    cfg = local_provider_config(row, settings)
    if row.get("env_key") == ZAI_CODING_PLAN_KEY:
        # One read: the key and the endpoint of the same GLM route.
        key, url, source = glm_route()
        cfg.update(api_key=key, url=url, credential_source=source)
    else:
        cfg["api_key"] = provider_key(row.get("env_key"))
    return cfg


def clamp_effort(cfg: Dict[str, Any], effort: Optional[str]) -> Optional[str]:
    """An effort the model accepts: ``effort`` when allowed, else the closest
    allowed one ("none" -> the lowest)."""
    allowed = cfg.get("reasoning_efforts")
    if not allowed or effort in allowed:
        return effort
    order = ("none", "minimal", "low", "medium", "high", "xhigh", "max")
    rank = order.index(effort) if effort in order else 0
    for e in allowed:
        if order.index(e) >= rank:
            return e
    return allowed[-1]


# --------------------------------------------- the task engines' HTTP lists

GLM_ENGINE, API_ENGINE = "glm", "api"


def task_models(engine: str) -> List[Tuple[str, str]]:
    """``(name, label)`` of the HTTP models an engine of the AI task window,
    the AI setting panel and the Find Chart AI search can run: the task tools
    need the tool loop, so chat-only models are left out. GLM: the Coding
    Plan's models (any GLM route); API: the others whose key is present (the
    local server is its own engine)."""
    out: List[Tuple[str, str]] = []
    for row in KEY_PROVIDERS:
        env_key = row.get("env_key")
        if not env_key or not row.get("supports_tool_loop", True):
            continue
        glm = env_key in SUBSCRIPTION_ENV_KEYS
        if (engine == GLM_ENGINE) != glm:
            continue
        if engine == API_ENGINE and not has_key(env_key):
            continue
        out.append((row["name"], row["name"]))
    return out


def glm_available() -> bool:
    return has_key(ZAI_CODING_PLAN_KEY)


def api_available() -> bool:
    return bool(task_models(API_ENGINE))
