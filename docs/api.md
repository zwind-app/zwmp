# API

Base path: `/api`

## Health

```text
GET /api/health
```

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
    "force_refresh": false,
    "force_network_sniff": false,
    "fast_mode": false,
    "max_items": 30
  }
}
```

The job response includes status, phase, progress, debug events, and a result when complete.

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

## Rules

```text
GET /api/rules
GET /api/rules/{rule_id}
```

## Proxy

```text
GET /api/proxy/{session_id}/{media_id}
```

This endpoint only proxies media discovered by the matching job/session.

