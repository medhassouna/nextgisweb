from ..component import Component, require

from .model import Base, FeatureDescription

__all__ = ['FeatureDescriptionComponent', 'FeatureDescription']


class FeatureDescriptionComponent(Component):
    identity = 'feature_description'
    metadata = Base.metadata

    @require('feature_layer')
    def initialize(self):
        from . import extension # NOQA

    def setup_pyramid(self, config):
        from . import api, view
        api.setup_pyramid(self, config)
        view.setup_pyramid(self, config)
