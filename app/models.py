from typing import Any
from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str
    app_id: str | None = None
    client_id: str | None = None


class LoginResponse(BaseModel):
    token_type: str = "cookie"
    expires_in: int | None = None
    user: dict[str, Any] | None = None


class SemanticBootstrap(BaseModel):
    semanticModel: dict[str, Any]
    useCases: list[dict[str, Any]]
    projects: list[dict[str, Any]]
    epics: list[dict[str, Any]]
    kpis: list[dict[str, Any]]
