# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""The fill of a Jewel Lamp (V2) cell on the vector South Indian chart (SPEC-RST-001 D-31).

Lorris's choice of 2026-10-14: the standard finish keeps the V1 South Indian colour as the
V2 fill (the retinue cells: ``retinue_strength.lamp_fill`` of the lit source's ``q``; the
sign squares: the V1 square colour, ``sign_strength.sign_lamp`` with the square's own
text inks), with the cut and the light on top and the ink judged on that fill. Wood keeps
its V2 fill (the Morning Prism curve on the stain)."""
from apps.widgets.jewel_lamp_display import colour_transform
from core import jewel_lamp as jl, jewel_star as jstar
from core import retinue_strength as rs
from core import sign_strength as ss
from ui.qt_theme import desat_hex


def cell_look(pass_, base, parts, q, wood_rec):
    """A retinue cell's V2 look; the standard fill is the V1 colour (D-31), wood keeps its curve."""
    opts = pass_.snap.options
    fill = None if wood_rec else rs.lamp_fill(base, q, opts.A, pass_.card)
    return jl.look(base, parts, pass_.light, fill=fill, transform=colour_transform(), **jstar.kw(pass_.snap))


def card_look(frame, base, parts, sign, lord):
    """A sign square's V2 look; the standard fill is the V1 square colour (D-31)."""
    from apps.widgets.south_indian_strength import _ink
    opts, fill = frame.snap.options, None
    if not frame.wood:
        inks = [_ink(item) for item in frame.texts.get(sign, ())]
        fill = ss.sign_lamp(base, frame.snap.q.get(lord, 0.0), opts.A, frame.ground, inks, desat_hex).fill
    return jl.look(base, parts, frame.light, fill=fill, transform=colour_transform(), **jstar.kw(frame.snap))
