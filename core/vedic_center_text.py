# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""The texts of the Vedic center drawing (SPEC-VAC-001 §3.5, §4.6; D-9), Qt-free.

Tooltips of the studs, lenses and Y beads, and the pieces the tour caption and the matrix
cell tooltips are made of, all through ``core.i18n.t`` with English defaults in the
``center_drawing`` catalog. Body names come from the model; sign names from the caller's
``sign_name(index)`` (frame-aware ``displayed_sign_name``). A cast is a direction and a
strength only: no aspect kind (INV-11).
"""
from __future__ import annotations

import math
from typing import Callable, Mapping

from core import vedic_center as vc
from core.center_geometry import Body
from core.i18n import t
from core.planet_label import degree_text

def _degree(longitude: float) -> str:          # the chart labels' degree (W6 R5)
    return degree_text(longitude - 30.0 * math.floor(longitude / 30.0))


def stud_tooltip(body: Body, sign_name: Callable[[int], str],
                 bodies: Mapping[str, Body]) -> str:
    """"Saturn · Parjanya 1°44' · casts" (a node: "· receives only"); a cluster lists all."""
    lines = []
    for name in (body.name,) + tuple(body.cluster):
        b = bodies[name]
        sign, degree = sign_name(int(b.longitude // 30) % 12), _degree(b.longitude)
        if b.pewter:
            lines.append(t("center_drawing.vedic.stud_receives",
                           "{body} · {sign} {degree} · receives only", body=name, sign=sign,
                           degree=degree))
        else:
            lines.append(t("center_drawing.vedic.stud_casts", "{body} · {sign} {degree} · casts",
                           body=name, sign=sign, degree=degree))
    return "\n".join(lines)


def cast_title(cast: vc.Cast) -> str:
    return t("center_drawing.vedic.cast_title", "{caster} casts on {receiver}",
             caster=cast.caster, receiver=cast.receiver)


def cast_detail(cast: vc.Cast) -> str:
    """"56.6 virupas · strong · special aspect (3rd house)"."""
    parts = [t("center_drawing.vedic.virupas", "{value} virupas", value=f"{cast.virupas:.1f}")]
    if cast.strong:
        parts.append(t("center_drawing.vedic.strong", "strong"))
    if cast.special:
        parts.append(t("center_drawing.vedic.special", "special aspect ({house})",
                       house=cast.special))
    return " · ".join(parts)


def cast_back(cast: vc.Cast) -> str:
    """What the receiver casts back: a value, nothing, or "receives only" (a node)."""
    if cast.back is None:
        return t("center_drawing.vedic.receives_only", "{body} receives only", body=cast.receiver)
    if cast.back <= 0:
        return t("center_drawing.vedic.nothing_back", "{body} casts nothing back",
                 body=cast.receiver)
    return t("center_drawing.vedic.back", "{body} casts {value} back", body=cast.receiver,
             value=f"{cast.back:.1f}")


def lens_tooltip(cast: vc.Cast) -> str:
    return "\n".join((cast_title(cast), cast_detail(cast), cast_back(cast)))


def yuti_title(yuti: vc.Yuti, sign_name: Callable[[int], str]) -> str:
    return t("center_drawing.vedic.yuti_title", "{a} and {b} together in {sign}",
             a=yuti.a, b=yuti.b, sign=sign_name(yuti.sign_index))


def yuti_detail() -> str:
    return t("center_drawing.vedic.yuti_detail", "Yuti · same sign, no virupa value")


def bead_tooltip(yuti: vc.Yuti, sign_name: Callable[[int], str]) -> str:
    return "\n".join((yuti_title(yuti, sign_name), yuti_detail()))
