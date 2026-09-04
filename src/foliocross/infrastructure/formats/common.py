"""Shared segmentation helpers."""

from __future__ import annotations

from dataclasses import replace

from ...domain.models import ChapterDraft, ParsedBook, SegmentDraft
from .markers import MARKER_PATTERN

SENTENCE_ENDINGS = frozenset("。！？!?；;.")


def _safe_cut(text: str, cursor: int, proposed: int) -> int:
    for match in MARKER_PATTERN.finditer(text):
        if match.start() < proposed < match.end():
            return match.start() if match.start() > cursor else match.end()
    return proposed


def _split_preserving_text(text: str, max_chars: int) -> list[str]:
    """Split without consuming whitespace or cutting a protected marker token."""

    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    cursor = 0
    while len(text) - cursor > max_chars:
        ceiling = min(len(text), cursor + max_chars)
        preferred = 0
        for index in range(cursor, ceiling):
            if text[index] not in SENTENCE_ENDINGS:
                continue
            boundary = index + 1
            while boundary < ceiling and text[boundary].isspace():
                boundary += 1
            if boundary - cursor >= max(1, max_chars // 2):
                preferred = boundary
        cut = _safe_cut(text, cursor, preferred or ceiling)
        if cut <= cursor:
            cut = _safe_cut(text, cursor, ceiling)
        if cut <= cursor:
            cut = min(len(text), cursor + max_chars)
        chunks.append(text[cursor:cut])
        cursor = cut
    if cursor < len(text):
        chunks.append(text[cursor:])
    return chunks


def _markers_for_chunk(chunk: str, markers: list[dict]) -> list[dict]:
    result = []
    for marker in markers:
        token = str(marker["token"])
        offset = chunk.find(token)
        if offset < 0:
            continue
        local = dict(marker)
        local["source_offset"] = len(MARKER_PATTERN.sub("", chunk[:offset]))
        result.append(local)
    return result


def split_long_segments(book: ParsedBook, max_chars: int) -> ParsedBook:
    chapters: list[ChapterDraft] = []
    for chapter in book.chapters:
        segments: list[SegmentDraft] = []
        for segment in chapter.segments:
            if len(segment.source_text) <= max_chars:
                locator = dict(segment.locator)
                locator.setdefault("logical_part", 0)
                locator.setdefault("logical_parts", 1)
                segments.append(replace(segment, locator=locator))
                continue
            chunks = _split_preserving_text(segment.source_text, max_chars)
            logical_id = f"{segment.locator.get('resource', '')}:{segment.locator.get('ordinal', len(segments))}"
            for part, chunk in enumerate(chunks):
                locator = dict(segment.locator)
                locator.update(
                    {"logical_id": logical_id, "logical_part": part, "logical_parts": len(chunks)}
                )
                segments.append(
                    SegmentDraft(
                        chunk,
                        locator=locator,
                        markers=_markers_for_chunk(chunk, segment.markers),
                    )
                )
        chapters.append(ChapterDraft(chapter.title, segments, dict(chapter.locator)))
    return replace(book, chapters=chapters)


def batches(segments: list[dict], max_chars: int) -> list[list[dict]]:
    result: list[list[dict]] = []
    current: list[dict] = []
    size = 0
    for segment in segments:
        length = len(segment["source_text"])
        if current and size + length > max_chars:
            result.append(current)
            current = []
            size = 0
        current.append(segment)
        size += length
    if current:
        result.append(current)
    return result
