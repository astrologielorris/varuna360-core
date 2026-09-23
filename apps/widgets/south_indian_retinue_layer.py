# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Owned native graphics for SPEC-SIC-006; never changes natal items."""
from apps.widgets.south_indian_layer_services import LayerServices
from PySide6.QtCore import Qt, QRectF, QPointF
from shiboken6 import delete
from PySide6.QtGui import QColor, QBrush, QPen, QFont, QFontMetricsF, QPainterPath, QRadialGradient
from PySide6.QtWidgets import (QGraphicsItem, QGraphicsItemGroup,
    QGraphicsPathItem, QGraphicsSimpleTextItem, QMenu, QLabel)
from core.south_indian_retinue import Box, partitions, pack_chips, placement, house_connections
from core.retinue_constants import ADITYA_SIGN_ORDER, get_hora, get_trimsamsa_being, HORA_COLORS, TRIMSAMSA_COLORS
from visualizations.wheel_constants import ELEMENT_COLORS
from ui.qt_theme import desat_hex, get_scale_factor, get_area_font_size, is_light_theme

from apps.widgets.south_indian_material import (
    WoodBoardItem, WoodFaceItem, WoodRopeTraceItem, rounded, pigment, outer_wood_palette)

TAG = 'sic006'


def outer_palette(light):
    """Local SI palette: preserve element hues without dark panels in light UI."""
    if light:
        return dict(card='#faf9f6', border='#b9bec5', header='#edf0f3',
                    header_border='#bac2cc', text='#242b35', muted='#515b69',
                    guide='#526174', asc='#956600', marker='#ffffff',
                    highlight='#875a00',
                    hora=dict(sun_bg='#f3c7c4', sun_text='#542724',
                              moon_bg='#c9dcf3', moon_text='#243f61'),
                    trim={element:dict(bg=bg,text=fg) for element,bg,fg in (
                        ('Fire','#f3c7c4','#542724'), ('Earth','#e4d3be','#503b29'),
                        ('Air','#f6e5ab','#55430e'), ('Water','#c9dcf3','#243f61'),
                        ('Ether','#e3d1ed','#513463'))})
    return dict(card='#0f1116', border='#34363b', header='#07080b',
                header_border='#45464a', text='#f6f3ed', muted='#aaa9a5',
                guide='#fff8e8', asc='#ffdc82', marker='#0b0c10',
                highlight='#f0c75e', hora=HORA_COLORS, trim=TRIMSAMSA_COLORS)

def label_clear_beam(a, b, label_rects):
    """Keep an axis-aligned degree guide on its axis, with gaps for labels."""
    vertical = a[0] == b[0]
    axis = 1 if vertical else 0
    start, end = sorted((a[axis], b[axis]))
    cuts = []
    for rect in label_rects:
        if vertical and rect.left() <= a[0] <= rect.right():
            cuts.append((rect.top(), rect.bottom()))
        elif not vertical and rect.top() <= a[1] <= rect.bottom():
            cuts.append((rect.left(), rect.right()))
    path = QPainterPath()
    cursor = start
    def segment(lo, hi):
        if hi > lo:
            path.moveTo(a[0] if vertical else lo, lo if vertical else a[1])
            path.lineTo(a[0] if vertical else hi, hi if vertical else a[1])
    for lo, hi in sorted(cuts):
        if hi <= cursor or lo >= end:
            continue
        segment(cursor, min(lo, end))
        cursor = max(cursor, hi)
    segment(cursor, end)
    return path

class Chip(QGraphicsPathItem):
    def __init__(self, layer, members, rect, stack=False):
        super().__init__()
        self.layer, self.members = layer, members
        self.stack = stack
        path = QPainterPath()
        path.addRoundedRect(rect, 9*layer.scale, 9*layer.scale)
        self.setPath(path)
        ink = layer.services.wood['ink'] if layer.services.wood else None
        self.setBrush(pigment(ink['brass'] if members[0].identity == 'Ascendant' else ink['plate'])
                      if ink else QColor('#f0c75e' if members[0].identity == 'Ascendant' else '#f8f4ec'))
        self.setPen(QPen(QColor('#141414'), layer.scale))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable)
        self.setAcceptHoverEvents(True)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setZValue(5)

    def choose(self):
        if not self.stack:
            self.layer.select(self.members[0].identity)
            return
        menu = self.layer.services.menu_factory()
        menu.setAccessibleName('Retinue stack members')
        layer, generation = self.layer, self.layer.generation
        layer.member_menu = menu
        def select_member(checked=False, key=None):
            if layer.generation == generation:
                layer.select(key)
        for p in self.members:
            action = menu.addAction(self.layer.detail(p))
            action.triggered.connect(lambda checked=False, key=p.identity: select_member(checked, key))
        point = self.layer.services.global_position(self.sceneBoundingRect().center())
        try:
            menu.exec(point)
        finally:
            if layer.member_menu is menu:
                layer.member_menu = None
            menu.deleteLater()

    def mousePressEvent(self, event):
        self.setFocus()
        self.choose()
        event.accept()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.choose()
            event.accept()
        elif event.key() == Qt.Key.Key_Escape:
            self.layer.clear_trace()
            event.accept()
        else:
            super().keyPressEvent(event)

    def hoverEnterEvent(self, event):
        self.layer.hover(self.members[0].identity)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.layer.hover(None)
        super().hoverLeaveEvent(event)

    def focusInEvent(self, event):
        self.layer.hover(self.members[0].identity)
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self.layer.hover(None)
        super().focusOutEvent(event)


class SouthIndianRetinueLayer:
    def __init__(self, services):
        self.services = services
        self.dirty = False
        self.palette = outer_palette(is_light_theme())
        self.scale = 2048/600
        self.root = None
        self.card_group = None
        self.rulers = None
        self.trace = None
        self.activation = None
        self.active_connections = ()
        self._hover_token = None
        self.headers = {}
        self.placements = {}
        self.chips = []
        self.sectors = {}
        self.pin = None
        self.member_menu = None
        self.generation = 0
        self._label_rects = []
        self.services.notice.hide()

    def clear(self):
        if self.member_menu is not None:
            self.member_menu.close()
            self.member_menu = None
        self.clear_trace()
        self.services.notice.hide()
        self.generation += 1
        root = self.root
        self.root = self.rulers = self.card_group = None
        self.placements.clear()
        self.chips.clear()
        self.sectors.clear()
        self.headers.clear()
        if root is not None:
            self.services.scene.removeItem(root)
            delete(root)

    def own(self, item, parent=None):
        item.setParentItem(parent if parent is not None else (self.card_group or self.root))
        item.setData(Qt.ItemDataRole.UserRole, TAG)
        return item

    def rect(self, rect, color, radius=4, parent=None, stroke=None, opacity=1, pocket=False):
        if self.services.wood:
            item = self.own(WoodFaceItem(rect, self.services.vector_finish,
                radius*self.scale, color, opacity, pocket, 1.55 if radius == 16 else 1.0), parent)
            if stroke:
                item.setPen(QPen(pigment(stroke, .5), self.scale))
            return item
        path = QPainterPath()
        path.addRoundedRect(rect, radius*self.scale, radius*self.scale)
        item = self.own(QGraphicsPathItem(path), parent)
        item.setBrush(QColor(desat_hex(color)))
        item.setPen(QPen(QColor(stroke), self.scale) if stroke else QPen(Qt.PenStyle.NoPen))
        return item

    def font(self, size, bold=True):
        # A fresh face avoids inheriting a theme font's explicit style name
        # (which can override setWeight and retain a heavy/synthetic face).
        font=QFont('Inter')
        font.setWeight(QFont.Weight.Medium if bold else QFont.Weight.Normal)
        font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
        floor=max(self.services.display_settings.get('planet_degrees', {}).get('font_size',14),
                  get_area_font_size('chart_labels'))*get_scale_factor()
        # Reference dimensions are scene pixels; configured readability is a
        # floor in the same units, not a second multiplication by cell scale.
        font.setPixelSize(round(max(size*self.scale*(.85 if bold else 1), floor)))
        return font

    def two_lines(self, primary, secondary, rect, rotation, size, small, color, parent):
        f1,f2=QFontMetricsF(self.font(size)),QFontMetricsF(self.font(small,False))
        width=rect.height() if rotation else rect.width()
        depth=rect.width() if rotation else rect.height()
        cx,cy=rect.center().x(),rect.center().y()
        if f1.height()+f2.height() > depth-4*self.scale:
            self.text(primary,(cx,cy),size,color,rotation,parent,limit=width-4*self.scale)
            return
        offset1,offset2=-f2.height()/2,f1.height()/2
        p1=(cx+offset1,cy) if rotation else (cx,cy+offset1)
        p2=(cx+offset2,cy) if rotation else (cx,cy+offset2)
        self.text(primary,p1,size,color,rotation,parent,limit=width-4*self.scale)
        self.text(secondary,p2,small,color,rotation,parent,limit=width-4*self.scale,bold=False)

    def text(self, text, point, size, color, rotation=0, parent=None, limit=None, bold=True):
        font=self.font(size,bold)
        fm = QFontMetricsF(font)
        shown = fm.elidedText(text, Qt.TextElideMode.ElideRight, limit) if limit else text
        item = self.own(QGraphicsSimpleTextItem(shown), parent)
        item.setFont(font)
        item.setBrush(pigment(color) if self.services.wood else QColor(color))
        bounds = item.boundingRect()
        item.setTransformOriginPoint(bounds.center())
        item.setRotation(rotation)
        item.setPos(point[0]-bounds.width()/2, point[1]-bounds.height()/2)
        item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        item.setZValue(3)
        pad = 2 * self.scale
        self._label_rects.append(item.sceneBoundingRect().adjusted(-pad, -pad, pad, pad))
        return item

    def line(self, a, b, color=None, width=1.9, parent=None, clear_labels=False):
        if clear_labels:
            path = label_clear_beam(a, b, self._label_rects)
        else:
            path = QPainterPath(QPointF(*a))
            path.lineTo(QPointF(*b))
        item = self.own(QGraphicsPathItem(path), parent)
        item.setPen(QPen(QColor(color or self.palette['guide']), width*self.scale))
        if clear_labels:
            item.setData(Qt.ItemDataRole.UserRole + 1, 'sic006.band-beam')
        item.setZValue(2)
        return item

    def detail(self, p):
        spans = partitions(p.sign)
        start, end, *_ = next(s for s in spans if s[0] <= p.degree < s[1])
        return (f'{p.identity} · {getattr(self, "labels", ADITYA_SIGN_ORDER)[p.sign]} · {p.degree:.8f}°\n'
                f'Hora {1 if p.degree < 15 else 2}: {p.hora["being_name"]}\n'
                f'Trimshamsha {start}–{end}°: {p.trim["being_name"]} '
                f'({p.trim["being_type"]}, {p.trim["element"]})')

    def rebuild(self, placements, labels, ascendant):
        self.clear()
        wood = self.services.wood
        self.palette = palette = (outer_wood_palette(self.services.vector_finish)
                                  if wood else outer_palette(is_light_theme()))
        self.root = QGraphicsItemGroup()
        self.root.setHandlesChildEvents(False)
        self.services.scene.addItem(self.root)
        self.rulers = self.own(QGraphicsItemGroup())
        self.rulers.setHandlesChildEvents(False)
        self.rulers.setZValue(4)
        if wood:
            path = QPainterPath()
            for sign in range(12):
                box = Box(sign)
                path.addPath(rounded(QRectF(*box.card), 16*self.scale))
            WoodBoardItem(path, self.services.vector_finish, self.root)
        self.placements = {p.identity: p for p in placements}
        self.labels = labels
        for sign in range(12):
            self._label_rects = []
            box = Box(sign)
            s = box.scale
            clip_path=QPainterPath()
            clip_path.addRect(QRectF(*box.card))
            self.card_group=QGraphicsPathItem(clip_path,self.root)
            self.card_group.setPen(QPen(Qt.PenStyle.NoPen))
            self.card_group.setFlag(QGraphicsItem.GraphicsItemFlag.ItemClipsChildrenToShape)
            self.rect(QRectF(*box.card), palette['card'], 16, stroke=palette['border'],
                      opacity=0 if wood else 1)
            element = ('Fire','Earth','Air','Water')[sign%4]
            if not wood:
                tint = self.rect(QRectF(*box.card), ELEMENT_COLORS[element], 16)
                tint.setOpacity(.085)
            self.rect(QRectF(*box.rect(0, 1, 0, 3.5)),
                      wood['stain'][element]['c'] if wood else ELEMENT_COLORS[element], 2,
                      opacity=wood['spine'] if wood else 1)
            if not wood:
                self.rect(QRectF(*box.rect(.01, .69, 9, 41)), palette['header'], 16, stroke=palette['header_border'])
            self.headers[sign] = self.text(labels[sign], box.point(.36, 25), 20, palette['text'],
                                          0 if box.horizontal else -90, limit=175*s)
            self.text(f'H {(sign-ascendant)%12+1}', box.point(.91, 25), 13, palette['muted'],
                      0 if box.horizontal else -90)
            for i, (start, end, lord, kind, element) in enumerate(partitions(sign)):
                record = get_trimsamsa_being(ADITYA_SIGN_ORDER[sign], start)
                rect = QRectF(*box.rect(start/30, end/30, 48, 140)).adjusted(.9*s,.9*s,-.9*s,-.9*s)
                item = self.rect(rect, palette['trim'][element]['bg'],
                                 opacity=wood['stain'][element]['o'] if wood else 1, pocket=bool(wood))
                self.sectors[(sign, 'trim', i)] = item
                item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                item.setOpacity(1 if wood else .86)
                item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemClipsChildrenToShape)
                self.two_lines(record['being_name'], record['being_type'], rect,
                               -90 if box.horizontal else 0,14.6,8.8,
                               palette['trim'][element]['text'], item)
            for half in range(2):
                h = get_hora(ADITYA_SIGN_ORDER[sign], half*15)
                prefix = 'sun' if h['lord'] == 'Sun' else 'moon'
                rect = QRectF(*box.rect(half/2, (half+1)/2, 240, 288)).adjusted(.9*s,.9*s,-.9*s,-.9*s)
                item = self.rect(rect, palette['hora'][prefix+'_bg'],
                                 opacity=wood['hora'][h['lord']]['o'] if wood else 1, pocket=bool(wood))
                self.sectors[(sign, 'hora', half)] = item
                item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                item.setOpacity(1 if wood else .86)
                item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemClipsChildrenToShape)
                lum='☉' if prefix=='sun' else '☾'
                self.two_lines(lum+' '+h['being_name'],f'{half*15}° – {(half+1)*15}°',
                               rect,0 if box.horizontal else -90,16,10,
                               palette['hora'][prefix+'_text'],item)
            ruler_clip=QGraphicsPathItem(clip_path,self.rulers)
            ruler_clip.setPen(QPen(Qt.PenStyle.NoPen))
            ruler_clip.setFlag(QGraphicsItem.GraphicsItemFlag.ItemClipsChildrenToShape)
            for degree in [p[0] for p in partitions(sign)] + [30]:
                self.line(box.point(degree/30, 140), box.point(degree/30, 146), parent=ruler_clip, width=.7)
                self.text(f'{degree}°', box.point(degree/30,154), 9, palette['muted'] if wood or is_light_theme() else '#c8c4bc', parent=ruler_clip)
            members = sorted((p for p in placements if p.sign == sign), key=lambda p:(p.degree,p.identity))
            degree_metrics = QFontMetricsF(self.font(11, False))
            name_metrics = QFontMetricsF(self.font(17.5))
            sizes = [(max(52, degree_metrics.horizontalAdvance(p.label)/s+8,
                          name_metrics.horizontalAdvance('ASC' if p.identity=='Ascendant' else p.identity[:2])/s+8),
                      max(34, (degree_metrics.height()+name_metrics.height())/s+4)) for p in members]
            slots = pack_chips([p.degree for p in members], sizes, box.horizontal)
            for p in members:
                for a,b in ((48,140),(140,240),(240,288)):
                    beam = self.line(box.point(p.degree/30,a), box.point(p.degree/30,b),
                                    palette['asc'] if p.identity == 'Ascendant' else palette['guide'],
                                    clear_labels=a != 140)
                    if a != 140:
                        pen=beam.pen();pen.setDashPattern([2.5,3.5]);beam.setPen(pen)
                        beam.setOpacity(.72)
                for depth in (48,288):
                    x,y = box.point(p.degree/30, depth)
                    self.rect(QRectF(x-4*s,y-4*s,8*s,8*s), palette['marker'], 4,stroke=palette['asc'] if p.identity=='Ascendant' else palette['guide'])
            groups = [members] if slots is None and members else [[p] for p in members]
            for i, group in enumerate(groups):
                slot = (.5,200) if slots is None else slots[i]
                center = box.point(*slot)
                w,h = ((78,max(34,QFontMetricsF(self.font(13.5)).height()/s+6)) if slots is None else sizes[i])
                rect = QRectF(-w*s/2,-h*s/2,w*s,h*s)
                chip = self.own(Chip(self, group, rect,stack=slots is None))
                chip.setPos(*center)
                self.chips.append(chip)
                if slots is not None:
                    self.line(center, box.point(group[0].degree/30,slot[1]), width=1.0)
                if slots is None:
                    count = len(group)
                    label = (self.services.translate('1 point') if count == 1 else
                             self.services.translate('%1 points').replace('%1', str(count)))
                    self.text(label,(0,0),13.5,'#141414',parent=chip,limit=(w-6)*s)
                else:
                    label='ASC' if group[0].identity=='Ascendant' else group[0].identity[:2]
                    self.two_lines(label,group[0].label,rect,0,17.5,11,'#141414',chip)
        self.card_group = None
        self.rulers.setVisible(self.services.ruler)

    def select(self, key):
        self.pin = None if self.pin == key else key
        self.hover(None)

    def sector_at(self, scene_point):
        """Resolve cell geometry to the canonical Wheel dialog payload.

        Geometry includes child labels and guides. Identity stays independent
        of translated/Western display labels and the active house frame.
        """
        for (sign, ring, index), sector in self.sectors.items():
            if sector.contains(sector.mapFromScene(scene_point)):
                if ring == 'trim':
                    return ADITYA_SIGN_ORDER[sign], 'trimsamsa', partitions(sign)[index][3]
                hora = get_hora(ADITYA_SIGN_ORDER[sign], index * 15)
                return ADITYA_SIGN_ORDER[sign], 'hora', 'aditya' if hora['lord'] == 'Sun' else 'naga'
        return None

    def chip_for_item(self, item):
        """Find chip ancestry without changing a scene item's ownership.

        PySide6 6.10.1 makes a top-level item Python-owned when parentItem()
        returns None. Querying it during hit testing can consequently delete
        natal cards as temporary wrappers leave scope. Native isAncestorOf()
        checks the relationship without exposing/reparenting those wrappers.
        """
        for chip in self.chips:
            if item is chip or chip.isAncestorOf(item):
                return chip
        return None

    def clear_trace(self):
        self.pin = None
        self.hover(None)

    def hover_sector(self, point):
        for (sign, ring, index), item in self.sectors.items():
            if item.contains(item.mapFromScene(point)):
                degree = index * 15 if ring == 'hora' else partitions(sign)[index][0]
                self.hover(None, placement('sector', sign, degree), ring)
                return
        self.hover(None)

    def _light_connections(self, p, ring):
        # Separate scene owner keeps soft light below natal labels and planets.
        # All light is vector-painted at the current device resolution.
        from apps.widgets.south_indian_geometry import cell_rect
        self.active_connections = house_connections(p, ring)
        self.activation = QGraphicsItemGroup()
        self.activation.setHandlesChildEvents(False)
        self.activation.setZValue(2)
        self.services.scene.addItem(self.activation)
        for connection in self.active_connections:
            sign = connection.sign
            box = Box(sign)
            color = self.services.style.ink('highlight', self.palette['highlight'])
            for rect in (QRectF(*box.card), cell_rect(sign)):
                rect = rect.adjusted(5, 5, -5, -5)
                path = rounded(rect, 22)
                light = self.own(QGraphicsPathItem(path), self.activation)
                gradient = QRadialGradient(rect.center(), max(rect.width(), rect.height()) * .7)
                center = QColor(color); center.setAlpha(12)
                edge = QColor(color); edge.setAlpha(65)
                gradient.setColorAt(0, center)
                gradient.setColorAt(1, edge)
                light.setBrush(QBrush(gradient))
                outline = QColor(color); outline.setAlpha(155)
                light.setPen(QPen(outline, 5))
                light.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            if sign == p.sign:
                continue  # The source header below includes every active house.
            # The original natal H label remains untouched. This second line
            # explicitly names the source of the relative connection number.
            self.headers[sign].hide()
            rect = QRectF(*box.rect(.01, .70, 5, 44))
            label = f"{'Hora' if connection.ring == 'hora' else 'Trim'} H {connection.house} · from {self.labels[p.sign]}"
            label_count = len(self._label_rects)
            self.two_lines(self.labels[sign], label, rect,
                           0 if box.horizontal else -90, 17, 9.5,
                           self.palette['text'], self.activation)
            del self._label_rects[label_count:]

    def _show_connections(self, p):
        # Summarize ALL connections in the current outer square, including H1.
        # Destination headers remain separate; no viewport widget or popup.
        parts = []
        for ring, title in (('hora', 'Hora'), ('trim', 'Trim')):
            houses = [str(c.house) for c in self.active_connections if c.ring == ring]
            if houses:
                parts.append(f'{title} H ' + ', '.join(houses))
        box = Box(p.sign)
        self.headers[p.sign].hide()
        group = self.own(QGraphicsItemGroup(), self.activation)
        group.setData(Qt.ItemDataRole.UserRole + 1, 'sic006.source-connections')
        group.setHandlesChildEvents(False)
        group.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        label_count = len(self._label_rects)
        self.two_lines(self.labels[p.sign], ' · '.join(parts),
                       QRectF(*box.rect(.01, .70, 5, 44)),
                       0 if box.horizontal else -90, 17, 11,
                       self.palette['text'], group)
        del self._label_rects[label_count:]

    def hover(self, key, sector_placement=None, ring=None):
        key = self.pin or key
        p = self.placements.get(key)
        if p is not None:
            ring = None
        else:
            p = sector_placement
        token = (p, ring)
        if self._hover_token == token:
            return
        self._hover_token = token
        if self.activation is not None:
            self.services.scene.removeItem(self.activation)
            delete(self.activation)
            self.activation = None
        self.active_connections = ()
        for header in self.headers.values():
            header.show()
        if self.trace is not None:
            self.services.scene.removeItem(self.trace)
            delete(self.trace)
            self.trace = None
        for item in self.sectors.values():
            item.setPen(QPen(Qt.PenStyle.NoPen))
        for chip in self.chips:
            selected=any(p.identity==key for p in chip.members)
            chip.setPen(QPen(QColor(self.palette['highlight'] if selected else '#141414'),(3 if selected else 1)*self.scale))
        if p is None:
            return
        self._light_connections(p, ring)
        self._show_connections(p)
        trim_index = next(i for i,s in enumerate(partitions(p.sign)) if s[0] <= p.degree < s[1])
        for which,index in (('hora',int(p.degree>=15)),('trim',trim_index)):
            if ring is not None and which != ring:
                continue
            self.sectors[(p.sign,which,index)].setPen(QPen(
                pigment(self.services.wood['carve']['dark']) if self.services.wood else QColor(self.palette['guide']),
                (4 if self.services.wood else 3)*self.scale))
        self.trace = QGraphicsItemGroup()
        self.services.scene.addItem(self.trace)
        self.trace.setZValue(70 if self.services.wood else 90)
        if p.anchor:
            x,y = p.anchor
            # Follow the sign's nearest outside edge, keeping the hollow center clear.
            box = Box(p.sign)
            endpoint = box.point(p.degree/30,288)
            if box.row == 0:
                elbow = (x,-5)
            elif box.row == 3:
                elbow = (x,2053)
            elif box.column == 0:
                elbow = (-5,y)
            else:
                elbow = (2053,y)
            path = QPainterPath(QPointF(x,y))
            path.lineTo(QPointF(*elbow))
            path.lineTo(QPointF(*endpoint))
            if self.services.wood:
                self.own(WoodRopeTraceItem(path, self.services.vector_finish), self.trace)
            else:
                item = self.own(QGraphicsPathItem(path), self.trace)
                item.setPen(QPen(QColor(self.palette['highlight']),3))
                self.rect(QRectF(x-70,y-70,140,140),'#f0c75e',12,parent=self.trace).setOpacity(.15)
