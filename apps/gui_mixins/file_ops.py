"""FILE OPEN / NEW / EDIT / SAVE cluster, extracted from ChartGUI (Stage 1b, move-only).

Move-only mixin per the split-investigation plan Option 4 (see
proprietary_docs/docs/god_object_decomposition/). Method BODIES are moved
byte-identically (AST-identical); ChartGUI inherits this mixin so every
self.* resolves unchanged via the MRO and no self.gui.* write is created.
Imports are MODULE-TOP here (not method-local) to preserve body byte-identity
— the Kala mixin needed zero top-level imports, this cluster references
module-level names, so they are imported at module top and cycle-checked.
"""

from PySide6.QtWidgets import QFileDialog, QMessageBox


class FileOpsMixin:
    """FILE OPEN / NEW / EDIT / SAVE behaviour for ChartGUI (see module docstring)."""

    def _open_file_dialog(self):
        """Show file dialog to open CHTK file. Delegates to ChartManager."""
        self.chart_manager.open_file_dialog()

    def _show_new_chart(self):
        """Switch to Edit Chart tab and select New Chart sub-tab."""
        # Find the Edit Chart tab
        for i in range(self.tab_widget.count()):
            tab_text = self.tab_widget.tabText(i).replace("&&", "&")
            if "New & Edit" in tab_text:
                self.tab_widget.setCurrentIndex(i)
                break

        # Select New Chart sub-tab (index 1)
        if hasattr(self, 'edit_chart_panel') and self.edit_chart_panel:
            self.edit_chart_panel.sidebar.setCurrentRow(1)

    def _show_edit_chart(self):
        """Switch to Edit Chart tab and select Edit Info sub-tab."""
        # Find the Edit Chart tab
        for i in range(self.tab_widget.count()):
            tab_text = self.tab_widget.tabText(i).replace("&&", "&")
            if "New & Edit" in tab_text:
                self.tab_widget.setCurrentIndex(i)
                break

        # Select Edit Info sub-tab (index 0)
        if hasattr(self, 'edit_chart_panel') and self.edit_chart_panel:
            self.edit_chart_panel.sidebar.setCurrentRow(0)

    def _reload_current(self):
        """Reload the currently loaded chart. Delegates to ChartManager."""
        self.chart_manager.reload_current()

    @staticmethod
    def _writer_for_path(file_path):
        """Map a chosen save path to a writer kind (SPEC-IMPORT-001 §6.1 B5).

        Pure helper (no GUI state) so it is unit-testable. Returns 'toml' for a
        .toml suffix, else 'chtk' (the default for .chtk and any unknown
        extension — CHTK stays the conservative fallback). This is the writer
        gate that prevents a .toml target from being written as CHTK binary.
        """
        from pathlib import Path
        return 'toml' if Path(file_path).suffix.lower() == '.toml' else 'chtk'

    def _save_as_chtk(self):
        """Save current chart as a chart file (CHTK or TOML).

        Writer is gated on the chosen file extension (SPEC-IMPORT-001 §6.1):
        .toml -> TOMLChartWriter, .chtk (or unknown) -> CHTKWriter. Uses recipe
        as primary source when available, with fallback to current_chart_data
        and current_birth_data for legacy entries.
        """
        if not self.current_chart_data:
            QMessageBox.warning(self, "No Chart", "No chart loaded to save.")
            return

        _active = self.state.active_chart
        _active_jd = _active.context.timeJD.jd if _active else None
        if (self.birth_jd is not None and _active_jd is not None
                and abs(_active_jd - self.birth_jd) > 0.0001
                and not getattr(self, 'is_human_design', False)):
            QMessageBox.warning(self, "Transit Chart",
                                "Cannot save a transit/Now chart as CHTK.\n"
                                "Load a natal chart first.")
            return

        _recipe = None
        if hasattr(self, 'memory_panel') and self.memory_panel:
            _idx = self.memory_panel.current_index
            if 0 <= _idx < len(self.memory_panel.charts):
                _recipe = self.memory_panel.charts[_idx].get('recipe')

        chart = self.current_chart_data
        bm = {}
        bd = getattr(self, 'current_birth_data', None) or {}

        # Helper: first non-empty/non-zero value from multiple sources
        def pick(keys_sources, default=''):
            """Try (key, source) pairs, return first truthy value."""
            for key, src in keys_sources:
                val = src.get(key) if isinstance(src, dict) else None
                if val is not None and val != '' and val != 0 and val != 'Unknown':
                    return val
            return default

        name = (_recipe.get('name') if _recipe else None) or chart.get('name') or bd.get('name') or 'chart'
        safe_name = "".join(c for c in name if c.isalnum() or c in " -_").strip()
        # SPEC-IMPORT-001 §6.1: TOML is the preferred format, default the
        # suggested name to .toml while still offering .chtk for Kala.
        suggested = f"{safe_name}.toml" if safe_name else "chart.toml"

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Chart As", suggested,
            "Chart Files (*.chtk *.toml);;CHTK (*.chtk);;TOML (*.toml);;All Files (*)"
        )
        if not file_path:
            return

        # SPEC-IMPORT-001 §6.1 (B5, 2nd corruption site): gate the writer on the
        # chosen extension. A .toml target MUST NOT be written by CHTKWriter
        # (UTF-16 binary) — that would corrupt the file. _writer_for_path() maps
        # the suffix to the writer class; default to CHTK for unknown suffixes.
        writer_kind = self._writer_for_path(file_path)

        try:
            from core.chtk_reader import CHTKWriter

            if _recipe:
                lat = _recipe.get('lat', 0)
                lon = _recipe.get('lon', 0)
                country = _recipe.get('country', 'Unknown')
                city = _recipe.get('city', 'Unknown')
                gender = _recipe.get('gender', 'Unknown')
                tz = _recipe.get('timezone', 'UTC')
                tcf = _recipe.get('time_change_flag', 0)
            else:
                chart_coords = chart.get('coordinates', {})
                chart_location = chart.get('location', {})
                bm_coords = bm.get('coordinates', {})

                lat = pick([
                    ('latitude', chart), ('latitude', chart_coords),
                    ('latitude', chart_location),
                    ('latitude', bm), ('latitude', bm_coords), ('latitude', bd),
                ], default=0)
                lon = pick([
                    ('longitude', chart), ('longitude', chart_coords),
                    ('longitude', chart_location),
                    ('longitude', bm), ('longitude', bm_coords), ('longitude', bd),
                ], default=0)

                country = pick([
                    ('country', chart), ('country', chart_location),
                    ('country', bm), ('country', bd),
                ], default='Unknown')
                city = pick([
                    ('city', chart), ('city', chart_location),
                    ('city', bm), ('city', bd),
                ], default='Unknown')

                gender = pick([
                    ('gender', chart), ('gender', bm), ('gender', bd),
                ], default='Unknown')

                tz = getattr(self, 'current_timezone', None)
                if not tz or tz == 'UTC':
                    tz = pick([
                        ('timezone', chart), ('timezone', bm),
                        ('iana_timezone', bd), ('chtk_timezone', bd),
                    ], default='UTC')

                tcf = chart.get('time_change_flag', bm.get('time_change_flag',
                        bd.get('time_change_flag', 0)))

            if _recipe:
                from core.chart_factory import timedec_to_hms
                _h, _m, _s = timedec_to_hms(_recipe['timedec'])
                metadata = {
                    'name': name,
                    'year': _recipe['year'],
                    'month': _recipe['month'],
                    'day': _recipe['day'],
                    'hour': _h,
                    'minute': _m,
                    'second': _s,
                    'gender': gender,
                    'country': country,
                    'city': city,
                    'timezone': _recipe.get('timezone', 'UTC'),
                    'time_change_flag': tcf,
                    'coordinates': {
                        'latitude': lat,
                        'longitude': lon,
                    },
                }
            else:
                metadata = {
                    'name': name,
                    'year': chart['year'] if 'year' in chart else (bm['year'] if 'year' in bm else bd.get('local_year', 1900)),
                    'month': chart['month'] if 'month' in chart else (bm['month'] if 'month' in bm else bd.get('local_month', 1)),
                    'day': chart['day'] if 'day' in chart else (bm['day'] if 'day' in bm else bd.get('local_day', 1)),
                    'hour': chart.get('hour', bm.get('hour', bd.get('local_hour', 0))),
                    'minute': chart.get('minute', bm.get('minute', bd.get('local_minute', 0))),
                    'second': chart.get('second', bm.get('second', bd.get('local_second', 0))),
                    'gender': gender,
                    'country': country,
                    'city': city,
                    'timezone': tz,
                    'time_change_flag': tcf,
                    'coordinates': {
                        'latitude': lat,
                        'longitude': lon,
                    },
                }

            if writer_kind == 'toml':
                # SPEC-IMPORT-001 §5: TOMLChartWriter consumes a CANONICAL
                # birth_data dict (flat lat/lon, local_* fields, julian_day,
                # rodden/tags/notes), NOT the CHTK `metadata` shape. Build that
                # canonical dict from the same sources, forwarding the additive
                # metadata from current_birth_data when present (a .toml chart
                # loaded earlier carries it; CHTK-origin charts leave it None).
                from core.toml_chart import TOMLChartWriter
                _coords = metadata['coordinates']

                # Prefer birth_data, fall back to recipe, using an explicit
                # `is None` check (NOT `or`) so a legitimate 0.0 dst_offset is
                # not swallowed as falsy (project rule: no `or` chains on 0.0).
                # `recipe_key` handles the BDM/recipe key mismatch: the recipe
                # stores the UTC offset under 'utcoffset', the canonical dict
                # under 'utc_offset_hours' (project memory: UTC offset key
                # mismatch). Without the alias a recipe-only save (bd is None)
                # would silently write utc_offset = 0.0.
                def _meta(key, recipe_key=None):
                    v = bd.get(key) if bd else None
                    if v is None and _recipe:
                        v = _recipe.get(recipe_key or key)
                    return v

                canonical = {
                    'name': name,
                    'gender': gender,
                    'local_year': metadata['year'],
                    'local_month': metadata['month'],
                    'local_day': metadata['day'],
                    'local_hour': metadata['hour'],
                    'local_minute': metadata['minute'],
                    'local_second': metadata['second'],
                    'latitude': _coords['latitude'],
                    'longitude': _coords['longitude'],
                    'city': city,
                    'country': country,
                    'time_change_flag': metadata['time_change_flag'],
                    # Additive TOML-native metadata (omit-when-None handled by
                    # the writer): forward from the loaded birth_data / recipe.
                    'rodden': _meta('rodden'),
                    'tags': _meta('tags'),
                    'notes': _meta('notes'),
                    'julian_day': _meta('julian_day'),
                    'dst_offset_hours': _meta('dst_offset_hours'),
                    'utc_offset_hours': _meta('utc_offset_hours',
                                              recipe_key='utcoffset'),
                }
                TOMLChartWriter().write(canonical, file_path)
            else:
                writer = CHTKWriter()
                writer.save_chtk_file(metadata, name=name, output_path=file_path)

            self.statusBar().showMessage(f"Saved: {file_path}")

        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save chart:\n{e}")
            import traceback
            traceback.print_exc()
