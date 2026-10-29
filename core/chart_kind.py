"""What kind of chart a chart-memory / session entry is (td-chart-kind).

Every entry carries ``kind``: a person's birth chart, or one of the event
charts the app makes itself (a Now chart, a dasha moment, an eclipse, a lunar
chart, a birth-time-finder result, an exploration chart). Find Chart leaves
event charts out of its searches by default; bulk export skips transits.

``is_transit`` stays on every entry for compatibility: it is True exactly for
the moment kinds (``transit``, ``dasha_moment``), which is what it meant
before ``kind`` existed.

Entries saved before ``kind`` existed are classified once on load by
:func:`entry_kind`, from ``is_transit`` and the names the app itself gives
event charts. A legacy exploration chart cannot be told from a birth chart
(it is a .chtk with a person-like name), so it stays ``birth``.
"""
import re

BIRTH = "birth"
TRANSIT = "transit"
DASHA_MOMENT = "dasha_moment"
ECLIPSE = "eclipse"
LUNAR = "lunar"
BIRTH_TIME_FINDER = "birth_time_finder"
EXPLORATION = "exploration"

KINDS = (BIRTH, TRANSIT, DASHA_MOMENT, ECLIPSE, LUNAR, BIRTH_TIME_FINDER, EXPLORATION)
EVENT_KINDS = frozenset(KINDS) - {BIRTH}
MOMENT_KINDS = frozenset({TRANSIT, DASHA_MOMENT})   # what is_transit means

# Names the app gives its own event charts (core_gui_qt, dasha_manager,
# eclipse_panel, lunar_new_year_panel). Used ONLY for entries saved before
# ``kind`` existed.
_LEGACY_NAMES = (
    (re.compile(r"^Dasha \S+ \d{4}-\d{2}-\d{2}$"), DASHA_MOMENT),
    (re.compile(r"^\S+ Eclipse \d{4}-\d{2}-\d{2}"), ECLIPSE),
    (re.compile(r"^Eclipse \d{4}$"), ECLIPSE),
    (re.compile(r"^Lunar, "), LUNAR),
    (re.compile(r"^Lunar New Year \d{4}$"), LUNAR),
    (re.compile(r"^Birth Finder Result \("), BIRTH_TIME_FINDER),
)


def _entry_name(entry):
    recipe = entry.get("recipe") if isinstance(entry.get("recipe"), dict) else {}
    return str(recipe.get("name") or entry.get("person_name") or "").strip()


def is_transit_kind(kind):
    return kind in MOMENT_KINDS


def entry_kind(entry):
    """The entry's kind: its stored ``kind`` when valid, else the legacy
    classification (``is_transit`` plus the app's own event-chart names)."""
    kind = entry.get("kind")
    if kind in KINDS:
        return kind
    name = _entry_name(entry)
    for pattern, legacy_kind in _LEGACY_NAMES:
        # A moment name counts only with is_transit (every old dasha-moment
        # entry has it, a person called "Dasha ..." does not); an event name
        # only without it.
        if pattern.search(name) and (legacy_kind in MOMENT_KINDS) == bool(entry.get("is_transit")):
            return legacy_kind
    if entry.get("is_transit") or name.lower().startswith("now "):
        return TRANSIT
    return BIRTH


def is_event(entry):
    """True for every chart that is not a person's birth chart."""
    return entry_kind(entry) in EVENT_KINDS


def resolve_kind(kind=None, is_transit=False):
    """The kind a new entry gets from an ``add_chart`` call: the explicit
    ``kind`` when given, else ``transit`` for ``is_transit=True`` callers,
    else ``birth``."""
    if kind is not None:
        if kind not in KINDS:
            raise ValueError(f"unknown chart kind {kind!r}; expected one of {KINDS}")
        return kind
    return TRANSIT if is_transit else BIRTH
