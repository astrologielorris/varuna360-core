# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Human Design Calculator

Calculates the Design date by finding when the Sun is 88 degrees backward
from the birth date. This represents the unconscious/design aspect in
Human Design astrology.

The Design date is typically ~88 days (3 months) before birth, since the
Sun moves approximately 1 degree per day through the zodiac.
"""

from libaditya import swe

from core.planets_calculator import get_calendar_flag_from_jd


# Time constants (in Julian Days)
ONE_SECOND_JD = 1.157401129603386e-05
ONE_MINUTE_JD = ONE_SECOND_JD * 60
ONE_HOUR_JD = ONE_MINUTE_JD * 60
ONE_DAY_JD = ONE_HOUR_JD * 24


def calculate_design_jd(birth_jd):
    """
    Calculate the Julian Day for the Design date.

    The Design date is when the Sun is 88 degrees backward from the birth date.
    Uses iterative refinement to achieve precision of <0.0001 degrees.

    Args:
        birth_jd (float): Julian Day of birth date

    Returns:
        float: Julian Day of the Design date (approximately 88 days before birth)
    """
    # Get birth Sun position
    birth_sun_pos = swe.calc_ut(birth_jd, swe.SUN)[0][0]

    # Calculate target Sun position (88 degrees backward)
    target_sun_pos = (birth_sun_pos - 88) % 360

    # Start search 95 days before birth
    test_jd = birth_jd - (95 * ONE_DAY_JD)

    # Iterative refinement to find when Sun reaches target position
    while True:
        test_sun_pos = swe.calc_ut(test_jd, swe.SUN)[0][0]
        diff = abs(target_sun_pos - test_sun_pos) % 360

        # Handle wraparound (e.g., 359 to 1 degrees is actually 2 difference, not 358)
        if diff > 180:
            diff = 360 - diff

        # Iteratively refine with decreasing step sizes
        if diff > 1:
            test_jd = test_jd + ONE_DAY_JD
        elif diff > 0.5:
            test_jd = test_jd + 12 * ONE_HOUR_JD
        elif diff > 0.25:
            test_jd = test_jd + 6 * ONE_HOUR_JD
        elif diff > 0.1:
            test_jd = test_jd + 2 * ONE_HOUR_JD
        elif diff > 0.01:
            test_jd = test_jd + 5 * ONE_MINUTE_JD
        elif diff > 0.001:
            test_jd = test_jd + ONE_MINUTE_JD
        elif diff <= 0.0001:
            # Achieved required precision
            break
        else:
            test_jd = test_jd + ONE_SECOND_JD

    return test_jd


def get_design_date_info(birth_jd):
    """
    Get calendar date and time info for the Design date.

    Args:
        birth_jd (float): Julian Day of birth date

    Returns:
        dict: {
            'jd': design_jd,
            'year': year,
            'month': month,
            'day': day,
            'hour': hour (decimal, UTC)
        }
    """
    design_jd = calculate_design_jd(birth_jd)

    # Convert Julian Day back to calendar date
    year, month, day, hour = swe.revjul(design_jd, get_calendar_flag_from_jd(design_jd))

    return {
        'jd': design_jd,
        'year': int(year),
        'month': int(month),
        'day': int(day),
        'hour': hour
    }
