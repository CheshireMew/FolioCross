"""Recover template structure when importing plain-text Wenyi revisions."""

from __future__ import annotations

import hashlib
from collections import defaultdict, deque
from typing import Any

from bs4 import BeautifulSoup

from ..infrastructure.formats.markers import MARKER_PATTERN, strip_protected_markers


def restore_wenyi_structure(
    segment: dict[str, Any], rows: list[dict[str, Any]], key: str
) -> tuple[str, int]:
    """Use verified legacy link placements and flag proportional fallback positions.

    Legacy placements refer to the final target digest only. Never apply them to
    a pre-polish revision or to text that no longer matches that digest.
    """
    values = [row.get(key) for row in rows]
    if not values or not all(isinstance(value, str) and value.strip() for value in values):
        return "", 0
    target = "".join(values)
    markers = segment.get("markers", [])
    if not markers:
        return target, 0
    links: dict[str, deque[tuple[int, int]]] = defaultdict(deque)
    offset = 0
    for row, value in zip(rows, values):
        annotations = (row.get("meta") or {}).get("epub_annotations") or {}
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        if key == "target" and annotations.get("target_digest") == digest:
            placements = {item.get("id"): item for item in annotations.get("placements", [])}
            for item in annotations.get("items", []):
                placement = placements.get(item.get("id"), {})
                start, end = placement.get("target_start"), placement.get("target_end")
                if (
                    placement.get("status") == "aligned"
                    and isinstance(start, int)
                    and isinstance(end, int)
                    and 0 <= start <= end <= len(value)
                ):
                    links[str(item.get("raw_href", ""))].append((offset + start, offset + end))
        offset += len(value)

    source = segment["source_text"]
    source_length = len(strip_protected_markers(source))
    positions: list[int] = []
    uncertain: set[int] = set()
    stack: list[tuple[int, int | None]] = []
    for index, marker in enumerate(markers):
        token_at = source.find(marker["token"])
        source_offset = len(strip_protected_markers(source[:token_at]))
        position = round(len(target) * source_offset / max(1, source_length))
        if source_offset not in {0, source_length}:
            uncertain.add(index)
        kind = marker.get("kind")
        if kind == "tag_start":
            tag = BeautifulSoup(marker["html"], "html.parser").find()
            href = str(tag.get("href", "")) if tag is not None else ""
            aligned = links[href].popleft() if href and links[href] else None
            if aligned:
                position = aligned[0]
                uncertain.discard(index)
            stack.append((index, aligned[1] if aligned else None))
        elif kind == "tag_end" and stack:
            start_index, end = stack.pop()
            if end is not None:
                position = end
                uncertain.discard(index)
            # Full-container styles inherit their aligned child's range.
            for child in range(start_index + 1, index):
                positions[child] = max(positions[start_index], min(position, positions[child]))
        positions.append(position)

    # Retain the original nesting order even when a legacy placement conflicts
    # with a neighbouring style. Such a conflict still requires review.
    cursor = 0
    chunks: list[str] = []
    for index, (position, marker) in enumerate(zip(positions, markers)):
        if position < cursor:
            uncertain.add(index)
        position = max(cursor, position)
        chunks.extend((target[cursor:position], marker["token"]))
        cursor = position
    chunks.append(target[cursor:])
    restored = "".join(chunks)
    assert MARKER_PATTERN.findall(restored) == [marker["token"] for marker in markers]
    return restored, len(uncertain)
