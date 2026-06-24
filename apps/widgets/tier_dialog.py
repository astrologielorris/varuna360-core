# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Tier Dialog — side-by-side comparison of the three Varuna360 account tiers.

Opened from the Account > View Tiers menu. Non-modal so the user can
keep exploring the app while they read. Shows what each tier unlocks
on the website; does not gate any desktop feature (the desktop runs
every Core feature regardless of account state).

All copy comes from core/pro_marketing.py constants — the SINGLE point
of tier-related text in Core. If the website renames a tier or
changes its features, update pro_marketing.py and this dialog picks
up the change automatically.
"""

from __future__ import annotations

import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from core.pro_marketing import (
    PRO_UPGRADE_URL,
    TIER_ANONYMOUS_FEATURES, TIER_ANONYMOUS_NAME, TIER_ANONYMOUS_PRICE,
    TIER_EXPLORER_FEATURES, TIER_EXPLORER_NAME, TIER_EXPLORER_PRICE,
    TIER_REGISTERED_FEATURES, TIER_REGISTERED_NAME, TIER_REGISTERED_PRICE,
)

from ui.qt_theme import scaled_area_font


class TierDialog(QDialog):
    """Non-modal three-column tier comparison dialog."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Varuna360 — Account Tiers")
        self.setModal(False)
        self.setMinimumWidth(760)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 20, 24, 20)

        # ── Header ──
        header = QLabel("Website Tiers")
        header.setFont(scaled_area_font('panel_titles', bold=True))
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)

        subtitle = QLabel(
            "Account tiers unlock content on the website. The desktop app "
            "runs every Core feature regardless of tier."
        )
        subtitle.setWordWrap(True)
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        # ── Three columns ──
        columns = QHBoxLayout()
        columns.setSpacing(12)
        columns.addWidget(self._make_tier_column(
            TIER_ANONYMOUS_NAME, TIER_ANONYMOUS_PRICE, TIER_ANONYMOUS_FEATURES,
        ))
        columns.addWidget(self._make_tier_column(
            TIER_REGISTERED_NAME, TIER_REGISTERED_PRICE, TIER_REGISTERED_FEATURES,
        ))
        columns.addWidget(self._make_tier_column(
            TIER_EXPLORER_NAME, TIER_EXPLORER_PRICE, TIER_EXPLORER_FEATURES,
        ))
        layout.addLayout(columns)

        # ── Footer buttons ──
        footer = QHBoxLayout()
        footer.setSpacing(8)

        subscribe_btn = QPushButton("Subscribe at 360heartsinthesky.com")
        subscribe_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        subscribe_btn.clicked.connect(self._on_subscribe_clicked)
        footer.addWidget(subscribe_btn)

        footer.addStretch(1)

        close_btn = QPushButton("Close")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)

        layout.addLayout(footer)

    def _make_tier_column(
        self, name: str, price: str, features: tuple[str, ...],
    ) -> QFrame:
        """Build a single tier column widget."""
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        col_layout = QVBoxLayout(frame)
        col_layout.setSpacing(6)
        col_layout.setContentsMargins(14, 14, 14, 14)

        name_label = QLabel(name)
        name_label.setFont(scaled_area_font('tables', bold=True))
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col_layout.addWidget(name_label)

        price_label = QLabel(price)
        price_label.setFont(scaled_area_font('tables'))
        price_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col_layout.addWidget(price_label)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        col_layout.addWidget(separator)

        for feature in features:
            bullet = QLabel(f"•  {feature}")
            bullet.setWordWrap(True)
            col_layout.addWidget(bullet)

        col_layout.addStretch(1)
        return frame

    def _on_subscribe_clicked(self) -> None:
        """Open the subscription page in the default browser."""
        webbrowser.open(PRO_UPGRADE_URL)
