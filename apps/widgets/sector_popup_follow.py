# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""An open sign popup (SectorInfoDialog) follows the DUC Bala method
(``strength.duc_method``, SPEC-STR-001 §7.5, td-7zu14), whatever wrote it
(Settings Apply, remote ``set_setting``, an AI request): same view and layer,
new numbers; a structure-only popup stays so; it stops when the popup closes.
Kept out of sector_dialog.py: that budget is a down-only ratchet."""
from core.bala_calculator import DUC_METHOD_KEY, duc_method_from


def sector_summaries(chart, aditya_mode, sign_name, ring=None, being_type=None):
    """The five view summaries of one sign, by the saved DUC Bala method."""
    from AI_tools.AI_main_function.avastha_sign import sign_summaries_all_views
    from managers.settings_manager import get_settings
    return sign_summaries_all_views(chart, aditya_mode, sign_name, ring, being_type,
                                    duc_method_from(get_settings().get))


def _replace(dialog, summaries) -> None:
    """Swap in new summaries of the same shape and re-render (same view, layer)."""
    import shiboken6
    if not shiboken6.isValid(dialog):
        return
    old = getattr(dialog, "_summaries", None)
    if old is None or not isinstance(summaries, dict) or set(summaries) != set(old):
        return
    dialog._summaries = summaries
    dialog._render()


def _moved(get, last) -> bool:
    """The effective method moved off ``last[0]`` (remembered); a rewrite is inert."""
    method = duc_method_from(get)
    moved, last[0] = method != last[0], method
    return moved


def follow_duc_method(dialog, recompute) -> None:
    """While ``dialog`` is open, re-render it with ``recompute()`` after each
    change of the effective method, once per event-loop pass. An object
    without the dialog's close signals is not followed."""
    finished, destroyed = (getattr(dialog, n, None) for n in ("finished", "destroyed"))
    if finished is None or destroyed is None:
        return
    from PySide6.QtCore import QTimer
    from managers.settings_manager import get_settings
    settings, pending, last = get_settings(), [False], [None]
    _moved(settings.get, last)

    def _apply():
        pending[0] = False
        try:
            _replace(dialog, recompute())
        except Exception:          # a deleted dialog or a failed calculation
            pass

    def _changed(_key, _value):
        if _moved(settings.get, last) and not pending[0]:
            pending[0] = True
            QTimer.singleShot(0, _apply)

    def _drop(*_a):
        settings.remove_on_changed(DUC_METHOD_KEY, _changed)
    settings.on_changed(DUC_METHOD_KEY, _changed)
    finished.connect(_drop)
    destroyed.connect(_drop)
