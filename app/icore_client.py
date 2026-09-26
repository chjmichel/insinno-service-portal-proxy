from typing import Any

import httpx

from .settings import Settings


class ICoreError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


class ICoreClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def login(
        self,
        username: str,
        password: str,
        app_id: str | None = None,
        client_id: str | None = None,
    ) -> dict[str, Any]:
        data: dict[str, str] = {"username": username, "password": password}
        if app_id:
            data["appId"] = app_id
        if client_id:
            data["clientId"] = client_id

        headers = {
            "Origin": self.settings.icore_login_origin,
            "Content-Type": "application/x-www-form-urlencoded",
        }

        response = await self._request(
            "POST",
            "/login",
            headers=headers,
            data=data,
            include_api_path=True,
        )
        return self._json(response)

    async def get_current_user(self, token: str) -> dict[str, Any]:
        response = await self._request(
            "GET",
            "/loggedUser",
            headers=self._bearer(token),
            include_api_path=True,
        )
        return self._json(response)

    async def request(
        self,
        method: str,
        path: str,
        token: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        response = await self._request(
            method,
            path,
            headers=self._bearer(token),
            params=params,
            include_api_path=True,
        )
        return self._json(response)

    async def _request(self, method: str, path: str, include_api_path: bool, **kwargs: Any) -> httpx.Response:
        base = self.settings.icore_api_url if include_api_path else self.settings.icore_base_url.rstrip("/")
        url = f"{base}/{path.lstrip('/')}"
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.icore_timeout_seconds,
                verify=self.settings.icore_verify_ssl,
            ) as client:
                response = await client.request(method, url, **kwargs)
        except httpx.RequestError as exc:
            raise ICoreError(f"iCore is not reachable: {exc}") from exc

        if response.status_code == 401:
            raise ICoreError("Unauthorized", 401)
        if response.status_code >= 400:
            raise ICoreError(f"iCore returned HTTP {response.status_code}", response.status_code)
        return response

    @staticmethod
    def _bearer(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    @staticmethod
    def _json(response: httpx.Response) -> Any:
        if not response.content:
            return {}
        return response.json()
