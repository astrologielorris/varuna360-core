# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under the GNU AGPL-3.0. See LICENSE at the repository root.
"""
Chart Info / Wikipedia biography fetcher — pure Python, no GUI dependencies.
============================================================================
Extracted from apps/widgets/chart_title_widget.py (ChartInfoWorker).
Uses only requests + re + html.unescape().

Usage:
    from AI_tools.AI_main_function.chart_info import fetch_chart_info
    result = fetch_chart_info("Albert Einstein")
    if result["found"]:
        print(result["title"], result["content"][:500])
"""

import html
import re

import requests

_HEADERS = {"User-Agent": "Varuna360/1.0 (Vedic Astrology App)"}
_API_URL = "https://en.wikipedia.org/w/api.php"


def fetch_chart_info(name: str, timeout: int = 30, max_chars: int = 0) -> dict:
    """
    Fetch a Wikipedia biography for *name*.

    Args:
        name: Person (or topic) to search for.
        timeout: HTTP timeout in seconds.
        max_chars: If >0, truncate content to this many characters.

    Returns:
        dict with keys:
            found  (bool)  — True if a page was found and parsed
            title  (str)   — Wikipedia article title
            content (str)  — Clean plain-text content
            url    (str)   — Full Wikipedia URL
            error  (str)   — Error description (only when found=False)
    """
    try:
        # Step 1: Search Wikipedia
        search_params = {
            "action": "query",
            "list": "search",
            "srsearch": name,
            "srlimit": 5,
            "format": "json",
        }
        resp = requests.get(_API_URL, params=search_params,
                            headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
        results = resp.json().get("query", {}).get("search", [])

        if not results:
            return {"found": False, "error": f"No Wikipedia article found for '{name}'"}

        page_title = results[0]["title"]

        # Step 2: Fetch article HTML
        parse_params = {
            "action": "parse",
            "page": page_title,
            "prop": "text",
            "format": "json",
            "disabletoc": "true",
        }
        resp2 = requests.get(_API_URL, params=parse_params,
                             headers=_HEADERS, timeout=timeout)
        resp2.raise_for_status()
        data = resp2.json()

        if "error" in data:
            return {"found": False,
                    "error": data["error"].get("info", "Unknown API error")}

        html_content = data.get("parse", {}).get("text", {}).get("*", "")
        if not html_content:
            return {"found": False, "error": f"No content for '{page_title}'"}

        # Step 3: Convert to clean text
        clean = _html_to_text(html_content)
        if not clean.strip():
            return {"found": False,
                    "error": f"Could not extract text from '{page_title}'"}

        if max_chars > 0:
            clean = clean[:max_chars]

        url = f"https://en.wikipedia.org/wiki/{page_title.replace(' ', '_')}"

        return {"found": True, "title": page_title, "content": clean, "url": url}

    except requests.exceptions.Timeout:
        return {"found": False, "error": "Request timed out"}
    except requests.exceptions.RequestException as e:
        return {"found": False, "error": f"Network error: {e}"}
    except Exception as e:
        return {"found": False, "error": f"Error: {e}"}


def _html_to_text(html_str: str) -> str:
    """
    Convert Wikipedia HTML to clean readable text.

    Verbatim logic from ChartInfoWorker._html_to_text() — uses only re + html.unescape().
    """
    text = html_str

    # Remove script and style tags
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)

    # Remove reference tags [1], [2], etc.
    text = re.sub(r'\[(?:edit|citation needed|\d+)\]', '', text)

    # Remove infobox, navbox, sidebar tables
    text = re.sub(
        r'<table[^>]*class="[^"]*(?:infobox|navbox|sidebar|vertical-navbox|wikitable)[^"]*"[^>]*>.*?</table>',
        '', text, flags=re.DOTALL | re.IGNORECASE)

    # Remove nav/ref divs
    text = re.sub(
        r'<div[^>]*class="[^"]*(?:navbox|catlinks|reflist|references|mw-references|toc|thumb|gallery)[^"]*"[^>]*>.*?</div>',
        '', text, flags=re.DOTALL | re.IGNORECASE)

    # Headers
    text = re.sub(r'<h2[^>]*><span[^>]*>([^<]*)</span>.*?</h2>', r'\n\n═══ \1 ═══\n\n', text, flags=re.DOTALL)
    text = re.sub(r'<h3[^>]*><span[^>]*>([^<]*)</span>.*?</h3>', r'\n\n─── \1 ───\n\n', text, flags=re.DOTALL)
    text = re.sub(r'<h4[^>]*><span[^>]*>([^<]*)</span>.*?</h4>', r'\n\n── \1 ──\n\n', text, flags=re.DOTALL)
    text = re.sub(r'<h[1-6][^>]*>([^<]*)</h[1-6]>', r'\n\n═══ \1 ═══\n\n', text)

    # Paragraphs
    text = re.sub(r'</p>\s*<p[^>]*>', '\n\n', text)
    text = re.sub(r'<p[^>]*>', '\n', text)
    text = re.sub(r'</p>', '\n', text)

    # Lists and breaks
    text = re.sub(r'<li[^>]*>', '\n  • ', text)
    text = re.sub(r'</li>', '', text)
    text = re.sub(r'<br\s*/?>', '\n', text)

    # Strip remaining tags
    text = re.sub(r'<[^>]+>', '', text)

    # Decode entities
    text = html.unescape(text)

    # Whitespace cleanup
    text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r' +\n', '\n', text)
    text = re.sub(r'\n +', '\n', text)

    # Remove trailing reference sections
    for section in ['See also', 'References', 'External links', 'Further reading', 'Notes']:
        text = re.sub(rf'\n═══ {section} ═══.*', '', text, flags=re.DOTALL | re.IGNORECASE)

    return text.strip()
