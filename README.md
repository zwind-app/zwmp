# Zwind Web Media Projection (ZWMP)

[ZWMP](https://github.com/zwind-app/zwmp) is an open-source toolkit for turning a web listing page into projected WebDAV-style media resources.

The project has two parts:

1. A `.wm` rule specification that describes how a site exposes media items.
2. A reference implementation built with a Python backend and a web frontend that can generate, validate, preview, and save rules.

[Zwind - WebDAV Server & Player](https://apps.apple.com/us/app/zwind-webdav-server-player/id6755239096) is one implementation of this specification on iOS. The app can consume `.wm` marker files and expose projected media directories through WebDAV.

## Rule Example

```ini
source=https://example.com/videos
candidate_selector=a:has(img)
projection=by-item
media_type=video
max_items=30
```

## Local Development

Backend:

```bash
cd apps/api
python -m venv .venv
source .venv/bin/activate
pip install -e ../../packages/rule-core -e ".[test,browser]"
python -m playwright install chromium
uvicorn zwmp_api.main:app --reload
```

Frontend:

```bash
cd apps/web
npm install
npm run dev
```

Tests:

```bash
pytest
```

Local services:
- frontend: http://127.0.0.1:5173/
- backend: http://127.0.0.1:8000/
- API doc: http://127.0.0.1:8000/docs

Generated rules are saved under `data/generated-rules` by default. Set `ZWMP_RULE_OUTPUT_DIR` to use a different directory.

没有配置 ZWMP_AI_PROVIDER / ZWMP_AI_API_KEY 时会自动使用 deterministic heuristic fallback。Playwright 也是可选路径，未安装浏览器 runtime 时后端会 fallback 到普通 HTTP 加载。

## Current Status

This repository contains the first implementation pass:

- rule parser and formatter
- media URL matcher
- projection JSON model
- FastAPI job API
- browser-capable page loading with urllib fallback
- heuristic selector generation
- SQLite cache and generated rule persistence
- React workbench for generation and preview

AI analysis is represented by a provider-ready boundary and currently falls back to deterministic heuristics when no provider is configured.


