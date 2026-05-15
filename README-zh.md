# Zwind Web Media Projection (ZWMP)

[English](README.md)

[ZWMP](https://github.com/zwind-app/zwmp) 是一个开源工具，用于把网页列表页投影成类似 WebDAV 目录的媒体资源视图。

项目包含两部分：

1. `.wm` 规则 specification，用于描述一个网站如何暴露媒体条目。
2. 一个参考实现：Python 后端 + Web 前端，可以生成、校验、预览并保存规则。

[Zwind - WebDAV Server & Player](https://apps.apple.com/us/app/zwind-webdav-server-player/id6755239096) 是这个 specification 在 iOS 上的一个实现。它可以消费 `.wm` marker file，并通过 WebDAV 暴露投影后的媒体目录。

## 快速开始

创建本地配置：

```bash
cp .env.example .env
```

安装后端依赖：

```bash
cd apps/api
python -m venv .venv
source .venv/bin/activate
pip install -e ../../packages/rule-core -e ".[test,browser]"
python -m playwright install chromium
```

安装前端依赖：

```bash
cd apps/web
npm install
```

在仓库根目录启动前后端：

```bash
./scripts/dev.sh
```

日志会写入：

- `.logs/backend.log`
- `.logs/frontend.log`

本地服务：

- 前端：http://127.0.0.1:5173/
- 后端：http://127.0.0.1:8000/
- API 文档：http://127.0.0.1:8000/docs

## 规则示例

```ini
source=https://example.com/videos
candidate_selector=a:has(img)
projection=by-item
media_type=video
max_items=30
```

## 配置

后端读取这些环境变量：

- `ZWMP_DATA_DIR`：运行数据根目录。默认：`data`。
- `ZWMP_CACHE_DB`：SQLite 缓存路径。默认：`data/cache/zwmp.sqlite3`。
- `ZWMP_RULE_OUTPUT_DIR`：生成规则输出目录。默认：`data/generated-rules`。
- `ZWMP_AI_PROVIDER`：OpenAI-compatible API base URL。默认：`none`。
- `ZWMP_AI_API_KEY`：AI provider API key。
- `ZWMP_AI_MODEL`：AI 模型名。默认：`gpt-4.1-mini`。
- `ZWMP_MAX_ITEMS`：默认最多解析的列表条目数。默认：`30`。
- `ZWMP_PROBE_ITEMS`：默认探测的候选详情页数量。默认：`3`。
- `ZWMP_REQUEST_TIMEOUT`：页面请求超时时间，单位秒。默认：`12`。
- `ZWMP_MAX_HTML_BYTES`：最大 HTML 响应大小。默认：`2000000`。
- `ZWMP_PROXY_TTL_SECONDS`：预期 proxy session TTL。默认：`900`。

如果没有配置 `ZWMP_AI_PROVIDER` 或 `ZWMP_AI_API_KEY`，ZWMP 会自动使用 deterministic heuristic fallback 来生成规则。Web UI 会显式提示这个 fallback，并引导用户配置 AI。

Playwright 在运行时是可选的。如果没有安装 Playwright 或浏览器 runtime，后端会 fallback 到普通 HTTP 加载。Web UI 会显式提示这个 fallback，因为对于依赖 JavaScript 渲染的网站、network sniffing 和播放交互，browser-backed loading 才是推荐的完整态。

## 开发

手动启动后端：

```bash
cd apps/api
source .venv/bin/activate
uvicorn zwmp_api.main:app --reload
```

手动启动前端：

```bash
cd apps/web
npm run dev
```

测试：

```bash
pytest
npm run build
```

## 当前状态

仓库目前包含早期参考实现：

- rule parser / formatter
- media URL matcher
- projection JSON model
- FastAPI job API
- 支持浏览器的页面加载，并带普通 HTTP fallback
- heuristic selector generation
- 带结构化校验的可选 AI provider 边界
- SQLite cache 和 generated rule 持久化
- React 规则生成与资源预览工作台

高级 runtime 覆盖还在继续增强，尤其是多跳 detail expansion、剧集 fan-out、network sniffing 和交互式播放。

