# Zwind Web Media Projection (ZWMP)

[中文](README-zh.md)

[ZWMP](https://github.com/zwind-app/zwmp) is an open-source toolkit for turning a web listing page into projected WebDAV-style media resources.

The project has two parts:

1. A `.wm` rule specification that describes how a site exposes media items.
2. A reference implementation built with a Python backend and a web frontend that can generate, validate, preview, and save rules.

[Zwind - WebDAV Server & Player](https://apps.apple.com/us/app/zwind-webdav-server-player/id6755239096) is one implementation of this specification on iOS. The app can consume `.wm` marker files and expose projected media directories through WebDAV.

## Quick Start

Create local configuration:

```bash
cp .env.example .env
```

Install backend dependencies:

```bash
cd apps/api
python -m venv .venv
source .venv/bin/activate
pip install -e ../../packages/rule-core -e ".[test,browser]"
python -m playwright install chromium
```

Install frontend dependencies:

```bash
cd apps/web
npm install
```

Start both services from the repository root:

```bash
./scripts/dev.sh
```

Logs are written to:

- `.logs/backend.log`
- `.logs/frontend.log`

Local services:

- Frontend: http://127.0.0.1:5173/
- Backend: http://127.0.0.1:8000/
- API docs: http://127.0.0.1:8000/docs

## Rule Example

```ini
source=https://example.com/videos
candidate_selector=a:has(img)
projection=by-item
media_type=video
max_items=30
```

## Configuration

The backend reads these environment variables:

- `ZWMP_DATA_DIR`: base runtime data directory. Default: `data`.
- `ZWMP_CACHE_DB`: SQLite cache path. Default: `data/cache/zwmp.sqlite3`.
- `ZWMP_RULE_OUTPUT_DIR`: generated rule output directory. Default: `data/generated-rules`.
- `ZWMP_AI_PROVIDER`: OpenAI-compatible API base URL. Default: `none`.
- `ZWMP_AI_API_KEY`: API key for the configured AI provider.
- `ZWMP_AI_MODEL`: AI model name. Default: `gpt-4.1-mini`.
- `ZWMP_MAX_ITEMS`: default maximum listing items. Default: `30`.
- `ZWMP_PROBE_ITEMS`: number of candidate detail pages to probe. Default: `3`.
- `ZWMP_REQUEST_TIMEOUT`: page request timeout in seconds. Default: `12`.
- `ZWMP_MAX_HTML_BYTES`: maximum HTML response size. Default: `2000000`.
- `ZWMP_PROXY_TTL_SECONDS`: intended proxy session TTL. Default: `900`.

If `ZWMP_AI_PROVIDER` or `ZWMP_AI_API_KEY` is not configured, ZWMP uses a deterministic heuristic fallback for rule generation. The web UI shows this fallback explicitly and guides users to configure AI.

Playwright is optional at runtime. When Playwright or its browser runtime is unavailable, the backend falls back to plain HTTP loading. The web UI shows this fallback explicitly because browser-backed loading is the recommended complete mode for JavaScript-heavy sites, network sniffing, and playback interaction.

## Development

Manual backend:

```bash
cd apps/api
source .venv/bin/activate
uvicorn zwmp_api.main:app --reload
```

Manual frontend:

```bash
cd apps/web
npm run dev
```

Tests:

```bash
pytest
npm run build
```

## Current Status

This repository contains an early reference implementation:

- rule parser and formatter
- media URL matcher
- projection JSON model
- FastAPI job API
- browser-capable page loading with HTTP fallback
- heuristic selector generation
- optional AI provider boundary with structured validation
- SQLite cache and generated rule persistence
- React workbench for generation and resource preview

Advanced runtime coverage is being expanded, especially multi-hop detail expansion, episode fan-out, network sniffing, and interactive playback.

