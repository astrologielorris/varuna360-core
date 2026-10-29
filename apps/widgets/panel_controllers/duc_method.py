# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The DUC Bala method for the app's own panels (SPEC-STR-001 §7.5).

``current_duc_method`` reads the ``strength.duc_method`` setting from the app's
settings manager (the value the live frame publishes, so a panel and the AI
tools answer alike). Every surface that shows a DUC value listens to the key
through ``on_duc_method_changed``: a write from the Settings page Apply, the
remote ``set_setting`` command or the in-app AI request service all end in
``SettingsManager._notify_change``, so one subscription covers every path.

- ``subscribe_duc_method``: a panel controller refreshes through its own
  coalesced, visibility-gated chart refresh;
- ``subscribe_chart_redraw``: the chart views (retinue strength colours, Jewel
  Lamp, planet glow) redraw with the strength Apply tail when the lit strength
  source is DUC (no other source reads DUC Bala);
- the fullscreen Avastha page, the folded-panel summary chips and the sign
  popups follow it too (popups through apps/widgets/sector_popup_follow.py).
"""
from core.bala_calculator import DUC_METHOD_KEY, duc_method_from


def current_duc_method() -> str:
    """The saved DUC Bala method ("equal" or "wilhelm")."""
    from managers.settings_manager import get_settings
    return duc_method_from(get_settings().get)


def on_duc_method_changed(owner, callback, until=None):
    """Call ``callback()`` after each change of the EFFECTIVE DUC method,
    coalesced to one call per event-loop pass, for as long as the QObject
    ``owner`` lives (and, with ``until``, a signal such as a dialog's
    ``finished``, until it fires). A write of the value already in force (an
    unrelated Settings Apply writes every row) is inert. Returns the
    unsubscribe function (idempotent)."""
    from PySide6.QtCore import QTimer
    from managers.settings_manager import get_settings
    settings = get_settings()
    pending, last = [False], [duc_method_from(settings.get)]

    def _alive():
        try:
            import shiboken6
            return shiboken6.isValid(owner)
        except (ImportError, TypeError):
            return True                   # not a Qt object: lives as long as Python holds it

    def _run():
        pending[0] = False
        if not _alive():
            return
        try:
            callback()
        except RuntimeError:          # the owner's widgets are gone
            pass

    def _drop(*_a):
        settings.remove_on_changed(DUC_METHOD_KEY, _changed)

    def _changed(_key, _value):
        if not _alive():              # destroyed without the signal reaching us
            _drop()
            return
        method = duc_method_from(settings.get)
        if method == last[0]:
            return
        last[0] = method
        if not pending[0]:
            pending[0] = True
            QTimer.singleShot(0, _run)

    settings.on_changed(DUC_METHOD_KEY, _changed)
    for signal in (getattr(owner, "destroyed", None), until):
        if signal is not None:
            try:
                signal.connect(_drop)
            except (RuntimeError, TypeError):
                pass
    return _drop


def subscribe_duc_method(controller, gui) -> None:
    """Refresh ``controller`` (a PanelControllerBase) on a DUC method change:
    the chart bucket (hidden -> pending until shown; shown -> one refresh per
    event-loop pass, state.panel_mixin)."""
    on_duc_method_changed(gui, lambda: controller._dispatch_state_change("active_chart"))


def duc_lit(get) -> bool:
    """True when a chart view colours by DUC Bala: the retinue strength display
    is on with the DUC source (the PLANET glow and the Jewel Lamp ``q`` read the
    same source)."""
    from core.retinue_strength import StrengthOptions
    options = StrengthOptions.from_settings(get)
    return bool(options.enabled and options.source == "duc")


def redraw_chart_hosts(gui) -> int:
    """The strength Apply tail's redraw (every South Indian host, embedded
    wheel / North Indian host and the main wheel; drawn now when on screen,
    else at its next show). Returns the views drawn now."""
    from managers.retinue_strength_shortcut import redraw_strength_hosts
    return redraw_strength_hosts(getattr(gui, "wheel_view", None))


def subscribe_chart_redraw(gui) -> None:
    """Redraw the chart views on a DUC method change while they colour by DUC."""
    from managers.settings_manager import get_settings

    def _redraw():
        if duc_lit(get_settings().get):
            redraw_chart_hosts(gui)
    on_duc_method_changed(gui, _redraw)


def follow_panel_dialog(dialog, gui, section_key) -> None:
    """An open fullscreen Strength dialog (InfoPanelDialog) follows a DUC method
    change: its pages are clones, so the source table is refreshed (a folded
    panel's controllers are held) and the dialog rebuilt on its page, as at
    open. Ends when the dialog closes (``finished``). The Avastha page of the
    aspects dialog follows by itself while shown (avastha_fullscreen)."""
    if section_key != "strength":
        return

    def _rebuild():
        if not dialog.isVisible():
            return
        ctrl = getattr(gui, "strength_controller", None)
        if ctrl is not None:
            ctrl._refresh()               # the clone's source (DUC BALA column)
        dialog.refresh_theme()
    on_duc_method_changed(dialog, _rebuild, until=getattr(dialog, "finished", None))


DUC_TIPS = {
    "equal": "Combined strength: (Digbala + Uccha + Chesta) / 3",
    "wilhelm": ("Combined strength, Ernst Wilhelm method: Ishta = (Uccha + Chesta) / 2, "
                "then (Ishta + Digbala) / 2. Digbala counts double, not one third."),
}


def apply_duc_tooltip(table) -> None:
    """The DUC BALA column header tooltip names the formula in force."""
    item = table.horizontalHeaderItem(4)
    if item:
        item.setToolTip(DUC_TIPS[current_duc_method()])


def follow_duc_tooltip(table) -> None:
    """Set the DUC BALA header tooltip now and after each method change."""
    apply_duc_tooltip(table)
    on_duc_method_changed(table, lambda: apply_duc_tooltip(table))
