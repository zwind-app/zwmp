#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Export generated ZWMP rules for self-hosted review or ZWMP-Hub curation.")
    parser.add_argument("--source", default="data/generated-rules", help="Generated rule directory")
    parser.add_argument("--output", default="exports/zwmp-rules", help="Export destination")
    args = parser.parse_args()

    source = Path(args.source)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    manifest = []

    for rule_path in sorted(source.rglob("*.wm")):
        rel = export_relative_path(rule_path, source)
        target = output / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(rule_path, target)
        metadata_path = rule_path.with_suffix(".json")
        if metadata_path.exists():
            shutil.copy2(metadata_path, target.with_suffix(".json"))
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        else:
            metadata = {"id": rule_path.stem}
        manifest.append({"rule": str(rel), "metadata": metadata})

    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"exported {len(manifest)} rules to {output}")


def export_relative_path(rule_path: Path, source: Path) -> Path:
    rel = rule_path.relative_to(source)
    if rel.parts and rel.parts[0] in {"ai", "local"}:
        return rel
    metadata_path = rule_path.with_suffix(".json")
    mode = "local"
    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            mode = "ai" if metadata.get("generation_mode") == "ai" else "local"
        except json.JSONDecodeError:
            mode = "local"
    return Path(mode) / rel


if __name__ == "__main__":
    main()
