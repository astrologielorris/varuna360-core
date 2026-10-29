# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The hub's words (SPEC-COACH-001 Appendix A): Lorris's draft from the
competition brief, verbatim, plus the short labels of the winning design.
DRAFTS awaiting his review (Q-6): change them here only."""

TILES = {
    "coach": ("AI coach", "Ask a question. The AI opens the right view, points at what matters "
                          "and explains it step by step on your chart."),
    "capture": ("AI capture", "Freeze the window and drag over what you want to ask about."),
    "library": ("AI library", "Your saved AI readings: open, archive or delete them."),
    "search": ("AI search", "Find charts in your collection by asking in your own words."),
    "blind": ("Blind reading", "Let the AI read a chart without knowing whose it is."),
    "natal": ("My natal reading", "A full AI reading of your own birth chart."),
    "settings": ("AI settings", "Choose the AI model, your keys and how much it may do."),
    "connect": ("Connect AI apps", "Let Claude Desktop and other AI apps on this computer use "
                                   "Varuna360."),
}

QUESTIONS = (
    "Show me the Moon's transits this week.",
    "Show me the next eclipse and explain the important aspects.",
    "Why is my Saturn weak in the Avastha grid?",
    "Which houses are most active in this chart?",
    "What is the Trimsamsa being of my Venus?",
    "Walk me through my Ascendant guide.",
)

INTRO_TITLE = "Working with AI"
INTRO = (
    ("The AI is a helper, not an astrologer.",
     "It reads the numbers Varuna360 calculates and shows you where they are on the chart. "
     "It does not understand a life the way you do."),
    ("You lead, the AI follows.",
     "Ask one clear question at a time. Say which chart, which date and what you want to "
     "see. If an answer looks wrong, say so and ask it to check again."),
    ("The AI can be wrong while sounding sure.",
     "Check what matters on the chart itself."),
    ("The reading is yours.",
     "The AI opens the right view, points and explains. You decide what it means for the "
     "person in front of you. The astrologer is responsible, not the machine."),
    ("Ask with care and patience.",
     "A precise, kind question gets a better answer."),
)

# Short labels (the winning design's)
BUTTON = "AI"
BUTTON_TIP = "AI hub"
HEADER = "AI"
CLOSE = "Close"
GOT_IT = "Got it"
NEW = "New"
EXAMPLES = "Example questions"
