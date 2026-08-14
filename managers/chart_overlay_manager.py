# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""ChartOverlayManager — resolve a dropped payload into an overlay chart (SPEC-TRN-006).

The single place that knows how a drag-and-drop payload (a memory entry id, or an
external .chtk/.toml file) becomes a built Chart handed to
TransitOverlayManager.overlay_chart(). Keeps chart-construction knowledge out of
the transit manager (which only knows the live-sky path) and out of the drop
widget (Rule 4 delegation).

Also owns the two clear transitions and the mode/house-system rebuild, so every
overlay lifecycle event runs through one owner.
"""

import copy


class ChartOverlayManager:
    """Turns drop payloads into overlay charts and owns overlay teardown."""

    def __init__(self, gui):
        self._gui = gui

    # --- entry points --------------------------------------------------------
    def handle_drop(self, mime):
        """Dispatch a dropped QMimeData by payload kind. Always reports outcome."""
        from apps.widgets.chart_memory_button import CHART_ENTRY_MIME
        from apps.widgets.chart_drop_common import chart_file_urls

        if self._gui.state.active_chart is None:
            self._status("Load a chart first, then drop one to overlay it.")
            return False

        if mime.hasFormat(CHART_ENTRY_MIME):
            entry_id = bytes(mime.data(CHART_ENTRY_MIME)).decode("utf-8")
            return self.overlay_from_memory_id(entry_id)

        files = chart_file_urls(mime)
        if files:
            if len(files) > 1:
                self._status(
                    f"Overlay uses one chart: {files[0].name}. "
                    f"{len(files)} files dropped, first one used.")
            return self.overlay_from_file(str(files[0]))

        self._status("Nothing to overlay from that drop.")
        return False

    def overlay_from_memory_id(self, entry_id):
        """Build a chart from a memory entry (by id) and overlay it."""
        if self._gui.state.active_chart is None:
            self._status("Load a chart first, then drop one to overlay it.")
            return False
        entry = self._find_entry(entry_id)
        if entry is None:
            self._status("Could not find that chart in memory.")
            return False
        try:
            chart = self._build_from_entry(entry)
            label = self._entry_label(entry)
        except Exception as e:
            self._status(f"Could not overlay chart: {e}")
            import traceback
            traceback.print_exc()
            return False
        source = {"kind": "memory", "id": entry_id, "path": None}
        return self._apply_overlay(chart, label, source)

    def overlay_from_file(self, path):
        """Build a chart from a .chtk/.toml file (non-activating) and overlay it."""
        from pathlib import Path
        if self._gui.state.active_chart is None:
            self._status("Load a chart first, then drop one to overlay it.")
            return False
        try:
            chart, birth_data = self._gui.chart_manager.build_chart_from_file(path)
            label = birth_data.get("name") or Path(path).stem
        except Exception as e:
            self._status(f"Could not overlay {Path(path).name}: {e}")
            import traceback
            traceback.print_exc()
            return False
        source = {"kind": "file", "id": None, "path": str(path)}
        return self._apply_overlay(chart, label, source)

    def reoverlay_current(self):
        """Rebuild the current overlay in the active chart's current frame.

        Called when the zodiac mode or house system changes under an overlay.
        Falls back to clearing (with a message) if the source is unresolvable.
        """
        mgr = self._gui.transit_overlay_manager
        source = mgr.overlay_source
        if not source:
            mgr.clear_overlay_chart()
            self._status("Overlay cleared (could not rebuild in the new frame).")
            return False
        if source.get("kind") == "memory":
            ok = self.overlay_from_memory_id(source.get("id"))
        elif source.get("kind") == "file":
            ok = self.overlay_from_file(source.get("path"))
        else:
            ok = False
        if not ok:
            mgr.clear_overlay_chart()
            self._status("Overlay cleared (could not rebuild in the new frame).")
        return ok

    def clear(self):
        """Clear the overlay and turn the rim OFF (chip x -> off)."""
        self._gui.transit_overlay_manager.clear_overlay_chart()
        self._persist_transit(False)

    def back_to_live_sky(self):
        """Clear the overlay but keep the rim ON, back on live sky."""
        self._gui.transit_overlay_manager.clear_overlay_to_live_sky()
        self._persist_transit(
            self._gui.transit_overlay_manager.transit_enabled)

    # --- internals -----------------------------------------------------------
    def _apply_overlay(self, chart, label, source):
        ok = self._gui.transit_overlay_manager.overlay_chart(
            chart, label=label, source=source)
        if not ok:
            self._status(f"Could not overlay {label}.")
            return False
        # SPEC-TRN-006 B-8: an overlay is session-transient; never persist it as a
        # live-sky rim to restore at next boot.
        self._persist_transit(False)
        self._status(f"Overlay: {label}")
        return True

    def _find_entry(self, entry_id):
        panel = getattr(self._gui, "memory_panel_instance", None) \
            or getattr(self._gui, "memory_panel", None)
        if panel is None:
            return None
        for entry in getattr(panel, "charts", []):
            if entry.get("id") == entry_id:
                return entry
        return None

    def _build_from_entry(self, entry):
        """Build from a COPY of the recipe so the persisted memory row is never
        mutated (SPEC-TRN-006 B-9: get_or_build_chart writes house_system into the
        entry recipe and pollutes its cache, a two-instance conflict hazard)."""
        from core.chart_factory import build_chart_from_recipe
        recipe = copy.deepcopy(entry["recipe"])
        recipe["house_system"] = self._gui.state.house_system
        return build_chart_from_recipe(
            recipe,
            self._gui.state.aditya_mode,
            getattr(self._gui, "chart_sidereal_ayanamsa_id", 100),
        )

    def _entry_label(self, entry):
        recipe = entry.get("recipe") or {}
        return recipe.get("name") or "chart"

    def _persist_transit(self, value):
        try:
            from managers.settings_manager import get_settings
            get_settings().set("chart.show_transit_overlay", bool(value))
        except Exception:
            pass

    def _status(self, message):
        try:
            self._gui.statusBar().showMessage(message, 5000)
        except Exception:
            pass
