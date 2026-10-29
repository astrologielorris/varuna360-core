# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Which chart views of the main window draw at their next show when hidden
(paint on show, ``apps.widgets.paint_on_show``).

The views of the chart stack that a birth-time step or a varga switch redraws,
and both children of each live South Indian host (the main one and the
Body/Aspect one): they still get every chart and setting at once, only their
full draw waits until they are on screen. Cards of Truth (under 1 ms) and the
Human Design page (pushed only when current) are left as they are.
"""
from __future__ import annotations

from apps.widgets.paint_on_show import paint_on_show


def _host_children(host):
    return [v for v in (getattr(host, "classic_view", None), getattr(host, "vector_view", None))
            if v is not None]


def opt_in_chart_views(gui):
    views = [*_host_children(getattr(gui, "chart_view", None)),
             getattr(gui, "wheel_view", None), getattr(gui, "north_indian_view", None)]
    body_aspect = getattr(gui, "body_graph_view", None)
    if body_aspect is not None:
        views += [body_aspect, getattr(body_aspect, "body_graph_view", None),
                  *_host_children(getattr(body_aspect, "aspect_si_host", None))]
    nakshatra = getattr(gui, "nakshatra_core_panel", None)
    views.append(getattr(nakshatra, "wheel_view", None))
    paint_on_show(*(v for v in views if v is not None))
