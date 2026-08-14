# Changelog

Release notes for **Varuna360 Core**, the open-source edition.

This file is the single source of the release notes that appear in the public
README. `release_gates/sync_to_mirror.py` reads the section matching the
`VERSION` file and stamps it into the mirror's README between the
`RELEASE-BLOCK` markers. **A sync fails if the current version has no section
here**, so every release carries notes by construction.

Format rules, because a script parses this file:

- One `## <version> (<YYYY-MM-DD>)` heading per release, newest first.
- Under it, only `### Added` and `### Fixed` (either may be omitted).
- Plain `- ` bullets. Keep them to the majors: this is a README, not a log.
- Only list what actually ships in **Core**. Pro-only work does not belong here.
- No em dashes or en dashes. This text is published verbatim in the README.
- **Write for someone whose last version was the previous public release.**
  A bug introduced and fixed between two releases never existed for them, so
  it is not a fix; it is part of the feature, and the feature goes under
  Added. Only list defects that were reachable in the version people are
  actually upgrading from. Nothing about the build, the release process or
  internal tooling belongs here either.

---

## 4.4.1 (2026-08-14)

### Fixed

- **On macOS, "Move a chart to another profile" did nothing when clicked.**
  The submenu actions could silently disconnect; the move now always fires.
- **The right-click menu on Nisarga dasha rows was permanently greyed out**,
  and when it acted it used Vimshottari cycle math. Nisarga rows now carry
  their own dates and their own rules.

## 4.4.0 (2026-08-14)

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

## 4.0.0 (2026-08-04)

The largest Core release so far: four new chart views, a rebuilt location
picker, and the first macOS build produced by CI rather than by hand.

### Added

- **Cards of Truth**, a fifth chart view, with the Deck Rail, the progression
  ladder, and the Age-N Quadration as a second timing family. Each card draws
  its own pips, cusps and period year, and the spread follows the varga column.
- **Cards of Truth inside the charts themselves.** Every sign can show the
  card of its ruling planet, in the wheel, the South Indian chart and the
  North Indian chart, so the index is readable without leaving the chart you
  are working in.
- **Fullscreen on any chart with the `F` key**, the way a video player does
  it, on every tab that displays a chart. Your zoom, pan and layout come back
  exactly as they were when you leave it.
- **A second chart overlaid on the first**, drawn in the centre of the chart
  itself. It is not only for transits: any two-chart comparison now stays in
  one view instead of splitting the screen.
- **Body Graph**, a new view mapping the chart onto the body, with per-zone
  aspect arrows, female body types, and its own divisional-chart support.
- **A new South Indian style.** The South Indian chart is redrawn as true
  vector art with themed sign pills and a calibrated lagna strike, and sits
  beside the classic artistic one as a choice rather than replacing it.
- **Nabhasa Yogas panel**: the twenty Akriti yogas detected and drawn, each
  with its diagram and description.
- **Refined Avastha strength**, with positive and negative rows split out, the
  dignity multiplier applied on the diagonal, retinue rows for Hora and
  Trimsamsa, and an expanded fullscreen page showing what each planet casts
  rather than only what it receives.
- **A redesigned map.** The location picker now follows your theme instead of
  always rendering in the pale OpenStreetMap palette, with a proper pin, a
  graticule, and a floating card that shows the timezone and the Ascendant
  your click produces before you apply it, so you can see what a place does to
  the chart without applying and rebuilding first.
- **`.toml` chart import**, so the Open Astrology Chart format is now a
  supported exchange format alongside CHTK.
- **Varga on the wheel**: divisional positions drawn as a ring on the wheel
  and the North Indian chart, and in the centre box.
- **Per-area font size settings**, so the chart, tables and panels scale
  independently of the interface.
- **A colour saturation slider**, which tones the whole interface down or up
  in one move without leaving your theme.
- **A session health banner** that tells you plainly when a save is failing,
  replacing a dialog that could interrupt you mid-chart, plus **built-in bug
  reporting** so a problem can be sent without assembling anything by hand.
- **A rewritten manual**, with a glossary, a beginner pass over every new
  section, and an option to save it for an AI assistant to read alongside the
  source code.
- **macOS builds from CI.** The macOS app is now built and packaged by GitHub
  Actions for both Apple Silicon and Intel.

### Fixed

- **The map is no longer slow or unpredictable.** Searching for a place could
  freeze the interface for ten to twenty seconds, clicking a point cost about
  two seconds, and one mouse-wheel gesture could jump several zoom levels at
  once, blanking the map and starting the wait again. Zoom is now a smooth
  transform rather than a rebuild, tiles load in the background, and picking a
  place is instant and works fully offline.
- **Moon's mulatrikona range** was wrong: it runs from 3 degrees to the end of
  Aryama, not 3 to 27. Dignity, and anything downstream of it, was affected.
- **Your work is much harder to lose.** An autosave landing during a profile
  switch could write into the wrong profile; a session file that failed to
  parse was overwritten rather than kept; some profile names produced a folder
  id the app could not read back; and Favorites did not re-sync at startup.
- **Editing the DST flag on a chart was silently discarded**, so a correction
  you made was not the chart you got.
- **CHTK gender codes**: the format uses three, not two, and one of them was
  read incorrectly on import.
- **Adjusting a chart's time could keep the previous house system**, leaving a
  stale cache behind the new positions.
- **Info panel column headers ignored the font size setting** and clipped
  their text at some window sizes.
- **Find Chart kept the old theme** when you switched theme while it was open.
- **The manual said outer planets do not cast sign aspects.** They do. A full
  factual audit corrected that and a number of other statements.
