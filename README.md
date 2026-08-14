# Varuna360 Core

**Tropical Vedic astrology, open-sourced.**

Varuna360 Core is the free, open-source foundation of Varuna360, a desktop
astrology application that computes and visualizes charts in **Tropical,
Sidereal, and Aditya Circle** modes with Vedic concepts (Adityas,
Nakshatras, Vedic mythology). The author practices Tropical astrology,
but the software computes both Tropical and Sidereal with full ayanamsa
support. It is the same calculation engine that powers the Pro edition.

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Upgrade to Pro](https://img.shields.io/badge/Pro-%E2%82%AC29.99%2Fmonth-orange)](https://360heartsinthesky.com/subscribe)

![Varuna360 Core full interface with wheel chart, panels, and dasha timeline](docs/help/images/interface_full.webp)

> **[Read the full manual](docs/help/manual.html)** for a complete walkthrough of every feature.

---

## Built on libaditya

Varuna360 Core is built on top of
[**libaditya**](https://gitlab.com/ninthhouse/libaditya), an astrological
calculation library created by Josh
([ninthhouse](https://gitlab.com/ninthhouse)). His work on libaditya gave
this project a solid, well-structured foundation for tropical, sidereal,
and Aditya zodiac calculations, divisional charts, Vimshottari Dasha,
Jaimini techniques, Human Design bodygraphs, Cards of Truth, and more.
Without his library, Varuna360 would not have the calculation backbone it
has today.

Many features inside libaditya do not yet have a GUI in Varuna360, but
they are fully functional from the command line or through an AI assistant.
If you have a Claude or ChatGPT/Codex subscription and know how to work
with AI, you can use libaditya's Python API directly to explore chart
calculations, vargas, dignities, and other techniques that the desktop
interface does not yet cover.

Josh has also created several mobile astrology apps. You can find them
across his various repositories on
[GitLab](https://gitlab.com/ninthhouse).

## What's in Core

- Every paid Core feature runs fully from source with no account
- Full interactive wheel chart with clickable planets and signs showing detailed descriptions
- 5 chart views: Wheel, South Indian, North Indian, Body Graph and Cards of Truth
- Two South Indian styles: a new conventional vector chart, or the classic artistic one
- Cards of Truth as its own view, and as an index drawn inside the wheel, the South Indian and the North Indian charts
- A second chart overlaid on the first, shown in the centre of the chart itself, so any two-chart comparison stays in one view
- Fullscreen on any chart with the `F` key, the way a video player does it
- Light and dark themes with color presets, plus a saturation slider to tone the whole interface
- 3 zodiac configurations: Aditya Circle (from Ernst Wilhelm's new research), Tropical Western, and Sidereal, with many ayanamsa options
- Human Design mode (computes the astrology layer of Human Design, bodygraph coming in a later update)
- Divisional charts (Varga D1 to D60)
- Trimsamsa and Hora panels with full chart creation (from Ernst Wilhelm's Aditya retinue course)
- Interactive Vimshottari Dasha timeline
- CHTK file import and export (Kala compatibility)
- Automatic chart download from the web (Wikipedia biography search)
- Chart editing with an interactive themed map that shows the timezone and the Ascendant a place produces before you apply it
- Find Chart: search your chart database by planetary positions in any zodiac mode
- User profiles (like Chrome) to save charts in memory
- Autosave and Autoload, never lose your chart data again
- 16 Tajika aspects and Yoga detection plus Vedic planetary aspects
- Nabhasa Yogas panel: the twenty Akriti yogas detected, drawn and described
- Avastha relationship analysis (help and damage between planets), with refined strength, positive and negative rows split out, and its own fullscreen page
- Element and Modality breakdown with pie charts
- Per-area font sizes, so the chart, the tables and the panels scale independently of the interface
- Planetary strength (Shadbala) and Karakas panels
- Available on Windows, Linux and Mac

## What's in Varuna360 Pro

Pro is the larger paid edition, with new screens, advanced research tools,
and features being added over time. It is AGPL-3.0 too, like everything else
in Varuna360: Pro subscribers receive its corresponding source. It is simply
**not** published in this repository, and Core never imports from it. If you
want any of these, see
[Varuna360 Pro](https://360heartsinthesky.com/subscribe):

- All Core features
- Full transit screen with real-time tracking
- Eclipse and Saros panel: per-country Ascendant map plus historical Saros cycle research
- Solar return screen
- AI-assisted chart interpretation
- Psychological pattern and trauma detection (Lajitadi)
- Element and Modality statistical analysis
- Chinese Lunar New Year tab
- Nakshatra wheel with innovative display options
- Birth Finder: reverse-engineer charts from planetary positions
- Pattern searching across time and databases
- Planet Ingress and Conjunction finder
- New features added regularly

## Pricing

Varuna360 Core runs fully from this repository under AGPL-3.0, with no
account, no payment, no server call at launch. The desktop app is a
legitimate product you can test for free for as long as you want.
When you decide it is worth paying for, the website offers three
account tiers that unlock content on the web app.

### Website tiers

| Tier               | Price                        | Website access                                                                 |
|--------------------|------------------------------|---------------------------------------------------------------------------------|
| No account         | €0                           | Natal chart calculation, manual entry, element pie charts plus positions table, dominant Aditya description, Ascendant plus House Strength |
| Registered free    | €0                           | All No account features plus celebrity database, transit ring (current planets), 2 save slots |
| Explorer           | €9.99 / month                | All Registered free features plus CHTK file import, full transit calculation plus Now button, Dignified Planets panel, Divine Cow (Kamadhenu) panel, Planet Strength (Shadbala) panel, 20 save slots |

### Desktop and mobile distribution

| Distribution       | Price                        | What you get                                                                   | Status      |
|--------------------|------------------------------|---------------------------------------------------------------------------------|-------------|
| Source (this repo) | €0                           | Every Core feature, AGPL-3.0, clone and build                                  | Available   |
| Lite Mobile        | From €3 / month              | The Aditya wheel on Android: Hora and Trimsamsa rings, Avastha, 16 Tajika aspects, live transits and live Ascendant | Available |
| Lite Desktop       | From €3 / month, suggested €14.99 / month | Same Core features as source plus pre-built installer, auto-updates, email help, matching website tier | Coming Soon |
| Pro                | €29.99 / month               | Everything in Core plus the "What's in Varuna360 Pro" list above               | Coming Soon |

Every paid tier is a monthly recurring subscription, priced in EUR.

**You choose what you pay.** Lite Desktop and Lite Mobile use a slider
starting at €3 / month. €14.99 is what the author suggests, not a gate:
salaries are not the same everywhere, and there is no proof to provide and
no country box to tick. Pay what your situation allows, and adjust later if
it changes.

Two thresholds are worth knowing. From €9.90 / month, Lite Desktop includes
the mobile app. From €11 / month, it also includes the Explorer website
tier; below €11 the two subscriptions simply coexist.

**The €29.99 Pro price is not final.** Pro is still growing, and the price
may change as it does. Treat it as the current intent rather than a
commitment.

The bundled installers and the Pro subscription go live on
[360heartsinthesky.com](https://360heartsinthesky.com) when ready. Building
from this source stays free forever under AGPL-3.0.

## Running from source

```bash
git clone https://github.com/astrologielorris/varuna360-core.git
cd varuna360-core
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
python apps/core_gui_qt.py
```

You'll need the Swiss Ephemeris data files in `ephe/`. They are bundled
with this repository.

## License

The whole of Varuna360 is licensed under the **GNU AGPL v3.0**, Core and Pro
alike. Pro is a paid edition, not a proprietary one. See [`LICENSE`](LICENSE)
for the full text and [`NOTICE`](NOTICE) for copyright details. The author,
Lorris Turpin, holds the copyright and, as sole copyright holder, reserves
the right to license his own code under other terms as well. That reservation
does not affect the AGPL-3.0 grant on the copy you have.

## Contributing

This repository is a **read-only mirror** of an internal canonical
codebase. Direct pull requests are **not accepted at this time.** Please
see [`CONTRIBUTING.md`](CONTRIBUTING.md) for how to report bugs and
propose patches.

## Security

To report a security vulnerability, see [`SECURITY.md`](SECURITY.md).
**Do not** open a public GitHub issue for security reports.

## Links

- **Website:** https://360heartsinthesky.com
- **Upgrade to Pro:** https://360heartsinthesky.com/subscribe
- **Issues:** https://github.com/astrologielorris/varuna360-core/issues

---

<!-- RELEASE-BLOCK:BEGIN -->
<!-- Generated at sync time from VERSION + CHANGELOG.md. Edits here are
     overwritten on the next sync; edit CHANGELOG.md instead. -->

## Current release: 4.4.0 (2026-08-14)

The chart-entry release: the Edit Chart tab is rebuilt from the ground up as
"New & Edit", and the macOS packages are fixed.

### Added

- **The New & Edit tab**, a full redesign of chart entry. Type or paste a
  birth line ("Marie 12 June 1990 14:30 Paris, France") into the new token
  bar and it parses into editable chips that fill the form; click a chip to
  correct its token. Creating a chart is one click: create, save and open.
- **A simpler, safer form.** Time-zone fields are locked by default and
  filled by the map or the place search (unlock them if you need to), the
  UTC time derives live as you type, a missing birth time falls back to noon
  with a visible warning, and impossible dates and times are blocked at the
  keyboard. DST is now a single "DST applied" toggle, resolved automatically
  from the place and the date.
- **Every field is selectable and copyable**, plus a copy-all button that
  puts the whole birth data on the clipboard in one move.
- **Rodden rating** on a chart, with a help popup explaining the scale.
- **Elevation** looked up for the selected place and shown as a chip.
- **Save & open** in edit mode: save the correction, then show the chart.
- **Drag a chart onto the TRANSIT button** to overlay it on the current
  chart, or right-click a saved chart and pick "Overlay on current chart".
- **Move a chart to another profile** from the saved-chart right-click menu.
- **The Birth Time popup redrawn**: a live preview recomputes the chart as
  you drag, highlights what changed in red, follows the light theme, and a
  "Revert to saved" undoes the whole adjustment. The window title now shows
  seconds, for D60-level work.
- **A near-black variant** of the dark themes, opt-in, for OLED screens and
  late nights.
- **Place-search ambiguity warning.** A one-word search ("Brunswick") tells
  you which town it picked and how to ask for a different one.

### Fixed

- **The macOS app could not add a chart**: the packaged .app was missing its
  timezone database, so entering a birth place crashed. The data is now
  bundled and verified on every build. The app also starts correctly on
  Intel Macs and carries the blue Core icon.
- **The chart folder chosen during first-run setup was not applied.**
- **The South Indian chart now defaults to the conventional style.**
- **Online place search failed on some machines** because the system TLS
  certificates were not found; the app now carries its own.
- **Dignity had one-point holes at exact degree boundaries** (a planet at
  precisely 3.0 degrees could miss its mulatrikona).
- **Aryama's yaksha is Rathauja**, not Athauja.
- **TOML charts round-trip faithfully**: civil date stays in sync with the
  calendar, notes survive, tags are not duplicated.

Earlier releases are in [CHANGELOG.md](CHANGELOG.md).

<!-- RELEASE-BLOCK:END -->
