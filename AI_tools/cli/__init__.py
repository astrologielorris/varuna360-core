# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""AI_tools.cli — command-line equivalents of GUI features (Rule 24).

Run as modules from the repository root:

    python -m AI_tools.cli.convert_chart input.chtk output.toml
    python -m AI_tools.cli.read_chart input.toml --json
    python -m AI_tools.cli.show_nakshatra_positions input.chtk --json

Both commands wrap the same calculation paths the GUI uses
(BirthDataManager dispatch + core.toml_chart / core.chtk_reader writers),
so the CLI and GUI stay in lockstep (SPEC-IMPORT-001 Section 8).
"""
