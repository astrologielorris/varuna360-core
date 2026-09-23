"""KALA EXPORT cluster, extracted from ChartGUI (Stage 1a, td-63xl).

Move-only mixin per the split investigation plan Option 4: a plain-Python
mixin (NOT a QObject, no __init__) that ChartGUI inherits. The method body
is moved byte-identically; every import it needs is local to the method, so
this module needs no module-level imports and introduces no import cycle.
ChartGUI provides self (prefs_store, memory_panel, statusBar()) via
inheritance, so self.* resolves unchanged and no self.gui.* write is created
(Rule 4b safe). test_kala_export.py inspect.getsource(ChartGUI._open_in_kala)
keeps resolving through the MRO.
"""


class KalaIntegrationMixin:
    """Kala-export behavior for ChartGUI (see module docstring)."""

    def _open_in_kala(self):
        """
        Open the current chart in Kala astrology software.

        Priority (memory panel is authoritative for current chart):
        1. Use memory panel's current chart chtk_path (if exists)
        2. Create temp CHTK from memory panel's birth_metadata
        3. Launch Kala without a file

        Cross-platform:
        - Windows: launches Kala.exe directly
        - Linux/macOS: launches through Wine
        """
        import os
        import sys
        import subprocess
        import tempfile
        import json
        from PySide6.QtWidgets import QMessageBox

        # Load Kala exe path: SettingsManager first, legacy PrefsStore fallback
        from managers.settings_manager import get_settings
        kala_exe_path = get_settings().get("paths.kala_path", "")
        if not kala_exe_path:
            try:
                all_prefs = self.prefs_store.load()
                kala_exe_path = all_prefs.get("kala", {}).get("exe_path", "")
            except Exception as e:
                print(f"Error reading Kala settings: {e}")

        # Platform-specific defaults if no setting configured
        if not kala_exe_path:
            if sys.platform == 'win32':
                kala_exe_path = r"C:\Kala\Kala.exe"
            else:
                kala_exe_path = os.path.expanduser("~/Kala/Kala.exe")

        use_wine = sys.platform != 'win32'

        # Check if Kala exists
        if not use_wine and not os.path.exists(kala_exe_path):
            QMessageBox.warning(
                self, "Kala Not Found",
                f"Kala.exe not found at:\n{kala_exe_path}\n\n"
                "Please set the Kala path in Settings > Default Folders."
            )
            return
        if use_wine and not os.path.exists(kala_exe_path):
            QMessageBox.warning(
                self, "Kala Not Found",
                f"Kala.exe not found at:\n{kala_exe_path}\n\n"
                "Please set the Kala path in Settings > Default Folders.\n"
                "Kala will be launched through Wine."
            )
            return

        chtk_path = None
        chart_name = "chart"
        metadata = None

        # Get current chart from memory panel (authoritative source)
        if hasattr(self, 'memory_panel') and self.memory_panel:
            current_idx = self.memory_panel.current_index
            if 0 <= current_idx < len(self.memory_panel.charts):
                current_chart = self.memory_panel.charts[current_idx]
                chart_name = current_chart.get('recipe', {}).get('name') or current_chart.get('person_name', 'chart')

                # Option 1: hand Kala the file only if Kala can READ it.
                # SPEC-PERSIST-001 D-13 (td-rayw): this used to ask whether a
                # file existed, which was the same question only while every
                # chart was a .chtk. With .toml the default, the extension is
                # the question — a .toml falls through to the temp-CHTK
                # projection below, and the user's file is never rewritten.
                from core.kala_export import kala_can_open
                memory_chtk_path = current_chart.get('chtk_path')
                if kala_can_open(memory_chtk_path):
                    chtk_path = str(memory_chtk_path)
                else:
                    # Option 2: Build metadata from recipe for temp CHTK
                    recipe = current_chart.get('recipe')
                    if recipe:
                        from core.chart_factory import timedec_to_hms
                        _h, _m, _s = timedec_to_hms(recipe['timedec'])
                        metadata = {
                            'name': recipe.get('name', chart_name),
                            'year': recipe['year'],
                            'month': recipe['month'],
                            'day': recipe['day'],
                            'hour': _h,
                            'minute': _m,
                            'second': _s,
                            'latitude': recipe['lat'],
                            'longitude': recipe['lon'],
                            'timezone': recipe.get('timezone', 'UTC'),
                            'time_change_flag': recipe.get('time_change_flag', 0),
                            'gender': recipe.get('gender', 'Unknown'),
                            'city': recipe.get('city', ''),
                            'country': recipe.get('country', ''),
                            'coordinates': {
                                'latitude': recipe['lat'],
                                'longitude': recipe['lon'],
                            },
                        }
                    else:
                        # Legacy fallback for pre-recipe entries
                        metadata = current_chart.get('birth_metadata', {})
                        if not metadata:
                            bd = current_chart.get('birth_data') or {}
                            if not bd:
                                sp = current_chart.get('source_params')
                                bd = (sp.get('birth_data') or {}) if sp else {}
                            if not bd:
                                bd = current_chart.get('planets_data', {})
                            metadata = {
                                'name': chart_name,
                                'year': bd['year'] if 'year' in bd else bd.get('local_year'),
                                'month': bd['month'] if 'month' in bd else bd.get('local_month'),
                                'day': bd['day'] if 'day' in bd else bd.get('local_day'),
                                'hour': bd['hour'] if 'hour' in bd else bd.get('local_hour'),
                                'minute': bd['minute'] if 'minute' in bd else bd.get('local_minute'),
                                'second': bd.get('second', 0),
                                'latitude': bd['latitude'] if 'latitude' in bd else bd.get('lat'),
                                'longitude': bd['longitude'] if 'longitude' in bd else bd.get('lon'),
                                'timezone': bd.get('timezone') or bd.get('iana_timezone', 'UTC'),
                            }
            else:
                pass
        else:
            pass

        # Create temp CHTK if we have metadata but no chtk_path
        if not chtk_path and metadata:
            try:
                # SPEC-IMPORT-001 §6.1: this ungated CHTKWriter path is
                # intentional — Kala only consumes .chtk, and this always writes
                # a FRESH temp file (never overwrites a user .toml), so it is not
                # a B5 corruption site.
                from core.chtk_reader import CHTKWriter

                temp_dir = tempfile.gettempdir()
                # Was `.replace(' ', '_').replace('/', '_')`, which leaves
                # : \ ? * < > | " intact. Windows rejects every one of them,
                # so "Open in Kala" on a chart named e.g. "Eclipse 11:14 UT"
                # failed there and only there. windows_safe_filename returns
                # an already-safe name byte-identical, so nothing that works
                # today changes.
                from core.fs_safety import windows_safe_filename
                safe_name = windows_safe_filename(chart_name, default="chart")
                temp_path = os.path.join(temp_dir, f"{safe_name}_kala.chtk")

                writer = CHTKWriter()
                saved_path = writer.save_chtk_file(metadata, name=chart_name, output_path=temp_path)
                chtk_path = str(saved_path)

            except Exception as e:
                print(f"Error creating Kala temp file: {e}")
                import traceback
                traceback.print_exc()
                QMessageBox.critical(self, "Save Error", f"Could not save chart for Kala:\n{str(e)}")
                return

        # Convert Linux path to Wine/Windows path (Z:\...)
        def _to_wine_path(linux_path):
            try:
                result = subprocess.run(
                    ["winepath", "-w", linux_path],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.strip()
            except Exception:
                pass
            # Fallback: manual Z: drive mapping
            return "Z:" + linux_path.replace("/", "\\")

        # Build launch command based on platform
        def _build_kala_cmd(exe_path, chart_path=None):
            if use_wine:
                cmd = ["wine", exe_path]
                if chart_path:
                    cmd.append(_to_wine_path(chart_path))
            else:
                cmd = [exe_path]
                if chart_path:
                    cmd.append(chart_path)
            return cmd

        # Option 3: No chart data - just launch Kala
        if not chtk_path:
            try:
                cmd = _build_kala_cmd(kala_exe_path)
                subprocess.Popen(cmd, shell=False)
                self.statusBar().showMessage("Launched Kala (no chart)")
                return
            except Exception as e:
                QMessageBox.critical(self, "Launch Error", f"Could not launch Kala:\n{str(e)}")
                return

        # Launch Kala with the CHTK file
        try:
            cmd = _build_kala_cmd(kala_exe_path, chtk_path)
            subprocess.Popen(cmd, shell=False)
            self.statusBar().showMessage(f"Opened '{chart_name}' in Kala")
        except Exception as e:
            QMessageBox.critical(self, "Launch Error", f"Could not launch Kala:\n{str(e)}")
