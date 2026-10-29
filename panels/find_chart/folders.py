# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The folder list (design.md §4.9), shown in the Library sheet
(SPEC-FIND-005 §3.7): three chart folders with a checkbox each, plus "Loaded
charts (no file)" for the session charts that have no file. Saving the list writes
``paths.chart_folders``; it never starts a scan (FIND-003 §3.4).
"""

import os

from PySide6.QtWidgets import QFileDialog

from core.settings_registry import default as registry_default
from managers import find_chart_sync
from panels.find_chart import kit, states
from panels.find_chart import workers as fc_workers
from panels.find_chart.library import FILELESS_LABEL, LibraryContent  # noqa: F401

#: The Library sheet's width (x the larger of the bar and info_text scales):
#: 460 + 100 so the Rate and Sort card has room (Lorris, 2026-10-29).
LIBRARY_W = 560
#: Removed folders still owed a forget (``_folders_changed``).
FORGET_OWED_KEY = "ui.find_chart_forget_owed"


class FolderListMixin:
    """``FindChartPanel``'s folder list, now in the Library sheet
    (SPEC-FIND-005 §3.7, W8): ``folder_entries``, ``folder_checkboxes`` and
    ``fileless_checkbox`` are the Library's own widgets."""

    def _create_folder_section(self, parent_layout=None):
        """The Library sheet (LIBRARY opens it): database, the three folder
        slots and "Loaded charts (no file)", the index and coverage. The
        sheet floats over the panel, so ``parent_layout`` gets nothing."""
        self.library_sheet = kit.Sheet(self, "Library", width=LIBRARY_W, text_area="info_text")
        self.library = LibraryContent()
        self.library_sheet.content_layout.addWidget(self.library)
        lib = self.library
        self.folder_entries = lib.folder_fields()
        self.folder_checkboxes = lib.folder_checks()
        self.fileless_checkbox = lib.fileless_check()
        self._browse_buttons = lib.browse_buttons()
        self._remove_buttons = lib.remove_buttons()
        self.rebuild_btn = lib.rebuild_button
        self.index_btn = lib.index_menu_button
        lib.browse_requested.connect(
            lambda i: self._browse_folder(self.folder_entries[i])
        )
        lib.remove_requested.connect(self._remove_folder_slot)
        lib.folders_edited.connect(self._on_folder_list_edited)
        lib.checks_changed.connect(self._on_scope_changed)  # quiet (INV-3)
        lib.rebuild_requested.connect(self._rebuild_index)
        lib.refresh_requested.connect(self._rebuild_index)
        lib.full_rebuild_requested.connect(self._full_rebuild_index)
        lib.show_location_requested.connect(self._open_index_folder)
        lib.export_requested.connect(self._export_index)
        lib.import_requested.connect(self._import_index)
        lib.coverage_action_requested.connect(self._on_coverage_action)
        lib.compute_everything_requested.connect(self._on_compute_everything)
        lib.settings_requested.connect(self._open_compute_settings)
        lib.set_database(str(self.cache.path))

    def _add_folder_entry(self):
        """Kept for old callers: the Library has exactly three slots."""
        return None

    def _remove_folder_slot(self, i):
        """The slot's x: empty it, save the list, refresh quietly."""
        if not 0 <= i < len(self.folder_entries):
            return
        self.folder_entries[i].setText("")
        self._on_folder_list_edited()

    def _browse_folder(self, entry_widget):
        """Open folder browser dialog."""
        # Determine initial directory
        current_path = entry_widget.text().strip()
        if current_path and os.path.isdir(current_path):
            initial_dir = current_path
        else:
            # Try to use first configured folder, or home directory
            for e in self.folder_entries:
                path = e.text().strip()
                if path and os.path.isdir(path):
                    initial_dir = path
                    break
            else:
                initial_dir = os.path.expanduser("~")

        folder = QFileDialog.getExistingDirectory(
            self, "Select CHTK Folder", initial_dir, QFileDialog.Option.ShowDirsOnly
        )

        if folder:
            entry_widget.setText(folder)
            self._on_folder_list_edited()
            self.index_status.setText("Folder added. Click REBUILD INDEX to index it.")

    def _on_folder_list_edited(self):
        """A path typed (committed), browsed or removed: ONE quiet scope
        change (review r8 #4): the revision, the list saved, the search shown
        again with no compute (a pending debounce stays quiet, INV-3). A
        folder that left the list takes its charts out of the index at once
        (varuna/43), and that sync's completion refreshes quietly too; no
        scan, so no consent needed (FIND-003 §3.4). An added folder waits
        for REBUILD INDEX."""
        before = self._configured_folders()
        self._save_folder_paths()
        after = self._configured_folders()
        if after == before:
            return  # a field left without a change (focus out): nothing to do
        self._bump_revision()  # the folder list is part of the query
        self._folders_changed(before, after)
        self._refresh_quietly()

    def _folders_changed(self, before, after):
        """The saved folder list went from ``before`` to ``after``. A folder
        that left is out of every scope at once (``Scope.forgetting``: its
        FILE entries, unless loaded) and the app's sync takes its files out
        of the index (no scan, no compute). The removed folder is saved
        (``FORGET_OWED_KEY``) until that forget commits, so a failed forget
        or a new panel keeps it out and the next opening asks again
        (review r10); a failure is shown."""
        removed = set(before) - set(after)
        owed = set(self._forget_owed())
        if owed & set(after):  # put back on the list: no longer owed
            owed -= set(after)
            self._save_forget_owed(owed)
        app_sync = find_chart_sync.current()
        if app_sync is not None and set(before) != set(after):
            # A queued forget read the old list: it must not run (r12). The
            # generation also dates each removal, so only a forget asked
            # after it may settle it (review r13).
            generation = app_sync.folder_list_changed()
            for root in removed:
                app_sync.removed_at[root] = generation
        if not removed:
            # An add-only change superseded any queued forget (review r14):
            # whatever is still owed is asked again against the new list.
            if self._forgetting() and app_sync is not None:
                self._request_forget(app_sync, after)
            return
        self._save_forget_owed(owed | removed)
        if self._index_worker is not None:
            # A rebuild read the old list (review r11): it is cancelled (no
            # write before its commit point; after it, no compute), and the
            # forget waits until that writer is done, so its commit can never
            # republish the removed folder after the forget.
            self._index_worker.cancel()
            return
        if app_sync is not None:
            self._request_forget(app_sync, after)

    def _after_index_writer(self):
        """The folder sync ended (any way): a forget owed meanwhile runs now."""
        app_sync = find_chart_sync.current()
        if app_sync is not None:
            self._ask_forget_owed(app_sync)

    def _forget_owed(self):
        from managers.settings_manager import get_settings

        owed = get_settings().get(FORGET_OWED_KEY, registry_default(FORGET_OWED_KEY))
        return [os.path.normpath(p) for p in owed if isinstance(p, str) and p]

    def _save_forget_owed(self, owed):
        from managers.settings_manager import get_settings

        get_settings().set(FORGET_OWED_KEY, sorted(owed))

    def _forgetting(self):
        """Removed folders still owed a forget, unless back in the list."""
        listed = set(self._configured_folders())
        return tuple(sorted(r for r in self._forget_owed() if r not in listed))

    def _ask_forget_owed(self, app_sync):
        """At opening: a forget that failed or never ran is asked again."""
        if self._forgetting():
            self._request_forget(app_sync, self._configured_folders())

    def _request_forget(self, app_sync, roots):
        if self._index_worker is not None or fc_workers.folder_writer_parked():
            # A folder sync from an older list may still publish (review
            # r12): the forget waits (the debt stays saved) and any queued
            # one is superseded; the sync's end or the next opening asks.
            app_sync.folder_list_changed()
            return
        owed = frozenset(self._forget_owed())  # what this forget may settle
        job = app_sync.folders_changed(roots, self._current_session())
        if job is None:
            return
        settled = (owed, getattr(job, "generation", None))
        def done(j):
            if j.cancelled():
                outcome = False
            elif isinstance(j.exception(), find_chart_sync.ForgetSuperseded):
                outcome = None  # a later change owns the outcome
            else:
                outcome = j.exception() is None
            try:
                self._folders_forgotten.emit(settled, outcome)
            except RuntimeError:  # the panel is gone: the next one asks again
                pass

        job.add_done_callback(done)

    def _on_folders_forgotten(self, settled, ok):
        """The forget committed (``ok`` True): the folders it settled are no
        longer owed, and the view refreshes quietly. It failed (False): they
        stay owed (and out of the results), and the error says so.
        Superseded (None): a later folder change owns the outcome. A success
        clears only the removals made before it was asked (review r13: a
        root removed again since, by a later removal, stays owed until that
        removal's own forget commits)."""
        if ok is None:
            return
        if ok:
            owed, generation = settled
            app_sync = find_chart_sync.current()
            removed_at = getattr(app_sync, "removed_at", {})
            done = {
                root for root in owed
                if generation is None or removed_at.get(root, 0) < generation
            }
            self._save_forget_owed(set(self._forget_owed()) - done)
        self._bump_revision()
        self._store_changed()
        self._refresh_quietly()
        if not ok:
            self.status_bar.set_state(states.FORGET_FAILED_TEXT, states.ERROR)

    @staticmethod
    def _configured_folders():
        """The saved folder list, checked or not: the index's folder sources."""
        from managers.settings_manager import get_settings
        from utils.path_translator import translate_path

        return [
            os.path.normpath(translate_path(folder) or folder)
            for folder in get_settings().get_chart_folders()
            if folder
        ]

    def _get_checked_folders(self):
        """Get list of folder paths that are checked."""
        return self._folders_ticked(True)

    def _get_unchecked_folders(self):
        """Folder paths that are unticked: Sources All hides them (varuna/43)."""
        return self._folders_ticked(False)

    def _folders_ticked(self, ticked):
        folders = []
        for entry, checkbox in zip(self.folder_entries, self.folder_checkboxes):
            if checkbox.isChecked() == ticked:
                path = entry.text().strip()
                if path:
                    folders.append(os.path.normpath(path))
        return folders

    def _filter_redundant_subfolders(self, folder_paths):
        """
        Filter out folders that are subfolders of other folders in the list.
        This prevents redundant indexing when one path contains another.
        """
        if not folder_paths:
            return []

        # Normalize all paths
        normalized = [(os.path.normpath(p), p) for p in folder_paths if p]
        if not normalized:
            return []

        # Sort by path length (shortest first = parent folders first)
        normalized.sort(key=lambda x: len(x[0]))

        # Keep only folders that are not subfolders of others
        root_folders = []
        for norm_path, orig_path in normalized:
            is_subfolder = False
            for root in root_folders:
                # Check if norm_path is inside root
                if norm_path.startswith(root + os.sep) or norm_path == root:
                    is_subfolder = True
                    break
            if not is_subfolder:
                root_folders.append(norm_path)

        # Return original paths for the root folders
        result = []
        for norm_path, orig_path in normalized:
            if norm_path in root_folders:
                result.append(orig_path)
        return result

    def _load_folder_paths(self):
        """Load chart folder paths via SettingsManager (single source of truth)."""
        from managers.settings_manager import get_settings
        from utils.path_translator import translate_path

        s = get_settings()
        folders = s.get_chart_folders()
        paths = [translate_path(f) or "" if f else "" for f in folders]

        before = [field.text() for field in self.folder_entries]
        shown = [os.path.normpath(t.strip()) for t in before if t.strip()]
        for i, field in enumerate(self.folder_entries):  # three slots
            field.setText(paths[i] if i < len(paths) else "")
        loaded = getattr(self, "_folders_loaded", False)
        self._folders_loaded = True
        if loaded and before != [field.text() for field in self.folder_entries]:
            # Settings changed the folders: a query change, shown quietly
            # (review r7 #11); never a scan. A removed folder's charts leave
            # the index as with the Library's own x (review r8 #4).
            self._bump_revision()
            self._folders_changed(shown, self._configured_folders())
            self._refresh_quietly()

    def _save_folder_paths(self):
        """Save chart folder paths via SettingsManager (single source of truth)."""
        from managers.settings_manager import get_settings

        paths = [e.text().strip() for e in self.folder_entries]
        while len(paths) < 3:
            paths.append("")
        paths = paths[:3]

        s = get_settings()
        s.set_chart_folders(paths)
        print(
            f"[FIND CHART] Saved {len([p for p in paths if p])} folder paths via SettingsManager"
        )
