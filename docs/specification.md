# ZWMP Rule Specification

License: CC BY 4.0.

ZWMP rules are UTF-8 `.wm` text files using `key=value` lines. Comments start with `#`; blank lines are ignored.

## Minimal Rule

```ini
source=https://example.com/videos
candidate_selector=a:has(img)
projection=by-item
media_type=video
```

## Supported Fields

The reference implementation accepts and preserves the following rule keys:

```ini
source=https://example.com/videos
candidate_selector=.video-card
candidate_link_selector=a.title
detail_url_selector=a.btn-play
detail_url_mode=single
detail_url_selector_2=a.source
detail_url_mode_2=single
detail_url_selector_3=a.real-play-url
detail_url_mode_3=single
detail_url_max_hops=3
detail_url_stop_when_media_found=true
max_detail_concurrency=3
title_selector=h1
thumbnail_selector=.thumb img
duration_selector=.duration
media_selector=video source
media_type=video
media_url_ttl=0
media_delivery=auto
projection=by-item
max_items=30
force_network_sniff=false
fast_mode=true
force_desktop_mode=false
selector_wait_timeout=1.5
network_sniff_timeout=5.0
network_sniff_idle_timeout=1.0
```

Runtime support levels:

- Stable v3 generation: `source`, `candidate_selector`, `candidate_link_selector`, `detail_url_selector`, `detail_url_mode`, numbered detail hops, `detail_url_max_hops`, `detail_url_stop_when_media_found`, `max_detail_concurrency`, `title_selector`, `thumbnail_selector`, `duration_selector`, `projection`, `media_type`, `media_url_ttl`, `media_delivery`, `max_items`, `force_network_sniff`, `fast_mode`, `force_desktop_mode`, `selector_wait_timeout`, `network_sniff_timeout`, `network_sniff_idle_timeout`.
- Parsed for compatibility but intentionally disabled in v3 output: `media_selector`, `play_button_selector`.

## Required Fields

- `source`: absolute `http` or `https` URL.
- `candidate_selector`: CSS selector for listing items.

## Defaults

- `projection=by-item`
- `media_type=video`
- `media_delivery=auto`
- `detail_url_mode=single`
- `detail_url_max_hops=3`
- `detail_url_stop_when_media_found=true`
- `max_detail_concurrency=3`
- v3 generated rules force `fast_mode=true`
- boolean fields default to `false` unless documented otherwise

## Media Types

- `video`: video files and manifests such as `.mp4`, `.webm`, `.m3u8`, `.mpd`.
- `audio`: audio files such as `.mp3`, `.m4a`, `.flac`, `.ogg`.
- `image`: image files such as `.jpg`, `.png`, `.webp`, `.avif`.
- `all`: all supported media categories.

## Projection Modes

- `by-item`: each listing item becomes a projected directory.
- `flat`: media entries are projected as files in one directory.

## Intermediate Detail Pages

Some listing items point to an intermediate page before the actual media page.

```ini
source=https://example.com/videos
candidate_selector=a.video-thumb
detail_url_selector=a.btn-play
detail_url_mode=single
projection=by-item
media_type=video
```

`detail_url_selector` is evaluated on the first detail page. The reference runtime extracts URLs from matching anchors and then probes those pages for media. `detail_url_mode=expand` allows multiple matched links, which is useful for episode lists.

## Projection JSON

The preview API returns:

- `tree`: projected WebDAV-like directory nodes.
- `items`: resolved listing items.
- `media`: discovered media resources.
- `debug_events`: phase-by-phase generation information.
- `warnings`: non-fatal issues and next-step hints.
