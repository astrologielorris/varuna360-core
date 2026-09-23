"""SPEC-BAR-001 M2 — the d0-d5 density ladder table (design: 12_opus_m2_ladder.md §1).

ONE source of truth for what every control shows at every tier: label-variant
lists (full / lb-min / lb-tiny, aligned by index so a logical label maps to
its short form), per-tier display mode, and per-tier padding. The
ActionBarLayoutController reads this for both required(d) arithmetic and
apply(d); nothing else may hardcode a tier behavior.

Traps this table encodes (all measured in the mockup, doc §1.2/§6):
- TRANSIT has NO lb-min: it keeps its full grid-stacked swap at d1 (V-1).
- NOW/ADD live in `.lb4`, not `.lb`: their labels drop at d4, not d2 (V-2).
- lb-tiny exists ONLY on the three zodiac segments and renders at d4 only.
- NOW and SIDEREAL have lb-min identical to lb-full (d0->d1 no-op for them).
- Padding is per (tier, group), not per "icon-only": left group collapses to
  9px at d2+ (:448), right icoable at d4+ (:454) — zodiac keeps its TINY
  label at d4 yet already pads 9 (V-9).
- classic carries the D-5 dual-role "SIDEREAL" variant set (D-22b): INV-1
  fixes each tier box over ALL variants of that tier, dual role included.
- The `*` alternate-names state NEVER enters a variant set (D-22c).
- The overflow capsule pad is a LITERAL 8px, not 8*fs (D-22d, second D-4
  exception; goldens measure 16 + 13*fs).

Modes: "full" | "min" | "tiny" (label from that list) | "icon" (no label,
icon centred) | "gone" (not in the layout — folded into the overflow menu
at d3+ for the .lvl3 controls).
"""
from __future__ import annotations

from dataclasses import dataclass

FULL, MIN, TINY, ICON, GONE = "full", "min", "tiny", "icon", "gone"
N_TIERS = 6


@dataclass(frozen=True)
class LadderRow:
    key: str
    full: tuple[str, ...]
    mins: tuple[str, ...] | None          # None = control never shortens
    tinys: tuple[str, ...] | None
    modes: tuple[str, ...]                # len 6, d0..d5
    pads: tuple[float | None, ...]        # CSS px to scale by fs; None=default

    def __post_init__(self):
        assert len(self.modes) == N_TIERS and len(self.pads) == N_TIERS
        if self.mins is not None:
            assert len(self.mins) == len(self.full)
        if self.tinys is not None:
            assert len(self.tinys) == len(self.full)

    def labels_at(self, d: int) -> tuple[str, ...]:
        """The variant list whose max advance sizes the box at tier d
        (empty for icon-only / gone)."""
        m = self.modes[d]
        if m == FULL:
            return self.full
        if m == MIN:
            return self.mins if self.mins is not None else self.full
        if m == TINY:
            return self.tinys if self.tinys is not None else self.full
        return ()

    def display_at(self, logical: str, d: int) -> str:
        """Map the logical (full-form) label onto tier d's displayed text."""
        labels = self.labels_at(d)
        if not labels:
            return ""
        try:
            return labels[self.full.index(logical)]
        except ValueError:
            # td-m31b9: an unmeasured logical label paints BLANK, never another
            # view's name — the old labels[0] fallback silently showed a sibling
            # (a Body stop reading "NORTH"). A blank is an obvious gap; a wrong
            # name is a silent lie. Add the logical to `full` to give it a variant.
            return ""

    def visible_at(self, d: int) -> bool:
        return self.modes[d] != GONE


# ---- the table (doc §1.2/§1.3; measured boxes quoted there) ---------------

_L10 = (10.0, 10.0, 9.0, 9.0, 9.0, 9.0)         # left group :448
_R10 = (10.0, 10.0, 10.0, 10.0, 9.0, 9.0)       # right icoable :454
_ZOD = (7.0, 7.0, 7.0, 7.0, 9.0, 9.0)           # C8: tighter pills (Lorris)
_LVL3 = (10.0, 10.0, 10.0, None, None, None)    # folded at d3

LADDER: dict[str, LadderRow] = {r.key: r for r in (
    LadderRow("transit", ("TRANSIT", "OVERLAY"), None, None,
              (FULL, FULL, ICON, ICON, ICON, ICON), _L10),
    # D-23(d) (was Dm3-10): the view cycler now has FOUR views and the label
    # names the NEXT one (WHEEL/SOUTH/NORTH/BODY); CARDS LEFT the cycler for
    # its own button, so this row DROPS the "CARDS"/"C" variant. The widest min
    # letter is unchanged — "W" still dominates (W > C), so the d1 north box is
    # identical to the five-variant box; only the now-removed "C" is gone (the
    # D-22(j) re-measure: dropping C moves nothing because W already sized it).
    # td-m31b9: the F2 ring gained NAKSHATRA (index 6), pushed here via
    # set_base_label; without a variant, display_at() fell to labels[0] and the
    # stop painted "NORTH" — a sibling view's name, not blank. NAKSHATRA
    # abbreviates to "K" (N/S/E/W/B already taken). NAKSHATRA is now the widest
    # FULL variant (was WHEEL), so the d0 north box grows to fit it; the MIN box
    # is unchanged ("W" still dominates "K"), so no other label shrinks.
    LadderRow("north",
              ("NORTH", "SOUTH", "EAST", "WHEEL", "BODY", "NAKSHATRA"),
              ("N", "S", "E", "W", "B", "K"), None,
              (FULL, MIN, ICON, ICON, ICON, ICON), _L10),
    # D-23(d): CARDS is its own view-segment cell. lb-full and lb-min are BOTH
    # "CARDS" (it never abbreviates to a letter); FULL through d1, icon-only at
    # d2 with the rest of the left group.
    LadderRow("cards", ("CARDS",), ("CARDS",), None,
              (FULL, FULL, ICON, ICON, ICON, ICON), _L10),
    LadderRow("kala", ("OPEN IN KALA",), ("KALA",), None,
              (FULL, MIN, ICON, ICON, ICON, ICON), _L10),
    LadderRow("info", ("CHART INFO",), ("INFO",), None,
              (FULL, MIN, ICON, ICON, ICON, ICON), _L10),
    LadderRow("now", ("NOW",), ("NOW",), None,
              (FULL, MIN, MIN, MIN, ICON, ICON), _R10),
    LadderRow("add", ("ADD CHART",), ("ADD",), None,
              (FULL, MIN, MIN, MIN, ICON, ICON), _R10),
    LadderRow("birth", ("BIRTH TIME ±",), ("TIME ±",), None,
              (FULL, MIN, MIN, GONE, GONE, GONE), _LVL3),
    # C7: HD moved into the LEFT group next to CARDS and became a 3-state cycle
    # (bodygraph page / -88 Design chart / wheel), so its caption switches between
    # "HUMAN DESIGN" and "DESIGN CHART". BOTH captions (and both short forms) live
    # in the row so the fixed box (INV-1) is sized over every variant and
    # display_at can map either logical label. Left-group profile like kala/info:
    # FULL, MIN, then icon-only — it never folds GONE (it is no longer in the
    # fold-at-d3 toggles cluster).
    LadderRow("hd", ("HUMAN DESIGN", "DESIGN CHART"), ("HD", "DES"), None,
              (FULL, MIN, ICON, ICON, ICON, ICON), _L10),
    LadderRow("aditya", ("ADITYA CIRCLE",), ("ADITYA",), ("ADI",),
              (FULL, MIN, MIN, MIN, TINY, ICON), _ZOD),
    LadderRow("classic", ("TROPICAL CLASSIC",), ("CLASSIC",), ("TRO",),
              (FULL, MIN, MIN, MIN, TINY, ICON), _ZOD),
    LadderRow("sidereal", ("SIDEREAL",), ("SIDEREAL",), ("SID",),
              (FULL, MIN, MIN, MIN, TINY, ICON), _ZOD),
    # Dm3-23: the modifier's label follows the mode (+ TROPICAL in aditya,
    # + ADITYA otherwise). Measured: the second variant moves the box 0px at
    # every fs and tier — no golden change.
    LadderRow("dual", ("+ TROPICAL", "+ ADITYA"), ("+ TRP", "+ ADI"), None,
              (FULL, MIN, MIN, GONE, GONE, GONE), _LVL3),
)}

# D-5 dual role (D-22b): when the Sidereal SEGMENT is app-hidden (HD button
# visible), the classic segment can DISPLAY "Sidereal"; its box must then
# cover these extra variants per tier mode (INV-1 within the config). The
# controller toggles them with the sidereal app_visible flag — in hdhid the
# real segment exists, the dual role never fires, and the box stays the
# mockup's (the goldens show plain CLASSIC there).
DUAL_ROLE_EXTRAS = {FULL: ("SIDEREAL",), MIN: ("SIDEREAL",), TINY: ("SID",)}

# The overflow capsule is not a LadderRow (no labels, literal pad — D-22d):
OVERFLOW_VISIBLE_FROM = 3                        # .ovf at d3+ (:421-422)
OVERFLOW_PAD_PX = 8.0                            # literal, NOT *fs (D-22d)

# Structural per-tier facts the controller applies (doc §1.2 bottom rows):
TOGGLES_CLUSTER_GONE_FROM = 3                    # .lvl3 + .sep.s3 (:449-450)
MODSPLIT_GONE_FROM = 3                           # :451
TRAY_GAP_ZERO_FROM = 3                           # :452 (cosmetically inert)
META_HIDDEN_FROM = 1                             # .title .meta (:446)
