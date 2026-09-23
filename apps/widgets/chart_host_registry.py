# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""Live registry for the Wheel / North-Indian views embedded in composed panels
(td-iaqm.5 CP7d).

The main-stack Wheel and North-Indian views are redrawn on a display-settings
Apply by ``_refresh_chart_display`` (via ``_apply_current_varga``), and every
South-Indian host — main, dual-chart, Pro panels — rides the SI live registry
(``sync_all_south_indian_hosts``). The Wheel/North-Indian views embedded in the
composed panels (dual chart, Compatibility comparison, Exploration) had no such
broadcast: they read ``display.sign_display`` at draw time but only redrew on
``showEvent``, so a live flip while the panel stayed visible left them stale.

This mirrors the SI registry for those embedded hosts: a panel registers each
Wheel/NorthIndianView it builds, and ``_on_chart_display_changed`` broadcasts a
``reload_display_settings()`` (which re-reads ``display.sign_display`` and
redraws) to every live host. WeakSet membership means a disposed panel drops out
on its own; a redraw against a deleted C++ object is caught and discarded.
"""
import weakref

_LIVE_CHART_HOSTS = weakref.WeakSet()


def register_chart_host(view):
    """Register an embedded WheelView / NorthIndianView for live sign-display
    broadcasts. Main-stack hosts are refreshed by ``_refresh_chart_display`` and
    must NOT register (they would redraw twice, harmlessly, but the registry is
    for the composed surfaces the main refresh does not reach)."""
    if view is not None:
        _LIVE_CHART_HOSTS.add(view)


def sync_all_chart_hosts():
    """Redraw every registered embedded Wheel/North-Indian host so a live
    ``display.sign_display`` (or any chart-display) change flips it. Called from
    ``_on_chart_display_changed`` — the handler Settings Apply and the remote
    ``set_setting`` path both fire (CP7c/CP7d, Rule 24 harness parity).

    Redraws unconditionally, matching the SI broadcast (sync_all_south_indian_hosts);
    the hidden-wheel redraw is the td-sy9e waste class, tracked as a follow-up to
    give both registries a shared visible-else-flag catch-up (bead filed CP7d).
    One misbehaving host must never abort the Apply handler mid-way — every
    exception is swallowed so the later Apply sections still run; a deleted C++
    object (RuntimeError) is dropped from the registry, a transient failure is
    skipped but the host kept for the next Apply."""
    for view in list(_LIVE_CHART_HOSTS):
        try:
            view.reload_display_settings()
        except RuntimeError:
            # C++ object deleted while the Python wrapper lingered.
            _LIVE_CHART_HOSTS.discard(view)
        except Exception:
            # Any other redraw failure: never break the Apply handler.
            pass
