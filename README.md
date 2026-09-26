# insinno-service-portal-proxy

Backend-for-frontend / semantic proxy for the iCore Service Portal.

## Responsibilities
- Own the configurable iCore connection.
- Authenticate against iCore and pass through the iCore access token.
- Validate bearer tokens against iCore with a short TTL cache.
- Convert iCore payloads into stable portal semantics.
- Expose semantic portal services to the React frontend.
- Keep iCore endpoint URLs and mapping rules out of the frontend.

## Architecture

```
React frontend
  |
  | /auth/* + /api/v1/*
  v
Service Portal Proxy (FastAPI)
  |
  | semantic mapping + bearer token
  v
iCore /api/v2/icore
```

The frontend URL for this proxy is runtime-configurable in the frontend `public/config.json`.
The iCore base URL and login origin are environment-configurable in this service.

## Run

```bash
cp .env.example .env
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Swagger UI: `http://localhost:8000/docs`

## Semantic configuration

`config/semantics.json` defines:
- semantic resource names
- iCore source paths
- response collection paths
- field mappings

No iCore-specific path is hardcoded into frontend components.
