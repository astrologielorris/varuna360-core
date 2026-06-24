# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Session Manager - Persist and restore chart sessions across app restarts

This module handles:
- Auto-save session on app close
- Auto-save every 30 seconds (crash protection)
- Restore dialog on startup
- Session file management per profile

Uses PySide6 (Qt6) for the restore dialog.
"""

import json
import os
import threading
import tempfile
import shutil
from datetime import datetime
from pathlib import Path
from utils.debug import debug_print

# Try to import Qt (PySide6)
try:
    from PySide6.QtWidgets import (
        QDialog, QMessageBox, QLabel, QPushButton,
        QVBoxLayout, QHBoxLayout, QWidget
    )
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtGui import QFont
    QT_AVAILABLE = True
except ImportError:
    QT_AVAILABLE = False

CTK_AVAILABLE = False  # Legacy Tkinter/CustomTkinter support removed

# Project root is one level up: managers/ -> chart_calculation/
_MANAGERS_DIR = Path(__file__).parent
PROJECT_ROOT = _MANAGERS_DIR.parent


def _translate_mode(mode):
    """Translate old enum values from saved sessions to current names."""
    if mode == "zodiac":
        return "aditya"
    if mode == "classic":
        return "tropical_classic"
    return mode


class SessionManager:
    """
    Manages session persistence for chart memory.
    Sessions are stored per-profile in profiles/{profile_name}/session.json
    """

    VERSION = "3.0"
    AUTO_SAVE_INTERVAL = 30000  # 30 seconds in milliseconds

    def __init__(self, app, profiles_dir=None, profile_store=None):
        """
        Initialize the session manager.

        Args:
            app: The main CoreChartApp instance (Tkinter) or QMainWindow (Qt)
            profiles_dir: Optional custom profiles directory
            profile_store: Optional state.ProfileStore instance. When provided,
                load/save delegate to it (Phase 4 W4); when None, falls back
                to the legacy in-class file I/O for backwards compat.
        """
        self.app = app
        self._profile_store = profile_store

        # Detect framework type
        self.is_qt = QT_AVAILABLE and hasattr(app, 'centralWidget')
        self.is_ctk = not self.is_qt and hasattr(app, 'root')

        # Set up profiles directory (in project root)
        if profiles_dir:
            self.profiles_dir = Path(profiles_dir)
        elif profile_store is not None:
            # Honor the store's directory so disk layout stays consistent
            self.profiles_dir = Path(profile_store.profiles_dir)
        else:
            from state.user_data import get_user_data_dir
            data_dir = get_user_data_dir() or PROJECT_ROOT
            self.profiles_dir = data_dir / "profiles"

        # Current profile (default until profile system is implemented)
        self.current_profile = "default"

        # Auto-save timer (QTimer for Qt, int for Tkinter)
        self._auto_save_timer = None

        # Track if we've restored this session (to avoid double prompts)
        self._session_restored = False

        # Thread safety for file operations (prevents race conditions)
        self._file_lock = threading.RLock()

        # Auto-save pause flag (used during profile switching)
        self._auto_save_paused = False

        # Track consecutive save failures for user notification
        self._consecutive_failures = 0
        self._failure_threshold = 3

        # Ensure profiles directory exists
        self._ensure_profile_dir()

    def _ensure_profile_dir(self):
        """Create profiles directory structure if needed."""
        profile_dir = self.profiles_dir / self.current_profile
        profile_dir.mkdir(parents=True, exist_ok=True)

    def _get_session_path(self, profile_name=None):
        """Get path to session file for given profile."""
        profile = profile_name or self.current_profile
        return self.profiles_dir / profile / "session.json"

    def _atomic_write_json(self, file_path: Path, data: dict) -> bool:
        """
        Write JSON atomically using temp file + rename pattern.

        This ensures that either the complete file is written, or the old file
        remains intact. Prevents corruption if app crashes during write.

        Args:
            file_path: Target file path
            data: Dictionary to write as JSON

        Returns:
            True if successful, False otherwise
        """
        temp_fd = None
        temp_path = None
        try:
            # Create temp file in same directory (for same-filesystem rename)
            temp_fd, temp_path = tempfile.mkstemp(
                suffix='.tmp',
                dir=str(file_path.parent),
                prefix='session_'
            )

            # Write to temp file with fsync for durability
            with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
                temp_fd = None  # os.fdopen takes ownership
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())

            # Atomic rename (POSIX guarantees atomicity on same filesystem)
            os.replace(temp_path, file_path)
            return True

        except Exception as e:
            debug_print(f"[SESSION] Atomic write failed: {e}")
            # Clean up temp file if it exists
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except Exception:
                    pass
            # Close fd if still open
            if temp_fd is not None:
                try:
                    os.close(temp_fd)
                except Exception:
                    pass
            return False

    def _create_backup(self, file_path: Path) -> bool:
        """
        Create a .bak backup before writing.

        Args:
            file_path: File to back up

        Returns:
            True if successful or file doesn't exist, False on error
        """
        if not file_path.exists():
            return True

        backup_path = file_path.with_suffix('.json.bak')
        try:
            shutil.copy2(file_path, backup_path)
            return True
        except Exception as e:
            debug_print(f"[SESSION] Backup failed: {e}")
            return False

    def pause_auto_save(self):
        """Pause auto-save (use during profile switching)."""
        self._auto_save_paused = True
        debug_print("[SESSION] Auto-save paused")

    def resume_auto_save(self):
        """Resume auto-save after profile switching."""
        self._auto_save_paused = False
        debug_print("[SESSION] Auto-save resumed")

    def has_previous_session(self):
        """Check if a previous session exists and has charts."""
        # Phase 4 W4: delegate to ProfileStore when available
        if self._profile_store is not None:
            if not self._profile_store.profile_exists(self.current_profile):
                return False, 0, False
            data = self._profile_store.load_profile(self.current_profile)
            charts = data.get('charts', [])
            return len(charts) > 0, len(charts), data.get('properly_closed', True)

        session_path = self._get_session_path()
        if not session_path.exists():
            return False, 0, False

        try:
            with open(session_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            charts = data.get('charts', [])
            chart_count = len(charts)
            properly_closed = data.get('properly_closed', True)

            return chart_count > 0, chart_count, properly_closed
        except Exception as e:
            debug_print(f"[SESSION] Error checking session: {e}")
            return False, 0, True

    def _show_qt_restore_dialog(self, chart_count, properly_closed):
        """
        Show restore dialog using Qt (PySide6).

        Args:
            chart_count: Number of charts in session
            properly_closed: Whether app closed properly

        Returns:
            True if user chose to restore, False otherwise
        """
        from ui.qt_theme import get_theme_colors, STATUS, scaled_area_px

        # Build dialog message
        if not properly_closed:
            title = "Restore Session"
            message = f"Application didn't close properly.\nRestore previous session?\n\n({chart_count} charts)"
        else:
            title = "Restore Session"
            message = f"Restore previous session?\n\n({chart_count} charts)"

        theme = get_theme_colors()

        # Create dialog
        dialog = QDialog(self.app)
        dialog.setWindowTitle(title)
        dialog.setFixedSize(380, 170)
        dialog.setModal(True)

        # Layout
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Message label — SPEC-THM-001 G14 live theme color.
        msg_label = QLabel(message)
        msg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg_label.setWordWrap(True)
        msg_label.setStyleSheet(f"""
            QLabel {{
                color: {theme["secondary_text"]};
                font-size: {scaled_area_px('info_text')}px;
                background: transparent;
            }}
        """)
        layout.addWidget(msg_label)

        # Button layout
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        # Result variable
        result = {'restore': False}

        def on_restore():
            result['restore'] = True
            dialog.accept()

        def on_start_fresh():
            result['restore'] = False
            dialog.accept()

        # Restore button (primary - green)
        restore_btn = QPushButton("Restore")
        restore_btn.setFixedSize(120, 36)
        restore_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        restore_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #27AE60;
                color: #FFFFFF;
                border: none;
                border-radius: 4px;
                font-size: {scaled_area_px('info_text')}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #219A52;
            }}
        """)
        restore_btn.clicked.connect(on_restore)
        btn_layout.addWidget(restore_btn)

        # Start Fresh button (secondary) — SPEC-THM-001 G14 live theme colors.
        fresh_btn = QPushButton("Start Fresh")
        fresh_btn.setFixedSize(120, 36)
        fresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        fresh_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme["secondary"]};
                color: {theme["secondary_text"]};
                border: 1px solid {theme["secondary_light"]};
                border-radius: 4px;
                font-size: {scaled_area_px('info_text')}px;
            }}
            QPushButton:hover {{
                background-color: {theme["secondary_light"]};
            }}
        """)
        fresh_btn.clicked.connect(on_start_fresh)
        btn_layout.addWidget(fresh_btn)

        layout.addLayout(btn_layout)

        # Show dialog and wait
        dialog.exec()

        return result['restore']

    def _show_ctk_restore_dialog(self, chart_count, properly_closed):
        """Legacy CTK dialog — no longer used. Falls back to Qt dialog."""
        debug_print("[SESSION] CTK dialog removed — use Qt dialog instead")
        return self._show_qt_restore_dialog(chart_count, properly_closed)

    def show_restore_dialog_if_needed(self):
        """
        Show restore dialog if there's a previous session.
        Automatically detects Qt vs CustomTkinter and uses appropriate dialog.

        Returns:
            True if session was restored, False otherwise
        """
        has_session, chart_count, properly_closed = self.has_previous_session()

        if not has_session:
            return False

        # Dispatch to appropriate dialog based on framework
        if self.is_qt:
            user_wants_restore = self._show_qt_restore_dialog(chart_count, properly_closed)
        elif self.is_ctk:
            user_wants_restore = self._show_ctk_restore_dialog(chart_count, properly_closed)
        else:
            debug_print("[SESSION] No supported GUI framework detected")
            return False

        # Perform restore if requested
        if user_wants_restore:
            self.restore_session()
            self._session_restored = True
            return True
        else:
            # Clear the improperly closed flag
            self.mark_properly_closed()
            return False

    def restore_session_silently(self, preserve_current_chart=False):
        """Silently restore previous session without showing a dialog.

        Args:
            preserve_current_chart: If True, save current chart before restoring and add it back

        Returns:
            True if session was restored, False otherwise
        """
        has_session, chart_count, properly_closed = self.has_previous_session()

        if not has_session:
            return False

        _preserved_recipe = None
        _preserved_sp = {}
        if preserve_current_chart and self.app.state.active_chart is not None:
            debug_print("[SESSION] Preserving current chart before restore")
            from core.chart_factory import recipe_from_chart
            _active = self.app.state.active_chart
            _preserved_sp = getattr(self.app.state, 'source_params', None) or {}
            _preserved_recipe = recipe_from_chart(
                _active,
                timezone=getattr(self.app, 'current_timezone', 'UTC'),
                city=getattr(self.app, 'city', ''),
                country=getattr(self.app, 'birth_country', ''),
            )

        debug_print(f"[SESSION] Auto-restoring previous session ({chart_count} charts)")
        success = self.restore_session(skip_auto_select=preserve_current_chart)
        if success:
            self._session_restored = True

            if _preserved_recipe is not None and hasattr(self.app, 'chart_memory_panel') and self.app.chart_memory_panel:
                import uuid
                memory_panel = self.app.chart_memory_panel
                entry = {
                    'id': str(uuid.uuid4()),
                    'recipe': _preserved_recipe,
                    'mode': _preserved_sp.get('mode', 'aditya'),
                    'ayanamsa': _preserved_sp.get('ayanamsa', 1),
                    'chtk_path': getattr(self.app, 'loaded_chtk_path', None),
                    'is_transit': False,
                    '_chart': None,
                }
                from core.chart_factory import metadata_from_recipe
                recipe = entry['recipe']
                _bd, _bm = metadata_from_recipe(recipe)
                entry['person_name'] = recipe['name']
                entry['city'] = recipe['city']
                entry['country'] = recipe['country']
                entry['birth_data'] = _bd
                entry['birth_metadata'] = _bm
                entry['planets_data'] = {}
                entry['aditya_mode'] = entry['mode']
                entry['source_params'] = None
                memory_panel.charts.append(entry)
                memory_panel._insertion_order.append(entry['id'])
                memory_panel.refresh()
                debug_print(f"[SESSION] Added current chart back to memory (total: {len(memory_panel.charts)} charts)")

        return success

    def save_session(self, mark_closed=False):
        """
        Save current session to disk using atomic writes.

        Args:
            mark_closed: If True, mark session as properly closed

        Returns:
            bool: True if save succeeded, False otherwise
        """
        # Acquire lock to prevent concurrent access
        with self._file_lock:
            try:
                # Get chart memory panel
                if not hasattr(self.app, 'chart_memory_panel') or not self.app.chart_memory_panel:
                    debug_print("[SESSION] No chart memory panel, skipping save")
                    return True  # Not an error, just nothing to save

                memory_panel = self.app.chart_memory_panel

                # Build session data (save even if empty - this clears the session file)
                session_data = {
                    'version': self.VERSION,
                    'last_saved': datetime.now().isoformat(),
                    'properly_closed': mark_closed,
                    'current_chart_index': memory_panel.current_index,
                    'ui_state': {
                        'aditya_mode': self.app.state.aditya_mode,
                        'background_num': getattr(self.app, 'background_num', 1),
                        'planet_size': getattr(self.app, 'planet_size', 60),
                        # Dasha ayanamsa settings
                        'vedanga_ayanamsa': getattr(self.app, 'vedanga_ayanamsa', 100),
                        'vimshottari_ayanamsa': getattr(self.app, 'vimshottari_ayanamsa', 98),
                        'right_dasha_mode': getattr(self.app, 'right_dasha_mode', 'nisarga'),
                        # Chart zodiac (sidereal) settings
                        'chart_zodiac': getattr(self.app, 'chart_zodiac', 'tropical'),
                        'chart_sidereal_ayanamsa_id': getattr(self.app, 'chart_sidereal_ayanamsa_id', 1),
                    },
                    'charts': []
                }

                for entry in memory_panel.charts:
                    chart_data = {
                        'id': entry.get('id', ''),
                        'recipe': entry['recipe'],
                        'mode': entry.get('mode', 'aditya'),
                        'ayanamsa': entry.get('ayanamsa', 1),
                        'chtk_path': entry.get('chtk_path'),
                        'is_transit': entry.get('is_transit', False),
                    }
                    session_data['charts'].append(chart_data)

                # Prepare file path
                session_path = self._get_session_path()
                session_path.parent.mkdir(parents=True, exist_ok=True)

                # Create backup before writing (enables recovery)
                self._create_backup(session_path)

                # Phase 4 W4: delegate atomic write to ProfileStore when available;
                # fall back to legacy _atomic_write_json otherwise.
                if self._profile_store is not None:
                    success = self._profile_store.save_profile(self.current_profile, session_data)
                else:
                    success = self._atomic_write_json(session_path, session_data)

                if success:
                    debug_print(f"[SESSION] Saved {len(session_data['charts'])} charts to {session_path}")
                    self._consecutive_failures = 0
                    return True
                else:
                    self._consecutive_failures += 1
                    debug_print(f"[SESSION] Save failed (attempt {self._consecutive_failures})")
                    self._notify_save_failure_if_needed()
                    return False

            except Exception as e:
                self._consecutive_failures += 1
                debug_print(f"[SESSION] Error saving session: {e}")
                import traceback
                traceback.print_exc()
                self._notify_save_failure_if_needed()
                return False

    def _notify_save_failure_if_needed(self):
        """Show warning to user if save has failed multiple times."""
        if self._consecutive_failures >= self._failure_threshold:
            try:
                if self.is_qt:
                    from PySide6.QtWidgets import QMessageBox
                    QMessageBox.warning(
                        self.app,
                        "Save Failed",
                        f"Could not save session after {self._consecutive_failures} attempts.\n"
                        "Your charts may not be restored on restart.\n\n"
                        "Check disk space and file permissions."
                    )
                # Reset counter after showing warning
                self._consecutive_failures = 0
            except Exception as e:
                debug_print(f"[SESSION] Could not show warning: {e}")

    def _migrate_v2_entry(self, old_entry):
        """Convert a v2.x chart entry to v3.0 recipe format (SPEC-MEM-002 S8.3)."""
        import uuid
        from core.chart_factory import make_recipe
        from utils.path_translator import translate_path

        bd = old_entry.get('birth_data') or {}
        sp = old_entry.get('source_params') or {}
        sp_bd = sp.get('birth_data') or {}
        pd = old_entry.get('planets_data') or {}

        name = old_entry.get('person_name') or bd.get('name') or sp_bd.get('name') or ''

        def _pick(key, *sources, default=None):
            for src in sources:
                v = src.get(key)
                if v is not None:
                    return v
            return default

        year = _pick('year', bd, sp_bd, pd, default=2000)
        month = _pick('month', bd, sp_bd, pd, default=1)
        day = _pick('day', bd, sp_bd, pd, default=1)

        timedec = _pick('timedec', bd, sp_bd)
        if timedec is None:
            h = pd.get('hour') if pd.get('hour') is not None else 0
            m = pd.get('minute') if pd.get('minute') is not None else 0
            s = pd.get('second') if pd.get('second') is not None else 0
            timedec = h + m / 60.0 + s / 3600.0

        utcoffset = _pick('utcoffset', bd, sp_bd, pd)
        if utcoffset is None:
            utcoffset = _pick('utc_offset_hours', bd, sp_bd, pd)
        if utcoffset is None:
            utcoffset = 0.0
        lat = _pick('lat', bd, sp_bd, default=_pick('latitude', pd, default=0.0))
        lon = _pick('lon', bd, sp_bd, default=_pick('longitude', pd, default=0.0))
        tz = bd.get('iana_timezone') or old_entry.get('detected_timezone') or 'UTC'
        city = old_entry.get('city') or bd.get('city') or ''
        country = old_entry.get('country') or bd.get('country') or ''

        all_empty = (not bd and not sp_bd and not pd)
        if all_empty:
            print(f"Warning: chart '{name}' has no reconstruction data, skipping migration")
            return None

        raw_path = old_entry.get('chtk_path')
        translated_path = translate_path(raw_path) if raw_path else None

        return {
            'id': old_entry.get('id', str(uuid.uuid4())),
            'recipe': make_recipe(
                name=name, year=year, month=month, day=day,
                timedec=timedec, utcoffset=utcoffset, timezone=tz,
                lat=lat, lon=lon, city=city, country=country,
            ),
            'mode': _translate_mode(old_entry.get('aditya_mode') or sp.get('mode') or 'aditya'),
            'ayanamsa': sp.get('ayanamsa', 1),
            'chtk_path': translated_path,
            'is_transit': old_entry.get('is_transit', False),
            '_chart': None,
        }

    def restore_session(self, skip_auto_select=False):
        """Restore session from disk.

        Args:
            skip_auto_select: If True, don't auto-select any chart after restore
        """
        try:
            # Phase 4 W4: delegate read to ProfileStore when available
            if self._profile_store is not None:
                if not self._profile_store.profile_exists(self.current_profile):
                    debug_print("[SESSION] No session file to restore")
                    return False
                data = self._profile_store.load_profile(self.current_profile)
            else:
                session_path = self._get_session_path()
                if not session_path.exists():
                    debug_print("[SESSION] No session file to restore")
                    return False

                with open(session_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

            # Verify version compatibility
            version = data.get('version', '1.0')
            if version != self.VERSION:
                debug_print(f"[SESSION] Warning: Session version mismatch ({version} vs {self.VERSION})")

            # Restore UI state
            ui_state = data.get('ui_state', {})
            if ui_state:
                from state.events import SetZodiacMode
                from managers.settings_manager import get_settings
                # Guard restore: a locked zodiac.mode must not be clobbered by
                # session restore (which fires ~500ms after boot).
                if not get_settings().is_locked("zodiac.mode"):
                    session_mode = _translate_mode(ui_state.get('aditya_mode', 'aditya'))
                    if session_mode != self.app.state.aditya_mode:
                        self.app.state.dispatch(SetZodiacMode(mode=session_mode))
                self.app.background_num = ui_state.get('background_num', 1)
                self.app.planet_size = ui_state.get('planet_size', 60)
                # Restore dasha ayanamsa settings. Guard each side by its lock key so
                # a locked dasha config (frozen in app_settings.json) is not clobbered
                # by session restore (which fires ~500ms after boot). Grouped per side.
                if not get_settings().is_locked("dasha.left.ayanamsa_id"):
                    self.app.vedanga_ayanamsa = ui_state.get('vedanga_ayanamsa', 100)
                if not get_settings().is_locked("dasha.right.ayanamsa_id"):
                    self.app.vimshottari_ayanamsa = ui_state.get('vimshottari_ayanamsa', 98)
                if not get_settings().is_locked("dasha.right.mode"):
                    self.app.right_dasha_mode = ui_state.get('right_dasha_mode', 'nisarga')
                # Restore chart zodiac (sidereal) settings
                self.app.chart_zodiac = ui_state.get('chart_zodiac', 'tropical')
                self.app.chart_sidereal_ayanamsa_id = ui_state.get('chart_sidereal_ayanamsa_id', 1)
                get_settings().persist_runtime_change("zodiac.ayanamsa_id", self.app.chart_sidereal_ayanamsa_id)
                # Restore sidereal mode if it was active (skip if mode is locked or already set)
                if self.app.chart_zodiac == "sidereal" and not get_settings().is_locked("zodiac.mode"):
                    if self.app.state.aditya_mode != "sidereal":
                        self.app.state.dispatch(SetZodiacMode(mode="sidereal"))
                # Update title buttons if they exist
                if hasattr(self.app, 'dasha_manager'):
                    self.app.dasha_manager._update_dasha_title("vedanga")
                    if getattr(self.app, 'right_dasha_mode', 'vimshottari') == 'nisarga':
                        self.app.vimshottari_title_btn.setText("Planetary Ages")
                        self.app.vimshottari_title_btn.setEnabled(False)
                    else:
                        self.app.dasha_manager._update_dasha_title("vimshottari")

            # Restore charts
            charts = data.get('charts', [])
            if not charts:
                debug_print("[SESSION] No charts in session")
                return False

            # Get chart memory panel
            if not hasattr(self.app, 'chart_memory_panel') or not self.app.chart_memory_panel:
                debug_print("[SESSION] No chart memory panel available")
                return False

            memory_panel = self.app.chart_memory_panel

            memory_panel.charts.clear()
            memory_panel._insertion_order.clear()
            memory_panel.current_index = -1

            import uuid
            from utils.path_translator import translate_path
            version = data.get('version', '1.0')

            for i, chart_data in enumerate(charts):
                if version < '3.0':
                    entry = self._migrate_v2_entry(chart_data)
                    if entry is None:
                        continue
                else:
                    translated_path = translate_path(chart_data.get('chtk_path')) if chart_data.get('chtk_path') else None
                    entry = {
                        'id': chart_data.get('id', str(uuid.uuid4())),
                        'recipe': chart_data['recipe'],
                        'mode': _translate_mode(chart_data.get('mode', 'aditya')),
                        'ayanamsa': chart_data.get('ayanamsa', 1),
                        'chtk_path': translated_path,
                        'is_transit': chart_data.get('is_transit', False),
                        '_chart': None,
                    }

                from core.chart_factory import metadata_from_recipe
                recipe = entry['recipe']
                _bd, _bm = metadata_from_recipe(recipe)
                entry['person_name'] = recipe['name']
                entry['city'] = recipe['city']
                entry['country'] = recipe['country']
                entry['birth_data'] = _bd
                entry['birth_metadata'] = _bm
                entry['planets_data'] = {}
                entry['aditya_mode'] = entry['mode']
                entry['source_params'] = None

                memory_panel.charts.append(entry)
                memory_panel._insertion_order.append(entry['id'])
                debug_print(f"[SESSION] Added chart {i+1}/{len(charts)}: {recipe['name']}")

            # Restore selected chart index (unless skip_auto_select is True)
            if not skip_auto_select:
                saved_index = data.get('current_chart_index', 0)
                debug_print(f"[SESSION] Saved index was: {saved_index}, total charts: {len(memory_panel.charts)}")
                if 0 <= saved_index < len(memory_panel.charts):
                    debug_print(f"[SESSION] Selecting chart at index {saved_index}")
                    memory_panel.select_chart(saved_index)
                elif memory_panel.charts:
                    debug_print(f"[SESSION] Saved index out of range, selecting first chart (index 0)")
                    memory_panel.select_chart(0)
            else:
                debug_print("[SESSION] Skipping auto-select of restored chart")

            # Refresh the memory panel display
            debug_print(f"[SESSION] About to refresh memory panel with {len(memory_panel.charts)} charts")
            memory_panel.refresh()
            debug_print(f"[SESSION] Memory panel refreshed, buttons count: {len(memory_panel.chart_buttons)}")

            debug_print(f"[SESSION] ✅ Successfully restored {len(charts)} charts")
            return True

        except Exception as e:
            debug_print(f"[SESSION] Error restoring session: {e}")
            import traceback
            traceback.print_exc()
            return False

    def mark_properly_closed(self):
        """Mark session as properly closed (no crash)."""
        with self._file_lock:
            try:
                session_path = self._get_session_path()
                if not session_path.exists():
                    return

                with open(session_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                data['properly_closed'] = True

                # Use atomic write for safety
                self._atomic_write_json(session_path, data)

            except Exception as e:
                debug_print(f"[SESSION] Error marking properly closed: {e}")

    def clear_session(self):
        """Delete session file for current profile."""
        try:
            session_path = self._get_session_path()
            if session_path.exists():
                session_path.unlink()
                debug_print(f"[SESSION] Cleared session: {session_path}")
        except Exception as e:
            debug_print(f"[SESSION] Error clearing session: {e}")

    def start_auto_save(self):
        """Start the auto-save timer for crash protection."""
        if self.is_qt:
            # Qt: Use QTimer
            if QT_AVAILABLE:
                self._auto_save_timer = QTimer()
                self._auto_save_timer.timeout.connect(self._auto_save_tick)
                self._auto_save_timer.start(self.AUTO_SAVE_INTERVAL)
                debug_print("[SESSION] Started Qt auto-save timer (30s interval)")
        elif self.is_ctk:
            # Tkinter: Use after()
            self._schedule_auto_save()
            debug_print("[SESSION] Started Tkinter auto-save timer (30s interval)")

    def _schedule_auto_save(self):
        """Schedule the next auto-save (Tkinter only)."""
        if not self.is_ctk:
            return

        if self._auto_save_timer:
            self.app.root.after_cancel(self._auto_save_timer)

        self._auto_save_timer = self.app.root.after(
            self.AUTO_SAVE_INTERVAL,
            self._auto_save_tick
        )

    def _auto_save_tick(self):
        """Perform auto-save and schedule next one."""
        try:
            # Skip if paused (during profile switching)
            if self._auto_save_paused:
                debug_print("[SESSION] Auto-save skipped (paused)")
                # Still schedule next tick
                if self.is_ctk:
                    self._schedule_auto_save()
                return

            # Save session (not marking as closed - that's only on clean exit)
            self.save_session(mark_closed=False)

            # Schedule next auto-save (Tkinter only - Qt uses repeating QTimer)
            if self.is_ctk:
                self._schedule_auto_save()

        except Exception as e:
            debug_print(f"[SESSION] Auto-save error: {e}")

    def stop_auto_save(self):
        """Stop the auto-save timer."""
        if self._auto_save_timer:
            try:
                if self.is_qt and QT_AVAILABLE:
                    # Qt: Stop QTimer
                    self._auto_save_timer.stop()
                elif self.is_ctk:
                    # Tkinter: Cancel after()
                    self.app.root.after_cancel(self._auto_save_timer)
            except Exception as e:
                debug_print(f"[SESSION] Error stopping auto-save: {e}")
            self._auto_save_timer = None

    def on_app_closing(self):
        """Called when app is closing - save session and mark as properly closed."""
        debug_print("[SESSION] App closing - saving session...")
        self.stop_auto_save()
        self.save_session(mark_closed=True)
        debug_print("[SESSION] Session saved successfully")
