# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Package the help manual as a single .zip the user can hand to an AI.

Why this exists
---------------
The manual is a good reference and a poor answering machine. A reader with a
specific question ("why is my Moon shown in a different sign than my other
software?") has to guess which section holds the answer. Handing the whole
manual to an AI assistant turns it into something you can ask.

That only works if the manual travels as ONE file. A reader who is told to
"upload the manual" will upload `manual.html` alone, the images will be missing,
and the assistant will answer without ever seeing what the panels look like. So
this builds a zip carrying the HTML, every image, and a short plain-text file
explaining to both the human and the assistant what they are looking at.

Deliberately dependency-free: only the standard library, so the export cannot
fail for a reason the user cannot act on.
"""
from pathlib import Path
import zipfile

_CORE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _CORE_DIR.parent

MANUAL_DIR = PROJECT_ROOT / "docs" / "help"
MANUAL_HTML = MANUAL_DIR / "manual.html"
IMAGES_DIR = MANUAL_DIR / "images"

REPO_URL = "https://github.com/astrologielorris/varuna360-core"
WEBSITE_URL = "https://360heartsinthesky.com"

# manual.html carries {{token}} placeholders that HelpDialog swaps for live theme
# colors at load time. Exported to disk they are not merely ugly: a browser drops
# every declaration containing one, so the reader gets a borderless black-on-white
# page. The export therefore bakes its own palette.
#
# Rule 20 (never hardcode hex) governs the GUI, where a theme system exists to be
# respected. A file that leaves the program has no theme system to read, and must
# not import Qt: the CLI exporter runs headless. These are the app's own dark
# values, so the dark screenshots sit on a matching page instead of glaring
# against white.
_EXPORT_PALETTE = {
    "{{text}}": "#EAEAEA",
    "{{bg}}": "#1C1C1E",
    "{{primary}}": "#007AFF",
    "{{heading}}": "#5EADFF",
    "{{border}}": "#3A3A3C",
    "{{surface}}": "#0D0D0D",
    "{{accent}}": "#007AFF",
}

# Appended to the exported page only. QTextBrowser is not a browser and lays the
# manual out at natural image size on a fixed-width panel; a real browser on a
# wide monitor needs a reading measure and needs to be told not to let a 950px
# screenshot punch through a narrow window.
_BROWSER_CSS = """
<style>
  body { max-width: 1000px; margin: 0 auto; }
  img { max-width: 100%; height: auto; }
  table { display: block; overflow-x: auto; }
</style>
"""


def render_manual_html():
    """The manual with theme placeholders resolved, ready to open anywhere."""
    html = MANUAL_HTML.read_text(encoding="utf-8")
    for token, color in _EXPORT_PALETTE.items():
        html = html.replace(token, color)
    return html.replace("</head>", _BROWSER_CSS + "</head>", 1)

# Shipped inside the zip. Written for two readers at once: the person who opens
# the folder, and the assistant that gets told to read everything in it.
_READ_ME = """\
VARUNA360 - HELP MANUAL
=======================
Version {version}

WHAT THIS IS
------------
The complete help manual for Varuna360, a Tropical Vedic astrology program.
manual.html is the manual itself. The images/ folder holds every screenshot it
refers to. Open manual.html in any web browser to read it normally.

IF YOU ARE AN AI ASSISTANT: read the final section of manual.html, "Notes for
an AI Assistant", before answering anything. It is addressed to you. It sets
out what this program is, the facts most often got wrong about it, how to shape
an answer, and an index of every feature and where it lives.


HOW TO ASK AN AI ABOUT IT
-------------------------
Drag this .zip file straight into the chat. You do not need to unzip it first:
ChatGPT and other assistants open the archive themselves and read what is
inside. Then ask your question in your own words. A prompt like this works:

    I have attached the manual for an astrology program called Varuna360.
    Read it, then answer my questions about how to use the program.
    My question is: <your question>

The assistant answers from the manual instead of from whatever it happens to
remember about astrology software, so it will not invent buttons that do not
exist.

The manual ends with a section called "Notes for an AI Assistant". It is
written for the assistant rather than for you, and it tells it how to answer
accurately: what this program is, what it must not guess at, and where each
feature lives. You do not need to do anything with it. It will find it.

Two things it can do well that a search box cannot:
  - "Where do I change X?" - it will name the exact settings page.
  - "What is the difference between X and Y?" - it will compare the sections
    for you instead of making you read both.

Keep in mind it is reading a document, not running the program. If it tells you
something the program does not do, trust the program.


IF YOU WANT DEEPER ANSWERS: GIVE IT THE SOURCE CODE TOO
-------------------------------------------------------
Varuna360 Core is open source (AGPL-3.0). Every calculation the program makes
is public and readable:

    {repo}

An assistant that has read the source can answer questions the manual cannot,
because it can look up how a number is actually produced rather than how it is
described. The manual explains what a panel shows; the code shows the formula.

It can also help you CHANGE the program. See the section
"Modifying Varuna360 Yourself" in the manual.


WEBSITE
-------
    {website}

(C) 2024-2026 Lorris Turpin / 360 Hearts in the Sky
The program is licensed under AGPL-3.0. This manual travels with it.
"""


def app_version():
    """Version string from the VERSION file, or 'unknown'.

    Duplicated from core.bug_report rather than imported: the export must not
    grow a dependency on the diagnostics stack just to name a file.
    """
    try:
        return (PROJECT_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except Exception:
        return "unknown"


def default_filename():
    """Suggested name for the exported archive."""
    return f"Varuna360-Manual-{app_version()}.zip"


def manual_available():
    """True when there is a manual on disk to export."""
    return MANUAL_HTML.is_file()


def build_manual_zip(dest_path):
    """Write the manual archive to `dest_path`.

    Returns (ok, message, stats) where stats is
    {"html": 1, "images": n, "bytes": size}.

    Never raises: the caller is a menu action, and an export that explodes into
    a traceback is worse than one that says why it could not run.
    """
    dest = Path(dest_path)
    stats = {"html": 0, "images": 0, "bytes": 0}

    if not manual_available():
        return False, f"The manual was not found at {MANUAL_HTML}.", stats

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return False, f"Cannot write to {dest.parent}: {exc}", stats

    # Build beside the target and move into place, so an interrupted export
    # cannot leave a half-written .zip wearing the final name.
    staging = dest.with_name(dest.name + ".part")
    try:
        with zipfile.ZipFile(staging, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manual.html", render_manual_html())
            stats["html"] = 1

            if IMAGES_DIR.is_dir():
                for img in sorted(IMAGES_DIR.iterdir()):
                    if img.is_file():
                        zf.writestr(f"images/{img.name}", img.read_bytes())
                        stats["images"] += 1

            zf.writestr("READ-ME-FIRST.txt", _READ_ME.format(
                version=app_version(), repo=REPO_URL, website=WEBSITE_URL))

        staging.replace(dest)
    except (OSError, zipfile.BadZipFile) as exc:
        try:
            if staging.exists():
                staging.unlink()
        except OSError:
            pass
        return False, f"Could not write the archive: {exc}", stats

    stats["bytes"] = dest.stat().st_size
    return True, (f"Saved {dest.name} "
                  f"({stats['images']} images, "
                  f"{stats['bytes'] // 1024} KB)"), stats
