# Web Media Rule Spec

## Purpose

Web Media Projection Resolver uses a declarative rule to turn a web listing page into projected WebDAV media resources.

In Zwind, this rule is stored inside a `.wm` marker file under a Web Media resolver binding.

Example:

```text
/WebMedia/top-favorite.wm
```

When the `.wm` file contains a valid rule, the marker file becomes a projected directory. When the file is empty or invalid, it remains an editable backend file.

The rule describes:

- where discovery starts
- how candidate media entries are found on a listing page
- how each candidate opens its detail page
- how title/cover/metadata are extracted
- how playback is triggered
- how network requests are inspected to locate playable manifests
- how projected WebDAV resources should be shaped

This spec is designed to be simple enough for users to paste/edit, and structured enough that AI can generate rules from a sample page.

Resolver discovery should run against a browser-like runtime with JavaScript
execution, not a raw HTTP fetch only. On iOS this means a shared
`ZwindBrowserRuntime` backed by `WKWebView`. Rule generation and debug tooling
should use an equivalent browser-capable runtime when available so the observed
DOM matches what the resolver sees after scripts execute.

## Rule Format

Rules are UTF-8 text files using `key=value` lines. The file extension should be `.wm`.

Comments start with `#`.

Blank lines are ignored.

Values are strings unless explicitly documented as lists, booleans, integers, or enums.

Example:

```ini
source=https://example.com/videos
candidate_selector=a:has(img)
click_strategy=open-link
projection=by-item

title_selector=h1
play_button_selector=button[aria-label*=Play]
manifest_types=m3u8,mpd
```

## Marker File Semantics

The `.wm` file is both:

- the editable backend definition file
- the projection boundary when the rule is valid

Example tree before writing a rule:

```text
/WebMedia/
  top-favorite.wm
```

After `top-favorite.wm` contains a valid rule, opening it projects:

```text
/WebMedia/top-favorite.wm/
  items.json
  item-title-1/
    media.m3u8
    detail.url
    item.json
```

Mutation behavior:

- Creating an empty `.wm` file must write to backend storage.
- Editing a `.wm` file must write to backend storage.
- Renaming/deleting a `.wm` file must operate on backend storage.
- Long-pressing a projected `.wm` directory should allow opening the underlying marker file in a text editor.

## Required Fields

### `source`

The listing page URL used for discovery.

```ini
source=https://example.com/videos
```

Rules:

- Must be an absolute `http` or `https` URL.
- Resolver uses this as the base URL for relative links.
- If pagination is configured, this is page 1.

### `candidate_selector`

CSS selector used on the listing page to find candidate media entries.

```ini
candidate_selector=img, a:has(img)
```

Recommended selectors:

```ini
candidate_selector=a:has(img)
candidate_selector=.video-elem a.display
candidate_selector=.item-card a[href]
```

The resolver will inspect each matched element and derive:

- detail URL
- title
- thumbnail
- duration when available

The selector should normally point to a clickable wrapper or anchor, not the inner image alone.

### `click_strategy`

How to open each candidate.

Supported values:

```ini
click_strategy=open-link
click_strategy=click
click_strategy=click-selector
```

Meaning:

- `open-link`: extract the candidate's `href` and navigate directly.
- `click`: click the matched candidate element in a browser context.
- `click-selector`: after candidate is selected, click `candidate_click_selector`.

Default:

```ini
click_strategy=open-link
```

## Projection Fields

### `media_type`

Controls which resource kind counts as projected media.

Supported values:

```ini
media_type=video
media_type=audio
media_type=image
media_type=all
```

Default:

```ini
media_type=video
```

`video` includes normal video files and video manifests such as `.mp4`, `.webm`,
`.m3u8`, and `.mpd`. With the default value, images found on intermediate pages
are treated as thumbnails/page assets and do not stop `detail_url_*` navigation.

Use `image` for image galleries, `audio` for music or podcast pages, and `all`
only when the site intentionally exposes mixed media resources.

### `media_url_ttl`

Controls how long a discovered playback URL may be reused when a user opens
`media.url` or the projected media file such as `<title>.mp4`.

```ini
media_url_ttl=0
media_url_ttl=60
```

Default: unset, which means the resolver uses the binding-level detail cache TTL.

Use `media_url_ttl=0` for sites whose media URLs contain short-lived signatures
or tokens. Directory listings can still use cached metadata, but the actual media
open will re-resolve the detail page before returning the URL/stream.

When `force_network_sniff=true` and `media_url_ttl` is unset, the runtime treats
media opens as fresh resolves because sniffed URLs are commonly short-lived.

### `media_delivery`

Controls how the projected media file is delivered to WebDAV clients.

```ini
media_delivery=auto
media_delivery=proxy
media_delivery=redirect
```

Default:

```ini
media_delivery=auto
```

`auto` returns HTTP 302 when the media URL can be opened directly. If the browser
runtime discovered required request headers such as `Referer`, `Origin`, or
`Cookie`, Zwind proxies the stream so those headers can be sent upstream.

`proxy` forces Zwind to stream the media through the app. Use it for sites that
often return `403` or `410` for direct links, or when you need Zwind to refresh
and retry after a short-lived URL expires.

`redirect` forces HTTP 302 to the upstream media URL even when Zwind discovered
browser request headers. This is fastest, but some sites may reject third-party
players with `403` if they require `Referer`, `Origin`, or `Cookie`.

### `projection`

Controls projected WebDAV shape.

Supported values:

```ini
projection=by-item
projection=flat
```

`by-item`:

```text
/WebMedia/top-favorite.wm/
  item-title-1/
    media.m3u8
    media.url
    item.json
    thumbnail.jpg
  item-title-2/
    media.m3u8
    media.url
    item.json
```

`flat`:

```text
/WebMedia/top-favorite.wm/
  item-title-1.m3u8
  item-title-2.m3u8
  items.json
```

Default:

```ini
projection=by-item
```

## Listing Extraction Fields

### `candidate_container_selector`

Optional selector used to expand from the matched candidate element to a parent card.

```ini
candidate_container_selector=.video-elem
```

Use this when `candidate_selector` points to an anchor but title/duration/thumbnail are siblings inside a card.

### `candidate_link_selector`

Optional selector used within the candidate container to find the detail link.

```ini
candidate_link_selector=a.display
```

If omitted, the resolver uses:

1. matched element's `href`
2. first descendant anchor's `href`
3. first ancestor anchor's `href`

### `candidate_title_selector`

Optional selector used within the candidate container to get the listing title.

```ini
candidate_title_selector=a.title
```

If omitted, resolver falls back to:

1. text content of matched element
2. text content of nearest anchor
3. image `alt`
4. detail URL path slug

### `candidate_thumbnail_selector`

Optional selector used within the candidate container to get a thumbnail.

```ini
candidate_thumbnail_selector=.img, img
```

Resolver extracts thumbnail from:

- `src`
- `data-src`
- `data-original`
- CSS `background-image: url(...)`

### `candidate_duration_selector`

Optional selector used within the candidate container to get duration text.

```ini
candidate_duration_selector=.layer
```

Duration is metadata only. The resolver does not need it to play media.

### Example for `web-media/example-html.md`

The sample listing has repeated `.video-elem` cards. Each card contains:

- `.display` anchor to detail page
- `.img` with CSS `background-image`
- `.layer` duration
- `a.title` title link

Suggested rule:

```ini
source=https://91porny.com/video/category/top-favorite
candidate_selector=.video-elem
candidate_link_selector=a.display
candidate_title_selector=a.title
candidate_thumbnail_selector=.img
candidate_duration_selector=.layer
click_strategy=open-link
projection=by-item
```

## Item Detail URL Resolution Fields

Some sites do not expose the final media detail page directly from the listing page.
The listing item may first point to an intermediate information page, and that
intermediate page then links to the actual playback/detail page.

Example:

```html
<!-- listing page -->
<a href="/movie/elietianqi.html" class="video-thumb">
  <img src="..." alt="恶劣天气">
</a>

<!-- /movie/elietianqi.html intermediate page -->
<a href="/play/elietianqi-1.html" class="btn-play">立即播放</a>

<!-- /play/elietianqi-1.html final detail page -->
<video>
  <source src="https://cdn.example.com/index.m3u8" type="application/x-mpegURL">
</video>
```

The default behavior is direct:

```ini
candidate link -> final detail page
```

When an intermediate page is required, configure a detail URL chain:

```ini
source=https://example.com/videos
candidate_selector=a.video-thumb
detail_url_selector=a.btn-play
projection=by-item
```

Resolution flow:

```text
listing candidate href
  -> fetch /movie/elietianqi.html
  -> select a.btn-play
  -> resolve href /play/elietianqi-1.html
  -> final detail page
```

### `detail_url_selector`

Optional selector used on the first intermediate page to find the next URL.

```ini
detail_url_selector=a.btn-play
detail_url_selector=a[href*="/play/"]
detail_url_selector=.play-button a
```

The resolver should extract the next URL from the first matching element using
this priority:

1. `href`
2. `data-href`
3. `data-url`
4. `data-play-url`
5. `data-src`
6. first URL literal in `onclick`

Relative URLs are resolved against the intermediate page URL.

By default only the first matched URL is used.

To expand all matched links from the intermediate page into multiple projected
items, use `detail_url_mode=expand`.

### `detail_url_mode`

Controls whether the current hop selects one next URL or fans out into multiple
next URLs.

Supported values:

```ini
detail_url_mode=single
detail_url_mode=expand
```

Default:

```ini
detail_url_mode=single
```

Semantics:

- `single`: use only the first matched next URL.
- `expand`: keep all matched next URLs and turn them into separate projected items.

When `expand` is used, the matched link text becomes the default title suffix
for each generated item.

### `detail_url_selector_N`

Optional numbered selectors for additional hops.

```ini
detail_url_selector=a.btn-play
detail_url_selector_2=a.source-link
detail_url_selector_3=a.real-play-url
```

The resolver applies selectors in order. In the example above:

```text
candidate href -> selector 1 -> selector 2 -> selector 3 -> final detail page
```

Use the smallest number of hops that reaches the page where media manifests are
available.

### `detail_url_mode_N`

Optional per-hop mode matching `detail_url_selector_N`.

```ini
detail_url_selector=a.btn-play
detail_url_mode=single
detail_url_selector_2=.play-list a.play-item
detail_url_mode_2=expand
```

This means:

```text
candidate href
  -> first hop picks one play entry page
  -> second hop expands all episode/play-item links
```

### `detail_url_max_hops`

Maximum number of intermediate hops allowed when resolving an item detail URL.

```ini
detail_url_max_hops=3
```

Default:

```ini
detail_url_max_hops=3
```

This is a safety limit for redirects, malformed rules, and sites that loop.

### `detail_url_stop_when_media_found`

Whether to stop resolving the chain when the current page already exposes a
direct media URL or manifest.

```ini
detail_url_stop_when_media_found=false
```

Default:

```ini
detail_url_stop_when_media_found=false
```

Keep this `false` for episode pages that expose the current episode media and
also contain links to other episodes. Set it to `true` only when a direct media
page should stop the chain immediately.

### `force_desktop_mode`

Whether browser-backed discovery should try to force desktop page mode.

```ini
force_desktop_mode=true
```

Default:

```ini
force_desktop_mode=false
```

Use this when the mobile site hides or restructures the DOM in a way that
breaks your selectors.

### `selector_wait_timeout`

How many seconds selector queries may poll for late-rendered DOM nodes before
declaring no match.

```ini
selector_wait_timeout=1.5
```

Default:

```ini
selector_wait_timeout=0
```

This applies to browser-backed selector lookups. Keep it at `0` for fast,
static pages. Increase it for JS-heavy pages whose target nodes appear only
after hydration.

### Example: list -> movie -> play

```ini
source=https://example.com/video
candidate_selector=a.video-thumb
detail_url_selector=a.btn-play
title_selector=h1
projection=by-item
max_items=50
force_network_sniff=false
```

### Example: list -> season page -> all episodes

```html
<div class="play-list">
  <a href="/play/shenghuodabaozha-diliuji-1.html" class="play-item">第1集</a>
  <a href="/play/shenghuodabaozha-diliuji-2.html" class="play-item">第2集</a>
</div>
```

Rule:

```ini
source=https://example.com/drama
candidate_selector=a.video-thumb
detail_url_selector=.play-list a.play-item
detail_url_mode=expand
projection=by-item
```

Result:

```text
listing item
  -> intermediate season page
  -> expand every .play-item link
  -> generate one projected item per episode
```

## Detail Page Fields

### `title_selector`

Selector used on detail page to override listing title.

```ini
title_selector=h1
```

If no matching title is found, the listing title remains in use.

### `description_selector`

Optional detail page description.

```ini
description_selector=.description
```

### `poster_selector`

Optional detail page poster selector.

```ini
poster_selector=video[poster], img.poster
```

Resolver extracts:

- `poster`
- `src`
- `data-src`
- CSS `background-image`

### `play_button_selector`

Selector clicked after detail page loads to trigger media network requests.

```ini
play_button_selector=button[aria-label*=Play]
```

If omitted, resolver tries:

1. native `video`/`audio` element sources
2. page scripts and initial HTML
3. network requests during idle wait

### `wait_after_load_ms`

How long to wait after opening detail page.

```ini
wait_after_load_ms=1000
```

Default: `1000`.

### `wait_after_play_ms`

How long to listen for media requests after clicking play.

```ini
wait_after_play_ms=5000
```

Default: `5000`.

### `scroll_strategy`

Whether to scroll before extracting/clicking.

Supported values:

```ini
scroll_strategy=none
scroll_strategy=viewport
scroll_strategy=bottom
```

Default: `none`.

## Manifest Detection Fields

### `force_network_sniff`

Whether to sniff network requests even if direct media URLs are found in the page DOM.

```ini
force_network_sniff=false
```

Default: `false`.

When `false`, discovery uses this priority:

1. Direct media or manifest URL exposed by `video`, `audio`, or `source`.
2. Direct media or manifest URL found in initial HTML/scripts.
3. Network sniffing after optional play interaction.

This avoids unnecessary browser/network work on pages that already expose playable URLs.

### `network_sniff_timeout`

Maximum seconds to wait for browser network sniffing after play interaction.

```ini
network_sniff_timeout=5
```

Default: `5`.

This is separate from binding-level request/navigation timeout. Sniffing should
fail fast when no useful media request appears.

### `network_sniff_idle_timeout`

Maximum idle seconds with no new observed network resources during sniffing.

```ini
network_sniff_idle_timeout=1
```

Default: `1`.

### `manifest_types`

Comma-separated manifest types to detect.

```ini
manifest_types=m3u8,mpd
```

Supported values:

- `m3u8`
- `mpd`

Default:

```ini
manifest_types=m3u8,mpd
```

### `manifest_url_patterns`

Optional comma-separated wildcard patterns.

```ini
manifest_url_patterns=*.m3u8*,*.mpd*
```

Default behavior already detects:

- URL path ending in `.m3u8` or `.mpd`
- URL containing `.m3u8?` or `.mpd?`
- response content type:
  - `application/vnd.apple.mpegurl`
  - `application/x-mpegurl`
  - `audio/mpegurl`
  - `application/dash+xml`

### `media_url_patterns`

Optional fallback direct media patterns.

```ini
media_url_patterns=*.mp4*,*.mov*,*.m4v*,*.mp3*
```

Direct media is lower priority than manifests.

Direct media includes common extensions:

- `.mp4`
- `.m4v`
- `.mov`
- `.webm`
- `.mp3`
- `.m4a`

### `prefer_manifest`

Whether manifest URLs win over direct media URLs.

```ini
prefer_manifest=true
```

Default: `true`.

### `request_url_denylist`

Comma-separated patterns ignored during network capture.

```ini
request_url_denylist=*analytics*,*ads*,*tracking*
```

### `request_domain_allowlist`

Optional comma-separated host allowlist.

```ini
request_domain_allowlist=cdn.example.com,media.example.com
```

If omitted, all domains are allowed except denylisted ones.

## Browser Context Fields

### `user_agent`

Optional user agent override.

```ini
user_agent=Mozilla/5.0 ...
```

### `referer`

Optional referer override used for manifest/media projected requests.

```ini
referer=detail
referer=source
referer=https://example.com/
```

Supported values:

- `detail`: use detail page URL
- `source`: use source page URL
- absolute URL

Default: `detail`.

### `cookies`

Optional cookie header.

```ini
cookies=session=...; age_check=1
```

This is sensitive and should be stored as a secret field in Zwind if exposed.

### `headers.*`

Custom headers.

```ini
headers.Accept-Language=en-US,en;q=0.9
headers.Authorization=Bearer ...
```

Headers are applied to discovery and projected media access where appropriate.

## Limits and Cache Fields

### `max_items`

Maximum candidates discovered from the listing page.

```ini
max_items=50
```

Default: `50`.

### `max_detail_concurrency`

Maximum detail pages opened concurrently.

```ini
max_detail_concurrency=2
```

Default: `1` for mobile stability.

### `discovery_cache_ttl`

Seconds to cache listing/detail discovery results.

```ini
discovery_cache_ttl=1800
```

Default: `1800`.

### `manifest_cache_ttl`

Seconds to cache manifest URL validation.

```ini
manifest_cache_ttl=300
```

Default: `300`.

## Output Fields

### `include_item_json`

Whether to expose item metadata.

```ini
include_item_json=true
```

Default: `true`.

### `include_source_url`

Whether to expose a `.url` file to the detail page.

```ini
include_source_url=true
```

Default: `true`.

### `include_thumbnail`

Whether to expose thumbnail as a projected remote file/reference.

```ini
include_thumbnail=true
```

Default: `true`.

### `manifest_filename`

Name used for manifest inside each item directory.

```ini
manifest_filename=media
```

Resolver appends extension based on detected manifest type:

- `media.m3u8`
- `media.mpd`

Default: `media`.

## Error Handling Fields

### `missing_manifest_behavior`

Behavior when no manifest is found for an item.

```ini
missing_manifest_behavior=show-error-file
missing_manifest_behavior=hide-item
missing_manifest_behavior=show-detail-url-only
```

Default: `show-error-file`.

`show-error-file` projects:

```text
error.txt
detail.url
item.json
```

This makes debugging rules easier.

## Validation Rules

Rules must satisfy:

- `source` is absolute `http` or `https`.
- `candidate_selector` is non-empty.
- `click_strategy` is one of the supported enum values.
- `projection` is one of the supported enum values.
- selectors are syntactically valid CSS selectors for the resolver selector engine.
- numeric fields are within resolver-defined ranges.
- `headers.*` keys must be valid HTTP header names.
- sensitive fields such as `cookies` and `headers.Authorization` should not be exported in plain text.
- empty `.wm` files are allowed at storage level and should not be treated as resolver failures.

## Minimal Rule

```ini
source=https://example.com/videos
candidate_selector=a:has(img)
click_strategy=open-link
projection=by-item
force_network_sniff=false
```

## Recommended AI Prompt Contract

When asking AI to generate a rule from sample HTML, require it to output:

```ini
source=<absolute listing URL>
candidate_selector=<card or link selector>
candidate_container_selector=<optional card selector>
candidate_link_selector=<optional link selector>
candidate_title_selector=<optional title selector>
candidate_thumbnail_selector=<optional thumbnail selector>
candidate_duration_selector=<optional duration selector>
click_strategy=open-link
projection=by-item
title_selector=<detail title selector if known>
play_button_selector=<detail play selector if known>
manifest_types=m3u8,mpd
force_network_sniff=false
```

The AI should prefer stable class names and semantic attributes over deeply nested selectors.
