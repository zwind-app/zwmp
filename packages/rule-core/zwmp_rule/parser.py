from __future__ import annotations

from pydantic import ValidationError

from .types import WebMediaRule


class RuleError(ValueError):
    def __init__(self, message: str, line: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.line = line


FIELD_ORDER = [
    "source",
    "candidate_selector",
    "candidate_link_selector",
    "title_selector",
    "thumbnail_selector",
    "duration_selector",
    "projection",
    "media_type",
    "media_url_ttl",
    "media_delivery",
    "max_items",
    "force_network_sniff",
    "fast_mode",
    "force_desktop_mode",
]

BOOL_FIELDS = {"force_network_sniff", "fast_mode", "force_desktop_mode"}
INT_FIELDS = {"media_url_ttl", "max_items"}


def parse_rule(text: str) -> WebMediaRule:
    data: dict[str, object] = {}
    for index, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise RuleError("expected key=value", index)
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise RuleError("empty key", index)
        if key in BOOL_FIELDS:
            lowered = value.lower()
            if lowered not in {"true", "false"}:
                raise RuleError(f"{key} must be true or false", index)
            data[key] = lowered == "true"
        elif key in INT_FIELDS:
            try:
                data[key] = int(value)
            except ValueError as exc:
                raise RuleError(f"{key} must be an integer", index) from exc
        else:
            data[key] = value
    try:
        return WebMediaRule.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(part) for part in first.get("loc", []))
        message = first.get("msg", str(exc))
        raise RuleError(f"{loc}: {message}" if loc else message) from exc


def format_rule(rule: WebMediaRule) -> str:
    values = rule.model_dump(exclude_none=True)
    lines: list[str] = []
    for key in FIELD_ORDER:
        if key not in values:
            continue
        value = values[key]
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        else:
            rendered = str(value)
        lines.append(f"{key}={rendered}")
    extras = sorted(key for key in values if key not in FIELD_ORDER)
    for key in extras:
        value = values[key]
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        else:
            rendered = str(value)
        lines.append(f"{key}={rendered}")
    return "\n".join(lines) + "\n"

