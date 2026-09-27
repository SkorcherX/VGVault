# VGVault

Self-hosted video game collection tracker with price tracking and analytics. Multi-user, runs as a single Docker container (built for unRAID).

See [docs/PLAN.md](docs/PLAN.md) for the full design and roadmap.

**Status:** Phase 1 (foundation) — accounts & roles, platform catalog, collection CRUD with filters. PriceCharting price tracking is phase 2.

## Run with Docker

```bash
docker compose up -d
```

Open http://localhost:8080 and create the admin account.

### unRAID

Add the template URL in *Docker → Template repositories*:
`https://raw.githubusercontent.com/SkorcherX/VGVault/main/unraid/vgvault.xml`

| Variable | Default | Notes |
|---|---|---|
| `PUID` / `PGID` | `99` / `100` | File ownership for `/config` |
| `TZ` | `UTC` | |
| `PORT` | `8080` | |
| `SECRET_KEY` | auto | Generated into `/config/secret.key` if unset |
| `ALLOW_REGISTRATION` | `false` | Self-signup from the login page |
| `COOKIE_SECURE` | `false` | Set `true` behind HTTPS |
| `DATABASE_URL` | SQLite in `/config` | Optional Postgres |

## Development

Backend (Python 3.12+):

```bash
cd backend
python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt   # or .venv/bin on Linux/macOS
CONFIG_DIR=.devconfig .venv/Scripts/uvicorn app.main:app --reload --port 8000
.venv/Scripts/pytest
```

Frontend (Node 20+), proxies `/api` to port 8000:

```bash
cd frontend
npm install
npm run dev
```

New migration after changing models:

```bash
cd backend
CONFIG_DIR=.devconfig .venv/Scripts/alembic revision --autogenerate -m "describe change"
```
