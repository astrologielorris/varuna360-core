# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The chart-database warning in Settings (SPEC-PERSIST-001 INV-6, td-rx09).

The status bar says "this chart did not save". This says "your chart database
is not working", and it is still saying it after a restart — which is the
whole point, because the status message is gone by then and every chart made
in the meantime is session-only.

It reads `managers.persist_health`, which the creation pipeline writes at
both of its exits: a failure records, a success resolves. So this banner
disappears on its own the moment a chart saves normally, and "Check again"
exists for the user who fixed the folder and does not want to make a chart
to find out.

Two conventions borrowed from ui/session_health_banner.py rather than
reinvented: semantic red is the Rule 20 exemption, and the widget is styled
through `setObjectName` because a QSS type selector naming a Python class
matches nothing in PySide6 and fails silently.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ui.qt_theme import hex_to_rgb_str
from ui.themed_style import ThemedStyleMixin

ERROR_RED = "#D9534F"


class ChartWriteBanner(ThemedStyleMixin, QFrame):
    """Hidden unless there is an unresolved chart-write failure."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("chartWriteBanner")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._build_ui()
        self._apply_theme()
        self.refresh()

    # -- construction ----------------------------------------------------

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(8)

        self.headline = QLabel("Charts are not being saved to files")
        f = QFont()
        f.setPointSize(11)
        f.setBold(True)
        self.headline.setFont(f)
        self.headline.setWordWrap(True)
        outer.addWidget(self.headline)

        self.body = QLabel(
            "Charts you create are kept in this session only, so they will "
            "not come back after a restart and there is no file to open in "
            "Kala. Everything else works normally, and the chart files you "
            "already have have not been touched."
        )
        self.body.setWordWrap(True)
        bf = QFont()
        bf.setPointSize(9)
        self.body.setFont(bf)
        outer.addWidget(self.body)

        # The folder and the raw error, selectable: the first thing anyone
        # does with an error string is copy it.
        self.detail = QLabel("")
        self.detail.setWordWrap(True)
        self.detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        df = QFont("monospace")
        df.setPointSize(8)
        self.detail.setFont(df)
        outer.addWidget(self.detail)

        row = QHBoxLayout()
        row.addStretch()
        self.check_button = QPushButton("Check again")
        self.check_button.setToolTip(
            "Try to write a small test file in the chart folder.")
        self.check_button.clicked.connect(self._on_check)
        row.addWidget(self.check_button)
        self.dismiss_button = QPushButton("Dismiss")
        self.dismiss_button.setToolTip(
            "Hide this until the next time a chart fails to save.")
        self.dismiss_button.clicked.connect(self._on_dismiss)
        row.addWidget(self.dismiss_button)
        outer.addLayout(row)

    def _apply_theme(self):
        # _register_themed takes a CALLABLE that re-reads the theme on every
        # replay — a pre-rendered string would freeze whatever palette was
        # live at construction time and never update on a theme switch.
        def frame_style():
            tint = hex_to_rgb_str(ERROR_RED)
            return (f"#chartWriteBanner {{ background-color: rgba({tint}, 0.12); "
                    f"border-left: 3px solid {ERROR_RED}; border-radius: 4px; }}")

        self._register_themed(self, frame_style)
        self._register_themed(
            self.headline, lambda: f"QLabel {{ color: {ERROR_RED}; }}")

    # -- state -----------------------------------------------------------

    def refresh(self):
        """Show or hide from the persisted record. Never raises.

        The Settings page must open even when the record is unreadable —
        a warning system that can crash the page it lives on is worse than
        no warning.
        """
        try:
            from managers.persist_health import last_write_failure
            failure = last_write_failure()
        except Exception:
            failure = None
        if not failure:
            self.setVisible(False)
            return
        folder = failure.get("folder") or "(no folder could be resolved)"
        when = failure.get("when") or ""
        name = failure.get("chart_name") or ""
        lines = [f"Folder: {folder}", f"Error:  {failure.get('message', '')}"]
        if name:
            lines.append(f"Chart:  {name}")
        if when:
            lines.append(f"When:   {when}")
        self.detail.setText("\n".join(lines))
        self.setVisible(True)

    def _on_check(self):
        from managers.persist_health import probe_chart_folder
        ok, message = probe_chart_folder()
        if ok:
            self.setVisible(False)
            return
        # Still broken: replace the stored error with what we just learned,
        # so the banner reflects the CURRENT state rather than the first
        # failure of the week.
        from managers.persist_health import record_write_failure
        record_write_failure(message)
        self.refresh()

    def _on_dismiss(self):
        from managers.persist_health import clear_write_failure
        clear_write_failure()
        self.setVisible(False)
