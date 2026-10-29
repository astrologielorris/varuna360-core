"""Chart tab widget that accepts drag-and-drop of chart files and folders.

Dropping one or more .chtk or .toml files adds them all to chart memory and
displays ONLY the last one: the others go in silently through the Chart Memory
Panel's add_chart_files_silently (the Load Folder path), then the last file is
loaded via ChartManager.load_chart. Displaying each dropped chart in turn only
to replace it with the next was wasted work the user watched.

Dropping a folder reuses the Chart Memory Panel's load_folder_charts_from_path,
the same core used by the "📁 Load Folder" button. No loader logic is
duplicated here — this widget only dispatches.

SPEC-TRN-006: a chart file dropped on the TRANSIT button overlays it on the
active chart instead of loading it as active. That is handled by TransitDropButton
(a child of this tab); Qt delivers the drop to the deepest accepting widget, so
once the button accepts drops it wins over this ancestor. Tab-body drops keep the
load-as-active behavior below unchanged.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from apps.widgets.chart_drop_common import classify_chart_drop


class ChartDropTab(QWidget):
    """QWidget subclass for the main chart tab with CHTK drag-and-drop support."""

    def __init__(self, gui, parent=None):
        super().__init__(parent)
        self._gui = gui
        self.setAcceptDrops(True)

    def _collect_paths(self, mime):
        """Return (chtk_files, folders) from a QMimeData, or (None, None) if unsupported.

        Classification is shared with TransitDropButton via classify_chart_drop
        (SPEC-IMPORT-001 §6.1 / SPEC-TRN-006) — one accept rule, no duplicate lists.
        """
        chtk_files, folders = classify_chart_drop(mime)
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
        *background, last = chtk_files or [None]
        panel = getattr(self._gui, "memory_panel_instance", None)

        def _show_last(_last_added_id=None):
            nonlocal loaded, failed
            try:
                self._gui.chart_manager.load_chart(last)
                loaded += 1
            except Exception:
                failed += 1

        if background and panel is not None and hasattr(panel, "add_chart_files_silently"):
            # Add the others to memory without drawing them, then draw the last
            # one while the loading overlay is still up.
            bg_loaded, bg_failed = panel.add_chart_files_silently(
                background, f"Loading {len(chtk_files)} charts...", then=_show_last)
            loaded += bg_loaded
            failed += bg_failed
        elif last is not None:
            for chtk_path in background:
                try:
                    self._gui.chart_manager.load_chart(chtk_path)
                    loaded += 1
                except Exception:
                    failed += 1
            _show_last()

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
