"""SPEC-BAR-001 — SegmentButton: the bar's workhorse control (thin, stateful).

A QPushButton whose ENTIRE appearance is `paint_controls.paint_segment_button`
(INV-4: no QSS ever) and whose box is fixed at construction from the metrics
table (INV-1: no state variable in the geometry path). Every state setter
calls update() and NOTHING else — the M0 spike proved update() is
layout-silent while updateGeometry() wakes the layout even with an unchanged
hint (test/fidelity_bar/spike_layoutrequest.py).

Qt `checkable`/`checked` is used ONLY where the old bar used it (transit,
dual-rim — INV-5 semantics stability). The mockup's `.on` visual state is the
separate `lit` flag, driven by state observers (INV-7), so remote-control and
programmatic mode changes never depend on Qt's click bookkeeping.
"""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QPushButton

from . import motion as bar_motion
from . import paint_controls
from .bar_types import (BarMetrics, Role, SegInk, SegMotion, SegPos,
                        SegPaintState, SegSpec, button_font)
from .ladder import DUAL_ROLE_EXTRAS, LADDER, OVERFLOW_PAD_PX


class SegFader:
    """The three-clock fade driver for one SegmentButton (Dm4-2/3/14).

    One lazy Fader per animated group — fill (160 ms, signature curve), ink
    (160 ms, ease: fg/icon/rim/plus), acc (180 ms, ease). On every state
    edge `retarget_all` resolves the NEW target SegInk from live tokens,
    compares group-wise, and retargets only the clocks whose target actually
    moved (reversal shortening lives inside Fader, Dm4-5). The `from`
    snapshot is the DISPLAYED ink at the edge: the OLD target blended with
    the old snapshot at the clock's current t.
    """
    _GROUPS = ("fill", "ink", "acc")

    def __init__(self, btn: "SegmentButton"):
        self._btn = btn
        self._faders = {g: bar_motion.Fader(btn, g) for g in self._GROUPS}
        self._target: SegInk | None = None

    # -- keys / blending ----------------------------------------------------
    @staticmethod
    def _rgba(c):
        return None if c is None else c.rgba()

    @classmethod
    def _key(cls, g: str, ink: SegInk) -> tuple:
        if g == "fill":
            return (cls._rgba(ink.fill),)
        if g == "ink":
            return (cls._rgba(ink.fg), cls._rgba(ink.ico), ink.ico_opacity,
                    cls._rgba(ink.rim), cls._rgba(ink.plus))
        return (cls._rgba(ink.acc), cls._rgba(ink.acc_glow))

    @staticmethod
    def _mix(a, b, t):
        if a is None and b is None:      # keep "absent" absent (plus/rim)
            return None
        return bar_motion.lerp_premul(a, b, t)

    @classmethod
    def _blend(cls, g: str, frm: SegInk, to: SegInk, t: float) -> SegInk:
        """The on-screen ink for group ``g`` at clock position ``t``."""
        if g == "fill":
            return replace(to, fill=cls._mix(frm.fill, to.fill, t))
        if g == "ink":
            return replace(
                to,
                fg=cls._mix(frm.fg, to.fg, t),
                ico=cls._mix(frm.ico, to.ico, t),
                ico_opacity=(frm.ico_opacity
                             + (to.ico_opacity - frm.ico_opacity) * t),
                rim=cls._mix(frm.rim, to.rim, t),
                plus=cls._mix(frm.plus, to.plus, t))
        return replace(to, acc=cls._mix(frm.acc, to.acc, t),
                       acc_glow=cls._mix(frm.acc_glow, to.acc_glow, t))

    # -- driver -------------------------------------------------------------
    def seed(self, ink: SegInk) -> None:
        """First-paint baseline so the very first state edge can fade."""
        if self._target is None:
            self._target = ink

    def target_is_unset(self) -> bool:
        return self._target is None

    def retarget_all(self) -> None:
        btn = self._btn
        if (bar_motion.mode() is bar_motion.Mode.POSE
                or not btn.isVisible()):                 # Dm4-12/45: snap
            self.snap()
            return
        new = paint_controls.resolve_ink(btn._paint_state(),
                                         btn._tokens_fn())
        old, self._target = self._target, new
        if old is None:
            return                       # nothing displayed yet: no edge
        for g, f in self._faders.items():
            old_key = self._key(g, old)
            if old_key == self._key(g, new):
                continue
            f.ensure_baseline(old_key)     # first edge: reversal detectable
            if f.in_flight() and f.frm is not None:
                shown = self._blend(g, f.frm, old, f.t())
            else:
                shown = old
            f.retarget(self._key(g, new), shown)

    def motion_state(self) -> SegMotion | None:
        fl, ik, ac = (self._faders[g] for g in self._GROUPS)
        if not (fl.in_flight() or ik.in_flight() or ac.in_flight()):
            return None                  # resting: byte-identical M3 path
        return SegMotion(frm_fill=fl.frm, frm_ink=ik.frm, frm_acc=ac.frm,
                         t_fill=fl.t(), t_ink=ik.t(), t_acc=ac.t())

    def snap(self) -> None:
        """Cancel everything, land on end state (theme/metrics — Dm4-8/9)."""
        self._target = None              # re-seeded from live tokens at paint
        for f in self._faders.values():
            if f.in_flight() or f.frm is not None:
                f.snap()


class LiveDot:
    """The NOW dot (A16) — SOLID in every mode, never breathing.

    It used to ping-pong 0.30 -> 1.00 forever (Dm4-28..32). Lorris asked for a
    static dot, so the animation is gone: ``value()`` is 1.0 unconditionally
    and no QVariantAnimation is ever constructed. The class and the
    ``SegmentButton._dot`` slot survive so the paint path and the three
    ``sync()`` call sites (show/hide/settings-change) stay exactly as they
    were — ``sync()`` is now the no-op that keeps that wiring honest.

    Golden impact: none. POSE already pinned 1.0 and every capture forces
    POSE, so all goldens already render `.live` at opacity 1.
    """

    def __init__(self, btn: "SegmentButton"):
        self._btn = btn
        self._anim = None                # kept: asserted to stay None

    def value(self) -> float:
        """Always fully opaque — mode no longer changes the dot."""
        return 1.0

    def sync(self) -> None:
        """No-op: there is no loop to reconcile with mode or visibility."""
        return


class SegmentButton(QPushButton):
    def __init__(self, spec: SegSpec, metrics: BarMetrics, tokens_fn,
                 parent=None):
        super().__init__(parent)
        self._spec = spec
        self._m = metrics
        self._tokens_fn = tokens_fn      # () -> dict, read at PAINT time
        self._lit = False
        self._drop_hover = False
        self._alt_names = False                     # Dm3-18: the `*` accent
        self._disabled_reason = ""                  # Dm3-39 (D-12 tooltip)
        self._current_label = spec.labels[0] if spec.labels else ""
        self._pos = SegPos.MID
        self._tier = 0                              # density tier (M2 ladder)
        self._ladder_row = LADDER.get(spec.key)     # None: not tier-driven
        self._dual_role = False                     # D-22b extras (classic)
        self._hover = False                         # tracked flag (Dm4-11)
        self._fader = SegFader(self)                # M4 fade driver
        # A14 label swap (Dm4-39): outgoing vanishes instantly, incoming
        # fades in over 160 ms — one scalar clock, resting at 1.0.
        self._label_fade = bar_motion.HoverFade(self, bar_motion.MS_LABEL)
        self._label_fade.snap(1.0)
        self._dot = LiveDot(self) if spec.live_dot else None   # A16

        self.setToolTip(spec.tooltip)
        self.setCheckable(spec.checkable)
        self.setFont(button_font(metrics.fs))
        self.setCursor(Qt.ArrowCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setAttribute(Qt.WA_Hover, True)
        self._apply_fixed_box()

    # -- geometry (construction/tier time only; never from state) ----------
    def _labels_for(self, d: int) -> list[str]:
        """The variant list whose max sizes the box at tier d (INV-1 holds
        per (tier, config): any state-driven label swap stays inside it).
        Dual-role extras (D-22b) join only while the controller has enabled
        them — i.e. while the Sidereal segment is app-hidden."""
        if self._ladder_row is None:
            return list(self._spec.labels)
        labels = list(self._ladder_row.labels_at(d))
        if self._dual_role and labels:
            labels += list(DUAL_ROLE_EXTRAS.get(self._ladder_row.modes[d], ()))
        return labels

    def _pad_for(self, d: int) -> float | None:
        if self._spec.role is Role.SOLO:
            return OVERFLOW_PAD_PX          # LITERAL 8px, not *fs (D-22d)
        if self._ladder_row is None:
            return None
        css = self._ladder_row.pads[d]
        return None if css is None else css * self._m.fs

    def width_at(self, d: int) -> int:
        """THE box function — used both to size this widget and by the
        controller's required(d) table, so arithmetic and reality cannot
        diverge (T-1 equivalence)."""
        return self._m.button_width(self._labels_for(d),
                                    with_icon=bool(self._spec.icon),
                                    pad_x=self._pad_for(d))

    def set_dual_role(self, on: bool):
        """D-22b: controller-owned; reboxes if the current tier is affected."""
        if on != self._dual_role:
            self._dual_role = on
            self._apply_fixed_box()
            self.updateGeometry()
            self._sync_tooltip()                    # D-5/D-24 tooltip base

    def _apply_fixed_box(self):
        self.setFixedSize(self.width_at(self._tier), self._m.ctl_h)

    def set_metrics(self, metrics: BarMetrics):
        """Tier/scale change (controller-driven, M2). The ONE geometry path."""
        self._fader.snap()                          # Dm4-9: old-box snapshots
        self._label_fade.snap(1.0)
        self._m = metrics
        self.setFont(button_font(metrics.fs))
        self._apply_fixed_box()
        self.updateGeometry()

    def apply_tier(self, d: int):
        """The ladder's ONE geometry write per control (design doc §1.6):
        rebox for tier d's variant set + pad. Visibility is the controller's
        job (it must go through SegmentCluster.set_button_visible)."""
        if d == self._tier:
            return
        self._tier = d
        self._label_fade.snap(1.0)     # ladder steps are hard cuts (§3.9)
        self._apply_fixed_box()
        self.updateGeometry()
        self.update()

    @property
    def tier(self) -> int:
        return self._tier

    def set_position(self, pos: SegPos):
        self._pos = pos
        self.update()

    # -- paint-only state ---------------------------------------------------
    @property
    def lit(self) -> bool:
        return self._lit

    def set_lit(self, on: bool):
        if on != self._lit:
            self._lit = on
            self._fader.retarget_all()              # Dm4-22: all three clocks
            self._sync_tooltip()                    # D-24 name-set token
            self.update()
            self._notify_cluster()

    def set_drop_hover(self, on: bool):
        """SPEC-TRN-006 drop affordance — paint-only, like every state.
        The ring itself never fades (§3.9), but the state is an ink input."""
        if on != self._drop_hover:
            self._drop_hover = on
            self.update()

    def set_alt_names(self, on: bool):
        """D-24 (supersedes Dm3-17/18): alternate naming swaps the GLYPH —
        ``spec.alt_icon`` replaces ``spec.icon`` (sun = Aditya names on, ram =
        Western names on) and the lit cell's tooltip names the name set. The
        accent hairline no longer recolors (one marker, one meaning).
        Paint-only: never a label variant (D-22c), never geometry."""
        if on != self._alt_names:
            self._alt_names = on
            self._fader.retarget_all()
            self._sync_tooltip()
            self.update()

    def _icon_id(self) -> str:
        """D-24: the glyph that names the CURRENT name set."""
        if self._alt_names and self._spec.alt_icon:
            return self._spec.alt_icon
        # D-5 dual role: the classic cell standing in as SIDEREAL rests on
        # the Sidereal system's own emblem (star), not on the ram.
        if self._dual_role and self._current_label == "SIDEREAL":
            return "sid"
        return self._spec.icon

    def set_disabled_reason(self, reason: str):
        """Dm3-39 (D-12): while disabled, the tooltip appends the reason;
        the overflow QAction inherits it via act.setToolTip(btn.toolTip())."""
        self._disabled_reason = reason or ""
        self._sync_tooltip()

    def _sync_tooltip(self):
        base = self._spec.tooltip
        if (self._dual_role and self._current_label == "SIDEREAL"
                and self._spec.dual_tooltip):
            base = self._spec.dual_tooltip          # D-5: never "Tropical"
        # D-24: the LIT zodiac cell names its name set behind the title well's
        # middle dot; unlit cells stay plain (clicking them selects a system).
        if self._lit and len(self._spec.name_sets) == 2:
            base = f"{base} · {self._spec.name_sets[1 if self._alt_names else 0]}"
        if self._disabled_reason and not self.isEnabled():
            self.setToolTip(f"{base} — {self._disabled_reason}")
        else:
            self.setToolTip(base)

    def changeEvent(self, event):
        super().changeEvent(event)
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.EnabledChange:
            self._sync_tooltip()
            # Dm4-11: a control disabled under the pointer must not keep a
            # hover fill.
            if not self.isEnabled():
                self._hover = False
            self._fader.retarget_all()
            self.update()

    # -- M4 fade edges (Dm4-11/14): real Qt events, tracked flags -----------
    def enterEvent(self, e):
        super().enterEvent(e)
        self._hover = True
        self._fader.retarget_all()
        self.update()

    def leaveEvent(self, e):
        super().leaveEvent(e)
        self._hover = False
        self._fader.retarget_all()
        self.update()

    def mousePressEvent(self, e):
        super().mousePressEvent(e)
        self._fader.retarget_all()

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        self._fader.retarget_all()

    def showEvent(self, e):
        super().showEvent(e)
        if self._dot is not None:
            self._dot.sync()                       # Dm4-30 P1 / Dm4-31

    def hideEvent(self, e):
        super().hideEvent(e)
        self._hover = False                        # defensive clear (Dm4-11)
        self._fader.snap()                         # Dm4-12: no hidden work
        self._label_fade.snap(1.0)
        if self._dot is not None:
            self._dot.sync()                       # Dm4-30 P1: pause

    def snap_motion(self):
        """Bar-level cancel hook (theme refresh / metrics — Dm4-8/9)."""
        self._fader.snap()
        self._label_fade.snap(1.0)
        if self._dot is not None:
            self._dot.sync()             # mode may have flipped (Dm4-49)

    def _notify_cluster(self):
        """Divider suppression is painted by the parent cluster; a
        programmatic lit change must invalidate it too (Sol M1 minor 1)."""
        parent = self.parentWidget()
        notify = getattr(parent, "notify_state_changed", None)
        if callable(notify):
            notify()

    def set_base_label(self, text: str):
        """Swap the displayed variant (must be within the measured set).

        M4 (Dm4-39/40): a real swap fades the INCOMING variant in; a swap
        that lands while one is running restarts at t=0 (no chaining — the
        CSS span that becomes [hidden] disappears at once). Tier-driven form
        changes never come through here, so ladder cuts stay hard cuts.
        """
        old_disp = self._displayed_label()
        self._current_label = text
        self._sync_tooltip()                        # D-5/D-24 tooltip base
        if self._displayed_label() not in ("", old_disp):
            self._label_fade.snap(0.0)
            self._label_fade.to(1.0)
        self.update()

    def setText(self, text: str):
        """INV-5 bridge: legacy writers drive the label through
        QPushButton.setText ("⟐ Overlay", chart_title_widget:309) but the
        painter shows _current_label. Map the write onto the measured variant
        set (glyphs/case stripped) so the box never changes; an unmatched
        text keeps the painted label but stays readable via text()."""
        super().setText(text)

        def _norm(s):
            return "".join(c for c in (s or "")
                           if c.isalnum() or c.isspace()).strip().upper()

        norm = _norm(text)
        # Dm3-10/Dm3-22: the measured set is the LADDER row's full tuple when
        # one exists (the spec labels are its construction subset), plus the
        # dual-role logical label while D-22b has it reserved — so the old
        # writers' "◇ North" / "+ Aditya" / "Sidereal" all land on variants.
        candidates = list(self._spec.labels)
        if self._ladder_row is not None:
            candidates += [v for v in self._ladder_row.full
                           if v not in candidates]
        if self._dual_role:
            candidates.append("SIDEREAL")
        for variant in candidates:
            # normalize BOTH sides: "+ TROPICAL"'s glyph would otherwise
            # never match the glyph-stripped incoming text (T6-11)
            if norm == _norm(variant):
                self.set_base_label(variant)
                break

    def base_label(self) -> str:
        return self._current_label

    @property
    def spec(self) -> SegSpec:
        return self._spec

    # -- painting -----------------------------------------------------------
    def _paint_state(self) -> SegPaintState:
        return SegPaintState(
            role=self._spec.role, pos=self._pos,
            lit=self._lit or self.isChecked(),
            # Dm4-11: the tracked flag, not underMouse() — WA_UnderMouse is
            # set by dispatchEnterLeave, so a synthesized QEnterEvent (tests,
            # capture posing) reaches enterEvent but never underMouse().
            hovered=self._hover and self.isEnabled(),
            pressed=self.isDown(),
            focused=self.hasFocus(),
            enabled=self.isEnabled(),
            label=self._displayed_label(), icon=self._icon_id(),
            live_dot=self._spec.live_dot, gold_plus=self._spec.gold_plus,
            drop_hover=self._drop_hover, alt_names=self._alt_names,
        )

    def _displayed_label(self) -> str:
        """The tier-mapped text: logical label -> full/min/tiny form, or ""
        at icon-only tiers. The LOGICAL label (set_base_label/setText) is
        untouched — INV-5 writers keep working at every tier."""
        if self._ladder_row is None:
            return self._current_label
        # Dm3-22: the dual-role logical label is NOT in the row's full tuple
        # (adding it there would grow the hdhid box the goldens show plain);
        # map it through DUAL_ROLE_EXTRAS here, keeping the table pure.
        if self._dual_role and self._current_label == "SIDEREAL":
            extras = DUAL_ROLE_EXTRAS.get(
                self._ladder_row.modes[self._tier], ())
            return extras[0] if extras else ""
        return self._ladder_row.display_at(self._current_label, self._tier)

    def _cluster_thumb_pose(self):
        """The travelling zodiac thumb, if the parent cluster is mid-slide
        (Dm4-23), translated into THIS widget's coordinates. Widget origins
        are integer, so translating the rect preserves the device-grid
        phase — every child slices one and the same cluster-space rect."""
        if self._spec.role is not Role.ZOD:
            return None
        fn = getattr(self.parentWidget(), "thumb_pose", None)
        pose = fn() if callable(fn) else None
        if pose is None:
            return None
        from .bar_types import ThumbPose
        return ThumbPose(pose.rect.translated(-self.x(), -self.y()),
                         pose.radii)

    def paintEvent(self, event):
        p = QPainter(self)
        try:
            st = self._paint_state()
            tokens = self._tokens_fn()
            if self._fader.target_is_unset():      # baseline for first edge
                self._fader.seed(paint_controls.resolve_ink(st, tokens))
            mo = self._fader.motion_state()
            lt = self._label_fade.value()
            if lt < 1.0:                           # A14: incoming label fade
                mo = replace(mo or SegMotion(), t_label=lt)
            pose = self._cluster_thumb_pose()
            if pose is not None:                   # D-2 travelling thumb
                mo = replace(mo or SegMotion(), thumb=pose)
            if self._dot is not None:
                dv = self._dot.value()
                if dv < 1.0:      # A16: static now, so this never fires —
                    mo = replace(mo or SegMotion(), dot=dv)   # kept for the
                    # disabled-dim path, which still multiplies motion.dot.
            paint_controls.paint_segment_button(
                p, QRectF(self.rect()), st, tokens, self._m,
                self.devicePixelRatioF(), motion=mo)
        finally:
            p.end()

    def checkStateSet(self):  # checked change repaints, never relayouts
        super().checkStateSet()
        self._fader.retarget_all()    # checked feeds `lit` (INV-5 controls)
        self.update()

    def nextCheckState(self):
        super().nextCheckState()
        self._fader.retarget_all()
        self.update()
