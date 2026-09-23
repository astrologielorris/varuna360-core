"""PROFILE menu/avatar methods, extracted from ChartGUI (Stage 1b W6-A,
move-only SPLIT of the MENUS & PROFILE cluster).

Only the 4 PROFILE methods moved here in W6-A. `_create_menus` (the 363-line
menu builder) was retained in ChartGUI at the time because it referenced
VARGA_NAMES, then defined in core_gui_qt.py (a core->mixin->core import cycle if
moved). That blocker was removed in Stage 1d (td-gl6y de-dup'd VARGA_NAMES to
core.varga_codes), and `_create_menus` was then extracted to its own move-only
mixin `apps/gui_mixins/menu_builder.py` (`MenuBuilderMixin`, td-6azk) — so the
MENUS & PROFILE cluster is now fully extracted. Bodies moved byte-identically;
imports are module-top for AST-identity (cycle-checked).
"""

import sys
from pathlib import Path
from PySide6.QtCore import QProcess, QSize
from PySide6.QtGui import QIcon
from ui.qt_theme import get_theme_colors, scaled_px


class ProfileMenuMixin:
    """Profile menu/avatar behaviour for ChartGUI (see module docstring)."""

    def _restart_app(self):
        """Restart the application with the same command-line arguments."""
        # Close the window
        self.close()

        # Use QProcess to restart the app with original arguments (includes -d flag)
        QProcess.startDetached(
            sys.executable,
            self.original_argv,
            Path.cwd().as_posix()
        )

    def _show_profile_menu(self):
        """Show profile dropdown menu from profile button."""
        if hasattr(self, 'profile_manager'):
            # Get button global position
            button_pos = self.profile_button.mapToGlobal(self.profile_button.rect().bottomLeft())
            self.profile_manager.show_profile_menu(self, button_pos)
        else:
            pass

    def _update_profile_button_style(self):
        """Update profile button styling with current theme colors."""
        # SPEC-THM-001 E5: get_theme_colors imported at module level.
        theme = get_theme_colors()

        self.profile_button.setStyleSheet(f"""
            QPushButton {{
                border-radius: 18px;
                background-color: {theme["secondary"]};
                color: {theme["secondary_text"]};
                font-size: {scaled_px(16)}px;
                border: 1px solid {theme["primary"]};
            }}
            QPushButton:hover {{
                background-color: {theme["primary"]};
                color: {theme["primary_text"]};
            }}
        """)

    def _load_profile_avatar(self):
        """Load avatar image for profile button from ProfileManager."""
        if not hasattr(self, 'profile_manager'):
            self.profile_button.setText("👤")
            return

        try:
            profile_data = self.profile_manager.get_profile_data()
            if not profile_data:
                self.profile_button.setText("👤")
                return

            avatar_path = profile_data.get("avatar", "img/planets/sun.webp")

            # Load avatar at full button size for visibility
            pixmap = self.profile_manager.get_avatar_pixmap(avatar_path, size=(36, 36))

            if pixmap and not pixmap.isNull():
                icon = QIcon(pixmap)

                # Set icon and remove text
                self.profile_button.setIcon(icon)
                self.profile_button.setIconSize(QSize(36, 36))  # Full button size
                self.profile_button.setText("")  # Clear text to show icon

                # Force visibility and bring to front
                self.profile_button.show()
                self.profile_button.raise_()
                self.profile_button.update()
                self.profile_button.repaint()
            else:
                # Ensure emoji is visible if avatar fails
                self.profile_button.setText("👤")
                self.profile_button.setIcon(QIcon())  # Clear any null icon
                self.profile_button.show()
                self.profile_button.raise_()
        except Exception as e:
            print(f"Error loading profile avatar: {e}")
            # Ensure emoji is visible on error
            self.profile_button.setText("👤")
            self.profile_button.setIcon(QIcon())  # Clear any null icon
            self.profile_button.show()
            self.profile_button.raise_()
            import traceback
            traceback.print_exc()
