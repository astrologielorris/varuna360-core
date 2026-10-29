# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Shared drag-and-drop constants for chart files.

One definition of what counts as a droppable chart file, imported by both
ChartDropTab (tab-body drop = load as active) and TransitDropButton (drop on the
TRANSIT button = overlay). Two copies of the suffix list is exactly how .toml
support gets forgotten on one side. SPEC-IMPORT-001 §6.1 accepts .toml alongside
.chtk.
"""

from pathlib import Path

# Accepted chart file extensions (lowercase). SPEC-IMPORT-001 §6.1.
CHART_FILE_SUFFIXES = (".chtk", ".toml")


def classify_chart_drop(mime):
    """Split a QMimeData's local urls into (chart_files, folders).

    Single classifier shared by ChartDropTab (tab-body drop) and TransitDropButton
    (overlay drop) so the accept rule lives in exactly one place. Both lists are
    Paths; either may be empty.
    """
    files, folders = [], []
    if mime.hasUrls():
        for url in mime.urls():
            if not url.isLocalFile():
                continue
            p = Path(url.toLocalFile())
            if p.is_dir():
                folders.append(p)
            elif p.is_file() and p.suffix.lower() in CHART_FILE_SUFFIXES:
                files.append(p)
    return files, folders


def chart_file_urls(mime):
    """Return local chart-file Paths from a QMimeData (excludes folders)."""
    return classify_chart_drop(mime)[0]


def chart_payload_kind(mime):
    """Classify a drag payload: "memory" | "files" | "folder" | None.

    SPEC-DUAL-001 INV-7 (td-1mgk7): the ONE classifier for every chart drop
    target that accepts and refuses (TRANSIT, the legacy TransitDropButton, the
    chart pill and the chart-B frame). A folder is RECOGNISED so the target
    consumes the drop and refuses it with a message; otherwise Qt would hand it
    to the ChartDropTab ancestor, which loads it as a chart library
    (SPEC-TRN-006 B-3).
    """
    from apps.widgets.chart_memory_button import CHART_ENTRY_MIME
    if mime.hasFormat(CHART_ENTRY_MIME):
        return "memory"
    files, folders = classify_chart_drop(mime)
    if files:
        return "files"
    if folders:
        return "folder"
    return None
