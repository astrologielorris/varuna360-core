"""Chart visibility policy for the ten optional bodies and points."""
from libaditya.optional_bodies import BODIES
from shiboken6 import isValid

SETTING = 'chart.additional_bodies'


def enabled_names():
    from managers.settings_manager import get_settings
    selected = get_settings().get(SETTING, [])
    if not isinstance(selected, (list, tuple)):
        return ()
    return tuple(body.name for body in BODIES if body.name in selected)


def display_names(base):
    return tuple(dict.fromkeys((*base, *enabled_names())))


def visible_items(planets, base):
    for name in display_names(base):
        try:
            yield name, planets[name]
        except KeyError:
            continue


def add_unavailable_notice(scene, planets):
    """Surface ephemeris failures without placing anything in the chart center."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QFont
    from PySide6.QtWidgets import QGraphicsTextItem
    for old in scene.items():
        if old.data(Qt.ItemDataRole.UserRole) == 'additional_body_notice':
            scene.removeItem(old)
    errors = getattr(planets, 'additional_body_errors', {})
    missing = [name for name in enabled_names() if name in errors]
    if not missing:
        return
    item = QGraphicsTextItem('Unavailable for this chart: ' + ', '.join(missing))
    item.setFont(QFont('DejaVu Sans', 18))
    item.setDefaultTextColor(QColor('#d17b42'))
    item.setToolTip('\n'.join(errors[name] for name in missing))
    item.setData(Qt.ItemDataRole.UserRole, 'additional_body_notice')
    item.setPos(scene.sceneRect().left() + 20, scene.sceneRect().bottom() - 38)
    item.setZValue(200)
    scene.addItem(item)


def groups_with_notice(groups, scene, planets):
    add_unavailable_notice(scene, planets)
    return groups


def refresh_host(host):
    if not isValid(host):
        raise RuntimeError('Deleted chart host')
    host.sync_style()
    host.draw_full_chart()


def refresh_vector(view, finish, sign_display):
    if not isValid(view):
        raise RuntimeError('Deleted chart view')
    view.set_vector_appearance(finish, sign_display)
    view.draw_full_chart()
