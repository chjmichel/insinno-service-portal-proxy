# insinno-service-portal-proxy

Backend-for-frontend and semantic proxy for the iCore Service Portal.

## Responsibilities
- Own the configurable iCore connection.
- Authenticate against iCore.
- Keep the original iCore token server-side in an HttpOnly cookie.
- Validate the iCore token with a short TTL cache.
- Convert iCore payloads into stable portal semantics.
- Expose semantic portal services to the React frontend.
- Keep iCore endpoint URLs and mapping rules out of the frontend.

## Architecture

```
React frontend
  |
  | /auth/* + /api/v1/* (HttpOnly session cookie)
  v
Service Portal Proxy (FastAPI)
  |
  | semantic mapping + iCore Bearer token
  v
iCore /api/v2/icore
```

No second JWT is minted. The token remains the token issued by iCore, but JavaScript does not receive or store it.

## Configuration

Copy `.env.example` to `.env`.

Important settings:
- `ICORE_BASE_URL`: environment-specific iCore host.
- `ICORE_API_PATH`: normally `/api/v2/icore`.
- `ICORE_LOGIN_ORIGIN`: required Origin header for iCore login.
- `ICORE_USERINFO_PATH`: configurable because deployed iCore versions may use `/loggedUser` or `/auth/userinfo`.
- `AUTH_COOKIE_SECURE=true` in production.
- `CORS_ORIGINS`: frontend origins allowed to send credentials.

## Semantic configuration

`config/semantics.json` is the semantic adapter configuration. It defines resource source paths, collection paths, field mappings, and UI object schemas.

Changing iCore field/path mappings therefore does not require changes in React components.

## Run

```bash
cp .env.example .env
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Swagger UI: `http://localhost:8000/docs`
