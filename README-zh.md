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

## 规则文档

- [Web Media `.wm` 规则语法说明](docs/web-media-rule-guide-zh.md)：面向用户的规则写法和常见示例。
- [ZWMP Rule Specification](docs/specification.md)：面向实现者的规则 specification 细节。

## 配置

后端读取这些环境变量：

- `ZWMP_CONFIG`：统一 JSON 配置文件。默认：`config/zwmp.config.json`。
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

站点引导文案、SEO metadata、公开链接、AI providers 和 AI quota 都配置在 `config/zwmp.config.json`。如果该文件配置了 AI providers，会覆盖旧的 env AI 配置。如果没有可用 provider、quota 用尽或 provider ratelimited，ZWMP 会 fallback 到 v3 local hypotheses + validation finalizer，并在 Web UI 显式提示。

默认 AI quota 是 global：每个 `zwmp_device_id` cookie 每天最多 2 次 AI 生成。provider 可以覆盖 global quota，支持 `ip` / `device_id` 维度和 `hour` / `day` 时间窗口。

生成 cache 是强制的，key 基于 normalized URL pattern、媒体类型、generator version 和 generation mode（`ai` / `local`）。URL 查询参数会保留参数名但移除参数值。AI cache 优先；只有 AI 不可用或 quota 用尽时才使用 local cache。cache 没有 TTL；管理员可以手动删除 cache 记录或 generated rule 文件。

Playwright 是运行时硬要求。生成和预览都使用 v3 browser-first workflow；如果 Chromium 无法启动，任务会失败并提示安装方式。

媒体预览只使用浏览器直连 URL。ZWMP 不提供后端媒体 proxy endpoint。

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

导出 generated rules，用于 self-hosted 审查或未来 ZWMP-Hub 整理：

```bash
./scripts/export_rules.py --output exports/zwmp-rules
```

导出目录会区分 AI/local：

```text
exports/zwmp-rules/
  ai/
  local/
  manifest.json
```

Docker Compose、systemd 和 nginx 的线上部署示例在 `deploy/`。

## 当前状态

仓库目前包含早期参考实现：

- rule parser / formatter
- media URL matcher
- projection JSON model
- FastAPI job API
- 基于 Playwright 的 browser-first 页面 evidence 收集
- v3 local hypotheses 和 validation
- 可选 AI hypotheses/finalization，并带 local validation fallback
- SQLite cache 和 generated rule 持久化
- React 规则生成与资源预览工作台

高级 runtime 覆盖还在继续增强，尤其是多跳 detail expansion、剧集 fan-out、network sniffing 和交互式播放。

## License

ZWMP 软件实现采用 AGPL-3.0-or-later。ZWMP Rule Specification 采用 CC BY 4.0。
