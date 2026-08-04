# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Per-yoga readings for the Nabhasa Yogas panel.
==============================================
A reading for every Nabhasa yoga (3 Asraya, 2 Dala, 7 Sankhya, 20 Akriti) and
the 5 Pancha Mahapurusha yogas.

Sourcing policy (Golden principle 6, mirrors parivartana_descriptions.py):
  * The classical phala ("one born in this yoga is...") is a FACT and is cited to
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
# "auspicious" / "difficult" / "mixed". Classical valuation; the Ernst layer may
# soften a "difficult" yoga into a workable strength, which the reading explains.
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
# Asraya (modality of the signs the seven planets rest in)
# =====================================================================
ASRAYA_DESC = {
    "Rajju": {
        "cite": _BJ12,
        "reading": (
            "With all seven planets resting in movable signs, the life is built "
            "for motion. The classical reading gives a charming, good looking, "
            "restless nature that struggles to hold on to means. Read this as "
            "pioneering energy that starts readily and travels far, but scatters "
            "when nothing anchors it; the work is to give the restlessness a "
            "steady place to land."
        ),
    },
    "Musala": {
        "cite": _BJ12,
        "reading": (
            "All seven planets rest in fixed signs, so the chart is a compact, "
            "grounded whole. Classically this is the honoured, wise and wealthy "
            "nature, firm, steady and productive. It is a strong, settled will "
            "that accumulates and holds what it builds; the caution is that the "
            "same firmness can harden into stubbornness."
        ),
    },
    "Nala": {
        "cite": _BJ12,
        "reading": (
            "All seven planets rest in dual signs, giving the versatile, "
            "adaptable nature the texts call skilful, shrewd and resourceful "
            "(they also note an uneven build). This is a mind that works well "
            "with whatever is at hand and adjusts to circumstance, balanced "
            "between the fixed and the movable rather than committed to either."
        ),
    },
}

# =====================================================================
# Dala (benefic vs malefic weight at the angles)
# =====================================================================
DALA_DESC = {
    "Mala": {
        "cite": _BJ12,
        "reading": (
            "The gentle planets carry the angles, so the structural houses of the "
            "life are held by support rather than pressure. The classical Mala "
            "(garland) yoga promises comforts, conveyances, learning and lasting "
            "pleasures. Read as a life whose framework tends to unfold smoothly, "
            "with the right things arriving at roughly the right time."
        ),
    },
    "Sarpa": {
        "cite": _BJ12,
        "reading": (
            "The cruel planets carry the angles, so the structural houses of the "
            "life meet more friction. The classical Sarpa (serpent) yoga is read "
            "as hardship, want and difficulty. In the modern reading the "
            "difficulty is largely external, the circumstances the life is coiled "
            "around, and it works as pressure that forces growth rather than a "
            "verdict on the person."
        ),
    },
}

# =====================================================================
# Sankhya (how many distinct signs the seven planets occupy)
# =====================================================================
SANKHYA_DESC = {
    "Gola": {
        "cite": _BJ12,
        "reading": (
            "All seven planets crowd into a single sign. The classical phala is "
            "stark (little learning, strength or means). Read the geometry as "
            "total concentration with no outlet: enormous focus on one point of "
            "the chart, which can overwhelm unless it finds a channel to pour into."
        ),
    },
    "Yuga": {
        "cite": _BJ12,
        "reading": (
            "The seven planets fall in only two signs. Classically an unsettled, "
            "changeable nature that struggles to keep to a path. Read as a life "
            "that mirrors its two environments and swings between them, so the "
            "task is to choose a direction and hold it rather than reflect "
            "whatever is nearest."
        ),
    },
    "Sula": {
        "cite": _BJ12,
        "reading": (
            "The seven planets fall in three signs. The texts give a sharp, "
            "combative, warrior nature (Sula is the spear). Read as strong mental "
            "attachment to a few fixed ideas: real force of conviction and "
            "argument, which builds pressure until it finds concrete expression."
        ),
    },
    "Kedara": {
        "cite": _BJ12,
        "reading": (
            "The seven planets spread across four signs. Kedara (the cultivated "
            "field) is classically the truthful, patient, useful nature that "
            "benefits others. Read as grounded, realistic security: a settled "
            "worker whose inner steadiness becomes a foundation for a contented "
            "life."
        ),
    },
    "Pasa": {
        "cite": _BJ12,
        "reading": (
            "The seven planets occupy five signs. The classical texts give Pasa "
            "(the noose) two opposite readings, one of bondage and ill repute, "
            "one of many friends, servants and plenty. Read the split as "
            "character dependent: the same binding energy either entangles the "
            "life or ties a wide, loyal circle to it, according to how it is used."
        ),
    },
    "Dama": {
        "cite": _BJ12,
        "reading": (
            "The seven planets occupy six signs. Dama (the wreath) is classically "
            "generous, patient, learned and happy in its children. Read as a "
            "nature that understands how its own good deeds return to it and keeps "
            "improving on that basis, with a high capacity for steady happiness."
        ),
    },
    "Veena": {
        "cite": _BJ12,
        "reading": (
            "The seven planets are spread through all seven usable signs, the "
            "widest possible distribution. Veena (the lute) is classically the "
            "skilled, musical, learned and eloquent nature. Read as broad "
            "versatility, satisfaction drawn from developing many given talents to "
            "a high degree rather than resting on one."
        ),
    },
}

# =====================================================================
# Akriti (the shape the seven planets trace across the houses)
# =====================================================================
AKRITI_DESC = {
    "Sringataka": {
        "cite": _BJ12,
        "reading": (
            "The planets gather in the dharma trine (1, 5, 9). Classically a "
            "spirited, contentious nature dear to those in power, happy and "
            "intelligent. Read as strong self reliance that is ready for a "
            "challenge and dislikes leaning on anyone, which is a strength that "
            "can cost it in close relationships."
        ),
    },
    "Hala": {
        "cite": _BJ12,
        "reading": (
            "The planets fill one of the non self trines (the plough). "
            "Classically a hard, labouring, often thankless life. Read as effort "
            "whose fruit tends to serve others more than the self, and a felt "
            "distance from one's own centre; which trine carries it (2/6/10 work, "
            "3/7/11 desire, 4/8/12 release) colours where the labour falls."
        ),
    },
    "Gada": {
        "cite": _BJ12,
        "reading": (
            "The planets sit in two successive angles (the mace). Classically "
            "wealth won through effort, honours, and skill in scripture, song and "
            "craft. Read as solid inner security and the strength to fight through "
            "obstacles, a nature that knows what it is and can defend it."
        ),
    },
    "Sakata": {
        "cite": _BJ12,
        "reading": (
            "The planets fall on the 1st and 7th axis (the cart). Classically a "
            "burdened, up and down life pulled along like a cart. Read as slow, "
            "cumbersome forward motion, often caught between one's own aim and the "
            "pull of relationships, so progress comes in effortful stretches."
        ),
    },
    "Vihaga": {
        "cite": _BJ12,
        "reading": (
            "The planets fall on the 4th and 10th axis (the sky goer). Brihat "
            "Jataka reads this as a restless, roaming, unsettled nature, yet Hora "
            "Sara (Prithuyasas) gives the opposite, a happy accumulator of wealth "
            "and homes; the classical texts genuinely disagree here. Read as "
            "action tied to feeling and standing, needing outer validation, which "
            "can read as either wandering or wide reach."
        ),
    },
    "Kamala": {
        "cite": _BJ12,
        "reading": (
            "All four angles are occupied (the lotus), one of the finest Nabhasa "
            "shapes. Classically rich, virtuous, famous, long lived and widely "
            "loved. Read as a nature that rises above petty difficulty and stays "
            "set on the good, with a high and durable capacity for happiness."
        ),
    },
    "Vapi": {
        "cite": _BJ12,
        "reading": (
            "The planets fill the four succeedent or the four cadent houses (the "
            "reservoir). Classically a steady accumulator of lasting wealth, "
            "comfort and long life. Read as the inner security to take the best of "
            "what arrives and make the most of it, wealth that holds because it is "
            "gathered patiently."
        ),
    },
    "Vajra": {
        "cite": _BJ12,
        "reading": (
            "Gentle planets hold the 1st and 7th, cruel planets the 4th and 10th "
            "(the thunderbolt). Classically a charming, valiant life, happy at its "
            "beginning and end but sensual and wrathful in the middle. Read as "
            "real power hardened by the malefic concentration, with the middle of "
            "life carrying the strain. Read by nearest formation: the closer the "
            "chart comes to the complete thunderbolt, the stronger the effect."
        ),
    },
    "Yava": {
        "cite": _BJ12,
        "reading": (
            "Cruel planets hold the 1st and 7th, gentle planets the 4th and 10th "
            "(the barleycorn). Classically disciplined, charitable, firm and happy "
            "in middle life. Read as the capacity to find and hold happiness even "
            "through personal difficulty, the good reached by way of the gentle "
            "angles despite the pressure on the self. Read by nearest formation: "
            "the closer the chart comes to the complete barleycorn, the stronger "
            "the effect."
        ),
    },
    "Yupa": {
        "cite": _BJ12,
        "reading": (
            "Four consecutive houses from the ascendant (the sacrificial pillar). "
            "Classically drawn to knowledge, rites and self control, generous and "
            "self protecting. Read as security found within: a nature that reins "
            "in its outward reach and meets its own needs from the inside."
        ),
    },
    "Sara": {
        "cite": _BJ12,
        "reading": (
            "Four consecutive houses from the 4th (the arrow). The classical phala "
            "is among the harshest of the Akriti. Read as an emotionally spare "
            "shape weighted toward outer need, where the drive to secure those "
            "needs can turn sharp; the growth is in feeding the inner life the "
            "shape neglects."
        ),
    },
    "Shakti": {
        "cite": _BJ12,
        "reading": (
            "Four consecutive houses from the 7th (the spear). The classical "
            "reading is mixed: loving and intelligent in debate, yet often short "
            "of wealth and satisfaction. Read as a life driven by the power of "
            "mind and attached to its ideas, active and able but slow to feel "
            "genuinely satisfied."
        ),
    },
    "Danda": {
        "cite": _BJ12,
        "reading": (
            "Four consecutive houses from the 10th (the rod). Classically a hard, "
            "diminished, servile lot marked by loss. Read as a completion phase, "
            "the reaping of earlier karma where the theme is being made to let go; "
            "the difficulty is the release itself rather than a flaw in the person."
        ),
    },
    "Nauka": {
        "cite": _BJ12,
        "reading": (
            "Seven consecutive houses from the ascendant (the boat). Classically "
            "famous yet grasping, strong but restless, with gains from water and a "
            "swing between happy and miserable. Read as an emotionally centred "
            "shape that acts from feeling and can treat others as extensions of "
            "its needs, so fulfilment stays elusive."
        ),
    },
    "Kuta": {
        "cite": _BJ12,
        "reading": (
            "Seven consecutive houses from the 4th (the peak, also a word for "
            "deceit). The classical phala is severe. Read as action strongly "
            "coloured by imagination and need rather than a settled code, capable "
            "and cunning but liable to cut corners while chasing what it wants."
        ),
    },
    "Chatra": {
        "cite": _BJ12,
        "reading": (
            "Seven consecutive houses from the 7th (the royal parasol). "
            "Classically kind, intelligent and richly rewarded, dear to those in "
            "power and happy at the start and close of life. Read as a genuinely "
            "helpful nature, secure and capable, that recognises others' good and "
            "earns honour for it."
        ),
    },
    "Chapa": {
        "cite": _BJ12,
        "reading": (
            "Seven consecutive houses from the 10th (the bow). Classically a "
            "capable but concealed life, happy in childhood and old age but "
            "pressed in the middle. Read as happiness staked on one's deeds and "
            "kept hidden, so the shape rarely lets itself feel secure even when it "
            "has cause to."
        ),
    },
    "Ardha Chandra": {
        "cite": _BJ12,
        "reading": (
            "Seven consecutive houses beginning from a succeedent or cadent house "
            "(the half moon). Classically strong and splendorous, leading others, "
            "adorned and superior to those around. Read as having the resources "
            "and talents ready to hand and results that genuinely satisfy, a shape "
            "inclined toward contentment."
        ),
    },
    "Chakra": {
        "cite": _BJ12,
        "reading": (
            "The planets fall in the six odd houses (the wheel, the monarch's "
            "discus). Classically an emperor's shape: a repository of good "
            "qualities, valorous and famous through life. Read as concentrated, "
            "self reliant power whose merits reliably draw their due reward, with "
            "few real failings."
        ),
    },
    "Samudra": {
        "cite": _BJ12,
        "reading": (
            "The planets fall in the six even houses (the sea). Classically "
            "steady and greatly wealthy, truthful, well liked and kind. Read as a "
            "soft, receptive strength that good things are bestowed upon, an "
            "emotionally secure, ocean like breadth that gathers rather than seizes."
        ),
    },
}

# =====================================================================
# Pancha Mahapurusha (a raja-yoga planet dignified at an angle)
# =====================================================================
PMP_DESC = {
    "Ruchaka": {
        "cite": _BJ11,
        "reading": (
            "Mars stands dignified at an angle (Ruchaka, the radiant). Classically "
            "energetic, daring and brave, a renowned leader who wins wealth by "
            "bold deeds and commands armies, with the caution of a rash, "
            "hot tempered edge. Read as sharp martial force that, aimed well, "
            "carries the person to what they set out to take."
        ),
    },
    "Bhadra": {
        "cite": _BJ11,
        "reading": (
            "Mercury stands dignified at an angle (Bhadra, the blessed). "
            "Classically learned, eloquent and firm minded, skilled in every art, "
            "very rich and praised, a keen and contemplative intellect. Read as "
            "the practical manager and clear decision maker, the great personage "
            "yoga most tied to effective, intelligent success."
        ),
    },
    "Hamsa": {
        "cite": _BJ11,
        "reading": (
            "Jupiter stands dignified at an angle (Hamsa, the swan). Classically "
            "generous, virtuous and happy, devoted to scripture and revered, with "
            "a lovely voice and long life. Read as a faith carried nature, "
            "protected and lifted by hope and good foresight, drawing benefit "
            "through conviction rather than force."
        ),
    },
    "Malavya": {
        "cite": _BJ11,
        "reading": (
            "Venus stands dignified at an angle (Malavya). Classically graceful "
            "and lustrous, fond of the arts and every pleasure, liberal, resolute, "
            "wealthy and famous, a monarch of cultured mind. Read as the greatest "
            "capacity for enjoyment paired with wise diplomacy, recognising true "
            "value and choosing well without being ruled by craving."
        ),
    },
    "Sasa": {
        "cite": _BJ11,
        "reading": (
            "Saturn stands dignified at an angle (Sasa). Classically strong, "
            "crafty and commanding, a chief or minister devoted to the land and to "
            "the mother, wise and hard to oppose, with noted failings of appetite "
            "and hardness. Read as security won through fear and perseverance, "
            "great standing reached by controlling and enduring, the hardest "
            "temperament of the five even as it confers real power."
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
# Inline (i) doctrine tutorial (what the Nabhasa yogas ARE). Author's voice,
# classical taxonomy cited; NO pro/ import (H11).
# =====================================================================
DOC_TITLE = "Nabhasa Yogas: the shape of the whole chart"
DOC_SECTIONS = [
    ("WHAT THEY ARE",
     "The Nabhasa yogas read the seven planets (Sun through Saturn) as one whole "
     "arrangement, not as pairs. They are the first thing the classical texts "
     "describe, because the overall shape sets the foundation the rest of the "
     "chart is read against."),
    ("THE FOUR FAMILIES",
     "Asraya groups the planets by the modality of their signs (movable, fixed or "
     "dual). Dala weighs the gentle against the cruel planets at the four angles. "
     "Sankhya counts how many signs the seven planets occupy. Akriti reads the "
     "geometric shape they trace across the houses, and it carries the twenty "
     "named figures such as the lotus, the plough and the wheel."),
    ("MOST NEARLY FORMED",
     "These shapes are rarely perfect, so each is scored by how many of the seven "
     "planets would need to move to complete it. Zero means fully formed. The "
     "smaller the number, the more strongly the shape colours the chart, and the "
     "fuller the strength bar. This nearest-approach method is how the tradition "
     "handles shapes that are almost never exact."),
    ("PANCHA MAHAPURUSHA",
     "Separately, the five great-personage yogas form when Mars, Mercury, "
     "Jupiter, Venus or Saturn sits at an angle in its own or exaltation sign. "
     "Here the panel follows Ernst Wilhelm's teaching over the raw classical "
     "rule: moolatrikona is not counted, the yoga is read from the ascendant, and "
     "the Sun or Moon sitting with the planet cancels it."),
    ("CLASSICAL SOURCES",
     "The Nabhasa families are given in Varahamihira's Brihat Jataka chapter 12, "
     "with parity in Kalyanavarma's Saravali chapter 21. The Pancha Mahapurusha "
     "yogas are in Brihat Jataka chapter 11, and the rule that having more of "
     "them raises the person from fortunate through king to beyond an emperor is "
     "Mantreswara's Phaladeepika 6.4. The psychological layer follows the modern "
     "teaching of Ernst Wilhelm. Test all of it against your own chart."),
]
