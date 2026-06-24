# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Geometry helpers for the round zodiac wheel.
Handles polar/cartesian conversion and rotation calculations.
"""
import math


def calculate_rotation_offset(ascendant_degrees: float) -> float:
    """
    Calculate rotation to place Ascendant at LEFT (9 o'clock / 180°).

    In standard geometry:
      0° = 3 o'clock (Right)
      90° = 12 o'clock (Top)
      180° = 9 o'clock (Left)
      270° = 6 o'clock (Bottom)

    Args:
        ascendant_degrees: Ascendant position in degrees (0-360)

    Returns:
        Rotation offset to apply to all elements
    """
    TARGET_VISUAL_ANGLE = 180.0  # Left side = 9 o'clock
    return TARGET_VISUAL_ANGLE - ascendant_degrees


def polar_to_cartesian(cx: float, cy: float, radius: float, angle_degrees: float) -> tuple:
    """
    Convert polar coordinates to Tkinter canvas coordinates.

    Args:
        cx, cy: Center point of the wheel
        radius: Distance from center
        angle_degrees: Angle in degrees (0° = East/Right, counter-clockwise)

    Returns:
        (x, y) tuple for canvas placement

    Note: Tkinter's Y-axis is inverted (0 at top, increases downward),
    so we use MINUS for the sin component.
    """
    angle_rad = math.radians(angle_degrees)
    x = cx + radius * math.cos(angle_rad)
    y = cy - radius * math.sin(angle_rad)  # Minus for inverted Y-axis
    return (x, y)


def get_sector_center_angle(sign_index: int, rotation_offset: float) -> float:
    """
    Get the center angle of a zodiac sector after rotation.

    Each sign spans 30°. Sign 0 (Aries/Dhata) starts at 0°.
    The center of sign 0 is at 15°.

    Args:
        sign_index: 0-11 (0=Aries/Dhata, 11=Pisces/Parjanya)
        rotation_offset: Global rotation applied to wheel

    Returns:
        Center angle in degrees for the sector
    """
    base_center = sign_index * 30 + 15  # Center of 30° sector
    return base_center + rotation_offset


def get_sector_start_angle(sign_index: int, rotation_offset: float) -> float:
    """
    Get the starting angle of a zodiac sector after rotation.

    Args:
        sign_index: 0-11
        rotation_offset: Global rotation applied to wheel

    Returns:
        Start angle in degrees for the sector
    """
    base_start = sign_index * 30
    return base_start + rotation_offset


def normalize_angle(angle: float) -> float:
    """Normalize angle to 0-360 range."""
    return angle % 360


def angle_to_canvas_arc(angle_degrees: float) -> float:
    """
    Convert standard math angle to Tkinter canvas arc angle.

    Tkinter's create_arc uses:
    - 0° = 3 o'clock (East)
    - Angles increase counter-clockwise
    - 'start' parameter is where the arc begins

    Our system uses the same convention, so this is mostly
    for clarity and potential future adjustments.
    """
    return angle_degrees


def get_planet_angle(planet_degrees: float, rotation_offset: float) -> float:
    """
    Get the visual angle for a planet on the wheel.

    Args:
        planet_degrees: Planet's zodiac position (0-360)
        rotation_offset: Global rotation applied to wheel

    Returns:
        Visual angle for canvas placement
    """
    return planet_degrees + rotation_offset


def degrees_to_sign_position(degrees: float) -> tuple:
    """
    Convert absolute degrees to sign index and position within sign.

    Args:
        degrees: 0-360 zodiac position

    Returns:
        (sign_index, degrees_in_sign) tuple
    """
    sign_index = int(degrees // 30) % 12
    degrees_in_sign = degrees % 30
    return (sign_index, degrees_in_sign)
