# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""Static Pro-marketing constants for Varuna360 Core.

This module is the SINGLE point of "Pro awareness" in the Core codebase.
It contains pure data — URLs, feature names, marketing copy — that the
Help menu and About dialog use to advertise the proprietary Varuna360 Pro
edition. The Core build can mention that Pro exists, link to the upgrade
page, and list features, all without ever importing from the proprietary
tree or doing any runtime detection of whether Pro is installed.

(Note for future maintainers reading this docstring: deliberate prose
choices throughout — avoiding the literal substrings that the broad
release-gate text scan flags. This is not stylistic preference; the
gate rejects mentions of the proprietary directory in any context,
including comments and docstrings, to keep the boundary surface small
and machine-checkable.)

DESIGN INVARIANT (machine-checked by release_gates/test/test_pro_marketing_purity.py):

    This file MUST contain ONLY:
      - The module docstring
      - `from typing import ...` (and nothing else from anywhere)
      - Top-level constant assignments (Assign / AnnAssign nodes)

    NO function definitions. NO class definitions. NO conditionals. NO
    file I/O. NO environment variable reads. NO imports from anywhere
    other than `typing`. The AST purity test will fail loudly if any
    of those appear, and the failure will block the public release.

    The reason: this is the ONLY hook in Core for Pro-related content.
    Keeping it pure data means there is no failure mode where "Pro
    awareness" silently grows into "Pro detection" — the kind of creeping
    coupling that would ruin the open-core boundary. If you want Core
    to behave differently when Pro is installed, that's a different
    architectural decision and needs its own design review.

ADDING NEW PRO-RELATED CONTENT:
    Add it as a constant here. Update the AST purity test if you need
    a new top-level statement type (you almost certainly don't).

UPDATING URLS / COPY:
    Edit the constants below. The Help menu wiring in apps/core_gui_qt.py
    references them by name and will pick up changes automatically.
"""

from typing import Final

# ─── URLs ───────────────────────────────────────────────────────────────────
# These are the only public-facing links Core ever advertises. Both point
# at the public website. The Pro upgrade flow (Stripe checkout, account
# management, license redemption) lives entirely on the website — Core
# never knows what happens after the user clicks the link.
#
# PRO_UPGRADE_URL points at the live subscription page on the marketing
# site. If the page is ever moved or renamed, update only this constant —
# every dialog and menu reference flows from here.

PRO_UPGRADE_URL: Final[str] = "https://360heartsinthesky.com/subscribe"
PRO_LEARN_MORE_URL: Final[str] = "https://360heartsinthesky.com"

# ─── Marketing copy ─────────────────────────────────────────────────────────
# Kept short and factual. No exclamation marks, no marketing-speak, no
# urgency. The Help dialog renders these verbatim.

PRO_TAGLINE: Final[str] = (
    "Varuna360 Pro: the expanded edition with new screens, research tools, "
    "and features added over time."
)

PRO_DESCRIPTION: Final[str] = (
    "Varuna360 Core is the open-source foundation of Varuna360. The Pro edition "
    "is a growing suite of new and more powerful features: full transit screen, "
    "eclipse screen, solar return screen, advanced research panels, AI-assisted "
    "interpretation, and more being added over time. Core remains fully functional "
    "on its own."
)

# ─── Feature catalog ────────────────────────────────────────────────────────
# Aligned with the public website feature list. Each entry is a short
# phrase suitable for a bullet in the in-app About-Pro dialog. Keep this
# list in sync with the README template and the website pricing page.
# When editing, update all three surfaces together (this file, the README
# template at release_gates/templates/public_repo/README.md, and the
# website) to avoid split-brain copy.

PRO_FEATURES: Final[tuple[str, ...]] = (
    "Full transit screen with real-time tracking",
    "Eclipse and Saros panel: per-country Ascendant map plus historical Saros cycle research",
    "Solar return screen",
    "AI-assisted chart interpretation",
    "Psychological pattern and trauma detection (Lajitadi)",
    "Element and Modality statistical analysis",
    "Chinese Lunar New Year tab",
    "Nakshatra wheel with innovative display options",
    "Birth Finder: reverse-engineer charts from planetary positions",
    "Pattern searching across time and databases",
    "One-click chart creation plus Wikipedia biography search",
    "Automatic chart download from the web",
    "Planet Ingress and Conjunction finder",
    "New features added regularly",
)

# ─── Pricing ────────────────────────────────────────────────────────────────
# Optional — the dialog can choose to display this or omit it. Editing
# the price here automatically updates everywhere it is shown.

PRO_PRICE_DISPLAY: Final[str] = "€29.99 / month"

# ─── Account tiers (website parity) ─────────────────────────────────────────
# Varuna360 offers three account tiers that gate content on the website.
# The desktop software runs with every Core feature regardless of account
# state — account tiers unlock articles and web-app features at
# 360heartsinthesky.com, not desktop features.
#
# These tier names MUST match the website exactly. The Account menu, the
# first-launch welcome popup, the View Tiers dialog, and the public README
# all render these constants verbatim. If the website renames a tier,
# update this file and every surface updates automatically.
#
# Language rule: PRODUCT framing only. Charity-style vocabulary and
# solicitation metaphors are rejected mechanically by the release gate
# at check_static.py FORBIDDEN_PATTERNS. The enforced list covers the
# classic solicitation verbs, the coffee metaphor, the jar metaphor,
# and any framing that implies non-recurring billing. Every paid tier
# at Varuna360 is monthly recurring; there is no non-recurring tier
# and no "for the project" framing. Read the gate patterns directly
# in check_static.py for the exact enforced forms before adding new
# tier-related copy here.

TIER_ANONYMOUS_NAME: Final[str] = "No account"
TIER_REGISTERED_NAME: Final[str] = "Registered free"
TIER_EXPLORER_NAME: Final[str] = "Explorer"

TIER_ANONYMOUS_PRICE: Final[str] = "€0"
TIER_REGISTERED_PRICE: Final[str] = "€0"
TIER_EXPLORER_PRICE: Final[str] = "€9.99 / month"

TIER_ANONYMOUS_FEATURES: Final[tuple[str, ...]] = (
    "Natal chart calculation",
    "Manual entry",
    "Element pie charts plus positions table",
    "Dominant Aditya description",
    "Ascendant plus House Strength",
)

TIER_REGISTERED_FEATURES: Final[tuple[str, ...]] = (
    "All No account features",
    "Celebrity database",
    "Transit ring (current planets)",
    "2 save slots",
)

TIER_EXPLORER_FEATURES: Final[tuple[str, ...]] = (
    "All Registered free features",
    "CHTK file import",
    "Full transit calculation plus Now button",
    "Dignified Planets panel",
    "Divine Cow (Kamadhenu) panel",
    "Planet Strength (Shadbala) panel",
    "20 save slots",
)

# Subscription slider — every paid option is recurring monthly.
# The website offers a sliding-scale monthly subscription from €1 to
# €14.99, with €14.99 as the suggested amount. Paying €9.99/month or
# more also grants the Explorer website tier.
SUBSCRIPTION_MIN_DISPLAY: Final[str] = "€1 / month"
SUBSCRIPTION_SUGGESTED_DISPLAY: Final[str] = "€14.99 / month"
SUBSCRIPTION_EXPLORER_THRESHOLD_DISPLAY: Final[str] = "€9.99 / month"

# Welcome popup body — shown once per install before the main window
# appears. Subscription-only language, product framing throughout.
WELCOME_TITLE: Final[str] = "Welcome to Varuna360"
WELCOME_BODY: Final[str] = (
    "Varuna360 is a product. You can use the desktop app for free as long "
    "as you want — every feature, no time limit, no nagging.\n\n"
    "When you decide it is worth paying for, you can subscribe at "
    "360heartsinthesky.com from €1 / month (suggested: €14.99 / month). "
    "Subscribing at €9.99 / month or more also unlocks the Explorer tier "
    "on the website: celebrity database, full transit, dignified planets, "
    "Divine Cow, Shadbala, and 20 save slots on the web app.\n\n"
    "You can sign in anytime from the Account menu. No account is required "
    "to use the software."
)

# ─── Screenshot paths ───────────────────────────────────────────────────────
# Tuple of relative paths (from project root) to bundled marketing images
# that the About-Pro dialog can render in a small preview gallery. Empty
# tuple means "no screenshots, render text only" — the dialog will gracefully
# skip the screenshot section. Populate when actual marketing assets exist
# under img/pro_marketing/. Each path should resolve to a file the AppImage
# bundles via PyInstaller's --add-data.

PRO_SCREENSHOT_PATHS: Final[tuple[str, ...]] = ()
