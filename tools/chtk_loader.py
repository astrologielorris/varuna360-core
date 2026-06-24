# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
CHTK Loader - External module for loading CHTK files into chart applications.
Keeps core_gui.py clean by extracting loading logic to this module.
"""

import os
import re
from datetime import datetime, timedelta
from core.chtk_reader import CHTKReader



def load_chart_from_datetime(app, dt, lat, lon, name="Synthetic Chart",
                             preserve_natal=False):
    """Build a Chart from datetime + location, dispatch to state.

    Args:
        preserve_natal: If True, don't overwrite natal-specific fields
            (person_name, birth_metadata, etc.). Use for event charts
            (lunar, eclipse) that shouldn't pollute natal state.

    Returns True on success, False on failure.
    """
    try:
        from core.chart_factory import build_chart_from_params
        mode = getattr(app, 'aditya_mode', None)
        if mode is None and hasattr(app, 'state'):
            mode = getattr(app.state, 'aditya_mode', 'aditya')
        if mode is None:
            mode = 'aditya'

        # SPEC-HSY-001: read the active house system from app state the same
        # way mode is read above. Falls back to "C" when state is unavailable.
        hsys = "C"
        if hasattr(app, 'state'):
            hsys = getattr(app.state, 'house_system_code', 'C')

        from core.time_utils import julday
        hour_dec = dt.hour + dt.minute / 60.0 + dt.second / 3600.0
        jd = julday(dt.year, dt.month, dt.day, hour_dec)

        chart = build_chart_from_params(
            jd=jd, lat=lat, lon=lon, mode=mode, name=name,
            utcoffset=0.0,
            ayanamsa=getattr(app, 'chart_sidereal_ayanamsa_id', 98),
            hsys=hsys,
        )

        if not preserve_natal:
            app.person_name = name
            app.city = f"Lat {lat:.2f}, Lon {lon:.2f}"
            app.birth_country = "Synthetic"
            app.loaded_chtk_path = None

            app.birth_metadata = {
                'name': name, 'year': dt.year, 'month': dt.month,
                'day': dt.day, 'hour': dt.hour, 'minute': dt.minute,
                'second': dt.second, 'gender': '',
                'latitude': lat, 'longitude': lon,
                'timezone': '+00:00:00', 'time_change_flag': 0,
                'dst': 0,
                'city': f"Lat {lat:.2f}", 'country': f"Lon {lon:.2f}",
                'location': {'city': f"Lat {lat:.2f}", 'country': f"Lon {lon:.2f}", 'timezone': 'UTC'},
                'coordinates': {'latitude': lat, 'longitude': lon},
            }

        if hasattr(app, 'state'):
            from state.events import SetActiveChart
            app.state.dispatch(SetActiveChart(chart=chart))

        return True
    except Exception as e:
        print(f"Error loading chart from datetime: {e}")
        return False
