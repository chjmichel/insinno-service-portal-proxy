from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .auth import get_icore_client, invalidate_token, require_user
from .icore_client import ICoreClient, ICoreError
from .models import LoginRequest, LoginResponse, SemanticBootstrap
from .semantics import SemanticService
from .settings import Settings, get_settings

app = FastAPI(title="insinno Service Portal Proxy", version="0.6.2")

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def semantic_service(
    settings: Settings = Depends(get_settings),
    client: ICoreClient = Depends(get_icore_client),
) -> SemanticService:
    return SemanticService(
        settings.semantics_config_path,
        client,
        use_mock_data=settings.use_mock_data,
        mock_data_path=settings.mock_data_path,
    )


@app.get("/health")
async def health() -> dict[str, str | bool]:
    return {
        "status": "ok",
        "mockData": settings.use_mock_data,
    }


@app.post("/auth/login", response_model=LoginResponse)
async def login(
    request: LoginRequest,
    settings: Settings = Depends(get_settings),
    client: ICoreClient = Depends(get_icore_client),
) -> LoginResponse:
    # In mock mode the frontend receives a token immediately.
    # Username/password are deliberately ignored and no external iCore call is made.
    if settings.use_mock_data:
        return LoginResponse(
            access_token=settings.mock_access_token,
            expires_in=settings.mock_token_expires_in,
            user=settings.mock_user,
        )

    try:
        payload = await client.login(
            request.username,
            request.password,
            request.app_id,
            request.client_id,
        )
        token = payload.get("accessToken") or payload.get("access_token") or payload.get("token")
        if not token:
            raise HTTPException(status_code=502, detail="iCore login response contains no access token")

        user = await client.get_current_user(token)
        return LoginResponse(
            access_token=token,
            expires_in=payload.get("expiresIn") or payload.get("expires_in"),
            user=user,
        )
    except ICoreError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.get("/auth/me")
async def me(user: dict = Depends(require_user)) -> dict:
    return {key: value for key, value in user.items() if key != "_token"}


@app.post("/auth/logout")
async def logout(user: dict = Depends(require_user)) -> dict[str, bool]:
    token = user.get("_token")
    if token:
        invalidate_token(token)
    return {"success": True}


@app.get("/api/v1/semantics")
async def semantics(
    _: dict = Depends(require_user),
    service: SemanticService = Depends(semantic_service),
) -> dict:
    return service.model


@app.get("/api/v1/resources/{resource_name}")
async def resource(
    resource_name: str,
    user: dict = Depends(require_user),
    service: SemanticService = Depends(semantic_service),
) -> list[dict]:
    try:
        return await service.load_resource(resource_name, user.get("_token", ""))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown semantic resource: {resource_name}") from exc
    except ICoreError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.get("/api/v1/portal/bootstrap", response_model=SemanticBootstrap)
async def bootstrap(
    user: dict = Depends(require_user),
    service: SemanticService = Depends(semantic_service),
) -> SemanticBootstrap:
    token = user.get("_token", "")
    try:
        use_cases = await service.load_resource("useCases", token)
        projects = await service.load_resource("projects", token)
        epics = await service.load_resource("epics", token)
        kpis = await service.load_resource("kpis", token)

        # KPI records are attached to projects in iCore. Resolve them back to
        # their parent use case for the frontend's operational KPI views.
        project_to_use_case = {
            project.get("id"): project.get("useCaseId")
            for project in projects
            if project.get("id") and project.get("useCaseId")
        }
        for kpi in kpis:
            if not kpi.get("useCaseId") and kpi.get("projectId"):
                kpi["useCaseId"] = project_to_use_case.get(kpi["projectId"], "")
    except ICoreError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return SemanticBootstrap(
        semanticModel=service.model,
        useCases=use_cases,
        projects=projects,
        epics=epics,
        kpis=kpis,
    )
