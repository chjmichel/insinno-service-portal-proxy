# insinno-service-portal-proxy

Backend-for-frontend and semantic proxy for the iCore Service Portal.

## Authentication source of truth

Authentication behavior in this repository follows **AUTHENTICATION.md only** for live iCore operation.

- FastAPI does not create its own JWT for live iCore.
- `POST /auth/login` authenticates against iCore and returns the original iCore access token.
- Protected endpoints require `Authorization: Bearer <iCore token>`.
- The token is validated against iCore `GET /auth/userinfo`.
- Successful token validation is cached for 300 seconds.
- Logout invalidates the local validation cache.

When `USE_MOCK_DATA=true`, the proxy provides a complete local authentication flow with development-only mock credentials instead of calling iCore.

## Mandatory iCore connection

For the current development environment both the iCore base URL and login Origin are mandatory:

```env
ICORE_BASE_URL=https://c03-insinno-internal-dev.insinno.de/
ICORE_API_PATH=/api/v2/icore
ICORE_LOGIN_ORIGIN=https://c03-insinno-internal-dev.insinno.de/
```

The live login client always sends:

```http
Origin: https://c03-insinno-internal-dev.insinno.de/
Content-Type: application/x-www-form-urlencoded
```

The effective iCore API base is:

`https://c03-insinno-internal-dev.insinno.de/api/v2/icore`

## Semantic proxy

`config/semantics.json` defines the mapping from iCore resources to stable portal semantics. The React frontend only calls the proxy and therefore does not contain iCore endpoint paths or semantic mappings.

## Run

```bash
cp .env.example .env
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Swagger UI: `http://localhost:8000/docs`

## Mock iCore data and login

For frontend and integration testing the proxy can serve iCore-shaped mock data through the same semantic API used for live iCore.

Enable it in `.env`:

```env
USE_MOCK_DATA=true
REQUIRE_AUTHENTICATION=true
MOCK_DATA_PATH=config/mock/icore-api.json
```

Default development-only credentials:

```text
Username: demo@pfefferminzia.example
Password: demo
```

The mock login endpoint behaves like the live frontend contract:

```http
POST /auth/login
Content-Type: application/json

{
  "username": "demo@pfefferminzia.example",
  "password": "demo"
}
```

It returns the configured mock Bearer token and a mock user. The same token is accepted by `/auth/me`, semantic resources and `/api/v1/portal/bootstrap` while `USE_MOCK_DATA=true`. No iCore authentication request is made in mock mode.

The mock credentials and token can be overridden with:

```env
MOCK_USERNAME=demo@pfefferminzia.example
MOCK_PASSWORD=demo
MOCK_ACCESS_TOKEN=mock-service-portal-token
MOCK_TOKEN_EXPIRES_IN=86400
```

For an authentication-free local setup, `REQUIRE_AUTHENTICATION=false` remains available, but the authenticated mock flow above is preferred because it exercises the frontend login and Bearer-token handling.

The current mock dataset contains:

- Use case: `Pfefferminzia-Sales-tool`
- App: `Makler-Vetriebstools` with DEV/STG/PRD configuration
- Reengineering project with timeline, customer/insinno contacts, repository/branch and test-automation documents
- Project epics, milestones and KPI definitions represented as `ServiceContractDTO`-shaped records

Resources can be queried through:

```text
GET /api/v1/resources/useCases
GET /api/v1/resources/apps
GET /api/v1/resources/projects
GET /api/v1/resources/epics
GET /api/v1/resources/milestones
GET /api/v1/resources/kpis
GET /api/v1/portal/bootstrap
```

The mock file intentionally follows iCore DTO shapes. Semantic differentiation is configured in `config/semantics.json` via `product.producttype.name` and `objectitem.objectType`.
