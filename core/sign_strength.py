# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Sign-lord strength on the 12 main sign cells (SPEC-RST-001 D-12..D-15, td-w6xja).

Qt-free. Two follow-up preferences beside the four retinue strength keys, and
the lamplight of a MAIN sign cell: the same formulas as a retinue cell
(``core.retinue_strength``), driven by the sign lord's ``q``, but the existing
labels never change colour: each pull is held back instead until every ink
on the cell keeps ``min(4.5, .75 x today's contrast)``. Maths on RAW hex; the caller
passes its ``desat`` so the contrast is judged on the colours actually painted.
"""
from __future__ import annotations

from typing import Callable, Iterable, NamedTuple, Optional, Tuple

from core import retinue_strength as rs
from core.sign_lamp_limits import KEEP, _limits, _stain_opacity, fill_fg  # noqa: F401 (KEEP)

KEY_SIGN_COLOUR = "chart.retinue_strength_sign_colour"
KEY_RIBBON_STYLE = "chart.retinue_strength_ribbon_style"
STYLES = ("fine", "full")


class SignOptions(NamedTuple):
    """The two follow-up preferences (read only when the feature is on)."""
    colour: bool = False
    style: str = "fine"

    @classmethod
    def from_settings(cls, get: Callable) -> "SignOptions":
        style = get(KEY_RIBBON_STYLE, "fine")
        return cls(bool(get(KEY_SIGN_COLOUR, False)), style if style in STYLES else "fine")


SIGN_OFF = SignOptions()


class SignLamp(NamedTuple):
    fill: str                 # raw hex (standard) or the unchanged stain (wood)
    opacity: Optional[float]  # wood stain opacity, None for standard
    glow: str
    glow_alpha: float         # contrast-capped
    shadow: str
    shadow_alpha: float       # contrast-capped
    held: bool                # True when a pull was held back for the labels


Ink = Tuple[str, float]       # (desaturated text colour, its alpha)



def sign_lamp(base: str, q: float, A: float, card: str, inks: Iterable[Ink],
              desat: Callable[[str], str] = lambda h: h, wood_o: Optional[float] = None,
              glow_cap: float = .75, memo: Optional[dict] = None, bright=False) -> SignLamp:
    """Lamplight of one main sign cell, held back so its labels stay readable.

    ``base`` = the cell's raw element colour (wood: its stain), ``card`` = the
    ground under the cells, ``inks`` = the text colours drawn on the cell.
    Each pull is capped on its own (the weak sink, the strong richness, the rim
    shadow, the glow), so a stronger lord never looks weaker than a weaker one.
    Wood: the weak pull is ``A*max(0, 1-2q)``, so ``strong - weak = A(2q-1)``.
    ``memo``: a plain dict the caller keeps for ONE draw (cells with the same
    colour and labels share their limits); never kept across draws. ``bright`` (the wheel,
    td-9scg9): weak = paler (``rs.bright_fill``), no rim shadow, never darker."""
    wood = wood_o is not None
    key = (base, card, tuple(sorted(set(inks))), A, wood_o, glow_cap, bright)
    limits = memo.get(key) if memo is not None else None
    if limits is None:
        limits = _limits(base, card, key[2], A, desat, wood_o, glow_cap, bright)
        if memo is not None:
            memo[key] = limits
    f_max, g_max, shadow_top, glow_top = limits
    full_f = A * (max(0.0, .5 - q) * 2 if wood or bright else 1 - q)
    full_g = A * max(0.0, q - .5) * 2
    f, g = min(full_f, f_max), min(full_g, g_max)
    shadow_alpha = 0.0 if bright else min(rs.shadow_alpha(q, A, wood), shadow_top)
    glow_alpha = min(rs.glow_alpha(q, A, "sign", glow_cap), glow_top)
    fill = base if wood else fill_fg(base, f, g, card, bright)
    opacity = _stain_opacity(wood_o, g - f) if wood else None
    return SignLamp(fill, opacity, rs.sg.wheel_glow(base, fill, rs.glow_colour("sign", ""), bright, wood), glow_alpha,
                    rs.shadow_colour(card, wood), shadow_alpha, (f, g) != (full_f, full_g))
