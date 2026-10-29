# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Settings rows for the custom ayanamsa (id 255) and the degrees after each ayanamsa.

Kept out of ``ui/settings_tab.py`` (which only calls ``build_rows``, ``read_rows``,
``apply_rows`` and ``show_offsets``) so the tab does not grow. The rows write the
three ``zodiac.custom_ayanamsa_*`` keys; the zodiac settings manager installs them
into the engine (core/custom_ayanamsa_settings.py).
"""
from PySide6.QtWidgets import QCheckBox, QDoubleSpinBox, QLabel, QLineEdit, QSpinBox

from core import custom_ayanamsa_settings as _custom
from core import settings_registry as _registry
from core.ayanamsa_data import CUSTOM_AYANAMSA_ID as CUSTOM_ID, format_dms, name_with_offset

DESCRIPTION = (
    "Your own ayanamsa: tick \"Use custom ayanamsa\" to use it for the chart, or choose "
    "\"{name}\" in a dasha ayanamsa list. Enter its value "
    "in degrees on 1 January of the reference year; precession moves it from there for "
    "every other date. The degrees after each ayanamsa name are the exact amount "
    "subtracted from tropical longitudes for the sidereal signs today (nutation "
    "included, so a few arcseconds from the value you typed); a negative amount is "
    "added. Dhruva GC mid-Mula and Vedanga Jyotisha measure their nakshatras in "
    "equatorial coordinates, which is not a single shift.")


def build_rows(form, desc_style, locked_row, header, ayanamsa_combo):
    """Add the rows to ``form`` under ``header`` (the tab's own section header
    builder, called with the title); returns the widgets dict the other calls take.

    ``ayanamsa_combo`` is the chart's Ayanamsa list: the "Use custom ayanamsa" box
    selects the custom entry (id 255) in it and grays it out while ticked."""
    header("Custom Ayanamsa")

    use = _sized(QCheckBox("Use custom ayanamsa"))
    form.addRow("", use)

    name = _sized(QLineEdit())
    name.setMaximumWidth(220)
    name.setToolTip(_registry.get(_custom.NAME_KEY).help)
    locked_row(form, _custom.NAME_KEY, _registry.get(_custom.NAME_KEY).label, name)

    lo, hi = _registry.get(_custom.VALUE_KEY).bounds
    value = _sized(QDoubleSpinBox())
    value.setRange(lo, hi)
    value.setDecimals(6)
    value.setSingleStep(1.0 / 60.0)
    value.setSuffix("°")
    value.setMaximumWidth(160)
    value.setToolTip(_registry.get(_custom.VALUE_KEY).help)
    locked_row(form, _custom.VALUE_KEY, _registry.get(_custom.VALUE_KEY).label, value)

    dms = QLabel()
    dms.setStyleSheet(desc_style)
    value.valueChanged.connect(lambda v: dms.setText(f"= {format_dms(v)}"))
    form.addRow("", dms)

    ylo, yhi = _registry.get(_custom.YEAR_KEY).bounds
    year = _sized(QSpinBox())
    year.setRange(int(ylo), int(yhi))
    year.setMaximumWidth(120)
    year.setToolTip(_registry.get(_custom.YEAR_KEY).help)
    locked_row(form, _custom.YEAR_KEY, _registry.get(_custom.YEAR_KEY).label, year)

    note = QLabel()
    note.setWordWrap(True)
    note.setStyleSheet(desc_style)
    form.addRow("", note)
    name.textChanged.connect(
        lambda text: note.setText(DESCRIPTION.format(name=text.strip() or "Custom")))
    widgets = {"name": name, "value": value, "year": year, "dms": dms, "note": note,
               "use": use, "combo": ayanamsa_combo, "previous": None}
    _link_combo(widgets)
    return widgets


def _sized(widget):
    """The tab's font size for inputs, tagged so a live font change replays it (td-c038)."""
    from ui.qt_theme import scaled_area_px
    widget.setStyleSheet(f"font-size: {scaled_area_px('buttons')}px;")
    widget.setProperty("_c038_font_area", "buttons")
    return widget


def _link_combo(widgets):
    """Keep the box, the Ayanamsa list and the custom entry's label in step."""
    combo, use = widgets["combo"], widgets["use"]

    def toggled(checked):
        current = combo.currentData()
        if checked and current != CUSTOM_ID:
            widgets["previous"] = current
            _select(combo, CUSTOM_ID)
        elif not checked and current == CUSTOM_ID:
            back = widgets["previous"]
            if back is None or combo.findData(back) < 0:
                back = _registry.default("zodiac.ayanamsa_id")
            _select(combo, back)
        combo.setEnabled(not checked)

    def combo_changed(_index):
        custom = combo.currentData() == CUSTOM_ID
        use.blockSignals(True)
        use.setChecked(custom)
        use.blockSignals(False)
        combo.setEnabled(not custom)

    def relabel(*_args):
        """The custom entry shows the typed name and degrees before Apply."""
        idx = combo.findData(CUSTOM_ID)
        if idx < 0:
            return
        from core.ayanamsa_data import today_jd
        from libaditya.custom_ayanamsa import using_custom_ayanamsa
        with using_custom_ayanamsa(widgets["value"].value(), widgets["year"].value(),
                                   widgets["name"].text()):
            combo.setItemText(idx, name_with_offset(CUSTOM_ID, today_jd()))

    use.toggled.connect(toggled)
    combo.currentIndexChanged.connect(combo_changed)
    widgets["name"].textChanged.connect(relabel)
    widgets["value"].valueChanged.connect(relabel)
    widgets["year"].valueChanged.connect(relabel)
    combo_changed(combo.currentIndex())


def _select(combo, value):
    idx = combo.findData(value)
    if idx >= 0:
        combo.setCurrentIndex(idx)


def custom_in_use(widgets):
    """True while the chart's Ayanamsa list is on the custom entry (list grayed)."""
    return widgets["combo"].currentData() == CUSTOM_ID


def read_rows(widgets, settings):
    """Show the saved definition."""
    name, value, year = _custom.read(settings)
    widgets["name"].setText(name)
    widgets["value"].setValue(value)
    widgets["year"].setValue(year)
    widgets["dms"].setText(f"= {format_dms(value)}")
    widgets["note"].setText(DESCRIPTION.format(name=name))


def apply_rows(widgets, settings):
    """Write the three keys; True when the definition changed."""
    new = (widgets["name"].text().strip() or "Custom",
           float(widgets["value"].value()), int(widgets["year"].value()))
    changed = new != _custom.read(settings)
    for key, val in zip(_custom.KEYS, new):
        settings.set(key, val)
    _custom.install_from(settings)   # the labels below read the new definition now
    return changed


def show_offsets(*combos):
    """Put each ayanamsa's exact degrees today after its name in these combos."""
    from core.ayanamsa_data import today_jd
    jd = today_jd()
    for combo in combos:
        for i in range(combo.count()):
            aid = combo.itemData(i)
            if isinstance(aid, int):
                combo.setItemText(i, name_with_offset(aid, jd))
