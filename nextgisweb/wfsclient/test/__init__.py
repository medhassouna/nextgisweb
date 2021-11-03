from contextlib import contextmanager

import transaction

from nextgisweb.auth import User
from nextgisweb.models import DBSession
from nextgisweb.vector_layer.test import create_feature_layer as create_vector_layer
from nextgisweb.wfsclient import WFSConnection, WFSLayer
from nextgisweb.wfsserver import Layer as WFS_Service_Layer, Service as WFSService


@contextmanager
def create_feature_layer(data, parent_id, ngw_httptest_app):
    with create_vector_layer(data, parent_id) as vlayer:
        with transaction.manager:
            res_common = dict(
                parent_id=parent_id,
                owner_user=User.by_keyname('administrator'))
            service = WFSService(
                **res_common, display_name='WFS service',
            ).persist()
            service_layer = WFS_Service_Layer(
                resource_id=vlayer.id, display_name='Layer',
                keyname='layer'
            )
            service.layers.append(service_layer)

        with transaction.manager:
            wfs_path = '{}/api/resource/{}/wfs'.format(ngw_httptest_app.base_url, service.id)
            connection = WFSConnection(
                **res_common, display_name='WFS connection',
                path=wfs_path, version='2.0.2',
                username='administrator', password='admin',
            ).persist()

            layer = WFSLayer(
                **res_common, display_name='Feature layer (WFS)',
                connection=connection, srs_id=3857,
                layer_name=service_layer.keyname, column_geom='geom',
                geometry_srid=vlayer.srs_id, geometry_type='POINT',
            ).persist()

            DBSession.flush()

            layer.setup()

        try:
            yield layer
        finally:
            with transaction.manager:
                DBSession.delete(WFSLayer.filter_by(id=layer.id).one())
                DBSession.delete(WFSConnection.filter_by(id=connection.id).one())
                DBSession.delete(WFSService.filter_by(id=service.id).one())
