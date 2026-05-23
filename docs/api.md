# API

Base path: `/api`

## Health

```text
GET /api/health
```

## Public Config

```text
GET /api/config
```

Returns public site configuration: localized guidance, SEO metadata, supported locales, and public links.

## Generation Jobs

```text
POST /api/generation-jobs
GET  /api/generation-jobs/{job_id}
```

Request:

```json
{
  "url": "https://example.com/videos",
  "media_type": "video",
  "options": {
    "force_network_sniff": false,
    "fast_mode": true,
    "max_items": 30,
    "sample_items": 8,
    "max_candidate_groups": 6,
    "validate_hypotheses": 5,
    "validation_limit": 24,
    "detail_probes": 3,
    "scroll_steps": 3,
    "desktop": false
  }
}
```

The job response includes status, phase, progress, debug events, `partial_result` while running, and a final `result` when complete.

During generation, `partial_result.rule_text` is emitted as soon as the rule is ready, before preview finishes. During generation and projection preview, `partial_result.projection_preview` is updated incrementally as detail pages are resolved.

Generation results include:

- `rule_text`
- `site_profile`
- `projection_preview`
- `cache_hit`
- `alternatives`
- `warnings`
- `runtime_notices`
- `v3`

`runtime_notices` tells clients when AI finalization fell back to the v3 local validation finalizer. Browser fallback is not supported in the v3 path; Playwright failures fail the job.

Generation cache is mandatory and keyed by normalized URL pattern, media type, and generator version. `force_refresh` is intentionally unsupported.

## Projection Jobs

```text
POST /api/projection-jobs
GET  /api/projection-jobs/{job_id}
```

Request:

```json
{
  "rule_text": "source=https://example.com/videos\ncandidate_selector=a:has(img)\n"
}
```

Projection results include `projection` and `runtime_notices`.

## Share Links

```text
POST /api/shares
GET  /api/shares/{share_id}
```

Share records store the rule text and the already-built projection view so a user with the link can reopen the result directly.

## Hidden Admin Data

Generated rules are saved on disk for self-hosted export, but no public `/api/rules` endpoint is exposed. Use `scripts/export_rules.py` to export generated rules. ZWMP also does not expose a media proxy endpoint; all media preview URLs are browser-direct.
