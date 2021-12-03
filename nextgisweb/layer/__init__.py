from ..component import Component, require

from .models import SpatialLayerMixin
from .interface import IBboxLayer

__all__ = [
    'LayerComponent',
    'SpatialLayerMixin',
    'IBboxLayer',
]


class LayerComponent(Component):
    identity = 'layer'

    @require('resource', 'spatial_ref_sys')
    def setup_pyramid(self, config):
        from . import api
        api.setup_pyramid(self, config)
