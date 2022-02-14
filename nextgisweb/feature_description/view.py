from ..dynmenu import DynItem, Label, Link
from ..feature_layer import IFeatureLayer
from ..pyramid import viewargs
from ..resource import (
    DataScope,
    Resource,
    resource_factory,
)

from .util import _


@viewargs(renderer='nextgisweb:feature_description/template/import.mako')
def import_descriptions(request):
    request.resource_permission(DataScope.write)

    return dict(obj=request.context)


class FeatureDescriptionExt(DynItem):

    def build(self, args):
        if IFeatureLayer.providedBy(args.obj):
            yield Label('feature_description', _("Descriptions"))

            user = args.request.user
            if (
                args.obj.has_permission(DataScope.read, user)
                and args.obj.has_export_permission(user)
            ):
                yield Link(
                    'feature_description/export', _("Export"),
                    lambda args: args.request.route_url(
                        'feature_description.export', id=args.obj.id))

            if args.obj.has_permission(DataScope.write, user):
                yield Link(
                    'feature_description/export', _("Import"),
                    lambda args: args.request.route_url(
                        'feature_description.import.page', id=args.obj.id))


def setup_pyramid(comp, config):
    config.add_route(
        'feature_description.import.page',
        '/resource/{id}/feature_description/import',
        factory=resource_factory,
    ).add_view(import_descriptions, context=IFeatureLayer)

    Resource.__dynmenu__.add(FeatureDescriptionExt())
