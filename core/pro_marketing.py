# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Static Pro-marketing constants for Varuna360 Core.

This module is the SINGLE point of "Pro awareness" in the Core codebase.
It contains pure data — URLs, feature names, marketing copy — that the
Help menu and About dialog use to advertise the paid Varuna360 Pro
edition. The Core build can mention that Pro exists, link to the upgrade
page, and list features, all without ever importing from the paid
edition's tree or doing any runtime detection of whether Pro is installed.

(Note for future maintainers reading this docstring: deliberate prose
choices throughout — avoiding the literal substrings that the broad
release-gate text scan flags. This is not stylistic preference; the
gate rejects mentions of the paid edition's directory in any context,
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
    "Varuna360 Pro: the AI edition of Varuna360, built for AI and fully "
    "connected to it."
)

PRO_DESCRIPTION: Final[str] = (
    "Varuna360 Lite is complete on its own. Pro adds full AI interpretation "
    "with local access to an AI: almost every task the software can do is also "
    "an AI tool, so you can simply ask. The AI computes the charts, finds the "
    "dates and searches for what you are looking for, and it works interactively "
    "with the program window. Pro comes with a manual, a few extra screens, and "
    "keeps growing: new screens and AI tools are added over time."
)

# ─── Feature catalog ────────────────────────────────────────────────────────
# What Pro adds on top of Lite (Lorris, 2026-10-29). Features Lite already
# has (Lajitadi avastha, Nakshatra wheel, one-click chart creation, web chart
# download, Find Chart) are not listed. Keep in sync with the README template
# at release_gates/templates/public_repo/README.md and the website.

PRO_FEATURES: Final[tuple[str, ...]] = (
    "Full AI interpretation of your charts, with local access to an AI",
    "Built for AI: the software's tasks are AI tools the AI runs for you",
    "Just ask: dates, ingresses, conjunctions and patterns found by the AI",
    "Interactive: the AI opens charts and shows its findings in the window",
    "Connect your own AI apps to Varuna360",
    "Eclipse pages: per-country Ascendant map, Saros Explorer, Eclipse Reading",
    "Transit page",
    "Solar return screen",
    "Chinese Lunar New Year page",
    "A manual for the AI features",
    "New screens and AI tools added over time",
)

# ─── AI in Pro (SPEC-EDN-002 D-21) ──────────────────────────────────────────
# Lite keeps the AI button in the status bar; clicking it shows this message
# instead of the AI hub. Lorris's wording (2026-10-28), lightly edited.

PRO_AI_TITLE: Final[str] = "AI"
PRO_AI_REQUIRED: Final[str] = (
    "Please use the Pro version to have access to the AI abilities."
)
PRO_AI_MORE: Final[str] = "About Varuna360 Pro..."

# ─── Pricing ────────────────────────────────────────────────────────────────
# Optional — the dialog can choose to display this or omit it. Editing
# the price here automatically updates everywhere it is shown.

PRO_PRICE_DISPLAY: Final[str] = "€14.99 / month (starting price)"

# Shown under the price in the About-Pro dialog (Lorris, 2026-10-29).
PRO_PRICE_NOTE: Final[str] = (
    "Pro is released a few days after Lite, at a starting price of €14.99 / month. "
    "It is stable and its AI tools have been tested for a long time, but a few "
    "areas are still being improved. The price will probably rise to €20 / month "
    "over time, as Pro is fully tested and grows."
)

# ─── Subscription plans (website parity) ────────────────────────────────────
# This desktop app is unlocked by a license key from the Explorateur plan
# (EUR9.99) or Pro. There is no in-app account; the user pastes a key copied
# from their 360heartsinthesky.com account (like the mobile app).
#
# These plan names MUST match the website exactly. The View Plans dialog and
# the first-launch welcome popup render these constants verbatim. If the
# website renames a plan, update this file and every surface updates
# automatically.
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

# Display plans shown in the License > View Plans dialog. FOUR plans, in the
# website's display order (matched to the live site, kept in sync with the
# website session):
#   TIER_FREE        Free (EUR0)
#   TIER_MOBILE      Varuna360 Mobile (EUR3) — mobile + web only, NOT this desktop
#   TIER_EXPLORATEUR Explorateur (EUR9.99) — the plan whose key unlocks THIS desktop
#   TIER_PRO         Pro (EUR14.99, Lorris 2026-10-28) — COMING SOON, not purchasable yet
#
# Only an Explorateur license key (or an admin comp) activates the desktop.
# Free and Mobile keys do NOT unlock it. Pro is a coming-soon teaser: it is
# marked as such and never offered for purchase from this dialog.
TIER_FREE_NAME: Final[str] = "Free"
TIER_MOBILE_NAME: Final[str] = "Varuna360 Mobile"
TIER_EXPLORATEUR_NAME: Final[str] = "Explorateur"
TIER_PRO_NAME: Final[str] = "Pro"

TIER_FREE_PRICE: Final[str] = "€0"
TIER_MOBILE_PRICE: Final[str] = "€3 / month"
TIER_EXPLORATEUR_PRICE: Final[str] = "€9.99 / month"
TIER_PRO_PRICE: Final[str] = "€14.99 / month"

# Pro is not yet available. The dialog reads this flag to grey the column and
# show a "coming soon" tag instead of any purchase affordance.
TIER_PRO_COMING_SOON: Final[bool] = True

# The plan whose key unlocks this desktop app. The dialog reads this to draw
# the gold "unlocks this app" highlight on the right column.
TIER_DESKTOP_UNLOCK_NAME: Final[str] = "Explorateur"

TIER_FREE_FEATURES: Final[tuple[str, ...]] = (
    "Natal chart calculation, manual entry",
    "Element pie charts plus positions table",
    "Dominant Aditya description",
    "Ascendant plus house strength",
)

TIER_MOBILE_FEATURES: Final[tuple[str, ...]] = (
    "Android mobile app (installable APK) plus web app",
    "A single license key for both",
    "Without the Varuna360 Lite desktop software",
    "Without the website Explorer tools",
)

TIER_EXPLORATEUR_FEATURES: Final[tuple[str, ...]] = (
    "Mobile app (Android plus web) included",
    "Varuna360 Lite desktop (Windows, Linux, Mac) plus desktop license key",
    "All website Explorer tools (advanced calculator, Avastha, Shadbala, Divine Cow, transits)",
    "CHTK import, 20 save slots, premium articles",
)

TIER_PRO_FEATURES: Final[tuple[str, ...]] = (
    "Everything in Explorateur",
    "Full AI interpretation, connected to every desktop tool, plus eclipse and transit pages",
    "Coming soon, not yet available",
)

# Welcome popup body — shown once per install before the main window
# appears, and ONLY when running from source (should_show_welcome() in
# apps/widgets/welcome_dialog.py gates on is_frozen()). Users of the
# packaged editions paid for their download; greeting them with "free as
# long as you want" reads as a downgrade of what they bought. The
# source-build audience is the one this message exists for.
# Subscription-only language, product framing throughout.
WELCOME_TITLE: Final[str] = "Welcome to Varuna360"
WELCOME_BODY: Final[str] = (
    "Varuna360 is a product. You are running the Core edition from source, "
    "free to use for as long as you want, every feature, no time limit, "
    "no nagging.\n\n"
    "When you decide it is worth paying for, you can subscribe at "
    "360heartsinthesky.com. The Explorateur plan (€9.99 / month) unlocks the "
    "Varuna360 Lite desktop app, the mobile app, and all the website Explorer "
    "tools.\n\n"
    "Once you have a plan, copy your license key from your account page and "
    "paste it into the app from the License menu. No sign in is required."
)

# ─── Screenshot paths ───────────────────────────────────────────────────────
# Tuple of relative paths (from project root) to bundled marketing images
# that the About-Pro dialog can render in a small preview gallery. Empty
# tuple means "no screenshots, render text only" — the dialog will gracefully
# skip the screenshot section. Populate when actual marketing assets exist
# under img/pro_marketing/. Each path should resolve to a file the AppImage
# bundles via PyInstaller's --add-data.

PRO_SCREENSHOT_PATHS: Final[tuple[str, ...]] = ()
