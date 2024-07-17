import re
from functools import partial
from itertools import chain
from pathlib import Path

from msgspec import UNSET
from osgeo import gdal, ogr
from sqlalchemy import event, inspect, select, text
from sqlalchemy.orm import validates
from zope.interface import implementer
from zope.sqlalchemy import mark_changed

from nextgisweb.env import COMP_ID, Base, DBSession, env, gettext
from nextgisweb.lib import db, saext

from nextgisweb.core.exception import ValidationError as VE
from nextgisweb.feature_layer import (
    FIELD_TYPE,
    GEOM_TYPE,
    IFeatureLayer,
    IFieldEditableFeatureLayer,
    IGeometryEditableFeatureLayer,
    IWritableFeatureLayer,
    LayerField,
    LayerFieldsMixin,
)
from nextgisweb.feature_layer.exception import FeatureNotFound, RestoreNotDeleted
from nextgisweb.feature_layer.versioning import (
    FeatureCreate,
    FeatureDelete,
    FeatureRestore,
    FeatureUpdate,
    FVersioningMixin,
    FVersioningNotImplemented,
    OperationFieldValue,
    fversioning_guard,
)
from nextgisweb.file_upload import FileUpload
from nextgisweb.layer import IBboxLayer, SpatialLayerMixin
from nextgisweb.resource import DataScope, DataStructureScope, Resource, ResourceGroup, Serializer
from nextgisweb.resource import SerializedProperty as SP
from nextgisweb.resource import SerializedRelationship as SR
from nextgisweb.spatial_ref_sys import SRS

from .feature_query import FeatureQueryBase, calculate_extent
from .kind_of_data import VectorLayerData
from .ogrloader import FID_SOURCE, FIX_ERRORS, TOGGLE, LoaderParams, OGRLoader
from .util import DRIVERS, FIELD_TYPE_2_DB, FIELD_TYPE_SIZE, SCHEMA, read_dataset_vector, uuid_hex
from .vlschema import VLSchema

Base.depends_on("resource", "feature_layer")

GEOM_TYPE_DISPLAY = (
    gettext("Point"),
    gettext("Line"),
    gettext("Polygon"),
    gettext("Multipoint"),
    gettext("Multiline"),
    gettext("Multipolygon"),
    gettext("Point Z"),
    gettext("Line Z"),
    gettext("Polygon Z"),
    gettext("Multipoint Z"),
    gettext("Multiline Z"),
    gettext("Multipolygon Z"),
)


class VectorLayerField(Base, LayerField):
    identity = "vector_layer"

    __tablename__ = LayerField.__tablename__ + "_" + identity
    __mapper_args__ = dict(polymorphic_identity=identity)

    id = db.Column(db.ForeignKey(LayerField.id), primary_key=True)
    fld_uuid = db.Column(db.Unicode(32), nullable=False)

    def __init__(self, *args, **kwagrs):
        if "fld_uuid" not in kwagrs:
            kwagrs["fld_uuid"] = uuid_hex()
        super().__init__(*args, **kwagrs)


def vlschema_autoflush(func):
    def wrapped(*args, **kwargs):
        _vlschema_autoflush(args[0])
        return func(*args, **kwargs)

    return wrapped


def _vlschema_autoflush(res):
    insp = inspect(res)
    session = insp.session
    if session._flushing:
        return

    assert session, f"{res} not in a session"
    assert res not in session.deleted, f"{res} is deleted"
    if insp.pending or session.is_modified(res):
        assert session.autoflush
        session.flush()


@implementer(
    IFeatureLayer,
    IFieldEditableFeatureLayer,
    IGeometryEditableFeatureLayer,
    IWritableFeatureLayer,
    IBboxLayer,
)
class VectorLayer(Base, Resource, SpatialLayerMixin, LayerFieldsMixin, FVersioningMixin):
    identity = "vector_layer"
    cls_display_name = gettext("Vector layer")

    __scope__ = DataScope

    tbl_uuid = db.Column(db.Unicode(32), nullable=False)
    geometry_type = db.Column(db.Enum(*GEOM_TYPE.enum), nullable=False)

    __field_class__ = VectorLayerField

    def __init__(self, *args, **kwagrs):
        if "tbl_uuid" not in kwagrs:
            kwagrs["tbl_uuid"] = uuid_hex()
        super().__init__(*args, **kwagrs)

    @classmethod
    def check_parent(cls, parent):
        return isinstance(parent, ResourceGroup)

    def get_info(self):
        return super().get_info() + (
            (
                gettext("Geometry type"),
                dict(zip(GEOM_TYPE.enum, GEOM_TYPE_DISPLAY))[self.geometry_type],
            ),
            (gettext("Feature count"), self.feature_query()().total_count),
        )

    @property
    def _tablename(self):
        return "layer_%s" % self.tbl_uuid

    def from_source(self, source, *, layer=UNSET, **kw):
        lparams = LoaderParams()
        for k in list(kw.keys()):
            if hasattr(lparams, k):
                setattr(lparams, k, kw.pop(k))

        if isinstance(source, Path):
            source = str(source)

        if isinstance(source, str):
            source = read_dataset_vector(source, **kw)
        else:
            assert len(kw) == 0, f"Unconsumed arguments: {kw}"

        if isinstance(source, gdal.Dataset):
            # Keep reference against GC
            dataset_ref = source
            source = (
                source.GetLayerByName(layer)
                if isinstance(layer, str)
                else source.GetLayer(0 if layer is UNSET else layer)
            )
        else:
            dataset_ref = None
            assert layer is UNSET

        loader = OGRLoader(source, params=lparams).scan()
        self.geometry_type = loader.geometry_type
        self.fields[:] = [
            VectorLayerField(
                keyname=lf.name,
                datatype=lf.datatype,
                display_name=lf.name,
            )
            for lf in loader.fields.values()
        ]

        session = inspect(self).session
        session.flush()

        vls = self.vlschema()
        columns = {lf.idx: vls.ctab.fields[lf.name].name for lf in loader.fields.values()}

        size = loader.write(
            srs=self.srs,
            schema=vls.ctab.schema,
            table=vls.ctab.name,
            sequence=vls.cseq.name,
            columns=columns,
            connection=session,
        )

        if self.fversioning:
            session.execute(vls.dml_initfill())

        env.core.reserve_storage(
            COMP_ID,
            VectorLayerData,
            value_data_volume=size,
            resource=self,
        )

        # Keep reference against GC
        if dataset_ref:
            pass

        return self

    def from_ogr(self, *args, **kw):
        return self.from_source(*args, validate=False, **kw)

    def setup_from_fields(self, fields):
        assert len(self.fields) == 0
        keynames = set()
        display_names = set()
        for fdata in fields:
            keyname = fdata.get("keyname")
            display_name = fdata.get("display_name", keyname)
            field = VectorLayerField(
                keyname=keyname,
                datatype=fdata.get("datatype"),
                display_name=display_name,
                grid_visibility=fdata.get("grid_visibility", True),
            )

            if keyname in keynames:
                raise VE(message="Field keyname (%s) is not unique." % keyname)
            if display_name in display_names:
                raise VE(message="Field display_name (%s) is not unique." % display_name)
            keynames.add(keyname)
            display_names.add(display_name)

            if fdata.get("label_field"):
                self.feature_label_field = field

            self.fields.append(field)

    def vlschema(
        self,
        *,
        tbl_uuid=None,
        fversioning_enabled=None,
        geometry_type=None,
        fields=None,
    ) -> VLSchema:
        if tbl_uuid is None:
            tbl_uuid = self.tbl_uuid
        if fversioning_enabled is None:
            fversioning_enabled = bool(self.fversioning)
        if geometry_type is None:
            geometry_type = self.geometry_type
        if fields is None:
            fields = {
                fld.keyname: (
                    fld.fld_uuid,
                    FIELD_TYPE_2_DB[fld.datatype],
                )
                for fld in self.fields
            }

        return VLSchema(
            tbl_uuid=tbl_uuid,
            versioning=fversioning_enabled,
            geom_column_type=self._geom_column_type(geometry_type),
            fields=fields,
        )

    # IFeatureLayer

    @property
    @vlschema_autoflush
    def feature_query(self):
        srs_supported_ = [row[0] for row in DBSession.query(SRS.id).all()]

        class BoundFeatureQuery(FeatureQueryBase):
            layer = self
            srs_supported = srs_supported_

        return BoundFeatureQuery

    def field_by_keyname(self, keyname):
        for f in self.fields:
            if f.keyname == keyname:
                return f

        raise KeyError("Field '%s' not found!" % keyname)

    # IFieldEditableFeatureLayer

    def field_create(self, datatype):
        return VectorLayerField(datatype=datatype)

    def field_delete(self, field):
        DBSession.delete(field)

    # IGeometryEditableFeatureLayer

    @vlschema_autoflush
    def geometry_type_change(self, geometry_type):
        if self.fversioning:
            raise FVersioningNotImplemented

        if self.geometry_type == geometry_type:
            return

        regexp = re.compile(r"(?:MULTI)?(POINT|LINESTRING|POLYGON)(?:Z)?")
        base_type = lambda v: regexp.sub(r"\g<1>", v)
        if base_type(geometry_type) != base_type(self.geometry_type):
            raise VE(
                message="Can't convert {0} geometry type to {1}.".format(
                    self.geometry_type, geometry_type
                )
            )

        self.geometry_type = geometry_type

    # IWritableFeatureLayer

    @vlschema_autoflush
    @fversioning_guard
    def feature_create(self, feature):
        vls = self.vlschema()
        session = inspect(self).session

        data = dict()
        query, bmap = vls.dml_insert(fields=feature.fields.keys())

        geom = feature.geom
        data["geom"] = geom.wkb if geom not in (None, UNSET) else None

        for f in self.fields:
            if (v := feature.fields.get(f.keyname, UNSET)) is not UNSET:
                data[bmap[f.keyname]] = v

        if vobj := self.fversioning_vobj:
            data["vid"] = vobj.version_id

        fid = session.scalar(query, data)
        assert fid is not None

        if vobj:
            vobj.mark_changed()
        mark_changed(session)
        return fid

    @vlschema_autoflush
    @fversioning_guard
    def feature_put(self, feature):
        vls = self.vlschema()
        session = inspect(self).session

        data = dict()
        with_geom = False
        if (geom := feature.geom) is not UNSET:
            data["geom"] = geom.wkb if geom else None
            with_geom = True

        query, bmap = vls.dml_update(
            id=feature.id,
            with_geom=with_geom,
            fields=feature.fields.keys(),
        )

        for f in self.fields:
            if (v := feature.fields.get(f.keyname, UNSET)) is not UNSET:
                data[bmap[f.keyname]] = v

        if vobj := self.fversioning_vobj:
            data["vid"] = vobj.version_id

        result = session.execute(query, data)
        if result.rowcount:
            if vobj:
                vobj.mark_changed()
            mark_changed(session)
            return True

        return False

    @vlschema_autoflush
    @fversioning_guard
    def feature_delete(self, feature_id):
        vls = self.vlschema()
        session = inspect(self).session
        query = vls.dml_delete(filter_by=dict(fid=feature_id))

        if vobj := self.fversioning_vobj:
            result = session.execute(query, dict(vid=vobj.version_id))
            row_count = result.rowcount
            if row_count > 0:
                vobj.mark_features_deleted(feature_id)
        else:
            row_count = session.execute(query).rowcount

        if row_count == 0:
            raise FeatureNotFound(self.id, feature_id)
        mark_changed(session)

    @vlschema_autoflush
    @fversioning_guard
    def feature_restore(self, feature):
        vls = self.vlschema()
        session = inspect(self).session

        data = dict(p_fid=feature.id)
        with_geom = False
        if (geom := feature.geom) is not UNSET:
            data["geom"] = geom.wkb if geom else None
            with_geom = True

        query, bmap = vls.dml_restore(
            with_geom=with_geom,
            fields=feature.fields.keys(),
        )

        for f in self.fields:
            if (v := feature.fields.get(f.keyname, UNSET)) is not UNSET:
                data[bmap[f.keyname]] = v

        if vobj := self.fversioning_vobj:
            data["p_vid"] = vobj.version_id

        result = session.execute(query, data)
        if result.rowcount:
            if vobj:
                vobj.mark_changed()
            mark_changed(session)
            return True
        else:
            raise RestoreNotDeleted(self.id, feature.id)

    @vlschema_autoflush
    @fversioning_guard
    def feature_delete_all(self):
        vls = self.vlschema()
        session = inspect(self).session
        query = vls.dml_delete(filter_by={})

        if vobj := self.fversioning_vobj:
            result = session.execute(query, dict(vid=vobj.version_id))
            if result.rowcount > 0:
                vobj.mark_features_deleted(all=True)
        else:
            result = session.execute(query)

        if result.rowcount > 0:
            mark_changed(session)

    # IBboxLayer implementation:

    @property
    @vlschema_autoflush
    def extent(self):
        ctab = self.vlschema(fields={}).ctab
        return calculate_extent(ctab.columns.geom)

    # Versioning

    def fversioning_changed_fids(self):
        yield from self.vlschema().query_changed_fids()

    def fversioning_changes(self, *, initial, target, fid_min, fid_max):
        initial = initial or 0

        fields = {fld.id: (fld.fld_uuid, FIELD_TYPE_2_DB[fld.datatype]) for fld in self.fields}

        query, fmap = self.vlschema(fields=fields).query_changes()
        result = DBSession.execute(
            query,
            dict(
                p_initial=initial,
                p_target=target,
                p_fid_min=fid_min,
                p_fid_max=fid_max,
            ),
        )

        geom_col_offset = 4
        for row in result:
            fid, vid, op, bits, geom = row[: geom_col_offset + 1]
            if op == "D":
                yield FeatureDelete(fid=fid, vid=vid)
            elif op == "C":
                yield FeatureCreate(
                    fid=fid,
                    vid=vid,
                    geom=geom if geom is not None else UNSET,
                    fields=[
                        OperationFieldValue(id, row[geom_col_offset + idx])
                        for id, idx in fmap.items()
                        if row[geom_col_offset + idx] is not None
                    ],
                )
            elif op == "U":
                yield FeatureUpdate(
                    fid=fid,
                    vid=vid,
                    geom=geom if geom is not None else UNSET,
                    fields=[
                        OperationFieldValue(id, row[geom_col_offset + idx])
                        for id, idx in fmap.items()
                        if bits[idx] == "1"
                    ],
                )
            elif op == "R":
                yield FeatureRestore(
                    fid=fid,
                    vid=vid,
                    geom=geom if geom is not None else UNSET,
                    fields=[
                        OperationFieldValue(id, row[geom_col_offset + idx])
                        for id, idx in fmap.items()
                        if bits[idx] == "1"
                    ],
                )
            else:
                raise NotImplementedError

    # Internals

    def _vlschema_wipe(self):
        self.fields[:] = []
        self.tbl_uuid = uuid_hex()

    @validates("tbl_uuid")
    def _tbl_uuid_validate(self, key, value):
        assert self.tbl_uuid is None or self.fields == []
        return value

    def _geom_column_type(self, geometry_type=None):
        geometry_type = geometry_type if geometry_type else self.geometry_type
        return saext.Geometry(geometry_type, self.srs.id)


# Create vector_layer schema on table creation
event.listen(
    VectorLayer.__table__,
    "after_create",
    db.DDL(f"CREATE SCHEMA {SCHEMA}"),
    propagate=True,
)

# Drop vector_layer schema on table creation
event.listen(
    VectorLayer.__table__,
    "after_drop",
    db.DDL(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"),
    propagate=True,
)


class VectorLayerSession:
    @classmethod
    def listen(cls, session):
        event.listen(session, "before_flush", cls.before_flush)

    @classmethod
    def before_flush(cls, session, flush_context, instances):
        exec = partial(_execute_multiple, session=session)

        deleted = set()
        for obj in session.deleted:
            if isinstance(obj, VectorLayer):
                # TODO: Consider changing of tbl_uuid
                exec(obj.vlschema(fields={}).sql_drop())
                deleted.add(obj)

        for obj in session:
            if isinstance(obj, VectorLayer) and obj not in deleted:
                insp = inspect(obj)
                if insp.pending:
                    exec(obj.vlschema().sql_create())
                else:
                    cls.handle_changed(obj, insp, exec, session)

    @classmethod
    def handle_changed(cls, obj, insp, exec, session):
        attrs = {"tbl_uuid", "fversioning", "geometry_type", "fields"}
        if insp.unloaded.issuperset(attrs):
            return

        achanges, fadd, fdel = dict(), None, None
        iattrs = insp.attrs
        for attr in attrs:
            a, u, d = getattr(iattrs, attr).history
            if not a and not d:
                continue
            if attr == "fields":
                fadd, fdel = a, d
            elif attr == "fversioning":
                achanges[attr] = (bool(d) and (bool(d[0])), bool(a) and bool(a[0]))
            else:
                assert a and d
                achanges[attr] = (d[0], a[0])
        if not achanges and not fadd and not fdel:
            return

        if len(achanges) > 1:
            raise NotImplementedError(f"Too many operations: {achanges}")

        wiped = False
        if tu := achanges.pop("tbl_uuid", None):
            if obj.fversioning:
                raise FVersioningNotImplemented
            vls = obj.vlschema(tbl_uuid=tu[0])
            exec(vls.sql_drop())
            exec(obj.vlschema().sql_create())
            wiped = True

        elif vm := achanges.pop("fversioning", None):
            fversioning_enabled = vm[1]
            vls = obj.vlschema()
            if fversioning_enabled:
                exec(vls.sql_versioning_enable())
            else:
                exec(vls.sql_versioning_disable())

        elif gt := achanges.pop("geometry_type", None):
            if obj.fversioning:
                raise FVersioningNotImplemented
            exec(
                obj.vlschema(
                    geometry_type=gt[0],
                    fields={},
                ).sql_convert_geom_column_type(
                    obj._geom_column_type(gt[1]),
                )
            )

        assert len(achanges) == 0, f"Unconsumed: {achanges}"

        if (fadd or fdel) and not wiped:
            # Collect deleted and added fields to construct VLSchema instance.
            # The 'delete' key goes first as it's better to delete then add new
            # columns.
            fields, operations = dict(), dict(delete=[], add=[])
            for fidx, (fld, oper) in enumerate(
                chain(
                    [(i, "add") for i in (fadd if fadd else [])],
                    [(i, "delete") for i in (fdel if fdel else [])],
                )
            ):
                fields[fidx] = (fld.fld_uuid, FIELD_TYPE_2_DB[fld.datatype])
                operations[oper].append(fidx)

            if fields:
                vls = obj.vlschema(fields=fields)
                for oper, fidxs in operations.items():
                    if len(fidxs) > 0:
                        exec(getattr(vls, f"sql_{oper}_fields")(fidxs))


def _execute_multiple(queries, *, session):
    for q in queries:
        session.execute(q)


VectorLayerSession.listen(DBSession)


def estimate_vector_layer_data(resource):
    ctab = resource.vlschema().ctab

    # NOTE: Without SQL manipulations it will hit Python recursion limit on 400+
    # columns. Columns name aren't user generated, so it's safe to use them here
    # without escaping.

    fixed = FIELD_TYPE_SIZE[FIELD_TYPE.INTEGER]  # ID field size
    dynamic = [f"coalesce(length(ST_AsBinary({ctab.c.geom.name})), 0)"]
    for f in resource.fields:
        if f.datatype == FIELD_TYPE.STRING:
            dynamic.append(f"coalesce(octet_length({ctab.fields[f.keyname].name}), 0)")
        else:
            fixed += FIELD_TYPE_SIZE[f.datatype]

    dynamic.insert(0, str(fixed))
    query = select(text(" + ".join(dynamic))).select_from(ctab)
    return inspect(resource).session.scalar(query)


class _source_attr(SP):
    def _ogrds(self, filename, source_filename=None):
        ogrds = read_dataset_vector(
            filename,
            source_filename=source_filename,
        )

        if ogrds is None:
            ogrds = ogr.Open(filename, 0)
            if ogrds is None:
                raise VE(message=gettext("GDAL library failed to open file."))
            else:
                drivername = ogrds.GetDriver().GetName()
                raise VE(message=gettext("Unsupport OGR driver: %s.") % drivername)

        return ogrds

    def _ogrlayer(self, ogrds, layer_name=None):
        if layer_name is not None:
            ogrlayer = ogrds.GetLayerByName(layer_name)
        else:
            if ogrds.GetLayerCount() < 1:
                raise VE(message=gettext("Dataset doesn't contain layers."))

            if ogrds.GetLayerCount() > 1:
                raise VE(message=gettext("Dataset contains more than one layer."))

            ogrlayer = ogrds.GetLayer(0)

        if ogrlayer is None:
            raise VE(message=gettext("Unable to open layer."))

        # Do not trust geometry type of shapefiles
        if ogrds.GetDriver().ShortName == DRIVERS.ESRI_SHAPEFILE:
            ogrlayer.GetGeomType = lambda: ogr.wkbUnknown

        return ogrlayer

    def _setup_layer(self, obj, ogrlayer, **kw):
        try:
            # Apparently OGR_XLSX_HEADERS is taken into account during the GetSpatialRef call
            gdal.SetConfigOption("OGR_XLSX_HEADERS", "FORCE")
            if ogrlayer.GetSpatialRef() is None:
                raise VE(message=gettext("Layer doesn't contain coordinate system information."))
        finally:
            gdal.SetConfigOption("OGR_XLSX_HEADERS", None)

        obj.from_source(ogrlayer, **kw)

    def setter(self, srlzr, value):
        if srlzr.obj.id is not None:
            srlzr.obj._vlschema_wipe()
            inspect(srlzr.obj).session.flush()

        fupload = FileUpload(id=value["id"])
        ogrds = self._ogrds(str(fupload.data_path), source_filename=fupload.name)

        layer_name = srlzr.data.get("source_layer")
        ogrlayer = self._ogrlayer(ogrds, layer_name=layer_name)
        kwargs = dict()

        if (val := srlzr.data.get("skip_other_geometry_types", UNSET)) is not UNSET:
            kwargs["skip_other_geometry_types"] = bool(val)

        if (val := srlzr.data.get("fix_errors", UNSET)) is not UNSET:
            if val not in FIX_ERRORS.enum:
                raise VE(message=gettext("Unknown 'fix_errors' value."))
            kwargs["fix_errors"] = val

        if (val := srlzr.data.get("skip_errors", UNSET)) is not UNSET:
            kwargs["skip_errors"] = bool(val)

        if (val := srlzr.data.get("cast_geometry_type", UNSET)) is not UNSET:
            if val not in (None, "POINT", "LINESTRING", "POLYGON"):
                raise VE(message=gettext("Unknown 'cast_geometry_type' value."))
            kwargs["cast_geometry_type"] = val

        if (val := srlzr.data.get("cast_is_multi", UNSET)) is not UNSET:
            if val not in TOGGLE.enum:
                raise VE(message=gettext("Unknown 'cast_is_multi' value."))
            kwargs["cast_is_multi"] = val

        if (val := srlzr.data.get("cast_has_z", UNSET)) is not UNSET:
            if val not in TOGGLE.enum:
                raise VE(message=gettext("Unknown 'cast_has_z' value."))
            kwargs["cast_has_z"] = val

        if (val := srlzr.data.get("fid_source", UNSET)) is not UNSET:
            if val not in FID_SOURCE.enum:
                raise VE(message=gettext("Unknown 'fid_source' value."))
            kwargs["fid_source"] = val

        if (val := srlzr.data.get("fid_field", UNSET)) is not UNSET:
            if isinstance(val, str):
                val = re.split(r"\s*,\s*", val)
            kwargs["fid_field"] = val

        self._setup_layer(
            srlzr.obj,
            ogrlayer,
            **kwargs,
        )


class _fields_attr(SP):
    def setter(self, srlzr, value):
        srlzr.obj.setup_from_fields(value)


class _geometry_type_attr(SP):
    def setter(self, srlzr, value):
        if value not in GEOM_TYPE.enum:
            raise VE(message=gettext("Unsupported geometry type."))

        if srlzr.obj.id is None:
            srlzr.obj.geometry_type = value
        elif srlzr.obj.geometry_type == value:
            pass
        else:
            srlzr.obj.geometry_type_change(value)


class _delete_all_features_attr(SP):
    def setter(self, srlzr, value):
        if value:
            srlzr.obj.feature_delete_all()


P_DSS_READ = DataStructureScope.read
P_DSS_WRITE = DataStructureScope.write
P_DS_READ = DataScope.read
P_DS_WRITE = DataScope.write


class _source_option(SP):
    def __init__(self):
        super().__init__(write=P_DS_WRITE)

    def setter(self, srlzr, value):
        pass


class VectorLayerSerializer(Serializer):
    identity = VectorLayer.identity
    resclass = VectorLayer

    srs = SR(read=P_DSS_READ, write=P_DSS_WRITE)

    source = _source_attr(write=P_DS_WRITE)
    source_layer = _source_option()
    fix_errors = _source_option()
    skip_errors = _source_option()
    cast_geometry_type = _source_option()
    cast_is_multi = _source_option()
    cast_has_z = _source_option()
    fid_source = _source_option()
    fid_field = _source_option()
    skip_other_geometry_types = _source_option()

    geometry_type = _geometry_type_attr(read=P_DSS_READ, write=P_DSS_WRITE)
    fields = _fields_attr(write=P_DS_WRITE)

    delete_all_features = _delete_all_features_attr(write=P_DS_WRITE)
