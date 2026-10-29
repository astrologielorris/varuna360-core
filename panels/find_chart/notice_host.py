# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""The Find Chart panel's status notice and chart folder, in every edition
(SPEC-EDN-002 P4). Pro and up extend it with Sort with AI
(``sort_host.SortWithAIMixin``, reached through
``core.edition_features.ai_features``); Lite ships no AI file, so its panel
has this host alone: no UNSORTED DOWNLOADS section, no sort sheet, and the
sort hooks the panel calls do nothing."""

from __future__ import annotations

import os

#: The status bar notice's owner: one slot, the compute failure first.
NOTICE_RETRY = "retry"
NOTICE_MOVED = "moved"
NOTICE_SORT = "sort"


class NoticeHostMixin:
    """The notice slot and the first chart folder (Lite's whole host)."""

    def _create_sort_section(self):
        self._sort_worker = None
        self._sort_pending = False
        self._notice_kind = None
        # Sort with AI's widgets, Pro and up (``SortWithAIMixin``).
        self.unsorted_section = self.sort_flow = self.sort_sheet = None

    def _create_rate_section(self):
        """RATE AND SORT (SPEC-LIB-002) takes the UNSORTED DOWNLOADS slot, in
        every edition. Pro and up: the Sort with AI section moves inside it,
        its path line shown once, at the top of Rate and Sort."""
        from panels.find_chart.rate_sort_host import RateSortController
        self.rate_sort = RateSortController(self, store_file=getattr(self.cache, "path", None))
        self.library.set_unsorted_section(self.rate_sort.view)
        ai_section = getattr(self, "unsorted_section", None)
        if ai_section is not None:
            ai_section.subtitle.hide()
            ai_section.path_label.hide()
            self.rate_sort.view.set_ai_widget(ai_section)

    def _first_folder(self):
        """The Library's first chart folder (the sort and the checks act on it)."""
        fields = getattr(self, "folder_entries", None) or []
        text = fields[0].text().strip() if fields else ""
        return os.path.normpath(text) if text else None

    def _set_notice(self, kind, text="", action=None):
        """The status bar's one notice, with its owner (RETRY wins)."""
        self._notice_kind = kind if text else None
        self.status_bar.set_notice(text, action)

    def refresh_unsorted_downloads(self, force_recount=False):
        """The unsorted downloads' section and notices (Sort with AI)."""

    def _update_sort_banner(self, force_recount=False):
        """Old name (web lookup, results): the Library section now."""
        self.refresh_unsorted_downloads(force_recount=force_recount)

    def _start_sort_request(self):
        """SORT WITH AI: Pro and up."""

    def _open_sort_sheet(self):
        """The Sort with AI sheet (Pro and up)."""

    def _sort_index_rebuilt(self):
        """A REBUILD INDEX finished (Sort with AI's moved notice)."""

    def _stop_sort_worker(self, *, app_quit=False):
        """The sort worker's lifetime (Pro and up)."""
