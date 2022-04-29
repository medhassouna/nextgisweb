from datetime import timedelta

from sqlalchemy.engine.url import (
    URL as EngineURL,
    make_url as make_engine_url)

from .. import db
from ..component import Component, require
from ..lib.config import Option

from .model import Base, PostgisConnection, PostgisLayer

__all__ = ['PostgisConnection', 'PostgisLayer']


class PostgisComponent(Component):
    identity = 'postgis'
    metadata = Base.metadata

    def initialize(self):
        super().initialize()
        self._engine = dict()

    def get_engine(self, hostname, port, database, username, password, key=None):
        # Need to check connection params to see if
        # they changed for each connection request
        credhash = (hostname, port, database, username, password)
        if key is not None and key in self._engine:
            engine = self._engine[key]

            if engine._credhash == credhash:
                return engine
            else:
                del self._engine[key]

        connect_timeout = int(self.options['connect_timeout'].total_seconds())
        statement_timeout_ms = int(self.options['statement_timeout'].total_seconds()) * 1000
        args = dict(connect_args=dict(
            connect_timeout=connect_timeout,
            options='-c statement_timeout=%d' % statement_timeout_ms))
        engine_url = make_engine_url(EngineURL.create(
            'postgresql+psycopg2',
            host=hostname, port=port, database=database,
            username=username, password=password))
        engine = db.create_engine(engine_url, **args)

        if key is not None:
            engine._credhash = credhash
            self._engine[key] = engine

        return engine

    @require('feature_layer')
    def setup_pyramid(self, config):
        from . import view # NOQA
        from . import api
        api.setup_pyramid(self, config)

    option_annotations = (
        Option('connect_timeout', timedelta, default=timedelta(seconds=15)),
        Option('statement_timeout', timedelta, default=timedelta(seconds=15)),
    )
