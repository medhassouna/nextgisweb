from .. import db
from ..env import env
from ..lib.i18n import trstr_factory


COMP_ID = 'postgis'
_ = trstr_factory(COMP_ID)


def translate(trstring):
    return env.core.localizer().translate(trstring)


postgis_srs = db.table(
    'spatial_ref_sys',
    db.column('srid'),
)


info_tables = db.table(
    'tables',
    db.column('table_schema'),
    db.column('table_name'),
    schema='information_schema')


info_grants = db.table(
    'role_table_grants',
    db.column('table_schema'),
    db.column('table_name'),
    db.column('grantee'),
    db.column('privilege_type'),
    schema='information_schema')


def table_exists(connection, table_name, table_schema='public'):
    stmt = db.select(info_tables).where(db.and_(
        info_tables.c.table_schema == table_schema,
        info_tables.c.table_name == table_name,
    )).exists().select()
    exists = connection.execute(stmt).scalar()

    return exists
