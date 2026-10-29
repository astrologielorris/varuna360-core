# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Edition features as registration hooks (Core never imports the Pro tree).

Core code must not import the Pro package (``.importlinter`` no-pro-imports;
the Lite build strips such imports and a stripped name then fails at run
time). Where Core reaches a Pro feature (the Pro main window, the South Indian
host widget class, the AI tool registry and chat layer of the terminal, the Pro
CHTK writer), the Pro package registers a provider here when it is imported
(``pro/__init__.py``), and Core asks for it by name:

    from core.edition_hooks import resolve
    writer = resolve(CHTK_WRITER)         # None when the edition has none

Nothing here loads an edition: the process entry point imports the Pro package
in the Pro edition (the launcher ``run_app.py`` for the GUI and ``--tool``, or a
module under the Pro tree for a Pro CLI), which registers everything. A name
nobody registered resolves to the default (Core alone, the Lite build, or a
Core script run directly).

A provider is a zero-argument callable that imports lazily and returns the
object; an ImportError while it runs means "not available" (None), exactly as
the old ``try: from <pro module> import X / except ImportError`` did. Any
other error propagates, as before.

Stdlib only at import: safe from any import cycle.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

MAIN_WINDOW_CLASS = "main_window_class"   # the edition's main window class
SOUTH_INDIAN_HOST_CLASS = "south_indian_host_class"  # the South Indian host widget class
AI_TOOL_REGISTRY = "ai_tool_registry"     # TOOL_COMMANDS / get_tool_definitions module
AI_CHAT = "ai_chat"                       # available_provider_ids / build_chat_worker module
CHTK_WRITER = "chtk_writer"               # create_chtk(...) callable
AI_TOOL_SERVER = "ai_tool_server"         # varuna_mcp module (the Pro tool list)
AI_CLI_TOOLS = "ai_cli_tools"             # ((name, module, summary), ...): the edition's All tools commands
CHART_RENDERER = "chart_renderer"         # the render_chart CLI module (the MCP chart picture)
VALUE_WORDS = "value_words"               # {setting key: value -> words} for AI keys (core/ai_capture; Lite: none)

Provider = Callable[[], Any]

_PROVIDERS: Dict[str, Provider] = {}


def register(name: str, provider: Provider) -> None:
    """Register (or replace) the provider of feature ``name``."""
    _PROVIDERS[name] = provider


def unregister(name: str) -> None:
    """Remove a provider (tests)."""
    _PROVIDERS.pop(name, None)


def provider(name: str) -> Optional[Provider]:
    """The registered provider of ``name``; None when nothing registered it."""
    return _PROVIDERS.get(name)


def resolve(name: str, default: Any = None) -> Any:
    """The object feature ``name`` provides, or ``default`` when no provider
    is registered or the provider raises ImportError."""
    fn = provider(name)
    if fn is None:
        return default
    try:
        return fn()
    except ImportError:
        return default
