import json
from pathlib import Path
from typing import Any

from .icore_client import ICoreClient


class SemanticService:
    """Maps generic iCore resources to stable portal semantics.

    In mock mode the same semantic filtering and normalization is applied to
    iCore-shaped JSON fixtures, so frontend behavior stays identical when
    switching to live iCore.
    """

    def __init__(
        self,
        config_path: str,
        client: ICoreClient,
        *,
        use_mock_data: bool = False,
        mock_data_path: str = "config/mock/icore-api.json",
    ) -> None:
        self.mock_data_path = mock_data_path
        self.client = client
        self.use_mock_data = use_mock_data
        self.model = self._load_json(config_path)
        self.mock_data = self._load_json(mock_data_path) if use_mock_data else {}

    async def load_resource(self, resource_name: str, token: str) -> list[dict[str, Any]]:
        resource = self.model["resources"][resource_name]
        source = resource["source"]

        if self.use_mock_data:
            payload = self.mock_data.get(source["mockKey"], [])
        else:
            payload = await self.live_records(source["endpoint"], token)

        if isinstance(payload, dict):
            payload = payload.get("items", payload.get("content", []))
        if not isinstance(payload, list):
            return []

        filtered = [
            item
            for item in payload
            if not item.get("deactivated") and self._matches_filters(item, resource.get("filters", {}))
        ]
        return [self._normalize(resource_name, item) for item in filtered]

    async def live_records(self, endpoint, token):
        payload = await self.client.request('GET', endpoint, token)
        rows = payload if isinstance(payload, list) else payload.get('items', payload.get('content', []))
        cache = {}

        async def expand(ref, path, marker):
            if not isinstance(ref, dict) or not ref.get('id') or marker in ref:
                return ref
            key = (path, str(ref['id']))
            if key not in cache:
                cache[key] = await self.client.request('GET', f"{path}/{ref['id']}", token)
            return cache[key]

        for row in rows:
            for field, path, marker in [('product', '/products', 'producttype'), ('objectitem', '/objectitems', 'objectType'), ('owner', '/partners', 'company')]:
                if row.get(field): row[field] = await expand(row[field], path, marker)
            product = row.get('product') or {}
            if product.get('producttype'):
                product['producttype'] = await expand(product['producttype'], '/producttypes', 'name')
            for field, path in [('contractDetails', '/contractdetails'), ('serviceDetails', '/servicedetails')]:
                if field in row:
                    row[field] = [await expand(ref, path, 'attributeName') for ref in row[field]]
        return rows

    @classmethod
    def _normalize(cls, resource_name: str, item: dict[str, Any]) -> dict[str, Any]:
        if resource_name == "useCases":
            details = cls._detail_map(item.get("contractDetails", []))
            product = item.get("product") or {}
            owner = item.get("owner") or {}
            return {
                "id": str(item.get("id", "")),
                "customerId": str(owner.get("id", "")) if owner.get("id") is not None else None,
                "name": item.get("name") or product.get("displayName") or product.get("name") or "",
                "type": (product.get("producttype") or {}).get("name") or "USE_CASE",
                "category": product.get("displayName") or "Service",
                "description": details.get("summary") or product.get("description") or "",
                "status": details.get("serviceStatus") or cls._service_status(item.get("status")),
                "currentProject": details.get("currentProject"),
                "customerAction": details.get("customerAction"),
            }

        if resource_name == "projects":
            details = cls._detail_map(item.get("contractDetails", []))
            parent = item.get("parentcontract") or {}
            owner = item.get("owner") or {}
            responsible = " ".join(
                part for part in [owner.get("firstname"), owner.get("lastname")] if part
            ) or owner.get("company")
            return {
                "id": str(item.get("id", "")),
                "useCaseId": str(parent.get("id", "")),
                "name": item.get("name") or "",
                "status": item.get("status") or "PLANNED",
                "progress": cls._number(details.get("progress"), 0),
                "startDate": item.get("startDate") or details.get("plannedStart") or "",
                "targetDate": item.get("endDate") or details.get("plannedEnd") or "",
                "responsible": details.get("responsible") or responsible,
                **{k: details.get(k, "") for k in ["projectType", "customerContact", "repositoryUrl", "branch"]},
                "projectManager": details.get("projectManager"),
                "developmentTeam": details.get("developmentTeam") or details.get("technicalLead"),
            }

        if resource_name == "epics":
            details = cls._detail_map(item.get("serviceDetails", []))
            contract = item.get("contract") or {}
            return {
                "id": str(item.get("id", "")),
                "projectId": str(contract.get("id", "")),
                "name": details.get("name") or item.get("name") or "",
                "status": details.get("status") or "PLANNED",
                "progress": cls._number(details.get("progress"), 0),
                "targetDate": details.get("endDate") or details.get("plannedDate") or "",
                "startDate": details.get("startDate") or details.get("endDate") or "",
            }

        if resource_name == "milestones":
            details = cls._detail_map(item.get("serviceDetails", []))
            contract = item.get("contract") or {}
            return {
                "id": str(item.get("id", "")),
                "projectId": str(contract.get("id", "")),
                "name": details.get("name") or item.get("name") or "",
                "status": details.get("status") or "PLANNED",
                "targetDate": details.get("endDate") or details.get("plannedDate") or "",
                "startDate": details.get("startDate") or details.get("plannedDate") or "",
                "timelineName": details.get("timelineName") or "Delivery",
                "progress": cls._number(details.get("progress"), 0),
            }

        if resource_name == "kpis":
            details = cls._detail_map(item.get("serviceDetails", []))
            contract = item.get("contract") or {}
            value = details.get("value")
            unit = details.get("unit")
            display_value = f"{value} %" if unit == "PERCENT" and value not in (None, "") else str(value or "")
            return {
                "id": str(item.get("id", "")),
                "projectId": str(contract.get("id", "")),
                "useCaseId": "",
                "name": item.get("name") or "",
                "value": display_value,
                "target": details.get("target"),
                "delta": cls._number(details.get("delta"), 0) if details.get("delta") is not None else None,
                "health": details.get("health") or "neutral",
            }

        return item

    @staticmethod
    def _detail_map(details: list[dict[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for detail in details:
            key = detail.get("attributeName")
            if key:
                result[key] = detail.get("value")
        return result

    @staticmethod
    def _number(value: Any, default: float | int = 0) -> float | int:
        try:
            number = float(value)
            return int(number) if number.is_integer() else number
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _service_status(value: Any) -> str:
        if value in {"RUNNING", "PARTLY_RUNNING", "OFFLINE", "MAINTENANCE"}:
            return str(value)
        return "RUNNING" if value == "ACTIVE" else "OFFLINE"

    @staticmethod
    def _load_json(path: str) -> dict[str, Any]:
        with Path(path).open("r", encoding="utf-8") as handle:
            return json.load(handle)

    @classmethod
    def _matches_filters(cls, item: dict[str, Any], filters: dict[str, Any]) -> bool:
        return all(cls._get_path(item, path) == expected for path, expected in filters.items())

    @staticmethod
    def _get_path(value: Any, path: str) -> Any:
        current = value
        for part in path.split("."):
            if not isinstance(current, dict):
                return None
            current = current.get(part)
        return current

