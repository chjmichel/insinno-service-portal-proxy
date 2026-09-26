import json
from pathlib import Path
from typing import Any

from .icore_client import ICoreClient


class SemanticService:
    """Maps generic iCore resources to stable portal semantics.

    In mock mode the same semantic filtering is applied to iCore-shaped JSON
    fixtures, so frontend behavior stays identical when switching to live iCore.
    """

    def __init__(
        self,
        config_path: str,
        client: ICoreClient,
        *,
        use_mock_data: bool = False,
        mock_data_path: str = "config/mock/icore-api.json",
    ) -> None:
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
            payload = await self.client.request(
                source.get("method", "GET"),
                source["endpoint"],
                token,
            )

        if isinstance(payload, dict):
            payload = payload.get("items", payload.get("content", []))
        if not isinstance(payload, list):
            return []

        return [
            item
            for item in payload
            if self._matches_filters(item, resource.get("filters", {}))
        ]

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
