import json
from collections import OrderedDict
from io import BytesIO
from pathlib import Path
from shutil import copyfileobj
from zipfile import ZipFile

import zipstream
from PIL import Image
from pyramid.response import Response, FileResponse

from ..core.exception import ValidationError
from ..resource import DataScope, resource_factory
from ..env import env
from ..models import DBSession
from ..feature_layer.exception import FeatureNotFound

from .exception import AttachmentNotFound
from .exif import EXIF_ORIENTATION_TAG, ORIENTATIONS
from .model import FeatureAttachment
from .util import _, COMP_ID


def attachment_or_not_found(resource_id, feature_id, attachment_id):
    """ Return attachment filtered by id or raise AttachmentNotFound exception. """

    obj = FeatureAttachment.filter_by(
        id=attachment_id, resource_id=resource_id,
        feature_id=feature_id
    ).one_or_none()

    if obj is None:
        raise AttachmentNotFound(resource_id, feature_id, attachment_id)

    return obj


def download(resource, request):
    request.resource_permission(DataScope.read)

    obj = attachment_or_not_found(
        resource_id=resource.id, feature_id=int(request.matchdict['fid']),
        attachment_id=int(request.matchdict['aid'])
    )

    fn = env.file_storage.filename(obj.fileobj)
    return FileResponse(fn, content_type=obj.mime_type, request=request)


def image(resource, request):
    request.resource_permission(DataScope.read)

    obj = attachment_or_not_found(
        resource_id=resource.id, feature_id=int(request.matchdict['fid']),
        attachment_id=int(request.matchdict['aid'])
    )

    image = Image.open(env.file_storage.filename(obj.fileobj))
    ext = image.format

    exif = None
    try:
        exif = image._getexif()
    except Exception:
        pass

    if exif is not None:
        otag = exif.get(EXIF_ORIENTATION_TAG)
        if otag in (3, 6, 8):
            orientation = ORIENTATIONS.get(otag)
            image = image.transpose(orientation.degrees)

    if 'size' in request.GET:
        image.thumbnail(
            list(map(int, request.GET['size'].split('x'))),
            Image.ANTIALIAS)

    buf = BytesIO()
    image.save(buf, ext)
    buf.seek(0)

    return Response(body_file=buf, content_type=obj.mime_type)


def iget(resource, request):
    request.resource_permission(DataScope.read)

    obj = attachment_or_not_found(
        resource_id=resource.id, feature_id=int(request.matchdict['fid']),
        attachment_id=int(request.matchdict['aid'])
    )

    return Response(
        json.dumps(obj.serialize()),
        content_type='application/json',
        charset='utf-8')


def idelete(resource, request):
    request.resource_permission(DataScope.read)

    obj = attachment_or_not_found(
        resource_id=resource.id, feature_id=int(request.matchdict['fid']),
        attachment_id=int(request.matchdict['aid'])
    )

    DBSession.delete(obj)

    return Response(
        json.dumps(None),
        content_type='application/json',
        charset='utf-8')


def iput(resource, request):
    request.resource_permission(DataScope.write)

    obj = attachment_or_not_found(
        resource_id=resource.id, feature_id=int(request.matchdict['fid']),
        attachment_id=int(request.matchdict['aid'])
    )

    obj.deserialize(request.json_body)

    DBSession.flush()

    return Response(
        json.dumps(dict(id=obj.id)),
        content_type='application/json',
        charset='utf-8')


def cget(resource, request):
    request.resource_permission(DataScope.read)

    query = FeatureAttachment.filter_by(
        feature_id=request.matchdict['fid'],
        resource_id=resource.id)

    result = [itm.serialize() for itm in query]

    return Response(
        json.dumps(result),
        content_type='application/json',
        charset='utf-8')


def cpost(resource, request):
    request.resource_permission(DataScope.write)

    feature_id = int(request.matchdict['fid'])
    query = resource.feature_query()
    query.filter_by(id=feature_id)
    query.limit(1)

    feature = None
    for f in query():
        feature = f

    if feature is None:
        raise FeatureNotFound(resource.id, feature_id)

    obj = FeatureAttachment(resource_id=feature.layer.id, feature_id=feature.id)
    obj.deserialize(request.json_body)

    DBSession.add(obj)
    DBSession.flush()

    return Response(
        json.dumps(dict(id=obj.id)),
        content_type='application/json',
        charset='utf-8')


def export_attachments(resource, request):
    request.resource_permission(DataScope.read)

    zip_stream = zipstream.ZipFile(mode='w', compression=zipstream.ZIP_DEFLATED,
                                   allowZip64=True)

    fid = None
    for obj in FeatureAttachment \
        .filter_by(resource_id=resource.id) \
        .order_by(
            FeatureAttachment.feature_id,
            FeatureAttachment.id):

        if fid != obj.feature_id:
            idx = 0
            fid = obj.feature_id

        name = f'{fid}/{idx}'

        meta = OrderedDict((
            ('name', obj.name),
            ('size', obj.size),
            ('mime_type', obj.mime_type),
            ('description', obj.description),
        ))
        meta_bytes = json.dumps(meta, ensure_ascii=False).encode('utf-8')
        zip_stream.writestr(name + '.json', meta_bytes)

        fn = env.file_storage.filename(obj.fileobj)
        zip_stream.write(fn, arcname=name + '.data')

        idx += 1

    return Response(
        app_iter=zip_stream,
        content_type='application/zip',
        content_disposition='attachment; filename="%d.attachments.zip"' % resource.id,
    )


class DataFormatError(ValidationError):
    message = _("Wrong data format.")


def import_attachments(resource, request):
    request.resource_permission(DataScope.write)

    upload_meta = request.json_body['source']
    data, meta = request.env.file_upload.get_filename(upload_meta['id'])
    with ZipFile(data, mode='r', allowZip64=True) as z, DBSession.no_autoflush:
        for meta_path in sorted([
            Path(name) for name in z.namelist()
            if name.endswith('.json')
        ]):
            try:
                fid = int(meta_path.parent.name)
            except ValueError:
                raise DataFormatError()

            obj = FeatureAttachment(
                resource=resource,
                feature_id=fid,
            )

            meta_bytes = z.read(str(meta_path))
            try:
                meta = json.loads(meta_bytes.decode('utf-8'))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise DataFormatError()
            for k in ('name', 'size', 'mime_type', 'description'):
                if k not in meta:
                    raise DataFormatError()
                setattr(obj, k, meta[k])

            data_path = meta_path.with_suffix('.data')
            obj.fileobj = env.file_storage.fileobj(component=COMP_ID)
            dstfile = env.file_storage.filename(obj.fileobj, makedirs=True)
            try:
                with z.open(str(data_path), 'r') as sf, open(dstfile, 'wb') as df:
                    copyfileobj(sf, df)
            except KeyError:
                raise DataFormatError()


def setup_pyramid(comp, config):
    colurl = '/api/resource/{id}/feature/{fid}/attachment/'
    itmurl = '/api/resource/{id}/feature/{fid}/attachment/{aid}'

    config.add_route(
        'feature_attachment.download',
        itmurl + '/download',
        factory=resource_factory) \
        .add_view(download)

    config.add_route(
        'feature_attachment.image',
        itmurl + '/image',
        factory=resource_factory) \
        .add_view(image)

    config.add_route(
        'feature_attachment.item', itmurl,
        factory=resource_factory) \
        .add_view(iget, request_method='GET') \
        .add_view(iput, request_method='PUT') \
        .add_view(idelete, request_method='DELETE')

    config.add_route(
        'feature_attachment.collection', colurl,
        factory=resource_factory) \
        .add_view(cget, request_method='GET') \
        .add_view(cpost, request_method='POST')

    config.add_route(
        'feature_attachment.export',
        '/api/resource/{id}/feature_attachment/export',
        factory=resource_factory
    ).add_view(export_attachments, request_method='GET')

    config.add_route(
        'feature_attachment.import',
        '/api/resource/{id}/feature_attachment/import',
        factory=resource_factory
    ).add_view(import_attachments, request_method='PUT', renderer='json')
