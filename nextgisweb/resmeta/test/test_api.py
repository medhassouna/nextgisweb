import pytest
import transaction

from nextgisweb.auth import User
from nextgisweb.models import DBSession
from nextgisweb.resource import ResourceGroup


@pytest.fixture
def resource_id(ngw_resource_group):
    with transaction.manager:
        res = ResourceGroup(
            parent_id=ngw_resource_group,
            display_name='test-resource-group',
            owner_user=User.by_keyname('administrator')
        ).persist()

        DBSession.flush()
        DBSession.expunge(res)

    yield res.id

    with transaction.manager:
        DBSession.delete(res)


def test_items(ngw_webtest_app, resource_id, ngw_auth_administrator):
    items = dict(key1='text1', key2='text2')

    res_url = '/api/resource/%d' % resource_id

    resp = ngw_webtest_app.get(res_url, status=200)
    assert resp.json['resmeta']['items'] == dict()

    data = dict(resmeta=dict(items=items))
    ngw_webtest_app.put_json(res_url, data, status=200)

    resp = ngw_webtest_app.get(res_url, status=200)
    assert resp.json['resmeta']['items'] == items

    del items['key2']
    ngw_webtest_app.put_json(res_url, data, status=200)

    resp = ngw_webtest_app.get(res_url, status=200)
    assert resp.json['resmeta']['items'] == items


@pytest.mark.parametrize('value', (
    'text', -123, 4.5, True, False, None,
))
def test_item_type(value, ngw_webtest_app, resource_id, ngw_auth_administrator):
    res_url = '/api/resource/%d' % resource_id

    items = dict(key=value)
    data = dict(resmeta=dict(items=items))

    ngw_webtest_app.put_json(res_url, data, status=200)

    resp = ngw_webtest_app.get(res_url, status=200)
    value_saved = resp.json['resmeta']['items']['key']

    if value is None:
        assert value_saved is None
    elif type(value) == float:
        assert value_saved == pytest.approx(value)
    else:
        assert value_saved == value
