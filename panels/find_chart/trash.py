# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Move a chart file to the trash folder, moved from ``find_chart_panel``
(design.md §4.9). One file the app itself moved: the store forgets its entry
(FIND-003 §3.5) and the results refresh when it has.
"""

from PySide6.QtWidgets import QMessageBox
from panels.find_chart import kit

from managers import find_chart_sync


class TrashMixin:
    """``FindChartPanel``'s "Move to trash"."""

    def _move_chart_to_trash(self, filepath):
        """Move a chart file to the trash folder (no deletion)."""
        import shutil
        from pathlib import Path

        trash_dir = Path(self._database_path) / "trash"
        trash_dir.mkdir(exist_ok=True)

        src = Path(filepath)
        if not src.exists():
            return

        # Unique destination name to avoid collisions
        dst = trash_dir / src.name
        counter = 1
        while dst.exists():
            dst = trash_dir / f"{src.stem}_{counter}{src.suffix}"
            counter += 1

        try:
            shutil.move(str(src), str(dst))
            app_sync = find_chart_sync.current()
            if app_sync is not None:
                self._refresh_when_done(app_sync.file_removed(src))
            kit.message(
                self, QMessageBox.Icon.Information, "Moved to Trash", f"'{src.name}' moved to trash folder."
            )
        except Exception as e:
            kit.message(self, QMessageBox.Icon.Warning, "Error", f"Failed to move to trash: {e}")
