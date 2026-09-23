"""SPEC-BAR-001 M2 — TierEngine: hysteresis-guarded density-tier selection.

Pure logic, no Qt: the ActionBarLayoutController owns the WIDGETS; this owns
the DECISION. Separated so the oscillation proof is a unit-test property, not
a hope (plan M2-1: ">=16px hysteresis"; pre-mortem 4 wants the table proven
against reality separately from the policy).

Model
-----
Tiers are density levels 0..N-1 (d0 = full, d5 = minimal). Each tier t has a
``fit_width[t]``: the minimum available width at which tier t's content fits.
fit widths are strictly decreasing (denser tier => needs less). The table is
an INPUT — measured from live widget content by the controller (and, in CP-2,
cross-checked against the mockup's own tier flips), so label changes, fs and
the HD swap re-enter through ``set_table``, never through this module.

Policy (asymmetric band)
------------------------
- DEMOTE (get denser) the moment the current tier no longer fits:
  ``width < fit_width[current]``. Pick the least dense tier that fits.
- PROMOTE (get less dense) only with margin: tier u < current is adopted only
  when ``width >= fit_width[u] + hysteresis_px``.
- ``set_table`` (content/fs/HD changed) re-picks the exact fitting tier with
  NO hysteresis: the old anchor is meaningless for new content, and applying
  the margin there would under-promote on boot when the window sits within
  the band of a threshold.

Oscillation proof sketch (test_tier_engine has the sweep): after a demote at
width w (so w < fit_width[old]), promoting back needs
w' >= fit_width[old] + H, i.e. the width must RISE by more than H beyond the
demote point; a monotone sweep or any jitter with amplitude < H can therefore
never flip the tier twice. Within-band widths keep the current tier.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TierEngine:
    fit_widths: list[float] = field(default_factory=list)  # index = tier
    hysteresis_px: float = 16.0
    tier: int = 0
    _last_width: float = 0.0

    def set_table(self, fit_widths: list[float],
                  width: float | None = None) -> int:
        """Install a new fit table (boot, label change, fs, HD swap).
        Widths must be strictly decreasing with tier. Re-evaluates the tier
        WITHOUT hysteresis at ``width`` (or the last seen width)."""
        if any(b >= a for a, b in zip(fit_widths, fit_widths[1:])):
            raise ValueError(f"fit widths must strictly decrease: {fit_widths}")
        self.fit_widths = list(fit_widths)
        if width is not None:
            self._last_width = width
        self.tier = self._least_dense_fitting(self._last_width)
        return self.tier

    def _least_dense_fitting(self, width: float) -> int:
        for t, need in enumerate(self.fit_widths):
            if width >= need:
                return t
        return len(self.fit_widths) - 1        # even d-max may overflow; clamp

    def on_width(self, width: float) -> int:
        """Feed an available width; returns the tier to be in (stable unless
        the band is crossed)."""
        self._last_width = width
        if not self.fit_widths:
            return self.tier
        if width < self.fit_widths[self.tier]:
            # densify: no hysteresis on the way down — overflow is never ok
            self.tier = self._least_dense_fitting(width)
            return self.tier
        # relax: adopt the LEAST dense tier that fits with margin
        for t in range(self.tier):
            if width >= self.fit_widths[t] + self.hysteresis_px:
                self.tier = t
                break
        return self.tier
