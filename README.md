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

When `USE_MOCK_DATA=true`, the proxy skips credential validation completely. `POST /auth/login` immediately returns a local mock token and mock user without calling iCore.

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

In mock mode, `POST /auth/login` ignores the submitted username and password and immediately returns the configured mock Bearer token and a local mock user.

The returned token is accepted by `/auth/me`, semantic resources and `/api/v1/portal/bootstrap` while `USE_MOCK_DATA=true`. No iCore authentication request is made in mock mode.

The mock token can be configured with:

```env
MOCK_ACCESS_TOKEN=mock-service-portal-token
MOCK_TOKEN_EXPIRES_IN=86400
```

For an authentication-free local setup, `REQUIRE_AUTHENTICATION=false` remains available. With `REQUIRE_AUTHENTICATION=true`, mock mode still exercises frontend token handling while skipping credential validation.

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


## Editable portal resources

The existing semantic resource routes also accept writes:

- `POST /api/v1/resources/useCases` — name, customerId (existing Partner ID), description, service status.
- `POST /api/v1/resources/projects` / `PUT /api/v1/resources/projects/{id}` — useCaseId, name, projectType, status, progress, startDate, targetDate, responsible, projectManager, customerContact, developmentTeam, repositoryUrl, branch.
- `POST /api/v1/resources/epics` / `PUT` / `DELETE /api/v1/resources/epics/{id}`.
- `POST /api/v1/resources/milestones` / `PUT` / `DELETE /api/v1/resources/milestones/{id}` — timeline entries.

Epic and timeline bodies contain name, projectId, status, progress, startDate, targetDate and timelineName (default Delivery). Dates use YYYY-MM-DD; progress must be 0–100. Updates send a complete editable form. Parent IDs must reference the correct semantic resource. Writes use the same authentication dependencies as reads.

`GET /api/v1/portal/bootstrap` now includes `milestones`. Multiple named timelines and projects use one shared date scale in the frontend. The mock fixture includes two projects and Delivery / Quality assurance timelines.

In mock mode changes persist atomically to `MOCK_DATA_PATH`. Run a single Uvicorn worker for JSON persistence; concurrent requests within that process are serialized. Keep a copy of the fixture to reset test data. The file must be writable.

Live writes use existing iCore `/contracts`, `/contractdetails`, `/servicecontracts` and `/servicedetails` endpoints. Contract writes use the OpenAPI `{body: ...}` wrapper and relationships use `{id: "..."}` references. Existing Product/ObjectItem definitions are reused; an existing instance of the semantic type is needed to select its definition. ServiceContract names are stored in a ServiceDetail because ServiceContractDTO has no name field. Relation references returned by iCore are expanded for semantic reads. Record/detail saves are multiple upstream calls; a detail failure reports the saved record ID so users can reload before retrying. No live iCore server was used during validation.

Install and run:

```powershell
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8010 --reload
```

Tests (isolated temporary mock file): `python -m pip install pytest`, then `python -m pytest -q`.

## Services created from Products (v0.7.0)

A Use Case can contain several ServiceContracts. Each service is created from a separate Product with `producttype.name = SERVICE`; the Product's ObjectItem defines its semantic role and configurable attributes. The demo catalog contains:

| Product | ObjectItem.objectType |
| --- | --- |
| Technical Operations | TECHNICAL_OPERATIONS |
| Sales Processes | SALES_PROCESSES |
| Correction Services | CORRECTION_SERVICES |

Canonical instance links remain `ServiceContract.contract → Use Case Contract` and `ServiceContract.objectitem → selected Product ObjectItem`. `ServiceContractDTO` has no Product field, so new instances persist the Product ID in a ServiceDetail named `sourceProductId`. Native iCore-generated instances without that field resolve through unique SERVICE Product/ObjectItem membership. Ambiguous membership requires explicit provenance; names never determine semantics.

- `GET /api/v1/resources/serviceProducts`: available SERVICE Products and their ObjectItems/attributes.
- `GET /api/v1/resources/services`: resolved Use Case service instances.
- `POST /api/v1/resources/services`: create from `{useCaseId, productId, objectItemId, status, responsible, customerContact, configuration}`.
- Bootstrap includes `services` and `serviceProducts`. KPIs carry `serviceId` to keep service dashboards separate.

Creation validates the parent is a Use Case, the Product is type SERVICE, and the selected ObjectItem belongs to that Product. Configuration keys come from ObjectItem attributes, and reserved provenance fields cannot be overridden. A Product/ObjectItem pair can be configured once per Use Case. Service editing/deletion is not exposed in this version. Live creation uses existing `/servicecontracts` and `/servicedetails` APIs; no Product field or new DTO is sent upstream.

The mock JSON includes three SERVICE Products, three distinct ObjectItems, three generated ServiceContracts and six service-specific KPI samples for Pfefferminzia. Mock persistence remains atomic in a single worker. Live iCore was not contacted during validation.
