"""Chart tab widget that accepts drag-and-drop of CHTK files and folders.

Dropping one or more .chtk files loads each via ChartManager.load_chart; the
last one becomes the active chart (mirrors the menu's Open Chart behavior
with multi-select). Dropping a folder reuses the Chart Memory Panel's
load_folder_charts_from_path, the same core used by the "📁 Load Folder"
button. No loader logic is duplicated here — this widget only dispatches.
"""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget


class ChartDropTab(QWidget):
    """QWidget subclass for the main chart tab with CHTK drag-and-drop support."""

    def __init__(self, gui, parent=None):
        super().__init__(parent)
        self._gui = gui
        self.setAcceptDrops(True)

    def _collect_paths(self, mime):
        """Return (chtk_files, folders) from a QMimeData, or (None, None) if unsupported."""
        if not mime.hasUrls():
            return None, None

        chtk_files = []
        folders = []
        for url in mime.urls():
            if not url.isLocalFile():
                continue
            p = Path(url.toLocalFile())
            if p.is_dir():
                folders.append(p)
            elif p.is_file() and p.suffix.lower() == ".chtk":
                chtk_files.append(p)

        if not chtk_files and not folders:
            return None, None
        return chtk_files, folders

    def dragEnterEvent(self, event):
        chtk_files, folders = self._collect_paths(event.mimeData())
        if chtk_files or folders:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        chtk_files, folders = self._collect_paths(event.mimeData())
        if chtk_files or folders:
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event):
        chtk_files, folders = self._collect_paths(event.mimeData())
        if not chtk_files and not folders:
            super().dropEvent(event)
            return

        event.acceptProposedAction()

        for folder in folders:
            panel = getattr(self._gui, "memory_panel_instance", None)
            if panel is not None and hasattr(panel, "load_folder_charts_from_path"):
                try:
                    panel.load_folder_charts_from_path(str(folder))
                except Exception as exc:
                    self._status(f"Failed to load folder {folder.name}: {exc}")
            else:
                self._status("Chart Memory Panel unavailable — cannot load folder.")

        loaded = 0
        failed = 0
        for chtk_path in chtk_files:
            try:
                self._gui.chart_manager.load_chart(chtk_path)
                loaded += 1
            except Exception:
                failed += 1

        if chtk_files:
            if failed == 0:
                self._status(f"Loaded {loaded} chart(s) via drag-and-drop")
            else:
                self._status(f"Loaded {loaded} chart(s), {failed} failed")

    def _status(self, message):
        try:
            self._gui.statusBar().showMessage(message, 5000)
        except Exception:
            pass
