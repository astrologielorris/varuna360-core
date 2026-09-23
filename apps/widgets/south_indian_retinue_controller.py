"""Requested/effective retinue state and owned graphics materialization."""
from dataclasses import dataclass, replace
from apps.widgets.south_indian_geometry import SCENE_SIZE
from PySide6.QtCore import QRectF

@dataclass(frozen=True)
class RetinueEligibility:
    center_enabled: bool
    drawable: bool
    compass: bool

@dataclass(frozen=True)
class RetinueInput:
    eligibility: RetinueEligibility
    placements: tuple
    omissions: tuple
    labels: tuple
    ascendant: int
    style: object

class RetinueController:
    def __init__(self, layer):
        self.layer = layer
        self.rings = self.ruler = self.drawable = self.updating = False
        self.style_active = True
        self.omissions = ()
        self.generation = 0

    def effective(self, eligibility):
        return bool(self.rings and eligibility.center_enabled and eligibility.drawable
                    and self.style_active and not eligibility.compass)

    def state(self, eligibility):
        reason = None
        if not eligibility.center_enabled:
            reason = 'miniature'
        elif not self.style_active:
            reason = 'Hora + Trimshamsha available in vector style.'
        elif eligibility.compass:
            reason = 'Hora + Trimshamsha available in sign view.'
        elif not eligibility.drawable:
            reason = 'No chart'
        effective = self.effective(eligibility)
        return dict(requested=self.rings, ruler_requested=self.ruler, effective=effective,
                    suppression_reason=reason, outer_sign_count=12 if effective else 0,
                    frame='compass' if eligibility.compass else 'sign', omissions=list(self.omissions))

    def set_rings(self, on):
        on = bool(on)
        if self.rings == on:
            return False
        self.rings = on
        self.generation += 1
        return True

    def set_ruler(self, on):
        self.ruler = bool(on)
        if self.layer.rulers is not None:
            self.layer.rulers.setVisible(self.ruler)

    def set_style_active(self, active):
        active = bool(active)
        if self.style_active == active:
            return False
        self.style_active = active
        self.generation += 1
        return True

    def begin_rebuild(self):
        self.generation += 1
        self.layer.dirty = False
        self.layer.clear()

    def defer(self):
        self.generation += 1
        self.layer.dirty = True

    def materialize(self, inputs, expected_generation=None):
        if expected_generation is not None and expected_generation != self.generation:
            return False
        self.layer.dirty = False
        self.layer.services = replace(self.layer.services, style=inputs.style, ruler=self.ruler)
        self.omissions = inputs.omissions
        if self.effective(inputs.eligibility):
            self.layer.rebuild(inputs.placements, inputs.labels, inputs.ascendant)
            self.layer.services.scene.setSceneRect(-SCENE_SIZE/2,-SCENE_SIZE/2,2*SCENE_SIZE,2*SCENE_SIZE)
        else:
            self.layer.clear()
            self.layer.services.scene.setSceneRect(QRectF(0,0,SCENE_SIZE,SCENE_SIZE))
        return True

    def notice_margin(self, eligibility):
        if not (self.rings and eligibility.center_enabled and eligibility.drawable
                and eligibility.compass and self.style_active):
            return 0
        notice = self.layer.services.notice
        notice.setText(self.state(eligibility)['suppression_reason'])
        notice.adjustSize()
        notice.move(8,8)
        notice.show()
        return notice.height()+16

    def dispose(self):
        self.generation += 1
        try:
            if self.layer.services:
                self.layer.clear()
        except RuntimeError:  # Qt may have already destroyed the scene/items.
            pass
        self.layer.services = None
