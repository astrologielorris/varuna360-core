"""Stable identifiers for the main window tabs (SPEC-LOC-002 INV-3, W0.2).

A tab title is display text: it will be translated, so code must never find,
count or persist a tab by its title. A tab is identified by the WIDGET it
holds. This module maps each stable tab id to the window attributes that can
hold that tab's widget (the lazy placeholder first, then the real panel that
replaces it), so ``tab_index(gui, "settings")`` finds the Settings tab whatever
its title reads.

Pure helpers: no window state is written here (Rule 4b).
"""

from __future__ import annotations

# tab id -> window attribute names that may hold the tab's widget. Order does
# not matter: at most one of them is in the tab widget at any moment.
TAB_WIDGET_ATTRS: dict[str, tuple[str, ...]] = {
    "chart": ("chart_tab",),
    "new_edit": ("edit_chart_panel", "_edit_chart_placeholder"),
    "find_chart": ("find_chart_panel", "_find_chart_placeholder"),
    "birth_finder": ("birth_finder_panel",),
    "predictive_tools": ("eclipse_panel",),
    "ai_tools": ("exploration_panel",),
    "nakshatra": ("nakshatra_panel",),
    "strengths": ("strengths_tab",),
    "settings": ("settings_tab", "_settings_placeholder"),
    "testing": ("testing_tab",),
    "debug": ("debug_tab",),
    # Not a main tab today (Transit is a Predictive Tools page); kept so the
    # callers that look for it keep their exact current behaviour (no match).
    "transit": ("transit_panel",),
}

# The English titles these tabs carried before W0.2. Used ONLY to read data
# written by older versions (tab_usage_counts keys) and as remote-control
# aliases (SPEC-REM back-compat). Never compared against a live tabText().
LEGACY_TAB_TITLES: dict[str, str] = {
    "Chart": "chart",
    "New && Edit": "new_edit",
    "New & Edit": "new_edit",
    "Find Chart": "find_chart",
    "Birth Finder": "birth_finder",
    "Predictive Tools": "predictive_tools",
    "AI Tools": "ai_tools",
    "Nakshatra": "nakshatra",
    "Strengths": "strengths",
    "Settings": "settings",
    "Testing": "testing",
    "Debug": "debug",
    "Transit": "transit",
}


# tab id -> the FIXED English title under which ``tab_usage_counts`` is
# persisted (exactly the tabText the pre-W0.2 code wrote: "New && Edit" keeps
# its double ampersand). W0 contract: no byte change to persisted values, so the
# ids live only in memory and are written back under these constants. Never
# derived from a live (translated) tabText().
# Keyed by the persisted title (a storage key, not display text) and inverted
# below, so the census does not read these keys as a table of shown labels.
_PERSISTED_TITLE_TO_ID: dict[str, str] = {
    "Chart": "chart",
    "New && Edit": "new_edit",
    "Find Chart": "find_chart",
    "Birth Finder": "birth_finder",
    "Predictive Tools": "predictive_tools",
    "AI Tools": "ai_tools",
    "Nakshatra": "nakshatra",
    "Strengths": "strengths",
    "Settings": "settings",
    "Testing": "testing",
    "Debug": "debug",
    "Transit": "transit",
}
TAB_PERSIST_TITLES: dict[str, str] = {tab_id: title for title, tab_id in _PERSISTED_TITLE_TO_ID.items()}


def register_tab(tab_id: str, attrs: tuple[str, ...], title: str) -> None:
    """Add a main tab that an edition package builds and Core does not ship
    (td-txv5v): its stable id, the window attributes that may hold its widget,
    and the fixed English title under which its usage count is persisted (also
    its remote-control alias). Called by the Pro package when it is imported.
    Without it, a stored count under that title is an unknown key, kept as it
    is and written back unchanged."""
    TAB_WIDGET_ATTRS[tab_id] = tuple(attrs)
    LEGACY_TAB_TITLES[title] = tab_id
    _PERSISTED_TITLE_TO_ID[title] = tab_id
    TAB_PERSIST_TITLES[tab_id] = title


def _tab_widget(gui):
    return getattr(gui, "tab_widget", None)


def tab_id_of_widget(gui, widget) -> str | None:
    """The stable id of ``widget`` as a main tab of ``gui``, or None."""
    if widget is None:
        return None
    for tab_id, attrs in TAB_WIDGET_ATTRS.items():
        for attr in attrs:
            if getattr(gui, attr, None) is widget:
                return tab_id
    return None


def tab_id_at(gui, index: int) -> str | None:
    """The stable id of the main tab at ``index``, or None."""
    tabs = _tab_widget(gui)
    if tabs is None or not (0 <= index < tabs.count()):
        return None
    return tab_id_of_widget(gui, tabs.widget(index))


def tab_index(gui, tab_id: str, tabs=None) -> int:
    """Index of the main tab ``tab_id`` in ``tabs`` (default ``gui.tab_widget``),
    or -1 when that tab is not present."""
    if tabs is None:
        tabs = _tab_widget(gui)
    if tabs is None:
        return -1
    for attr in TAB_WIDGET_ATTRS.get(tab_id, ()):
        widget = getattr(gui, attr, None)
        if widget is None:
            continue
        idx = tabs.indexOf(widget)
        if idx >= 0:
            return idx
    return -1


def legacy_title_to_id(title: str) -> str | None:
    """Map a pre-W0.2 English tab title (any case, ``&&`` or ``&``) to its id."""
    if not isinstance(title, str):
        return None
    if title in LEGACY_TAB_TITLES:
        return LEGACY_TAB_TITLES[title]
    wanted = title.replace("&&", "&").strip().lower()
    for legacy, tab_id in LEGACY_TAB_TITLES.items():
        if legacy.replace("&&", "&").lower() == wanted:
            return tab_id
    return None


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


class TabUsageCounts(dict):
    """Id-keyed tab usage counts that remember how each entry was stored (R3-3).

    ``storage_keys``: tab id -> the legacy title key the count was read from, so it is
    written back under the same spelling. ``kept``: legacy title keys that met another
    key of the same id, kept verbatim and written back unchanged. ``order``: the
    original key order, so an untouched file is rewritten byte for byte.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.storage_keys: dict = {}
        self.kept: dict = {}
        self.order: list = []


def migrate_tab_usage_counts(counts) -> dict:
    """Return tab usage counts keyed by stable tab id.

    Older versions persisted ``tab_usage_counts`` keyed by the English tab
    title. Title keys are mapped to their id; keys that are already ids pass
    through (summed into the id); unknown keys are kept as they are so nothing a
    user accumulated is lost.

    Each id remembers the title key it was read from, and is saved under it.
    When two title keys map to one id ("New & Edit" and "New && Edit"), the one
    today's code writes (TAB_PERSIST_TITLES) carries the in-memory count and the
    other is kept verbatim, unchanged, for the save (no merge, R3-3).
    """
    out = TabUsageCounts()
    if not isinstance(counts, dict):
        return out
    out.order = list(counts)
    legacy: dict = {}  # id -> [title keys], in file order
    for key in counts:
        if key not in TAB_WIDGET_ATTRS and legacy_title_to_id(key):
            legacy.setdefault(legacy_title_to_id(key), []).append(key)
    for tab_id, keys in legacy.items():
        persist = TAB_PERSIST_TITLES.get(tab_id)
        used = persist if persist in keys else keys[0]
        out.storage_keys[tab_id] = used
        for key in keys:
            if key != used:
                out.kept[key] = counts[key]
    for key, value in counts.items():
        if key in out.kept:
            continue
        new_key = key if key in TAB_WIDGET_ATTRS else (legacy_title_to_id(key) or key)
        if _is_number(value):
            out[new_key] = out.get(new_key, 0) + value
        else:
            out.setdefault(new_key, value)
    return out


def tab_usage_counts_for_settings(counts) -> dict:
    """The persisted form of in-memory (id-keyed) tab usage counts.

    Each id is written under the title key it was read from (TabUsageCounts), or,
    for a tab with no stored count yet, under its fixed English title
    (TAB_PERSIST_TITLES), so the settings file holds the same keys, byte for
    byte, as before W0.2. Keys kept verbatim by the migration are written back
    unchanged, in their original position. Keys that are not ids (unknown titles)
    pass through. Counts that meet under one title are summed.
    """
    if not isinstance(counts, dict):
        return {}
    storage = getattr(counts, "storage_keys", {})
    kept = getattr(counts, "kept", {})
    order = getattr(counts, "order", [])
    out: dict = {}
    for key, value in counts.items():
        title = storage.get(key) or TAB_PERSIST_TITLES.get(key, key)
        if title in out and _is_number(value) and _is_number(out[title]):
            out[title] = out[title] + value
        else:
            out.setdefault(title, value)
    for key, value in kept.items():
        out.setdefault(key, value)
    rank = {key: i for i, key in enumerate(order)}
    return dict(sorted(out.items(), key=lambda kv: rank.get(kv[0], len(rank))))


def resolve_tab_selector(gui, name: str) -> int:
    """Index of the main tab named by ``name`` for the remote API: a stable id
    (``"find_chart"``) or, as a back-compat alias, today's English title
    (``"Find Chart"``, any case). -1 when nothing matches."""
    if not isinstance(name, str):
        return -1
    key = name.strip()
    tab_id = key if key in TAB_WIDGET_ATTRS else (
        key.lower() if key.lower() in TAB_WIDGET_ATTRS else legacy_title_to_id(key))
    if tab_id is None:
        return -1
    return tab_index(gui, tab_id)
