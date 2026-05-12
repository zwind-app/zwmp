# ZWMP Rule Specification

ZWMP rules are UTF-8 `.wm` text files using `key=value` lines. Comments start with `#`.

## Supported Fields

```ini
source=https://example.com/videos
candidate_selector=a:has(img)
candidate_link_selector=a.title
title_selector=h1
thumbnail_selector=.thumb img
duration_selector=.duration
projection=by-item
media_type=video
media_url_ttl=0
media_delivery=auto
max_items=30
force_network_sniff=false
fast_mode=false
force_desktop_mode=false
```

Required:

- `source`: absolute `http` or `https` URL.
- `candidate_selector`: CSS selector for listing items.

Defaults:

- `projection=by-item`
- `media_type=video`
- `media_delivery=auto`
- boolean fields default to `false`

Supported media types:

- `video`
- `audio`
- `image`
- `all`

Supported projection modes:

- `by-item`
- `flat`

## Planned Fields

The broader design includes intermediate page chains, click strategies, selector wait timeouts, and multi-hop expansion. These are documented in `tmp/refs/web-media-rule-spec.md`, but they are experimental until implemented in the reference runtime.

The generator must not emit planned fields by default unless the UI marks them as experimental.

## Projection JSON

The preview API returns a JSON shape with:

- `tree`: projected WebDAV-like directory nodes.
- `items`: resolved listing items.
- `media`: discovered media resources.
- `debug_events`: phase-by-phase generation information.
- `warnings`: non-fatal issues and next-step hints.

