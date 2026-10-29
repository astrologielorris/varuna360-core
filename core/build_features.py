# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Features a BRANCH builds in or switches off (SPEC-AIC-001 D-26).

THIS FILE HOLDS A DIFFERENT VALUE ON EACH LONG-LIVED BRANCH, ON PURPOSE:

    main      AI_CAPTURE_ENABLED = True
              PARTNER_READING_ENABLED = True
    lts/5.0   AI_CAPTURE_ENABLED = True    (D-27, 2026-10-22; was False under D-26)
              PARTNER_READING_ENABLED = True (Lorris 2026-10-22)
              BRANCH_LINE = "lts"

Never copy this file from one branch to the other, and never "fix" the value
during a main -> LTS port. The guard test ``test/test_build_features_branch.py``
asserts the value expected on its own branch and fails when a port flips it.

AI capture (the AI menu, the "AI capture" and "AI readings" status-bar pills,
the capture hotkey, the capture overlay and review panel, the AI task window
and the Readings window) is shown on ``main`` and, since D-27 (2026-10-22), on
LTS too. Every GUI entry point asks ``ai_capture_enabled()`` once, when it
would install itself, and installs nothing when it is False.
The headless parts the rest of the app uses (``core.ai_capture.packet``'s
edition answer, ``apps.ai_capture.freeze``, the capability CLI) keep working on both branches.

A build constant, not a user setting: nothing in the Settings tab, the
settings file or ``settings.py`` can turn it back on.
"""

AI_CAPTURE_ENABLED = True   # SPEC-AIC-001 D-27 (Lorris, 2026-10-22): shown on LTS too

# The long-lived line this file belongs to (bug reports); differs per branch.
BRANCH_LINE = "lts"


def ai_capture_enabled() -> bool:
    """True when this build shows AI capture to the user."""
    return AI_CAPTURE_ENABLED


# Partner reading (SPEC-PRT-001 D-3): the red "mynatal reading" pill, its
# menu action and window. True on main; False on lts/5.0 until the partner
# agreement is signed and Lorris says so. Independent of AI_CAPTURE_ENABLED.
PARTNER_READING_ENABLED = True   # Lorris 2026-10-22: on LTS too (agreement being signed)


def partner_reading_enabled() -> bool:
    """True when this build shows the partner reading to the user."""
    return PARTNER_READING_ENABLED
