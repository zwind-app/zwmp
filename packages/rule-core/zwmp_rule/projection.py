from __future__ import annotations

import re

from .types import Projection, ProjectionItem, ProjectionMedia, ProjectionNode


def safe_name(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|]+", "-", value).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:100] or fallback


def build_projection_tree(
    projection: str | Projection,
    items: list[ProjectionItem],
    media: list[ProjectionMedia],
) -> list[ProjectionNode]:
    mode = Projection(projection)
    media_by_item: dict[str, list[ProjectionMedia]] = {}
    for entry in media:
        media_by_item.setdefault(entry.item_id, []).append(entry)

    root: list[ProjectionNode] = []
    if mode == Projection.FLAT:
        for item in items:
            for index, entry in enumerate(media_by_item.get(item.id, []), start=1):
                ext = entry.extension or "url"
                suffix = "" if index == 1 else f"-{index}"
                root.append(
                    ProjectionNode(
                        id=f"node-{entry.id}",
                        name=f"{safe_name(item.title, item.id)}{suffix}.{ext}",
                        kind="file",
                        item_id=item.id,
                        media_id=entry.id,
                    )
                )
        return root

    for item in items:
        children = []
        for index, entry in enumerate(media_by_item.get(item.id, []), start=1):
            ext = entry.extension or "url"
            name = f"{safe_name(item.title, item.id)}.{ext}" if index == 1 else f"{safe_name(item.title, item.id)}-{index}.{ext}"
            children.append(
                ProjectionNode(
                    id=f"node-{entry.id}",
                    name=name,
                    kind="file",
                    item_id=item.id,
                    media_id=entry.id,
                )
            )
        if not children:
            children.append(
                ProjectionNode(
                    id=f"{item.id}-pending",
                    name="Media not found yet",
                    kind="file",
                    item_id=item.id,
                )
            )
        root.append(
            ProjectionNode(
                id=f"dir-{item.id}",
                name=safe_name(item.title, item.id),
                kind="directory",
                item_id=item.id,
                children=children,
            )
        )
    return root
