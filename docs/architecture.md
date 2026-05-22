# Architecture

ZWMP uses a direct, validation-first pipeline.

```text
URL + media type
  -> SSRF guard
  -> v3 Playwright browser runtime
  -> repeated item structure mining
  -> optional AI hypotheses/finalization
  -> local hypotheses + validation fallback
  -> rule validation by execution
  -> rule text + projection preview
  -> generated rule persistence
```

## Backend

The backend is a FastAPI application in `apps/api`.

Core responsibilities:

- load user-provided pages with the v3 Playwright browser-first runtime
- discover repeated item structures from browser evidence
- produce `.wm` rule drafts
- validate drafts by executing them with the same v3 browser runtime
- save generated rules and metadata
- expose share links for explicit user-created shares
- keep media playback browser-direct; no backend media proxy is provided

## Rule Core

`packages/rule-core` contains code that should stay independent from the web service:

- parser and deterministic formatter
- media URL matching and extraction
- projection tree generation
- SSRF URL guard

## Cache Boundary

ZWMP deliberately separates rule generation from resource preview:

- Rule generation cache: mandatory, infinite TTL, keyed by normalized URL pattern, media type, and generator version.
- Projection preview: not long-term cached. It represents a fresh execution of the rule and may contain expiring media URLs.

This is important because many media URLs contain short-lived signatures or require request headers observed during browser loading.

## ZWMP-Hub

Successful generated rules are saved under `data/generated-rules`:

```text
data/generated-rules/
  video/
    streaming/
      example.com/
        example.com-video-<hash>.wm
        example.com-video-<hash>.json
```

The metadata file is intended to become the source material for a future community rule index named ZWMP-Hub.

## Security

The backend treats input URLs as untrusted:

- only `http` and `https` are allowed
- localhost, private, link-local, multicast, reserved, and metadata-service addresses are blocked
- page loads have timeouts and maximum HTML size limits
- no public generated-rule list API is exposed
- no backend media proxy endpoint is exposed
