import time
from typing import Any

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .icore_client import ICoreClient, ICoreError
from .settings import Settings, get_settings

security = HTTPBearer(auto_error=False)
_token_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def get_icore_client(settings: Settings = Depends(get_settings)) -> ICoreClient:
    return ICoreClient(settings)


async def require_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    settings: Settings = Depends(get_settings),
    client: ICoreClient = Depends(get_icore_client),
) -> dict[str, Any]:
    if not settings.require_authentication:
        return {"username": "development", "_token": ""}

    token = None
    if credentials and credentials.scheme.lower() == "bearer":
        token = credentials.credentials
    if not token:
        token = request.cookies.get(settings.auth_cookie_name)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")

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
