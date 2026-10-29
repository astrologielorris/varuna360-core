# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The filter picker's model (SPEC-FIND-005 §3.3). Qt-free.

Four columns over ``core.chart_search.facets``: BODY (a subject prefix),
FACT (a value facet, menus flattened, multi-property facets split), VALUE
(the fact's picks) and DETAIL (the qualifiers offered after the value).
Easy is a filter over the same lists (INV-5): ``EASY_SUBJECTS`` and
``EASY_FACTS``.

A selection compiles through ``facets.compile``; editing a chip goes the
other way through ``load`` (from the resolved filter, never ``path_of``'s
step order), and a loaded pick the store does not hold stays selected,
annotated (D-16).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from functools import cached_property, lru_cache

from core.chart_search import facets, search
from core.chart_search.extractors.subjects import CHART, SUBJECT_GROUPS
from core.chart_search.facets import Facet, Narrow, Path, Pick, Slot, Step
from core.chart_search.search import Filter, ResolvedFilter
from core.chart_search.system import SearchSystem
from core.chart_search.taxonomy import Naming

EASY, ADVANCED = "easy", "advanced"

#: The UI's "Any" for a qualifier whose absence means any (Pada): emits no
#: step. Distinct from ``Pick(None)``, the facet's own open pick.
OMITTED = object()

NOT_STORED = "No stored matches in this system"

def _chart_rank(chart_facts, header: str) -> int:
    """A chart body's place in ``_CHART_BODY_ORDER``, by its menu's key."""
    menu = next((x.menu.key for x in chart_facts if x.header == header and x.menu), None)
    return _CHART_BODY_ORDER.index(menu) if menu in _CHART_BODY_ORDER else len(_CHART_BODY_ORDER)


# Body keys
ANY_PLANET, ANY_CUSP = "planets:*", "cusps:*"
#: WHOLE_CHART is no longer a body: it keys the cache of every chart-only
#: fact (``all_facts(WHOLE_CHART)``), the union of the CHART_BODY bodies.
WHOLE_CHART, ANY_SUBJECT = "chart", "any"
#: Chart-level bodies are named by their domain ("chart:Human Design"), one
#: per chart-only fact group, in the Chart section (Lorris 2026-10-25: a
#: generic "Whole chart" hid the Human Design reading; named, not moved).
CHART_BODY = "chart:"
#: Chart bodies in this order (by menu facet key, never its label), then any
#: other domain.
_CHART_BODY_ORDER = ("hd",)
#: Facts in the HD page's Reading order, the gate wiring after. Matched on
#: ``FactItem.key``, which is the facet key while the facet is unsplit.
_CHART_FACT_ORDER = ("hd_type", "strategy", "authority", "profile", "definition",
                     "cross", "channel", "center")
ANY_POSITION = "spread:*"

EASY_PLANETS = (
    "Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn",
    "Rahu", "Ketu", "Uranus", "Neptune", "Pluto",
)
#: Easy bodies (§3.3): Any planet, the planets, the Ascendant.
EASY_SUBJECTS: tuple[str, ...] = (
    ANY_PLANET, *(f"planets:{p}" for p in EASY_PLANETS), "cusps:Ascendant",
)
#: Easy facts as (facet key, property or None).
EASY_FACTS: tuple[tuple[str, str | None], ...] = (
    ("signs", None),
    ("whole_sign_house", None),
    ("nakshatras", None),
    ("dignity", None),
    ("motion", None),
)
#: Properties Easy searches, for ``is_easy`` (motion's property is retrograde).
_EASY_PROPERTIES = {"sign", "whole_sign_house", "nakshatra", "dignity", "retrograde"}


@dataclass(frozen=True)
class BodyItem:
    key: str
    label: str
    section: str
    prefix: Path
    easy: bool


@dataclass(frozen=True)
class FactItem:
    """One FACT: ``facet`` (VALUE) under ``menu`` when flattened;
    ``property`` set when the facet is split per property."""

    key: str
    label: str
    header: str
    facet: Facet
    menu: Facet | None
    property: str | None
    easy: bool
    chart_only: bool


@dataclass(frozen=True)
class ValueItem:
    pick: Pick
    label: str
    section: str | None = None
    #: False: valid but absent from the store, kept because it was loaded.
    stored: bool = True


@dataclass(frozen=True)
class DetailSlot:
    facet: Facet
    label: str
    items: tuple[ValueItem | object, ...]  # ValueItem, or OMITTED first
    selected: Pick | object


@dataclass(frozen=True)
class Selection:
    body: str | None = None
    fact: str | None = None
    value: Pick | None = None
    #: facet key -> Pick or OMITTED
    details: tuple[tuple[str, object], ...] = ()

    def detail(self, key: str, default=None):
        return dict(self.details).get(key, default)

    def with_detail(self, key: str, pick) -> Selection:
        d = dict(self.details)
        d[key] = pick
        return replace(self, details=tuple(d.items()))


@dataclass
class PickerModel:
    """``level`` easy/advanced; ``system`` / ``naming`` label every pick;
    ``narrow`` (``FilterChoices``) keeps values to what the store holds."""

    level: str
    system: SearchSystem
    naming: Naming
    narrow: Narrow | None = None
    _facts_cache: dict = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------- bodies
    def all_bodies(self) -> tuple[BodyItem, ...]:
        return self._bodies

    @cached_property
    def _bodies(self) -> tuple[BodyItem, ...]:
        """The catalogue depends on this model's system and naming, not level.

        Values still consult ``narrow`` live; only the static navigation is
        retained across Easy / Advanced and database refreshes.
        """
        items: list[BodyItem] = []
        for key, section in (("planets", "Planets"), ("cusps", "Ascendant / Cusps")):
            f = facets.facet(key)
            for choice in facets.choices((), f, self.system.mode, self.naming):
                subject = choice.pick.value
                bkey = f"{key}:{'*' if subject is None else subject}"
                items.append(BodyItem(bkey, choice.label, section,
                                      (Step(f, choice.pick),), bkey in EASY_SUBJECTS))
        items += [
            BodyItem(CHART_BODY + header, header, "Chart", (), False)
            for header in sorted(
                dict.fromkeys(x.header for x in self._chart_facts()),
                key=lambda h: _chart_rank(self._chart_facts(), h),
            )
        ]
        items.append(BodyItem(ANY_SUBJECT, "Any subject", "Chart", (), False))
        cot = facets.facet("cot")
        spread = facets.facet("spread")
        for choice in facets.choices((Step(cot, None),), spread, self.system.mode, self.naming):
            pos = choice.pick.value
            bkey = ANY_POSITION if pos is None else f"spread:{pos}"
            items.append(BodyItem(bkey, choice.label, "Cards of Truth spread",
                                  (Step(cot, None), Step(spread, choice.pick)), False))
        return tuple(items)

    def bodies(self) -> tuple[BodyItem, ...]:
        every = self.all_bodies()
        return every if self.level == ADVANCED else tuple(b for b in every if b.easy)

    def body(self, key: str) -> BodyItem:
        return next(b for b in self.all_bodies() if b.key == key)

    # -------------------------------------------------------------- facts
    def all_facts(self, body_key: str) -> tuple[FactItem, ...]:
        cached = self._facts_cache.get(body_key)
        if cached is not None:
            return cached
        if body_key.startswith(CHART_BODY) or body_key == WHOLE_CHART:
            if body_key != WHOLE_CHART:
                self.body(body_key)  # unknown chart body: StopIteration, as elsewhere
            header = body_key[len(CHART_BODY):]
            result = tuple(x for x in self._chart_facts()
                           if body_key == WHOLE_CHART or x.header == header)
            self._facts_cache[body_key] = result
            return result
        body = self.body(body_key)
        result = self._collect(body.prefix, body.easy, body_key)
        if body_key == ANY_SUBJECT:
            result = tuple(x for x in result if not x.chart_only)
        self._facts_cache[body_key] = result
        return result

    def _chart_facts(self) -> tuple[FactItem, ...]:
        """Every chart-only fact, in engine order (WHOLE_CHART caches it)."""
        cached = self._facts_cache.get(WHOLE_CHART)
        if cached is None:
            facts = [x for x in self._collect((), False, WHOLE_CHART) if x.chart_only]
            rank = {k: i for i, k in enumerate(_CHART_FACT_ORDER)}
            cached = tuple(sorted(facts, key=lambda x: rank.get(x.key, len(rank))))
            self._facts_cache[WHOLE_CHART] = cached
        return cached

    def _collect(self, prefix: Path, body_easy: bool, body_key: str) -> tuple[FactItem, ...]:
        out: list[FactItem] = []
        seen: set[tuple[str, str | None]] = set()

        def add(facet: Facet, menu: Facet | None, header: str) -> None:
            base = prefix + ((Step(menu, None),) if menu is not None else ())
            props = self._props(base, facet)
            split = len(props) > 1
            for prop in props:
                ident = (facet.key, prop)
                if ident in seen:
                    continue
                seen.add(ident)
                chart_only = not prefix and self._chart_only(base, facet, prop)
                label = facets._property_label(prop) if split else facets.facet_label(facet, self.system)
                key = facet.key + (f":{prop}" if split else "")
                easy = (facet.key, None) in EASY_FACTS and body_easy
                if facet.key == "motion" and not body_key.startswith("planets:"):
                    easy = False
                out.append(FactItem(key, label, header, facet, menu, prop, easy, chart_only))

        offered = facets.next_facets(prefix)
        # Flat VALUE facets first (spread prefix: the flat Card wins over the
        # menu copy, §3.3 dedupe).
        for f in offered:
            if f.slot is Slot.VALUE:
                add(f, None, f.section.value if f.section else "")
        for f in offered:
            if f.slot is Slot.MENU:
                for child in facets.next_facets(prefix + (Step(f, None),)):
                    if child.slot is Slot.VALUE:
                        add(child, f, f.label)
        return tuple(out)

    def facts(self, body_key: str) -> tuple[FactItem, ...]:
        every = self.all_facts(body_key)
        return every if self.level == ADVANCED else tuple(x for x in every if x.easy)

    def fact(self, body_key: str, fact_key: str) -> FactItem:
        return next(x for x in self.all_facts(body_key) if x.key == fact_key)

    def _props(self, base: Path, facet: Facet) -> tuple[str | None, ...]:
        if len(facet.properties) == 1:
            return (None,)
        picks = facets.choices(base, facet, self.system.mode, self.naming)
        props = tuple(dict.fromkeys(c.pick.property for c in picks))
        return props if any(p is not None for p in props) else (None,)

    def _chart_only(self, base: Path, facet: Facet, prop: str | None) -> bool:
        """No SUBJECT facet follows the open value: the property's only
        subject is the chart (engine-derived, never listed)."""
        open_pick = next(
            (c.pick for c in facets.choices(base, facet, self.system.mode, self.naming)
             if c.pick.value is None and c.pick.property == prop),
            None,
        )
        if open_pick is None:
            return False
        after = facets.next_facets(base + (Step(facet, open_pick),))
        return not any(f.slot is Slot.SUBJECT for f in after)

    # ------------------------------------------------------------- values
    def fact_path(self, body_key: str, fact_key: str) -> Path:
        x = self.fact(body_key, fact_key)
        return self.body(body_key).prefix + ((Step(x.menu, None),) if x.menu else ())

    def values(self, body_key: str, fact_key: str, keep: Pick | None = None) -> tuple[ValueItem, ...]:
        """The fact's picks, the open pick first; ``keep`` (a loaded value)
        stays listed, annotated, when the store does not hold it."""
        x = self.fact(body_key, fact_key)
        base = self.fact_path(body_key, fact_key)
        narrowed = facets.choices(base, x.facet, self.system.mode, self.naming, self.narrow)
        items = [ValueItem(c.pick, c.label, c.section) for c in narrowed
                 if x.property is None or c.pick.property == x.property]
        if keep is not None and all(i.pick != keep for i in items):
            full = facets.choices(base, x.facet, self.system.mode, self.naming)
            label = next((c.label for c in full if c.pick == keep), None)
            if label is not None:
                items.append(ValueItem(keep, label, None, stored=False))
        return tuple(items)

    # ------------------------------------------------------------ details
    def value_path(self, sel: Selection) -> Path | None:
        if sel.body is None or sel.fact is None or sel.value is None:
            return None
        x = self.fact(sel.body, sel.fact)
        return self.fact_path(sel.body, sel.fact) + (Step(x.facet, sel.value),)

    def details(self, sel: Selection) -> tuple[DetailSlot, ...]:
        """One slot per QUALIFIER (and later VALUE) facet offered after the
        value, in engine order, each list computed after the slots before it."""
        path = self.value_path(sel)
        if path is None:
            return ()
        slots: list[DetailSlot] = []
        handled: set[str] = set()
        while True:
            nxt = [f for f in facets.next_facets(path)
                   if f.slot is not Slot.SUBJECT and f.slot is not Slot.MENU and f.key not in handled]
            if not nxt:
                break
            f = nxt[0]
            handled.add(f.key)
            initial = self._initial(path, f)
            chosen = sel.detail(f.key, initial)
            items = self._detail_items(path, f, chosen)
            if chosen is not OMITTED and chosen not in [i.pick for i in items if isinstance(i, ValueItem)]:
                chosen = initial
            slots.append(DetailSlot(f, facets.facet_label(f, self.system), items, chosen))
            if chosen is not OMITTED:
                path = path + (Step(f, chosen),)
        return tuple(slots)

    def _initial(self, path: Path, f: Facet):
        if f.slot is Slot.QUALIFIER:
            absent = facets.absent_pick(path, f)
            return OMITTED if absent is None else absent
        picks = facets.choices(path, f, self.system.mode, self.naming)
        return picks[0].pick if picks else OMITTED

    def _detail_items(self, path: Path, f: Facet, keep) -> tuple:
        narrowed = facets.choices(path, f, self.system.mode, self.naming, self.narrow)
        items: list = [ValueItem(c.pick, c.label, c.section) for c in narrowed]
        if f.slot is Slot.QUALIFIER and facets.absent_pick(path, f) is None:
            items.insert(0, OMITTED)
        if keep is not None and keep is not OMITTED and all(
            not isinstance(i, ValueItem) or i.pick != keep for i in items
        ):
            full = facets.choices(path, f, self.system.mode, self.naming)
            label = next((c.label for c in full if c.pick == keep), None)
            if label is not None:
                items.append(ValueItem(keep, label, None, stored=False))
        return tuple(items)

    # ------------------------------------------------------------ compile
    def path(self, sel: Selection) -> Path | None:
        path = self.value_path(sel)
        if path is None:
            return None
        for slot in self.details(sel):
            if slot.selected is not OMITTED:
                path = path + (Step(slot.facet, slot.selected),)
        return path

    def filter(self, sel: Selection) -> Filter | None:
        path = self.path(sel)
        return None if path is None else facets.compile(path)

    def needs_detail(self, sel: Selection) -> bool:
        """A Detail must be picked before ADD (none today: every slot has an
        initial pick); kept for VALUE details."""
        return False

    # --------------------------------------------------------------- load
    def load(self, f: Filter, fact_hint: str | None = None) -> Selection:
        """The selection that edits ``f`` (§3.3 Load). Resolves once;
        ``BadFilterError`` for an invalid filter. The selection compiles to
        an equal ResolvedFilter (T-3)."""
        resolved = search.resolve(f)
        prop = resolved.spec.name
        body = self._body_for(resolved)
        candidates = [x for x in self.all_facts(body)
                      if (x.property == prop) or (x.property is None and prop in x.facet.properties)]
        if not candidates:
            raise ValueError(f"no picker fact for {prop!r} under {body!r}")
        fact = next((x for x in candidates if x.key == fact_hint), None)
        if fact is None:
            fact = next((x for x in candidates if x.facet.relabel is None), candidates[0])
        value = Pick(resolved.value, fact.property)
        sel = Selection(body, fact.key, value)
        given = {
            q.name: v
            for q, v in zip(resolved.spec.qualifiers, (resolved.q1, resolved.q2), strict=False)
        }
        defaults = {q.name: q.default for q in resolved.spec.qualifiers}
        # Walk the detail slots in order, choosing each from the filter.
        for _ in range(4):
            changed = False
            for slot in self.details(sel):
                name = slot.facet.qualifier
                if name is None or name not in given:
                    continue
                v = given[name]
                pick = slot.selected if v == defaults[name] else Pick(v)
                if sel.detail(slot.facet.key, None) != pick:
                    sel = sel.with_detail(slot.facet.key, pick)
                    changed = True
            if not changed:
                break
        return sel

    def _chart_body_for(self, prop: str) -> str:
        """The named chart body whose facts search ``prop``."""
        for x in self._chart_facts():
            if x.property == prop or (x.property is None and prop in x.facet.properties):
                return CHART_BODY + x.header
        raise ValueError(f"no chart body for {prop!r}")

    def _body_for(self, resolved: ResolvedFilter) -> str:
        spec = resolved.spec
        subjects = resolved.subjects
        if spec.name == "card":
            # Any position only for an open subject; one position only when
            # the spread offers it; a group of positions has no Body and is
            # refused (never widened to Any position, review r4).
            if subjects is None:
                return ANY_POSITION
            if len(subjects) == 1:
                key = f"spread:{subjects[0]}"
                if any(b.key == key for b in self.all_bodies()):
                    return key
            raise ValueError(f"no picker body for card subjects {subjects!r}")
        if subjects == (CHART,) or (subjects is None and spec.subjects == (CHART,)):
            return self._chart_body_for(spec.name)
        if subjects is None:
            return ANY_SUBJECT
        if len(subjects) == 1:
            for key in ("planets", "cusps"):
                if subjects[0] in facets.facet(key).subjects:
                    return f"{key}:{subjects[0]}"
        for key in ("planets", "cusps"):
            f = facets.facet(key)
            if f.group is not None:
                members = tuple(s for s in SUBJECT_GROUPS[f.group] if s in spec.subjects)
                if set(members) == set(subjects):
                    return f"{key}:*"
        raise ValueError(f"no picker body for subjects {subjects!r}")

    # ---------------------------------------------------------------- easy
    def extra_in_advanced(self, column: str, body_key: str | None = None) -> tuple[int, tuple[str, ...]]:
        """Easy column footers: how many items Advanced adds, and their labels."""
        if column == "body":
            extra = [b.label for b in self.all_bodies() if not b.easy]
        else:
            extra = [x.label for x in self.all_facts(body_key) if not x.easy] if body_key else []
        return len(extra), tuple(extra)


def is_easy(f: Filter) -> bool:
    """§3.2: Easy body, Easy fact, no qualifier but an omitted or explicit D1
    varga (motion for planets only)."""
    try:
        resolved = search.resolve(f)
    except Exception:  # noqa: BLE001 - an invalid filter is not Easy
        return False
    prop = resolved.spec.name
    if prop not in _EASY_PROPERTIES:
        return False
    subjects = resolved.subjects
    planets = set(EASY_PLANETS)
    group = facets.facet("planets").group
    group_members = {s for s in SUBJECT_GROUPS.get(group, ()) if s in resolved.spec.subjects} if group else set()
    if subjects is None:
        return False
    if set(subjects) == group_members:
        body_ok = True
    elif len(subjects) == 1:
        body_ok = subjects[0] in planets or (subjects[0] == "Ascendant" and prop != "retrograde")
    else:
        body_ok = False
    if not body_ok:
        return False
    for q, v in zip(resolved.spec.qualifiers, (resolved.q1, resolved.q2), strict=False):
        if v != q.default:
            return False
    return True


#: Easy suggestion chips (§3.3), as filters; labels come from the taxonomy.
SUGGESTIONS: tuple[Filter, ...] = (
    Filter("Sun", "sign", 8),
    Filter("Moon", "nakshatra", 8),
    Filter("Mars", "dignity", "EX"),
    Filter("Saturn", "retrograde", 1),
)


def suggestion_label(f: Filter, model: PickerModel) -> str:
    sel = model.load(f)
    body = model.body(sel.body).label
    value = next(v.label for v in model.values(sel.body, sel.fact, keep=sel.value) if v.pick == sel.value)
    return f"{body} · {value}"


@lru_cache(maxsize=8)
def suggestion_labels(system: SearchSystem, naming: Naming) -> tuple[str, ...]:
    """Suggestions label fixed filters, independent of database narrowing."""
    model = PickerModel(EASY, system, naming)
    return tuple(suggestion_label(f, model) for f in SUGGESTIONS)


def chip_text(model: PickerModel, f: Filter, path_text: Callable[[Path], str] | None = None) -> str:
    """"Sun · Sign · Vishnu · D9": body, fact, value and each non-default
    detail, labelled in the model's system and naming."""
    sel = model.load(f)
    parts = [model.body(sel.body).label, model.fact(sel.body, sel.fact).label]
    value = next((v.label for v in model.values(sel.body, sel.fact, keep=sel.value) if v.pick == sel.value), "")
    parts.append(value)
    path = model.value_path(sel) or ()
    for slot in model.details(sel):
        initial = model._initial(path, slot.facet)
        if slot.selected is not OMITTED and slot.selected != initial:
            label = next((i.label for i in slot.items
                          if isinstance(i, ValueItem) and i.pick == slot.selected), "")
            parts.append(label)
        if slot.selected is not OMITTED:
            path = path + (Step(slot.facet, slot.selected),)
    return " · ".join(p for p in parts if p)


def equal_filters(a: Filter | None, b: Filter | None) -> bool:
    """Two filters search the same (their resolved forms are equal)."""
    if a is None or b is None:
        return a is b
    return search.resolve(a) == search.resolve(b)


__all__: Sequence[str] = (
    "PickerModel", "Selection", "OMITTED", "is_easy", "SUGGESTIONS",
    "chip_text", "equal_filters", "EASY", "ADVANCED",
)
