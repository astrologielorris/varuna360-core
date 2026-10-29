# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The models the user's own local AI servers serve (Lorris, 2026-10-26).

The Local LLM engine lists, beside the AI Settings server, every chat model a
usual local server on this computer answers with: LM Studio (and Bionic, the
same server) on port 1234, Ollama on port 11434. Each is asked with a short
timeout; a server that is off adds nothing. Qt-free.

A found model's id is ``"<server key>:<model id>"`` (``lmstudio:qwen/qwen3-8b``,
``ollama:qwen3:8b``): it names its own server, so a remembered pick routes
(``found_model``) before any probe has answered.

The probe runs off the calling thread (``refresh``) or, in a worker thread,
directly (``discover``); the last answer is kept for the process (``known``).
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, List, Optional

SERVERS = (
    {"key": "lmstudio", "app": "LM Studio", "root": "http://localhost:1234"},
    {"key": "ollama", "app": "Ollama", "root": "http://localhost:11434"},
)
TIMEOUT = (0.5, 1.5)            # connect, read: a local server answers at once
FRESH_S = 10.0                  # a list this recent is not asked again
# A local model reads a long tool result for minutes before its first token.
READ_TIMEOUT = 600

_LOCK = threading.Lock()
_STATE: Dict[str, Any] = {"models": None, "at": 0.0, "running": False}
_WAITING: List[Callable[[], None]] = []      # told when the running probe ends


def _server(key: str) -> Optional[Dict[str, str]]:
    return next((s for s in SERVERS if s["key"] == key), None)


def _get(url: str, timeout) -> Any:
    import requests
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _lmstudio(root: str, timeout) -> List[Dict[str, Any]]:
    """LM Studio's chat models with their state and loaded context
    (``/api/v0/models``); a server without that API, by its OpenAI list. A
    model LM Studio says cannot use tools is left out: the Local LLM reads
    the chart through tools."""
    import requests
    try:
        rows = _get(root + "/api/v0/models", timeout).get("data") or []
        return [{"model": r["id"], "state": r.get("state"), "vision": r.get("type") == "vlm",
                 "context": r.get("loaded_context_length") if r.get("state") == "loaded" else None}
                for r in rows if isinstance(r, dict) and isinstance(r.get("id"), str)
                and r.get("type") != "embeddings"
                and (not isinstance(r.get("capabilities"), list)
                     or "tool_use" in r["capabilities"])]
    except (requests.ConnectionError, requests.Timeout):
        return []                                # off, or too slow: never asked twice
    except Exception:                                             # noqa: BLE001
        pass
    try:
        rows = _get(root + "/v1/models", timeout).get("data") or []
    except Exception:                                             # noqa: BLE001
        return []
    return [{"model": r["id"], "state": None, "context": None, "vision": False}
            for r in rows if isinstance(r, dict) and isinstance(r.get("id"), str)
            and "embed" not in r["id"].lower()]


def _ollama(root: str, timeout) -> List[Dict[str, Any]]:
    """Ollama's installed models (``/api/tags``), embedding models left out."""
    try:
        rows = _get(root + "/api/tags", timeout).get("models") or []
    except Exception:                                             # noqa: BLE001
        return []
    out = []
    for r in rows:
        name = r.get("name") or r.get("model") if isinstance(r, dict) else None
        if isinstance(name, str) and name and "embed" not in name.lower():
            out.append({"model": name, "state": None, "context": None, "vision": False})
    return out


def _ollama_capabilities(root: str, model: str, timeout) -> Optional[List[str]]:
    """What an Ollama model can do (``/api/show``: "tools", "vision", ...);
    None when the server does not say."""
    import requests
    try:
        r = requests.post(root + "/api/show", json={"model": model}, timeout=timeout)
        r.raise_for_status()
        caps = r.json().get("capabilities")
    except Exception:                                             # noqa: BLE001
        return None
    return [c for c in caps if isinstance(c, str)] if isinstance(caps, list) else None


_PROBES = {"lmstudio": _lmstudio, "ollama": _ollama}


def entry(server: Dict[str, str], model: str, context: Optional[int] = None,
          vision: bool = False) -> Dict[str, Any]:
    """A found model as a Local LLM choice (the shape of a fixed local setup).
    ``vision``: the server says it reads pictures (a model that cannot is
    never sent one)."""
    return {"id": f"{server['key']}:{model}", "label": f"{model} ({server['app']})",
            "url": server["root"] + "/v1", "model": model, "app": server["app"],
            "context_window": context, "vision": bool(vision), "read_timeout": READ_TIMEOUT,
            "launcher": server["app"], "discovered": True}


def probe_server(server: Dict[str, str], timeout=TIMEOUT) -> List[Dict[str, Any]]:
    """The chat models one server serves now; [] when it is off or silent."""
    rows = _PROBES[server["key"]](server["root"], timeout)
    seen, out = set(), []
    for r in rows:
        if r["model"] not in seen:
            seen.add(r["model"])
            out.append(entry(server, r["model"], r.get("context"), r.get("vision")))
    return out


def discover(servers=None, timeout=TIMEOUT) -> List[Dict[str, Any]]:
    """Ask every server at once (blocking: call it off the GUI thread), keep
    and return the models found."""
    servers = SERVERS if servers is None else servers
    results: Dict[int, List[Dict[str, Any]]] = {}

    def ask(i, server):
        try:
            results[i] = probe_server(server, timeout)
        except Exception:                                         # noqa: BLE001
            results[i] = []
    threads = [threading.Thread(target=ask, args=(i, s), daemon=True,
                                name=f"local-ai-probe-{s['key']}")
               for i, s in enumerate(servers)]
    for t in threads:
        t.start()
    budget = sum(timeout) if isinstance(timeout, tuple) else float(timeout)
    for t in threads:
        t.join(budget + 1.0)
    models = [m for i in range(len(servers)) for m in results.get(i, [])]
    with _LOCK:
        _STATE["models"] = list(models)
        _STATE["at"] = time.monotonic()
    return models


def known() -> Optional[List[Dict[str, Any]]]:
    """The models found by the last probe (None: never asked)."""
    with _LOCK:
        models = _STATE["models"]
        return None if models is None else [dict(m) for m in models]


def is_fresh(max_age: float = FRESH_S) -> bool:
    with _LOCK:
        return _STATE["models"] is not None and time.monotonic() - _STATE["at"] < max_age


def refresh(done: Optional[Callable[[], None]] = None, max_age: float = FRESH_S) -> bool:
    """Probe off the calling thread unless the last list is fresh; ``done()``
    runs on the probe's thread when it ends (every caller's, the ones that
    ask while it runs too). False, and ``done`` never called, when the list
    is fresh: the caller already shows it."""
    with _LOCK:
        if (_STATE["models"] is not None and not _STATE["running"]
                and time.monotonic() - _STATE["at"] < max_age):
            return False
        if done is not None:
            _WAITING.append(done)
        if _STATE["running"]:
            return True
        _STATE["running"] = True

    def run():
        try:
            discover()
        finally:
            with _LOCK:
                _STATE["running"] = False
                waiting = list(_WAITING)
                _WAITING.clear()
            for notify in waiting:
                try:
                    notify()
                except Exception:                                 # noqa: BLE001
                    pass
    threading.Thread(target=run, name="local-ai-discovery", daemon=True).start()
    return True


def found_model(model_id: Any) -> Dict[str, Any]:
    """The found model ``model_id`` names (``"<server key>:<model>"``), from
    the id alone, with its loaded context when the last probe saw it; {}."""
    if not isinstance(model_id, str):
        return {}
    key, sep, model = model_id.partition(":")
    server = _server(key)
    if not sep or server is None or not model.strip():
        return {}
    seen = next((m for m in known() or [] if m["id"] == model_id), None)
    return seen or entry(server, model)


def check(found: Dict[str, Any], timeout: float = 3.0) -> Dict[str, Any]:
    """Ask the found model's server again before a request (a worker
    thread): ``{"error": ...}`` when the server is off, no longer serves the
    model or says it cannot call tools, else ``{"context": loaded context or
    None, "vision": bool}``."""
    key = found["id"].partition(":")[0]
    server = _server(key)
    rows = probe_server(server, (timeout, timeout)) if server else []
    row = next((m for m in rows if m["model"] == found["model"]), None)
    if row is None:
        where = f"no server answers at {found['url']}" if not rows else \
            f"{found['app']} does not serve this model now"
        return {"error": (f"{found['label']}: {where}. Start {found['app']} with "
                          f"{found['model']}, then send again.")}
    vision = row["vision"]
    if key == "ollama":
        caps = _ollama_capabilities(server["root"], found["model"], (timeout, timeout))
        if caps is not None and "tools" not in caps:
            return {"error": (f"{found['label']}: this model cannot call tools, and the "
                              "Local LLM reads the chart through tools. Choose another model.")}
        vision = caps is not None and "vision" in caps
    return {"context": row.get("context_window"), "vision": vision}
