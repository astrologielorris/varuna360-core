# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Nabhasa Yogas panel reference data.
===================================
For every Nabhasa yoga (3 Asraya, 2 Dala, 7 Sankhya, 20 Akriti) and the 5
Pancha Mahapurusha yogas: the classical source of its definition and its
classical auspiciousness class (the card colour). The Nabhasa families are
given in Varahamihira's Brihat Jataka chapter 12 (with parity in
Kalyanavarma's Saravali chapter 21); the Pancha Mahapurusha yogas in Brihat
Jataka chapter 11; the multiple-yoga escalation rule in Mantreswara's
Phaladeepika 6.4.

The per-yoga reading texts are not part of this (LTS) branch.

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
# "auspicious" / "difficult" / "mixed". Classical valuation.
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
# Classical source of each yoga's definition (the citation only; no reading
# text ships on this branch).
# =====================================================================
_FAMILIES = {
    "asraya": ('Rajju', 'Musala', 'Nala'),
    "dala": ('Mala', 'Sarpa'),
    "sankhya": ('Gola', 'Yuga', 'Sula', 'Kedara', 'Pasa', 'Dama', 'Veena'),
    "akriti": ('Sringataka', 'Hala', 'Gada', 'Sakata', 'Vihaga', 'Kamala', 'Vapi', 'Vajra', 'Yava', 'Yupa', 'Sara', 'Shakti', 'Danda', 'Nauka', 'Kuta', 'Chatra', 'Chapa', 'Ardha Chandra', 'Chakra', 'Samudra'),
    "pmp": ('Ruchaka', 'Bhadra', 'Hamsa', 'Malavya', 'Sasa'),
}
CITES = {name: (_BJ11 if family == "pmp" else _BJ12)
         for family, members in _FAMILIES.items() for name in members}

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

def describe_nabhasa_yoga(name):
    """Return {"cite": str, "auspiciousness": str} for a yoga name (canonical
    Akriti names, not variant names), or None if unknown. No "reading" key:
    the per-yoga reading text is not part of this branch, and the panel shows
    no reading area."""
    if name not in CITES:
        return None
    return {"cite": CITES[name], "auspiciousness": AUSPICIOUSNESS.get(name, "mixed")}


# =====================================================================
# Inline (i) tutorial: how to use the panel (usage only, no interpretation);
# classical sources cited; NO pro/ import (H11).
# =====================================================================
DOC_TITLE = "Nabhasa Yogas: how to use this panel"
DOC_SECTIONS = [
    ("WHAT THE PANEL SHOWS",
     "The panel checks the seven planets (Sun through Saturn) against the "
     "Nabhasa yoga patterns. The top card is the shape the chart comes closest "
     "to. Below it come the Foundation cards, the twenty Akriti shapes ranked "
     "from most to least formed, and the five Pancha Mahapurusha yogas. Click "
     "view combination on a card to open the complete pattern in North and South "
     "Indian styles. The button is off while the chart is shown as a wheel; "
     "switch to a diamond or square chart to use it."),
    ("THE FOUR FAMILIES",
     "Asraya groups the planets by the modality of their signs (movable, fixed "
     "or dual). Dala counts the gentle and the cruel planets in the four angles. "
     "Sankhya counts how many signs the seven planets occupy. Akriti checks the "
     "pattern of houses the planets occupy."),
    ("BARS, CHIPS AND COLOURS",
     "Each shape is scored by how many of the seven planets would have to move "
     "to complete it. The chip and the strength bar show how many already fit, "
     "for example 5/7 planets. FORMED means all seven fit. The card colour shows "
     "the classical class of the yoga: auspicious, mixed or difficult."),
    ("PANCHA MAHAPURUSHA",
     "A Mahapurusha yoga forms when Mars, Mercury, Jupiter, Venus or Saturn sits "
     "in an angle from the ascendant in its own or exaltation sign. This panel "
     "follows Ernst Wilhelm's rule: moolatrikona is not counted, and the Sun or "
     "Moon sitting with the planet cancels the yoga. Each card shows FORMED, "
     "CANCELLED or not formed, with the planet's house and dignity below."),
    ("CLASSICAL SOURCES",
     "The Nabhasa families are given in Varahamihira's Brihat Jataka chapter 12, "
     "with parity in Kalyanavarma's Saravali chapter 21. The Pancha Mahapurusha "
     "yogas are in Brihat Jataka chapter 11. The note shown when more than one "
     "of them forms is from Mantreswara's Phaladeepika 6.4."),
]
