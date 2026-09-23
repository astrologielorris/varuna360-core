"""SPEC-BAR-001 — container widgets: SegmentCluster, ZodiacTray, HairlineSep.

Containers own layout and SHARED chrome (cluster fill, dividers, tray recess,
the D-14 focus-ring overlay); children are real SegmentButtons with native
hover/focus/click (spec §3 tree — report 06's single-widget alternative was
rejected for attribute stability). Divider suppression next to a lit segment
is repainted via each child's state changes (`notify_state_changed`).
"""
from __future__ import annotations

from PySide6.QtCore import (QAbstractAnimation, QEvent, QRectF, Qt,
                            QVariantAnimation)
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QHBoxLayout, QWidget

from . import motion as bar_motion
from . import paint_controls, paint_surfaces
from .bar_types import BarMetrics, Role, SegPos, ThumbPose
from .motion import MS_DIVIDER, MS_THUMB, HoverFade
from .segment_button import SegmentButton


class SegmentCluster(QWidget):
    """One .seg pill: shared rounded chrome + N SegmentButton children."""

    def __init__(self, buttons: list[SegmentButton], metrics: BarMetrics,
                 tokens_fn, transparent_bg: bool = False, parent=None):
        super().__init__(parent)
        self._m = metrics
        self._tokens_fn = tokens_fn
        self._transparent = transparent_bg
        self._buttons = list(buttons)

        # M4 (Dm4-38): one suppression fader per neighbour PAIR, keyed by
        # button key — a tier change that hides a sibling can then never
        # leave a fader animating the wrong boundary.
        self._div_faders: dict[tuple[str, str], HoverFade] = {}
        # M4 thumb slide (D-2 / Dm4-23..27): the cluster owns the travelling
        # rect; each ZOD child paints the slice inside its own box. At rest
        # the cluster owns nothing and the lit child paints its M1 thumb.
        self._thumb_target: SegmentButton | None = None
        self._thumb_anim: QVariantAnimation | None = None
        self._thumb_frm: tuple[QRectF, tuple] | None = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        for b in self._buttons:
            b.setParent(self)
            lay.addWidget(b)
            b.toggled.connect(self._on_child_state)
        self.setFixedHeight(metrics.ctl_h)
        self._restripe()
        self.snap_motion()               # pre-create faders at rest: paint
        #                                  stays a pure read (never creates)

    def _restripe(self):
        """Assign first/mid/last corner rounding over VISIBLE children."""
        vis = [b for b in self._buttons if not b.isHidden()]
        for b in vis:
            b.set_position(SegPos.MID)
        if len(vis) == 1:
            vis[0].set_position(SegPos.SOLO)
        elif vis:
            vis[0].set_position(SegPos.FIRST)
            vis[-1].set_position(SegPos.LAST)
        self.update()

    def notify_state_changed(self):
        """A child's lit state moved — divider suppression may change, and
        the zodiac thumb may need to travel (Dm4-26)."""
        self._retarget_dividers()
        self._maybe_arm_slide()
        self.update()

    def set_button_visible(self, btn: SegmentButton, visible: bool):
        """THE visibility path for cluster children (Sol M1 major 5): a bare
        setVisible leaves the FIRST/MID/LAST corner striping stale, which only
        shows on hover/lit fills — restripe over the new visible set."""
        btn.setVisible(visible)
        self._restripe()
        self.snap_motion()               # Dm4-38: visibility change snaps

    def _on_child_state(self, _checked):
        self._retarget_dividers()
        self.update()

    def buttons(self) -> list[SegmentButton]:
        return list(self._buttons)

    def set_metrics(self, metrics: BarMetrics):
        self._m = metrics
        self.setFixedHeight(metrics.ctl_h)
        for b in self._buttons:
            b.set_metrics(metrics)
        self.snap_motion()               # Dm4-9: rebox cancels animations

    # -- divider suppression fade (Dm4-38) ----------------------------------
    def _pair_targets(self) -> list[tuple[tuple[str, str], float]]:
        vis = [b for b in self._buttons if not b.isHidden()]
        out = []
        for a, b in zip(vis, vis[1:]):
            lit = (a.lit or a.isChecked()) or (b.lit or b.isChecked())
            out.append(((a.spec.key, b.spec.key), 0.0 if lit else 1.0))
        return out

    def _pair_fader(self, key: tuple[str, str], target: float) -> HoverFade:
        f = self._div_faders.get(key)
        if f is None:                    # born AT its target: no birth fade
            f = HoverFade(self, MS_DIVIDER)
            f.snap(target)
            self._div_faders[key] = f
        return f

    def _retarget_dividers(self):
        for key, target in self._pair_targets():
            self._pair_fader(key, target).to(target)

    def snap_motion(self):
        """Cancel divider fades and land on current targets (tier/visibility/
        metrics/theme — the Dm4-8/9 rule applied to the cluster's chrome).
        Pairs that no longer exist in the visible set are stopped and DROPPED
        — a fold must never leave a fader animating a vanished boundary.
        Dm4-27: the thumb slide cancels too — stop, re-anchor the target to
        the currently-lit segment, pose drops to None (resting paint)."""
        self._cancel_thumb_anim()
        lit = [b for b in self._buttons
               if not b.isHidden() and (b.lit or b.isChecked())
               and b.spec.role is Role.ZOD]
        if len(lit) == 1:
            self._thumb_target = lit[0]
        self._update_zod()
        targets = dict(self._pair_targets())
        for key in list(self._div_faders):
            if key in targets:
                self._div_faders[key].snap(targets.pop(key))
            else:
                self._div_faders[key].snap(0.0)     # stop its clock
                del self._div_faders[key]
        for key, target in targets.items():         # newly-visible pairs
            self._pair_fader(key, target)
        self.update()

    # -- the zodiac thumb slide (D-2 / Dm4-23..27) --------------------------
    def _zod_rest_pose(self, b: SegmentButton) -> tuple[QRectF, tuple]:
        """The resting thumb of segment ``b``: its box in CLUSTER coords and
        its SegPos corner radii — what the lit child paints at rest."""
        g = b.geometry()
        rect = QRectF(g)
        radii = paint_controls._corner_radii(
            b._pos, b.spec.role, QRectF(0, 0, g.width(), g.height()), self._m)
        return rect, radii

    def _maybe_arm_slide(self) -> None:
        """Dm4-26: the exactly-one-lit rule, evaluated synchronously. The
        0-lit / 2-lit transients inside one _render_state call never reach a
        paint (update() is deferred), so this fires once per mode change —
        on the final write. len != 1 leaves the thumb in place (M1
        degradation: every lit child paints its own resting thumb)."""
        lit = [b for b in self._buttons
               if not b.isHidden() and (b.lit or b.isChecked())
               and b.spec.role is Role.ZOD]
        if len(lit) != 1:
            return
        if lit[0] is self._thumb_target:
            return
        self._start_slide(lit[0])

    def _start_slide(self, to: SegmentButton) -> None:
        src = self._thumb_target
        frm = None
        pose = self.thumb_pose()          # mid-slide retarget: continuity
        if pose is not None:
            frm = (pose.rect, pose.radii)
        elif src is not None and not src.isHidden():
            frm = self._zod_rest_pose(src)
        self._thumb_target = to
        self._cancel_thumb_anim()
        # Dm4-12/45: no animation while hidden or in POSE; no source = the
        # first observation — the thumb simply appears at rest.
        if (frm is None or to.isHidden()
                or bar_motion.mode() is bar_motion.Mode.POSE
                or not self.isVisible()):
            self._update_zod()
            return
        self._thumb_frm = frm
        anim = QVariantAnimation(self)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(MS_THUMB)
        anim.setEasingCurve(bar_motion.EASE_FILL)   # the thumb IS the fill
        anim.valueChanged.connect(lambda _v: self._update_zod())
        anim.finished.connect(self._on_slide_done)
        self._thumb_anim = anim
        anim.start()

    def _on_slide_done(self) -> None:
        self._thumb_anim = None
        self._thumb_frm = None
        self._update_zod()               # children fall back to resting paint

    def _cancel_thumb_anim(self) -> None:
        if self._thumb_anim is not None:
            self._thumb_anim.stop()
            self._thumb_anim = None
        self._thumb_frm = None

    def _update_zod(self) -> None:
        for b in self._buttons:
            if b.spec.role is Role.ZOD and not b.isHidden():
                b.update()

    def thumb_pose(self) -> ThumbPose | None:
        """The travelling thumb, or None at rest — the children's read side.
        The destination rect resolves LIVE (Dm4-27 cancels on any geometry
        event, so it cannot go stale mid-slide)."""
        anim = self._thumb_anim
        if (anim is None or self._thumb_frm is None
                or self._thumb_target is None
                or anim.state() != QAbstractAnimation.State.Running):
            return None
        t = float(anim.currentValue())               # eased (EASE_FILL)
        fr, frad = self._thumb_frm
        tr, trad = self._zod_rest_pose(self._thumb_target)
        rect = QRectF(fr.x() + (tr.x() - fr.x()) * t,
                      fr.y() + (tr.y() - fr.y()) * t,
                      fr.width() + (tr.width() - fr.width()) * t,
                      fr.height() + (tr.height() - fr.height()) * t)
        radii = tuple(a + (b - a) * t for a, b in zip(frad, trad))
        return ThumbPose(rect, radii)

    def hideEvent(self, e):
        super().hideEvent(e)
        self.snap_motion()               # Dm4-12: nothing animates hidden

    def _dividers(self) -> list[tuple[float, float]]:
        """(x, visibility 0..1) per inner boundary — the fade's read side.
        Pure read: retargeting happens on state edges, never at paint."""
        out = []
        vis = [b for b in self._buttons if not b.isHidden()]
        for (key, target), (a, b) in zip(self._pair_targets(),
                                         zip(vis, vis[1:])):
            out.append((float(b.geometry().left()),
                        self._pair_fader(key, target).value()))
        return out

    def paintEvent(self, event):
        p = QPainter(self)
        try:
            paint_surfaces.paint_cluster(
                p, QRectF(self.rect()), self._tokens_fn(), self._m,
                self.devicePixelRatioF(), self._dividers(),
                transparent_bg=self._transparent)
        finally:
            p.end()
        # D-14 focus overlay runs AFTER children paint — children are widgets,
        # so the true overlay lives in a paint pass the cluster schedules; the
        # ring lands with the state milestone.


class HairlineSep(QWidget):
    """A .sep — 1 logical px wide, sep_h tall, hairline token."""

    def __init__(self, metrics: BarMetrics, tokens_fn, gradient=False,
                 parent=None):
        super().__init__(parent)
        self._m = metrics
        self._tokens_fn = tokens_fn
        self._gradient = gradient
        self._apply_box(metrics)

    def _apply_box(self, metrics: BarMetrics):
        # D-22i REFUTED by the gate: folding the mockup's .modsplit margins
        # (:354) into this box read +2px tray width against the goldens in
        # BOTH HD configs (hdvis 402->404 vs golden 402; hdhid 498->500 vs
        # 497). The golden detector is the contract; the box stays 1px.
        self.setFixedSize(1, metrics.modsplit_h if self._gradient
                          else metrics.sep_h)

    def set_metrics(self, metrics: BarMetrics):
        self._m = metrics
        self._apply_box(metrics)

    def paintEvent(self, event):
        p = QPainter(self)
        try:
            fn = (paint_surfaces.paint_modsplit if self._gradient
                  else paint_surfaces.paint_hairline_sep)
            fn(p, QRectF(self.rect()), self._tokens_fn(), self._m,
               self.devicePixelRatioF())
        finally:
            p.end()


class ZodiacTray(QWidget):
    """The recessed .zodunit: zodiac SegmentCluster + modsplit + capsule."""

    _IDLE = object()     # sentinel: "no ink motion seen since last rest"

    def __init__(self, zodiac_cluster: SegmentCluster, modsplit: HairlineSep,
                 capsule: SegmentButton, metrics: BarMetrics, tokens_fn,
                 parent=None):
        super().__init__(parent)
        self._m = metrics
        self._tokens_fn = tokens_fn
        self.zodiac_cluster = zodiac_cluster
        self.capsule = capsule

        lay = QHBoxLayout(self)
        pad = metrics.tray_pad
        lay.setContentsMargins(pad, pad, pad, pad)
        lay.setSpacing(round(3 * metrics.fs))
        lay.addWidget(zodiac_cluster)
        lay.addWidget(modsplit)
        lay.addWidget(capsule)
        self._modsplit = modsplit
        self.setFixedHeight(metrics.tray_h)
        # outer-ring motion carry (Sol M4 r2 major 2): the from-colour of
        # the outer gold ring is whatever this tray LAST painted, captured
        # when a new ink motion starts. _outer_seen tracks the ink fader's
        # per-retarget frozen snapshot BY IDENTITY (motion_state() builds
        # a fresh SegMotion each call, but frm_ink is the one object
        # retarget() froze). _IDLE forces a re-capture after rest.
        self._outer_painted = None
        self._outer_frm = None
        self._outer_seen = ZodiacTray._IDLE
        # the lit capsule's OUTER gold ring (:369) lands on OUR pixels —
        # repaint its region on every toggle, and per capsule PAINT TICK
        # while its ink clock is in flight (the ring rides that clock).
        capsule.toggled.connect(
            lambda _=False: self.update(
                self.capsule.geometry().adjusted(-2, -2, 2, 2)))
        capsule.installEventFilter(self)

    def eventFilter(self, obj, e):
        if obj is self.capsule and e.type() == QEvent.Type.Paint:
            f = getattr(self.capsule, "_fader", None)
            if f is not None and f.motion_state() is not None:
                self.update(self.capsule.geometry().adjusted(-2, -2, 2, 2))
        return False

    def set_metrics(self, metrics: BarMetrics):
        self._m = metrics
        pad = metrics.tray_pad
        self.layout().setContentsMargins(pad, pad, pad, pad)
        self.layout().setSpacing(round(3 * metrics.fs))
        self.zodiac_cluster.set_metrics(metrics)
        self._modsplit.set_metrics(metrics)
        self.capsule.set_metrics(metrics)
        self.setFixedHeight(metrics.tray_h)

    def snap_motion(self):
        """Drop the outer-ring carry (Dm4-8/9 applied to the tray's own
        painted state): a snap lands on the end state, so the next motion
        must start fresh — a theme flip's old-theme colour must never
        survive in _outer_painted. The first post-snap paint's mo-is-None
        branch re-seeds it from the live target. (The capsule's own fader
        is snapped separately by the bar's snap_motion sweep.)"""
        self._outer_painted = None
        self._outer_frm = None
        self._outer_seen = ZodiacTray._IDLE
        self.update()

    # -- M2 ladder handles (12_opus_m2_ladder.md §1.6) ----------------------
    def set_modsplit_visible(self, visible: bool):
        self._modsplit.setVisible(visible)          # :451 — hidden at d3+

    def set_gap(self, px: int):
        self.layout().setSpacing(px)                # :452 — 0 at d3+ (inert)

    def paintEvent(self, event):
        p = QPainter(self)
        try:
            tokens = self._tokens_fn()
            paint_surfaces.paint_tray(p, QRectF(self.rect()), tokens,
                                      self._m, self.devicePixelRatioF())
            # .btn.mod.on's SECOND box-shadow (:369) — `0 0 0 .5px gold@.22`,
            # an OUTSET ring on the tray's pixels just outside the capsule.
            # paint_segment_button records the deferral ("the outer ring
            # belongs to whatever paints the tray"); CP-4m's light-theme
            # cells caught it as a missing C25 strip at the capsule edge.
            # It rides the capsule's INK clock (Sol M4 major 4: both rings
            # live in the same transitioned box-shadow property, :256/:366-
            # 369 — an endpoint-only outer ring pops while the inner fades).
            cap = self.capsule
            if cap.isVisible():
                lit = cap.lit or cap.isChecked()
                target = tokens["mod_rim_on_outer"] if lit else None
                fader = getattr(cap, "_fader", None)
                mo = fader.motion_state() if fader is not None else None
                if mo is None:
                    col = target
                    self._outer_seen = ZodiacTray._IDLE
                else:
                    if mo.frm_ink is not self._outer_seen:
                        # a NEW ink motion — a fresh press or a mid-
                        # flight reversal. The from-colour is what this
                        # tray last put on glass (Sol M4 r2 major 2:
                        # inferring on/off from frm_ink.rim equality
                        # breaks on reversal, where the frozen rim is a
                        # mid blend — the ring popped).
                        self._outer_seen = mo.frm_ink
                        self._outer_frm = self._outer_painted
                    col = None
                    if self._outer_frm is not None or target is not None:
                        col = bar_motion.lerp_premul(
                            self._outer_frm, target, mo.t_ink)
                self._outer_painted = col
                if col is not None and col.alpha() > 0:
                    g = QRectF(cap.geometry())

                    def pill(rr):
                        r = rr.height() / 2.0
                        return paint_controls._rounded_path(rr, (r, r, r, r))
                    paint_surfaces.outset_hairline(
                        p, g, pill, col, self.devicePixelRatioF())
        finally:
            p.end()
