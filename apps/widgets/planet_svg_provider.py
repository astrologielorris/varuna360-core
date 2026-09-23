"""Body name + icon family -> validated SVG, painted as vector at paint time.

SVG packs stay vector through QPicture recording and magnification. Each pass
is recolored to the active palette; invalid sources return None so callers can
draw the same body's procedural fallback."""
import json
import logging
import re
import xml.etree.ElementTree as ET
from functools import lru_cache
from apps.widgets.planet_icon_style import passes_for, recolor_source, pass_arguments
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtSvg import QSvgRenderer

log = logging.getLogger(__name__)

SETS_DIR = Path(__file__).resolve().parents[2] / 'img' / 'planets' / 'sets'
ADDITIONAL_SETTING = 'display.additional_body_icon_set'
# Persisted value -> pack directory. 'current' is the procedural renderer.
ADDITIONAL_FAMILIES = {'current': None, 'custom_svg': 'optional-symbols'}

# A dark casing and pale gold core stay legible on light, dark and wood. Widths
# are in 100-unit viewBox space and shared by SVG packs and fallback paths.
PASSES = (('#302b27', 7), ('#f3d596', 3.5))
SIMPLE_PASSES = (('#302b27', 10, 3.5), ('#f3d596', 6.5, 0))
PLANET_FAMILIES = {'artistic': None, 'simple_svg': 'simple-planets'}
SVG_NS = 'http://www.w3.org/2000/svg'
BASE_STROKE = 5.0
MAX_BYTES = 10_000
MAX_PATH_COMMANDS = 200
_SHAPES = {'path', 'circle', 'ellipse', 'line', 'polyline', 'polygon', 'rect'}
_ATTRS = {
    'svg': {'viewBox', 'width', 'height'},
    'g': {'fill', 'stroke', 'stroke-width', 'stroke-linecap', 'stroke-linejoin'},
    'path': {'d', 'fill'}, 'circle': {'cx', 'cy', 'r', 'fill'},
    'ellipse': {'cx', 'cy', 'rx', 'ry', 'fill'}, 'line': {'x1', 'y1', 'x2', 'y2'},
    'polyline': {'points', 'fill'}, 'polygon': {'points', 'fill'},
    'rect': {'x', 'y', 'width', 'height', 'fill'},
}
_VALUES = dict.fromkeys(('fill', 'stroke'), re.compile(r'none|#[0-9a-fA-F]{6}')) | {
    'stroke-width': re.compile(r'\d+(\.\d+)?')}

ET.register_namespace('', SVG_NS)

def selected_additional_family():
    """Pack directory for the optional-body appearance setting, or None."""
    from managers.settings_manager import get_settings
    value = get_settings().get(ADDITIONAL_SETTING, 'current')
    return ADDITIONAL_FAMILIES.get(value)


def validate_svg(data):
    """Problems that disqualify a source (empty list = acceptable)."""
    if len(data) > MAX_BYTES:
        return [f'{len(data)} bytes exceeds {MAX_BYTES}']
    try:
        text = data.decode('utf-8')
        if '<!' in text.replace('<!--', ''):
            return ['DOCTYPE/ENTITY/CDATA declarations are not allowed']
        root = ET.fromstring(text)
    except (UnicodeDecodeError, ET.ParseError, ValueError) as exc:
        return [f'not a UTF-8 XML document: {exc}']
    level = [root]
    for _ in range(6):
        level = [child for node in level for child in node]
    return ['nesting deeper than 6 levels'] if level else _document_problems(root)


def _document_problems(root):
    problems = []
    if root.tag != f'{{{SVG_NS}}}svg':
        problems.append('root element is not an SVG-namespace <svg>')
    if root.get('viewBox') != '0 0 100 100':
        problems.append('viewBox must be "0 0 100 100"')
    elements = list(root.iter())
    for element in elements:
        problems.extend(_element_problems(element))
    if not any(element.tag.rpartition('}')[2] in _SHAPES for element in elements):
        problems.append('no drawable shapes')
    commands = sum(len(re.findall(r'[A-Za-z]', element.get('d', ''))) for element in elements)
    if commands > MAX_PATH_COMMANDS:
        problems.append(f'{commands} path commands exceeds {MAX_PATH_COMMANDS}')
    return problems


def _element_problems(element):
    namespace, _, tag = element.tag.rpartition('}')
    if namespace != '{' + SVG_NS or tag not in _ATTRS:
        return [f'forbidden element <{element.tag}>']
    problems = [f'forbidden attribute {name!r} on <{tag}>'
                for name in element.attrib if name not in _ATTRS[tag]]
    problems += [f'{name}={value!r} is not an allowed value'
                 for name, value in element.attrib.items()
                 if name in _VALUES and not _VALUES[name].fullmatch(value)]
    if (element.text or '').strip() or (element.tail or '').strip():
        problems.append(f'live text in <{tag}>')
    return problems


def recolor(data, color, width_scale, outline=0):
    return recolor_source(data, color, width_scale, outline)


@lru_cache(maxsize=16)
def _manifest(pack, revision):
    path = SETS_DIR / pack / 'manifest.json'
    try:
        entries = json.loads(path.read_text(encoding='utf-8'))['bodies']
        if not all(isinstance(entry['file'], str) for entry in entries):
            raise TypeError('file names must be strings')
        return {entry['body']: entry['file'] for entry in entries}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        log.warning('Icon pack manifest unusable (%s): %s', path, exc)
        return {}


def _revision(path):
    try:
        return (stat := path.stat()).st_mtime_ns, stat.st_size
    except OSError:
        return None


def pack_revision_signature(pack):
    """Stable cache key for every file revision in a selected SVG pack."""
    return pack and (pack, tuple((p.name, _revision(p)) for p in sorted((SETS_DIR / pack).glob('*'))))


def source_path(pack, body):
    """Validated-later source file for body in pack, or None when unmapped."""
    manifest = SETS_DIR / pack / 'manifest.json'
    filename = _manifest(pack, _revision(manifest)).get(body)
    if not isinstance(filename, str) or not filename or Path(filename).name != filename:
        return None
    return SETS_DIR / pack / filename


@lru_cache(maxsize=64)
def _renderers(path, revision, passes):
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        log.warning('Icon SVG unreadable (%s): %s', path, exc)
        return None
    problems = validate_svg(data)
    if problems:
        log.warning('Icon SVG rejected (%s): %s', path, '; '.join(problems))
        return None
    try:
        renderers = tuple(QSvgRenderer(QByteArray(recolor(data, *pass_arguments(entry))))
                          for entry in passes)
    except Exception as exc:
        log.warning('Icon SVG not recolorable (%s): %r', path, exc)
        return None
    if not all(renderer.isValid() for renderer in renderers):
        log.warning('Icon SVG not renderable by Qt (%s)', path)
        return None
    return renderers


@lru_cache(maxsize=64)
def _warn_missing(path):
    # Cached so a repainting chart reports a missing file once, not per frame.
    log.warning('Icon SVG missing: %s', path)


def renderers_for(pack, body, passes):
    """Cached per-pass renderers, or None so the caller falls back."""
    if pack is None:
        return None
    path = source_path(pack, body)
    if path is None:
        return None
    revision = _revision(path)
    if revision is None:
        _warn_missing(str(path))
        return None
    return _renderers(str(path), revision, tuple(passes))


def paint_renderers(painter, rect, renderers):
    """Paint every pass into the largest centered square of rect."""
    side = min(rect.width(), rect.height())
    target = QRectF(rect.center().x() - side / 2, rect.center().y() - side / 2, side, side)
    for renderer in renderers:
        renderer.render(painter, target)


def _stroke_path(painter, rect, path, passes=PASSES):
    painter.translate(rect.left(), rect.top())
    painter.scale(rect.width() / 100, rect.height() / 100)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for entry in passes:
        color, width = entry[:2]
        pen = QPen(QColor(color), width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(path)


def paint_vector_icon(painter, rect, body, pack, fallback):
    """Vector item adapter: pack SVG when valid, else fallback(body) QPainterPath."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderers = renderers_for(pack, body, passes_for(body))
    if renderers:
        paint_renderers(painter, rect, renderers)
    else:
        _stroke_path(painter, rect, fallback(body), passes_for(body))
    painter.restore()
