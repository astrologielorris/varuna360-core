# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Settings tab rows that follow the dasha panels' own choices (td-fj70t.11.5).

The dasha chooser (ayanamsa) writes the
same keys as Settings > Zodiac calculation. The tab reads its rows once and its
Apply writes every row back, so without this a pick made in a panel would show
the old value in the tab and be undone by the next unrelated Apply.

Rule: when a key changes outside the tab, its combo shows the new value, unless
the user has edited that combo since it last showed the stored value (an
unapplied edit wins, as everywhere in the tab). Kept out of ui/settings_tab.py,
which only calls `attach`.
"""
import weakref


def _pairs(tab):
    """(combo, key) of every tab row a dasha panel can write."""
    pairs = [
        (tab.dasha_left_combo, "dasha.left.ayanamsa_id"),
        (tab.dasha_right_combo, "dasha.right.ayanamsa_id"),
    ]
    return pairs


def attach(tab, settings=None):
    """Subscribe `tab`'s dasha rows to outside changes of their keys; the
    subscriptions end when the tab is destroyed."""
    if settings is None:
        from managers.settings_manager import get_settings
        settings = get_settings()
    from core import settings_registry
    tab_ref = weakref.ref(tab)
    subs = []
    for combo, key in _pairs(tab):
        default = settings_registry.get(key).default
        state = {"stored": settings.get(key, default)}
        combo_ref = weakref.ref(combo)

        def on_change(_path=None, _value=None, key=key, default=default,
                      state=state, combo_ref=combo_ref):
            combo = combo_ref()
            if combo is None or tab_ref() is None:
                return
            try:
                import shiboken6
                if not shiboken6.isValid(combo):
                    return
            except ImportError:
                pass
            value = settings.get(key, default)      # re-read (notify contract)
            shown = combo.currentData()
            unedited = shown == state["stored"]
            state["stored"] = value
            if unedited and shown != value:
                idx = combo.findData(value)
                if idx >= 0:
                    # signals ON: the tab's own reactions follow; none of
                    # them writes a setting
                    combo.setCurrentIndex(idx)

        settings.on_changed(key, on_change)
        subs.append((key, on_change))

    def detach(*_a, subs=subs):
        for key, cb in subs:
            settings.remove_on_changed(key, cb)
    tab.destroyed.connect(detach)
    return detach
