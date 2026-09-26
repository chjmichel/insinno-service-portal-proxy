import time
from typing import Any

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .icore_client import ICoreClient, ICoreError
from .settings import Settings, get_settings

security = HTTPBearer(auto_error=False)
_token_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def get_icore_client(settings: Settings = Depends(get_settings)) -> ICoreClient:
    return ICoreClient(settings)


async def require_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    settings: Settings = Depends(get_settings),
    client: ICoreClient = Depends(get_icore_client),
) -> dict[str, Any]:
    if not settings.require_authentication:
        return {"username": "development", "_token": ""}

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Bearer token required")

    token = credentials.credentials

    # Full local mock authentication: keep auth enabled, but validate the
    # development token locally instead of calling iCore /auth/userinfo.
    if settings.use_mock_data:
        if token != settings.mock_access_token:
            raise HTTPException(status_code=401, detail="Unauthorized")
        return {**settings.mock_user, "_token": token}

    now = time.monotonic()
    cached = _token_cache.get(token)
    if cached and cached[0] > now:
        return {**cached[1], "_token": token}

    try:
        user = await client.get_current_user(token)
    except ICoreError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    _token_cache[token] = (now + settings.token_cache_seconds, user)
    return {**user, "_token": token}


def invalidate_token(token: str) -> None:
    _token_cache.pop(token, None)
