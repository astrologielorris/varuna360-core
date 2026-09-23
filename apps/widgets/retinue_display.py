# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Explicit retinue capability routing; a SI setter never implies draw_wheel."""

def apply_retinue(view, *, rings=None, ruler=None, redraw=True, defer_hidden=False):
    from apps.widgets.south_indian_vector_view import SouthIndianHostWidget, SouthIndianVectorView
    from apps.widgets.wheel_view import WheelView
    if isinstance(view, (SouthIndianHostWidget, SouthIndianVectorView)):
        if ruler is not None:
            view.set_show_trimsamsha_degrees(ruler)
        if rings is not None:
            view.set_show_retinue_rings(rings, defer_hidden=defer_hidden)
        return view.retinue_state()
    if isinstance(view, WheelView):
        if rings is not None:
            view.set_show_retinue_rings(rings)
        if ruler is not None:
            view.show_trimsamsha_degrees = bool(ruler)
        if redraw:
            if view.isVisible():
                view.draw_wheel()
                view.ensure_visible()
            else:
                view._retinue_dirty = True
        return dict(requested=view.show_retinue_rings, effective=view.show_retinue_rings,
                    suppression_reason=None)
    return dict(effective=False, suppression_reason='Hora + Trimshamsha available in Wheel or vector South Indian view.')


def broadcast_south_indian(*, rings=None, ruler=None):
    from apps.widgets.south_indian_vector_view import _LIVE_HOSTS
    for host in list(_LIVE_HOSTS):
        try:
            if host._retinue_live:
                apply_retinue(host, rings=rings, ruler=ruler, defer_hidden=True)
        except RuntimeError:
            _LIVE_HOSTS.discard(host)
