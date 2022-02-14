from ..dynmenu import DynItem, Label, Link
from ..feature_layer import IFeatureLayer
from ..pyramid import viewargs
from ..resource import (
    DataScope,
    Resource,
    resource_factory,
)

from .util import _


@viewargs(renderer='nextgisweb:feature_attachment/template/import.mako')
def import_attachments(request):
    request.resource_permission(DataScope.write)

    return dict(obj=request.context)


class FeatureAttachmentExt(DynItem):

    def build(self, args):
        if IFeatureLayer.providedBy(args.obj):
            yield Label('feature_attachment', _("Attachments"))

            user = args.request.user
            if (
                args.obj.has_permission(DataScope.read, user)
                and args.obj.has_export_permission(user)
            ):
                yield Link(
                    'feature_attachment/export', _("Export"),
                    lambda args: args.request.route_url(
                        'feature_attachment.export', id=args.obj.id))

            if args.obj.has_permission(DataScope.write, user):
                yield Link(
                    'feature_attachment/export', _("Import"),
                    lambda args: args.request.route_url(
                        'feature_attachment.import.page', id=args.obj.id))


def setup_pyramid(comp, config):
    config.add_route(
        'feature_attachment.import.page',
        '/resource/{id}/feature_attachment/import',
        factory=resource_factory,
    ).add_view(import_attachments, context=IFeatureLayer)

    Resource.__dynmenu__.add(FeatureAttachmentExt())
