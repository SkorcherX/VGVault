# VGVault — Project Plan

Self-hosted, multi-user video game collection tracker with price tracking and analytics. Ships as a single Docker container for unRAID.

## Decisions

| Topic | Decision |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 + Alembic, APScheduler |
| Frontend | React + Vite + TypeScript, TanStack Query/Table, ECharts (or Recharts) |
| Database | SQLite (WAL) in `/config` by default; optional Postgres via `DATABASE_URL` |
| Scope | Games, consoles, PC big boxes, controllers, accessories |
| Users | Multi-user; each user owns their own collection. Admin role has elevated rights |
| Price source | PriceCharting.com via polite scraping, behind a pluggable provider interface |
| Import | Deferred — "Import collection" feature to be designed later (users track differently) |

## Architecture

```
┌──────────────── vgvault container ────────────────┐
│  FastAPI (uvicorn)                                │
│   ├─ /api/*        REST API (JWT/session auth)    │
│   ├─ /*            React SPA static build         │
│   └─ Scheduler     APScheduler (cron from DB)     │
│        └─ Price worker → PriceProvider            │
│              └─ PriceChartingScraper (httpx)      │
│                   (optional Playwright mode)      │
│  /config: vgvault.db, images/, snapshots/, logs/  │
└───────────────────────────────────────────────────┘
```

## Users & roles

- **Admin**: manage users (create/disable/reset password), app settings, scrape schedule and rate limits, scraper health, edit shared catalog (platforms/products), trigger global refresh, backups.
- **User**: manage own collection & wishlist, link items to catalog products, view own analytics, request price refresh on own items (rate-limited).
- First run: setup wizard creates the admin account. Optional open registration toggle (off by default).
- Auth: username/password (argon2 hashing), HTTP-only session cookie. Designed to sit behind a reverse proxy (SWAG / NPM / Traefik).
- Price data and catalog are **shared** across users (one scrape serves everyone); collections are **private** per user. Admin can optionally see aggregate stats.

## Data model

**Catalog (shared)**
- `platforms`: name, slug, brand (Nintendo, Sony, Sega, Microsoft, Atari, NEC, SNK, PC, …), generation/era, media type (cartridge / disc / card / floppy / digital / mixed), handheld flag, region, release year, PriceCharting console slug. Seeded with ~100 platforms.
- `products`: title, platform_id, **category** (game / console / pc_big_box / controller / accessory / other), region, genre, release date, UPC, PriceCharting product ID + URL, cover image path.

**Per user**
- `users`: username, email, password hash, role (admin/user), active, created.
- `collection_items`: user_id, product_id, status (owned / wishlist / sold), condition (loose / cib / new / graded / box_only / manual_only), component flags (has_item, has_box, has_manual, has_inserts), grade (optional), quantity, purchase price, purchase date, sold price/date, location, tags, notes.

**Pricing (shared, append-only)**
- `price_snapshots`: product_id, captured_at, loose, cib, new, graded, box_only, manual_only, currency, source.
- `scrape_runs` / `scrape_errors`: timing, counts, status, HTTP code, parse failures, stored HTML snapshot path.
- `settings`: key/value (cron, rate limit, jitter, scraper mode, notification targets).

Item valuation = latest snapshot price matching the item's condition × quantity. Analytics filters (brand, era, media, category) derive from `platforms`/`products`.

## Price engine (PriceCharting)

- **Provider interface**: `search(query, platform) -> candidates`, `fetch(product) -> PriceData`. PriceCharting scraper is the first implementation; a CSV price-guide provider (paid subscription) can be added later.
- **Linking**: user searches → app queries PriceCharting search → user confirms the match → product ID/URL stored. No silent fuzzy matching.
- **Scope**: only products referenced by any user's collection or wishlist are scraped.
- **Politeness**: single worker, 3–10s randomized delay, real User-Agent, exponential backoff on 429/403/5xx, circuit breaker that pauses the run after repeated blocks.
- **Parsing**: select price cells by element ID (e.g. `#used_price`, `#complete_price`, `#new_price`, graded/box/manual rows), not position. Failed pages saved to `/config/snapshots/` for selector debugging. Parser covered by fixture-based tests.
- **Cadence**: cron expression configurable by admin (default weekly, e.g. `0 3 * * 0`). Manual "refresh now" per item (user) or global (admin). Optional tiering: high-value items refreshed more often.
- **Health page (admin)**: last run, success/failure counts, recent errors, blocked status.
- **Fallback**: optional `SCRAPER_MODE=playwright` for Cloudflare challenges (separate larger image tag).
- **Note**: PriceCharting's ToS restricts automated access. Keep volume minimal and personal-scale.

## Features

### Collection
- Table + grid (cover art) views, per-user.
- Filters: category, platform, brand, era/generation, media type, condition, region, status, tags, price range, genre.
- Sorting, saved filter presets, bulk edit, quantity handling.
- Wishlist with target price.

### Analytics (per user, filter-aware)
- KPIs: total value, cost basis, unrealized gain/loss, item count.
- Value over time (daily rollups from snapshots).
- Breakdown by category / platform / brand / era / media type / condition.
- Biggest movers: 7d / 30d / 90d / 1y, $ and %, with min-value threshold.
- Per-item price history chart (all conditions) with purchase price marker.
- Top N most valuable items.

### Notifications (phase 4)
- Price moved > X%, wishlist item below target. Via Apprise (Discord, ntfy, email, …).

## Docker / unRAID

- Multi-stage build: `node:20` builds SPA → `python:3.12-slim` runtime.
- Image published to GHCR via GitHub Actions (`linux/amd64`, `linux/arm64`).
- Volume: `/config` → `/mnt/user/appdata/vgvault`.
- Env: `PUID`, `PGID`, `TZ`, `PORT=8080`, `DATABASE_URL` (optional), `SCRAPER_MODE=http|playwright`, `SECRET_KEY` (auto-generated if absent).
- `/api/health` healthcheck.
- unRAID template at `unraid/vgvault.xml`.
- Alembic migrations run automatically on startup.

## Repo layout

```
backend/
  app/
    api/          routers (auth, users, collection, catalog, prices, analytics, admin)
    core/         config, security, db
    models/       SQLAlchemy models
    schemas/      Pydantic schemas
    services/     valuation, analytics
    pricing/      provider interface, pricecharting scraper
    scheduler/    APScheduler setup, jobs
    seed/         platforms.yaml
  alembic/
  tests/          incl. HTML fixtures for parser
frontend/
  src/ (pages, components, api client, charts)
docker/
  Dockerfile, entrypoint.sh
unraid/vgvault.xml
.github/workflows/  (lint, test, build & push image)
docker-compose.yml  (local dev)
```

## Roadmap

1. **Foundation**: scaffold, Docker, auth + roles + setup wizard, platform seed, catalog & collection CRUD, filters.
2. **Price engine**: PriceCharting search/link, scraper, snapshots, scheduler, admin health page.
3. **Analytics**: dashboard, breakdowns, movers, item history.
4. **Polish**: wishlist targets, notifications, backups/export, barcode (UPC) lookup, unRAID CA submission.
5. **Import collection** (to be designed): support multiple source formats (PriceCharting export, spreadsheets, others) with a mapping/review step.

## Open questions

- Should users be able to see each other's collections (opt-in sharing)?

## Resolved

- Currency: USD only (PriceCharting's currency).
- Regions: PAL and Japanese releases are separate platforms, each mapped to its PriceCharting console.
