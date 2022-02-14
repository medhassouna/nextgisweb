import json
from pathlib import Path
from zipfile import ZipFile

import zipstream
from pyramid.response import Response
from sqlalchemy.orm.exc import NoResultFound

from ..core.exception import ValidationError
from ..models import DBSession
from ..resource import DataScope, resource_factory

from .model import FeatureDescription
from .util import _


def export_descriptions(resource, request):
    request.resource_permission(DataScope.read)

    zip_stream = zipstream.ZipFile(mode='w', compression=zipstream.ZIP_DEFLATED,
                                   allowZip64=True)

    for obj in FeatureDescription.filter(
        FeatureDescription.resource_id == resource.id,
        FeatureDescription.value != '',
    ):
        meta = dict(value=obj.value)
        meta_bytes = json.dumps(meta, ensure_ascii=False).encode('utf-8')
        zip_stream.writestr(f'{obj.feature_id}.json', meta_bytes)

    return Response(
        app_iter=zip_stream,
        content_type='application/zip',
        content_disposition='attachment; filename="%d.descriptions.zip"' % resource.id,
    )


class DataFormatError(ValidationError):
    message = _("Wrong data format.")


def import_descriptions(resource, request):
    request.resource_permission(DataScope.write)

    upload_meta = request.json_body['source']
    data, meta = request.env.file_upload.get_filename(upload_meta['id'])
    with ZipFile(data, mode='r', allowZip64=True) as z, DBSession.no_autoflush:
        for name in z.namelist():
            try:
                fid = int(Path(name).stem)
            except ValueError:
                raise DataFormatError()

            try:
                obj = FeatureDescription.filter_by(
                    resource=resource,
                    feature_id=fid,
                ).one()
            except NoResultFound:
                obj = FeatureDescription(
                    resource=resource,
                    feature_id=fid,
                )

            meta_bytes = z.read(name)
            try:
                meta = json.loads(meta_bytes.decode('utf-8'))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise DataFormatError()
            if 'value' not in meta:
                raise DataFormatError()
            obj.value = meta['value']


def setup_pyramid(comp, config):
    config.add_route(
        'feature_description.export',
        '/api/resource/{id}/feature_description/export',
        factory=resource_factory
    ).add_view(export_descriptions, request_method='GET')

    config.add_route(
        'feature_description.import',
        '/api/resource/{id}/feature_description/import',
        factory=resource_factory
    ).add_view(import_descriptions, request_method='PUT', renderer='json')
