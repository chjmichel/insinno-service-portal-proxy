"""Service Products define instances through their ObjectItems.

ServiceContractDTO has no product relationship. sourceProductId is persisted as
an ordinary ServiceDetail; the actual canonical links stay contract/objectitem.
"""
import copy
import math

from .icore_client import ICoreError


def product_view(product):
    objects = []
    for obj in product.get('objectitems', []):
        if obj.get('deactivated') or not obj.get('objectType'):
            continue
        attributes = []
        for attr in obj.get('attributes', []):
            if not attr.get('varName') or attr.get('occult'):
                continue
            attributes.append({
                'key': attr['varName'], 'label': attr.get('name') or attr['varName'],
                'type': str(attr.get('type', 'STRING')).lower(),
                'required': bool(attr.get('required')), 'readonly': bool(attr.get('readonly')),
            })
        objects.append({'id': str(obj['id']), 'name': obj.get('name', ''), 'objectType': obj['objectType'], 'attributes': attributes})
    return {'id': str(product['id']), 'name': product.get('displayName') or product.get('name') or '',
            'description': product.get('description') or '', 'type': 'SERVICE', 'objectItems': objects}


async def load_products(service, token):
    rows = service.mock_data.get('products', []) if service.use_mock_data else await service.live_records('/products', token)
    return [product_view(p) for p in rows if not p.get('deactivated') and (p.get('producttype') or {}).get('name') == 'SERVICE']


def service_view(service, record, product, obj):
    details = service._detail_map(record.get('serviceDetails', []))
    return {
        'id': str(record['id']), 'useCaseId': str((record.get('contract') or {}).get('id', '')),
        'productId': product['id'], 'productName': product['name'], 'productType': 'SERVICE',
        'objectItemId': obj['id'], 'objectType': obj['objectType'],
        'name': details.get('instanceName') or product['name'], 'description': product['description'],
        'status': details.get('serviceStatus') or 'OFFLINE',
        'responsible': details.get('responsible') or '', 'customerContact': details.get('customerContact') or '',
        'configuration': {a['key']: details.get(a['key'], '') for a in obj['attributes']},
        'attributes': obj['attributes'],
    }


async def load_services(service, token):
    products = {p['id']: p for p in await load_products(service, token)}
    use_cases = {u['id'] for u in await service.load_resource('useCases', token)}
    rows = service.mock_data.get('servicecontracts', []) if service.use_mock_data else await service.live_records('/servicecontracts', token)
    result = []
    for row in rows:
        if row.get('deactivated') or str((row.get('contract') or {}).get('id', '')) not in use_cases:
            continue
        details = service._detail_map(row.get('serviceDetails', []))
        object_id = str((row.get('objectitem') or {}).get('id', ''))
        source_product_id = details.get('sourceProductId')
        product = products.get(str(source_product_id)) if source_product_id else None
        if not source_product_id:
            # Native iCore generation may not write portal provenance. A unique
            # Product.objectitems relationship is authoritative, unlike names.
            candidates = [p for p in products.values() if any(o['id'] == object_id for o in p['objectItems'])]
            product = candidates[0] if len(candidates) == 1 else None
        if not product:
            continue
        obj = next((o for o in product['objectItems'] if o['id'] == object_id), None)
        if obj:
            result.append(service_view(service, row, product, obj))
    return result


async def create_service(service, payload, token, record_id=None):
    from .mutations import _lock, details_set, persist, write_live
    async with _lock:
        if service.use_mock_data:
            service.mock_data = service._load_json(service.mock_data_path)
        use_case = next((u for u in await service.load_resource('useCases', token) if u['id'] == payload.useCaseId), None)
        if not use_case:
            raise ICoreError('Use case does not exist', 422)
        product = next((p for p in await load_products(service, token) if p['id'] == payload.productId), None)
        if not product:
            raise ICoreError('Choose a Product with ProductType SERVICE', 422)
        obj = next((o for o in product['objectItems'] if o['id'] == payload.objectItemId), None)
        if not obj:
            raise ICoreError('ObjectItem does not belong to the selected SERVICE Product', 422)
        existing = await load_services(service, token)
        current = next((s for s in existing if s['id'] == record_id), None) if record_id else None
        if record_id and not current:
            raise ICoreError('Service not found', 404)
        if current and (current['useCaseId'], current['productId'], current['objectItemId']) != (payload.useCaseId, payload.productId, payload.objectItemId):
            raise ICoreError('A service update cannot change its Use Case, Product or ObjectItem', 422)
        attrs = {a['key']: a for a in obj['attributes']}
        reserved = {'sourceProductId', 'instanceName', 'serviceStatus', 'responsible', 'customerContact'}
        for key, value in payload.configuration.items():
            if key in reserved or key not in attrs or attrs[key]['readonly']:
                raise ICoreError(f'Configuration field is not editable: {key}', 422)
            if attrs[key]['type'] == 'number':
                try:
                    if not math.isfinite(float(value)): raise ValueError()
                except ValueError: raise ICoreError(f'{key} must be a number', 422)
            if attrs[key]['type'] == 'url' and value and not value.startswith(('https://', 'http://')):
                raise ICoreError(f'{key} must be an http or https URL', 422)
        for key, attr in attrs.items():
            if attr['required'] and not payload.configuration.get(key, '').strip():
                raise ICoreError(f'Missing required configuration: {key}', 422)
        rows = service.mock_data.setdefault('servicecontracts', []) if service.use_mock_data else await service.live_records('/servicecontracts', token)
        record = copy.deepcopy(next(r for r in rows if str(r['id']) == record_id)) if record_id else {'contract': {'id': payload.useCaseId}, 'objectitem': {'id': payload.objectItemId}, 'deactivated': False}
        details_set(record, 'serviceDetails', {'sourceProductId': payload.productId, 'instanceName': payload.name, 'serviceStatus': payload.status,
                                             'responsible': payload.responsible, 'customerContact': payload.customerContact,
                                             **payload.configuration})
        if service.use_mock_data:
            if record_id:
                rows[next(i for i, r in enumerate(rows) if str(r['id']) == record_id)] = record
            else:
                record['id'] = max([int(r.get('id', 0)) for r in rows] + [0]) + 1
                rows.append(record)
            parent = next(c for c in service.mock_data['contracts'] if str(c['id']) == payload.useCaseId)
            if not record_id:
                parent.setdefault('serviceContracts', []).append({'id': record['id']})
            persist(service.mock_data_path, service.mock_data)
        else:
            await write_live(service, 'services', record, token, record_id)
        return service_view(service, record, product, obj)
