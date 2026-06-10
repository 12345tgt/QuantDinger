# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

QuantDinger is a self-hosted AI quant trading workspace — Flask backend + Vue SPA frontend + PostgreSQL + Redis, orchestrated via Docker Compose. It covers the full lifecycle: AI research → strategy code → backtest → paper/live trading → monitoring.

Version: 3.0.31 (see `VERSION`). License: Apache 2.0.

## Common commands

```bash
# Start all services (build backend from local source, pull frontend from GHCR)
docker compose up -d --build

# Start with local Vue frontend (requires QuantDinger-Vue clone in ./QuantDinger-Vue/)
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build

# View logs
docker compose logs -f backend

# Restart a single service
docker compose restart backend

# Rebuild backend after code changes
docker compose up -d --build backend

# Stop everything
docker compose down

# Backend only (no Docker — needs local PostgreSQL + Redis)
cd backend_api_python && pip install -r requirements.txt && python run.py

# Run tests
cd backend_api_python && pip install pytest && pytest tests/ -v
```

## Architecture

### Service topology (docker-compose.yml)

| Service | Port | Technology | Source |
|---------|------|-----------|--------|
| `frontend` | 8888→80 | Nginx serving Vue SPA | GHCR prebuilt image (`ghcr.io/brokermr810/quantdinger-frontend`) |
| `backend` | 127.0.0.1:5000 | Flask + Gunicorn (1 worker × 8 threads) | Built locally from `backend_api_python/Dockerfile` |
| `postgres` | 127.0.0.1:5432 | PostgreSQL 16 Alpine | Docker Hub (via `IMAGE_PREFIX` mirror) |
| `redis` | 127.0.0.1:6379 | Redis 7 Alpine (128MB LRU) | Docker Hub (via `IMAGE_PREFIX` mirror) |

### Backend layers (inside `backend_api_python/app/`)

1. **Routes** (`routes/`) — 22 Flask Blueprints. Human-facing routes use `HumanBlueprint` (flask-smorest subclass) with JWT auth. Agent-facing routes at `/api/agent/v1` use token-based auth with capability scopes (R/W/B/N/T/C). `routes/__init__.py` auto-discovers all blueprints.

2. **Services** (`services/`) — 80+ modules containing all business logic. Key ones:
   - `strategy.py` — CRUD + config coalescing
   - `strategy_compiler.py` — JSON config → executable Python indicator code
   - `trading_executor.py` — pulls K-lines, computes signals, writes orders to `pending_orders`
   - `backtest.py` — runs indicators against historical K-lines, computes KPIs
   - `fast_analysis.py` — unified AI market analysis (K-line + macro + news + fundamentals → single LLM call)
   - `kline.py` — K-line caching layer delegating to `DataSourceFactory`
   - `llm.py` — multi-provider LLM (OpenRouter, OpenAI, DeepSeek, Gemini, Grok, AtlasCloud, Custom)
   - `experiment/` — AI-driven strategy optimization pipeline (regime detection → backtest batch → scoring → evolution)
   - `grid/` — grid trading bot engine (price ladder → resting orders → fill detection → counter-orders)
   - `live_trading/` — 12 exchange REST clients (Binance, OKX, Bybit, Bitget, Gate, Kraken, HTX, Coinbase, Alpaca, IBKR, MT5)

3. **Data sources** (`data_sources/`) — Factory pattern. Each market has a source class with multi-provider fallback chains:
   - CNStock: Twelve Data → Tencent (free, qt.gtimg.cn) → yfinance → AkShare
   - USStock: yfinance → Finnhub
   - Crypto: CCXT
   - Forex/Futures/MOEX: Twelve Data → yfinance/Tiingo

4. **Config** (`config/`) — Settings via `MetaConfig` metaclass with `@property` reading from env vars. `APIKeys` class reads all third‑party keys. `config_loader.py` maps ~60 env vars to a nested dict (PHP‑compatible shape).

### Database

38 tables in PostgreSQL, idempotent migration via `migrations/init.sql` (all `CREATE TABLE IF NOT EXISTS` + column additions via `DO $$ ... information_schema.columns`). Applied automatically on every backend boot unless `SKIP_AUTO_MIGRATE=true`.

### Frontend

The Vue SPA source is in the **private** `QuantDinger-Vue` repo — not in this tree. GHCR images are built via GitHub Actions on every `v*` tag. To iterate on the UI, clone `QuantDinger-Vue` into `./QuantDinger-Vue/` and use `docker-compose.build.yml` override.

## Key patterns

### Auth dual-track
- **Human users**: JWT HS256 (7-day expiry) with `token_version` for single-device enforcement. Decorators: `@login_required`, `@admin_required`.
- **Agent API**: SHA-256 bearer tokens with 6 capability scopes (R=read, W=write, B=backtest, N=notify, C=credentials, T=trade). Tokens may have market/instrument allowlists and `paper_only` flag. Every call is audited to `qd_agent_audit`.

### Code sandboxing (`utils/safe_exec.py`)
User-submitted indicator Python code runs in a restricted env: whitelisted builtins (no `eval`/`exec`/`open`/`__import__`), safe imports only (numpy, pandas, math, etc.), regex + AST dual check for forbidden patterns (os.system, subprocess, dunders, pandas IO), timeout via SIGALRM/ctypes, memory limit via RLIMIT_AS on Linux.

### Credential encryption
Exchange API keys are stored encrypted in `qd_exchange_credentials`. Fernet key is derived from `SECRET_KEY` via SHA-256 (`utils/credential_crypto.py`). Credentials are redacted on read (only hints like `PK****` returned).

### Market visibility
`ENABLED_MARKETS` CSV whitelist in `backend_api_python/.env` takes precedence over legacy `SHOW_CN_STOCK`/`SHOW_HK_STOCK` flags. Valid values: Crypto, USStock, CNStock, HKStock, Forex, Futures, MOEX. When empty, all known markets default to visible except CNStock (needs `SHOW_CN_STOCK=true`).

### Caching
Two-tier: Redis when `CACHE_ENABLED=true` (default in Docker), falling back silently to in‑memory `MemoryCache` when Redis is unreachable. `data_providers/` uses stale‑while‑revalidate with request coalescing.

## Configuration files

- **`backend_api_python/.env`** — Backend runtime config (auth, DB, LLM keys, data source keys, proxy, market visibility). Mounted into container at `/app/.env`.
- **Project-root `.env`** — Docker Compose overrides (ports, `IMAGE_PREFIX`, `BUILD_REGION`, image tags).
- **`IMAGE_PREFIX`** — Prepended to all base image names. Set to `docker.m.daocloud.io/library/` for China Docker Hub mirror. Backend Dockerfile defaults to `BUILD_REGION=cn` (Aliyun apt/PyPI mirrors).

## Git workflow (this fork)

- `main` — mirrors `upstream/main` (original author), used only for syncing
- `stable` — this fork's production‑ready code
- `dev` — active development branch; merge into `stable` when features are stable

Sync upstream: `git checkout main && git fetch upstream && git merge upstream/main`, then `git checkout dev && git merge main`.
