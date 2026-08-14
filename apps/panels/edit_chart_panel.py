# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Edit Chart Panel — thin host for the redesigned "New & Edit" tab.

Once a 1200-line widget fusing three sub-tabs (Edit Info / New Chart / Map) with
their save/create/load/map glue, this is now a shell: it mounts one
:class:`~apps.panels.new_edit_workspace.NewEditWorkspace` (the view) and one
:class:`~managers.new_edit_binding.NewEditBinding` (the controller), and forwards
the small public surface the rest of the app and the remote-control layer still
call — ``load_chart_from_memory`` / ``load_from_gui`` / ``current_chart_data`` /
``refresh_theme`` / the ``chart_saved`` / ``chart_modified`` signals / a ``map_tab``
handle / a ``sidebar`` shim. Everything else lives in the binding, where it can
be tested without a screen.

The name and the tab title stay "New & Edit"; the class name stays
``EditChartPanel`` because ``apps/core_gui_qt.py`` imports it by that name.
"""

import logging

from PySide6.QtWidgets import QWidget, QHBoxLayout
from PySide6.QtCore import Signal

from apps.panels.new_edit_workspace import NewEditWorkspace
from managers.new_edit_binding import NewEditBinding
# Re-exported for the map-host tests and any caller that imported them from here
# before the split (the never-snap policy identity, the format-writer dispatch).
from managers.new_edit_binding import _EDIT_CHART_POLICY, _writer_for  # noqa: F401

logger = logging.getLogger(__name__)


class _SidebarShim:
    """A tiny stand-in for the retired navigation sidebar.

    ``apps/core_gui_qt.py`` still calls ``edit_chart_panel.sidebar.setCurrentRow(1)``
    (New) and ``.setCurrentRow(0)`` (Edit) — those are the remote-control
    ``switch_to_new_chart`` / ``switch_to_edit_info`` handlers WI-7 will migrate
    to the mode segment. Until then this maps the two row indices onto the mode
    state machine so nothing breaks. ``currentRow()`` reads back the mode for the
    map-host tests. WI-7 removes both the shim and the call sites together.
    """

    def __init__(self, panel):
        self._panel = panel

    def setCurrentRow(self, row: int):
        # Row 1 was "New Chart", row 0 was "Edit Info"; row 2 was "Map View"
        # (now embedded, no row of its own — treated as a no-op).
        if row == 1:
            self._panel.binding._on_mode_changed("new")
        elif row == 0:
            self._panel.binding._on_mode_changed("edit")

    def currentRow(self) -> int:
        return 1 if self._panel.binding._mode == "new" else 0


class EditChartPanel(QWidget):
    """Thin host mounting the New & Edit workspace + its binding.

    Signals:
        chart_modified(dict): the working form changed (unsaved).
        chart_saved(str): a save/create completed (path if written to file).
    """

    chart_modified = Signal(dict)
    chart_saved = Signal(str)

    def __init__(self, gui):
        super().__init__()
        self.gui = gui

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.workspace = NewEditWorkspace(self)
        # The map reads gui via getattr to reach the loading manager; hand it
        # the real orchestrator so add-ons and reverse-geocode name resolution
        # behave exactly as under the old panel.
        self.workspace.gui = gui
        self.binding = NewEditBinding(self.workspace, gui, host=self)
        layout.addWidget(self.workspace)

        # Image-paste capability: hand the token bar the edition-gated extractor
        # so a pasted chart image can be read into the entry line. Guarded — a
        # no-op until the token bar exposes attach_image_paste (the paste-side
        # snippet), and a no-op in editions where ai_image_extractor returns
        # None (the toggle then shows disabled / Pro-only).
        token_bar = getattr(self.workspace, "token_bar", None)
        if token_bar is not None and hasattr(token_bar, "attach_image_paste"):
            token_bar.attach_image_paste(getattr(gui, "ai_image_extractor", None))

        #: WI-7 bridge — see :class:`_SidebarShim`.
        self.sidebar = _SidebarShim(self)

    # -- public surface the app / remote-control call ------------------------

    @property
    def current_chart_data(self):
        return self.binding.current_chart_data

    @current_chart_data.setter
    def current_chart_data(self, value):
        self.binding.current_chart_data = value

    @property
    def is_modified(self) -> bool:
        return self.binding.is_dirty

    @property
    def map_tab(self):
        """The embedded map component (the map-host tests reach through here)."""
        return self.workspace.map_tab

    @property
    def info_tab(self):
        """WI-7 bridge — the unified form stands in for the old Edit Info sub-tab.

        It carries the same public surface (``collect_data`` / ``set_coordinates``
        / ``set_city`` / ``set_country`` / ``set_timezone`` / ``populate``) AND
        the same field-widget names (``name_input``, ``date_year``, ``local_hour``,
        ``latitude_input``, ``timezone_input``, ``dst_none/yes/war``,
        ``male_radio`` …) that ``pro/remote_control.py`` reaches through. WI-7
        migrates that layer onto the workspace + mode segment and drops this
        bridge (residual gaps then: the old ``info_tab._on_dst_changed`` and
        ``save``'s success channel — WI-7's set_edit_field/save_edit_chart port).
        """
        return self.workspace

    @property
    def new_chart_tab(self):
        """WI-7 bridge — one form serves both roads now (see :attr:`info_tab`)."""
        return self.workspace

    def load_chart_from_memory(self, chart_entry: dict):
        self.binding.load_chart_from_memory(chart_entry)

    def load_from_gui(self):
        self.binding.load_from_gui()

    def get_modified_data(self) -> dict:
        return self.workspace.collect_data()

    def save_changes(self):
        self.binding._on_save_requested()

    def cancel_changes(self):
        self.binding._on_cancel_requested()

    def refresh_theme(self):
        self.binding.refresh_theme()

    def shutdown(self, drain: bool = True):
        """Forward teardown to the binding (which drains the map workers)."""
        self.binding.shutdown(drain=drain)
