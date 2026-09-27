# VGVault

Self-hosted video game collection tracker with price tracking and analytics. Multi-user, runs as a single Docker container (built for unRAID).

See [docs/PLAN.md](docs/PLAN.md) for the full design and roadmap.

**Status:** Phase 2 complete.
- Phase 1: accounts & roles, platform catalog, collection with filters.
- Phase 2: PriceCharting search/import/link, scheduled polite price updates, monthly history backfill, item values, admin price-tracking page.
- Next: phase 3 analytics dashboard.

## Price tracking notes

- Only products that are in someone's collection or wishlist are fetched, one request at a time with a random 4–10s delay (configurable in *Price tracking*).
- The schedule uses standard cron syntax in the container's `TZ` (default weekly, Sunday 03:00).
- Linking or importing a game backfills its monthly price history from PriceCharting's charts, so trends are available immediately.
- If the site blocks requests (HTTP 403/429 or a bot challenge), the run stops and the error shows on the admin page. Pages that fail to parse are saved to `/config/snapshots/` for debugging.
- PriceCharting's terms restrict automated access; keep the volume personal-scale.

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
