# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The THREAD key: exchange chains on the charts (SPEC-EXCH-002 §4.3, td-m79zy).

The one owner of the overlay's state (INV-6, Rule 4b: no ChartGUI attribute):
- on / off = ``chart.exchange_chain_on`` and the link style
  ``chart.exchange_chain_style`` live in the settings registry, written through
  ``persist_runtime_change`` (a locked key is left alone);
- the focused exchange (a card click) is runtime only, never persisted, and is
  dropped when the chart's exchanges no longer hold it.
Any writer of the two keys (the THREAD key, Settings Apply, a remote or AI
``set_setting``, a section reset) reaches the views through ``watch``: one
coalesced light redraw (``exchange_chain_items.refresh_chains``), never the
host redraw.
"""
from __future__ import annotations

from core import exchange_chain as xc


def _items():
    from apps.widgets import exchange_chain_items
    return exchange_chain_items


def is_on(get) -> bool:
    return xc.chain_on(get)


class ExchangeChainSwitch:
    """Writes the THREAD key and the focus."""

    def __init__(self, gui=None, settings=None):
        self._gui = gui
        self._settings = settings

    def _s(self):
        if self._settings is None:
            from managers.settings_manager import get_settings
            self._settings = get_settings()
        return self._settings

    def say(self, text):
        bar = getattr(self._gui, "statusBar", None) if self._gui is not None else None
        if callable(bar):
            bar().showMessage(text, 3000)

    def select(self, on):
        """THREAD on / off. Returns the new state, or None when the key is locked."""
        s = self._s()
        if s.is_locked(xc.KEY_ON):
            from core.i18n import t
            self.say(t("panel.exchange.thread_locked", "Exchange chains are locked in Settings"))
            return None
        ensure_watch(s)
        if not on:
            set_focus(None)
        s.persist_runtime_change(xc.KEY_ON, bool(on))
        refresh_now()            # the watch coalesces; this makes the click immediate
        return bool(on)

    def toggle(self):
        return self.select(not is_on(self._s().get))


def set_focus(pair):
    """Focus one exchange (others at 18 %), or None for all. Only opacities change."""
    items = _items()
    pair = tuple(pair) if pair else None
    if pair == items.focus():
        return pair
    items.set_focus(pair)
    items.refresh_focus()
    return pair


def toggle_focus(pair):
    """A card click: focus it, or clear when it was the focused one."""
    return set_focus(None if _items().focus() == tuple(pair) else pair)


def chart_changed(links):
    """The active chart's exchanges changed: drop a focus they no longer hold."""
    current = _items().focus()
    if current is not None and current not in {lk.pair for lk in links}:
        set_focus(None)


def refresh_now():
    return _items().refresh_now()


def ensure_watch(settings=None):
    """Subscribe once (process life) to the two keys: any writer redraws the chains."""
    if settings is None:
        from managers.settings_manager import get_settings
        settings = get_settings()
    return _items().ensure_watch(settings)
