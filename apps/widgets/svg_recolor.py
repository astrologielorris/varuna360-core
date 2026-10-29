"""SVG recolouring helpers shared by the planet SVG packs (extracted from
planet_icon_style so that module stays within its line budget)."""


def recolor_source(data, color, width_scale, outline=0):
    """Recolor both strokes and fills; optional casing outlines filled silhouettes."""
    import xml.etree.ElementTree as ET
    root = ET.fromstring(data)
    for element in root.iter():
        for name in ('fill', 'stroke'):
            if element.get(name, 'none') != 'none':
                element.set(name, color)
        if 'stroke-width' in element.attrib:
            element.set('stroke-width', f"{float(element.get('stroke-width')) * width_scale:g}")
        elif outline and element.get('fill', 'none') != 'none':
            element.set('stroke', color)
            element.set('stroke-width', str(outline))
            element.set('stroke-linejoin', 'round')
    return ET.tostring(root)


def pass_arguments(entry):
    return entry[0], entry[1] / 5.0, entry[2] if len(entry) > 2 else 0
