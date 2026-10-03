"""Writes portal semantics through the existing canonical iCore resources."""
import asyncio
import copy
import json
import os
import tempfile
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .icore_client import ICoreError

STATUSES = Literal['PLANNED', 'CONCEPTED', 'IN_DEVELOPMENT', 'TEST', 'ACCEPTED', 'DONE']
_lock = asyncio.Lock()


class UseCaseInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)
    description: str = ''
    status: Literal['RUNNING', 'PARTLY_RUNNING', 'OFFLINE', 'MAINTENANCE'] = 'OFFLINE'
    customerId: str = Field(pattern=r"^[1-9][0-9]*$")


class ProjectInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)
    useCaseId: str
    status: STATUSES = 'PLANNED'
    progress: float = Field(default=0, ge=0, le=100)
    startDate: date
    targetDate: date
    responsible: str = ''
    projectManager: str = ''
    developmentTeam: str = ''
    projectType: Literal['REENGINEERING', 'INITIAL_PROJECT', 'SOLUTION_DESIGN'] = 'REENGINEERING'
    customerContact: str = ''
    repositoryUrl: str = ''
    branch: str = ''

    @model_validator(mode='after')
    def dates(self):
        if self.targetDate < self.startDate:
            raise ValueError('Target date must be on or after start date')
        if self.repositoryUrl and not self.repositoryUrl.startswith(('https://', 'http://')):
            raise ValueError('Repository URL must use http or https')
        return self


class WorkInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)
    projectId: str
    status: STATUSES = 'PLANNED'
    progress: float = Field(default=0, ge=0, le=100)
    startDate: date
    targetDate: date
    timelineName: str = Field(default='Delivery', min_length=1, max_length=100)

    @model_validator(mode='after')
    def dates(self):
        if self.targetDate < self.startDate:
            raise ValueError('Target date must be on or after start date')
        return self


class ServiceInput(BaseModel):
    name: str = Field(default='', max_length=200)
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    useCaseId: str = Field(pattern=r'^[1-9][0-9]*$')
    productId: str = Field(pattern=r'^[1-9][0-9]*$')
    objectItemId: str = Field(pattern=r'^[1-9][0-9]*$')
    status: Literal['RUNNING', 'PARTLY_RUNNING', 'OFFLINE', 'MAINTENANCE'] = 'OFFLINE'
    responsible: str = ''
    customerContact: str = ''
    configuration: dict[str, str] = Field(default_factory=dict)


def items(payload):
    return payload if isinstance(payload, list) else payload.get('items', payload.get('content', []))


def details_set(record, key, values):
    rows = record.setdefault(key, [])
    for name, value in values.items():
        row = next((r for r in rows if r.get('attributeName') == name), None)
        if row is None:
            row = {'attributeName': name}
            rows.append(row)
        row.update(value=str(value), valueLabel=str(value))


async def mutate(service, resource, token, payload=None, record_id=None, delete=False):
    if resource == 'services':
        if delete:
            raise ICoreError('Service deletion is not supported', 405)
        from .service_catalog import create_service
        return await create_service(service, payload, token, record_id)
    if resource not in {'useCases', 'projects', 'epics', 'milestones'}:
        raise ICoreError('Resource is not editable', 404)
    if delete and resource not in {'epics', 'milestones'}:
        raise ICoreError('Deletion is supported only for epics and timeline entries', 405)
    async with _lock:
        # Reload inside the lock: each request has a separate SemanticService.
        if service.use_mock_data:
            data = service._load_json(service.mock_data_path)
            service.mock_data = data
        else:
            data = {}
        source = service.model['resources'][resource]['source']
        endpoint, key = source['endpoint'], source['mockKey']
        records = data.setdefault(key, []) if service.use_mock_data else await service.live_records(endpoint, token)
        existing = next((r for r in records if str(r.get('id')) == record_id and service._matches_filters(r, service.model['resources'][resource]['filters'])), None)
        if record_id and existing is None:
            raise ICoreError('Record not found in this semantic resource', 404)
        if delete:
            if service.use_mock_data:
                records.remove(existing)
                for contract in data.get('contracts', []):
                    contract['serviceContracts'] = [r for r in contract.get('serviceContracts', []) if str(r.get('id')) != record_id]
                persist(service.mock_data_path, data)
            else:
                await service.client.request('DELETE', f'{endpoint}/{record_id}', token)
            return {'success': True}
        values = payload.model_dump(mode='json')
        relation = 'useCases' if resource == 'projects' else 'projects'
        if resource != 'useCases':
            parent_id = values['useCaseId' if resource == 'projects' else 'projectId']
            if not any(r['id'] == parent_id for r in await service.load_resource(relation, token)):
                raise ICoreError('Parent use case/project does not exist', 422)
        if resource == 'useCases':
            if service.use_mock_data:
                if not any(str(p.get('id')) == values['customerId'] for p in data.get('partners', [])):
                    raise ICoreError('Customer partner does not exist', 422)
            else:
                await service.client.request('GET', f"/partners/{values['customerId']}", token)
        record = copy.deepcopy(existing) if existing else {}
        record['deactivated'] = False
        semantic_type = service.model['resources'][resource]['semanticType']
        if not existing:
            # Reuse configured definitions. Never create new Product/Object types per instance.
            definition = 'product' if resource in {'useCases', 'projects'} else 'objectitem'
            template = next((r.get(definition) for r in records if service._matches_filters(r, service.model['resources'][resource]['filters'])), None)
            if not template and service.use_mock_data:
                template = {'id': 1101 if resource == 'useCases' else 1102, 'producttype': {'name': semantic_type}} if definition == 'product' else {'id': 1301 if resource == 'epics' else 1302, 'objectType': semantic_type}
            if not template:
                raise ICoreError(f'Configure an iCore {semantic_type} definition before creating an instance', 422)
            record[definition] = copy.deepcopy(template)
        record['name'] = values['name']
        if resource == 'useCases':
            record['status'] = 'ACTIVE'
            record['owner'] = {'id': values['customerId']}
            details_set(record, 'contractDetails', {'summary': values['description'], 'serviceStatus': values['status']})
        elif resource == 'projects':
            record.update(status=values['status'], startDate=values['startDate'], endDate=values['targetDate'], parentcontract={'id': values['useCaseId']})
            details_set(record, 'contractDetails', {k: v for k, v in values.items() if k not in {'name', 'useCaseId', 'status', 'startDate', 'targetDate'}})
        else:
            record['contract'] = {'id': values['projectId']}
            details_set(record, 'serviceDetails', {'name': values['name'], 'status': values['status'], 'progress': values['progress'], 'startDate': values['startDate'], 'endDate': values['targetDate'], 'plannedDate': values['targetDate'], 'timelineName': values['timelineName']})
        if service.use_mock_data:
            if not existing:
                record['id'] = max([int(r.get('id', 0)) for r in records] + [0]) + 1
                records.append(record)
            else:
                records[records.index(existing)] = record
            if resource in {'epics', 'milestones'}:
                for contract in data.get('contracts', []):
                    refs = [r for r in contract.get('serviceContracts', []) if str(r.get('id')) != str(record['id'])]
                    if str(contract.get('id')) == values['projectId']:
                        refs.append({'id': record['id']})
                    contract['serviceContracts'] = refs
            persist(service.mock_data_path, data)
            return service._normalize(resource, record)
        return await write_live(service, resource, record, token, record_id)


def persist(path, data):
    destination = Path(path)
    descriptor, temporary = tempfile.mkstemp(dir=destination.parent, suffix='.tmp')
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


async def write_live(service, resource, record, token, record_id):
    """Use the uploaded OpenAPI's body wrapper, relation refs and detail endpoints."""
    contract = resource in {'useCases', 'projects'}
    endpoint = '/contracts' if contract else '/servicecontracts'
    detail_key = 'contractDetails' if contract else 'serviceDetails'
    detail_endpoint = '/contractdetails' if contract else '/servicedetails'
    allowed = {'id', 'name', 'status', 'startDate', 'endDate', 'owner', 'parentcontract', 'product', 'objectitem', 'deactivated'} if contract else {'id', 'contract', 'objectitem', 'deactivated'}
    body = {k: v for k, v in record.items() if k in allowed}
    for k in ['owner', 'parentcontract', 'product', 'objectitem', 'contract']:
        if body.get(k): body[k] = {'id': str(body[k]['id'])}
    for k in ['startDate', 'endDate']:
        if body.get(k) and len(body[k]) == 10: body[k] += 'T00:00:00Z'
    response = await service.client.request('PUT' if record_id else 'POST', endpoint + (f'/{record_id}' if record_id else ''), token, json={'body': body} if contract else body)
    new_id = record_id or (response.get('body', response).get('id') if isinstance(response, dict) else None)
    if not new_id:
        raise ICoreError('iCore create response contains no id; reload before retrying', 502)
    record['id'] = new_id
    for row in record.get(detail_key, []):
        detail = {k: row[k] for k in ['id', 'attributeName', 'value', 'valueLabel', 'objectattribute'] if k in row}
        if detail.get('objectattribute'): detail['objectattribute'] = {'id': str(detail['objectattribute']['id'])}
        detail['contract' if contract else 'serviceContract'] = {'id': str(new_id)}
        try:
            await service.client.request('PUT' if row.get('id') else 'POST', detail_endpoint + (f"/{row['id']}" if row.get('id') else ''), token, json=detail)
        except ICoreError as exc:
            raise ICoreError(f'iCore record {new_id} was saved but detail {row.get("attributeName")} failed. Reload before retrying. {exc}', exc.status_code) from exc
    return service._normalize(resource, record)
