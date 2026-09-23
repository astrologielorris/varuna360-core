"""apps/widgets/hd_view_placeholder.py — page-5 stand-in until the real HD view merges.

The Human Design view (``apps.widgets.hd.hd_bodygraph_view.HDBodygraphView``) is
built on the design branch (SPEC-HD-001 WI-4/5). Until that branch merges into
this one, ``core_gui_qt`` imports the real view behind a try/except seam and
falls back to this placeholder, so the HD page exists at index 5 and the wiring
(shortcut, remote, manager, F2 exclusion) can be validated end-to-end now. When
the real view lands, the seam picks it up with no wiring change.

It honours the same call the GUI makes on the real view — ``update_from_chart``,
which for the HD view takes the HDModel dict as its first argument — so the
activation branch is identical for placeholder and real widget.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class HDViewPlaceholder(QWidget):
    """Neutral stand-in for the Human Design page (see module docstring)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label = QLabel("Human Design BodyGraph\n(view in progress)")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._label)
        self._model = None

    def update_from_chart(self, chart, **kwargs) -> None:
        """Accept the HDModel dict the GUI passes; show a one-line summary.

        Signature matches the real view so the activation branch is identical.
        """
        self._model = chart or None
        model = self._model
        if isinstance(model, dict):
            self._label.setText(
                "Human Design BodyGraph (view in progress)\n"
                f"type: {model.get('type', '?')}   "
                f"authority: {model.get('authority', '?')}\n"
                f"profile: {model.get('profile', '?')}   "
                f"frame: {model.get('frame', '?')}"
            )
        else:
            self._label.setText("Human Design BodyGraph\n(no chart loaded)")
