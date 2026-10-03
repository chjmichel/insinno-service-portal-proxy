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

Each service owns a Contract referencing its SERVICE Product and its parent Use Case Contract. Its ServiceContract references that service Contract and the selected Product ObjectItem. Existing instances directly attached to a Use Case remain readable and receive an own SERVICE Contract when saved. `sourceProductId` in ServiceDetails is retained as legacy provenance; new instances resolve their Product through Contract.product. Ambiguous legacy ObjectItem membership requires explicit provenance; names never determine semantics.

- `GET /api/v1/resources/serviceProducts`: available SERVICE Products and their ObjectItems/attributes.
- `GET /api/v1/resources/services`: resolved Use Case service instances.
- `POST /api/v1/resources/services`: create from `{useCaseId, productId, objectItemId, status, responsible, customerContact, configuration}`.
- Bootstrap includes `services` and `serviceProducts`. KPIs carry `serviceId` to keep service dashboards separate.

Creation validates the parent is a Use Case, the Product is type SERVICE, and the selected ObjectItem belongs to that Product. Configuration keys come from ObjectItem attributes, and reserved provenance fields cannot be overridden. A Product/ObjectItem pair can have multiple named instances per Use Case. Instance editing is supported; service deletion is not exposed. Live creation uses existing `/contracts`, `/servicecontracts` and `/servicedetails` APIs. The Product field belongs to ContractDTO, and ServiceContractDTO receives only its canonical Contract/ObjectItem relationships.

The mock JSON includes three SERVICE Products, three distinct ObjectItems, three generated ServiceContracts and six service-specific KPI samples for Pfefferminzia. Mock persistence remains atomic in a single worker. Live iCore was not contacted during validation.

### Service updates and additional instances

`PUT /api/v1/resources/services/{id}` updates instance name, status, responsible, customer contact and ObjectItem configuration. It preserves Product/ObjectItem/Use Case identity and all unrelated ServiceDetails. Names are saved on the service Contract, with `instanceName` ServiceDetails retained for legacy compatibility. Updates use the existing iCore PUT APIs and reuse detail IDs.

Several instances of the same SERVICE Product/ObjectItem can now belong to one Use Case, for example Technical Operations DEV and Technical Operations PRD. The previous one-instance restriction has been removed. Service deletion remains unavailable.


### Service Contract core data (v0.7.1)

The service create/update body accepts `contractCore: {status, startDate, endDate, ownerId, externalId, notes}` in addition to `name` and operational fields. Contract status is PLANNED / ACTIVE / SUSPENDED / CANCELLED / ENDED; operational status remains a separate service field. End date must follow start date; dates may be null, and ownerId is an existing Partner ID or blank.

For an existing service, the proxy calls `PUT /contracts/{contractId}` with the OpenAPI `{body: ContractDTO}` wrapper, then writes operational details through `/servicecontracts` and `/servicedetails`. Product and Use Case parent relationships stay fixed. New services first create an own SERVICE Contract with `POST /contracts`. Legacy services directly linked to a Use Case are migrated on save; mock migration and update persist atomically. Live operations use several API calls: partial failure reports the saved Contract ID and requires a reload before retrying. Live iCore server validation remains outstanding.

The sample JSON now has three SERVICE Contracts below Use Case 1001 (1601–1603), each owning one of the existing ServiceContracts. ServiceContract IDs and their KPI references are preserved. Deploy frontend and proxy together; read-only loading does not migrate existing data.
