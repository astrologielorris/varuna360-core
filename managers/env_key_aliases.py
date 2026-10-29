# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Legacy API-key name aliases, as a registration hook (Core never imports pro).

``SettingsManager`` resolves an API key under its canonical name and then its
legacy spellings (``Deepseek_API_KEY`` for ``DEEPSEEK_API_KEY``...). The alias
table belongs to the Pro provider layer (``pro.providers.registry``), and Core
code must never import ``pro`` (``.importlinter`` no-pro-imports). So Pro
registers a provider here when the ``pro`` package is imported
(``pro/__init__.py``); Core alone (Lite) has none and every key has no alias.

Stdlib only, no imports: safe from any import cycle.
"""
from __future__ import annotations

from typing import Callable, Iterable, List

AliasProvider = Callable[[str], Iterable[str]]

_PROVIDERS: List[AliasProvider] = []


def register_alias_provider(provider: AliasProvider) -> None:
    """Add a ``canonical name -> legacy names`` provider (idempotent)."""
    if provider not in _PROVIDERS:
        _PROVIDERS.append(provider)


def legacy_aliases_for(canonical: str) -> List[str]:
    """Every registered legacy alias of ``canonical``, in registration order.
    A provider that fails contributes nothing (the old lazy import did the
    same)."""
    out: List[str] = []
    for provider in list(_PROVIDERS):
        try:
            out.extend(provider(canonical) or ())
        except Exception:
            continue
    return out
