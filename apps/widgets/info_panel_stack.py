# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""InfoPanelStack: the container of the three Chart-tab info panels.

SPEC-LAYOUT-001 stream B (td-i214k, plan 2026-10-15 responsive dasha and
panels §6 + D3/D5/D6/D7a/D9). The three existing panel frames (Karakas,
Strength, the bottom Aspects/Avastha/Shame/Exch panel) keep their names,
stacks and sub-tab indices; this widget only places them:

- stacked: one vertical ``GlassSplitter`` holding the three frames;
- magazine (the column is wide enough for two columns' minimum widths):
  Karakas + Strength in the splitter on the left, the bottom panel full height
  on the right.

A panel folds to its header bar with a one-line summary (computed from the
chart, D6); a splitter knob click exchanges a pair's height (B.3, D9); a drag
snaps to fold / fit / half; AUTO derives the open count from the height (B.4).
User actions persist the ``ui.layout.info_*`` app-state keys; remote / AI
changes do not (D5, INV-17). Folded panels' controllers are held (B.6).

The Chart-tab layout collaborator (ChartLayoutManager) is the only caller of
``set_available_size``: the scroll viewport, not this widget's own height, is
the authoritative space (plan D3). Nothing here runs an engine on a resize.
"""
from __future__ import annotations

from typing import Dict

from PySide6.QtCore import QEvent, QSize, Qt, QTimer
from PySide6.QtWidgets import (QAbstractButton, QHBoxLayout, QStackedWidget, QTabWidget,
                               QTableView, QTextEdit, QVBoxLayout, QWidget)

from apps.widgets import info_panel_layout as L
from apps.widgets.info_panel_splitter import (FoldButton, GlassSplitter, SummaryChip,
                                              handle_thickness, small_px)
from apps.widgets.info_panel_summaries import PENDING, SummaryModel, title
from apps.widgets.panel_header import set_header_folded
from ui.qt_theme import scaled_px

PANEL_NAMES = L.PANEL_NAMES
QWIDGETSIZE_MAX = 16777215
MAGAZINE_HYSTERESIS = 24          # px, as the manager's band (plan A.3)
HOLD_RELEASE_MARGIN = 24          # px: the focus hold lets go only this far above its need (SPEC-TJK-003 §4.6)
# Hold owners whose shown drawing also folds Strength when the three panels do not fit
# (SPEC-VAC-001 D-13, Lorris 2026-10-28: all seven Aspects V rows show at Full HD; D-14,
# the same day: the Tajika drawing too, so the Aspects T matrix shows down to its PL row).
FOLD_STRENGTH_OWNERS = frozenset({"vedic", "tajika"})
NATURAL_CAP = 420                 # px at scale 1: text bodies (Shame, enriched) scroll past it

KEYS = {
    "auto": "ui.layout.info_panels_auto",
    "folded": "ui.layout.info_panels_folded",
    "stack": "ui.layout.info_stack_fractions",
    "magazine": "ui.layout.info_magazine_fractions",
}

# The controllers whose output a panel shows (B.6: held while it is folded).
CONTROLLERS = {
    "karakas": ("karakas_controller", "hora_controller", "trimsamsa_controller",
                "house_graph_controller", "planetary_condition_controller"),
    "strength": ("strength_controller", "elements_controller", "modality_controller",
                 "dignities_controller"),
    "bottom": ("aspects_controller", "avastha_controller", "shame_controller",
               "interchange_controller", "nabhasa_controller", "tajika_matrix_controller",
               "tajika_relationships_controller", "tajika_yogas_controller"),
}

# Capture region whose folded panel answers with its summary (plan D7a): the
# region of the data the summary is computed from.
SUMMARY_REGIONS = {"karakas": "karakas", "strength": "strength", "avastha": "bottom"}


BODY_MIN_CHARS = 46     # average characters a panel body needs to read well


def body_need_width(avastha: bool = False) -> int:
    """Font-derived width a panel body needs (plan B.5): the Tables font's
    average character times ``BODY_MIN_CHARS``; the Avastha matrix also needs
    its 5-char dignity diagonals ("MK105") in each of its 7 columns beside the
    40 px row labels (SPEC-AVA-001 rev3). Drives the magazine threshold."""
    from PySide6.QtGui import QFont, QFontMetrics
    from PySide6.QtWidgets import QApplication
    from ui.qt_theme import scaled_area_px
    font = QFont(QApplication.font())
    font.setPixelSize(max(1, scaled_area_px("tables")))
    fm = QFontMetrics(font)
    width = max(scaled_px(200), fm.averageCharWidth() * BODY_MIN_CHARS)
    if avastha:
        width = max(width, 40 + 7 * (fm.horizontalAdvance("MK105") + 2))
    return width


def _factory(key: str):
    from core.settings_registry.factory import APP_STATE_DEFAULTS
    node = APP_STATE_DEFAULTS
    for part in key.split("."):
        node = node[part]
    return node


class _Panel:
    __slots__ = ("name", "frame", "header", "body", "fold", "chip", "strip")

    def __init__(self, name, frame, header, body, fold, chip, strip):
        self.name, self.frame, self.header, self.body = name, frame, header, body
        self.fold, self.chip, self.strip = fold, chip, strip


def _tighten(header) -> None:
    """SPEC-PANELS-001 §2.6 geometry: chevron 4 px from the left edge, 2 px to
    the first tab, tabs touching (their own 8 px padding spaces them), the tabs
    full height so the active rule sits on the header's bottom hairline."""
    hl = header.layout()
    hl.setSpacing(small_px(2))
    hl.setContentsMargins(small_px(4), 0, small_px(6), 0)
    strip = header.findChild(TabStrip)
    if strip is not None:
        strip.tab_layout().setSpacing(0)


class _Row(QWidget):
    """Plain row (a QWidget SUBCLASS, so the header's ``QWidget {background}``
    rule is not painted a second time inside the strip)."""


class TabStrip(QWidget):
    """The sub-tab buttons of a panel header, laid out at their natural size
    in an inner row; when the header is narrower, the row is clipped at the
    RIGHT (the mockup's tab strip), never squeezed. Its minimum is the first
    tab, so a narrow column keeps the fold and swap buttons reachable."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._row = _Row(self)
        lay = QHBoxLayout(self._row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(small_px(2))
        self._row.installEventFilter(self)

    def tab_layout(self):
        return self._row.layout()

    def sizeHint(self):
        return self._row.sizeHint()

    def minimumSizeHint(self):
        lay = self._row.layout()
        # A folded header collapses all but the active tab (width 0, not
        # hidden): the minimum is the first tab that is really shown.
        first = next((lay.itemAt(i).widget() for i in range(lay.count())
                      if lay.itemAt(i).widget() is not None
                      and not lay.itemAt(i).widget().isHidden()
                      and lay.itemAt(i).widget().maximumWidth() > 0), None)
        return QSize(first.sizeHint().width() if first is not None else 0,
                     self._row.minimumSizeHint().height())

    def _place(self):
        hint = self._row.sizeHint()
        self._row.setGeometry(0, 0, max(self.width(), hint.width()), self.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place()

    def eventFilter(self, obj, event):
        if obj is self._row and event.type() == QEvent.Type.LayoutRequest:
            self.updateGeometry()          # a tab shown / hidden (Vedic / Tajika row)
            self._place()
        return False


class InfoPanelStack(QWidget):
    """Root widget returned by ``create_right_panels`` (frozen API, plan D1)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._available = QSize()
        self._gui = None
        self._panels: Dict[str, _Panel] = {}
        self._magazine = False
        self._auto = True
        self._folded = ()                         # manual folds (when not auto)
        self._fractions = {"stack": None, "magazine": None}
        self._effective = frozenset()             # folded on screen now
        self._tab_page = None
        self._tab_hidden = False
        self._drawer_held = False                 # SPEC-DUAL-001: in the closed info drawer
        # SPEC-TJK-003 §4.6, SPEC-VAC-001 §4.0: the focus hold, per owner (the drawing
        # kind): [holding, released by the user], and whether it folds panels now
        self._holds = {}
        self._hold_active = False                 # the hold folds panels now
        self._hold_both = False                   # ... Karakas and Strength (§4.6 threshold)
        self._width_released = False
        self._drag = None
        self._summaries = SummaryModel()
        self.relayout_count = 0                   # harness: resizes never relayout per pixel

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._relayout)
        self._chip_timer = QTimer(self)
        self._chip_timer.setSingleShot(True)
        self._chip_timer.setInterval(0)
        self._chip_timer.timeout.connect(self._refresh_chips)
        # A table settles its header and margins after its first layout, so a
        # natural height can change once after a relayout: one re-check per
        # trigger (bounded, never a loop).
        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.setInterval(0)
        self._settle_timer.timeout.connect(self._settle)
        self._settles_left = 0

        lay = QHBoxLayout(self)
        lay.setContentsMargins(5, 5, 5, 5)
        lay.setSpacing(scaled_px(6))
        self._split = GlassSplitter(self, self)
        lay.addWidget(self._split, 1)
        self._right = QWidget(self)
        right = QVBoxLayout(self._right)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        lay.addWidget(self._right, 1)
        self._right.hide()

    # ------------------------------------------------------------- building
    def attach_panels(self, gui, panels: Dict[str, tuple]) -> None:
        """Take the three frames built by ``create_right_panels``:
        ``{name: (frame, header, body_stack)}``. Adds the fold button and the
        summary chip to each header, restores the remembered state."""
        self._gui = gui
        for name in PANEL_NAMES:
            frame, header, body = panels[name]
            hl = header.layout()
            strip = self._wrap_tabs(header)
            fold = FoldButton(header)
            hl.insertWidget(0, fold)
            chip = SummaryChip(header)
            hl.insertWidget(hl.count() - 1, chip, 1)      # before the trailing stretch
            chip.hide()
            fold.clicked.connect(lambda _checked=False, n=name: self.toggle_fold(n))
            header.installEventFilter(self)
            # Bodies scroll inside themselves (plan P0.4 / D3): the frame's
            # minimum is its header bar, whatever the page minimums are.
            body.setMinimumHeight(1)
            for st in [body] + body.findChildren(QStackedWidget):
                st.currentChanged.connect(self._on_page_changed)
            for btn in header.findChildren(QAbstractButton):
                btn.clicked.connect(self._schedule_chips)  # avastha view / tab change
            self._split.addWidget(frame)
            self._panels[name] = _Panel(name, frame, header, body, fold, chip, strip)
        self._load_settings()
        state = getattr(gui, "state", None)
        if state is not None and hasattr(state, "connect"):
            state.connect(self._on_state_changed)
        # The DUC Bala method changes the Strength and Avastha summaries
        # (SPEC-STR-001 §7.5): Settings Apply, remote set_setting, AI request.
        from apps.widgets.panel_controllers.duc_method import on_duc_method_changed
        on_duc_method_changed(self, lambda: self._on_state_changed("active_chart"))
        self._schedule()

    @staticmethod
    def _wrap_tabs(header) -> "TabStrip":
        """Move the header's leading sub-tab buttons and their "|" separators
        (unchanged objects) into one ``TabStrip`` that may be clipped when the
        column is narrower than the tabs (the mockup's tab strip), so the fold
        button, the swap button and the summary chip always stay reachable.
        Header spacing is tightened so the fold button costs no tab at the
        default column width."""
        hl = header.layout()
        strip = TabStrip(header)
        while hl.count():
            w = hl.itemAt(0).widget()
            if w is None or (isinstance(w, QAbstractButton) and not w.text()):
                break                                   # the first icon button
            hl.removeWidget(w)
            strip.tab_layout().addWidget(w)
        hl.insertWidget(0, strip)
        _tighten(header)
        return strip

    # --- geometry input (from ChartLayoutManager) ---
    def set_available_size(self, size: QSize) -> None:
        """Usable viewport size of the info column (plan D3)."""
        if not self._width_released:
            # create_right_panels fixes the width so right_scroll can read it
            # once at construction; from now on the stack follows the viewport.
            self._width_released = True
            self.setMinimumWidth(0)
            self.setMaximumWidth(QWIDGETSIZE_MAX)
        self._watch_tab()
        if QSize(size) != self._available:
            self._available = QSize(size)
            self._schedule()

    def available_size(self) -> QSize:
        return QSize(self._available)

    # --- user operations (shortcuts, remote) ---
    def exchange_active(self) -> None:
        """Alt+X: reciprocal height exchange on the active splitter (plan D9):
        stacked -> Strength <-> bottom panel, magazine -> Karakas <-> Strength."""
        self._relayout_if_pending()
        self.exchange_at(1 if self._magazine else 2, user=True)

    def toggle_fold(self, name: str) -> None:
        """Fold or unfold one panel ("karakas" | "strength" | "bottom"); a user
        action (fold button, Alt+1), so it is remembered. In the magazine
        layout the bottom panel is always open (D9)."""
        self._relayout_if_pending()
        was_folded = name in self._effective
        if self._release_hold() and was_folded and name not in self._effective:
            return                                  # the hold had folded it: open again
        names = self._names()
        if name not in names or not self._panels:
            return
        hs = self._split.sizes()
        fold = [self._fold_h(n) for n in names]
        flags = L.folded_flags(hs, fold)
        i = names.index(name)
        weights = [0.0 if f else float(h) for h, f in zip(hs, flags)]
        if flags[i]:
            weights[i] = float(max(1, self._natural_h(name)))
        else:
            if sum(1 for f in flags if not f) <= 1:
                return                              # the last open panel stays open
            weights[i] = 0.0
        self._set_manual(names, weights, persist=True)

    def exchange_at(self, index: int, *, user: bool) -> None:
        """Knob click on handle ``index`` (between splitter widgets index-1 and
        index): the taller of the pair folds, the other takes the pair's height."""
        names = self._names()
        if not self._panels or not 1 <= index < len(names):
            return
        if user:
            self._release_hold()
        hs = self._split.sizes()
        fold = [self._fold_h(n) for n in names]
        a, b = index - 1, index
        flags = L.folded_flags(hs, fold)
        if flags[a] and flags[b]:
            # Both folded: nothing to exchange inside the pair; open the lower one.
            weights = [0.0 if f else float(h) for h, f in zip(hs, flags)]
            weights[b] = float(max(1, self._natural_h(names[b])))
            self._set_manual(names, weights, persist=user)
            return
        hs[a], hs[b] = L.exchange(hs[a], hs[b], fold[a], fold[b])
        self._commit(names, hs, persist=user)

    def set_auto_by_user(self) -> None:
        """AUTO chip: automatic heights again; manual folds and splits cleared."""
        self._release_hold()
        self._auto = True
        self._folded = ()
        self._fractions = {"stack": None, "magazine": None}
        self._persist()
        self._relayout()

    # --- the focus hold (SPEC-TJK-003 §4.6, SPEC-VAC-001 §4.0) ---
    def set_focus_hold(self, on: bool, period: bool = True, owner: str = "tajika") -> None:
        """While a center drawing is shown: fold Karakas and Strength when the stacked
        column cannot show all three panels at their natural heights. Flags per
        ``owner`` (the drawing kind), read by ``_relayout``; never persisted, never
        written into the manual folds. ``period`` False ends that owner's ON period (its
        toggle went OFF): only then is its user release forgotten; a suppression (Guide,
        D9, classic, the other panel mode) keeps it."""
        on = bool(on)
        hold = self._holds.setdefault(owner, [False, False])
        if not period:
            hold[1] = False
        if on == hold[0]:
            return
        hold[0] = on
        self._hold_active = self._hold_both = False
        self._schedule()

    @property
    def _focus_hold(self) -> bool:
        """Some owner holds (shown drawing)."""
        return any(hold[0] for hold in self._holds.values())

    @property
    def _hold_released(self) -> bool:
        """Some owner's hold was released by the user in its ON period."""
        return any(hold[1] for hold in self._holds.values())

    def _hold_applies(self) -> bool:
        """Panels fold while some owner is holding and not released."""
        return any(holding and not released for holding, released in self._holds.values())

    def focus_hold_active(self) -> bool:
        return self._hold_active

    def _release_hold(self) -> bool:
        """A user fold / unfold / exchange / AUTO / drag: the user's choice wins for the
        rest of this ON period. Returns True when the hold was folding panels."""
        if not self._focus_hold:
            return False
        for hold in self._holds.values():          # every holding owner is released
            hold[1] = hold[1] or hold[0]
        if not self._hold_active:
            return False
        self._hold_active = self._hold_both = False
        self._relayout()
        return True

    def _hold_weights(self, names, weights, avail, natural, handles, fold):
        """Fold Karakas and Strength while the hold applies: when the bottom panel at its
        natural height leaves the other two less than half their natural heights
        (natural heights only, separate enter and release thresholds). Else, for an
        owner of ``FOLD_STRENGTH_OWNERS``, Strength alone folds when the three panels do
        not fit (``L.fold_strength``)."""
        if not self._hold_applies() or self._magazine:
            self._hold_active = self._hold_both = False
            return weights, False
        need = natural["bottom"] + handles + sum(natural[n] for n in names if n != "bottom") / 2
        self._hold_both = (avail < need + HOLD_RELEASE_MARGIN) if self._hold_both else (avail < need)
        self._hold_active = self._hold_both
        if self._hold_active:
            return [float(max(1, natural[n])) if n == "bottom" else 0.0 for n in names], False
        strength_owner = self._strength_owner_holds()
        bottom = natural["bottom"] + (_layout_rows_h(self._panels["bottom"].body)
                                      if strength_owner else 0)
        held = strength_owner and L.fold_strength(names, weights, avail, natural, fold,
                                                  handles, bottom, self._auto)
        if held:
            self._hold_active = True
            return held, True
        # nothing folds: the bottom panel (the keys and the rail) keeps its natural
        # height, the open panels above share the rest by their natural heights
        rest = avail - handles - bottom
        above = [n for n, w in zip(names, weights) if n != "bottom" and w > 0]
        if rest <= 0 or not above:
            return weights, False
        share = sum(natural[n] for n in above) or 1
        return [float(bottom) if n == "bottom" else
                (rest * natural[n] / share if n in above else 0.0) for n in names], True

    def _strength_owner_holds(self) -> bool:
        """An owner of ``FOLD_STRENGTH_OWNERS`` holds, unreleased (SPEC-VAC-001 D-13):
        Strength may fold alone, and the bottom panel's need adds the rail row that
        ``_content_height`` leaves out (a nested layout, not a widget), so all seven
        Aspects V rows show. The other owners' hold is unchanged."""
        return any(holding and not released for owner, (holding, released)
                   in self._holds.items() if owner in FOLD_STRENGTH_OWNERS)

    def is_auto(self) -> bool:
        return self._auto

    def is_folded(self, name: str) -> bool:
        return name in self._effective

    # --- read-only views (capture, remote) ---
    def summary(self, name: str) -> str:
        """One-line summary of a panel, shown when folded (plan D6)."""
        if name not in self._panels or self._gui is None:
            return ""
        return self._summaries.text(name, self._gui, retry=True)

    def observation(self, name: str) -> Dict:
        """Capture observation of a folded panel (plan D7a); {} when open."""
        if name not in self._effective:
            return {}
        text = self.summary(name)
        return {"folded": True, "summary": text,
                "revision": self._summaries.status(name, self._gui)[1]}

    def capture_override(self, region_id: str):
        """AI capture of a region whose panel is folded (plan D7a): returns
        ``(header_widget, {"header": [...], "rows": [...]}, (status, revision))``
        or None when the region's panel is open."""
        name = SUMMARY_REGIONS.get(region_id)
        if name is None or name not in self._effective:
            return None
        text = self.summary(name)
        return (self._panels[name].header,
                {"header": [title(name)], "rows": [[text]]},
                self._summaries.status(name, self._gui))

    def layout_state(self) -> Dict:
        names = self._names()
        return {"auto": self._auto,
                "folded": [p for p in PANEL_NAMES if p in self._effective],
                "magazine": self._magazine,
                "open": [p for p in PANEL_NAMES if p in self._panels and p not in self._effective],
                "stack_fractions": self._fractions["stack"],
                "magazine_fractions": self._fractions["magazine"],
                "split": list(names)}

    def apply_layout_state(self, state: Dict, *, persist: bool) -> None:
        """Apply a layout state; ``persist=False`` for remote/AI (INV-17).

        Keys (all optional): ``auto`` (bool; True clears folds and splits),
        ``folded`` (list or CSV of panel names), ``stack_fractions`` /
        ``magazine_fractions`` (list or CSV of positive numbers). An invalid
        value falls back to the default (plan D5); a fold or split implies
        manual mode."""
        if not isinstance(state, dict):
            return
        if state.get("auto") is True:
            self._auto = True
            self._folded = ()
            self._fractions = {"stack": None, "magazine": None}
        else:
            manual = (state.get("auto") is False or "folded" in state
                      or "stack_fractions" in state or "magazine_fractions" in state)
            if manual:
                if self._auto:
                    self._folded = tuple(p for p in PANEL_NAMES if p in self._effective)
                self._auto = False
                if "folded" in state:
                    self._folded = L.parse_folded(state["folded"]) or ()
                for topo in ("stack", "magazine"):
                    if f"{topo}_fractions" in state:
                        self._fractions[topo] = L.parse_fractions(state[f"{topo}_fractions"])
        if persist:
            self._persist()
        self._relayout()

    # --- lifecycle (called by ChartLayoutManager after the app's QSS/relayout) ---
    def refresh_theme(self) -> None:
        """Everything this widget adds paints from the live theme: repaint."""
        for p in self._panels.values():
            p.fold.update()
            p.chip.update()
        for i in range(1, self._split.count()):
            self._split.handle(i).update()

    def refresh_fonts(self) -> None:
        """Header heights and table rows changed (relayout_info_panels ran
        first): re-measure, then lay out again."""
        self._split.setHandleWidth(handle_thickness())
        self.layout().setSpacing(scaled_px(6))
        for p in self._panels.values():
            _tighten(p.header)
            p.fold.refresh_size()
            p.chip.updateGeometry()
        self._schedule()

    # ---------------------------------------------------- controller gating
    def holds_controller(self, ctrl) -> bool:
        """B.6: a controller of a folded panel, or of any panel while the Chart
        tab is hidden, defers its refresh until the panel is shown again."""
        gui = self._gui
        if gui is None:
            return False
        held = PANEL_NAMES if (self._tab_hidden or self._drawer_held) else self._effective
        for name in held:
            for attr in CONTROLLERS[name]:
                if getattr(gui, attr, None) is ctrl:
                    return True
        return False

    def set_drawer_hold(self, held: bool) -> None:
        """SPEC-DUAL-001 §4.3: while the column sits in the CLOSED two-chart
        info drawer every controller is held (as for a hidden tab, B.6); the
        drawer opening drains them once."""
        held = bool(held)
        if held == self._drawer_held:
            return
        self._drawer_held = held
        if not held and not self._tab_hidden:
            self._reconcile(PANEL_NAMES)
            self._schedule_chips()

    def drawer_held(self) -> bool:
        return self._drawer_held

    def _reconcile(self, names) -> None:
        for name in names:
            for attr in CONTROLLERS[name]:
                ctrl = getattr(self._gui, attr, None)
                fn = getattr(ctrl, "reconcile_visibility", None)
                if callable(fn):
                    fn()

    def _watch_tab(self) -> None:
        """Find the Chart tab page once (the ancestor that is a QTabWidget page)."""
        if self._tab_page is not None:
            return
        w = self.parentWidget()
        while w is not None:
            p = w.parentWidget()
            if isinstance(p, QStackedWidget) and isinstance(p.parentWidget(), QTabWidget):
                self._tab_page = w
                self._tab_hidden = w.isHidden()
                w.installEventFilter(self)
                return
            w = p

    # --------------------------------------------------------------- events
    def eventFilter(self, obj, event):
        et = event.type()
        if obj is self._tab_page and et in (QEvent.Type.Show, QEvent.Type.Hide):
            hidden = obj.isHidden()
            if hidden != self._tab_hidden:
                self._tab_hidden = hidden
                if not hidden:
                    self._reconcile(PANEL_NAMES)
                    self._schedule_chips()
            return False
        if et == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            for p in self._panels.values():
                if obj is p.header and p.name in self._effective \
                        and p.header.rect().contains(event.position().toPoint()):
                    self.toggle_fold(p.name)       # click a folded bar: unfold
                    break
        return False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._schedule()

    def showEvent(self, event):
        super().showEvent(event)
        self._watch_tab()
        self._schedule()

    def _on_page_changed(self, _index) -> None:
        if self._auto:                              # natural heights changed
            self._schedule()

    def _on_state_changed(self, reason: str) -> None:
        if reason in ("active_chart", "aditya_mode"):
            self._summaries.invalidate()
            for name in self._effective:
                self._panels[name].chip.set_text(PENDING)
            self._schedule_chips()

    # --------------------------------------------------------------- layout
    def _schedule(self) -> None:
        if self._panels:
            self._settles_left = 2
            self._timer.start()

    def _settle(self) -> None:
        last = getattr(self, "last_layout", None)
        if last is None or self._drag is not None or self._settles_left <= 0:
            return
        if any(self._natural_h(n) != h for n, h in last["natural"].items()) \
                or any(self._fold_h(n) != h for n, h in last["fold"].items()):
            self._settles_left -= 1
            self._relayout()

    def _relayout_if_pending(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
            self._relayout()

    def _names(self):
        return L.names_for(self._magazine)

    def _topology(self) -> str:
        return "magazine" if self._magazine else "stack"

    def _target_size(self) -> QSize:
        a = self._available
        return QSize(a) if a.isValid() and not a.isEmpty() else self.size()

    def _fold_h(self, name: str) -> int:
        """Folded frame height: the frame's layout items except the body."""
        p = self._panels[name]
        lay = p.frame.layout()
        m = lay.contentsMargins()
        h, n = m.top() + m.bottom(), 0
        for i in range(lay.count()):
            item = lay.itemAt(i)
            if item.widget() is p.body:
                continue
            h += item.sizeHint().height()
            n += 1
        return h + lay.spacing() * max(0, n - 1)

    def _open_min(self, name: str) -> int:
        p = self._panels[name]
        return self._fold_h(name) + p.frame.layout().spacing() + max(1, p.body.minimumHeight())

    def _natural_h(self, name: str) -> int:
        p = self._panels[name]
        return self._fold_h(name) + p.frame.layout().spacing() + _content_height(p.body)

    def _header_need(self, name: str) -> int:
        """Header width with every tab unclipped (the summary chip excluded:
        folding must not move the magazine threshold)."""
        p = self._panels[name]
        hl = p.header.layout()
        m = hl.contentsMargins()
        w, n = m.left() + m.right(), 0
        for i in range(hl.count()):
            item = hl.itemAt(i)
            c = item.widget()
            if c is None or c is p.chip or c.isHidden():
                continue
            w += item.sizeHint().width()        # bounded by the widget's min / max
            n += 1
        return w + hl.spacing() * max(0, n - 1)

    def _col_min_w(self, name: str) -> int:
        """A magazine column's minimum: the body's font-derived minimum width
        and the unclipped header, whichever is wider, plus the frame margins."""
        p = self._panels[name]
        m = p.frame.layout().contentsMargins()
        return m.left() + m.right() + max(self._header_need(name),
                                          body_need_width(avastha=(name == "bottom")))

    def magazine_need(self) -> int:
        """Width at which the magazine layout fits (plan B.5): both columns'
        effective minimum widths (font-derived table minimums) plus the gap."""
        if not self._panels:
            return QWIDGETSIZE_MAX
        lay = self.layout()
        m = lay.contentsMargins()
        left = max(self._col_min_w(n) for n in L.MAGAZINE_NAMES)
        return m.left() + m.right() + left + self._col_min_w("bottom") + lay.spacing()

    def _set_topology(self, magazine: bool) -> None:
        bottom = self._panels["bottom"]
        if magazine:
            self._set_visual(bottom, False)
            self._right.layout().addWidget(bottom.frame)
            self._right.show()
        else:
            self._split.insertWidget(2, bottom.frame)
            self._right.hide()
        bottom.frame.show()
        bottom.fold.setVisible(not magazine)
        self._magazine = magazine

    def _relayout(self) -> None:
        # Geometry decisions need real geometry: a never-shown window (tests,
        # boot) or a hidden Chart tab keeps the last layout; showEvent re-runs.
        if not self._panels or self._drag is not None or not self.isVisible():
            return
        self.relayout_count += 1
        size = self._target_size()
        mag = L.want_magazine(size.width(), self.magazine_need(), self._magazine,
                              MAGAZINE_HYSTERESIS)
        if mag != self._magazine:
            self._set_topology(mag)
        names = self._names()
        m = self.layout().contentsMargins()
        avail = max(0, size.height() - m.top() - m.bottom())
        handles = self._split.handleWidth() * (len(names) - 1)
        fold = {n: self._fold_h(n) for n in names}
        natural = {n: self._natural_h(n) for n in names}
        if self._auto:
            weights = L.auto_weights(names, avail, natural, fold, handles)
        else:
            weights = L.weights_from(names, self._folded, self._fractions[self._topology()],
                                     natural)
        weights, bottom_first = self._hold_weights(names, weights, avail, natural, handles, fold)
        folded = {n for n, w in zip(names, weights) if w <= 0}
        self._apply_folds(folded)
        fold_l = [fold[n] for n in names]
        mins = [self._open_min(n) for n in names]
        if self._auto and not bottom_first:
            hs = L.auto_heights(weights, avail - handles, fold_l,
                                [natural[n] for n in names], mins)
        else:
            hs = L.give_surplus(L.heights(weights, avail - handles, fold_l, mins),
                                [natural[n] for n in names], [w > 0 for w in weights])
        self._split.setSizes(hs)
        self.last_layout = {"avail": avail, "weights": weights, "heights": hs,
                            "natural": natural, "fold": fold}
        if self._settles_left > 0:
            self._settle_timer.start()
        if self._split.count() > 1:
            self._split.handle(1).update()

    def _apply_folds(self, folded) -> None:
        folded = frozenset(folded)
        before = self._effective
        for p in self._panels.values():
            self._set_visual(p, p.name in folded)
        self._effective = folded
        opened = [n for n in before if n not in folded]
        if opened:
            self._reconcile(opened)
        if folded - before:
            for n in folded - before:
                cached = self._summaries.cached(n, self._gui) if self._gui else ""
                self._panels[n].chip.set_text(PENDING if cached is None else cached)
            self._schedule_chips()

    def _set_visual(self, p: _Panel, folded: bool) -> None:
        p.body.setVisible(not folded)
        p.chip.setVisible(folded)
        p.fold.set_folded(folded)
        set_header_folded(p.header, folded)      # title = active tab, swap hidden
        p.frame.setMaximumHeight(self._fold_h(p.name) if folded else QWIDGETSIZE_MAX)

    def _set_manual(self, names, weights, *, persist: bool) -> None:
        weights = L.ensure_one_open(weights)
        folded = [n for n, w in zip(names, weights) if w <= 0]
        # A fold outside this splitter (the bottom panel in magazine) is kept.
        kept = [n for n in self._manual_folded() if n not in names]
        self._auto = False
        self._folded = tuple(p for p in PANEL_NAMES if p in set(folded) | set(kept))
        opened = [w for w in weights if w > 0]
        s = sum(opened)
        self._fractions[self._topology()] = [w / s for w in opened] if s > 0 else None
        if persist:
            self._persist()
        self._relayout()

    def _commit(self, names, hs, *, persist: bool) -> None:
        flags = L.folded_flags(hs, [self._fold_h(n) for n in names])
        self._set_manual(names, [0.0 if f else float(h) for h, f in zip(hs, flags)],
                         persist=persist)

    def _manual_folded(self):
        if self._auto:
            return tuple(p for p in PANEL_NAMES if p in self._effective)
        return self._folded

    # ----------------------------------------------------------------- drag
    def drag_begin(self, index: int) -> None:
        names = self._names()
        if not 1 <= index < len(names):
            return
        self._relayout_if_pending()
        self._release_hold()
        a, b = index - 1, index
        hs = self._split.sizes()
        fa, fb = self._fold_h(names[a]), self._fold_h(names[b])
        total = hs[a] + hs[b]
        self._drag = {
            "index": index, "names": names, "hs": hs, "total": total, "raw": hs[a],
            "fold": (fa, fb), "min": (self._open_min(names[a]), self._open_min(names[b])),
            "cands": L.snap_candidates(total, fa, fb, self._natural_h(names[a]),
                                       self._natural_h(names[b])),
        }

    def drag_move(self, index: int, dy: int) -> None:
        d = self._drag
        if d is None or d["index"] != index:
            return
        a, b = index - 1, index
        (fa, fb), (ma, mb), total = d["fold"], d["min"], d["total"]
        raw = max(fa, min(total - fb, d["hs"][a] + dy))
        d["raw"] = raw
        ha = fa if raw < (fa + ma) / 2 else max(raw, ma)
        hb = total - ha
        if hb < (fb + mb) / 2:
            hb, ha = fb, total - fb
        elif hb < mb:
            hb, ha = mb, total - mb
        names = d["names"]
        self._set_visual(self._panels[names[a]], ha <= fa)
        self._set_visual(self._panels[names[b]], hb <= fb)
        hs = list(d["hs"])
        hs[a], hs[b] = int(ha), int(hb)
        self._split.setSizes(hs)

    def drag_end(self, index: int) -> None:
        d, self._drag = self._drag, None
        if d is None:
            return
        a, b = index - 1, index
        ha = L.snap(d["raw"], d["cands"])
        hs = list(d["hs"])
        hs[a], hs[b] = ha, d["total"] - ha
        self._commit(d["names"], hs, persist=True)

    # ------------------------------------------------------------ summaries
    def _schedule_chips(self, *_args) -> None:
        if self._effective:
            self._chip_timer.start()

    def _refresh_chips(self) -> None:
        if self._gui is None or self._tab_hidden:
            return
        for name in self._effective:
            self._panels[name].chip.set_text(self._summaries.text(name, self._gui))

    # ---------------------------------------------------------- persistence
    def _load_settings(self) -> None:
        from managers.settings_manager import get_settings
        s = get_settings()
        auto = s.get(KEYS["auto"], _factory(KEYS["auto"]))
        self._auto = auto if isinstance(auto, bool) else _factory(KEYS["auto"])
        if self._auto:
            return
        self._folded = L.parse_folded(s.get(KEYS["folded"], "")) or ()
        for topo in ("stack", "magazine"):
            self._fractions[topo] = L.parse_fractions(s.get(KEYS[topo], ""))

    def _persist(self) -> None:
        """One disk write per user action (plan D5); never on resize / auto."""
        from managers.settings_manager import get_settings
        s = get_settings()
        s.persist_runtime_change(KEYS["auto"], bool(self._auto), save=False)
        s.persist_runtime_change(KEYS["folded"], "" if self._auto else ",".join(self._folded),
                                 save=False)
        for topo in ("stack", "magazine"):
            s.persist_runtime_change(KEYS[topo], L.format_fractions(self._fractions[topo]),
                                     save=False)
        s.flush()


def _layout_rows_h(w) -> int:
    """Height of the nested layout rows of a plain page (the virupa rail row with its
    Tour key under the Aspects V and Aspects T matrices), which ``_content_height``
    skips: it measures the page's widgets only. Size hints, never current geometry."""
    if isinstance(w, QStackedWidget):
        return _layout_rows_h(w.currentWidget())
    lay = w.layout() if w is not None else None
    if type(w) is not QWidget or not isinstance(lay, QVBoxLayout):
        return 0
    rows = [lay.itemAt(i) for i in range(lay.count())]
    return sum(item.sizeHint().height() + lay.spacing() for item in rows
               if item.widget() is None and item.layout() is not None)


def _content_height(w) -> int:
    """Height ``w`` needs to show all of its current content (the "fit" snap
    and the AUTO rule): tables to their last row, text bodies up to a cap."""
    if w is None:
        return 0
    if isinstance(w, QStackedWidget):
        return _content_height(w.currentWidget())
    if isinstance(w, QTableView):
        hh = w.horizontalHeader()
        vm = w.viewportMargins()
        top = 0 if hh.isHidden() else max(hh.height(), hh.sizeHint().height())
        bottom = vm.bottom()
        from apps.panels.strength_style_switch import GAP, StrengthStyleSwitch, StrengthTable
        if isinstance(w, StrengthTable):
            # The V1 | V2 switch sits under the last row when there is room and
            # in a reserved bottom strip when not: "fit" always includes it.
            sw = w.findChild(StrengthStyleSwitch)
            bottom = sw.sizeHint().height() + 2 * GAP if sw is not None else bottom
        return max(vm.top(), top) + w.verticalHeader().length() + bottom + 2 * w.frameWidth()
    cap = scaled_px(NATURAL_CAP)
    fit = getattr(w, "fit_height", None)
    if callable(fit):           # a painted body whose sizeHint would calculate (Graph)
        return min(cap, int(fit()))
    if isinstance(w, QTextEdit):
        doc_h = int(w.document().size().height()) + 2 * w.frameWidth() + scaled_px(4)
        return min(cap, max(scaled_px(80), doc_h))
    lay = w.layout()
    if type(w) is QWidget and isinstance(lay, QVBoxLayout):
        m = lay.contentsMargins()
        h, n = m.top() + m.bottom(), 0
        for i in range(lay.count()):
            c = lay.itemAt(i).widget()
            if c is None or c.isHidden():
                continue
            if isinstance(c, (QTableView, QStackedWidget)) or callable(getattr(c, "fit_height", None)):
                h += _content_height(c)
            elif c.hasHeightForWidth() and w.width() > 0:
                h += c.heightForWidth(w.width())
            else:
                h += c.sizeHint().height()
            n += 1
        return h + lay.spacing() * max(0, n - 1)
    return min(cap, max(0, w.sizeHint().height()))
