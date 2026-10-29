# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Pure display-space evaluation, preserving raw Jewel Lamp paint colours."""


def evaluated(ground, star, transform, displayed_ground, inks):
    """Capture colour evaluation inputs; a composite ground can already be displayed."""
    shown = transform or (lambda value: value)
    ground = shown(ground) if displayed_ground is None else displayed_ground
    if star is not None:
        star = star._replace(stops=tuple((o, shown(c), a) for o, c, a in star.stops),
                             ray_mid=shown(star.ray_mid))
    return ground, star, [(ink, shown(ink)) for ink in inks]


def raw_light(raw, fitted):
    """The fitter scales alphas only; colour and geometry remain raw for paint."""
    if fitted is None:
        return None
    return raw._replace(stops=tuple((o, c, fit[2]) for (o, c, _a), fit in zip(raw.stops, fitted.stops)),
                        ray_alpha=fitted.ray_alpha)
