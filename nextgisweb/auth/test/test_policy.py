from datetime import timedelta

import pytest
from freezegun import freeze_time


@pytest.fixture(scope='module', autouse=True)
def disable_oauth(ngw_env):
    auth = ngw_env.auth

    prev_helper = auth.oauth
    with auth.options.override({'oauth.enabled': False}):
        auth.oauth = None
        yield
    auth.oauth = prev_helper


def test_fixture(ngw_webtest_app, ngw_auth_administrator):
    resp = ngw_webtest_app.get('/api/component/auth/current_user')
    assert resp.status_code == 200
    assert resp.json['keyname'] == 'administrator'


def test_http_basic(ngw_webtest_app):
    resp = ngw_webtest_app.get('/api/component/auth/user/', expect_errors=True)
    assert resp.status_code == 403

    ngw_webtest_app.authorization = ('Basic', ('administrator', 'admin'))
    resp = ngw_webtest_app.get('/api/component/auth/current_user')
    assert resp.status_code == 200
    assert resp.json['keyname'] == 'administrator'

    ngw_webtest_app.authorization = ('Basic', ('administrator', 'invalid'))
    resp = ngw_webtest_app.get('/api/component/auth/current_user', expect_errors=True)
    assert resp.status_code == 401


def test_api_login_logout(ngw_webtest_app):
    resp = ngw_webtest_app.post('/api/component/auth/login', dict(
        login='administrator', password='admin'))
    assert resp.status_code == 200
    assert resp.json['keyname'] == 'administrator'

    _dummy_auth_request(ngw_webtest_app)

    resp = ngw_webtest_app.post('/api/component/auth/logout')
    assert resp.json == dict()
    resp = ngw_webtest_app.get('/api/component/auth/user/', expect_errors=True)
    assert resp.status_code == 403


def test_local_refresh(ngw_webtest_app, ngw_env):
    lifetime = ngw_env.auth.options['policy.local.lifetime']
    refresh = ngw_env.auth.options['policy.local.refresh']
    epsilon = timedelta(seconds=5)

    with freeze_time() as dt:
        start = dt()

        resp = ngw_webtest_app.post('/api/component/auth/login', dict(
            login='administrator', password='admin'))
        assert resp.status_code == 200

        dt.tick(lifetime + epsilon)
        _dummy_auth_request(ngw_webtest_app, 403)

        dt.move_to(start)
        dt.tick(refresh)
        _dummy_auth_request(ngw_webtest_app, 200)

        dt.tick(lifetime - epsilon)
        _dummy_auth_request(ngw_webtest_app, 200)


def _dummy_auth_request(ngw_webtest_app, status_code=200):
    resp = ngw_webtest_app.get(
        '/api/component/auth/user/',
        expect_errors=status_code < 200 or status_code >= 300)
    assert resp.status_code == status_code
