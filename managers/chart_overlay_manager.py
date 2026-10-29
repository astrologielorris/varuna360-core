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

    def build_from_memory_id(self, entry_id):
        """Build a chart from a memory entry (by id) WITHOUT activating it.

        SPEC-DUAL-001 INV-7 (td-1mgk7): the one memory resolver, shared by the
        overlay and the Chart tab's chart B. Returns ``(chart, label, birth,
        recipe)`` where ``recipe`` is the deep copy the chart was built from
        (chart B keeps it as its immutable snapshot). Raises ``LookupError``
        when the id is not in the memory row and lets build errors propagate.
        """
        entry = self._find_entry(entry_id)
        if entry is None:
            raise LookupError("Could not find that chart in memory.")
        recipe = self._recipe_copy(entry)
        chart = self._build_from_recipe(recipe)
        label = self._entry_label(entry)
        # D-23(b) / F2: the chip's full birth-identity payload comes from
        # the recipe (the built Chart cannot supply the place — its
        # Location.placename holds the person NAME, chart_factory.py).
        from managers.overlay_display import overlay_display_from_recipe
        birth = overlay_display_from_recipe(entry.get("recipe") or {})
        return chart, label, birth, recipe

    def build_from_file(self, path):
        """Build a chart from a .chtk/.toml file WITHOUT activating it.

        SPEC-DUAL-001 INV-7: the one file resolver (``chart_manager.
        build_chart_from_file``, ``canonicalize=False``). Returns ``(chart,
        label, birth, params)`` where ``params`` are the built
        ``jd, lat, lon, name, utcoffset`` (chart B's immutable snapshot).
        Raises on failure.
        """
        from pathlib import Path
        chart, birth_data = self._gui.chart_manager.build_chart_from_file(path)
        label = birth_data.get("name") or Path(path).stem
        # D-23(b) / F2: build the chip payload from the file's birth_data.
        from managers.overlay_display import overlay_display_from_birth_data
        birth = overlay_display_from_birth_data(birth_data)
        if not birth_data.get("name"):
            import dataclasses
            birth = dataclasses.replace(birth, name=Path(path).stem)
        params = {
            "jd": chart.context.timeJD.jd_number(),
            "lat": birth_data.get("latitude", 0),
            "lon": birth_data.get("longitude", 0),
            "name": birth_data.get("name", ""),
            "utcoffset": birth_data.get("utc_offset_hours", 0.0),
        }
        return chart, label, birth, params

    def overlay_from_memory_id(self, entry_id):
        """Build a chart from a memory entry (by id) and overlay it."""
        if self._gui.state.active_chart is None:
            self._status("Load a chart first, then drop one to overlay it.")
            return False
        if self._find_entry(entry_id) is None:
            self._status("Could not find that chart in memory.")
            return False
        try:
            chart, label, birth, _recipe = self.build_from_memory_id(entry_id)
        except Exception as e:
            self._status(f"Could not overlay chart: {e}")
            import traceback
            traceback.print_exc()
            return False
        source = {"kind": "memory", "id": entry_id, "path": None}
        return self._apply_overlay(chart, label, source, birth)

    def overlay_from_file(self, path):
        """Build a chart from a .chtk/.toml file (non-activating) and overlay it."""
        from pathlib import Path
        if self._gui.state.active_chart is None:
            self._status("Load a chart first, then drop one to overlay it.")
            return False
        try:
            chart, label, birth, _params = self.build_from_file(path)
        except Exception as e:
            self._status(f"Could not overlay {Path(path).name}: {e}")
            import traceback
            traceback.print_exc()
            return False
        source = {"kind": "file", "id": None, "path": str(path)}
        return self._apply_overlay(chart, label, source, birth)

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
    def _apply_overlay(self, chart, label, source, birth=None):
        ok = self._gui.transit_overlay_manager.overlay_chart(
            chart, label=label, source=source, birth=birth)
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

    def _recipe_copy(self, entry):
        """A COPY of the entry recipe so the persisted memory row is never
        mutated (SPEC-TRN-006 B-9: get_or_build_chart writes house_system into
        the entry recipe and pollutes its cache, a two-instance conflict hazard)."""
        return copy.deepcopy(entry["recipe"])

    def _build_from_recipe(self, recipe):
        """Build in the active chart's current frame; ``recipe`` is a copy owned
        by the caller (its house_system is set to the current one)."""
        from core.chart_factory import build_chart_from_recipe
        recipe["house_system"] = self._gui.state.house_system
        return build_chart_from_recipe(
            recipe,
            self._gui.state.aditya_mode,
            getattr(self._gui, "chart_sidereal_ayanamsa_id", 100),
        )

    def _build_from_entry(self, entry):
        """Build from a copy of the entry recipe (kept for existing callers)."""
        return self._build_from_recipe(self._recipe_copy(entry))

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
