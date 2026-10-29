# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Partner reading preferences (SPEC-PRT-001 §4.1, §4.3.3). The mynatal window
writes them after each request (through ``core.partner_reading.settings``, an
owned-key allowlist of exactly these keys), so the next request opens with the
same choices; the CLI declares them in ``USES`` and ``--set`` changes them. Dynamic writer keys: not in
DEFAULT_SETTINGS (persisted=False), like the recorder's."""
# Calculation family (D-16): they change what the CLI prints (the reading's
# circle, language and register), so `--set` may change them for one run.
from core.settings_registry.rules import CALC_AI as CALC   # their control: the mynatal window
from core.settings_registry.schema import Choice, Setting

SETTINGS = (
    Setting("partner.reading.mode", str, "aditya", persisted=False,
            choices=(Choice("aditya"), Choice("fusion")), rules=CALC,
            help="mynatal reading: the Aditya circle, or fusion (Aditya first, nuanced by the tropical sign)."),
    Setting("partner.reading.language", str, "auto", persisted=False,
            choices=(Choice("auto"), Choice("fr"), Choice("en")), rules=CALC,
            help="Language of the mynatal reading; auto follows the app language (French or English)."),
    Setting("partner.reading.register", str, "vous", persisted=False,
            choices=(Choice("tu"), Choice("vous")), rules=CALC,
            help="French readings only: address the person as tu or vous."),
)
