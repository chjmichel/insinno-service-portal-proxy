import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.settings import Settings, get_settings
from app.semantics import SemanticService
from app.mutations import ServiceInput
from app.service_catalog import create_service

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client(tmp_path):
    fixture = tmp_path / 'icore-api.json'
    fixture.write_text((ROOT / 'config/mock/icore-api.json').read_text())
    config = Settings(use_mock_data=True, require_authentication=False, semantics_config_path=str(ROOT / 'config/semantics.json'), mock_data_path=str(fixture))
    app.dependency_overrides[get_settings] = lambda: config
    with TestClient(app) as api:
        yield api, fixture
    app.dependency_overrides.clear()


def test_three_distinct_service_products_and_scoped_kpis(client):
    api, _ = client
    data = api.get('/api/v1/portal/bootstrap').json()
    products = data['serviceProducts']
    services = data['services']
    assert len(products) == len(services) == 3
    assert {p['type'] for p in products} == {'SERVICE'}
    assert len({p['id'] for p in products}) == 3
    assert {s['objectType'] for s in services} == {'TECHNICAL_OPERATIONS', 'SALES_PROCESSES', 'CORRECTION_SERVICES'}
    assert {s['useCaseId'] for s in services} == {'1001'}
    for service in services:
        product = next(p for p in products if p['id'] == service['productId'])
        assert service['objectItemId'] in {o['id'] for o in product['objectItems']}
        metrics = [k for k in data['kpis'] if k.get('serviceId') == service['id']]
        assert len(metrics) == 2
        assert all(k['useCaseId'] == service['useCaseId'] for k in metrics)
    assert api.get('/api/v1/resources/services').json() == services
    assert api.get('/api/v1/resources/serviceProducts').json() == products


def test_create_from_product_and_reload(client):
    api, fixture = client
    uc = api.post('/api/v1/resources/useCases', json={'name': 'Another customer service', 'customerId': '501'}).json()
    payload = {'useCaseId': uc['id'], 'productId': '1151', 'objectItemId': '1401', 'status': 'RUNNING', 'responsible': 'Michael', 'configuration': {'devUrl': 'https://dev.example', 'supportWindow': '24/7'}}
    result = api.post('/api/v1/resources/services', json=payload)
    assert result.status_code == 201, result.text
    created = result.json()
    assert created['objectType'] == 'TECHNICAL_OPERATIONS'
    assert created['name'] == 'Technical Operations'
    assert created['configuration']['supportWindow'] == '24/7'
    assert created['useCaseId'] == uc['id']
    raw = json.loads(fixture.read_text())
    record = next(s for s in raw['servicecontracts'] if str(s['id']) == created['id'])
    assert record['contract'] == {'id': created['contractId']}
    assert record['objectitem'] == {'id': '1401'}
    assert 'product' not in record and 'serviceType' not in record
    assert next(d['value'] for d in record['serviceDetails'] if d['attributeName'] == 'sourceProductId') == '1151'
    parent = next(c for c in raw['contracts'] if str(c['id']) == created['contractId'])
    assert parent['parentcontract'] == {'id': uc['id']}
    assert str(parent['product']['id']) == '1151'
    assert {'id': record['id']} in parent['serviceContracts']
    service = SemanticService(str(ROOT / 'config/semantics.json'), None, use_mock_data=True, mock_data_path=str(fixture))
    reloaded = asyncio.run(service.load_resource('services', ''))
    assert any(s == created for s in reloaded)
    additional = api.post('/api/v1/resources/services', json={**payload, 'name': 'Additional technical operations'})
    assert additional.status_code == 201
    assert additional.json()['id'] != created['id']
    assert additional.json()['name'] == 'Additional technical operations'


@pytest.mark.parametrize('changes', [
    {'productId': '1101'},  # USE_CASE product
    {'objectItemId': '1402'},  # ObjectItem of another SERVICE product
    {'useCaseId': '1002'},  # project, not use case
    {'configuration': {'sourceProductId': '1153'}},
    {'configuration': {'devUrl': 'javascript:alert(1)'}},
    {'configuration': {'notInObjectItem': 'value'}},
])
def test_reject_invalid_product_objectitem_parent_and_attributes(client, changes):
    api, fixture = client
    before = fixture.read_text()
    payload = {'useCaseId': '1001', 'productId': '1151', 'objectItemId': '1401', **changes}
    response = api.post('/api/v1/resources/services', json=payload)
    assert response.status_code == 422, response.text
    assert fixture.read_text() == before


def test_names_do_not_define_semantics(client):
    api, fixture = client
    raw = json.loads(fixture.read_text())
    raw['products'][2]['name'] = 'Customer configurable name'
    raw['products'][2]['displayName'] = 'Custom hosting package'
    fixture.write_text(json.dumps(raw))
    rows = api.get('/api/v1/resources/services').json()
    row = next(s for s in rows if s['productId'] == '1151')
    assert row['productName'] == 'Custom hosting package'
    assert row['name'] == 'Technical Operations'
    assert row['objectType'] == 'TECHNICAL_OPERATIONS'


def test_live_service_creation_uses_only_existing_dto_fields():
    raw = json.loads((ROOT / 'config/mock/icore-api.json').read_text())
    class FakeClient:
        def __init__(self): self.calls = []
        async def request(self, method, path, token, **kwargs):
            self.calls.append((method, path, kwargs.get('json')))
            if method == 'GET':
                if path == '/products': return raw['products']
                if path == '/contracts': return raw['contracts']
                if path == '/servicecontracts': return []
                if path.startswith('/objectitems/'):
                    return next(o for o in raw['objectitems'] if str(o['id']) == path.split('/')[-1])
            return {'id': 2500}
    client = FakeClient()
    service = SemanticService(str(ROOT / 'config/semantics.json'), client)
    result = asyncio.run(create_service(service, ServiceInput(useCaseId='1001', productId='1151', objectItemId='1401', status='RUNNING'), 'token'))
    assert result['id'] == '2500'
    writes = [c for c in client.calls if c[0] == 'POST']
    assert writes[0][1] == '/contracts'
    assert writes[0][2]['body']['product'] == {'id': '1151'}
    assert writes[0][2]['body']['parentcontract'] == {'id': '1001'}
    assert writes[1][1] == '/servicecontracts'
    assert writes[1][2] == {'contract': {'id': '2500'}, 'objectitem': {'id': '1401'}, 'deactivated': False}
    assert any(path == '/servicedetails' and body.get('attributeName') == 'sourceProductId' and body['value'] == '1151' for _, path, body in writes[1:])


def test_native_generated_service_resolves_through_unique_product_objectitem(client):
    api, fixture = client
    raw = json.loads(fixture.read_text())
    record = next(s for s in raw['servicecontracts'] if s['id'] == 2401)
    record['contract'] = {'id': 1001}  # Legacy instance directly under the Use Case.
    record['serviceDetails'] = [d for d in record['serviceDetails'] if d['attributeName'] != 'sourceProductId']
    fixture.write_text(json.dumps(raw))
    services = api.get('/api/v1/resources/services').json()
    assert next(s for s in services if s['id'] == '2401')['productId'] == '1151'
    # A shared ObjectItem without provenance must not silently choose a Product.
    duplicate = dict(raw['products'][2], id=1199, name='Another hosting product')
    raw['products'].append(duplicate)
    fixture.write_text(json.dumps(raw))
    assert all(s['id'] != '2401' for s in api.get('/api/v1/resources/services').json())


def test_fixture_ids_are_unique(client):
    _, fixture = client
    raw = json.loads(fixture.read_text())
    for collection in ['products', 'contracts', 'objectitems', 'servicecontracts']:
        ids = [row['id'] for row in raw[collection]]
        assert len(ids) == len(set(ids)), collection


def test_update_service_preserves_product_and_other_services(client):
    api, fixture = client
    before = api.get('/api/v1/resources/services').json()
    current = next(s for s in before if s['id'] == '2401')
    body = dict(name='Technical Operations DEV', useCaseId=current['useCaseId'], productId=current['productId'], objectItemId=current['objectItemId'], status='MAINTENANCE', responsible='New operator', customerContact='Anna', configuration={**current['configuration'], 'supportWindow': '24/7', 'devUrl': 'https://new-dev.example'})
    result = api.put('/api/v1/resources/services/2401', json=body)
    assert result.status_code == 200, result.text
    updated = result.json()
    assert updated['name'] == 'Technical Operations DEV'
    assert updated['status'] == 'MAINTENANCE'
    assert updated['configuration']['supportWindow'] == '24/7'
    assert updated['configuration']['prdUrl'] == current['configuration']['prdUrl']
    after = api.get('/api/v1/resources/services').json()
    assert next(s for s in after if s['id'] == '2402') == next(s for s in before if s['id'] == '2402')
    assert len(after) == len(before)
    raw = json.loads(fixture.read_text())
    record = next(s for s in raw['servicecontracts'] if s['id'] == 2401)
    assert record['objectitem'] == {'id': 1401}
    assert record['contract'] == {'id': current['contractId']}
    assert next(d['value'] for d in record['serviceDetails'] if d['attributeName'] == 'sourceProductId') == '1151'
    assert api.put('/api/v1/resources/services/999999', json=body).status_code == 404
    unchanged = fixture.read_text()
    assert api.put('/api/v1/resources/services/2401', json={**body, 'productId':'1152','objectItemId':'1402'}).status_code == 422
    assert fixture.read_text() == unchanged


def test_live_service_update_puts_existing_record_and_details():
    raw = json.loads((ROOT / 'config/mock/icore-api.json').read_text())
    record = next(s for s in raw['servicecontracts'] if s['id'] == 2401)
    for i, detail in enumerate(record['serviceDetails']): detail['id'] = 9000 + i
    class FakeClient:
        def __init__(self): self.calls = []
        async def request(self, method, path, token, **kwargs):
            self.calls.append((method, path, kwargs.get('json')))
            if method == 'GET':
                if path == '/products': return raw['products']
                if path == '/contracts': return raw['contracts']
                if path == '/servicecontracts': return [record]
                if path.startswith('/objectitems/'):
                    return next(o for o in raw['objectitems'] if str(o['id']) == path.split('/')[-1])
            return {'id': 2401}
    client = FakeClient()
    service = SemanticService(str(ROOT / 'config/semantics.json'), client)
    result = asyncio.run(create_service(service, ServiceInput(name='Renamed instance', useCaseId='1001', productId='1151', objectItemId='1401', status='MAINTENANCE', configuration={'supportWindow':'24/7'}), 'token', '2401'))
    assert result['name'] == 'Renamed instance'
    writes = [c for c in client.calls if c[0] in {'PUT', 'POST'}]
    assert writes[0][0:2] == ('PUT', '/contracts/1601')
    assert writes[0][2]['body']['name'] == 'Renamed instance'
    assert writes[1][0:2] == ('PUT', '/servicecontracts/2401')
    assert any(method == 'PUT' and path.startswith('/servicedetails/') and body['attributeName']=='supportWindow' and body['value']=='24/7' for method,path,body in writes)
    assert all(path != '/servicecontracts' for _,path,_ in writes)


def test_contract_core_update_is_scoped_to_service_contract(client):
    api, fixture = client
    before = json.loads(fixture.read_text())
    original_use_case = next(c for c in before['contracts'] if c['id'] == 1001)
    original_other = next(c for c in before['contracts'] if c['id'] == 1602)
    service = next(s for s in api.get('/api/v1/resources/services').json() if s['id'] == '2401')
    body = dict(name='Hosting contract 2027', useCaseId='1001', productId='1151', objectItemId='1401', status='RUNNING', configuration=service['configuration'], contractCore=dict(status='SUSPENDED', startDate='2027-01-01', endDate='2027-12-31', ownerId='900', externalId='PFEFF-HOST-2027', notes='New service agreement'))
    response = api.put('/api/v1/resources/services/2401', json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['contractId'] == '1601'
    assert result['contractCore'] == body['contractCore']
    assert result['name'] == body['name']
    after = json.loads(fixture.read_text())
    contract = next(c for c in after['contracts'] if c['id'] == 1601)
    assert contract['name'] == body['name']
    assert contract['status'] == 'SUSPENDED'
    assert contract['owner'] == {'id': '900'}
    assert str(contract['product']['id']) == '1151'
    assert next(c for c in after['contracts'] if c['id'] == 1001) == original_use_case
    assert next(c for c in after['contracts'] if c['id'] == 1602) == original_other
    reloaded = api.get('/api/v1/portal/bootstrap').json()
    assert next(s for s in reloaded['services'] if s['id']=='2401')['contractCore'] == body['contractCore']
    snapshot = fixture.read_text()
    body['contractCore']['endDate'] = '2026-01-01'
    assert api.put('/api/v1/resources/services/2401', json=body).status_code == 422
    assert fixture.read_text() == snapshot
    body['contractCore'].update(endDate='2027-12-31', ownerId='999999')
    assert api.put('/api/v1/resources/services/2401', json=body).status_code == 422
    assert fixture.read_text() == snapshot


def test_legacy_service_migrates_on_save_without_changing_use_case(client):
    api, fixture = client
    raw = json.loads(fixture.read_text())
    raw['contracts'] = [c for c in raw['contracts'] if c['id'] != 1601]
    record = next(s for s in raw['servicecontracts'] if s['id']==2401)
    record['contract'] = {'id':1001}
    parent = next(c for c in raw['contracts'] if c['id']==1001)
    parent['serviceContracts'].append({'id':2401})
    fixture.write_text(json.dumps(raw))
    service = next(s for s in api.get('/api/v1/resources/services').json() if s['id']=='2401')
    assert service['contractId'] is None
    result = api.put('/api/v1/resources/services/2401', json=dict(name='Migrated service', useCaseId='1001', productId='1151', objectItemId='1401', configuration=service['configuration']))
    assert result.status_code==200,result.text
    cid=result.json()['contractId'];assert cid and cid!='1001'
    after=json.loads(fixture.read_text())
    updated_parent=next(c for c in after['contracts'] if c['id']==1001)
    assert updated_parent['name']==parent['name']
    assert updated_parent['product']==parent['product']
    assert {'id':2401} not in updated_parent['serviceContracts']
    child=next(c for c in after['contracts'] if str(c['id'])==cid)
    assert child['parentcontract']=={'id':'1001'}
    assert {'id':2401} in child['serviceContracts']
    assert next(s for s in after['servicecontracts'] if s['id']==2401)['contract']=={'id':cid}
