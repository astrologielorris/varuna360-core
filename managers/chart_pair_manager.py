# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""ChartPairManager: the Chart tab's two-chart mode (SPEC-DUAL-001, td-1mgk7).

Owns everything about the pair: the mode, chart B (an immutable snapshot built
WITHOUT activating it), the session memory of B, identity checks against chart
A, the checked activation behind swap and ✕ on A, the one ChartState listener
that rebuilds B on a frame change, B's single render authority, the shortcuts
and the fullscreen extra. ``ChartGUI`` holds exactly one attribute for it
(``chart_pair``, INV-9); the row geometry belongs to ChartLayoutManager
(``set_two_chart``), the pill to the action bar (``bar.pair``).

Rule 4b: this module never writes an attribute of the GUI object. It reads
GUI state, calls GUI / collaborator methods and dispatches through the
canonical activation paths (memory select, file load) only in a checked
activation (§3.4).
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QKeyCombination, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut

from core.i18n import t

_M, _K = Qt.KeyboardModifier, Qt.Key
SHORTCUT_TOGGLE = (_M.AltModifier, _K.Key_2)
SHORTCUT_SWAP = (_M.ControlModifier | _M.ShiftModifier, _K.Key_2)
B_VIEWS = ("south_indian", "wheel", "north_indian")


def resolve_path(path) -> str | None:
    """A chart file path normalised for identity (§3.2), or None."""
    if not path:
        return None
    try:
        return str(Path(path).expanduser().resolve())
    except (OSError, RuntimeError, TypeError, ValueError):
        return str(path)


def same_chart(a: dict | None, b: dict | None) -> bool:
    """SPEC-DUAL-001 §3.2: the same chart when the memory ids are equal or the
    resolved paths are equal (a memory entry's chtk_path counts as its path)."""
    if not a or not b:
        return False
    if a.get("memory_id") and a.get("memory_id") == b.get("memory_id"):
        return True
    return bool(a.get("path")) and a.get("path") == b.get("path")


@dataclass
class ChartB:
    """What the B frame shows. ``snapshot`` is never re-read from its source
    (D-17): ``{"recipe": dict}`` (memory entry, old A or sky, deep copy) or
    ``{"params": {jd, lat, lon, name, utcoffset}}`` (file, as built)."""
    chart: object
    label: str
    birth: object
    snapshot: dict
    identity: dict
    route: str                         # "memory" | "file" | "sky"
    frame: tuple
    kind: str = "birth"                # memory kind for the add route
    generation: int = 0
    extra: dict = field(default_factory=dict)

    def summary(self) -> dict:
        return {"label": self.label, "route": self.route}


class ChartPairManager(QObject):
    """Frozen API: SPEC-DUAL-001 plan §4."""

    changed = Signal(str)

    def __init__(self, gui):
        super().__init__(gui)
        self._gui = gui
        self._installed = False
        self._mode = "one"
        self._b: ChartB | None = None
        self._remembered: ChartB | None = None
        self._busy = False
        self._gen = 0
        self._a_record = None          # current A: {identity, recipe, kind, label}
        self._render_sig = None
        self._render_count = 0         # T-9 render-count probe
        self._render_pending = False
        self._frame = None             # ChartBFrame (built by install)
        self._a_chip = None            # A header chip (raised child of chart_stack)
        self._shortcuts = []
        self._listening = False
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(0)
        self._render_timer.timeout.connect(self._render_now)
        self._record_timer = QTimer(self)
        self._record_timer.setSingleShot(True)
        self._record_timer.setInterval(0)
        self._record_timer.timeout.connect(self._refresh_a_record)

    # ------------------------------------------------------------------ setup
    def install(self) -> None:
        """After ``chart_layout.install()``: B frame, A chip, shortcuts and the
        one ChartState listener. Idempotent."""
        if self._installed:
            return
        self._installed = True
        gui = self._gui
        self._build_widgets()
        tab = getattr(gui, "chart_tab", None)
        if tab is not None:
            for (mods, key), slot in ((SHORTCUT_TOGGLE, self.toggle),
                                      (SHORTCUT_SWAP, self._swap_shortcut)):
                sc = QShortcut(QKeySequence(QKeyCombination(mods, key)), tab)
                sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
                sc.activated.connect(slot)
                self._shortcuts.append(sc)
            tab.destroyed.connect(self._on_tab_destroyed)
        gui.state.connect(self._on_state)
        self._listening = True
        self.changed.connect(self._sync_bar)
        self._refresh_a_record()

    def _build_widgets(self) -> None:
        """The B frame and the A header chip (SPEC-DUAL-001 §4.2): the frame
        is inserted ONCE into chart_content's row right after chart_stack
        (hidden, stretch 1); the A chip is a raised child of chart_stack shown
        in its top margin band in mode two (INV-1: chart_stack never moves)."""
        gui = self._gui
        lay = getattr(gui, "chart_layout", None)
        content = getattr(gui, "chart_content", None)
        stack = getattr(gui, "chart_stack", None)
        if lay is None or content is None or stack is None or not hasattr(lay, "b_host_index"):
            return
        from apps.widgets.chart_b_frame import ChartBFrame, ChartHeaderChip
        self._frame = ChartBFrame(
            on_drop=self.handle_b_drop,
            on_sky_now=lambda *_: self.set_b_sky_now(),
            on_open_file=lambda *_: self.pick_b_file(),
            on_close=self.forget_b,
            on_shown=self.on_frame_shown)
        self._frame.hide()
        content.layout().insertWidget(lay.b_host_index(), self._frame, 1)
        self._a_chip = ChartHeaderChip(stack)
        self._a_chip.hide()

    def header_height(self) -> int:
        return self._frame.header_row.height() if self._frame is not None else 0

    def _sync_frames(self) -> None:
        """The B frame's empty / filled state and both header chips."""
        frame, chip = self._frame, self._a_chip
        if frame is None:
            return
        a_name = self.a_name()
        if self._b is None:
            if not frame.is_empty():
                self._render_sig = None
                frame.show_empty(a_name)
            else:
                frame.set_a_name(a_name)
        else:
            frame.set_a_name(a_name)
        if chip is not None and self._mode == "two":
            chip.set_content("a", a_name, t("chart.pair.header_a", "active chart"), False)
            h = self.header_height()
            chip.move(0, max(0, (h - chip.height()) // 2))

    def _show_frames(self, on: bool) -> None:
        """Mode two: B frame + A band (chart_stack top margin) shown; mode
        one: hidden and the margin back to 0."""
        frame, chip, stack = self._frame, self._a_chip, getattr(self._gui, "chart_stack", None)
        if frame is None or stack is None:
            return
        if on:
            self._sync_frames()
            stack.setContentsMargins(0, self.header_height(), 0, 0)
            frame.show()
            chip.show()
            chip.raise_()
        else:
            frame.hide()
            chip.hide()
            stack.setContentsMargins(0, 0, 0, 0)

    def _on_tab_destroyed(self, *_):
        self.teardown()

    def teardown(self) -> None:
        """Stop timers and disconnect the ChartState listener (§4.3)."""
        for timer in (self._render_timer, self._record_timer):
            try:
                timer.stop()
            except RuntimeError:
                pass
        if self._listening:
            self._listening = False
            try:
                self._gui.state.disconnect(self._on_state)
            except (ValueError, AttributeError):
                pass

    # ------------------------------------------------------------ read access
    def mode(self) -> str:
        return self._mode

    def b(self) -> ChartB | None:
        return self._b

    def remembered(self) -> ChartB | None:
        return self._remembered

    def busy(self) -> bool:
        return self._busy

    def render_count(self) -> int:
        return self._render_count

    def frame(self):
        return self._frame

    def state(self) -> dict:
        lay = getattr(self._gui, "chart_layout", None)
        drawer = bool(lay.info_drawer_open()) if lay is not None and hasattr(
            lay, "info_drawer_open") else False
        return {"mode": self._mode,
                "b": self._b.summary() if self._b else None,
                "remembered": self._remembered.label if self._remembered else None,
                "drawer_open": drawer,
                "fullscreen": self._fullscreen(),
                "busy": self._busy}

    # ----------------------------------------------------------------- helpers
    def _status(self, message: str) -> None:
        try:
            self._gui.statusBar().showMessage(message, 6000)
        except Exception:
            pass

    def _refuse(self, message: str) -> tuple[bool, str]:
        self._status(message)
        return False, message

    def _fullscreen(self) -> bool:
        vfm = getattr(self._gui, "view_float_manager", None)
        try:
            return bool(vfm is not None and vfm.is_fullscreen)   # a property
        except Exception:
            return False

    def _memory(self):
        return getattr(self._gui, "memory_panel", None)

    def _index_of(self, entry_id) -> int | None:
        mp = self._memory()
        if mp is None or not entry_id:
            return None
        for i, entry in enumerate(getattr(mp, "charts", [])):
            if entry.get("id") == entry_id:
                return i
        return None

    def _entry(self, entry_id):
        i = self._index_of(entry_id)
        return None if i is None else self._memory().charts[i]

    def current_frame(self) -> tuple:
        """(mode, ayanamsa id, house system, custom definition). The id-255
        value/year is part of the frame: editing it keeps the id, and B must
        still rebuild with A (review 2026-10-23)."""
        from core import custom_ayanamsa_settings
        g = self._gui
        ayanamsa_id = getattr(g, "chart_sidereal_ayanamsa_id", 100)
        return (g.state.aditya_mode, ayanamsa_id, g.state.house_system,
                custom_ayanamsa_settings.frame_part(ayanamsa_id))

    def _sp_identity(self) -> dict:
        sp = self._gui.state.source_params or {}
        return {"memory_id": sp.get("origin_memory_id"),
                "path": resolve_path(sp.get("chtk_path"))}

    @staticmethod
    def _entry_matches(entry, ident, sp) -> bool:
        if ident.get("memory_id"):
            return entry.get("id") == ident["memory_id"]
        if ident.get("path"):
            return resolve_path(entry.get("chtk_path")) == ident["path"]
        name = ((sp or {}).get("birth_data") or {}).get("name")
        return bool(name) and (entry.get("recipe") or {}).get("name") == name

    def a_identity(self) -> dict:
        """Chart A's identity (§3.2): the active chart's source params merged
        with the memory row's current entry when that entry is A's."""
        ident = self._sp_identity()
        mp = self._memory()
        entry = mp.get_current_chart() if mp is not None else None
        if entry is not None and self._entry_matches(entry, ident,
                                                     self._gui.state.source_params):
            ident = {"memory_id": ident["memory_id"] or entry.get("id"),
                     "path": ident["path"] or resolve_path(entry.get("chtk_path"))}
        return ident

    def a_name(self) -> str:
        sp = self._gui.state.source_params or {}
        name = (sp.get("birth_data") or {}).get("name")
        if not name:
            chart = self._gui.state.active_chart
            name = getattr(getattr(chart, "context", None), "name", "") if chart else ""
        return (name or "").title() if name else ""

    def _refresh_a_record(self) -> None:
        """Remember A (identity + recipe copy) for T15's "B becomes the
        previous A". Only data; never decides a transition."""
        if self._gui.state.active_chart is None:
            return
        ident = self.a_identity()
        mp = self._memory()
        entry = mp.get_current_chart() if mp is not None else None
        recipe = kind = None
        if entry is not None and self._entry_matches(entry, ident,
                                                     self._gui.state.source_params):
            recipe = copy.deepcopy(entry.get("recipe"))
            kind = entry.get("kind")
        prev = self._a_record
        if prev is not None and same_chart(prev["identity"], ident) and recipe is None:
            recipe, kind = prev.get("recipe"), prev.get("kind")
        self._a_record = {"identity": ident, "recipe": recipe, "kind": kind or "birth",
                          "label": self.a_name()}
        if self._mode == "two":
            self._sync_bar()                 # A's short meta reads this record

    # ------------------------------------------------------------- B building
    def _next_gen(self) -> int:
        self._gen += 1
        return self._gen

    def _build_chart(self, snapshot: dict):
        """Rebuild B natal in the current frame from its snapshot (INV-6)."""
        g = self._gui
        mode = g.state.aditya_mode
        ayan = getattr(g, "chart_sidereal_ayanamsa_id", 100)
        if "recipe" in snapshot:
            from core.chart_factory import build_chart_from_recipe
            recipe = copy.deepcopy(snapshot["recipe"])
            recipe["house_system"] = g.state.house_system
            return build_chart_from_recipe(recipe, mode, ayan)
        from core.chart_factory import build_chart_from_params
        return build_chart_from_params(**snapshot["params"], mode=mode, ayanamsa=ayan,
                                       hsys=g.state.house_system_code)

    def _b_from_memory(self, entry_id) -> ChartB:
        entry = self._entry(entry_id)
        if entry is None:
            raise LookupError(t("chart.pair.not_in_memory",
                                "Could not find that chart in memory."))
        chart, label, birth, recipe = self._gui.chart_overlay_manager.build_from_memory_id(
            entry_id)
        return ChartB(chart=chart, label=(label or "").title(), birth=birth,
                      snapshot={"recipe": recipe},
                      identity={"memory_id": entry_id,
                                "path": resolve_path(entry.get("chtk_path"))},
                      route="memory", frame=self.current_frame(),
                      kind=entry.get("kind") or "birth", generation=self._next_gen())

    def _b_from_file(self, path) -> ChartB:
        chart, label, birth, params = self._gui.chart_overlay_manager.build_from_file(path)
        return ChartB(chart=chart, label=(label or Path(path).stem).title(), birth=birth,
                      snapshot={"params": dict(params)},
                      identity={"memory_id": None, "path": resolve_path(path)},
                      route="file", frame=self.current_frame(), kind="birth",
                      generation=self._next_gen())

    def _b_from_sky(self) -> ChartB:
        from core.now_chart import build_now_chart
        g = self._gui
        now = build_now_chart(g.state.aditya_mode, getattr(g, "chart_sidereal_ayanamsa_id", 100),
                              g.state.house_system_code)
        if now is None:
            raise RuntimeError(t("chart.pair.sky_failed", "Could not calculate the sky now."))
        return ChartB(chart=now.chart, label=now.name, birth=None,
                      snapshot={"recipe": copy.deepcopy(now.recipe)},
                      identity={"memory_id": None, "path": None},
                      route="sky", frame=self.current_frame(), kind="transit",
                      generation=self._next_gen())

    def _b_from_record(self, record) -> ChartB | None:
        """The previous A as B, rebuilt natal from its recipe (never A's object:
        under Human Design that is the design chart)."""
        if not record:
            return None
        ident = record["identity"]
        if record.get("recipe"):
            snapshot = {"recipe": copy.deepcopy(record["recipe"])}
            chart = self._build_chart(snapshot)
            route = "memory" if ident.get("memory_id") else ("file" if ident.get("path")
                                                             else "sky")
            return ChartB(chart=chart, label=record.get("label") or snapshot["recipe"].get(
                "name", ""), birth=None, snapshot=snapshot, identity=dict(ident),
                route=route, frame=self.current_frame(),
                kind=record.get("kind") or "birth", generation=self._next_gen())
        if ident.get("path") and Path(ident["path"]).exists():
            return self._b_from_file(ident["path"])
        return None

    def _rebuild(self, b: ChartB) -> ChartB:
        b.chart = self._build_chart(b.snapshot)
        b.frame = self.current_frame()
        b.generation = self._next_gen()
        return b

    def b_meta_short(self, b: ChartB | None = None) -> str:
        """Short meta for a well (§4.1): the age, or "sky" for a Now chart."""
        b = b or self._b
        if b is None:
            return ""
        if b.kind == "transit" or b.route == "sky":
            return t("chart.pair.meta_sky", "sky")
        return self.b_age_suffix(b).strip()

    def b_age_suffix(self, b: ChartB | None = None) -> str:
        from core.chart_age import age_suffix
        b = b or self._b
        if b is None or b.kind == "transit":
            return ""
        snap = b.snapshot
        if "recipe" in snap:
            return age_suffix(snap["recipe"])
        try:
            from libaditya import swe
            p = snap["params"]
            y, m, d, _h = swe.revjul(float(p["jd"]) + float(p.get("utcoffset") or 0.0) / 24.0)
            return age_suffix({"year": y, "month": m, "day": d})
        except Exception:
            return ""

    def b_meta_full(self, b: ChartB | None = None) -> str:
        b = b or self._b
        if b is None:
            return ""
        compose = getattr(self._gui, "_compose_title_meta", None)
        suffix = "" if b.kind == "transit" else self.b_age_suffix(b)
        try:
            meta = compose(suffix) if compose else suffix.strip()
        except Exception:
            meta = suffix.strip()
        if b.kind == "transit":
            meta = f"{meta} · {t('chart.pair.meta_sky', 'sky')}" if meta else t(
                "chart.pair.meta_sky", "sky")
        return meta

    # ------------------------------------------------------------ transitions
    def _require_two(self) -> tuple[bool, str] | None:
        refused = self._refuse_busy()
        if refused:
            return refused
        if self._mode != "two":
            return False, "one-chart mode"
        if self._fullscreen():
            return self._refuse(t("chart.pair.refuse_fullscreen", "Leave fullscreen first."))
        return None

    def set_two(self, on: bool) -> tuple[bool, str]:
        """T1 / T2 / T3. Refused while fullscreen (T21) or while an
        activation runs (code review Astra F3 / Sol F2)."""
        on = bool(on)
        if on == (self._mode == "two"):
            return True, ""
        refused = self._refuse_busy()
        if refused:
            return refused
        if self._fullscreen():
            return self._refuse(t("chart.pair.refuse_fullscreen", "Leave fullscreen first."))
        return self._set_two_now(on)

    def _set_two_now(self, on: bool) -> tuple[bool, str]:
        if on == (self._mode == "two"):
            return True, ""
        if on:
            if self._gui.state.active_chart is None:
                return self._refuse(t("chart.pair.refuse_no_chart", "Load a chart first."))
            b = self._remembered
            if b is not None and same_chart(b.identity, self.a_identity()):
                b = self._remembered = None              # T1: never A beside itself
            if b is not None and b.frame != self.current_frame():
                try:
                    self._rebuild(b)                     # T17: remembered B, lazily
                except Exception:
                    b = self._remembered = None
            self._b = b
            self._mode = "two"
            self._render_sig = None
            self._apply_geometry(True)
            self._sync_view()
            self.invalidate()
        else:
            self._remembered = self._b
            self._b = None
            self._mode = "one"
            self._apply_geometry(False)
        self._emit("mode")
        return True, ""

    def _apply_geometry(self, on: bool) -> None:
        """Row geometry (ChartLayoutManager, the one transition entry point)
        and the shelf chip."""
        lay = getattr(self._gui, "chart_layout", None)
        if lay is not None and hasattr(lay, "set_two_chart"):
            # the frames / header band change after the layout's fit snapshot and
            # before its geometry change (code review Sol F4)
            lay.set_two_chart(on, before=lambda: self._show_frames(on))
        else:
            self._show_frames(on)
        self._sync_shelf_chip()

    def _sync_shelf_chip(self) -> None:
        """SPEC-DUAL-001 §4.4: "of <active chart>" on the shelf, mode two only."""
        panel = getattr(self._gui, "vimshottari_panel", None)
        setter = getattr(panel, "set_title_chip", None)
        if setter is None:
            return
        name = self.a_name() if self._mode == "two" else ""
        setter(t("chart.pair.shelf_chip", "of {a}", a=name) if name else None)

    def _bar_pair(self):
        bar = getattr(self._gui, "chart_title_widget", None)
        return getattr(bar, "pair", None)

    def a_meta_short(self) -> str:
        """Well A's short meta (§4.1): the age suffix, or "sky" for a Now chart."""
        rec = self._a_record or {}
        if rec.get("kind") == "transit":
            return t("chart.pair.meta_sky", "sky")
        from core.chart_age import age_suffix
        sp = self._gui.state.source_params or {}
        birth = sp.get("birth_data") or getattr(self._gui, "current_chart_data", None) or {}
        try:
            return age_suffix(birth).strip()
        except Exception:
            return ""

    def _sync_bar(self, *_):
        """Push the pair to the bar's pill (SPEC-DUAL-001 §4.1). The bar owns
        its widgets; this only hands it the texts (Rule 4b: no GUI writes)."""
        self._sync_frames()
        pair = self._bar_pair()
        if pair is None:
            return
        if self._mode != "two":
            pair.set_mode("one")
            render = getattr(getattr(self._gui, "chart_title_widget", None), "render_state", None)
            if callable(render):
                render("pair")               # A's ✕ tooltip back to the bar's own
            return
        a_name = self.a_name()
        b = self._b
        if b is None:
            tip = t("chart.pair.close_b_tip", "Back to one chart")
            pair.set_mode("two", a={"short": self.a_meta_short(), "close_tip": tip}, b=None)
            return
        tip = t("chart.pair.close_a_tip", "Close {a}; {b} stays as the one chart",
                a=a_name, b=b.label)
        pair.set_mode("two", a={"short": self.a_meta_short(), "close_tip": tip},
                      b={"name": b.label, "full": self.b_meta_full(b),
                         "short": self.b_meta_short(b)})

    def toggle(self) -> None:
        """Alt+2, COMPARE / ONE CHART."""
        self.set_two(self._mode != "two")

    def set_b_from_memory(self, entry_id: str) -> tuple[bool, str]:
        """T4 / T5 for a memory id."""
        refused = self._require_two()
        if refused:
            return refused
        entry = self._entry(entry_id)
        if entry is None:
            return self._refuse(t("chart.pair.not_in_memory",
                                  "Could not find that chart in memory."))
        ident = {"memory_id": entry_id, "path": resolve_path(entry.get("chtk_path"))}
        name = ((entry.get("recipe") or {}).get("name") or "").title()
        if same_chart(ident, self.a_identity()):
            return self._refuse(t("chart.pair.refuse_same_a", "{name} is already chart A.",
                                  name=name))
        try:
            b = self._b_from_memory(entry_id)
        except Exception as e:
            return self._refuse(t("chart.pair.build_failed", "Could not build {name}: {error}",
                                  name=name, error=str(e)))
        return self._set_b(b)

    def set_b_from_file(self, path: str) -> tuple[bool, str]:
        """T4 / T5 for a chart file."""
        refused = self._require_two()
        if refused:
            return refused
        ident = {"memory_id": None, "path": resolve_path(path)}
        name = Path(str(path)).stem
        if same_chart(ident, self.a_identity()):
            return self._refuse(t("chart.pair.refuse_same_a", "{name} is already chart A.",
                                  name=name.title()))
        try:
            b = self._b_from_file(path)
        except Exception as e:
            return self._refuse(t("chart.pair.build_failed", "Could not build {name}: {error}",
                                  name=name, error=str(e)))
        return self._set_b(b)

    def set_b_sky_now(self) -> tuple[bool, str]:
        """T6: the sky at this moment (frozen), named like the NOW button."""
        refused = self._require_two()
        if refused:
            return refused
        try:
            b = self._b_from_sky()
        except Exception as e:
            return self._refuse(str(e))
        return self._set_b(b)

    def pick_b_file(self) -> tuple[bool, str]:
        """T7: OPEN .CHTK FILE... (File > Open's filter and start folder)."""
        refused = self._require_two()
        if refused:
            return refused
        path = self._gui.chart_manager.pick_chart_file()
        if not path:
            return False, "cancelled"
        return self.set_b_from_file(str(path))

    def handle_b_drop(self, mime) -> tuple[bool, str]:
        """A drop on the B frame (accept-and-refuse, INV-8)."""
        from apps.widgets.chart_drop_common import chart_file_urls, chart_payload_kind
        kind = chart_payload_kind(mime)
        if kind == "memory":
            from apps.widgets.chart_memory_button import CHART_ENTRY_MIME
            entry_id = bytes(mime.data(CHART_ENTRY_MIME)).decode("utf-8")
            return self.set_b_from_memory(entry_id)
        if kind == "files":
            files = chart_file_urls(mime)
            ok, reason = self.set_b_from_file(str(files[0]))
            if ok and len(files) > 1:
                self._status(t("chart.pair.first_file", {
                    "one": "Chart B uses one chart: {name}. {count} file dropped, first one used.",
                    "other": "Chart B uses one chart: {name}. {count} files dropped, first one used."},
                    count=len(files), name=files[0].name))
            return ok, reason
        if kind == "folder":
            return self._refuse(t("chart.pair.refuse_folder",
                                  "A folder cannot be chart B. Drop a single chart."))
        return False, "no chart"

    def _set_b(self, b: ChartB) -> tuple[bool, str]:
        self._b = self._remembered = b
        self._render_sig = None
        self._b_changed()
        self._emit("b")
        return True, ""

    def _b_changed(self) -> None:
        """Frame content for the new / cleared B; rendering is coalesced."""
        self.invalidate()

    def forget_b(self) -> tuple[bool, str]:
        """T9: ✕ on well B or on the B header chip."""
        refused = self._refuse_busy()
        if refused:
            return refused
        if self._fullscreen():
            return self._refuse(t("chart.pair.refuse_fullscreen", "Leave fullscreen first."))
        if self._mode != "two":
            self._remembered = None
            return True, ""
        self._b = None
        ok, reason = self.set_two(False)
        self._remembered = None
        self._emit("b")
        return ok, reason

    def swap(self) -> tuple[bool, str]:
        """T8: B becomes the active chart through a checked activation; the
        old A becomes B (natal, from its recipe). The outgoing A is built
        BEFORE anything is mutated, so a failure there leaves the pair and A
        as they were (code review Astra F4); the transaction guard is held
        until the pair is committed (Astra F3 / Sol F2)."""
        if self._mode != "two" or self._b is None:
            return False, "no chart B"
        refused = self._preflight()
        if refused:
            return refused
        anchor = self._anchor()
        if anchor is None:
            return self._refuse(self._failed_text())
        try:
            new_b = self._b_from_record(anchor)
        except Exception:
            new_b = None
        if new_b is None:
            return self._refuse(self._failed_text())
        self._busy = True
        try:
            ok, reason = self._activate_b(anchor)
            if not ok:
                return ok, reason
            self._b = self._remembered = new_b
            self._render_sig = None
            self._refresh_a_record()
            self._b_changed()
        finally:
            self._busy = False
        self._emit("swap")
        return True, ""

    def _swap_shortcut(self) -> None:
        self.swap()

    def close_a(self) -> tuple[bool, str]:
        """T10 / T11: ✕ on well A in mode two. A leaves the pair (it stays in
        the memory row, Lorris Q1); B becomes the active chart."""
        if self._mode != "two":
            return False, "one-chart mode"
        if self._b is None:
            return self.set_two(False)                   # T11
        refused = self._preflight()
        if refused:
            return refused
        anchor = self._anchor()
        if anchor is None:
            return self._refuse(self._failed_text())
        self._busy = True
        try:
            ok, reason = self._activate_b(anchor)
            if not ok:
                return ok, reason
            self._b = None
            self._remembered = None
            self._refresh_a_record()
            self._set_two_now(False)
            self._remembered = None
        finally:
            self._busy = False
        self._emit("b")
        return True, ""

    # ---------------------------------------------------- checked activation
    def _refuse_busy(self) -> tuple[bool, str] | None:
        """Every pair mutation is refused while an activation or its rollback
        runs: the loading overlay pumps events, so a queued Alt+2, drop, ✕ or
        remote request could otherwise change the pair mid-transaction (code
        review Astra F3 / Sol F2)."""
        if self._busy:
            return self._refuse(t("chart.pair.refuse_busy", "A chart is opening; try again."))
        return None

    def _failed_text(self) -> str:
        return t("chart.pair.activate_failed", "Could not open {b}; the pair is unchanged.",
                 b=self._b.label if self._b else "")

    def _preflight(self) -> tuple[bool, str] | None:
        """Read-only checks before an activation (nothing mutated)."""
        refused = self._refuse_busy()
        if refused:
            return refused
        if self._fullscreen():
            return self._refuse(t("chart.pair.refuse_fullscreen", "Leave fullscreen first."))
        cm = getattr(self._gui, "chart_manager", None)
        if cm is not None and getattr(cm, "_loading_chart", False):
            return False, "a chart is loading"
        return None

    def _anchor(self) -> dict | None:
        """Chart A as it is now (read only): what a failed activation restores
        and what a swap turns into chart B."""
        g = self._gui
        mp = self._memory()
        entry = mp.get_current_chart() if mp is not None else None
        if entry is None or g.state.active_chart is None:
            return None
        return {"chart": g.state.active_chart, "id": entry.get("id"),
                "hd": bool(g.state.human_design_mode),
                "recipe": copy.deepcopy(entry.get("recipe")),
                "kind": entry.get("kind") or "birth",
                "identity": {"memory_id": entry.get("id"),
                             "path": resolve_path(entry.get("chtk_path"))},
                "label": self.a_name()}

    def _activate_b(self, anchor):
        """SPEC-DUAL-001 §3.4. The caller holds ``_busy`` and has run the
        preflight. Success means the canonical path COMPLETED: the active
        chart, the memory row's current entry and the source params all name
        the target (a file load also reports its own completion, code review
        Astra F1). Any failure after the first mutation re-activates A by its
        id, unconditionally (Astra F2 / Sol F1). Returns (ok, reason)."""
        g = self._gui
        b = self._b
        mp = self._memory()
        cm = getattr(g, "chart_manager", None)
        if b.identity.get("memory_id") and self._index_of(b.identity["memory_id"]) is not None:
            route = "memory"
        elif "params" in b.snapshot and b.identity.get("path") and Path(
                b.identity["path"]).exists():
            route = "file"
        elif "recipe" in b.snapshot:
            route = "add"
        else:
            return self._refuse(self._failed_text())
        from state.events import SetHumanDesignMode
        added_id = target_id = target_path = None
        try:
            if route == "add":
                before = {e.get("id") for e in mp.charts}
                index = mp.add_chart(copy.deepcopy(b.snapshot["recipe"]), kind=b.kind)
                target_id = mp.charts[index]["id"]
                added_id = target_id if target_id not in before else None
                if b.kind == "transit":
                    g.state.dispatch(SetHumanDesignMode(enabled=False))   # NOW's rule
                mp.select_chart(index)
                completed = True
            elif route == "memory":
                target_id = b.identity["memory_id"]
                mp.select_chart(self._index_of(target_id))
                completed = True
            else:
                target_path = resolve_path(b.identity["path"])
                completed = cm.load_chart(target_path) is True
            sp = g.state.source_params or {}
            cur = mp.get_current_chart() or {}
            if target_id is not None:
                # under Human Design the recompute re-dispatches without the
                # origin id; the memory row's current entry still names it
                landed = (cur.get("id") == target_id
                          and sp.get("origin_memory_id") in (target_id, None))
            else:
                landed = (resolve_path(sp.get("chtk_path")) == target_path
                          and resolve_path(cur.get("chtk_path")) == target_path)
            ok = (completed and landed and g.state.active_chart is not None
                  and g.state.active_chart is not anchor["chart"])
        except Exception:
            import traceback
            traceback.print_exc()
            ok = False
        if ok:
            if added_id is not None:
                self._status(t("chart.pair.added_to_memory", "{name} was added to the memory row.",
                               name=b.label))
            return True, ""
        if self._rollback(anchor, added_id):
            return self._refuse(self._failed_text())
        return self._refuse(t("chart.pair.rollback_failed",
                              "Could not open {b}, and {a} could not be restored.",
                              b=b.label, a=anchor.get("label") or ""))

    def _rollback(self, anchor, added_id) -> bool:
        """Restore A through its own canonical path: ALWAYS re-activated by
        its id once the transaction began (a failed load may have written B's
        birth fields under A's still-displayed chart), the added entry removed,
        then verified. True when A is back."""
        g = self._gui
        mp = self._memory()
        from state.events import SetHumanDesignMode
        reselected = False
        try:
            if added_id is not None:
                i = self._index_of(added_id)
                if i is not None:
                    mp.remove_chart(i)
            g.state.dispatch(SetHumanDesignMode(enabled=anchor["hd"]))
            index = self._index_of(anchor["id"])
            if index is None and anchor.get("recipe"):
                index = mp.add_chart(copy.deepcopy(anchor["recipe"]), kind=anchor["kind"])
                anchor["id"] = mp.charts[index]["id"]
            if index is not None:
                mp.select_chart(index)
                reselected = True
        except Exception:
            import traceback
            traceback.print_exc()
        sp = g.state.source_params or {}
        cur = mp.get_current_chart() or {}
        return (reselected and g.state.active_chart is not None
                and cur.get("id") == anchor["id"]
                and sp.get("origin_memory_id") in (anchor["id"], None))

    # ------------------------------------------------------- state listener
    def _on_state(self, reason) -> None:
        """The ONE ChartState listener (D-5 / INV-6): reason ``active_chart``
        only. Rebuilds B on a frame diff, applies T15 / T16, invalidates."""
        if reason != "active_chart":
            return
        g = self._gui
        if g.state.active_chart is None:
            if self._mode == "two":                      # T16
                if self._fullscreen():
                    try:
                        g.view_float_manager.exit_fullscreen()
                    except Exception:
                        pass
                self._remembered = self._b
                self._b = None
                self._mode = "one"
                self._apply_geometry(False)
                self._emit("mode")
            return
        if not self._busy and self._mode == "two" and self._b is not None:
            ident = self.a_identity()
            if same_chart(ident, self._b.identity):      # T15: B became A
                prev = self._a_record
                new_b = None
                if prev is not None and not same_chart(prev["identity"], ident):
                    try:
                        new_b = self._b_from_record(prev)
                    except Exception:
                        new_b = None
                self._b = self._remembered = new_b
                self._render_sig = None
                if new_b is None:
                    self._status(t("chart.pair.b_cleared",
                                   "Chart B is now the active chart; drop another chart on the right frame."))
                self._b_changed()
                self._emit("b")
        frame = self.current_frame()
        if self._b is not None and self._b.frame != frame:   # T17
            try:
                self._rebuild(self._b)
            except Exception:
                import traceback
                traceback.print_exc()
        if not self._busy:
            self._record_timer.start()
        self.invalidate()
        if self._mode == "two":
            self._sync_shelf_chip()
            self._emit("a")

    def _emit(self, reason: str) -> None:
        try:
            self.changed.emit(reason)
        except RuntimeError:
            pass

    # ------------------------------------------------------- render authority
    def invalidate(self) -> None:
        """Coalesced B render (INV-14): end of ``_apply_current_varga``, a
        rebuild, B set / replaced. The shot renders only on a new signature."""
        if self._mode != "two" or self._b is None:
            return
        self._render_timer.start()

    def render_signature(self):
        g = self._gui
        b = self._b
        if b is None:
            return None
        from core.capabilities.chart import varga_surfaces
        from core.hd_model import chart_display_for
        ayan_off = (getattr(g, "chart_ayanamsa_offset", 0.0)
                    if g.state.aditya_mode == "sidereal" else 0.0)
        varga_code = varga_surfaces(g.state.current_varga, False, ayan_off)["main"]
        mode, western = chart_display_for(g.state.aditya_mode,
                                          getattr(g, "use_western_names", False), None)
        return (id(b.chart), b.generation, b.frame, varga_code, bool(western), mode)

    def _render_now(self) -> None:
        b, frame = self._b, self._frame
        if self._mode != "two" or b is None or frame is None:
            return
        if not frame.isVisible():
            self._render_pending = True                  # rendered on show
            return
        sig = self.render_signature()
        if sig == self._render_sig:
            return
        _cid, _gen, _frame, varga_code, western, mode = sig
        frame.show_chart(b.chart, b.label, varga_code=varga_code,
                         use_western_names=western, aditya_mode=mode)
        self._render_sig = sig
        self._render_pending = False
        self._render_count += 1

    def on_frame_shown(self) -> None:
        if self._render_pending:
            self._render_pending = False
            self.invalidate()

    # ------------------------------------------------------------- view sync
    def _sync_view(self) -> None:
        """On entry B takes A's current view when B can show it; otherwise B
        keeps its last supported view (INV-12; code review Astra F5 / Sol F3:
        B gets no broadcast while mode one)."""
        frame = self._frame
        style = getattr(self._gui.state, "chart_view_style", None)
        if frame is not None and style in frame.supported_chart_views():
            frame.sync_chart_view(style)

    def view_sync_targets(self):
        """Yields the B frame for ``ChartGUI._view_sync_panels`` (INV-12)."""
        if self._frame is not None and self._mode == "two":
            yield self._frame

    def fullscreen_extra(self) -> dict:
        """The pair's fullscreen descriptor keys (§4.7), merged into the chart
        descriptor. Mode one: {}. Mode two, B empty: only the hooks (chart A
        alone, its header band hidden). Mode two, B filled: B's body as the
        companion beside A, both views refit, both stacks' page changes refit."""
        if self._mode != "two" or self._frame is None:
            return {}
        gui = self._gui
        lay = gui.chart_layout
        extra = {
            "on_enter": lambda: (lay.on_fullscreen(True), self._fullscreen_chrome(True)),
            "on_exit": lambda: (lay.on_fullscreen(False), self._fullscreen_chrome(False)),
        }
        if self._b is None:
            return extra
        frame = self._frame
        base_views = gui._chart_fullscreen_views

        def views():
            out = list(base_views() or [])
            v = frame.current_view()
            active = getattr(v, "active_view", None)
            out.append(active if active is not None else v)
            return out
        extra.update({
            "companion": {"widget": frame.body, "layout": frame.body_layout(),
                          "spacing": gui.chart_content.layout().spacing()},
            "views": views,
            "refit_signals": [gui.chart_stack.currentChanged, frame.body.stack.currentChanged],
        })
        return extra

    def _fullscreen_chrome(self, entering: bool) -> None:
        """Fullscreen entry: drawer closed, A chip + band and B header hidden;
        exit restores them (mode two kept exactly)."""
        lay = getattr(self._gui, "chart_layout", None)
        stack = self._gui.chart_stack
        if entering:
            if lay is not None:
                lay.close_info_drawer()
            if self._a_chip is not None:
                self._a_chip.hide()
            stack.setContentsMargins(0, 0, 0, 0)
            if self._frame is not None:
                self._frame.header_row.hide()
        elif self._mode == "two":
            if self._frame is not None:
                self._frame.header_row.show()
            stack.setContentsMargins(0, self.header_height(), 0, 0)
            if self._a_chip is not None:
                self._a_chip.show()
                self._a_chip.raise_()

    # ------------------------------------------------------------ theme/font
    def refresh_theme(self) -> None:
        if self._frame is not None:
            self._frame.refresh_theme()
        if self._a_chip is not None:
            self._a_chip.update()

    def refresh_fonts(self) -> None:
        if self._frame is not None and hasattr(self._frame, "refresh_fonts"):
            self._frame.refresh_fonts()
        if self._a_chip is not None:
            self._a_chip.refresh_fonts()
        if self._mode == "two" and self._frame is not None and not self._fullscreen():
            # in fullscreen the band stays 0; the exit hook sets the new height
            # (code review Sol F6)
            self._gui.chart_stack.setContentsMargins(0, self.header_height(), 0, 0)
        self._emit("fonts")

