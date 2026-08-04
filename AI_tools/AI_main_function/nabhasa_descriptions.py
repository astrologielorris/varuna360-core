# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Per-yoga readings for the Nabhasa Yogas panel.
==============================================
A reading for every Nabhasa yoga (3 Asraya, 2 Dala, 7 Sankhya, 20 Akriti) and
the 5 Pancha Mahapurusha yogas.

Sourcing policy (Golden principle 6, mirrors parivartana_descriptions.py):
  * The classical phala ("") is a FACT and is cited to
    its classical text. The Nabhasa families are given in Varahamihira's Brihat
    Jataka chapter 12 (with parity in Kalyanavarma's Saravali chapter 21); the
    Pancha Mahapurusha yogas in Brihat Jataka chapter 11; the multiple-yoga
    escalation rule in Mantreswara's Phaladeepika 6.4.
  * The psychological / house-type layer is PARAPHRASED in the app author's own
    voice from the modern teaching of Ernst Wilhelm, expressed only in the app
    author's own wording of the underlying idea.

Note: Phaladeepika is NOT cited for the Akriti definitions. Phaladeepika 6.44-57
gives a DIFFERENT twelve-yoga "Bhava" set, not Varahamihira's twenty Akriti, so
the Akriti citations point to Brihat Jataka / Saravali only.

Presentation only: no GUI state, no pro/ import (H11).
"""

# --- classical citation shorthands -----------------------------------------
_BJ12 = "Brihat Jataka 12 (Varahamihira); parity in Saravali 21 (Kalyanavarma)"
_BJ11 = "Brihat Jataka 11 (Varahamihira)"
_PD64 = "Phaladeepika 6.4 (Mantreswara)"

# Auspiciousness class per yoga, used for the card's semantic colour ramp.
# 
# 
AUSPICIOUSNESS = {
    # Asraya
    "Rajju": "difficult", "Musala": "auspicious", "Nala": "mixed",
    # Dala
    "Mala": "auspicious", "Sarpa": "difficult",
    # Sankhya
    "Gola": "difficult", "Yuga": "difficult", "Sula": "difficult",
    "Kedara": "auspicious", "Pasa": "mixed", "Dama": "auspicious",
    "Veena": "auspicious",
    # Akriti
    "Sringataka": "mixed", "Hala": "difficult", "Gada": "auspicious",
    "Sakata": "difficult", "Vihaga": "mixed", "Kamala": "auspicious",
    "Vapi": "auspicious", "Vajra": "mixed", "Yava": "auspicious",
    "Yupa": "auspicious", "Sara": "difficult", "Shakti": "mixed",
    "Danda": "difficult", "Nauka": "difficult", "Kuta": "difficult",
    "Chatra": "auspicious", "Chapa": "difficult", "Ardha Chandra": "auspicious",
    "Chakra": "auspicious", "Samudra": "auspicious",
    # Pancha Mahapurusha (all are great-personage blessings; Sasa's temperament
    # is the hardest even so).
    "Ruchaka": "auspicious", "Bhadra": "auspicious", "Hamsa": "auspicious",
    "Malavya": "auspicious", "Sasa": "mixed",
}

# =====================================================================
# 
# =====================================================================
ASRAYA_DESC = {
    "Rajju": {
        "cite": _BJ12,
        "reading": (
            " "
            " "
            " "
            " "
            " "
            "steady place to land."
        ),
    },
    "Musala": {
        "cite": _BJ12,
        "reading": (
            " "
            " "
            " "
            " "
            ""
        ),
    },
    "Nala": {
        "cite": _BJ12,
        "reading": (
            " "
            " "
            " "
            " "
            ""
        ),
    },
}

# =====================================================================
# 
# =====================================================================
DALA_DESC = {
    "Mala": {
        "cite": _BJ12,
        "reading": (
            " "
            " "
            " "
            " "
            ""
        ),
    },
    "Sarpa": {
        "cite": _BJ12,
        "reading": (
            " "
            " "
            " "
            " "
            " "
            "verdict on the person."
        ),
    },
}

# =====================================================================
# 
# =====================================================================
SANKHYA_DESC = {
    "Gola": {
        "cite": _BJ12,
        "reading": (
            " "
            " "
            " "
            ""
        ),
    },
    "Yuga": {
        "cite": _BJ12,
        "reading": (
            " "
            " "
            " "
            " "
            "whatever is nearest."
        ),
    },
    "Sula": {
        "cite": _BJ12,
        "reading": (
            " "
            " "
            " "
            ""
        ),
    },
    "Kedara": {
        "cite": _BJ12,
        "reading": (
            " "
            " "
            " "
            " "
            "life."
        ),
    },
    "Pasa": {
        "cite": _BJ12,
        "reading": (
            " "
            " "
            " "
            " "
            ""
        ),
    },
    "Dama": {
        "cite": _BJ12,
        "reading": (
            " "
            " "
            " "
            ""
        ),
    },
    "Veena": {
        "cite": _BJ12,
        "reading": (
            " "
            " "
            " "
            " "
            ""
        ),
    },
}

# =====================================================================
# 
# =====================================================================
AKRITI_DESC = {
    "Sringataka": {
        "cite": _BJ12,
        "reading": (
            " "
            " "
            " "
            " "
            ""
        ),
    },
    "Hala": {
        "cite": _BJ12,
        "reading": (
            " "
            " "
            " "
            " "
            ""
        ),
    },
    "Gada": {
        "cite": _BJ12,
        "reading": (
            " "
            " "
            " "
            ""
        ),
    },
    "Sakata": {
        "cite": _BJ12,
        "reading": (
            " "
            " "
            " "
            ""
        ),
    },
    "Vihaga": {
        "cite": _BJ12,
        "reading": (
            " "
            " "
            " "
            " "
            " "
            ""
        ),
    },
    "Kamala": {
        "cite": _BJ12,
        "reading": (
            " "
            " "
            " "
            ""
        ),
    },
    "Vapi": {
        "cite": _BJ12,
        "reading": (
            " "
            " "
            " "
            " "
            "gathered patiently."
        ),
    },
    "Vajra": {
        "cite": _BJ12,
        "reading": (
            " "
            " "
            " "
            " "
            " "
            ""
        ),
    },
    "Yava": {
        "cite": _BJ12,
        "reading": (
            " "
            " "
            " "
            " "
            " "
            " "
            "the effect."
        ),
    },
    "Yupa": {
        "cite": _BJ12,
        "reading": (
            " "
            " "
            " "
            ""
        ),
    },
    "Sara": {
        "cite": _BJ12,
        "reading": (
            " "
            " "
            " "
            " "
            "shape neglects."
        ),
    },
    "Shakti": {
        "cite": _BJ12,
        "reading": (
            " "
            " "
            " "
            " "
            "genuinely satisfied."
        ),
    },
    "Danda": {
        "cite": _BJ12,
        "reading": (
            " "
            " "
            " "
            ""
        ),
    },
    "Nauka": {
        "cite": _BJ12,
        "reading": (
            " "
            " "
            " "
            " "
            ""
        ),
    },
    "Kuta": {
        "cite": _BJ12,
        "reading": (
            " "
            " "
            " "
            ""
        ),
    },
    "Chatra": {
        "cite": _BJ12,
        "reading": (
            " "
            " "
            " "
            " "
            "earns honour for it."
        ),
    },
    "Chapa": {
        "cite": _BJ12,
        "reading": (
            " "
            " "
            " "
            " "
            "has cause to."
        ),
    },
    "Ardha Chandra": {
        "cite": _BJ12,
        "reading": (
            " "
            " "
            " "
            " "
            ""
        ),
    },
    "Chakra": {
        "cite": _BJ12,
        "reading": (
            " "
            " "
            " "
            " "
            "few real failings."
        ),
    },
    "Samudra": {
        "cite": _BJ12,
        "reading": (
            " "
            " "
            " "
            ""
        ),
    },
}

# =====================================================================
# 
# =====================================================================
PMP_DESC = {
    "Ruchaka": {
        "cite": _BJ11,
        "reading": (
            " "
            " "
            " "
            " "
            ""
        ),
    },
    "Bhadra": {
        "cite": _BJ11,
        "reading": (
            " "
            " "
            " "
            " "
            ""
        ),
    },
    "Hamsa": {
        "cite": _BJ11,
        "reading": (
            " "
            " "
            " "
            " "
            ""
        ),
    },
    "Malavya": {
        "cite": _BJ11,
        "reading": (
            " "
            " "
            " "
            " "
            ""
        ),
    },
    "Sasa": {
        "cite": _BJ11,
        "reading": (
            " "
            " "
            " "
            " "
            " "
            ""
        ),
    },
}

# The multiple-Mahapurusha escalation, cited to Phaladeepika 6.4. The widget
# shows this when more than one PMP forms.
PMP_ESCALATION = {
    "cite": _PD64,
    1: "one formed: a fortunate person.",
    2: "two formed: the equal of a king.",
    3: "three formed: a king.",
    4: "four formed: an emperor.",
    5: "five formed: greater than an emperor.",
}

_ALL_TABLES = (ASRAYA_DESC, DALA_DESC, SANKHYA_DESC, AKRITI_DESC, PMP_DESC)


def describe_nabhasa_yoga(name):
    """Return {"reading": str, "cite": str, "auspiciousness": str} for a yoga
    name (canonical Akriti names, not variant names), or None if unknown."""
    for table in _ALL_TABLES:
        if name in table:
            entry = table[name]
            return {
                "reading": entry["reading"],
                "cite": entry["cite"],
                "auspiciousness": AUSPICIOUSNESS.get(name, "mixed"),
            }
    return None


# =====================================================================
# 
# classical taxonomy cited; NO pro/ import (H11).
# =====================================================================
DOC_TITLE = ""
DOC_SECTIONS = [
    ("WHAT THEY ARE",
     " "
     " "
     " "
     "chart is read against."),
    ("THE FOUR FAMILIES",
     " "
     " "
     " "
     " "
     ""),
    ("MOST NEARLY FORMED",
     " "
     " "
     " "
     " "
     ""),
    ("PANCHA MAHAPURUSHA",
     " "
     " "
     " "
     " "
     ""),
    ("CLASSICAL SOURCES",
     "The Nabhasa families are given in Varahamihira's Brihat Jataka chapter 12, "
     "with parity in Kalyanavarma's Saravali chapter 21. The Pancha Mahapurusha "
     " "
     " "
     " "
     ""),
]
