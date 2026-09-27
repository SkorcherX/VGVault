# VGVault

Self-hosted video game collection tracker with price tracking and analytics. Multi-user, runs as a single Docker container (built for unRAID).

See [docs/PLAN.md](docs/PLAN.md) for the full design and roadmap.

**Status:** Phase 4 complete.
- Phase 1: accounts & roles, platform catalog, collection with filters.
- Phase 2: PriceCharting search/import/link, scheduled polite price updates, monthly history backfill, item values, admin price-tracking page.
- Phase 3: analytics dashboard — value/cost KPIs, value over time, value by brand/platform/era/media/category/condition/genre (click to drill down), most valuable items, biggest movers over 7d/30d/90d/1y.
- Phase 4: price alerts (Apprise), scheduled backups & CSV/JSON export, UPC barcode scanning, CSV import with PriceCharting auto-link, sort by market value.

## Price alerts

Each user can add [Apprise URLs](https://github.com/caronc/apprise/wiki#notification-services) under *Account* (Discord, ntfy, email, Telegram, ...). After each scheduled price update they get one message listing owned items that moved by a chosen percentage, and wishlist items that dropped to their target price.

## Backups

Admins can schedule SQLite backups (default daily 02:30, keep 14) under *Backups*; files go to `/config/backups`. To restore, stop the container, replace `/config/vgvault.db` with a backup file (renamed to `vgvault.db`), delete any `vgvault.db-wal` / `vgvault.db-shm`, and start it again.

## Importing a collection

*Collection → Import* accepts a CSV with a header row. Columns are matched by name (VGVault's own export round-trips), every row is checked before anything is saved, and afterwards *Auto-link* matches the new items to PriceCharting in the background. It only links a game when there's exactly one match on the same platform with the same title (ignoring word order); the rest are listed so you can link them by hand.

## Barcode scanning

*Add item → Scan* uses the device camera to read a UPC. Browsers only allow camera access over HTTPS (or on localhost), so put VGVault behind your reverse proxy with TLS to scan from a phone. Typing the UPC into the search box works everywhere.

## Regions and currency

- All prices are in **USD**, as PriceCharting reports them, including for PAL and Japanese games.
- **PAL and Japanese releases are separate platforms** (e.g. *Nintendo 64 (PAL)*, *Sega Saturn (JP)*), each mapped to its own PriceCharting console, because their prices differ a lot from the North American versions. Famicom, Super Famicom and PC Engine are the Japanese counterparts of NES, SNES and TurboGrafx-16.
- Filter and break down the collection and dashboard by region (NTSC-U / PAL / NTSC-J).
- Imports read region from a Region column or from words in the platform name ("N64 PAL", "Japanese Saturn"); European and Japanese collectors can set a default region for rows that don't say.

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
