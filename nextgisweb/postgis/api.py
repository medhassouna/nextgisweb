from collections import OrderedDict

import geoalchemy2 as ga
from sqlalchemy.exc import NoResultFound, NoSuchTableError, SQLAlchemyError

from .. import db
from ..core.exception import ValidationError
from ..feature_layer import FIELD_TYPE, GEOM_TYPE
from ..resource import resource_factory, ConnectionScope

from .exception import ExternalDatabaseError
from .model import PostgisConnection, PostgisLayer
from .util import _, table_exists, info_tables, info_grants, postgis_srs, translate


# Field type - generic DB type
_FIELD_TYPE_2_DB = {
    FIELD_TYPE.INTEGER: db.Integer,
    FIELD_TYPE.BIGINT: db.BigInteger,
    FIELD_TYPE.REAL: db.Numeric,
    FIELD_TYPE.STRING: db.String,
    FIELD_TYPE.DATE: db.Date,
    FIELD_TYPE.TIME: db.Time,
    FIELD_TYPE.DATETIME: db.TIMESTAMP,
}


def inspect_connection(request):
    request.resource_permission(ConnectionScope.connect)

    connection = request.context
    engine = connection.get_engine()
    try:
        inspector = db.inspect(engine)
    except SQLAlchemyError as exc:
        raise ExternalDatabaseError(message="Failed to inspect database.", sa_error=exc)

    result = []
    for schema_name in inspector.get_schema_names():
        if schema_name != 'information_schema':
            result.append(dict(
                schema=schema_name,
                views=inspector.get_view_names(schema=schema_name),
                tables=inspector.get_table_names(schema=schema_name)))

    return result


def inspect_table(request):
    request.resource_permission(ConnectionScope.connect)

    connection = request.context
    engine = connection.get_engine()
    try:
        inspector = db.inspect(engine)
    except SQLAlchemyError as exc:
        raise ExternalDatabaseError(message="Failed to inspect database.", sa_error=exc)

    table_name = request.matchdict['table_name']
    schema = request.GET.get('schema', 'public')

    result = []
    try:
        for column in inspector.get_columns(table_name, schema):
            result.append(dict(
                name=column.get('name'),
                type='%r' % column.get('type')))
    except NoSuchTableError:
        raise ValidationError(_("Table (%s) not found in schema (%s)." % (table_name, schema)))

    return result


def postgis_check(request):

    def check(data, warnings):
        cdata = data.get('connection')
        ldata = data.get('layer')

        engine = None
        connection = None

        layer_table = None
        layer = None

        if cdata is not None:
            if 'id' in cdata:
                try:
                    connection = PostgisConnection.filter_by(id=cdata['id']).one()
                except NoResultFound:
                    return _("Connection (id=%d) not found.") % cdata['id']
                request.resource_permission(ConnectionScope.connect, connection)
                engine = connection.get_engine()
            else:
                request.require_authenticated()
                engine = request.env.postgis.get_engine(
                    cdata['hostname'], cdata['port'], cdata['database'],
                    cdata['username'], cdata['password'])

        if ldata is not None:
            if 'id' in ldata:
                try:
                    layer = PostgisLayer.filter_by(id=ldata['id']).one()
                except NoResultFound:
                    return _("Layer (id=%d) not found.") % ldata['id']

                if cdata is not None and cdata.get('id') != layer.connection_id:
                    return _("Can't check layer with unfamiliar connection.")

                elif cdata is None:
                    connection = layer.connection
                    request.resource_permission(ConnectionScope.connect, connection)
                    engine = connection.get_engine()

                layer_table = (layer.schema, layer.table)
            elif cdata is None:
                return _("Connection credentials not specified.")
            else:
                layer_table = (ldata['schema'], ldata['table'])

        if engine is None:
            raise ValidationError()

        # DB connection

        try:
            conn = engine.connect()
        except SQLAlchemyError:
            return _("Could not establish connextion.")

        try:

            try:
                conn.execute(db.select(info_tables)).first()
            except SQLAlchemyError:
                return _("Could not get a table list.")

            # PostGIS

            postgis_version = conn.execute(db.text(
                'SELECT extversion FROM pg_extension WHERE extname = \'postgis\';')).scalar()
            if postgis_version is None:
                return _("PostGIS extension not installed.")

            if layer_table is not None:

                # Table exist

                table_schema, table_name = layer_table
                if not table_exists(conn, table_name, table_schema):
                    return _("Table '%s.%s' not found!") % (table_schema, table_name)

                # Privileges

                username = connection.username if connection is not None else cdata['username']

                def privilege_not_granted_msg(privilege):
                    return _("Privilege '%s' not granted.") % privilege

                stmt = db.select(info_grants.c.privilege_type).where(db.and_(
                    info_grants.c.table_schema == table_schema,
                    info_grants.c.table_name == table_name,
                    info_grants.c.grantee == username,
                ))
                privileges = [r[0] for r in conn.execute(stmt)]
                for privilege, required in (
                    ('SELECT', True),
                    ('INSERT', False),
                    ('UPDATE', False),
                    ('DELETE', False),
                ):
                    if privilege not in privileges:
                        msg = privilege_not_granted_msg(privilege)
                        if required:
                            return msg
                        else:
                            warnings.append(msg)

                # Columns

                columns = dict()
                int_colnames = []
                geom_colnames = []

                inspector = db.inspect(engine)
                for column in inspector.get_columns(table_name, table_schema):
                    if isinstance(column['type'], ga.Geometry):
                        geom_colnames.append(column['name'])
                    elif isinstance(column['type'], (db.Integer, db.BigInteger)):
                        int_colnames.append(column['name'])
                    columns[column['name']] = column

                def check_idcol_writable(column, add_warn=False):
                    ok = True
                    if column['nullable']:
                        ok = False
                        if add_warn:
                            warnings.append(_("ID column '%s' can be NULL.") % column['name'])
                    if not column['autoincrement']:
                        ok = False
                        if add_warn:
                            warnings.append(_("ID column '%s' has no autoincrement.") % column['name'])
                    return ok

                if layer is not None:
                    if layer.column_id not in columns:
                        return _("ID column '%s' not found.") % layer.column_id
                    idcol = columns[layer.column_id]
                    if layer.column_id not in int_colnames:
                        return _("ID column '%s' have unsuitable type ('%r').") % (
                            layer.column_id, idcol['type'])
                    check_idcol_writable(idcol, add_warn=True)

                    if layer.column_geom not in columns:
                        return _("Geometry column '%s' not found.") % layer.column_geom
                    geomcol = columns[layer.column_geom]
                    if layer.column_geom not in geom_colnames:
                        return _("Geometry column '%s' have unsuitable type ('%r').") % (
                            layer.column_geom, geomcol['type'])
                    if geomcol['type'].geometry_type not in ('GEOMETRY', layer.geometry_type):
                        return _("Geometry column '%s' have unsuitable type ('%s').") % (
                            layer.column_geom, geomcol['type'].geometry_type)
                    if layer.geometry_srid != geomcol['type'].srid:
                        return _("Geometry column '%s' have unsuitable SRID (%d).") % (
                            layer.column_geom, geomcol['type'].srid)

                    for field in layer.fields:
                        column = columns.get(field.column_name)
                        if column is None:
                            return _("Column '%s' not found.") % field.column_name
                        if not isinstance(column['type'], _FIELD_TYPE_2_DB[field.datatype]):
                            return _("Column '%s' have unsuitable type ('%r').") % (
                                field.column_name, column['type'])

                else:
                    if len(int_colnames) == 0:
                        return _("Table must have an integer type column.")
                    for name in int_colnames:
                        check_idcol_writable(columns[name])

                    if len(geom_colnames) == 0:
                        return _("Table must have a geometry type column.")

                    geom_colnames_gtype_filtered = []
                    for name in geom_colnames:
                        geom_type = columns[name]['type'].geometry_type
                        if geom_type == 'GEOMETRY' or geom_type in GEOM_TYPE.enum:
                            geom_colnames_gtype_filtered.append(name)
                    if len(geom_colnames_gtype_filtered) == 0:
                        return _("Table does not contain columns with supported geometry types.")

                    geom_colnames_srid_filtered = []
                    for name in geom_colnames_gtype_filtered:
                        srid = columns[name]['type'].srid
                        if srid is not None:
                            stmt = db.select(postgis_srs).where(
                                postgis_srs.c.srid == srid
                            ).exists().select()
                            exists = conn.execute(stmt).scalar()
                            if exists:
                                geom_colnames_srid_filtered.append(name)
                    if len(geom_colnames_srid_filtered) == 0:
                        return _("Table does not contain geometry columns with valid SRID.")

        except SQLAlchemyError as exc:
            raise ExternalDatabaseError(sa_error=exc)
        finally:
            conn.close()

        return None

    warnings = []
    error = check(request.json_body, warnings)

    result = OrderedDict()

    if error is not None:
        result['status'] = 'error'
        result['error'] = translate(error)
    if len(warnings) > 0:
        if error is None:
            result['status'] = 'warning'
        result['warnings'] = [translate(w) for w in warnings]
    if 'status' not in result:
        result['status'] = 'success'

    return result


def setup_pyramid(comp, config):
    config.add_route(
        'postgis.connection.inspect', '/api/resource/{id}/inspect/',
        factory=resource_factory
    ).add_view(inspect_connection, context=PostgisConnection,
               request_method='GET', renderer='json')

    config.add_route(
        'postgis.connection.inspect.table', '/api/resource/{id}/inspect/{table_name}/',
        factory=resource_factory
    ).add_view(inspect_table, context=PostgisConnection,
               request_method='GET', renderer='json')

    config.add_route(
        'postgis.check', '/api/component/postgis/check',
    ).add_view(postgis_check, request_method='POST', renderer='json')
