import json
from pathlib import Path
from typing import Any

from .icore_client import ICoreClient


def get_path(value: Any, path: str | None) -> Any:
    if not path:
        return value
    current = value
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


class SemanticService:
    def __init__(self, config_path: str, client: ICoreClient):
        self.client = client
        self.config = json.loads(Path(config_path).read_text(encoding="utf-8"))

    @property
    def model(self) -> dict[str, Any]:
        return {
            "version": self.config.get("version", 1),
            "objectSchemas": self.config.get("schemas", []),
        }

    async def load_resource(self, resource_name: str, token: str) -> list[dict[str, Any]]:
        resource = self.config["resources"].get(resource_name)
        if not resource:
            raise KeyError(resource_name)

        source = resource["source"]
        payload = await self.client.request(
            source.get("method", "GET"),
            source["path"],
            token,
        )
        rows = get_path(payload, source.get("collectionPath"))
        if rows is None:
            rows = payload
        if not isinstance(rows, list):
            rows = [rows]

        mapping = resource.get("map", {})
        return [
            {target: get_path(row, source_path) for target, source_path in mapping.items()}
            for row in rows
            if isinstance(row, dict)
        ]
