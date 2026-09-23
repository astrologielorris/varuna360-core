"""Glyph-only sign badge placement without sign-name geometry."""

from apps.widgets.north_indian_items import badge_corners_inside, place_sign_icon


def draw_glyph_only_badges(scene, geometry, sign_for_house, sign_display,
                            font_color, offset_x, offset_y, tag, icon_loader,
                            point_in_polygon):
    """Place one square glyph badge per house and record its true footprint."""
    for house_num in range(1, 13):
        geom = geometry[house_num]
        sign_index = sign_for_house(house_num)
        polygon, centroid = geom['polygon'], geom['center']
        size = 140 if geom.get('shape') == 'diamond' else 90
        anchor_x, anchor_y = geom['icon_position']
        anchor_x, anchor_y = anchor_x + offset_x, anchor_y + offset_y
        dx, dy = centroid[0] - anchor_x, centroid[1] - anchor_y
        distance = (dx * dx + dy * dy) ** 0.5
        ux, uy = ((dx / distance, dy / distance)
                  if distance > 1e-6 else (0.0, 0.0))
        left, top = centroid[0] - size / 2, centroid[1] - size / 2
        for step in range(21):
            cx, cy = anchor_x + ux * step * 10, anchor_y + uy * step * 10
            if badge_corners_inside(point_in_polygon, cx - size / 2,
                                    cy - size / 2, size, size, polygon, 18):
                left, top = cx - size / 2, cy - size / 2
                break
        geom['badge_rect'] = (left, top, size, size)
        place_sign_icon(scene, sign_display, sign_index, left + size / 2,
                        top + size / 2, size, font_color, tag, icon_loader)
