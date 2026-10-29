# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Configuration for a user-owned OpenAI-compatible local server."""
from typing import Any

LOCAL_PROVIDER = "Qwen 3.5 9B"  # persisted identity, independent of the loaded model

# Fixed local setups offered beside the AI Settings server (Lorris, 2026-10-20).
# Bionic Qwen 80K: the "Bionic Qwen 80K" menu launcher (Linux Mint, Programming)
# starts Bionic (or reuses LM Studio, same server on port 1234) and loads Qwen
# 3.8 27B with 81920 tokens of context and a Q8 KV cache through the LM Studio
# SDK. Either app serves it; the model must be loaded with that context first.
LOCAL_PRESETS = (
    {"id": "bionic-qwen-80k", "label": "Bionic Qwen 80K",
     "url": "http://localhost:1234/v1",
     "model": "qwen3.8-27b-heretic-abliterated-uncensored",
     "context_window": 81920,
     # A 27B model reads a long tool result for minutes before its first token.
     "read_timeout": 600,
     "launcher": "Bionic Qwen 80K (app menu, Programming)",
     # Offered only where this launcher is installed: the setup is Lorris's own
     # machine, not a choice for every user (it showed in a customer's Mac
     # build, 2026-10-26).
     "desktop_file": "ai.elementlabs.bionic-qwen-80k.desktop"},
)


def offered_presets() -> tuple:
    """The fixed local setups this computer has: a preset with a
    ``desktop_file`` is listed only when that launcher is installed."""
    import os
    dirs = [os.path.join(os.path.expanduser("~"), ".local", "share", "applications"),
            "/usr/share/applications", "/usr/local/share/applications"]
    return tuple(p for p in LOCAL_PRESETS if not p.get("desktop_file")
                 or any(os.path.isfile(os.path.join(d, p["desktop_file"])) for d in dirs))


def local_preset(preset_id) -> dict:
    """The fixed local setup ``preset_id``, or the model found on a local
    server that id names (``core/local_ai_discovery``), a copy, or {}."""
    preset = next((p for p in LOCAL_PRESETS if p["id"] == preset_id), None)
    if preset is not None:
        return dict(preset)
    from core.local_ai_discovery import found_model
    return found_model(preset_id)


def offered_models(server_values=None) -> list:
    """The Local LLM's choices beside the AI Settings server: the fixed
    setups this computer has, then every model the last probe found on the
    local servers (``core/local_ai_discovery.known``), each once. A found model
    a fixed setup or the AI Settings server (``server_values``) already
    offers is left out."""
    from core.local_ai_discovery import known
    out = list(offered_presets())

    def endpoint(url):
        # localhost, 127.0.0.1 and ::1 are one server.
        from urllib.parse import urlsplit
        parts = urlsplit(local_chat_url(url))
        host = parts.hostname
        if host in ("127.0.0.1", "::1"):
            host = "localhost"
        return parts.scheme, host, parts.port, parts.path

    def same(a_url, a_model, b_url, b_model):
        try:
            return a_model == b_model and endpoint(a_url) == endpoint(b_url)
        except ValueError:
            return False
    taken = [(p["url"], p["model"]) for p in out]
    if server_values and isinstance(server_values.get("url"), str):
        taken.append((server_values["url"], server_values.get("model")))
    for m in known() or []:
        if not any(same(m["url"], m["model"], u, mod) for u, mod in taken):
            out.append(m)
            taken.append((m["url"], m["model"]))
    return out


def loaded_context(url: str, model: str, timeout: float = 3.0):
    """``(state, loaded context length)`` of ``model`` on an LM Studio /
    Bionic server (its /api/v0/models), or (None, None) when the server does
    not answer or does not list it."""
    import requests
    from urllib.parse import urlsplit, urlunsplit
    parts = urlsplit(url)
    try:
        r = requests.get(urlunsplit((parts.scheme, parts.netloc, "/api/v0/models", "", "")),
                         timeout=timeout)
        rows = r.json().get("data") or []
    except Exception:                                             # noqa: BLE001
        return None, None
    row = next((m for m in rows if isinstance(m, dict) and m.get("id") == model), None)
    if row is None:
        return None, None
    return row.get("state"), row.get("loaded_context_length")


def local_preset_config(preset_id) -> dict:
    """The request config of a fixed local setup, with
    ``local_config_error`` when its server is down or the model is not loaded
    with its full context (LM Studio would load it on demand with its own
    default context, 16K here, and long readings would fail)."""
    preset = local_preset(preset_id)
    if not preset:
        return {"local_config_error": f"Unknown local model: {preset_id}."}
    cfg = {"name": preset["label"], "label": preset["label"], "env_key": None,
           "url": local_chat_url(preset["url"]), "model": preset["model"],
           "vision": True, "vision_model": preset["model"],
           "context_window": preset["context_window"],
           "read_timeout": preset["read_timeout"], "supports_tool_loop": True}
    if preset.get("discovered"):
        # A found model runs as its server loads it (LM Studio loads one on
        # demand); only a server that no longer serves it is refused.
        from core.local_ai_discovery import check
        seen = check(preset)
        if seen.get("error"):
            cfg["local_config_error"] = seen["error"]
        else:
            cfg["context_window"] = seen.get("context")
            cfg["vision"] = bool(seen.get("vision"))
            cfg["vision_model"] = preset["model"] if cfg["vision"] else None
        return cfg
    state, ctx = loaded_context(preset["url"], preset["model"])
    start = f"Start {preset['launcher']}, wait until the model is loaded, then send again."
    if state is None:
        cfg["local_config_error"] = (f"{preset['label']}: no server answers at "
                                     f"{preset['url']} with {preset['model']}. {start}")
    elif state != "loaded" or not ctx or ctx < preset["context_window"]:
        now = f"loaded with {ctx} tokens" if state == "loaded" and ctx else "not loaded"
        reload = (" It is loaded with another context: eject it in LM Studio or Bionic first."
                  if state == "loaded" else "")
        cfg["local_config_error"] = (f"{preset['label']}: the model is {now}, not "
                                     f"{preset['context_window']}.{reload} {start}")
    return cfg


def is_local_provider(config: dict) -> bool:
    """A keyless HTTP endpoint; subscription CLI sessions are separate."""
    return (config.get("env_key", False) is None
            and not config.get("session_cli") and not config.get("native_anthropic")
            and isinstance(config.get("url"), str))


def local_server_values(settings=None) -> dict:
    """Repairable field values, even when an imported profile is malformed."""
    if settings is None:
        from managers.settings_manager import get_settings
        settings = get_settings()
    from core.settings_registry import default
    values = dict(default("ai.local_server"))
    saved = settings.get("ai.local_server", values)
    if isinstance(saved, dict):
        values.update({k: saved[k] for k in values if isinstance(saved.get(k), str)})
    return values

def local_chat_url(address: str) -> str:
    """Accept a server root, API base, or full OpenAI chat endpoint."""
    from urllib.parse import urlsplit, urlunsplit
    address = address.strip()
    parts = urlsplit(address)
    if (parts.scheme not in {"http", "https"} or not parts.hostname
            or parts.username or parts.password or parts.query or parts.fragment
            or any(c.isspace() for c in address)):
        raise ValueError("Enter an HTTP or HTTPS server address, e.g. http://localhost:1234/v1")
    # Accessing port also rejects malformed and out-of-range ports.
    parts.port
    path = parts.path.rstrip("/")
    if not path:
        path = "/v1"
    if not path.endswith("/chat/completions"):
        path += "/chat/completions"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def local_provider_config(config: dict, settings=None) -> dict:
    """Resolve the user's local server at use time; leave keyed vendors alone."""
    result = dict(config)
    if not is_local_provider(result):
        # GLM: the endpoint of the route its credential comes from.
        from core.ai_engines.catalog import resolve_glm
        return resolve_glm(result)
    if settings is None:
        from managers.settings_manager import get_settings
        settings = get_settings()
    from core.settings_registry import default
    saved = settings.get("ai.local_server", default("ai.local_server"))
    if not local_ai_server(saved):
        result["local_config_error"] = "Invalid local server settings. Edit the server address and model ID in AI Settings."
        return result
    result.update(url=local_chat_url(saved["url"]), model=saved["model"])
    if result.get("vision"):
        result["vision_model"] = saved["model"]
    result["context_window"] = None  # the configured model may not be Qwen
    return result


def local_ai_server(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != {"url", "model"}:
        return False
    if not isinstance(value["model"], str) or not value["model"].strip():
        return False
    if not isinstance(value["url"], str):
        return False
    try:
        local_chat_url(value["url"])
    except ValueError:
        return False
    return True


