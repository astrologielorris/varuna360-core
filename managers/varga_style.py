# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The varga style, ONE state for the varga column, the VARGA panel, the chart
and render_chart (SPEC-DIG-001 §4.3, td-m6xyo).

The state is the setting ``chart.varga_style`` (classical / parivritti /
reversed); this controller is its only GUI writer (the VARGA panel's style
button) and follows every other writer through a keyed subscription:

- the left varga column relabels in place (2p 3p 4p under Parivritti, 10R 24R
  under Reversed, plain numbers under Classical; 16 buttons, the 10R / 24R
  buttons folded into 10 and 24) and keeps its checked button;
- when the shown varga is one the old or the new style touches, the chart
  switches to the styled varga through ``ChartGUI._switch_varga`` (the one
  dispatch + paint path; it applies the style to a plain number itself);
- the VARGA panel (chips, header) and the full dignity table follow.

The panel's VIEW (one varga / All vargas) is a second setting,
``chart.varga_panel_view`` (SPEC-DIG-001 D-10): the header swap button is a
plain 4-step cycle, Classical -> Parivritti -> Reversed -> All vargas ->
Classical (one-varga view); in All vargas the bottom style key cycles the
style (Classical -> Parivritti -> Reversed).

No ChartGUI attribute (Rule 4b): the controller is owned by the VARGA panel.
"""
from __future__ import annotations

from core import varga_codes as vc
from core.i18n import t

KEY = vc.VARGA_STYLE_KEY
# Non-empty while resolve_switch writes the style for an explicit styled code:
# the style subscription (VargaStyleController.apply) must not switch the chart
# itself then, the switch in progress draws it (R1 review F5: 2 paints -> 1).
_SWITCHING = []


VIEW_KEY = vc.VARGA_VIEW_KEY


def _getter(get):
    if get is None:
        from managers.settings_manager import get_settings
        get = get_settings().get
    return get


def current_style(get=None) -> str:
    """The stored style, a known key (anything else reads Classical)."""
    from core import settings_registry as registry
    style = _getter(get)(KEY, registry.default(KEY))
    return style if style in vc.VARGA_STYLE_ORDER else "classical"


def table_view(get=None) -> bool:
    """True when the VARGA panel shows All vargas (the table)."""
    from core import settings_registry as registry
    return _getter(get)(VIEW_KEY, registry.default(VIEW_KEY)) == vc.VARGA_TABLE


def styled_for_app(varga_number, get=None):
    """``ChartGUI._switch_varga``'s rule: a plain column number becomes the
    varga the current style draws (10 + Reversed = 1010); an explicit styled
    code (1010, 202) is kept."""
    return vc.styled_gui_varga(varga_number, current_style(get))


def resolve_switch(varga_number, settings=None):
    """The varga ``_switch_varga`` draws, the style kept in agreement with it: a
    plain number takes the current style; an explicit styled code (1010 from the
    remote, a chart memory restore) makes its style the current one, so the
    column, the panel and the chart never disagree with ``chart.varga_style``."""
    if settings is None:
        from managers.settings_manager import get_settings
        settings = get_settings()
    own = vc.style_of_gui_varga(varga_number)
    if own is not None and own != current_style(settings.get) and not settings.is_locked(KEY):
        _SWITCHING.append(varga_number)
        try:
            settings.persist_runtime_change(KEY, own)    # the panel's subscription relabels
        finally:
            _SWITCHING.pop()
        return varga_number
    if own is not None and own != current_style(settings.get):
        return vc.base_gui_varga(varga_number)       # style locked: the plain varga
    return styled_for_app(varga_number, settings.get)


class VargaStyleController:
    """Cycles the style and keeps the column, the chart and the panel in step.
    ``on_change(switched)``: the style or the view changed; ``switched`` is True
    when the chart was switched to another varga for it (that varga change
    refreshes the window's panels on its own)."""

    def __init__(self, gui, on_change=None, settings=None):
        if settings is None:
            from managers.settings_manager import get_settings
            settings = get_settings()
        self._gui = gui
        self._settings = settings
        self._on_change = on_change
        self._last = current_style(settings.get)
        self._subscribed = False

    @property
    def style(self) -> str:
        """The stored drawing style (also while the table is shown)."""
        return current_style(self._settings.get)

    @property
    def table(self) -> bool:
        """The panel shows All vargas."""
        return table_view(self._settings.get)

    def subscribe(self, owner):
        """Follow every writer of the setting while ``owner`` (a QObject) lives."""
        if self._subscribed:
            return
        me = self

        def _changed(_key, _value):
            me.apply()

        def _view(_key, _value):
            if me._on_change is not None:
                me._on_change(False)

        self._settings.on_changed(KEY, _changed)
        self._settings.on_changed(VIEW_KEY, _view)
        self._subscribed = True

        def _drop(*_):
            self._settings.remove_on_changed(KEY, _changed)
            self._settings.remove_on_changed(VIEW_KEY, _view)
        owner.destroyed.connect(_drop)

    def _write(self, key, value):
        if self._settings.is_locked(key):
            return None
        self._settings.persist_runtime_change(key, value)
        if not self._subscribed:          # the subscription already applied it
            self.apply()
        return value

    def cycle(self):
        """The header swap button, a plain 4-step cycle: Classical ->
        Parivritti -> Reversed -> All vargas (the view, style kept) ->
        Classical in the one-varga view."""
        if self.table:
            if self._settings.is_locked(VIEW_KEY):
                return None
            if self.style != "classical":
                self._write(KEY, "classical")
            return self._write(VIEW_KEY, "list")
        if self.style == vc.VARGA_STYLE_ORDER[-1]:
            return self._write(VIEW_KEY, vc.VARGA_TABLE)
        return self.cycle_style()

    def cycle_style(self):
        """Classical -> Parivritti -> Reversed -> Classical (the All vargas
        view's style key)."""
        return self._write(KEY, vc.next_varga_style(self.style))

    def apply(self):
        """Relabel the column, redraw the styled varga when the shown one is
        touched, then the panel."""
        style, old = self.style, self._last
        self._last = style
        self.relabel_column(style)
        state = getattr(self._gui, "state", None)
        shown = getattr(state, "current_varga", 1) or 1
        base = vc.base_gui_varga(shown)
        target = vc.styled_gui_varga(base, style)
        touched = vc.style_touches(base, style) or vc.style_touches(base, old) or shown != base
        switched = False
        if (touched and target != shown and not _SWITCHING
                and getattr(state, "active_chart", None) is not None):
            switch = getattr(self._gui, "_switch_varga", None)
            if callable(switch):
                switch(target)
                switched = True
        if self._on_change is not None:
            self._on_change(switched)

    def relabel_column(self, style=None):
        """The column shows the style's labels (16 buttons, one per base number)."""
        style = style or self.style
        buttons = getattr(self._gui, "varga_buttons", None) or {}
        for base, btn in buttons.items():
            if base not in vc.COLUMN_VARGAS:
                continue
            code = vc.styled_gui_varga(base, style)
            btn.setText(vc.column_label(base, style))
            btn.setToolTip(f"{vc.gui_varga_code_label(code)} ({vc.get_varga_name(code)})")
        # the View > Varga Charts menu draws the same styled varga: same names
        for base, action in (getattr(self._gui, "varga_actions", None) or {}).items():
            if base in vc.COLUMN_VARGAS:
                code = vc.styled_gui_varga(base, style)
                name = vc.get_varga_name(code)
                action.setText(t("menu.view.varga.action", "D-{label} ({name})",
                                 label=vc.column_label(base, style), name=name))
                action.setStatusTip(t("menu.view.varga.tip", "Show {name} ({code}) chart",
                                      name=name, code=vc.gui_varga_code_label(code)))
