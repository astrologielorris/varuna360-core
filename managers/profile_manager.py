# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Profile Manager - Manage multiple user profiles with avatars (PySide6 version)

This module handles:
- Profile creation and deletion
- Profile switching
- Profile avatar selection (using planet images)
- Profile metadata storage
"""

import json
import os
import shutil
from datetime import datetime
from pathlib import Path

from core.fs_safety import is_reserved_windows_name

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QMessageBox, QGridLayout, QWidget,
    QScrollArea, QMenu
)
from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QPixmap, QCursor

from ui.qt_theme import (
    scaled_area_size, get_theme_colors,
    get_primary_button_style, get_secondary_button_style,
)

try:
    from utils.debug import debug_print
except ImportError:
    debug_print = print  # Fallback for standalone testing

# Project root
_MANAGERS_DIR = Path(__file__).parent
PROJECT_ROOT = _MANAGERS_DIR.parent


# Available avatars (from planets folder and icon)
AVAILABLE_AVATARS = [
    {"name": "Sun", "file": "img/planets/sun.webp"},
    {"name": "Moon", "file": "img/planets/moon.webp"},
    {"name": "Mars", "file": "img/planets/Mars.webp"},
    {"name": "Mercury", "file": "img/planets/Mercury.webp"},
    {"name": "Jupiter", "file": "img/planets/Jupiter.webp"},
    {"name": "Venus", "file": "img/planets/Venus.webp"},
    {"name": "Saturn", "file": "img/planets/Saturn.webp"},
    {"name": "Rahu", "file": "img/planets/rahu.webp"},
    {"name": "Ketu", "file": "img/planets/ketu.webp"},
    {"name": "Uranus", "file": "img/planets/uranus.webp"},
    {"name": "Neptune", "file": "img/planets/neptune.webp"},
    {"name": "Pluto", "file": "img/planets/pluto.webp"},
    {"name": "Cat", "file": "img/icon/logo_mini.png"},
]

# Default avatars for first 5 profiles
DEFAULT_PROFILE_AVATARS = [
    "img/planets/sun.webp",
    "img/planets/moon.webp",
    "img/planets/Jupiter.webp",
    "img/planets/Saturn.webp",
    "img/planets/Venus.webp",
]


class ProfileManager:
    """
    Manages user profiles for the chart calculator (PySide6 version).
    Each profile has its own session and preferences.
    """

    MAX_PROFILES = None  # No limit on profiles (was 5)

    def __init__(self, app, profiles_dir=None):
        """
        Initialize the profile manager.

        Args:
            app: The main ChartGUI instance
            profiles_dir: Optional custom profiles directory
        """
        self.app = app

        # True when the profiles dir could not be initialised. Set properly by
        # _ensure_default_profile() below; predefined so every read is safe
        # even if construction is interrupted before that point.
        self.storage_degraded = False

        if profiles_dir:
            self.profiles_dir = Path(profiles_dir)
        else:
            from state.user_data import get_user_data_dir
            data_dir = get_user_data_dir() or PROJECT_ROOT
            self.profiles_dir = data_dir / "profiles"

        # Active profile file
        self.active_profile_file = self.profiles_dir / "_active_profile.txt"

        # Cache for avatar images (QPixmap instead of ImageTk.PhotoImage)
        self._avatar_cache = {}

        # Ensure default profile exists
        self._ensure_default_profile()

        # If the app closed while in the Favorites profile, startup
        # restores its session.json directly (restore_session_silently
        # bypasses _on_profile_selected). Re-sync from favorites.json
        # here so the restored list is current (SPEC-FAV-001 S5.2).
        # ProfileManager is constructed before session restore.
        if self.get_current_profile() == "favorites":
            # Guarded for the same reason as _ensure_default_profile: this
            # runs inside __init__ and writes to disk, so an unwritable dir
            # here would take the whole window down at startup.
            try:
                from managers.favorites_manager import sync_favorites_profile
                sync_favorites_profile(self.profiles_dir)
            except OSError as e:
                self.storage_degraded = True
                debug_print(f"[PROFILE] Favorites sync skipped: {e}")

    def _ensure_default_profile(self):
        """Ensure the default profile exists, without ever raising.

        SPEC-SES-001 INV-2: an unwritable profiles directory must degrade the
        app, not prevent it from starting. This method is called from
        __init__, so an unguarded OSError here propagates out of the
        ProfileManager constructor and out of ChartGUI.__init__ - the user
        gets a traceback and no window at all, on a machine where the only
        thing actually wrong is that one folder cannot be written to.

        That is a realistic case, not a defensive nicety: a macOS user who
        denies the Files and Folders prompt for ~/Documents, a Windows folder
        redirected into a locked OneDrive, a data dir on a disconnected
        external disk. SessionManager relocates to a writable fallback for
        exactly this reason, and core_gui_qt passes us its post-relocation
        path, so reaching the except branch means even the fallback failed.
        In that case the app still opens and the session health banner tells
        the user what is wrong - which is far more useful than a crash.

        Only OSError is caught. A TypeError or ValueError in here is a bug in
        this code and should still be loud.
        """
        try:
            self._ensure_default_profile_unsafe()
            self.storage_degraded = False
        except OSError as e:
            self.storage_degraded = True
            debug_print(f"[PROFILE] Cannot initialise profiles dir "
                        f"{self.profiles_dir}: {e}")
            try:
                from core.diagnostics import get_logger
                get_logger("profile").error(
                    "profiles dir unusable (%s): %s; running degraded",
                    self.profiles_dir, e,
                )
            except Exception:
                pass

    def _ensure_default_profile_unsafe(self):
        """Real body of _ensure_default_profile. May raise OSError."""
        default_dir = self.profiles_dir / "default"
        default_dir.mkdir(parents=True, exist_ok=True)

        profile_json = default_dir / "profile.json"
        if not profile_json.exists():
            profile_data = {
                "name": "Default",
                "avatar": "img/planets/sun.webp",
                "created": datetime.now().isoformat(),
                "last_used": datetime.now().isoformat(),
                "preferences": {
                    "default_aditya_mode": "aditya",
                    "default_background": 1
                }
            }
            with open(profile_json, 'w', encoding='utf-8') as f:
                json.dump(profile_data, f, indent=2)

        # Ensure the built-in Favorites profile exists (SPEC-FAV-001 S5.1).
        # Its session.json is regenerated from favorites.json on each
        # switch-in, so only profile.json needs to exist here.
        favorites_dir = self.profiles_dir / "favorites"
        favorites_json = favorites_dir / "profile.json"
        if not favorites_json.exists():
            favorites_dir.mkdir(parents=True, exist_ok=True)
            with open(favorites_json, 'w', encoding='utf-8') as f:
                json.dump({
                    "name": "Favorites",
                    "avatar": "img/planets/Venus.webp",
                    "created": datetime.now().isoformat(),
                    "last_used": "",
                    "preferences": {
                        "default_aditya_mode": "aditya",
                        "default_background": 1
                    }
                }, f, indent=2)

        # Set as active if no active profile
        if not self.active_profile_file.exists():
            with open(self.active_profile_file, 'w') as f:
                f.write("default")

    def list_profiles(self):
        """
        Get list of all profiles.

        Returns:
            List of dicts with profile info (name, avatar, last_used)
        """
        profiles = []
        if not self.profiles_dir.exists():
            return profiles

        for item in self.profiles_dir.iterdir():
            if item.is_dir() and not item.name.startswith('_'):
                profile_json = item / "profile.json"
                if profile_json.exists():
                    try:
                        with open(profile_json, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        profiles.append({
                            "id": item.name,
                            "name": data.get("name", item.name.title()),
                            "avatar": data.get("avatar", "img/planets/sun.webp"),
                            "last_used": data.get("last_used", ""),
                            "created": data.get("created", "")
                        })
                    except Exception as e:
                        debug_print(f"[PROFILE] Error reading profile {item.name}: {e}")

        # Sort by last_used (most recent first)
        profiles.sort(key=lambda x: x.get("last_used", ""), reverse=True)
        return profiles

    def get_current_profile(self):
        """Get the currently active profile name."""
        try:
            if self.active_profile_file.exists():
                with open(self.active_profile_file, 'r') as f:
                    return f.read().strip()
        except Exception as e:
            debug_print(f"[PROFILE] Error reading active profile: {e}")
        return "default"

    def get_profile_data(self, profile_id=None):
        """Get full profile data for given profile (or current)."""
        profile_id = profile_id or self.get_current_profile()
        profile_json = self.profiles_dir / profile_id / "profile.json"

        if profile_json.exists():
            try:
                with open(profile_json, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                debug_print(f"[PROFILE] Error reading profile data: {e}")

        return {"name": profile_id.title(), "avatar": "img/planets/sun.webp"}

    def create_profile(self, name, avatar=None):
        """
        Create a new profile.

        Args:
            name: Display name for the profile
            avatar: Avatar image path (relative to app dir)

        Returns:
            Profile ID if created, None if failed
        """
        # Check max profiles (only if limit is set)
        profiles = self.list_profiles()
        if self.MAX_PROFILES is not None and len(profiles) >= self.MAX_PROFILES:
            QMessageBox.warning(
                self.app,
                "Profile Limit",
                f"Maximum of {self.MAX_PROFILES} profiles allowed.\n"
                "Please delete an existing profile first."
            )
            return None

        # Generate profile ID from name.
        profile_id = name.lower().replace(" ", "_")
        profile_id = "".join(c for c in profile_id if c.isalnum() or c == "_")

        # Two ways the stripping above produces an unusable directory name:
        #
        #   1. A name made entirely of punctuation ("???", "***") strips to "".
        #      profiles_dir / "" IS profiles_dir, which always exists, so the
        #      uniqueness loop below silently renamed it to "_1" — and
        #      list_profiles() skips anything starting with "_", so the
        #      profile was created and then invisible forever.
        #   2. Windows refuses a directory named CON, PRN, AUX, NUL, COM1-9 or
        #      LPT1-9. A profile called "Con" therefore fails to mkdir there
        #      and works fine here, which is the worst kind of bug to find.
        #
        # A leading "_" is also stripped so a name like "_hidden" cannot make
        # itself invisible.
        profile_id = profile_id.lstrip("_")
        if is_reserved_windows_name(profile_id):
            profile_id = f"{profile_id}_profile"
        if not profile_id:
            profile_id = "profile"

        # Ensure unique ID
        base_id = profile_id
        counter = 1
        while (self.profiles_dir / profile_id).exists():
            profile_id = f"{base_id}_{counter}"
            counter += 1

        # Default avatar if not specified
        if not avatar:
            avatar_index = len(profiles) % len(DEFAULT_PROFILE_AVATARS)
            avatar = DEFAULT_PROFILE_AVATARS[avatar_index]

        # Create profile directory
        profile_dir = self.profiles_dir / profile_id
        profile_dir.mkdir(parents=True, exist_ok=True)

        # Create profile.json
        profile_data = {
            "name": name,
            "avatar": avatar,
            "created": datetime.now().isoformat(),
            "last_used": datetime.now().isoformat(),
            "preferences": {
                "default_aditya_mode": "aditya",
                "default_background": 1
            }
        }

        profile_json = profile_dir / "profile.json"
        with open(profile_json, 'w', encoding='utf-8') as f:
            json.dump(profile_data, f, indent=2)

        # NEW: Create empty session.json for the new profile
        # This prevents issues when switching to a new profile that has no session file
        session_json = profile_dir / "session.json"
        empty_session = {
            "version": "1.0",
            "last_saved": datetime.now().isoformat(),
            "properly_closed": True,
            "current_chart_index": -1,
            "charts": [],
            "ui_state": {
                "aditya_mode": "aditya",
                "background_num": 1,
                "planet_size": 60
            }
        }
        with open(session_json, 'w', encoding='utf-8') as f:
            json.dump(empty_session, f, indent=2)

        return profile_id

    def delete_profile(self, profile_id):
        """
        Delete a profile.

        Args:
            profile_id: ID of profile to delete

        Returns:
            True if deleted, False otherwise
        """
        if profile_id in ("default", "favorites"):
            QMessageBox.warning(self.app, "Cannot Delete",
                                f"Cannot delete the built-in '{profile_id}' profile.")
            return False

        profile_dir = self.profiles_dir / profile_id
        if not profile_dir.exists():
            return False

        # Confirm deletion
        profile_data = self.get_profile_data(profile_id)
        profile_name = profile_data.get("name", profile_id)

        result = QMessageBox.question(
            self.app,
            "Delete Profile",
            f"Delete profile '{profile_name}'?\n\n"
            "This will remove all saved charts and settings for this profile.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if result != QMessageBox.StandardButton.Yes:
            return False

        # If this was the active profile, switch to default.
        #
        # _on_profile_selected, not switch_profile: switch_profile only flips
        # the pointer, so the memory panel would keep the DELETED profile's
        # charts while current_profile already read "default" — and the next
        # autosave tick, 30 s later, would write them into default's
        # session.json on top of whatever was there. Same cross-profile loss
        # as the switch race, reached by a different door (SPEC-SES-001 §8).
        if self.get_current_profile() == profile_id:
            self._on_profile_selected("default")

        # Delete profile directory
        try:
            shutil.rmtree(profile_dir)
            return True
        except Exception as e:
            debug_print(f"[PROFILE] Error deleting profile: {e}")
            QMessageBox.critical(self.app, "Error", f"Failed to delete profile:\n{e}")
            return False

    def switch_profile(self, profile_id):
        """
        Switch to a different profile.

        CRITICAL: Pauses auto-save during switch to prevent race conditions.
        The sequence is:
        1. Pause auto-save
        2. Save current session (forced — see below)
        3. Update active profile file
        4. Update session manager's profile reference
        5. Resume auto-save

        The pause this method opens covers only steps 2-4. It is NOT enough on
        its own: when the caller goes on to clear the panel and restore the new
        profile (_on_profile_selected), that work also has to be inside a
        pause, because restore pumps the Qt event loop. Callers that restore
        must therefore open their OWN pause around the whole operation — the
        pause depth is a counter precisely so the two nest (SPEC-SES-001 §8).

        Args:
            profile_id: ID of profile to switch to

        Returns:
            True if switched, False otherwise
        """
        profile_dir = self.profiles_dir / profile_id
        if not profile_dir.exists():
            return False

        current = self.get_current_profile()
        if current == profile_id:
            return True

        # PAUSE auto-save FIRST to prevent race conditions
        if hasattr(self.app, 'session_manager') and self.app.session_manager:
            self.app.session_manager.pause_auto_save()

        try:
            # Save current session before switching.
            #
            # force=True: this is the ONE save that must happen while paused.
            # It runs before current_profile is reassigned, so the panel's
            # charts and the target profile still agree — the exact condition
            # the pause guard exists to require. Every other save reached
            # during a switch is suppressed by that guard.
            if hasattr(self.app, 'session_manager') and self.app.session_manager:
                self.app.session_manager.save_session(mark_closed=True, force=True)

            # Update active profile file
            with open(self.active_profile_file, 'w') as f:
                f.write(profile_id)

            # Update last_used timestamp
            self._update_last_used(profile_id)

            # Update session manager's current profile
            if hasattr(self.app, 'session_manager') and self.app.session_manager:
                self.app.session_manager.current_profile = profile_id

            return True

        finally:
            # ALWAYS resume auto-save (even on error)
            if hasattr(self.app, 'session_manager') and self.app.session_manager:
                self.app.session_manager.resume_auto_save()

    def _update_last_used(self, profile_id):
        """Update the last_used timestamp for a profile."""
        profile_json = self.profiles_dir / profile_id / "profile.json"
        if profile_json.exists():
            try:
                with open(profile_json, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                data["last_used"] = datetime.now().isoformat()
                with open(profile_json, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2)
            except Exception as e:
                debug_print(f"[PROFILE] Error updating last_used: {e}")

    def get_avatar_pixmap(self, avatar_path, size=(32, 32)):
        """
        Get a QPixmap for the avatar.

        Args:
            avatar_path: Path to avatar image (relative to app dir)
            size: Tuple of (width, height) for the image

        Returns:
            QPixmap object or None
        """
        cache_key = f"{avatar_path}_{size[0]}x{size[1]}"
        if cache_key in self._avatar_cache:
            return self._avatar_cache[cache_key]

        try:
            full_path = PROJECT_ROOT / avatar_path
            # Auto-correct old paths (pre-img/ reorganization) for backwards compatibility
            if not full_path.exists():
                # If path starts with "planets/" or "icon/", try prepending "img/"
                if avatar_path.startswith(("planets/", "icon/")):
                    corrected_path = f"img/{avatar_path}"
                    full_path = PROJECT_ROOT / corrected_path

            # Auto-correct old .png paths to .webp (post PNG-to-WebP migration)
            if not full_path.exists() and avatar_path.endswith('.png'):
                webp_path = avatar_path[:-4] + '.webp'
                webp_full = PROJECT_ROOT / webp_path
                if webp_full.exists():
                    full_path = webp_full

            if not full_path.exists():
                return None

            pixmap = QPixmap(str(full_path))
            if pixmap.isNull():
                return None

            # Scale to desired size
            pixmap = pixmap.scaled(
                size[0], size[1],
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )

            self._avatar_cache[cache_key] = pixmap
            return pixmap

        except Exception as e:
            debug_print(f"[PROFILE] Error loading avatar: {e}")
            return None

    def show_profile_menu(self, parent, pos):
        """
        Show the profile selection menu.

        Args:
            parent: Parent widget
            pos: QPoint position for menu (global coordinates)
        """
        menu = QMenu(parent)

        current_profile = self.get_current_profile()
        profiles = self.list_profiles()

        # Add profile entries
        for profile in profiles:
            prefix = "✓ " if profile["id"] == current_profile else "   "
            action = menu.addAction(f"{prefix}{profile['name']}")
            action.triggered.connect(lambda checked=False, pid=profile["id"]: self._on_profile_selected(pid))

        menu.addSeparator()

        # Add "Create Profile" option (always available when no limit)
        if self.MAX_PROFILES is None or len(profiles) < self.MAX_PROFILES:
            create_action = menu.addAction("+ Create Profile")
            create_action.triggered.connect(self.show_create_profile_dialog)

        # Add "Manage Profiles" option
        manage_action = menu.addAction("Manage Profiles...")
        manage_action.triggered.connect(self.show_manage_profiles_dialog)

        menu.exec(pos)

    def _on_profile_selected(self, profile_id):
        """Handle profile selection from menu.

        Auto-save stays paused for the WHOLE switch — flip AND restore — not
        just for switch_profile()'s own steps (SPEC-SES-001 §8).

        Why: switch_profile() sets session_manager.current_profile to the new
        profile and then, in its `finally`, resumes auto-save. Everything below
        runs afterwards, so the app spends the entire clear-and-restore with
        current_profile pointing at the NEW profile while the memory panel
        holds the OLD profile's charts, then an empty list, then a partially
        rebuilt one. Restore pumps the Qt event loop (SetZodiacMode dispatch,
        select_chart via LoadingManager, the bulk chart load), so the 30 s
        autosave timer really can fire in there — and whatever the panel
        happened to hold at that instant would be written into the new
        profile's session.json, destroying it.
        """
        from contextlib import nullcontext

        session_manager = getattr(self.app, 'session_manager', None)
        # nullcontext keeps the no-session-manager path (CLI harnesses, tests)
        # behaving exactly as before instead of taking a separate branch that
        # would quietly skip the panel clear and the avatar reload.
        #
        # The context manager, not a pause/resume pair: its `finally`
        # guarantees the resume even if restore_session raises. Leaving
        # auto-save paused forever would stop ALL saving for the rest of the
        # run — worse than the race it is guarding.
        guard = (session_manager.auto_save_paused() if session_manager
                 else nullcontext())
        with guard:
            if not self.switch_profile(profile_id):
                return

            # Favorites profile: regenerate its session.json from
            # favorites.json BEFORE restore (SPEC-FAV-001 S5.2)
            if profile_id == "favorites":
                from managers.favorites_manager import sync_favorites_profile
                sync_favorites_profile(self.profiles_dir)

            # Clear display WITHOUT saving (avoid overwriting new profile's session)
            if hasattr(self.app, 'memory_panel') and self.app.memory_panel:
                self.app.memory_panel._clear_display_only()  # CRITICAL: Don't save!

            # Restore new profile's session
            if session_manager:
                session_manager.restore_session()

        # Reload profile avatar for the button
        if hasattr(self.app, '_load_profile_avatar'):
            QTimer.singleShot(100, self.app._load_profile_avatar)

    def show_create_profile_dialog(self):
        """Show dialog to create a new profile."""
        dialog = CreateProfileDialog(self, self.app)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            name, avatar = dialog.get_result()
            if name:
                profile_id = self.create_profile(name, avatar)
                if profile_id:
                    # Switch to new profile
                    self._on_profile_selected(profile_id)
                    QMessageBox.information(
                        self.app,
                        "Profile Created",
                        f"Profile '{name}' created successfully!"
                    )

    def show_manage_profiles_dialog(self):
        """Show dialog to manage existing profiles."""
        dialog = ManageProfilesDialog(self, self.app)
        dialog.exec()


class CreateProfileDialog(QDialog):
    """Dialog for creating a new profile with avatar selection."""

    def __init__(self, profile_manager, parent=None):
        super().__init__(parent)
        self.profile_manager = profile_manager
        self.selected_avatar = DEFAULT_PROFILE_AVATARS[0]
        self.name = ""

        self.setWindowTitle("Create Profile")
        self.setModal(True)
        self.setFixedSize(400, 550)

        self._setup_ui()

    def _setup_ui(self):
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # Profile name
        name_label = QLabel("Profile Name:")
        name_label.setStyleSheet(f"font-size: {scaled_area_size('buttons')}pt;")
        layout.addWidget(name_label)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Enter profile name...")
        self.name_input.setMaxLength(20)
        self.name_input.setStyleSheet(f"font-size: {scaled_area_size('buttons')}pt; padding: 5px;")
        layout.addWidget(self.name_input)

        # Avatar selection
        avatar_label = QLabel("Select Avatar:")
        avatar_label.setStyleSheet(f"font-size: {scaled_area_size('buttons')}pt; margin-top: 10px;")
        layout.addWidget(avatar_label)

        # Avatar grid (scrollable)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(300)

        avatar_widget = QWidget()
        avatar_grid = QGridLayout(avatar_widget)
        avatar_grid.setSpacing(10)

        self.avatar_buttons = []

        for i, avatar in enumerate(AVAILABLE_AVATARS):
            row = i // 4
            col = i % 4

            btn = QPushButton()
            btn.setFixedSize(70, 70)
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.setCheckable(True)
            btn.setChecked(i == 0)  # First avatar selected by default

            # Load avatar image
            pixmap = self.profile_manager.get_avatar_pixmap(avatar["file"], size=(50, 50))
            if pixmap:
                btn.setIcon(pixmap)
                btn.setIconSize(QSize(50, 50))
            else:
                btn.setText(avatar["name"][:2])

            btn.clicked.connect(lambda checked=False, av=avatar["file"], idx=i: self._on_avatar_clicked(av, idx))

            avatar_grid.addWidget(btn, row, col)
            self.avatar_buttons.append(btn)

        scroll.setWidget(avatar_widget)
        layout.addWidget(scroll)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        create_btn = QPushButton("Create")
        create_btn.setStyleSheet(get_primary_button_style())
        create_btn.clicked.connect(self._on_create)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(get_secondary_button_style())
        cancel_btn.clicked.connect(self.reject)

        btn_layout.addStretch()
        btn_layout.addWidget(create_btn)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

    def _on_avatar_clicked(self, avatar_path, index):
        """Handle avatar button click."""
        self.selected_avatar = avatar_path

        # Update button states (only one selected)
        for i, btn in enumerate(self.avatar_buttons):
            btn.setChecked(i == index)

    def _on_create(self):
        """Handle create button click."""
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Name Required", "Please enter a profile name.")
            return
        if len(name) > 20:
            QMessageBox.warning(self, "Name Too Long", "Profile name must be 20 characters or less.")
            return

        self.name = name
        self.accept()

    def get_result(self):
        """Get the dialog result (name, avatar)."""
        return self.name, self.selected_avatar


class ManageProfilesDialog(QDialog):
    """Dialog for managing existing profiles."""

    def __init__(self, profile_manager, parent=None):
        super().__init__(parent)
        self.profile_manager = profile_manager

        self.setWindowTitle("Manage Profiles")
        self.setModal(True)
        self.setFixedSize(400, 400)

        self._setup_ui()

    def _setup_ui(self):
        """Set up the dialog UI."""
        theme = get_theme_colors()

        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # Title
        title = QLabel("Your Profiles")
        title.setStyleSheet(
            f"font-size: {scaled_area_size('panel_titles')}pt;"
            f" font-weight: bold; color: {theme['secondary_text']};"
        )
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # Profile list (scrollable)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

        profile_list_widget = QWidget()
        profile_list_layout = QVBoxLayout(profile_list_widget)
        profile_list_layout.setSpacing(5)

        current_profile = self.profile_manager.get_current_profile()
        profiles = self.profile_manager.list_profiles()

        row_bg = theme['secondary']
        text_color = theme['secondary_text']

        for profile in profiles:
            profile_row = QFrame()
            profile_row.setStyleSheet(
                f"background-color: {row_bg}; border-radius: 3px;"
            )
            profile_row.setFixedHeight(50)

            row_layout = QHBoxLayout(profile_row)
            row_layout.setContentsMargins(10, 5, 10, 5)

            # Avatar
            pixmap = self.profile_manager.get_avatar_pixmap(profile["avatar"], size=(32, 32))
            if pixmap:
                avatar_label = QLabel()
                avatar_label.setPixmap(pixmap)
                avatar_label.setFixedSize(32, 32)
                row_layout.addWidget(avatar_label)

            # Name (with checkmark if current)
            prefix = "✓ " if profile["id"] == current_profile else ""
            name_label = QLabel(f"{prefix}{profile['name']}")
            if profile["id"] == current_profile:
                name_label.setStyleSheet(
                    f"font-weight: bold; font-size: {scaled_area_size('sidebar')}pt;"
                    f" color: {text_color};"
                )
            else:
                name_label.setStyleSheet(
                    f"font-size: {scaled_area_size('sidebar')}pt;"
                    f" color: {text_color};"
                )
            row_layout.addWidget(name_label)

            row_layout.addStretch()

            # Delete button (not for default)
            if profile["id"] != "default":
                delete_btn = QPushButton("DELETE")
                delete_btn.setStyleSheet(
                    f"color: red; font-size: {scaled_area_size('buttons')}pt;"
                    f" border: 1px solid red; border-radius: 3px;"
                    f" padding: 4px 12px;"
                )
                delete_btn.clicked.connect(lambda checked=False, pid=profile["id"]: self._on_delete_profile(pid))
                row_layout.addWidget(delete_btn)

            profile_list_layout.addWidget(profile_row)

        profile_list_layout.addStretch()
        scroll.setWidget(profile_list_widget)
        layout.addWidget(scroll)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(get_primary_button_style())
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

    def _on_delete_profile(self, profile_id):
        """Handle delete profile button click."""
        if self.profile_manager.delete_profile(profile_id):
            self.accept()  # Close dialog
            # Reopen to refresh list
            self.profile_manager.show_manage_profiles_dialog()
