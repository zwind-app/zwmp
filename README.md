# Zwind Web Media Projection (ZWMP)

English | [中文](#中文)

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
npm run build
```

Local services:

- Frontend: http://127.0.0.1:5173/
- Backend: http://127.0.0.1:8000/
- API docs: http://127.0.0.1:8000/docs

## Configuration

The backend reads these environment variables:

- `ZWMP_DATA_DIR`: base runtime data directory. Default: `data`.
- `ZWMP_CACHE_DB`: SQLite cache path. Default: `data/cache/zwmp.sqlite3`.
- `ZWMP_RULE_OUTPUT_DIR`: generated rule output directory. Default: `data/generated-rules`.
- `ZWMP_AI_PROVIDER`: OpenAI-compatible API base URL. Default: `none`.
- `ZWMP_AI_API_KEY`: API key for the configured AI provider.
- `ZWMP_AI_MODEL`: AI model name. Default: `gpt-4.1-mini`.

If `ZWMP_AI_PROVIDER` or `ZWMP_AI_API_KEY` is not configured, ZWMP uses a deterministic heuristic fallback for rule generation.

Playwright is optional at runtime. When Playwright or its browser runtime is unavailable, the backend falls back to plain HTTP loading. Browser-backed loading is still recommended for JavaScript-heavy sites.

## Current Status

This repository contains an early reference implementation:

- rule parser and formatter
- media URL matcher
- projection JSON model
- FastAPI job API
- browser-capable page loading with HTTP fallback
- heuristic selector generation
- optional AI provider boundary
- SQLite cache and generated rule persistence
- React workbench for generation and preview

Some advanced rule fields are parsed and preserved but still need stronger runtime coverage, especially multi-hop detail expansion and interactive playback sniffing.

---

## 中文

[ZWMP](https://github.com/zwind-app/zwmp) 是一个开源工具，用于把网页列表页投影成类似 WebDAV 目录的媒体资源视图。

项目包含两部分：

1. `.wm` 规则 specification，用于描述一个网站如何暴露媒体条目。
2. 一个参考实现：Python 后端 + Web 前端，可以生成、校验、预览并保存规则。

[Zwind - WebDAV Server & Player](https://apps.apple.com/us/app/zwind-webdav-server-player/id6755239096) 是这个 specification 在 iOS 上的一个实现。它可以消费 `.wm` marker file，并通过 WebDAV 暴露投影后的媒体目录。

## 规则示例

```ini
source=https://example.com/videos
candidate_selector=a:has(img)
projection=by-item
media_type=video
max_items=30
```

## 本地开发

后端：

```bash
cd apps/api
python -m venv .venv
source .venv/bin/activate
pip install -e ../../packages/rule-core -e ".[test,browser]"
python -m playwright install chromium
uvicorn zwmp_api.main:app --reload
```

前端：

```bash
cd apps/web
npm install
npm run dev
```

测试：

```bash
pytest
npm run build
```

本地服务：

- 前端：http://127.0.0.1:5173/
- 后端：http://127.0.0.1:8000/
- API 文档：http://127.0.0.1:8000/docs

## 配置

后端读取这些环境变量：

- `ZWMP_DATA_DIR`：运行数据根目录。默认：`data`。
- `ZWMP_CACHE_DB`：SQLite 缓存路径。默认：`data/cache/zwmp.sqlite3`。
- `ZWMP_RULE_OUTPUT_DIR`：生成规则输出目录。默认：`data/generated-rules`。
- `ZWMP_AI_PROVIDER`：OpenAI-compatible API base URL。默认：`none`。
- `ZWMP_AI_API_KEY`：AI provider API key。
- `ZWMP_AI_MODEL`：AI 模型名。默认：`gpt-4.1-mini`。

如果没有配置 `ZWMP_AI_PROVIDER` 或 `ZWMP_AI_API_KEY`，ZWMP 会自动使用 deterministic heuristic fallback 来生成规则。

Playwright 在运行时是可选的。如果没有安装 Playwright 或浏览器 runtime，后端会 fallback 到普通 HTTP 加载。对于依赖 JavaScript 渲染的网站，仍然建议安装 Playwright browser runtime。

## 当前状态

仓库目前包含早期参考实现：

- rule parser / formatter
- media URL matcher
- projection JSON model
- FastAPI job API
- 支持浏览器的页面加载，并带普通 HTTP fallback
- heuristic selector generation
- 可选 AI provider 边界
- SQLite cache 和 generated rule 持久化
- React 规则生成与预览工作台

部分高级字段已经可以解析和保留，但 runtime 覆盖还需要继续增强，尤其是多跳 detail expansion 和交互式 playback sniffing。

