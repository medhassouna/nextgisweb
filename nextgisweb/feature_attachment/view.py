from ..dynmenu import DynItem, Link
from ..feature_layer import IFeatureLayer
from ..resource import (
    DataScope,
    Resource,
)

from .util import _


class FeatureAttachmentExt(DynItem):

    def build(self, args):
        if IFeatureLayer.providedBy(args.obj):
            user = args.request.user
            if (
                args.obj.has_permission(DataScope.read, user)
                and args.obj.has_export_permission(user)
            ):
                yield Link(
                    'feature_layer/attachment_export', _("Export attachments"),
                    lambda args: args.request.route_url(
                        'feature_attachment.export', id=args.obj.id))


def setup_pyramid(comp, config):
    Resource.__dynmenu__.add(FeatureAttachmentExt())
