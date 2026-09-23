"""SPEC-BAR-001 M4 — the bar's motion layer: curves, modes, the Fader.

Design: proprietary_docs/spec_design/action_bar_v2/16_opus_m4_motion.md
(Dm4-1..12, Dm4-44/45/48). Three hard rules:

- INV-1: nothing here touches geometry — a tick calls ``update()`` only.
- INV-7: animations are TRIGGERED by the paint-only setters and real Qt
  input events; this module adds no writer path and no state source.
- Determinism: the whole layer is poseable (Mode.POSE) — in POSE no
  QVariantAnimation is ever constructed and every value sits at its end
  state, so a ``grab()`` can never race a 16 ms tick (Dm4-45).

This module owns the ONLY QEasingCurve constructions in the bar (Dm4-10)
and the process-level mode switch (Dm4-44).
"""
from __future__ import annotations

import os
from enum import Enum

from PySide6.QtCore import QAbstractAnimation, QPointF, QVariantAnimation
from PySide6.QtCore import QEasingCurve
from PySide6.QtGui import QColor


# ---------------------------------------------------------------- the mode
class Mode(Enum):
    LIVE = "live"        # default: everything animates
    REDUCED = "reduced"  # ui.reduce_motion: the infinite loop stops (dot
    #                      pinned), the 160/180 ms transitions still run
    #                      (Dm4-48 — the mockup's media query overrides
    #                      exactly one rule, :313)
    POSE = "pose"        # tests & captures: nothing animates, end state


# The env var is load-bearing: capture_bar_shots re-invokes itself in a
# subprocess per capture (theme is process-level), so an in-process flag
# cannot reach the capture (Dm4-44).
_MODE = Mode(os.environ.get("V360_BAR_MOTION", "live"))


def mode() -> Mode:
    return _MODE


def set_mode(m: Mode) -> None:
    """In-process override, for tests that flip live<->pose in one app."""
    global _MODE
    _MODE = m


def animated() -> bool:
    return _MODE is Mode.LIVE


# --------------------------------------------------------------- the curves
def _bez(x1: float, y1: float, x2: float, y2: float) -> QEasingCurve:
    c = QEasingCurve(QEasingCurve.Type.BezierSpline)
    c.addCubicBezierSegment(QPointF(x1, y1), QPointF(x2, y2),
                            QPointF(1.0, 1.0))
    return c


# E6: BezierSpline matches CSS cubic-bezier to 1.8e-5; OutCubic is off by
# 0.201 on the signature curve — BezierSpline is mandatory, not a nicety.
EASE_FILL = _bez(.32, .72, 0, 1)      # :256  the signature curve, fills only
EASE_CSS = _bez(.25, .1, .25, 1)      # CSS `ease` — everything else
# EASE_BREATHE / BREATHE_HALF_MS are GONE: the NOW dot is static (Lorris),
# the mockup's `.live` keyframes were deleted, and nothing else used that
# curve. Do not reintroduce them without a design decision to match.

MS_FILL, MS_INK, MS_ACC, MS_LABEL = 160, 160, 180, 160
MS_WELL, MS_CHEV, MS_DIVIDER, MS_THUMB = 180, 160, 160, 160

GROUP_MS = {"fill": MS_FILL, "ink": MS_INK, "acc": MS_ACC,
            "label": MS_LABEL}
GROUP_EASE = {"fill": EASE_FILL, "ink": EASE_CSS, "acc": EASE_CSS,
              "label": EASE_CSS}


# ----------------------------------------------------- colour interpolation
def lerp_premul(a: QColor | None, b: QColor | None, t: float) -> QColor:
    """CSS Color 4 interpolation — PREMULTIPLIED sRGB (Dm4-4).

    ``None`` == fully transparent. A naive component-wise lerp from
    transparent drags the midpoint toward black and a hover fade reads as
    a grey flash; premultiplying is what CSS actually does.

    ENDPOINTS ARE EXACT: t<=0 / t>=1 return the input colour itself, not a
    float round-trip of it — the resting render must be byte-identical to
    the pre-M4 one (Dm4-6), and a painter passing t=0.0/1.0 must land on
    the token, not on fromRgbF's re-quantisation of it.
    """
    if t <= 0.0:
        return QColor(a) if a is not None else QColor(0, 0, 0, 0)
    if t >= 1.0:
        return QColor(b) if b is not None else QColor(0, 0, 0, 0)
    a = a or QColor(0, 0, 0, 0)
    b = b or QColor(0, 0, 0, 0)
    aa, ab = a.alphaF(), b.alphaF()
    al = aa + (ab - aa) * t
    if al <= 0.0:
        return QColor(0, 0, 0, 0)

    def ch(fa: float, fb: float) -> float:
        return (fa * aa + (fb * ab - fa * aa) * t) / al

    return QColor.fromRgbF(ch(a.redF(), b.redF()), ch(a.greenF(), b.greenF()),
                           ch(a.blueF(), b.blueF()), al)


# ------------------------------------------------------------------ Fader
class Fader:
    """One animated GROUP on one widget (Dm4-2): `from`-snapshot +
    target-resolved-at-paint (Dm4-3), with the CSS Transitions reversal
    shortening rule (Dm4-5).

    The owner supplies ``snapshot()`` (freeze what is on screen NOW) and
    reads ``t()`` at paint time; the target is never stored here — the
    painter resolves it from live tokens (Dm4-7, theme safety).
    """

    def __init__(self, widget, group: str):
        self._w = widget
        self._group = group
        self._anim: QVariantAnimation | None = None
        self._t = 1.0
        self.frm = None            # the frozen SegInk snapshot (or None)
        self._target_key = None    # opaque identity of the current target

    # -- read side --------------------------------------------------------
    def t(self) -> float:
        return self._t

    def in_flight(self) -> bool:
        return self._t < 1.0

    # -- write side -------------------------------------------------------
    def ensure_baseline(self, key) -> None:
        """Seed the resting identity before the FIRST edge — without it the
        first fade records `from == None` and its reversal (hover in, then
        straight out) cannot be recognised as one (Dm4-5)."""
        if self._target_key is None:
            self._target_key = key

    def retarget(self, target_key, snapshot) -> None:
        """Start (or retarget) a fade toward ``target_key``.

        ``target_key`` is an opaque, comparable identity of the target
        appearance (used for the reversal rule and to no-op repeated
        renders); ``snapshot`` is the CURRENTLY DISPLAYED ink, frozen by
        the caller before the state change repaints.
        """
        if target_key == self._target_key and not self.in_flight():
            return                                    # already there
        if (mode() is Mode.POSE
                or not self._w.isVisible()):          # Dm4-12/45: snap
            self.snap(target_key)
            return

        factor = 1.0
        if (self._anim is not None
                and self._anim.state() == QAbstractAnimation.State.Running
                and target_key == self._from_key()):
            # CSS reversal shortening: reversing a half-done fade takes
            # half the time, not a fresh full duration (Dm4-5)
            factor = float(self._anim.currentValue())

        self.frm = snapshot
        self._frm_key = self._target_key
        self._target_key = target_key
        self._t = 0.0

        if self._anim is None:                        # lazy (Dm4-2)
            self._anim = QVariantAnimation(self._w)
            self._anim.setStartValue(0.0)
            self._anim.setEndValue(1.0)
            self._anim.setEasingCurve(GROUP_EASE[self._group])
            self._anim.valueChanged.connect(self._tick)
            self._anim.finished.connect(self._done)
        else:
            self._anim.stop()
        self._anim.setDuration(max(1, round(GROUP_MS[self._group] * factor)))
        self._anim.setCurrentTime(0)
        self._anim.start()

    def snap(self, target_key=None) -> None:
        """Cancel and land on the end state (theme/metrics/hide — Dm4-8/9)."""
        if self._anim is not None:
            self._anim.stop()
        if target_key is not None:
            self._target_key = target_key
        self._t = 1.0
        self.frm = None
        self._w.update()

    # -- internals --------------------------------------------------------
    def _from_key(self):
        return getattr(self, "_frm_key", None)

    def _tick(self, v) -> None:
        self._t = float(v)
        self._w.update()

    def _done(self) -> None:
        self._t = 1.0
        self.frm = None
        self._w.update()


# --------------------------------------------------------------- HoverFade
class HoverFade:
    """A two-endpoint scalar fade, 0..1 (§3.8: well, chevron, close glyph).

    The painter takes the VALUE as a float and blends its two fixed styles;
    hover-in animates toward 1, hover-out toward 0. For a pure two-endpoint
    reversal the CSS shortening factor reduces to |target - current| (the
    exact-reversal case of Dm4-5), so duration = ms * that distance.
    """

    def __init__(self, widget, ms: int, curve: QEasingCurve | None = None):
        self._w = widget
        self._ms = ms
        self._curve = curve if curve is not None else EASE_CSS
        self._anim: QVariantAnimation | None = None
        self._v = 0.0

    def value(self) -> float:
        return self._v

    def in_flight(self) -> bool:
        return (self._anim is not None
                and self._anim.state() == QAbstractAnimation.State.Running)

    def to(self, target: float) -> None:
        target = 1.0 if target >= 1.0 else 0.0 if target <= 0.0 else target
        if target == self._v and not self.in_flight():
            return
        if mode() is Mode.POSE or not self._w.isVisible():   # Dm4-12/45
            self.snap(target)
            return
        if self._anim is None:                               # lazy (Dm4-2)
            self._anim = QVariantAnimation(self._w)
            self._anim.setEasingCurve(self._curve)
            self._anim.valueChanged.connect(self._tick)
        else:
            self._anim.stop()
        self._anim.setStartValue(self._v)
        self._anim.setEndValue(target)
        self._anim.setDuration(max(1, round(self._ms * abs(target - self._v))))
        self._anim.setCurrentTime(0)
        self._anim.start()

    def snap(self, v: float) -> None:
        if self._anim is not None:
            self._anim.stop()
        self._v = 1.0 if v >= 1.0 else 0.0 if v <= 0.0 else v
        self._w.update()

    def _tick(self, value) -> None:
        self._v = float(value)
        self._w.update()
