# Web Media `.wm` 规则语法说明

本文面向 Zwind 用户，介绍 Web Media Projection Resolver 当前已经支持的 `.wm` 规则语法，以及常见写法示例。

目标很简单：给一个网页列表页 URL，让 Zwind 把网页中的媒体条目投影成 WebDAV 目录。

## 1. `.wm` 文件是什么

`.wm` 文件本质上是一个 UTF-8 文本文件，里面按 `key=value` 的形式写规则。

例如：

```ini
source=https://example.com/videos
candidate_selector=.video-card
candidate_link_selector=a.title
projection=by-item
```

当规则有效时，这个 `.wm` 文件在浏览器里会显示成一个投影目录，而不是普通文本文件。

## 2. 最小可用规则

最简单的情况，是列表页上的每一项本身就是详情页链接：

```ini
source=https://example.com/videos
candidate_selector=a:has(img)
projection=by-item
```

含义：

- `source`：从哪个列表页开始抓取
- `candidate_selector`：列表页上哪些元素算“候选条目”
- `projection=by-item`：每个条目投影成一个子目录

## 3. 当前已支持的字段

下面这些字段，是当前 resolver runtime 已经实际支持的。

### `source`

列表页 URL。必须是完整的 `http://` 或 `https://` 地址。

```ini
source=https://example.com/videos
```

### `candidate_selector`

列表页上用于匹配候选条目的 CSS selector。

常见写法：

```ini
candidate_selector=a:has(img)
candidate_selector=.video-card
candidate_selector=.thumb-item
```

建议优先指向“卡片”或“可点击项”，而不是只指向一张图片。

### `candidate_link_selector`

当 `candidate_selector` 匹配到的是卡片容器，而不是最终详情链接时，用它在卡片内部继续取链接。

```ini
candidate_selector=.frame-block
candidate_link_selector=p.title a
```

这个写法的意思是：

- 先找到 `.frame-block` 卡片
- 再从每张卡片里取 `p.title a` 作为真正的详情页链接

### `title_selector`

用于提取候选项标题。

```ini
title_selector=.title
```

如果不写，系统会尽量自动推断标题。

### `thumbnail_selector`

用于提取缩略图。

```ini
thumbnail_selector=.thumb img
```

### `duration_selector`

用于提取时长文本。

```ini
duration_selector=.duration
```

### `projection`

当前支持：

- `by-item`
- `flat`

通常推荐：

```ini
projection=by-item
```

`by-item` 会把每个条目投影成一个子目录，更适合大多数站点。

### `media_type`

指定哪些资源才算真正的媒体资源。

```ini
media_type=video
```

当前支持：

- `video`：默认值，匹配 `.mp4`、`.webm`、`.m3u8`、`.mpd` 等视频资源
- `audio`：匹配 `.mp3`、`.m4a`、`.flac` 等音频资源
- `image`：匹配 `.jpg`、`.png`、`.webp` 等图片资源
- `all`：匹配视频、音频、图片

建议默认保持 `video`。很多中间页会出现封面图、缩略图，如果不区分类型，系统可能会误以为已经找到了媒体资源，从而提前停止继续解析播放页。

只有在解析图片站、图集站时，才建议改成：

```ini
media_type=image
projection=flat
```

### `media_url_ttl`

控制播放 URL 的缓存时间，单位是秒。

```ini
media_url_ttl=0
```

默认不写，表示沿用 resolver binding 里的详情缓存时间。

很多视频站的真实播放 URL 会带签名、token 或过期时间。列表页和目录页可以缓存，但真正播放 `<标题>.mp4`、`<标题>.m3u8` 或打开 `media.url` 时，最好重新解析一次，避免旧 URL 播放到一半或下一个视频变成 `410 Gone`。

如果遇到这类站点，建议加上：

```ini
media_url_ttl=0
```

如果 `force_network_sniff=true` 且没有显式配置 `media_url_ttl`，播放时也会按新鲜解析处理，因为嗅探得到的播放 URL 通常更容易过期。

### `media_delivery`

控制媒体文件如何提供给 WebDAV 客户端。

```ini
media_delivery=auto
media_delivery=proxy
media_delivery=redirect
```

默认：

```ini
media_delivery=redirect
```

`auto` 会在可以直连时返回 HTTP 302，让播放器直接访问源媒体 URL。如果 browser runtime 发现这个 URL 需要 `Referer`、`Origin`、`Cookie` 等请求头，Zwind 会自动改为代理流。

`proxy` 会强制让 Zwind 代理媒体流。适合源站直链容易 `403` / `410`，或者你希望 Zwind 在 URL 过期时能重新解析并重试一次的站点。

`redirect` 会强制返回 HTTP 302 到源媒体 URL，兼容性和性能通常更好；但如果源站要求 `Referer`、`Origin`、`Cookie`，第三方播放器可能会收到 `403`。遇到这种情况应改回 `auto` 或 `proxy`。

### `max_items`

限制最多解析多少个条目。

```ini
max_items=50
```

### `force_network_sniff`

是否强制进行播放请求嗅探。

```ini
force_network_sniff=false
```

当前推荐默认保持 `false`。

浏览器嗅探默认最多等待 5 秒。可以按站点调整：

```ini
network_sniff_timeout=5
network_sniff_idle_timeout=1
```

### `fast_mode`

是否启用快速模式。

```ini
fast_mode=true
```

含义：

- `false`：默认模式，使用浏览器运行时，支持 JS 执行，更适合动态站点
- `true`：快速模式，使用普通 HTTP 抓取，不执行 JS，更快，但只适合静态 HTML 站点

如果某个站点不依赖前端 JS，就可以尝试打开它。

### `force_desktop_mode`

是否强制使用桌面端网页形态。

```ini
force_desktop_mode=true
```

含义：

- `false`：默认值，不强制桌面端，让站点自行决定返回桌面页还是移动页
- `true`：尽量强制使用桌面端网页形态。适合桌面 DOM 更稳定、而移动页会缺少目标 selector 的站点

如果某个站点在 App 里总是跳到移动页，导致 selector 命不中，可以尝试打开它。

### `selector_wait_timeout`

selector 短轮询等待时间，单位秒。

```ini
selector_wait_timeout=1.5
```

含义：

- `0`：默认值，不等待；页面一加载完就立即执行 selector
- `>0`：如果 selector 初次为空，短时间内继续轮询等待 JS/hydration 把 DOM 挂出来

适合前端框架渲染较慢、列表或剧集节点会延迟出现的站点。

## 4. 中间页跳转：`detail_url_*`

很多站点不是“列表页 -> 最终播放页”，而是：

- 列表页
- 中间页
- 最终详情页 / 播放页

这时就需要 `detail_url_*`。

### `detail_url_selector`

在候选详情页里继续寻找下一跳链接。

```ini
detail_url_selector=a.btn-play
```

### `detail_url_mode`

当前支持：

- `single`
- `expand`

```ini
detail_url_mode=single
```

`single`：只取第一个命中的链接，适合“立即播放”这类按钮。

`expand`：把命中的多个链接全部展开，适合剧集列表、分集列表。

### `detail_url_selector_2` / `detail_url_mode_2`

如果还要继续跳第二跳，可以继续写：

```ini
detail_url_selector=a.btn-play
detail_url_mode=single
detail_url_selector_2=.play-list a.play-item
detail_url_mode_2=expand
```

### `detail_url_max_hops`

限制最多跳几层。

```ini
detail_url_max_hops=3
```

### `detail_url_stop_when_media_found`

如果当前页面已经直接出现媒体链接，就停止继续跳转。

```ini
detail_url_stop_when_media_found=false
```

默认是 `false`。如果中间页既有当前集媒体，又有多集/分集按钮，必须保持 `false`，否则会只解析当前集。只有当“发现媒体后就一定不需要继续跳转”时，才手动设为 `true`。

## 5. 常见示例

### 示例 A：列表页直接就是详情页

```ini
source=https://example.com/videos
candidate_selector=.video-card a
projection=by-item
max_items=30
```

适用场景：

- 每个列表项本身就是视频详情页
- 不需要额外跳中间页

### 示例 B：卡片容器里再取标题链接

```ini
source=https://www.xvideos.com/
candidate_selector=.frame-block
candidate_link_selector=p.title a
title_selector=.title
thumbnail_selector=.thumb img
duration_selector=.duration
projection=by-item
max_items=50
```

适用场景：

- 列表页每一项是卡片
- 真正的详情链接藏在卡片内部

### 示例 C：列表页 -> 中间页 -> 播放页

```ini
source=https://example.com/movie/list
candidate_selector=a.video-thumb
detail_url_selector=a.btn-play
detail_url_mode=single
projection=by-item
max_items=50
```

适用场景：

- 列表项先进入影片页
- 影片页里还要再点一次“立即播放”

### 示例 D：列表页 -> 剧集页 -> 多集展开

```ini
source=https://example.com/drama/list
candidate_selector=a.video-thumb
detail_url_selector=.play-list a.play-item
detail_url_mode=expand
projection=by-item
max_items=100
```

适用场景：

- 候选条目进入的是剧集页
- 剧集页里包含多个“第 1 集 / 第 2 集 / 第 3 集”

注意：`expand` 模式下，这些展开出来的条目会出现在二级目录里，不会平铺在 `.wm` 根目录。

### 示例 E：静态站点快速模式

```ini
source=https://example.com/videos
candidate_selector=.entry-card a
projection=by-item
fast_mode=true
```

适用场景：

- 页面不依赖 JS
- 直接 `curl` 就能看到完整列表 DOM
- 希望解析速度更快

## 6. 推荐调试方法

使用 web 配套工具 ZWMP。

## 7. 当前未建议作为用户语法依赖的字段

`web-media-rule-spec.md` 里有一些字段仍属于扩展设计或未来规划，例如某些点击策略、嗅探控制、浏览器上下文字段等。

这些字段不应视为当前用户可以稳定依赖的正式语法。

如果你在写产品文案、帮助文档或示例，请优先使用本文档中的字段集合。
