import re
from contextlib import contextmanager

import geoalchemy2 as ga
import sqlalchemy.sql as sql
from shapely.geometry import box
from sqlalchemy import select, text, func
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from zope.interface import implementer

from ..lib.logging import logger
from .. import db
from ..core.exception import ValidationError, ForbiddenError
from ..models import declarative_base
from ..resource import (
    Resource,
    ConnectionScope,
    DataStructureScope,
    DataScope,
    Serializer,
    SerializedProperty as SP,
    SerializedRelationship as SR,
    SerializedResourceRelationship as SRR,
    ResourceGroup)
from ..spatial_ref_sys import SRS
from ..env import env
from ..layer import IBboxLayer, SpatialLayerMixin
from ..lib.geometry import Geometry
from ..feature_layer import (
    Feature,
    FeatureQueryIntersectsMixin,
    FeatureSet,
    LayerField,
    LayerFieldsMixin,
    GEOM_TYPE,
    FIELD_TYPE,
    IFeatureLayer,
    IWritableFeatureLayer,
    IFeatureQuery,
    IFeatureQueryFilter,
    IFeatureQueryFilterBy,
    IFeatureQueryLike,
    IFeatureQueryIntersects,
    IFeatureQueryOrderBy)

from .exception import ExternalDatabaseError
from .util import _, table_exists

Base = declarative_base(dependencies=('resource', 'feature_layer'))


GEOM_TYPE_DISPLAY = (
    _("Point"), _("Line"), _("Polygon"),
    _("Multipoint"), _("Multiline"), _("Multipolygon"),
    _("Point Z"), _("Line Z"), _("Polygon Z"),
    _("Multipoint Z"), _("Multiline Z"), _("Multipolygon Z"),
)

PC_READ = ConnectionScope.read
PC_WRITE = ConnectionScope.write
PC_CONNECT = ConnectionScope.connect


class PostgisConnection(Base, Resource):
    identity = 'postgis_connection'
    cls_display_name = _("PostGIS connection")

    __scope__ = ConnectionScope

    hostname = db.Column(db.Unicode, nullable=False)
    database = db.Column(db.Unicode, nullable=False)
    username = db.Column(db.Unicode, nullable=False)
    password = db.Column(db.Unicode, nullable=False)
    port = db.Column(db.Integer, nullable=True)

    @classmethod
    def check_parent(cls, parent): # NOQA
        return isinstance(parent, ResourceGroup)

    def get_engine(self):
        resid = self.id
        engine = env.postgis.get_engine(self.hostname, self.port, self.database,
                                        self.username, self.password, key=resid)

        @db.event.listens_for(engine, 'connect')
        def _connect(dbapi, record):
            logger.debug(
                "Resource #%d, pool 0x%x, connection 0x%x created",
                resid, id(dbapi), id(engine))

        @db.event.listens_for(engine, 'checkout')
        def _checkout(dbapi, record, proxy):
            logger.debug(
                "Resource #%d, pool 0x%x, connection 0x%x retrieved",
                resid, id(dbapi), id(engine))

        @db.event.listens_for(engine, 'checkin')
        def _checkin(dbapi, record):
            logger.debug(
                "Resource #%d, pool 0x%x, connection 0x%x returned",
                resid, id(dbapi), id(engine))

        return engine

    @contextmanager
    def get_connection(self):
        engine = self.get_engine()
        try:
            conn = engine.connect()
        except OperationalError:
            raise ValidationError(_("Cannot connect to the database!"))

        try:
            yield conn
        except SQLAlchemyError as exc:
            raise ExternalDatabaseError(sa_error=exc)
        finally:
            conn.close()


class PostgisConnectionSerializer(Serializer):
    identity = PostgisConnection.identity
    resclass = PostgisConnection

    hostname = SP(read=PC_READ, write=PC_WRITE)
    database = SP(read=PC_READ, write=PC_WRITE)
    username = SP(read=PC_READ, write=PC_WRITE)
    password = SP(read=PC_READ, write=PC_WRITE)
    port = SP(read=PC_READ, write=PC_WRITE)


class PostgisLayerField(Base, LayerField):
    identity = 'postgis_layer'

    __tablename__ = LayerField.__tablename__ + '_' + identity
    __mapper_args__ = dict(polymorphic_identity=identity)

    id = db.Column(db.ForeignKey(LayerField.id), primary_key=True)
    column_name = db.Column(db.Unicode, nullable=False)


@implementer(IFeatureLayer, IWritableFeatureLayer, IBboxLayer)
class PostgisLayer(Base, Resource, SpatialLayerMixin, LayerFieldsMixin):
    identity = 'postgis_layer'
    cls_display_name = _("PostGIS layer")

    __scope__ = DataScope

    connection_id = db.Column(db.ForeignKey(Resource.id), nullable=False)
    schema = db.Column(db.Unicode, default='public', nullable=False)
    table = db.Column(db.Unicode, nullable=False)
    column_id = db.Column(db.Unicode, nullable=False)
    column_geom = db.Column(db.Unicode, nullable=False)
    geometry_type = db.Column(db.Enum(*GEOM_TYPE.enum), nullable=False)
    geometry_srid = db.Column(db.Integer, nullable=False)

    __field_class__ = PostgisLayerField

    connection = db.relationship(
        Resource,
        foreign_keys=connection_id,
        cascade=False, cascade_backrefs=False)

    @classmethod
    def check_parent(cls, parent): # NOQA
        return isinstance(parent, ResourceGroup)

    @property
    def source(self):
        source_meta = super().source
        source_meta.update(dict(
            schema=self.schema,
            table=self.table,
            column_id=self.column_id,
            column_geom=self.column_geom,
            geometry_type=self.geometry_type)
        )
        return source_meta

    def setup(self):
        fdata = dict()
        for f in self.fields:
            fdata[f.keyname] = dict(
                display_name=f.display_name,
                grid_visibility=f.grid_visibility)

        for f in list(self.fields):
            self.fields.remove(f)

        self.feature_label_field = None

        with self.connection.get_connection() as conn:
            if table_exists(conn, self.table, self.schema):
                tableref = '%s.%s' % (self.schema, self.table)
                raise ValidationError(_("Table '%(table)s' not found!") % dict(table=tableref)) # NOQA

            result = conn.execute(text(
                """SELECT type, coord_dimension, srid FROM geometry_columns
                WHERE f_table_schema = :s
                    AND f_table_name = :t
                    AND f_geometry_column = :column"""),
                dict(s=self.schema, t=self.table, column=self.column_geom))

            row = result.mappings().first()

            if row:
                geometry_srid = row['srid']

                if geometry_srid == 0 and self.geometry_srid is None:
                    raise ValidationError(_("SRID missing in geometry_columns table! You should specify it manually."))  # NOQA

                if (self.geometry_srid == 0):
                    raise ValidationError(_("0 is an invalid SRID."))

                if (
                    self.geometry_srid is not None
                    and geometry_srid != 0
                    and self.geometry_srid != geometry_srid
                ):
                    raise ValidationError(_("SRID in geometry_columns table does not match specified!"))  # NOQA

                if self.geometry_srid is None:
                    self.geometry_srid = geometry_srid

                tab_geom_type = row['type']

                if tab_geom_type == 'GEOMETRY' and self.geometry_type is None:
                    raise ValidationError(_("Geometry type missing in geometry_columns table! You should specify it manually.")) # NOQA

                if row['coord_dimension'] == 3:
                    tab_geom_type += 'Z'

                if (
                    self.geometry_type is not None
                    and tab_geom_type != 'GEOMETRY'
                    and self.geometry_type != tab_geom_type
                ):
                    raise ValidationError(_("Geometry type in geometry_columns table does not match specified!")) # NOQA

                if self.geometry_type is None:
                    self.geometry_type = tab_geom_type

            result = conn.execute(text(
                """SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = :s AND table_name = :t
                ORDER BY ordinal_position"""),
                dict(s=self.schema, t=self.table))

            colfound_id = False
            colfound_geom = False

            for row in result.mappings():
                if row['column_name'] == self.column_id:
                    if row['data_type'] not in ['integer', 'bigint']:
                        raise ValidationError(_("To use column as ID it should have integer type!"))  # NOQA
                    colfound_id = True

                elif row['column_name'] == self.column_geom:
                    colfound_geom = True

                elif row['column_name'] in ('id', 'geom'):
                    # TODO: Currently id and geom fields break vector layer. We should fix it!
                    pass

                else:
                    datatype = None
                    if row['data_type'] == 'integer':
                        datatype = FIELD_TYPE.INTEGER
                    elif row['data_type'] == 'bigint':
                        datatype = FIELD_TYPE.BIGINT
                    elif row['data_type'] == 'double precision':
                        datatype = FIELD_TYPE.REAL
                    elif row['data_type'] == 'numeric':
                        datatype = FIELD_TYPE.REAL
                    elif row['data_type'] == 'character varying':
                        datatype = FIELD_TYPE.STRING
                    elif row['data_type'] == 'text':
                        datatype = FIELD_TYPE.STRING
                    elif row['data_type'] == 'uuid':
                        datatype = FIELD_TYPE.STRING
                    elif row['data_type'] == 'date':
                        datatype = FIELD_TYPE.DATE
                    elif re.match('^time(?!stamp)', row['data_type']):
                        datatype = FIELD_TYPE.TIME
                    elif re.match('^timestamp', row['data_type']):
                        datatype = FIELD_TYPE.DATETIME

                    if datatype is not None:
                        fopts = dict(display_name=row['column_name'])
                        fopts.update(fdata.get(row['column_name'], dict()))
                        self.fields.append(PostgisLayerField(
                            keyname=row['column_name'],
                            datatype=datatype,
                            column_name=row['column_name'],
                            **fopts))

            if not colfound_id:
                raise ValidationError(_("Column '%(column)s' not found!") % dict(column=self.column_id)) # NOQA

            if not colfound_geom:
                raise ValidationError(_("Column '%(column)s' not found!") % dict(column=self.column_geom)) # NOQA

    def get_info(self):
        return super().get_info() + (
            (_("Geometry type"), dict(zip(GEOM_TYPE.enum, GEOM_TYPE_DISPLAY))[
                self.geometry_type]),
        )

    # IFeatureLayer

    @property
    def feature_query(self):

        class BoundFeatureQuery(FeatureQueryBase):
            layer = self
            # TODO: support from spatial_ref_sys table
            srs_supported = (self.srs_id, )

        return BoundFeatureQuery

    def field_by_keyname(self, keyname):
        for f in self.fields:
            if f.keyname == keyname:
                return f

        raise KeyError("Field '%s' not found!" % keyname)

    # IWritableFeatureLayer

    def _sa_table(self, init_columns=False):
        cols = []
        if init_columns:
            cols.extend([db.sql.column(f.column_name)
                         for f in self.fields])
            cols.append(db.sql.column(self.column_id))
            cols.append(db.sql.column(self.column_geom))

        tab = db.sql.table(self.table, *cols)
        tab.schema = self.schema
        tab.quote = True
        tab.quote_schema = True

        return tab

    def _makevals(self, feature):
        values = dict()

        for f in self.fields:
            if f.keyname in feature.fields.keys():
                values[f.column_name] = feature.fields[f.keyname]

        if feature.geom is not None:
            values[self.column_geom] = func.st_transform(
                ga.elements.WKBElement(bytearray(feature.geom.wkb), srid=self.srs_id),
                self.geometry_srid)

        return values

    def feature_put(self, feature):
        """Update existing object

        :param feature: object description
        :type feature:  Feature
        """
        idcol = db.sql.column(self.column_id)
        tab = self._sa_table(True)
        stmt = db.update(tab).values(
            self._makevals(feature)).where(idcol == feature.id)

        with self.connection.get_connection() as conn:
            conn.execute(stmt)

    def feature_create(self, feature):
        """Insert new object to DB which is described in feature

        :param feature: object description
        :type feature:  Feature

        :return:    inserted object ID
        """
        idcol = db.sql.column(self.column_id)
        tab = self._sa_table(True)
        stmt = db.insert(tab).values(
            self._makevals(feature)).returning(idcol)

        with self.connection.get_connection() as conn:
            return conn.execute(stmt).scalar()

    def feature_delete(self, feature_id):
        """Remove record with id

        :param feature_id: record id
        :type feature_id:  int or bigint
        """
        idcol = db.sql.column(self.column_id)
        tab = self._sa_table()
        stmt = db.delete(tab).where(
            idcol == feature_id)

        with self.connection.get_connection() as conn:
            conn.execute(stmt)

    def feature_delete_all(self):
        """Remove all records from a layer"""
        tab = self._sa_table()
        stmt = db.delete(tab)

        with self.connection.get_connection() as conn:
            conn.execute(stmt)

    # IBboxLayer
    @property
    def extent(self):
        st_force2d = func.st_force2d
        st_transform = func.st_transform
        st_extent = func.st_extent
        st_setsrid = func.st_setsrid
        st_xmax = func.st_xmax
        st_xmin = func.st_xmin
        st_ymax = func.st_ymax
        st_ymin = func.st_ymin

        tab = self._sa_table(True)

        geomcol = getattr(tab.columns, self.column_geom)

        bbox = st_extent(st_transform(st_setsrid(db.cast(
            st_force2d(geomcol), ga.Geometry), self.geometry_srid), 4326)
        ).label('bbox')
        sq = select(bbox).alias('t')

        fields = (
            st_xmax(sq.c.bbox),
            st_xmin(sq.c.bbox),
            st_ymax(sq.c.bbox),
            st_ymin(sq.c.bbox),
        )

        with self.connection.get_connection() as conn:
            maxLon, minLon, maxLat, minLat = conn.execute(select(*fields)).first()

        extent = dict(
            minLon=minLon,
            maxLon=maxLon,
            minLat=minLat,
            maxLat=maxLat
        )

        return extent


DataScope.read.require(
    ConnectionScope.connect,
    attr='connection', cls=PostgisLayer)


class _fields_action(SP):
    """ Special write-only attribute that allows updating
    list of fields from the server """

    def setter(self, srlzr, value):
        if value == 'update':
            if srlzr.obj.connection.has_permission(PC_CONNECT, srlzr.user):
                srlzr.obj.setup()
            else:
                raise ForbiddenError()
        elif value != 'keep':
            raise ValidationError("Invalid 'fields' parameter.")


class PostgisLayerSerializer(Serializer):
    identity = PostgisLayer.identity
    resclass = PostgisLayer

    __defaults = dict(read=DataStructureScope.read,
                      write=DataStructureScope.write)

    connection = SRR(**__defaults)

    schema = SP(**__defaults)
    table = SP(**__defaults)
    column_id = SP(**__defaults)
    column_geom = SP(**__defaults)

    geometry_type = SP(**__defaults)
    geometry_srid = SP(**__defaults)

    srs = SR(**__defaults)

    fields = _fields_action(write=DataStructureScope.write)


@implementer(
    IFeatureQuery,
    IFeatureQueryFilter,
    IFeatureQueryFilterBy,
    IFeatureQueryLike,
    IFeatureQueryIntersects,
    IFeatureQueryOrderBy,
)
class FeatureQueryBase(FeatureQueryIntersectsMixin):

    def __init__(self):
        super(FeatureQueryBase, self).__init__()

        self._srs = None
        self._geom = None
        self._geom_format = 'WKB'
        self._box = None

        self._fields = None
        self._limit = None
        self._offset = None

        self._filter = None
        self._filter_by = None
        self._like = None

        self._order_by = None

    def srs(self, srs):
        self._srs = srs

    def geom(self):
        self._geom = True

    def geom_format(self, geom_format):
        self._geom_format = geom_format

    def box(self):
        self._box = True

    def fields(self, *args):
        self._fields = args

    def limit(self, limit, offset=0):
        self._limit = limit
        self._offset = offset

    def filter(self, *args):
        self._filter = args

    def filter_by(self, **kwargs):
        self._filter_by = kwargs

    def order_by(self, *args):
        self._order_by = args

    def like(self, value):
        self._like = value

    def __call__(self):
        tab = self.layer._sa_table(True)

        idcol = tab.columns[self.layer.column_id]
        columns = [idcol.label('id')]
        where = []

        geomcol = tab.columns[self.layer.column_geom]

        srs = self.layer.srs if self._srs is None else self._srs

        if srs.id != self.layer.geometry_srid:
            geomexpr = func.st_transform(geomcol, srs.id)
        else:
            geomexpr = geomcol

        if self._geom:
            if self._geom_format == 'WKB':
                geomexpr = func.st_asbinary(geomexpr, 'NDR')
            else:
                geomexpr = func.st_astext(geomexpr)

            columns.append(geomexpr.label('geom'))

        fieldmap = []
        for idx, fld in enumerate(self.layer.fields, start=1):
            if self._fields is None or fld.keyname in self._fields:
                clabel = 'f%d' % idx
                columns.append(getattr(tab.columns, fld.column_name).label(clabel))
                fieldmap.append((fld.keyname, clabel))

        if self._filter_by:
            for k, v in self._filter_by.items():
                if k == 'id':
                    where.append(idcol == v)
                else:
                    field = self.layer.field_by_keyname(k)
                    where.append(tab.columns[field.column_name] == v)

        if self._filter:
            token = []
            for k, o, v in self._filter:
                supported_operators = (
                    'eq',
                    'ne',
                    'isnull',
                    'ge',
                    'gt',
                    'le',
                    'lt',
                    'like',
                    'ilike',
                )
                if o not in supported_operators:
                    raise ValueError(
                        "Invalid operator '%s'. Only %r are supported." % (
                            o, supported_operators))

                if o == 'like':
                    o = 'like_op'
                elif o == 'ilike':
                    o = 'ilike_op'
                elif o == "isnull":
                    if v == 'yes':
                        o = 'is_'
                    elif v == 'no':
                        o = 'isnot'
                    else:
                        raise ValueError(
                            "Invalid value '%s' for operator '%s'."
                            % (v, o)
                        )
                    v = db.sql.null()

                op = getattr(db.sql.operators, o)
                if k == 'id':
                    column = idcol
                else:
                    field = self.layer.field_by_keyname(k)
                    column = tab.columns[field.column_name]

                token.append(op(column, v))

            where.append(db.and_(True, *token))

        if self._like:
            token = []
            for fld in self.layer.fields:
                token.append(db.sql.cast(
                    tab.columns[fld.column_name],
                    db.Unicode).ilike(
                    '%' + self._like + '%'))

            where.append(db.or_(*token))

        if self._intersects:
            reproject = self._intersects.srid is not None \
                and self._intersects.srid != self.layer.geometry_srid
            int_srs = SRS.filter_by(id=self._intersects.srid).one() \
                if reproject else self.layer.srs

            int_geom = func.st_geomfromtext(self._intersects.wkt)
            if int_srs.is_geographic:
                # Prevent tolerance condition error
                bound_geom = func.st_makeenvelope(-180, -89.9, 180, 89.9)
                int_geom = func.st_intersection(bound_geom, int_geom)
            int_geom = func.st_setsrid(int_geom, int_srs.id)
            if reproject:
                int_geom = func.st_transform(int_geom, self.layer.geometry_srid)

            where.append(func.st_intersects(geomcol, int_geom))

        if self._box:
            columns.extend((
                func.st_xmin(geomexpr).label('box_left'),
                func.st_ymin(geomexpr).label('box_bottom'),
                func.st_xmax(geomexpr).label('box_right'),
                func.st_ymax(geomexpr).label('box_top'),
            ))

        gt = self.layer.geometry_type
        if gt in GEOM_TYPE.has_z:
            gt = re.sub(r'Z$', '', gt)
            ndims = 3
        else:
            ndims = 2
        where.append(func.geometrytype(geomcol) == gt)
        where.append(func.st_ndims(geomcol) == ndims)

        order_criterion = []
        if self._order_by:
            for order, k in self._order_by:
                field = self.layer.field_by_keyname(k)
                order_criterion.append(dict(asc=db.asc, desc=db.desc)[order](
                    tab.columns[field.column_name]))
        order_criterion.append(idcol)

        class QueryFeatureSet(FeatureSet):
            layer = self.layer

            _geom = self._geom
            _geom_format = self._geom_format
            _box = self._box
            _fields = self._fields
            _limit = self._limit
            _offset = self._offset

            def __iter__(self):
                query = sql.select(*columns) \
                    .where(db.and_(True, *where)) \
                    .limit(self._limit) \
                    .offset(self._offset) \
                    .order_by(*order_criterion)

                with self.layer.connection.get_connection() as conn:
                    result = conn.execute(query)
                    for row in result.mappings():
                        fdict = dict((k, row[l]) for k, l in fieldmap)

                        if self._geom:
                            if self._geom_format == 'WKB':
                                geom_data = row['geom'].tobytes()
                                geom = Geometry.from_wkb(geom_data, validate=False)
                            else:
                                geom = Geometry.from_wkt(row['geom'], validate=False)
                        else:
                            geom = None

                        yield Feature(
                            layer=self.layer, id=row['id'],
                            fields=fdict, geom=geom,
                            box=box(
                                row['box_left'], row['box_bottom'],
                                row['box_right'], row['box_top']
                            ) if self._box else None
                        )

            @property
            def total_count(self):
                with self.layer.connection.get_connection() as conn:
                    query = sql.select(func.count(idcol)) \
                        .where(db.and_(True, *where))
                    result = conn.execute(query)
                    return result.scalar()

        return QueryFeatureSet()
