from typing import Any
from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str
    app_id: str | None = None
    client_id: str | None = None


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int | None = None
    user: dict[str, Any] | None = None


class SemanticBootstrap(BaseModel):
    semanticModel: dict[str, Any]
    useCases: list[dict[str, Any]]
    projects: list[dict[str, Any]]
    epics: list[dict[str, Any]]
    kpis: list[dict[str, Any]]

    milestones: list[dict[str, Any]] = Field(default_factory=list)
    services: list[dict[str, Any]] = Field(default_factory=list)
    serviceProducts: list[dict[str, Any]] = Field(default_factory=list)
