# Web Media `.wm` Rule Syntax Guide

This guide is written for Zwind users. It describes the `.wm` rule syntax currently supported by the Web Media Projection Resolver and gives common examples.

The goal is simple: given a web listing page URL, Zwind projects the media entries on that page into a WebDAV directory.

## 1. What Is a `.wm` File?

A `.wm` file is a UTF-8 text file that stores rules in `key=value` form.

Example:

```ini
source=https://example.com/videos
candidate_selector=.video-card
candidate_link_selector=a.title
projection=by-item
```

When the rule is valid, the `.wm` file appears as a projected directory in the browser instead of a plain text file.

## 2. Minimal Working Rule

The simplest case is when every item on the listing page is already a detail-page link:

```ini
source=https://example.com/videos
candidate_selector=a:has(img)
projection=by-item
```

Meaning:

- `source`: the listing page to start from
- `candidate_selector`: which elements on the listing page count as candidate items
- `projection=by-item`: project every item as a subdirectory

## 3. Currently Supported Fields

The fields below are supported by the current resolver runtime.

### `source`

The listing page URL. It must be a full `http://` or `https://` URL.

```ini
source=https://example.com/videos
```

### `candidate_selector`

The CSS selector used to match candidate items on the listing page.

Common forms:

```ini
candidate_selector=a:has(img)
candidate_selector=.video-card
candidate_selector=.thumb-item
```

Prefer selecting the card or clickable item, not only the image.

### `candidate_link_selector`

Use this when `candidate_selector` matches a card container instead of the final detail link. The resolver will find the actual link inside each card.

```ini
candidate_selector=.frame-block
candidate_link_selector=p.title a
```

This means:

- first find each `.frame-block` card
- then use `p.title a` inside each card as the real detail-page link

### `title_selector`

Extracts the candidate item title.

```ini
title_selector=.title
```

If omitted, the resolver tries to infer a title automatically.

### `thumbnail_selector`

Extracts the thumbnail.

```ini
thumbnail_selector=.thumb img
```

### `duration_selector`

Extracts duration text.

```ini
duration_selector=.duration
```

### `projection`

Currently supported values:

- `by-item`
- `flat`

Recommended for most sites:

```ini
projection=by-item
```

`by-item` projects every item into its own subdirectory, which fits most sites better.

### `media_type`

Specifies which resources count as actual media resources.

```ini
media_type=video
```

Supported values:

- `video`: default; matches `.mp4`, `.webm`, `.m3u8`, `.mpd`, and similar video resources
- `audio`: matches `.mp3`, `.m4a`, `.flac`, and similar audio resources
- `image`: matches `.jpg`, `.png`, `.webp`, and similar image resources
- `all`: matches video, audio, and images

Keep the default `video` for most sites. Many intermediate pages contain cover images and thumbnails. If media type is too broad, the resolver may think it has already found media and stop before reaching the playback page.

Only use the following for image or gallery sites:

```ini
media_type=image
projection=flat
```

### `media_url_ttl`

Controls the cache time for playback URLs, in seconds.

```ini
media_url_ttl=0
```

If omitted, the resolver binding's detail cache time is used.

Many video sites use signed, tokenized, or expiring playback URLs. Listing pages and directory pages can be cached, but when opening `<title>.mp4`, `<title>.m3u8`, or `media.url`, it is often safer to resolve again so an old URL does not fail midway or return `410 Gone` for the next video.

For those sites, use:

```ini
media_url_ttl=0
```

If `force_network_sniff=true` and `media_url_ttl` is not explicitly set, playback is also resolved fresh because sniffed playback URLs usually expire more easily.

### `media_delivery`

Controls how media files are delivered to the WebDAV client.

```ini
media_delivery=auto
media_delivery=redirect
media_delivery=proxy
```

Default:

```ini
media_delivery=redirect
```

`redirect` returns an HTTP redirect when direct access is possible, allowing the player to access the source media URL directly.

`auto` redirects when direct access is possible. If the browser runtime detects that the URL needs headers such as `Referer`, `Origin`, or `Cookie`, Zwind can automatically switch to proxy streaming.

`proxy` forces Zwind to proxy the media stream. It is useful when source direct links often return `403` / `410`, or when you want Zwind to re-resolve and retry once after a URL expires.

### `max_items`

Limits how many items are parsed.

```ini
max_items=50
```

### `force_network_sniff`

Forces playback request sniffing.

```ini
force_network_sniff=false
```

The recommended default is currently `false`.

### `fast_mode`

Enables fast mode.

```ini
fast_mode=true
```

Meaning:

- `false`: default mode; uses a browser runtime, supports JavaScript execution, and works better for dynamic sites
- `true`: fast mode; uses plain HTTP fetching without JavaScript, faster but only suitable for static HTML sites

If a site does not rely on frontend JavaScript, you can try enabling it.

### `force_desktop_mode`

Forces the desktop page shape.

```ini
force_desktop_mode=true
```

Meaning:

- `false`: default; does not force desktop mode and lets the site decide whether to return desktop or mobile HTML
- `true`: tries to force the desktop page shape. Useful when the desktop DOM is more stable or the mobile page misses the target selectors

If a site always switches to a mobile page in the app and selectors no longer match, try enabling this option.

### `selector_wait_timeout`

Short polling wait time for selectors, in seconds.

```ini
selector_wait_timeout=1.5
```

Meaning:

- `0`: default; do not wait. Run selectors as soon as the page finishes loading
- `>0`: if the selector is initially empty, keep polling briefly while JavaScript or hydration mounts the DOM

Useful for sites where frontend rendering is slow and listing or episode nodes appear late.

## 4. Intermediate Page Hops: `detail_url_*`

Many sites are not simply "listing page -> final playback page". They are often:

- listing page
- intermediate page
- final detail / playback page

In those cases, use `detail_url_*`.

### `detail_url_selector`

Finds the next-hop link inside the candidate detail page.

```ini
detail_url_selector=a.btn-play
```

### `detail_url_mode`

Currently supported values:

- `single`
- `expand`

```ini
detail_url_mode=single
```

`single`: use only the first matched link. This fits "play now" buttons.

`expand`: expand all matched links. This fits episode lists or multi-part lists.

### `detail_url_selector_2` / `detail_url_mode_2`

If a second hop is needed, continue with:

```ini
detail_url_selector=a.btn-play
detail_url_mode=single
detail_url_selector_2=.play-list a.play-item
detail_url_mode_2=expand
```

### `detail_url_max_hops`

Limits the maximum number of hops.

```ini
detail_url_max_hops=3
```

### `detail_url_stop_when_media_found`

Stops further hopping if the current page already contains media links.

```ini
detail_url_stop_when_media_found=true
```

The recommended default is usually `true`.

## 5. Common Examples

### Example A: Listing Items Are Direct Detail Pages

```ini
source=https://example.com/videos
candidate_selector=.video-card a
projection=by-item
max_items=30
```

Use when:

- each listing item is already a video detail page
- no intermediate page is needed

### Example B: Extract the Title Link Inside a Card Container

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

Use when:

- each listing item is a card
- the real detail link is hidden inside the card

### Example C: Listing Page -> Intermediate Page -> Playback Page

```ini
source=https://example.com/movie/list
candidate_selector=a.video-thumb
detail_url_selector=a.btn-play
detail_url_mode=single
projection=by-item
max_items=50
```

Use when:

- a listing item first opens a movie page
- that movie page still requires clicking "play now"

### Example D: Listing Page -> Series Page -> Expand Episodes

```ini
source=https://example.com/drama/list
candidate_selector=a.video-thumb
detail_url_selector=.play-list a.play-item
detail_url_mode=expand
projection=by-item
max_items=100
```

Use when:

- a candidate item opens a series page
- the series page contains multiple links such as "Episode 1 / Episode 2 / Episode 3"

Note: in `expand` mode, expanded entries appear under a second-level directory. They are not flattened into the `.wm` root directory.

### Example E: Static Site Fast Mode

```ini
source=https://example.com/videos
candidate_selector=.entry-card a
projection=by-item
fast_mode=true
```

Use when:

- the page does not depend on JavaScript
- the complete listing DOM is visible through `curl`
- faster parsing is preferred

## 6. Recommended Debugging Method

When a site cannot be parsed, start with:

```bash
python3 scripts/web_media_rule_generator.py debug \
  -r your-rule.wm \
  "https://example.com/list"
```

Focus on three things:

1. whether `candidate_selector` matches candidate items
2. whether `detail_url_selector` matches on the corresponding hop page
3. whether final items are produced

If `candidate_selector` matches zero nodes, the problem is usually on the listing page.

If candidates match but a `detail_url_selector` hop matches zero nodes, the problem is usually the intermediate page selector.

## 7. Fields Not Recommended as Stable User Syntax Yet

`web-media-rule-spec.md` contains fields that are still extension designs or future plans, such as some click strategies, sniffing controls, and browser context fields.

Those fields should not be treated as stable syntax that users can rely on today.

When writing product copy, help docs, or examples, prefer the field set described in this guide.
