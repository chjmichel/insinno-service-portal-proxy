import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.settings import Settings, get_settings
from app.auth import require_user
from app.mutations import ProjectInput, WorkInput, write_live
from app.semantics import SemanticService

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client(tmp_path):
    fixture = tmp_path / 'icore-api.json'
    fixture.write_text((ROOT / 'config/mock/icore-api.json').read_text())
    config = Settings(use_mock_data=True, require_authentication=False, semantics_config_path=str(ROOT / 'config/semantics.json'), mock_data_path=str(fixture))
    app.dependency_overrides[get_settings] = lambda: config
    with TestClient(app) as client:
        yield client, fixture
    app.dependency_overrides.clear()


def test_create_update_reload_and_delete(client):
    api, fixture = client
    base = '/api/v1/resources/'
    uc = api.post(base + 'useCases', json={'name': 'New sales service', 'customerId': '501', 'description': 'Customer-specific description', 'status': 'MAINTENANCE'})
    assert uc.status_code == 201, uc.text
    uc = uc.json()
    project = dict(name='Migration', useCaseId=uc['id'], startDate='2026-10-01', targetDate='2026-12-31', projectManager='Anna', responsible='Laura', progress=20, projectType='REENGINEERING', repositoryUrl='https://github.com/chjmichel/insinno-service-portal', branch='development')
    saved = api.post(base + 'projects', json=project)
    assert saved.status_code == 201, saved.text
    pid = saved.json()['id']
    project.update(progress=65, projectManager='Michael', branch='release')
    assert api.put(base + 'projects/' + pid, json=project).status_code == 200
    for resource in ['epics', 'milestones']:
        work = dict(name='Acceptance tests', projectId=pid, startDate='2026-11-01', targetDate='2026-11-20', timelineName='Quality assurance', progress=0)
        response = api.post(base + resource, json=work)
        assert response.status_code == 201, response.text
        wid = response.json()['id']
        work.update(name='Customer acceptance', progress=50)
        updated = api.put(base + resource + '/' + wid, json=work)
        assert updated.status_code == 200, updated.text
        rows = api.get(base + resource).json()
        assert any(r['id'] == wid and r['name'] == 'Customer acceptance' for r in rows)
        assert api.delete(base + resource + '/' + wid).status_code == 200
        assert all(r['id'] != wid for r in api.get(base + resource).json())
        assert api.delete(base + resource + '/' + wid).status_code == 404
    bootstrap = api.get('/api/v1/portal/bootstrap').json()
    assert next(r for r in bootstrap['useCases'] if r['id'] == uc['id'])['description'] == 'Customer-specific description'
    assert next(r for r in bootstrap['projects'] if r['id'] == pid)['progress'] == 65
    assert next(r for r in bootstrap['projects'] if r['id'] == pid)['branch'] == 'release'
    # File persisted in canonical shape, readable by a new service after restart.
    raw = json.loads(fixture.read_text())
    assert next(c for c in raw['contracts'] if str(c['id']) == pid)['product']['producttype']['name'] == 'PROJECT'
    service = SemanticService(str(ROOT / 'config/semantics.json'), None, use_mock_data=True, mock_data_path=str(fixture))
    assert any(p['id'] == pid for p in asyncio.run(service.load_resource('projects', '')))


def test_validation_and_semantic_boundaries(client):
    api, _ = client
    base = '/api/v1/resources/'
    assert api.post(base + 'useCases', json={'name': '  ', 'customerId': '501'}).status_code == 422
    assert api.post(base + 'useCases', json={'name': 'Sales', 'customerId': '99999'}).status_code == 422
    p = dict(name='Bad dates', useCaseId='1001', startDate='2026-12-01', targetDate='2026-10-01')
    assert api.post(base + 'projects', json=p).status_code == 422
    p.update(targetDate='2027-01-01', progress=101)
    assert api.post(base + 'projects', json=p).status_code == 422
    p.update(progress=30, useCaseId='99999')
    assert api.post(base + 'projects', json=p).status_code == 422
    w = dict(name='Scope', projectId='1002', startDate='2026-10-01', targetDate='2026-11-01')
    assert api.put(base + 'epics/2051', json=w).status_code == 404
    assert api.delete(base + 'projects/1002').status_code == 405
    assert api.post(base + 'apps', json={}).status_code == 404


def test_mock_multi_timelines(client):
    api, _ = client
    data = api.get('/api/v1/portal/bootstrap').json()
    assert len(data['projects']) >= 2
    assert len({m['projectId'] for m in data['milestones']}) >= 2
    assert {'Delivery', 'Quality assurance'} <= {m['timelineName'] for m in data['milestones']}


def test_write_requires_authentication(client):
    api, fixture = client
    app.dependency_overrides[get_settings] = lambda: Settings(use_mock_data=True, require_authentication=True, semantics_config_path=str(ROOT / 'config/semantics.json'), mock_data_path=str(fixture))
    response = api.post('/api/v1/resources/useCases', json={'name': 'Secure', 'customerId': '501'})
    assert response.status_code == 401


def test_live_wire_format():
    class FakeClient:
        def __init__(self): self.calls = []
        async def request(self, method, path, token, **kwargs):
            self.calls.append((method, path, kwargs.get('json')))
            return {'id': 888}
    client = FakeClient()
    service = SemanticService(str(ROOT / 'config/semantics.json'), client)
    record = {'name': 'Project', 'product': {'id': 1102, 'producttype': {'name': 'PROJECT'}}, 'parentcontract': {'id': 1001}, 'startDate': '2026-10-01', 'endDate': '2026-12-01', 'contractDetails': [{'attributeName': 'progress', 'value': '20'}]}
    asyncio.run(write_live(service, 'projects', record, 'token', None))
    assert client.calls[0][0:2] == ('POST', '/contracts')
    body = client.calls[0][2]['body']
    assert body['product'] == {'id': '1102'}
    assert body['startDate'] == '2026-10-01T00:00:00Z'
    assert 'contractDetails' not in body
    assert client.calls[1][1] == '/contractdetails'
    assert client.calls[1][2]['contract'] == {'id': '888'}
    client.calls.clear()
    work = {'contract': {'id': 1002}, 'objectitem': {'id': 1301, 'objectType': 'EPIC'}, 'name': 'Implementation', 'serviceDetails': [{'attributeName': 'name', 'value': 'Implementation'}]}
    asyncio.run(write_live(service, 'epics', work, 'token', None))
    assert client.calls[0][2] == {'contract': {'id': '1002'}, 'objectitem': {'id': '1301'}}
    assert client.calls[1][1] == '/servicedetails'
